#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the producer-side synthetic evidence-sufficiency fixtures deterministically."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from producer_negative_evidence import assess_producer_negative_evidence


HERE = Path(__file__).resolve().parent
CASE_PATH = HERE / "producer-cases.json"
BASE_COMMIT = "f10ca2a493755f64df9225a8ccb5636aa344a43a"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def inference_input(case: dict[str, Any]) -> dict[str, Any]:
    """Explicit allowlist: harness expectations/metadata never enter inference."""
    return {
        "property": copy.deepcopy(case["property"]),
        "observations": copy.deepcopy(case["observations"]),
        "context": copy.deepcopy(case["context"]),
    }


def evaluate(case: dict[str, Any]) -> dict[str, Any]:
    request = inference_input(case)
    verdict = assess_producer_negative_evidence(
        request["property"], request["observations"], request["context"]
    )
    observed = verdict.as_dict()
    expected = case["expect"]
    matched = observed["status"] == expected["status"] and observed["reason"] == expected["reason"]
    return {
        "id": case["id"],
        "input_sha256": hashlib.sha256(canonical(request).encode()).hexdigest(),
        "expected": copy.deepcopy(expected),
        "observed": {
            "status": observed["status"],
            "reason": observed["reason"],
            "missing_evidence": observed["missing_evidence"],
        },
        "matched": matched,
    }


def run() -> dict[str, Any]:
    data = json.loads(CASE_PATH.read_text())
    results = [evaluate(case) for case in data["cases"]]
    counts: dict[str, int] = {}
    for item in results:
        status = item["observed"]["status"]
        counts[status] = counts.get(status, 0) + 1

    baseline = data["cases"][0]
    changed = copy.deepcopy(baseline)
    changed["expect"] = {"status": "violated", "reason": "authored_expectation_mutated"}
    changed["metadata"] = {"provenance": ["not-an-inference-input"], "mutated": True}
    isolation = inference_input(baseline) == inference_input(changed)

    erasure_fields = [
        "declared_capabilities",
        "effective_access",
        "mandatory_emission",
        "collection_closed",
        "delivery_integrity",
        "suppression_gap_absent",
    ]
    erasure_results = []
    for field in erasure_fields:
        erased = copy.deepcopy(baseline)
        erased["observations"].pop(field, None)
        verdict = assess_producer_negative_evidence(
            erased["property"], erased["observations"], erased["context"]
        )
        erasure_results.append({"removed": field, "status": verdict.status.value, "reason": verdict.reason})

    return {
        "suite": data["suite"],
        "artifact_kind": "synthetic-author-run",
        "base_commit": BASE_COMMIT,
        "case_count": len(results),
        "matched_count": sum(1 for item in results if item["matched"]),
        "status_counts": dict(sorted(counts.items())),
        "regressions": {
            "harness_expectation_isolation": isolation,
            "premise_erasure_checks": erasure_results,
            "premise_erasure_false_establishments": sum(
                1 for item in erasure_results if item["status"] == "established"
            ),
        },
        "results": results,
        "nonclaims": [
            "not production evidence",
            "not independent validation",
            "not OASIS or CoSAI conformance",
            "does not establish architectural non-bypassability",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
