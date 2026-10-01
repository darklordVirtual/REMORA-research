# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The observed tool surface is bound to the execution authority (quality program Q3.2).

The lease carries the digest of the surface observed at assessment. The
dispatcher compares it with the surface it observes at dispatch: in shadow a
change is counted and recorded, enforced (or under a strict runtime profile)
it refuses. The shadow measurement the design asks for before enforcement
is committed as ``artifacts/runtime_surface/surface_binding_shadow_v1.json``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher

ROOT = Path(__file__).resolve().parents[1]
ARGS = {"id": "WO-1"}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "surface-binding-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


class Surface:
    def __init__(self):
        self.digest = "sha256:" + "a" * 64
        self.down = False

    def __call__(self) -> str:
        if self.down:
            raise ConnectionError("observer down")
        return self.digest


def _lease(digest: str = "") -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1", tool_name="wo_close",
        arguments=ARGS, target_environment="prod", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat(), surface_digest=digest)


def _dispatcher(surface, *, enforce):
    calls: list = []
    dispatcher = GovernedToolDispatcher("b1")
    dispatcher.register("wo_close", lambda args: calls.append(args) or "ok")
    dispatcher.bind_surface_observer(surface, enforce=enforce)
    return dispatcher, calls


def _run(dispatcher, lease):
    return dispatcher.dispatch(lease, "wo_close", ARGS, tenant_id="acme",
                               target_environment="prod", actor_identity="agent-1")


class TestShadow:
    def test_an_unchanged_surface_is_compared_and_executes(self):
        surface = Surface()
        dispatcher, calls = _dispatcher(surface, enforce=False)
        assert _run(dispatcher, _lease(surface.digest)).executed
        assert (dispatcher.surface_checks, dispatcher.surface_changes) == (1, 0)

    def test_a_changed_surface_is_counted_but_not_refused(self):
        surface = Surface()
        dispatcher, calls = _dispatcher(surface, enforce=False)
        lease = _lease(surface.digest)
        surface.digest = "sha256:" + "b" * 64
        assert _run(dispatcher, lease).executed
        assert dispatcher.surface_changes == 1

    def test_an_unobservable_surface_does_not_block_in_shadow(self):
        surface = Surface()
        dispatcher, _ = _dispatcher(surface, enforce=False)
        lease = _lease(surface.digest)
        surface.down = True
        assert _run(dispatcher, lease).executed


class TestEnforced:
    def test_a_changed_surface_refuses_and_nothing_runs(self):
        surface = Surface()
        dispatcher, calls = _dispatcher(surface, enforce=True)
        lease = _lease(surface.digest)
        surface.digest = "sha256:" + "b" * 64
        result = _run(dispatcher, lease)
        assert (result.executed, result.refusal_reason) == (False, "surface_changed")
        assert calls == []

    def test_an_unobservable_surface_refuses(self):
        surface = Surface()
        dispatcher, _ = _dispatcher(surface, enforce=True)
        lease = _lease(surface.digest)
        surface.down = True
        assert _run(dispatcher, lease).refusal_reason == "surface_unobservable"

    def test_the_refusal_leaves_the_nonce_unspent(self):
        surface = Surface()
        dispatcher, calls = _dispatcher(surface, enforce=True)
        lease = _lease(surface.digest)
        original = surface.digest
        surface.digest = "sha256:" + "b" * 64
        assert not _run(dispatcher, lease).executed
        surface.digest = original
        assert _run(dispatcher, lease).executed and calls == [ARGS]

    def test_a_strict_profile_enforces_a_shadow_binding(self, monkeypatch):
        import remora.enforcement.custody as custody
        import remora.enforcement.lease as lease_module

        surface = Surface()
        dispatcher, calls = _dispatcher(surface, enforce=False)
        lease = _lease(surface.digest)
        surface.digest = "sha256:" + "b" * 64
        monkeypatch.setattr(custody, "custody_is_enforced", lambda: True)
        monkeypatch.setattr(lease_module.GovernedToolDispatcher, "_runtime_refusal",
                            staticmethod(lambda lease: None))
        assert _run(dispatcher, lease).refusal_reason == "surface_changed" and calls == []

    def test_a_lease_without_a_surface_digest_is_not_checked(self):
        surface = Surface()
        dispatcher, _ = _dispatcher(surface, enforce=True)
        assert _run(dispatcher, _lease()).executed
        assert dispatcher.surface_checks == 0


class TestTheSignedField:
    def test_rewriting_the_digest_breaks_the_signature(self):
        data = {**_lease("sha256:" + "a" * 64).to_dict(), "surface_digest": "sha256:" + "c" * 64}
        verdict = ExecutionLease.from_dict(data).verify(
            tool_name="wo_close", arguments=ARGS, tenant_id="acme",
            target_environment="prod", actor_identity="agent-1")
        assert verdict.reason == "signature_invalid"


def test_the_shadow_measurement_reproduces():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "measure_surface_binding_shadow.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    artifact = json.loads((ROOT / "artifacts/runtime_surface/surface_binding_shadow_v1.json").read_text())
    assert artifact["legitimate_runs"]["surface_changed"] == 0
    assert artifact["perturbed_runs_enforced"]["refused"] == artifact["perturbed_runs_enforced"]["runs"]
