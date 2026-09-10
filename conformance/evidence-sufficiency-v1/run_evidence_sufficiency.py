# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the evidence-sufficiency-v1 synthetic corpus and emit a deterministic record."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from checker import EvidenceStatus, assess, canonical

HERE = Path(__file__).resolve().parent


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_json(path: Path):
    def reject_duplicates(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)


def build_record() -> dict:
    corpus = load_json(HERE / "cases.json")
    default_scope = {
        "kind": "synthetic_fixture",
        "suite": "evidence-sufficiency-v1",
        "bounded": True,
    }
    results = []
    failures: list[str] = []

    for case in corpus["cases"]:
        actual = assess(
            case["claim"],
            deepcopy(case["observations"]),
            scope={**default_scope, "case": case["id"]},
        ).as_dict()
        expected = case["expected"]
        match = actual["status"] == expected["status"] and actual["reason"] == expected["reason"]
        results.append(
            {
                "id": case["id"],
                "claim": case["claim"],
                "case_result": "MATCH" if match else "DIVERGENT",
                "expected_property_status": expected["status"],
                "property_verdict": actual,
            }
        )
        if not match:
            failures.append(case["id"])

    pairs = []
    for witness in corpus["indistinguishable_worlds"]:
        left, right = witness["worlds"]
        same = canonical(left["visible"]) == canonical(right["visible"])
        lv = assess(
            witness["claim"], left["visible"], scope={**default_scope, "witness": witness["id"]}
        )
        rv = assess(
            witness["claim"], right["visible"], scope={**default_scope, "witness": witness["id"]}
        )
        ok = (
            same
            and left["hidden_truth"] != right["hidden_truth"]
            and lv.status is EvidenceStatus.NOT_ESTABLISHED
            and rv.status is EvidenceStatus.NOT_ESTABLISHED
            and lv.reason == rv.reason
        )
        pairs.append(
            {
                "id": witness["id"],
                "identical_visible_input": same,
                "distinct_hidden_truth": left["hidden_truth"] != right["hidden_truth"],
                "same_nondecisive_verdict": ok,
            }
        )
        if not ok:
            failures.append(witness["id"])

    inconclusive_erasures = 0
    inconclusive_erasure_failures: list[str] = []
    for case in corpus["cases"]:
        base = assess(case["claim"], case["observations"])
        if base.status is not EvidenceStatus.NOT_ESTABLISHED:
            continue
        for field in case["observations"]:
            reduced = deepcopy(case["observations"])
            del reduced[field]
            inconclusive_erasures += 1
            if assess(case["claim"], reduced).status is not EvidenceStatus.NOT_ESTABLISHED:
                inconclusive_erasure_failures.append(f"{case['id']}:{field}")
    failures.extend(inconclusive_erasure_failures)

    decisive_erasures = 0
    polarity_flip_failures: list[str] = []
    for case in corpus["cases"]:
        base = assess(case["claim"], case["observations"])
        if base.status is EvidenceStatus.NOT_ESTABLISHED:
            continue
        opposite = (
            EvidenceStatus.VIOLATED
            if base.status is EvidenceStatus.ESTABLISHED
            else EvidenceStatus.ESTABLISHED
        )
        for field in case["observations"]:
            reduced = deepcopy(case["observations"])
            del reduced[field]
            decisive_erasures += 1
            if assess(case["claim"], reduced).status is opposite:
                polarity_flip_failures.append(f"{case['id']}:{field}")
    failures.extend(polarity_flip_failures)

    wrong_shortcuts = {
        "absence_always_means_violation": ("A02", "violated"),
        "refusal_always_means_enforced": ("B03", "established"),
        "matching_state_always_means_verified": ("E04", "established"),
        "tool_ack_means_postcondition": ("E02", "established"),
        "unknown_means_success": ("E03", "established"),
    }
    by_id = {case["id"]: case for case in corpus["cases"]}
    shortcut_results = {}
    for name, (case_id, wrong_status) in wrong_shortcuts.items():
        actual = assess(by_id[case_id]["claim"], by_id[case_id]["observations"])
        rejected = actual.status.value != wrong_status
        shortcut_results[name] = {"witness": case_id, "rejected": rejected}
        if not rejected:
            failures.append(name)

    empty = {
        claim: assess(claim, {}, scope=default_scope).as_dict()
        for claim in sorted({case["claim"] for case in corpus["cases"]})
    }
    if any(item["status"] != "not_established" for item in empty.values()):
        failures.append("empty_input_became_decisive")

    status_counts = Counter(item["property_verdict"]["status"] for item in results)
    record = {
        "suite": "evidence-sufficiency-v1",
        "record_kind": "synthetic-author-run",
        "purpose": "regression evidence for claim-sufficiency inference rules, not system conformance",
        "inputs_sha256": {
            name: sha256_file(HERE / name)
            for name in ("checker.py", "cases.json", "run_evidence_sufficiency.py")
        },
        "legacy_provenance": {
            "decision_to_effect_v1_vectors_blob_sha": "0dd98172541c7f93fbb2d2d6e0f13112209504c5",
            "decision_to_effect_v1_base_commit": "850220687994455fae7f4d76497a3e9885c4b404",
            "legacy_suite_modified": False,
        },
        "authored_expectations": {
            "matched": sum(item["case_result"] == "MATCH" for item in results),
            "total": len(results),
            "note": "expectation matches are regression checks, not a conformance score",
        },
        "property_verdict_distribution": dict(sorted(status_counts.items())),
        "indistinguishable_world_pairs": pairs,
        "evidence_erasure_checks": {
            "inconclusive_single_field_removals": inconclusive_erasures,
            "inconclusive_strengthening_failures": inconclusive_erasure_failures,
            "decisive_single_field_removals": decisive_erasures,
            "polarity_flip_failures": polarity_flip_failures,
        },
        "wrong_shortcuts": shortcut_results,
        "empty_observations": empty,
        "case_results": {item["id"]: item["case_result"] for item in results},
        "failures": failures,
        "limits": [
            "No external implementation was run.",
            "Evidence acceptance, scope and completeness are synthetic fixture premises.",
            "No production, cryptographic, APS or CoSAI conformance claim is made.",
            "No causal effect attribution is implemented.",
            "ESTABLISHED and VIOLATED are bounded property verdicts, not whole-system grades.",
        ],
    }
    return record


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
            print("committed run-record.json is stale")
            return 1
        print("evidence-sufficiency-v1 artifact is reproducible")
        return 1 if record["failures"] else 0

    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if record["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
