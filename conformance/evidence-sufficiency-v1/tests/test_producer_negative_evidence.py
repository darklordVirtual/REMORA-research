# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]
if str(SUITE) not in sys.path:
    sys.path.insert(0, str(SUITE))

from producer_negative_evidence import EvidenceStatus, assess_producer_negative_evidence  # noqa: E402
from run_producer_negative_evidence import evaluate, inference_input, run  # noqa: E402


CASES = json.loads((SUITE / "producer-cases.json").read_text())["cases"]


def by_id(case_id: str):
    return next(case for case in CASES if case["id"] == case_id)


def test_all_authored_cases_match():
    artifact = run()
    assert artifact["case_count"] == 10
    assert artifact["matched_count"] == 10


def test_harness_expectations_are_not_checker_inputs():
    case = by_id("PNE-01")
    mutated = copy.deepcopy(case)
    mutated["expect"] = {"status": "violated", "reason": "wrong_on_purpose"}
    mutated["metadata"] = {"mutated": True}
    assert inference_input(case) == inference_input(mutated)
    assert evaluate(case)["observed"] == evaluate(mutated)["observed"]


def test_capability_does_not_imply_emission_obligation():
    verdict = evaluate(by_id("PNE-02"))["observed"]
    assert verdict["status"] == "not_established"
    assert verdict["reason"] == "emission_obligation_unestablished"


def test_each_absence_establishment_premise_is_independently_required():
    baseline = by_id("PNE-01")
    for field in (
        "declared_capabilities",
        "effective_access",
        "mandatory_emission",
        "collection_closed",
        "delivery_integrity",
        "suppression_gap_absent",
    ):
        case = copy.deepcopy(baseline)
        case["observations"].pop(field, None)
        req = inference_input(case)
        verdict = assess_producer_negative_evidence(req["property"], req["observations"], req["context"])
        assert verdict.status is EvidenceStatus.NOT_ESTABLISHED, field


def test_direct_violation_witness_does_not_require_negative_coverage():
    result = evaluate(by_id("PNE-07"))["observed"]
    assert result["status"] == "violated"
    assert result["reason"] == "accepted_delegation_observed_in_bounded_scope"


def test_empty_and_unavailable_declarations_are_distinct():
    empty = evaluate(by_id("PNE-05"))["observed"]
    unavailable = evaluate(by_id("PNE-06"))["observed"]
    assert empty["reason"] == "producer_capability_not_declared"
    assert unavailable["reason"] == "producer_declaration_unavailable"
    assert empty["reason"] != unavailable["reason"]


def test_architectural_non_bypassability_is_out_of_profile():
    case = by_id("PNE-01")
    try:
        assess_producer_negative_evidence("non_bypassability", case["observations"], case["context"])
    except ValueError as exc:
        assert "unsupported property" in str(exc)
    else:
        raise AssertionError("architectural non_bypassability must not be inferred by this profile")


def test_production_premises_are_rejected():
    case = by_id("PNE-01")
    try:
        assess_producer_negative_evidence(
            case["property"], case["observations"], case["context"], premise_source="production"
        )
    except ValueError as exc:
        assert "production evidence admission is intentionally not implemented" in str(exc)
    else:
        raise AssertionError("production premise source must fail closed")
