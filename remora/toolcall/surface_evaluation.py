# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reproducible local runtime exercise with a real file write and separate read.

Fixture keys authorize only this temporary reference runtime. No production
credentials, external system, OS sandbox or hostile-host boundary are tested.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.governance.effect_verification import PostconditionContract
from remora.toolcall.runtime_surface import RuntimeTool, RuntimeToolSurface, canonical_json
from remora.toolcall.signed_surface_runtime import SignedSurfaceRuntime, source_digest
from remora.toolcall.surface_authority import analyze_authority
from remora.toolcall.toolspec import sign_bundle


class LocalRecordStore:
    """Fixed target path owned by the reference deployment, never by tool args."""

    def __init__(self, root: Path) -> None:
        self.path = root / "record.json"

    def write(self, arguments: dict) -> dict:
        self.path.write_text(canonical_json(arguments), encoding="utf-8")
        return {"stored": True}

    def read(self) -> dict | None:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None


def reference_runtime(root: Path, *, mode: str = "enforce"):
    store = LocalRecordStore(root)
    raw = dict(tool_id="write", version=1, callable_digest=source_digest(store.write),
               implementation_identity="remora-local-record-v1", description="Write the local record.",
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
    runtime = SignedSurfaceRuntime(GovernedToolDispatcher("reference-policy"), bundle,
                                   key=key, trusted_identities=["reference-signer"], mode=mode,
                                   inventory_complete=True,
                                   trusted_verifiers={"local-reader": "reference-reader"})
    # Provider observation: fixed-path writer, no external credentials or network.
    spec = runtime._bundle.get("write")
    observed = RuntimeTool("write", "native", True, True, spec.toolspec_hash,
                           configured=True, discovered=True, source_server="remora-reference",
                           implementation_identity="remora-local-record-v1",
                           argument_schema_json=canonical_json(raw["argument_schema"]),
                           credential_scope=("local-record:write",), allowed_targets=("local-record",),
                           network_scope=(), operations=("write",), effect_classes=("update",),
                           authority_provenance="LocalRecordStore fixed-path provider")
    runtime.register(observed, store.write)
    return runtime, store, observed, spec


def reference_lease(spec, arguments=None):
    return ExecutionLease.issue(
        decision="accept", tenant_id="reference", actor_identity="reference-agent",
        tool_name="write", arguments=arguments or {"value": 1}, target_environment="local-record",
        policy_bundle_hash="reference-policy", issued_at=datetime.now(UTC).isoformat(),
        toolspec_hash=spec.toolspec_hash, toolspec_version=spec.version)


def evaluate_reference() -> dict:
    results = {}
    # Limit fixture authority to the evaluation lifetime and restore caller env.
    with patch.dict("os.environ", {"REMORA_LEASE_SIGNING_KEY": secrets.token_hex(32)}):
        for case in ("verified", "mismatch", "unobserved", "extra_tool", "replacement", "shadow_drift", "missing_lease"):
            with TemporaryDirectory(prefix="remora-surface-") as directory:
                runtime, store, observed, spec = reference_runtime(Path(directory),
                    mode="shadow" if case == "shadow_drift" else "enforce")
                assessment = runtime.assess("write", {"value": 1}, tenant="reference",
                    principal="reference-agent", target="local-record",
                    postcondition=PostconditionContract("write", "local-reader", {"id": "record"}, {"value": 1}))
                if case in {"extra_tool", "shadow_drift"}:
                    runtime.dispatcher.register("shell", lambda args: args)
                if case == "replacement":
                    runtime.dispatcher.register("write", lambda args: {"stored": True})
                outcome = runtime.dispatch(assessment.assessment_id,
                    None if case == "missing_lease" else reference_lease(spec), "write", {"value": 1},
                    tenant="reference", principal="reference-agent", target="local-record")
                row = dict(runtime=outcome.runtime_outcome, surface=outcome.surface.verdict.value,
                           continuity=outcome.continuity.verdict.value,
                           authority=outcome.authority.verdict.value,
                           property=outcome.effect_verdict, file_written=store.path.exists())
                if case in {"verified", "mismatch", "unobserved"}:
                    if case == "mismatch":
                        store.path.write_text('{"value":2}', encoding="utf-8")
                    evidence = runtime.record_effect(assessment.assessment_id, tenant="reference",
                        principal="reference-reader", verifier_identity="local-reader",
                        observed=None if case == "unobserved" else store.read())
                    row.update(property=evidence["property_verdict"], receipt=evidence["binding_verdict"],
                               rechecked=runtime.recheck_effect(assessment.assessment_id, tenant="reference") == evidence)
                row["audit_valid"] = runtime.audit_valid("reference")
                results[case] = row
        authority = replace(observed, tool_id="shell", toolspec_hash=None)
        surface = RuntimeToolSurface("reference", "agent-runtime", True, (observed, authority))
        report = analyze_authority(surface, {"write": observed}, inventory_complete=True)
        results["alternate_effect_path"] = dict(verdict=report.verdict.value,
                                                paths=[list(p) for p in report.alternate_paths])
        report = analyze_authority(replace(surface, tools=(observed,)), {"write": observed})
        results["incomplete_inventory"] = dict(verdict=report.verdict.value, reasons=list(report.reasons))
    return dict(schema_version=1, scope="REMORA local reference runtime; temporary file target",
                external_deployment_verified=False, cases=results)
