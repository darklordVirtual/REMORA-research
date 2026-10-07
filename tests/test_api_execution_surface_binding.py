# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CR-006 (A1): the runtime-surface binding is active on the API path.

Before: the dispatcher could compare the surface a lease was granted under
with the surface at dispatch (Q3.2), but on the API path no lease carried a
surface digest and no observer was bound, so the binding was inert; and a
lease without a digest was never checked, even enforced.

After: every lease the API mints signs the signed execution surface (bundle
digest plus each spec's tool id and hash); the dispatcher observes the
surface it actually offers (its registered tools, each with its spec hash or
``unsigned``). Under a strict profile a difference refuses as
``surface_changed``, and a lease naming no surface as ``surface_unbound``.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest

pytest.importorskip("cryptography")

from remora.crypto import SignatureDomain, SigningKey  # noqa: E402
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher  # noqa: E402
from remora.execution.execution_surface import (  # noqa: E402
    observed_surface_digest,
    signed_surface_digest,
)
from remora.scaffold import _demo_spec  # noqa: E402
from remora.toolcall.toolspec import ToolSpecBundle  # noqa: E402
from remora.toolcall.toolspec_sign import sign_with_seed  # noqa: E402

ARGS = {"id": "WO-1"}


def _bundle(*tool_ids: str) -> ToolSpecBundle:
    key = SigningKey.generate([SignatureDomain.TOOLSPEC_BUNDLE])
    specs = [dict(_demo_spec("sha256:" + "0" * 64), tool_id=t) for t in tool_ids]
    signed, _, _ = sign_with_seed({"schema_version": 3, "tool_specs": specs},
                                  key.seed.hex(), signed_at="2026-10-07T00:00:00+00:00")
    return ToolSpecBundle.load(signed, verification_keys=[key.verification_key()],
                               accept_hmac=False)


# -- the surface definition -----------------------------------------------------

def test_the_observed_surface_equals_the_signed_one_only_for_exactly_the_signed_tools() -> None:
    bundle = _bundle("wo_close", "wo_read")
    signed = signed_surface_digest(bundle)
    assert observed_surface_digest(bundle, ["wo_read", "wo_close"]) == signed
    assert observed_surface_digest(bundle, ["wo_close"]) != signed           # one missing
    assert observed_surface_digest(bundle, ["wo_close", "wo_read", "shell"]) != signed  # one unsigned


def test_the_surface_moves_with_any_spec() -> None:
    a, b = _bundle("wo_close"), _bundle("wo_close", "wo_read")
    assert signed_surface_digest(a) != signed_surface_digest(b)


# -- enforcement at the dispatcher ----------------------------------------------

@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "surface-a1-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _executor(bundle, *tools):
    dispatcher = GovernedToolDispatcher("b1")
    for name in tools:
        dispatcher.register(name, lambda args: "ok")
    dispatcher.bind_surface_observer(
        lambda: observed_surface_digest(bundle, dispatcher.registered_tool_names()),
        enforce=True, require_digest=True)
    return dispatcher


def _lease(surface: str) -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1", tool_name="wo_close",
        arguments=ARGS, target_environment="prod", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat(), surface_digest=surface)


def _run(dispatcher, lease):
    return dispatcher.dispatch(lease, "wo_close", ARGS, tenant_id="acme",
                               target_environment="prod", actor_identity="agent-1")


def test_an_executor_running_exactly_the_signed_surface_executes() -> None:
    bundle = _bundle("wo_close")
    result = _run(_executor(bundle, "wo_close"), _lease(signed_surface_digest(bundle)))
    assert result.executed, result.refusal_reason


def test_an_unsigned_tool_on_the_executor_refuses_every_dispatch() -> None:
    """An alternative execution path the signed contract does not describe."""
    bundle = _bundle("wo_close")
    result = _run(_executor(bundle, "wo_close", "shell_exec"), _lease(signed_surface_digest(bundle)))
    assert (result.executed, result.refusal_reason) == (False, "surface_changed")


def test_a_lease_naming_no_surface_is_refused_where_the_binding_is_required() -> None:
    bundle = _bundle("wo_close")
    result = _run(_executor(bundle, "wo_close"), _lease(""))
    assert (result.executed, result.refusal_reason) == (False, "surface_unbound")


def test_without_require_digest_the_reference_behaviour_is_unchanged() -> None:
    """The reference runtime issues leases without a digest; its committed
    interop artifacts must not move (stop condition), so this stays opt-in."""
    bundle = _bundle("wo_close")
    dispatcher = GovernedToolDispatcher("b1")
    dispatcher.register("wo_close", lambda args: "ok")
    dispatcher.bind_surface_observer(
        lambda: observed_surface_digest(bundle, dispatcher.registered_tool_names()), enforce=True)
    assert _run(dispatcher, _lease("")).executed


# -- the API mints leases under the signed surface --------------------------------

def test_the_api_signs_the_surface_into_the_lease_and_binds_an_observer(monkeypatch, tmp_path) -> None:
    import servers.execution_api as exec_mod

    key = SigningKey.generate([SignatureDomain.TOOLSPEC_BUNDLE])
    specs = [dict(_demo_spec("sha256:" + "0" * 64), tool_id="store_artifact")]
    signed, public, digest = sign_with_seed({"schema_version": 3, "tool_specs": specs},
                                            key.seed.hex(), signed_at="2026-10-07T00:00:00+00:00")
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(signed), encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(path))
    monkeypatch.setenv("REMORA_TOOLSPEC_VERIFY_KEYS", public)
    monkeypatch.setenv("REMORA_TOOLSPEC_PINNED_DIGEST", digest)
    exec_mod._reset_toolspec_bundle()
    bundle_obj = exec_mod._authz_load_bundle(os.environ)
    captured = {}

    def fake_impl(**kwargs):
        captured.update(kwargs)
        return {"executed": False, "refusal_reason": "captured"}

    monkeypatch.setattr(exec_mod, "_dispatch_under_lease_impl", fake_impl)
    monkeypatch.setattr(exec_mod, "_tool_dispatcher", lambda: None)
    monkeypatch.setattr(exec_mod, "_resolve_capability", lambda *a, **k: None)
    call = exec_mod.ToolCallRequest(tool_name="store_artifact", arguments={},
                                    target_environment="prod")
    exec_mod._dispatch_under_lease(tenant="acme", principal="agent-1", tool_call=call,
                                   semantic={}, now=datetime.now(UTC))
    assert captured["surface_digest"] == signed_surface_digest(bundle_obj)
    exec_mod._reset_toolspec_bundle()
