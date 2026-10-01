# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Credential scope comes from the issuer, not the tool provider (quality program Q3.3).

The reference runtime used to compare the signed spec with the scope a
deployment provider *declared* for a tool. With an issuer bound, the scope
compared is the one the issuer reports for the credential the tool was
actually given, at registration and again before every dispatch.
"""
from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.toolcall.credential_issuer import (
    CredentialRefused,
    IssuedCredential,
    ReferenceCredentialIssuer,
)
from remora.toolcall.surface_evaluation import LocalRecordStore, reference_lease
from remora.toolcall.toolspec import ToolSpecRefused

KEY = secrets.token_bytes(32)


@pytest.fixture(autouse=True)
def _lease_key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "issuer-scope-lease-key")


def _issuer(scope=("local-record:write",)):
    return ReferenceCredentialIssuer(key=KEY, issuer_id="issuer-1", grants={"write": scope})


def _runtime(tmp_path: Path, issuer, *, pass_credential=False, fn=None):
    """The reference runtime of surface_evaluation, with an issuer bound."""
    from remora.enforcement.lease import GovernedToolDispatcher
    from remora.toolcall.runtime_surface import RuntimeTool, canonical_json
    from remora.toolcall.signed_surface_runtime import SignedSurfaceRuntime, source_digest
    from remora.toolcall.toolspec import sign_bundle

    store = LocalRecordStore(tmp_path)
    fn = fn or store.write
    raw = dict(tool_id="write", version=1, callable_digest=source_digest(fn),
               implementation_identity="remora-local-record-v1", description="Write.",
               argument_schema={"type": "object", "properties": {"value": {"type": "integer"}},
                                "required": ["value"], "additionalProperties": False},
               risk_tier="medium", action_type="write", domain="general", capabilities=["record"],
               semantic_contract={"effect": "update"}, credential_scope=["local-record:write"],
               allowed_targets=["local-record"], idempotency_contract={"safe_to_retry": False},
               postcondition_reader="local-reader", compensation_tool=None,
               timeout_policy={"dispatch_timeout_seconds": 10}, network_policy={"egress": "none"},
               signing_identity="reference-signer")
    key = secrets.token_hex(32)
    bundle = sign_bundle({"schema_version": 1, "tool_specs": [raw]}, key=key,
                         signing_identity="reference-signer", signed_at=datetime.now(UTC).isoformat())
    runtime = SignedSurfaceRuntime(GovernedToolDispatcher("reference-policy"), bundle, key=key,
                                   trusted_identities=["reference-signer"], mode="shadow",
                                   credential_issuer=issuer)
    spec = runtime._bundle.get("write")
    observed = RuntimeTool("write", "native", True, True, spec.toolspec_hash,
                           implementation_identity="remora-local-record-v1",
                           argument_schema_json=canonical_json(raw["argument_schema"]))
    return runtime, store, observed, spec, fn


def _dispatch(runtime, spec):
    assessment = runtime.assess("write", {"value": 1}, tenant="reference",
                                principal="reference-agent", target="local-record")
    return runtime.dispatch(assessment.assessment_id, reference_lease(spec), "write",
                            {"value": 1}, tenant="reference", principal="reference-agent",
                            target="local-record")


class TestTheIssuer:
    def test_a_request_is_narrowed_to_the_grant_never_widened(self):
        credential = _issuer().issue("write", ["local-record:write", "local-record:admin"])
        assert credential.scope == ("local-record:write",)

    def test_introspection_returns_the_issued_scope(self):
        issuer = _issuer()
        assert issuer.introspect(issuer.issue("write", [])) == ("local-record:write",)

    def test_a_forged_credential_is_refused(self):
        issuer = _issuer()
        credential = issuer.issue("write", [])
        forged = IssuedCredential(credential.credential_id, "issuer-1", "write",
                                  ("local-record:write", "root"), credential.expires_at,
                                  credential.signature)
        with pytest.raises(CredentialRefused, match="signature"):
            issuer.introspect(forged)

    def test_an_expired_credential_is_refused(self):
        issuer = ReferenceCredentialIssuer(key=KEY, issuer_id="i", grants={"write": ["s"]},
                                           ttl_seconds=0.001)
        credential = issuer.issue("write", [])
        time.sleep(0.01)
        with pytest.raises(CredentialRefused, match="expired"):
            issuer.introspect(credential)

    def test_a_tool_without_a_grant_gets_nothing(self):
        with pytest.raises(CredentialRefused):
            _issuer().issue("shell", [])


class TestTheRuntimeUsesTheIssuersAnswer:
    def test_an_issuer_scope_within_the_spec_registers_and_executes(self, tmp_path):
        runtime, store, observed, spec, fn = _runtime(tmp_path, _issuer())
        runtime.register(observed, fn)
        assert _dispatch(runtime, spec).execution.executed

    def test_an_issuer_granting_more_than_the_spec_is_refused_at_registration(self, tmp_path):
        class FixedScope(ReferenceCredentialIssuer):
            """Issues its whole grant whatever was requested, as some real
            issuers do. The reference issuer narrows, so it cannot show this."""

            def issue(self, tool_id, requested):
                return super().issue(tool_id, [])

        issuer = FixedScope(key=KEY, issuer_id="issuer-1",
                            grants={"write": ["local-record:write", "local-record:admin"]})
        runtime, _, observed, _, fn = _runtime(tmp_path, issuer)
        with pytest.raises(ToolSpecRefused) as refusal:
            runtime.register(observed, fn)
        assert refusal.value.reason_code == "toolspec_credential_scope_mismatch"

    def test_a_scope_widened_after_registration_is_refused_before_dispatch(self, tmp_path):
        class Widening(ReferenceCredentialIssuer):
            widened = False

            def introspect(self, credential):
                scope = super().introspect(credential)
                return scope + ("local-record:admin",) if self.widened else scope

        issuer = Widening(key=KEY, issuer_id="issuer-1", grants={"write": ["local-record:write"]})
        runtime, store, observed, spec, fn = _runtime(tmp_path, issuer)
        runtime.register(observed, fn)
        issuer.widened = True
        with pytest.raises(ToolSpecRefused):
            _dispatch(runtime, spec)
        assert not store.path.exists()

    def test_the_tool_receives_its_issuer_scoped_credential(self, tmp_path):
        received: list = []

        def write(arguments, credential):
            received.append(credential)
            return {"stored": True}

        runtime, _, observed, spec, fn = _runtime(tmp_path, _issuer(), fn=write)
        runtime.register(observed, fn, pass_credential=True)
        assert _dispatch(runtime, spec).execution.executed
        assert received[0].scope == ("local-record:write",)
        assert received[0].issuer_id == "issuer-1"

    def test_without_an_issuer_behaviour_is_unchanged(self, tmp_path):
        runtime, _, observed, spec, fn = _runtime(tmp_path, None)
        runtime.register(observed, fn)
        assert _dispatch(runtime, spec).execution.executed
