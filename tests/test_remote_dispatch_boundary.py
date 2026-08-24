# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The authority/execution hop: what it must and must not carry (ADR-A).

`test_custody_split_dispatch.py` establishes that a verifier-only executor can
dispatch a lease it could not have minted. This file covers the crossing itself,
which is new attack surface: a network hop that a lease now travels over.

Three properties, each with a way to get it wrong:

1. The hop is only taken by the AUTHORITY. A process holding a presented lease
   is already the executor; forwarding again would loop, and worse, would let a
   compromised executor use its own endpoint configuration to bounce a lease
   somewhere else.
2. Failure to reach the executor is never reported as "did not execute". The
   request may have arrived, spent the nonce and caused the effect, with only
   the answer lost. Reporting that as a clean refusal invites a retry of a side
   effect that already happened.
3. A 4xx from the executor is its VERDICT, not an outage. An operator reading
   the chain needs to tell "the executor refused this lease" from "the executor
   was unreachable", because only one of them is an incident.
"""
from __future__ import annotations

import json
import sys
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _security_extra import require_security_extra  # noqa: E402

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.enforcement.lease import GovernedToolDispatcher  # noqa: E402
from remora.enforcement.nonce_store import InMemoryNonceStore  # noqa: E402
from remora.execution import remote_dispatch as rd  # noqa: E402
from remora.execution.dispatch import dispatch_under_lease  # noqa: E402

# Skips locally without the 'security' extra; fails hard in CI, where a skip
# would silently withhold this file's evidence. See _security_extra for why.
require_security_extra()

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

NOW = datetime.now(UTC)
BUNDLE = "bundle-1"
SEMANTIC = {"tool_contract_bundle_hash": "tc-1", "intent_authority_hash": "ia-1"}
ENDPOINT = "http://execution.internal"


def _call():
    return SimpleNamespace(tool_name="wo_close", arguments={"id": "WO-1"},
                           target_environment="staging")


@pytest.fixture()
def authority(monkeypatch):
    """A process holding the private key and an execution endpoint."""
    k = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, k.private_bytes_raw().hex())
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC,
                       k.public_key().public_bytes_raw().hex())
    monkeypatch.delenv(signing.ENV_HMAC, raising=False)
    monkeypatch.delenv(signing.ENV_HMAC_FALLBACK, raising=False)
    monkeypatch.setenv(rd.ENDPOINT_ENV, ENDPOINT)


def _dispatch(dispatcher=None, presented=None):
    return dispatch_under_lease(
        tenant="acme", principal="agent-1", tool_call=_call(),
        semantic=SEMANTIC, now=NOW, dispatcher=dispatcher,
        policy_bundle_hash=BUNDLE, proposal_id="prop-1",
        presented_lease=presented)


# ── 1. the hop is the authority's, and only the authority's ────────────────

def test_the_authority_forwards_to_the_execution_domain(monkeypatch, authority):
    """The lease is minted here and executed there."""
    sent: list = []

    def capture(url, payload, timeout):
        sent.append((url, payload))
        return {"tool_execution": {"executed": True, "result": "closed"}}

    monkeypatch.setattr(rd, "_post", capture)

    # No dispatcher: the authority domain holds no tool callables and must not
    # need any. If this raised policy_bundle_unavailable, the split would
    # require every authority to also be an executor.
    result = _dispatch(dispatcher=None)
    assert result["executed"] is True

    url, payload = sent[0]
    assert url.endswith("/v1/execution/dispatch-leased")
    assert payload["lease"]["sig_alg"] == signing.ALG_ED25519
    assert payload["tool_call"]["arguments"] == {"id": "WO-1"}
    assert payload["tenant_id"] == "acme"


def test_a_presented_lease_is_never_forwarded_again(monkeypatch, authority):
    """The executor must not bounce a lease onward.

    Without this, a compromised executor could point REMORA_EXECUTION_ENDPOINT
    at something it controls and have leases delivered there. The check is
    structural: presented_lease means "I am the executor", and the hop is
    skipped regardless of configuration.
    """
    forwarded: list = []
    monkeypatch.setattr(rd, "_post",
                        lambda *a, **k: forwarded.append(a) or {})

    calls: list = []
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash=BUNDLE, nonce_store=InMemoryNonceStore())
    dispatcher.register("wo_close", lambda args: calls.append(args) or "ok")

    from remora.execution.dispatch import issue_execution_lease
    lease = issue_execution_lease(
        tenant="acme", principal="agent-1", tool_call=_call(),
        semantic=SEMANTIC, now=NOW, policy_bundle_hash=BUNDLE)

    result = _dispatch(dispatcher=dispatcher, presented=lease)
    assert result["executed"] is True
    assert forwarded == [], "a presented lease must be executed here, not relayed"
    assert calls == [{"id": "WO-1"}]


def test_without_an_endpoint_dispatch_stays_local(monkeypatch):
    """A deployment that has not split custody is unaffected.

    This is the compatibility guarantee: absent REMORA_EXECUTION_ENDPOINT, the
    behaviour is exactly what it was before the split existed.
    """
    monkeypatch.delenv(rd.ENDPOINT_ENV, raising=False)
    monkeypatch.setenv(signing.ENV_HMAC, "local-key")

    calls: list = []
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash=BUNDLE, nonce_store=InMemoryNonceStore())
    dispatcher.register("wo_close", lambda args: calls.append(args) or "ok")

    assert _dispatch(dispatcher=dispatcher)["executed"] is True
    assert calls == [{"id": "WO-1"}]


# ── 2. unreachable is unknown, not "did not happen" ────────────────────────

def test_an_unreachable_executor_reports_unknown_state(monkeypatch, authority):
    """The effect may have happened. Saying otherwise invites a double effect."""
    def unreachable(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(rd, "_post", unreachable)

    result = _dispatch(dispatcher=None)
    assert result["executed"] is False
    assert result["refusal_reason"] == "execution_domain_unreachable"
    assert result["state_unknown"] is True, (
        "an unreachable executor must not be reported as a clean refusal")


def test_a_lost_answer_reports_unknown_state(monkeypatch, authority):
    """Sent, executed, answer lost. The worst case, and it must be visible."""
    monkeypatch.setattr(rd, "_post", lambda *a, **k: (_ for _ in ()).throw(
        TimeoutError("read timed out")))
    result = _dispatch(dispatcher=None)
    assert result["state_unknown"] is True


def test_an_unparseable_answer_is_not_an_execution(monkeypatch, authority):
    """Refusing to infer. A missing tool_execution is not a success."""
    monkeypatch.setattr(rd, "_post", lambda *a, **k: {"something": "else"})
    result = _dispatch(dispatcher=None)
    assert result["executed"] is False
    assert result["state_unknown"] is True


def test_malformed_json_is_unknown_state(monkeypatch, authority):
    monkeypatch.setattr(rd, "_post", lambda *a, **k: (_ for _ in ()).throw(
        json.JSONDecodeError("bad", "", 0)))
    assert _dispatch(dispatcher=None)["state_unknown"] is True


# ── 3. a refusal is a verdict, an outage is not ────────────────────────────

def test_a_4xx_is_reported_as_the_executors_refusal(monkeypatch, authority):
    """The executor looked at the lease and said no. That is not an incident."""
    def refused(*_a, **_k):
        raise urllib.error.HTTPError(
            ENDPOINT, 409, "Conflict", {},  # type: ignore[arg-type]
            None)

    monkeypatch.setattr(rd, "_post", refused)
    result = _dispatch(dispatcher=None)
    assert result["executed"] is False
    assert result["refusal_reason"] == "execution_domain_refused"
    assert result.get("state_unknown") is not True, (
        "a refusal means nothing ran; it must not be conflated with unknown")


def test_a_5xx_is_reported_as_unknown_state(monkeypatch, authority):
    """The executor broke mid-request. Whether it ran first is not knowable."""
    def broke(*_a, **_k):
        raise urllib.error.HTTPError(
            ENDPOINT, 502, "Bad Gateway", {},  # type: ignore[arg-type]
            None)

    monkeypatch.setattr(rd, "_post", broke)
    assert _dispatch(dispatcher=None)["state_unknown"] is True


def test_the_executors_refusal_reason_is_carried_through(monkeypatch, authority):
    """A refusal decided at the executor must reach the audit chain intact."""
    monkeypatch.setattr(rd, "_post", lambda *a, **k: {
        "tool_execution": {"executed": False,
                           "refusal_reason": "nonce_already_consumed"}})
    result = _dispatch(dispatcher=None)
    assert result["refusal_reason"] == "nonce_already_consumed"


# ── the transport token is not an authority credential ─────────────────────

def test_the_transport_token_is_sent_but_is_not_authority(monkeypatch, authority):
    """Holding the hop token lets you ask; it does not let you forge.

    Recorded because a shared bearer on an internal hop looks like a
    credential that matters. It authenticates the transport. The executor still
    verifies the lease against a public key it holds and the call it was given,
    so a caller with this token and no private key can ask for nothing it could
    not already ask for.
    """
    seen: dict = {}

    def capture(url, payload, timeout):
        import os
        seen["token"] = os.environ.get(rd.TOKEN_ENV, "")
        return {"tool_execution": {"executed": True}}

    monkeypatch.setenv(rd.TOKEN_ENV, "internal-hop-token")
    monkeypatch.setattr(rd, "_post", capture)

    assert _dispatch(dispatcher=None)["executed"] is True
    assert seen["token"] == "internal-hop-token"


# ── the missing-dependency path, found in deployment ───────────────────────

def test_missing_crypto_is_a_named_refusal_not_a_server_error(monkeypatch,
                                                              authority):
    """A live 500, pinned as a refusal.

    The deployed image installed .[api,postgres] without [security], so
    `cryptography` was absent, `_ed25519()` raised SigningUnavailable, and
    dispatch_under_lease -- which caught only (LeaseRefused, ValueError) --
    let it escape as an unhandled 500. The gateway reported
    "An internal error occurred" with no reason in the audit chain.

    Failing loudly when the crypto library is missing is correct: falling back
    to HMAC would restore the custody defect. Failing as a server error is not.
    """
    monkeypatch.setattr(signing, "_ed25519", lambda: (_ for _ in ()).throw(
        signing.SigningUnavailable("cryptography is not installed")))
    monkeypatch.setattr(rd, "_post", lambda *a, **k: {
        "tool_execution": {"executed": True}})

    result = _dispatch(dispatcher=None)
    assert result["executed"] is False
    assert result["refusal_reason"].startswith("lease_unavailable")
    assert "cryptography" in result["refusal_reason"]


def test_the_deployed_image_installs_the_security_extra():
    """The other half of the same defect.

    A named refusal is better than a 500, but a deployment whose every call
    refuses is still broken. The image must carry the extra that the Ed25519
    path needs, and that is a Dockerfile fact rather than a Python one.
    """
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[1]
                  / "deploy" / "ot-pilot" / "Dockerfile").read_text()
    install = [ln for ln in dockerfile.splitlines() if "pip install -e" in ln]
    assert install, "no editable install line found in the image"
    assert "security" in install[0], (
        "the image must install the 'security' extra or Ed25519 lease signing "
        "raises SigningUnavailable on every call")
