# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SDAD-inspired context and Spec Fidelity intake contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from remora.governance.spec_intake import (
    ContextManifest,
    ContextSource,
    DimensionVerdict,
    EvidenceFinding,
    RequirementTrace,
    SpecIntakeEvidence,
    SpecIntakeRefused,
    assess_spec_intake,
    verify_context_manifest,
    verify_spec_fidelity_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_KEY = b"test-only-sdad-intake-key-v1"
PDF_SHA256 = "25486e94f07dfcb82ea46a17c3f5cfe7f4498bc8ac7fa2cb864195811e1c3f42"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _manifest(*, sources: tuple[ContextSource, ...] | None = None) -> ContextManifest:
    return ContextManifest.build(
        intake_id="intake-sdad-001",
        spec_id="remora-spec-intake-v1",
        spec_revision="2026-08-24",
        intent_authority_hash=_sha("reference-intent-authority"),
        tool_spec_hash=_sha("reference-tool-spec"),
        policy_bundle_hash=_sha("reference-policy-bundle"),
        prompt_template_hash=_sha("reference-prompt-template"),
        tool_manifest_hash=_sha("reference-tool-manifest"),
        model_provider="reference-only",
        model_id="human-reviewed-structural-intake",
        model_route_revision="v1",
        sources=sources or (
            ContextSource(
                source_id="sdad-paper",
                uri="https://arxiv.org/abs/2608.20341",
                revision="2608.20341v1",
                content_sha256=PDF_SHA256,
                purpose="spec-fidelity and context-ingestion design source",
            ),
        ),
        generated_at="2026-08-24T12:00:00+02:00",
        signing_identity="fixture.deployment/v1",
        signing_key=FIXTURE_KEY,
    )


def _evidence(**changes) -> SpecIntakeEvidence:
    values = {
        "requirement_ids": ("REQ-CONTEXT", "REQ-FIDELITY"),
        "acceptance_criterion_ids": ("AC-CONTEXT", "AC-FIDELITY"),
        "failure_mode_ids": ("FM-UNBOUND-CONTEXT", "FM-SCALAR-HIDING"),
        "edge_case_ids": ("EDGE-NEGATIVE-CLAIM",),
        "traces": (
            RequirementTrace(
                "REQ-CONTEXT", ("AC-CONTEXT",),
                ("tests/test_spec_intake.py::test_tampered_context_is_refused",),
            ),
            RequirementTrace(
                "REQ-FIDELITY", ("AC-FIDELITY",),
                ("tests/test_spec_intake.py::test_all_four_dimensions_are_kept_separate",),
            ),
        ),
        "consistency_check_refs": (
            "tests/test_spec_intake.py::test_trace_to_unknown_requirement_is_refused",
        ),
        "contradictions": (),
        "ambiguity_check_refs": (
            "schemas/spec_intake_v1.yaml#dimension_verdicts",
        ),
        "unresolved_terms": (),
    }
    values.update(changes)
    return SpecIntakeEvidence(**values)


def _receipt(**evidence_changes):
    return assess_spec_intake(
        manifest=_manifest(),
        evidence=_evidence(**evidence_changes),
        trusted_signers={"fixture.deployment/v1": FIXTURE_KEY},
        evaluator_identity="fixture.intake-evaluator/v1",
        evaluated_at="2026-08-24T12:01:00+02:00",
        evaluator_signing_key=FIXTURE_KEY,
    )


def test_all_four_dimensions_are_kept_separate() -> None:
    receipt = _receipt()
    assert [item.name for item in receipt.dimensions] == [
        "completeness", "consistency", "unambiguity", "verifiability"
    ]
    assert all(
        item.verdict is DimensionVerdict.SATISFIED
        for item in receipt.dimensions
    )
    assert receipt.intake_status == "INTAKE_ACCEPTED"
    wire = receipt.to_dict()
    assert "score" not in wire
    assert "aggregate_score" not in wire
    assert len(wire["receipt_sha256"]) == 64
    verify_spec_fidelity_receipt(
        receipt, {"fixture.intake-evaluator/v1": FIXTURE_KEY})


def test_tampered_context_is_refused() -> None:
    manifest = replace(_manifest(), model_id="different-model")
    with pytest.raises(SpecIntakeRefused) as exc:
        verify_context_manifest(
            manifest, {"fixture.deployment/v1": FIXTURE_KEY})
    assert exc.value.reason == "context_digest_mismatch"


def test_untrusted_context_signer_is_refused() -> None:
    with pytest.raises(SpecIntakeRefused) as exc:
        verify_context_manifest(_manifest(), {"another.identity": FIXTURE_KEY})
    assert exc.value.reason == "context_signer_untrusted"


def test_evaluator_identity_is_bound_to_the_receipt_signature() -> None:
    receipt = replace(_receipt(), evaluator_identity="typed.name/v1")
    with pytest.raises(SpecIntakeRefused) as exc:
        verify_spec_fidelity_receipt(
            receipt, {"fixture.intake-evaluator/v1": FIXTURE_KEY})
    assert exc.value.reason == "receipt_evaluator_untrusted"


def test_tampered_dimension_invalidates_the_receipt() -> None:
    receipt = _receipt()
    changed = replace(
        receipt.dimensions[0],
        evidence_refs=(*receipt.dimensions[0].evidence_refs, "invented-ref"),
    )
    tampered = replace(receipt, dimensions=(changed, *receipt.dimensions[1:]))
    with pytest.raises(SpecIntakeRefused) as exc:
        verify_spec_fidelity_receipt(
            tampered, {"fixture.intake-evaluator/v1": FIXTURE_KEY})
    assert exc.value.reason == "receipt_digest_mismatch"


def test_source_order_does_not_change_the_manifest_hash() -> None:
    a = ContextSource("a", "urn:a", "1", _sha("a"), "requirements")
    b = ContextSource("b", "urn:b", "1", _sha("b"), "policy")
    assert _manifest(sources=(a, b)).manifest_sha256 == _manifest(
        sources=(b, a)).manifest_sha256


def test_missing_coverage_refuses_only_by_named_reasons() -> None:
    receipt = _receipt(failure_mode_ids=(), edge_case_ids=())
    completeness = receipt.dimensions[0]
    assert completeness.verdict is DimensionVerdict.REFUSED
    assert completeness.reasons == ("missing_failure_modes", "missing_edge_cases")
    assert receipt.intake_status == "INTAKE_REFUSED"


def test_absent_checks_are_unresolved_not_silently_satisfied() -> None:
    receipt = _receipt(consistency_check_refs=(), ambiguity_check_refs=())
    by_name = {item.name: item for item in receipt.dimensions}
    assert by_name["consistency"].verdict is DimensionVerdict.UNRESOLVED
    assert by_name["unambiguity"].verdict is DimensionVerdict.UNRESOLVED
    assert receipt.intake_status == "INTAKE_UNRESOLVED"


def test_negative_finding_requires_evidence_just_like_a_positive_claim() -> None:
    with pytest.raises(ValueError, match="at least one evidence reference"):
        EvidenceFinding("CONTRA-1", "requirements disagree", ())


def test_evidenced_contradiction_refuses_consistency() -> None:
    finding = EvidenceFinding(
        "CONTRA-1", "REQ-A and REQ-B assign incompatible owners",
        ("spec.md#REQ-A", "spec.md#REQ-B"),
    )
    receipt = _receipt(contradictions=(finding,))
    consistency = receipt.dimensions[1]
    assert consistency.verdict is DimensionVerdict.REFUSED
    assert consistency.reasons == ("contradiction:CONTRA-1",)
    assert set(finding.evidence_refs) <= set(consistency.evidence_refs)


def test_trace_to_unknown_requirement_is_refused() -> None:
    traces = (*_evidence().traces, RequirementTrace(
        "REQ-NOT-DECLARED", ("AC-CONTEXT",), ("tests/missing-subject",)))
    receipt = _receipt(traces=traces)
    consistency = receipt.dimensions[1]
    assert consistency.verdict is DimensionVerdict.REFUSED
    assert consistency.reasons == (
        "trace_for_unknown_requirement:REQ-NOT-DECLARED",
    )


def test_requirement_without_verification_evidence_is_refused() -> None:
    traces = (
        RequirementTrace("REQ-CONTEXT", ("AC-CONTEXT",), ()),
        _evidence().traces[1],
    )
    receipt = _receipt(traces=traces)
    verifiability = receipt.dimensions[3]
    assert verifiability.verdict is DimensionVerdict.REFUSED
    assert verifiability.reasons == ("verification_missing:REQ-CONTEXT",)


def test_contract_schema_pins_scope_and_no_scalar_score() -> None:
    schema = yaml.safe_load(
        (ROOT / "schemas/spec_intake_v1.yaml").read_text(encoding="utf-8"))
    assert schema["schema_version"] == 1
    receipt = schema["spec_fidelity_receipt"]
    assert receipt["source_dimensions"] == [
        "completeness", "consistency", "unambiguity", "verifiability"
    ]
    assert receipt["aggregate_numeric_score"] == "forbidden"
    assert all(isinstance(code, str) for code in schema["reason_codes"])
    assert {
        "context_signature_invalid",
        "receipt_evaluator_untrusted",
        "receipt_signature_invalid",
    } <= set(schema["reason_codes"])
    assert schema["realization"]["execution_api_wiring"] == "not_implemented"
    assert schema["realization"]["semantic_correctness_claim"] == "refused"


def test_committed_reference_artifact_is_reproducible() -> None:
    artifact = json.loads(
        (ROOT / "artifacts/spec_intake/sdad_spec_fidelity_v1.json").read_text(
            encoding="utf-8"))
    expected = {
        "artifact_kind": "sdad_spec_intake_reference_v1",
        "claim_scope": (
            "reproducible structural intake fixture; not deployment evidence "
            "and not a semantic-correctness claim"),
        "context_manifest": _manifest().to_dict(),
        "spec_fidelity_receipt": _receipt().to_dict(),
    }
    assert artifact == expected
