# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the safety-case evidence profile v0.1 corpus and emit a deterministic record.

    python conformance/safety-case-evidence-profile-v0.1/run_profile.py --check

The record lays out each case as CLAIM -> PRODUCER EVIDENCE -> INDEPENDENT
VERIFICATION -> EVIDENCE SUFFICIENCY -> VERDICT and adds four checks on top of
the authored expectations:

- producer invariance: negating or erasing every producer field moves no verdict;
- erasure: removing one accepted premise never flips SUPPORTED <-> REFUTED, and
  never strengthens NOT_ESTABLISHED;
- empty input: no claim becomes decisive from no premises;
- coverage: every claim has at least one case per verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from profile_checker import ASSESSORS, DELEGATED, V1_CHECKER_PATH, Verdict, assess  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_json(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)


def _perturb(value: Any) -> Any:
    """A producer value that says the opposite, or something else entirely."""
    if type(value) is bool:
        return not value
    if type(value) is int:
        return -value - 1
    if type(value) is str:
        return f"not:{value}"
    if type(value) is dict:
        return {k: _perturb(v) for k, v in value.items()}
    if type(value) is list:
        return [_perturb(v) for v in value]
    return "perturbed"


def build_record() -> dict[str, Any]:
    profile = load_json(HERE / "profile.json")
    corpus = load_json(HERE / "cases.json")
    failures: list[str] = []
    traces = []

    for case in corpus["cases"]:
        verdict = assess(case["claim"], deepcopy(case["independent_verification"])).as_dict()
        expected = case["expected"]
        match = verdict["verdict"] == expected["verdict"] and verdict["reason"] == expected["reason"]
        if not match:
            failures.append(case["id"])
        traces.append(
            {
                "id": case["id"],
                "claim": case["claim"],
                "safeguard": profile["claims"][case["claim"]]["safeguard"],
                "producer_evidence": case["producer_evidence"],
                "independent_verification": case["independent_verification"],
                "evidence_sufficiency": {
                    "reason": verdict["reason"],
                    "missing_evidence": verdict["missing_evidence"],
                    **({"decisive_if": verdict["decisive_if"]} if "decisive_if" in verdict else {}),
                },
                "verdict": verdict["verdict"],
                "permitted_downstream_claim": verdict["permitted_downstream_claim"],
                "not_covered": profile["claims"][case["claim"]]["not_covered"],
                "case_result": "MATCH" if match else "DIVERGENT",
            }
        )

    # Producer invariance. The assessor has no producer parameter, so this
    # guards against a future edit that merges producer fields into the
    # verification premises: each producer field is copied in, negated, and
    # the verdict must not move.
    producer_checks = 0
    producer_failures: list[str] = []
    for case in corpus["cases"]:
        base = assess(case["claim"], case["independent_verification"]).verdict
        for field, value in case["producer_evidence"].items():
            if field in case["independent_verification"]:
                producer_failures.append(f"{case['id']}:{field}:shadows_verification")
                continue
            for variant in (value, _perturb(value)):
                merged = {**case["independent_verification"], field: variant}
                producer_checks += 1
                if assess(case["claim"], merged).verdict is not base:
                    producer_failures.append(f"{case['id']}:{field}")
    failures.extend(producer_failures)

    erasures = 0
    strengthening: list[str] = []
    polarity_flips: list[str] = []
    for case in corpus["cases"]:
        premises = case["independent_verification"]
        base = assess(case["claim"], premises).verdict
        opposite = {
            Verdict.SUPPORTED: Verdict.REFUTED,
            Verdict.REFUTED: Verdict.SUPPORTED,
        }.get(base)
        for field in premises:
            reduced = deepcopy(premises)
            del reduced[field]
            erasures += 1
            after = assess(case["claim"], reduced).verdict
            if base is Verdict.NOT_ESTABLISHED and after is not Verdict.NOT_ESTABLISHED:
                strengthening.append(f"{case['id']}:{field}")
            if opposite is not None and after is opposite:
                polarity_flips.append(f"{case['id']}:{field}")
    failures.extend(strengthening)
    failures.extend(polarity_flips)

    empty = {claim: assess(claim, {}).as_dict() for claim in sorted(ASSESSORS)}
    if any(item["verdict"] != Verdict.NOT_ESTABLISHED.value for item in empty.values()):
        failures.append("empty_input_became_decisive")

    coverage: dict[str, dict[str, int]] = {}
    for claim in sorted(ASSESSORS):
        counts = Counter(t["verdict"] for t in traces if t["claim"] == claim)
        coverage[claim] = {v.value: counts.get(v.value, 0) for v in Verdict}
        for v in Verdict:
            if counts.get(v.value, 0) == 0:
                failures.append(f"coverage:{claim}:{v.value}")

    if sorted(profile["claims"]) != sorted(ASSESSORS):
        failures.append("profile_claims_differ_from_assessors")

    return {
        "profile": profile["profile"],
        "record_kind": "synthetic-author-run",
        "purpose": (
            "regression evidence for safeguard-claim sufficiency rules; not an "
            "evaluation of any external system and not a safety case"
        ),
        "inputs_sha256": {
            "profile_checker.py": sha256_file(HERE / "profile_checker.py"),
            "cases.json": sha256_file(HERE / "cases.json"),
            "profile.json": sha256_file(HERE / "profile.json"),
            "evidence-sufficiency-v1/checker.py": sha256_file(V1_CHECKER_PATH),
        },
        "delegated_rules": DELEGATED,
        "authored_expectations": {
            "matched": sum(t["case_result"] == "MATCH" for t in traces),
            "total": len(traces),
            "note": "expectation matches are regression checks, not a conformance score",
        },
        "verdict_coverage": coverage,
        "producer_invariance": {"checks": producer_checks, "failures": producer_failures},
        "evidence_erasure_checks": {
            "single_premise_removals": erasures,
            "inconclusive_strengthening_failures": strengthening,
            "polarity_flip_failures": polarity_flips,
        },
        "empty_premises": empty,
        "traces": traces,
        "failures": failures,
        "limits": [
            "No external system was run; every premise is an authored synthetic fixture.",
            "Evidence acceptance, scope, completeness and immutability are trusted fixture premises.",
            "SUPPORTED is a bounded property verdict for one window and scope, not a safety case.",
            ("The five claim classes are the maintainer's reading of public safety-case discussion; "
             "they are not endorsed by, or taken verbatim from, any third party."),
            "Rules were written by the same author as the fixtures.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    record = build_record()
    rendered = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    committed = HERE / "run-record.json"

    if args.check:
        if not committed.exists() or committed.read_text(encoding="utf-8") != rendered:
            print("run-record.json is stale; regenerate with --out", file=sys.stderr)
            return 1
        print("run-record.json reproduces")
        return 1 if record["failures"] else 0

    (args.out or committed).write_text(rendered, encoding="utf-8")
    for t in record["traces"]:
        print(f"{t['id']:<7} {t['case_result']:<9} {t['claim']:<34} {t['verdict']:<16} {t['evidence_sufficiency']['reason']}")
    print(json.dumps({"failures": record["failures"]}))
    return 1 if record["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
