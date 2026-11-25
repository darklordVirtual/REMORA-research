# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""PolicyDecisionToken v3: a redeemer that can verify grants and mint none (RMR-CR-002).

The security review found the decision token minted and consumed under one
shared HMAC key: any code able to verify a grant could also mint one, so the
signature drew no line between decision and enforcement. Format v3 signs with
Ed25519 in its own domain. The regression the finding asked for is the first
test here: a grant issued by anyone who is not the PDP is refused by a PEP that
holds only verification material, whatever the forger holds instead.

The rest pins what makes that true: the redeemer cannot mint (not even an
unsigned token), HMAC grants are refused once asymmetric material exists unless
a migration window is opened on purpose, the key id is derived and revocable,
and a configured key that cannot be decoded refuses rather than crashing.
"""
from __future__ import annotations

import base64
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from remora.crypto import SignatureDomain, SigningKey, derive_kid, sign  # noqa: E402
from remora.enforcement.gate import EnforcementGate  # noqa: E402
from remora.enforcement.token import (  # noqa: E402
    FORMAT_V3,
    GrantMintingRefused,
    PolicyDecisionToken,
    TokenVerificationResult,
    asymmetric_configured,
    hmac_accepted,
    verify_only,
)

ROOT = Path(__file__).resolve().parents[1]
PDP = SigningKey.generate({SignatureDomain.POLICY_GRANT_ASYMMETRIC})
FORGER = SigningKey.generate({SignatureDomain.POLICY_GRANT_ASYMMETRIC})
OBS = "e" * 64

#: Environment names this module sets or clears. One per line: a secret scanner
#: reads two adjacent quoted names as a key and its value.
_ENVS = (
    "REMORA_PDP_SIGNING_KEY",
    "REMORA_PDP_SIGNING_KID",
    "REMORA_PDP_PREVIOUS_KEYS",
    "REMORA_PDP_REVOKED_KIDS",
    "REMORA_PDP_ISSUER",
    "REMORA_PDP_ACCEPT_HMAC",
    "REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE",
    "REMORA_PDP_VERIFY_KEYS_ED25519",
    "REMORA_SIGNATURE_FORMAT",
    "REMORA_RUNTIME_PROFILE",
    "REMORA_RUNTIME_PROFILE_CONTRACT",
)


def _seed(key: SigningKey) -> str:
    return key.seed.hex()


def _public(key: SigningKey) -> str:
    return key.verification_key().public_bytes.hex()


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _as_pdp(mp: pytest.MonkeyPatch, key: SigningKey = PDP) -> None:
    mp.delenv("REMORA_PDP_VERIFY_KEYS_ED25519", raising=False)
    mp.setenv("REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE", _seed(key))


def _as_redeemer(mp: pytest.MonkeyPatch, *keys: SigningKey) -> None:
    mp.delenv("REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE", raising=False)
    mp.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", ",".join(_public(k) for k in (keys or (PDP,))))


def _issue(**kw) -> PolicyDecisionToken:
    now = datetime.now(UTC)
    return PolicyDecisionToken.issue(
        action=kw.pop("action", "accept"), observation_hash=OBS, request_id="req-1",
        issued_at=now.isoformat(), expires_at=(now + timedelta(seconds=120)).isoformat(),
        audience="pep://remora-execution", **kw)


# ── the regression the finding asked for ───────────────────────────────────

def test_a_grant_minted_by_anyone_but_the_pdp_is_refused_by_a_verify_only_pep(
        _clean: pytest.MonkeyPatch) -> None:
    """Three forgers, one redeemer that holds only the PDP's public key."""
    _as_pdp(_clean, FORGER)
    own_key = _issue()
    _clean.delenv("REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE")
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "a-guessed-or-stolen-hmac-key")
    hmac_grant = _issue()

    _as_redeemer(_clean)
    _clean.delenv("REMORA_PDP_SIGNING_KEY")
    gate = EnforcementGate(strict=True)
    # 1. A key of its own: the derived kid names a key the PEP does not trust.
    assert gate.check(own_key).reason == "token_verification_failed:unknown_kid"
    # 2. The same key, relabelled with the PDP's kid: the signature does not hold.
    relabelled = dataclasses.replace(own_key, kid=PDP.kid)
    assert gate.check(relabelled).reason == "token_verification_failed:signature_invalid"
    # 3. A symmetric grant: refused before any HMAC key is consulted.
    assert hmac_grant.format != FORMAT_V3
    assert gate.check(hmac_grant).reason == "token_verification_failed:token_hmac_refused"


def test_the_pdps_grant_is_redeemed_once_by_the_verify_only_pep(
        _clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    grant = _issue()
    assert grant.format == FORMAT_V3 and grant.kid == PDP.kid

    _as_redeemer(_clean)
    gate = EnforcementGate(strict=True)
    first = gate.check(grant, OBS, consume=True)
    assert (first.allowed, first.reason) == (True, "accept")
    assert gate.check(grant, OBS, consume=True).reason == "token_already_consumed"


def test_a_verify_only_process_cannot_mint_even_an_unsigned_grant(
        _clean: pytest.MonkeyPatch) -> None:
    """An unsigned token from the redeemer would be the forgery, merely labelled honestly."""
    _as_redeemer(_clean)
    assert verify_only() is True
    with pytest.raises(GrantMintingRefused, match="cannot mint"):
        _issue()
    # Holding an HMAC key as well does not reopen minting on a redeemer.
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "k")
    with pytest.raises(GrantMintingRefused):
        _issue()


def test_custody_status_is_derived_from_what_the_process_holds(
        _clean: pytest.MonkeyPatch) -> None:
    assert (asymmetric_configured(), verify_only(), hmac_accepted()) == (False, False, True)
    _as_pdp(_clean)
    assert (asymmetric_configured(), verify_only(), hmac_accepted()) == (True, False, False)
    _as_redeemer(_clean)
    assert (asymmetric_configured(), verify_only(), hmac_accepted()) == (True, True, False)


# ── what is signed ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("field, value", [
    ("action", "reject"), ("observation_hash", "f" * 64), ("request_id", "req-2"),
    ("audience", "pep://elsewhere"), ("issuer", "pdp-2"), ("context_hash", "c" * 64),
    ("jti", "another-jti"), ("expires_at", "2099-01-01T00:00:00+00:00"),
])
def test_every_signed_field_is_bound(_clean: pytest.MonkeyPatch, field: str, value: str) -> None:
    _as_pdp(_clean)
    grant = _issue()
    _as_redeemer(_clean)
    assert dataclasses.replace(grant, **{field: value}).verify().reason == "signature_invalid"


def test_the_format_cannot_be_relabelled_to_reach_a_weaker_check(
        _clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    grant = _issue()
    _as_redeemer(_clean)
    for weaker in ("v2", ""):
        assert dataclasses.replace(grant, format=weaker).verify().reason == "token_hmac_refused"
    assert dataclasses.replace(grant, format="v9").verify().reason == "token_format_unknown"


def test_a_signature_from_another_domain_does_not_verify(_clean: pytest.MonkeyPatch) -> None:
    """Same seed, same payload bytes, the lease domain: refused."""
    from remora.enforcement.token import _canonical_payload

    _as_pdp(_clean)
    grant = _issue()
    both = SigningKey(PDP.seed, frozenset({SignatureDomain.EXECUTION_LEASE}))
    payload = _canonical_payload(
        grant.action, grant.observation_hash, grant.request_id, grant.issued_at,
        grant.expires_at, grant.jti, grant.audience, grant.kid, grant.issuer,
        grant.context_hash, grant.format)
    lease_sig = sign(SignatureDomain.EXECUTION_LEASE, payload, both).value
    _as_redeemer(_clean)
    assert dataclasses.replace(grant, signature=lease_sig).verify().reason == "signature_invalid"


def test_the_key_id_is_derived_from_the_public_key(_clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    assert _issue().kid == derive_kid(PDP.verification_key().public_bytes)


def test_a_v3_grant_round_trips_through_its_wire_form(_clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    grant = _issue()
    wire = grant.to_dict()
    assert wire["format"] == FORMAT_V3
    back = PolicyDecisionToken.from_dict(json.loads(json.dumps(wire)))
    _as_redeemer(_clean)
    assert back == grant and back.verify(OBS).reason == "ok"


# ── rotation, revocation, unusable material ────────────────────────────────

def test_rotation_keeps_grants_from_the_previous_key_redeemable(
        _clean: pytest.MonkeyPatch) -> None:
    old = SigningKey.generate({SignatureDomain.POLICY_GRANT_ASYMMETRIC})
    _as_pdp(_clean, old)
    from_old = _issue()
    _as_pdp(_clean, PDP)
    from_new = _issue()
    _as_redeemer(_clean, PDP, old)
    assert from_old.verify().reason == "ok"
    assert from_new.verify().reason == "ok"


def test_a_revoked_derived_kid_refuses_live_and_stays_readable_as_history(
        _clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    grant = _issue()
    _as_redeemer(_clean)
    _clean.setenv("REMORA_PDP_REVOKED_KIDS", f"unrelated, {PDP.kid}")
    assert grant.verify().reason == "kid_revoked"
    assert grant.verify_historical().reason == "ok"



def test_a_v3_grant_needs_verification_material(_clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    grant = _issue()
    _clean.delenv("REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE")
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "only-hmac-here")
    assert grant.verify().reason == "no_verification_key"


def test_an_undecodable_verify_key_refuses_instead_of_crashing_the_gate(
        _clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    grant = _issue()
    _as_redeemer(_clean)
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", "not-a-key")
    assert grant.verify().reason == "verification_key_unusable"
    assert EnforcementGate(strict=True).check(grant).allowed is False


def test_an_unsigned_v3_token_is_not_signed(_clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    grant = _issue()
    _as_redeemer(_clean)
    for stripped in (dataclasses.replace(grant, signature=""),
                     dataclasses.replace(grant, is_signed=False)):
        assert stripped.verify().reason == "token_not_signed"


# ── the HMAC migration window ──────────────────────────────────────────────

def test_hmac_grants_need_an_explicit_window_once_asymmetric_material_exists(
        _clean: pytest.MonkeyPatch) -> None:
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "shared")
    legacy = _issue()
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", _public(PDP))
    assert legacy.verify().reason == "token_hmac_refused"
    _clean.setenv("REMORA_PDP_ACCEPT_HMAC", "1")
    assert legacy.verify().reason == "ok"
    _clean.setenv("REMORA_PDP_ACCEPT_HMAC", "0")
    assert legacy.verify().reason == "token_hmac_refused"


def test_without_asymmetric_material_hmac_behaves_as_before(_clean: pytest.MonkeyPatch) -> None:
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "shared")
    grant = _issue()
    assert grant.format in ("", "v2")
    assert grant.verify().reason == "ok"


def test_historical_reading_of_an_hmac_grant_ignores_the_window(
        _clean: pytest.MonkeyPatch) -> None:
    """Evidence stays readable; only live authority is refused."""
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "shared")
    legacy = _issue()
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", _public(PDP))
    assert legacy.verify_historical().verified is True


def test_a_strict_v2_contract_accepts_a_v3_grant_as_live_authority(
        _clean: pytest.MonkeyPatch) -> None:
    _clean.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    _as_pdp(_clean)
    grant = _issue()
    assert grant.format == FORMAT_V3
    _as_redeemer(_clean)
    assert grant.verify().reason == "ok"


# ── the custody split and the golden vector ────────────────────────────────

def test_the_executor_domain_may_not_hold_the_pdp_seed(_clean: pytest.MonkeyPatch) -> None:
    from remora.enforcement.custody import CustodyViolation, assert_custody_split

    _clean.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    _clean.setenv("REMORA_EFFECT_CREDENTIAL_ENV_NAMES", "PROVIDER_API_KEY")
    _clean.setenv("REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE", _seed(PDP))
    with pytest.raises(CustodyViolation, match="REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE"):
        assert_custody_split(strict=True)


def test_the_v3_vector_verifies_with_the_production_code(_clean: pytest.MonkeyPatch) -> None:
    from remora.crypto import preimage
    from remora.enforcement.token import _canonical_payload

    vector = json.loads((ROOT / "vectors" / "v3" / "policy_grant.json").read_text(encoding="utf-8"))
    (case,) = vector["cases"]
    fields = json.loads(case["payload"])
    grant = PolicyDecisionToken(**{k: fields.get(k) for k in (
        "action", "observation_hash", "request_id", "issued_at", "expires_at", "jti",
        "audience", "kid", "issuer", "context_hash", "format")},
        signature=case["signature"], is_signed=True)
    payload = _canonical_payload(
        grant.action, grant.observation_hash, grant.request_id, grant.issued_at,
        grant.expires_at, grant.jti, grant.audience, grant.kid, grant.issuer,
        grant.context_hash, grant.format)
    assert payload.decode() == case["payload"]
    assert base64.b64decode(case["preimage_b64"]) == preimage(
        SignatureDomain.POLICY_GRANT_ASYMMETRIC, payload)
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", vector["keys"]["ed25519_public_hex"])
    assert grant.verify_historical().reason == "ok"
    from remora.sdk import evidence

    public = vector["keys"]["ed25519_public_hex"]
    assert evidence.verify_grant_signature(grant.to_dict(), public_key=public)
    assert not evidence.verify_grant_signature({**grant.to_dict(), "action": "altered"}, public_key=public)
    assert not evidence.verify_grant_signature(grant.to_dict(), public_key="00" * 32)


# ── the split on the API ───────────────────────────────────────────────────

def _api_client(mp: pytest.MonkeyPatch, tmp_path: Path):
    """The execute-accepted fixture's setup, without its HMAC key."""
    from fastapi.testclient import TestClient

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from remora.governance.tenant_chain import TenantAuditChain

    mp.setenv("REMORA_ENV", "development")
    mp.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    mp.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    mp.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    mp.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    mp.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    mp.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    return TestClient(api_mod.app)


def _issue_in_separate_process(send, root):
    from tests.test_execute_accepted import _mint_token

    with pytest.MonkeyPatch.context() as patch:
        key = SigningKey.generate({SignatureDomain.POLICY_GRANT_ASYMMETRIC})
        _as_pdp(patch, key)
        client = _api_client(patch, root)
        send.send((_public(key), _mint_token(client)))
    send.close()


def test_a_redeemer_replica_executes_a_grant_the_pdp_replica_minted(
        _clean: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Two custody domains on the real routes: the PDP mints, the redeemer
    (verify keys only, no grant-minting material at all) honours it once."""
    pytest.importorskip("fastapi")
    import tests.test_execute_accepted as accepted

    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    issuer = ctx.Process(target=_issue_in_separate_process, args=(send, tmp_path / "issuer"))
    issuer.start()
    send.close()
    try:
        assert recv.poll(30), "issuer did not return a grant"
        public, token = recv.recv()
    finally:
        recv.close()
        issuer.join(10)
        if issuer.is_alive():
            issuer.kill()
            issuer.join()
    assert issuer.exitcode == 0
    assert token["format"] == FORMAT_V3
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", public)
    _clean.setenv("REMORA_LEASE_SIGNING_KEY", "lease-key-held-by-the-redeemer")
    client = _api_client(_clean, tmp_path / "redeemer")
    assert verify_only() is True
    first = client.post("/v1/execution/execute-accepted",
                        json={"execution_token": token, "tool_call": accepted.READ_CALL})
    assert first.status_code == 200, first.text
    assert first.json()["tool_execution"]["executed"] is True
    again = client.post("/v1/execution/execute-accepted",
                        json={"execution_token": token, "tool_call": accepted.READ_CALL})
    assert again.status_code != 200


def test_a_flow_that_mints_refuses_on_a_redeemer_before_it_claims_anything(
        _clean: pytest.MonkeyPatch) -> None:
    from remora.execution.service import _refuse_minting_on_a_redeemer

    _refuse_minting_on_a_redeemer()  # no material at all: unchanged behaviour
    _as_pdp(_clean)
    _refuse_minting_on_a_redeemer()
    _as_redeemer(_clean)
    with pytest.raises(GrantMintingRefused, match="route this request to the PDP"):
        _refuse_minting_on_a_redeemer()


def test_the_api_answers_a_misrouted_mint_with_503_not_a_crash() -> None:
    pytest.importorskip("fastapi")
    import asyncio

    import servers.api as api_mod

    handler = api_mod.app.exception_handlers[GrantMintingRefused]
    response = asyncio.run(handler(None, GrantMintingRefused("x"))) if asyncio.iscoroutinefunction(
        handler) else handler(None, GrantMintingRefused("x"))
    assert response.status_code == 503
    assert json.loads(response.body)["detail"].startswith("grant_minting_refused:")


# ── whole results (mutation sweep 2026-10-13) ──────────────────────────────

def _refusal(reason: str, *, signed: bool = True) -> TokenVerificationResult:
    return TokenVerificationResult(verified=False, reason=reason, is_signed=signed)


def test_every_v3_refusal_is_a_whole_result(_clean: pytest.MonkeyPatch) -> None:
    """``verified`` and ``is_signed`` are part of the verdict: a refusal that
    reported a stripped signature as signed, or a missing key as verified,
    would mislead the gate's audit even with the right reason code."""
    _as_pdp(_clean)
    grant = _issue()
    _as_redeemer(_clean)
    assert dataclasses.replace(grant, signature="").verify() == _refusal(
        "token_not_signed", signed=False)
    assert dataclasses.replace(grant, request_id="other").verify() == _refusal("signature_invalid")
    _clean.setenv("REMORA_PDP_REVOKED_KIDS", PDP.kid)
    assert grant.verify() == _refusal("kid_revoked")
    _clean.delenv("REMORA_PDP_REVOKED_KIDS")
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", "not-a-key")
    assert grant.verify() == _refusal("verification_key_unusable")
    _clean.delenv("REMORA_PDP_VERIFY_KEYS_ED25519")
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "only-hmac")
    assert grant.verify() == _refusal("no_verification_key")


def test_an_hmac_refusal_is_a_whole_result(_clean: pytest.MonkeyPatch) -> None:
    _clean.setenv("REMORA_PDP_SIGNING_KEY", "shared")
    legacy = _issue()
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", _public(PDP))
    assert legacy.verify() == _refusal("token_hmac_refused")


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes", "on", "ON"])
def test_every_documented_spelling_opens_the_hmac_window(
        _clean: pytest.MonkeyPatch, value: str) -> None:
    _clean.setenv("REMORA_PDP_VERIFY_KEYS_ED25519", _public(PDP))
    _clean.setenv("REMORA_PDP_ACCEPT_HMAC", value)
    assert hmac_accepted() is True


def test_a_pdp_holding_only_its_seed_verifies_what_it_minted(
        _clean: pytest.MonkeyPatch) -> None:
    _as_pdp(_clean)
    assert _issue().verify(OBS).reason == "ok"


def test_the_minting_refusal_names_the_material_it_found(_clean: pytest.MonkeyPatch) -> None:
    _as_redeemer(_clean)
    with pytest.raises(GrantMintingRefused,
                       match=r"^this process holds only REMORA_PDP_VERIFY_KEYS_ED25519: it redeems "):
        _issue()


def test_the_issuer_is_signed_into_a_v3_grant(_clean: pytest.MonkeyPatch) -> None:
    _clean.setenv("REMORA_PDP_ISSUER", "pdp-1")
    _as_pdp(_clean)
    grant = _issue()
    assert grant.issuer == "pdp-1"
    _as_redeemer(_clean)
    assert grant.verify().reason == "ok"
    assert dataclasses.replace(grant, issuer="pdp-2").verify().reason in (
        "issuer_mismatch", "signature_invalid")
