# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the evidence-sufficiency-v1.2 corpus against the frozen v1 checker.

v1.2 adds three cases to the v1.1 corpus; the runner checks are those of v1.1. The checker is imported from
`../evidence-sufficiency-v1/checker.py`; its sha256 is recorded, never enforced
as a failure, so a seeded-fault measurement of this runner stays meaningful.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "evidence-sufficiency-v1"
CHECKER_PATH = V1 / "checker.py"
FROZEN_CHECKER_SHA256 = "c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0"
SUITE = "evidence-sufficiency-v1.2"


def _load_checker():
    spec = importlib.util.spec_from_file_location("evidence_sufficiency_checker", CHECKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
EvidenceStatus = checker.EvidenceStatus
assess = checker.assess
canonical = checker.canonical


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


def reason_vocabulary(source: str) -> dict[str, set[str]]:
    """Reason literals the checker can return, read from its source, not from its tables.

    `inconclusive`: second argument of every `_unknown(...)` call.
    `decisive`: third argument of every `_result(...)` call whose status is not NOT_ESTABLISHED.
    """
    inconclusive: set[str] = set()
    decisive: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == "_unknown" and len(node.args) >= 2:
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                inconclusive.add(arg.value)
        elif node.func.id == "_result" and len(node.args) >= 3:
            status, arg = node.args[1], node.args[2]
            is_inconclusive = isinstance(status, ast.Attribute) and status.attr == "NOT_ESTABLISHED"
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and not is_inconclusive:
                decisive.add(arg.value)
    return {"inconclusive": inconclusive, "decisive": decisive}


def guidance_problem(verdict: dict, guidance: dict) -> str | None:
    """Return why a verdict breaks the guidance contract, or None."""
    if verdict["status"] == EvidenceStatus.NOT_ESTABLISHED.value:
        expected = guidance.get(verdict["reason"])
        if expected is None:
            return "inconclusive_reason_without_declared_guidance"
        if not verdict["missing_evidence"] or not verdict.get("decisive_if"):
            return "inconclusive_verdict_without_guidance"
        if verdict["missing_evidence"] != expected["missing_evidence"]:
            return "missing_evidence_differs_from_declared_guidance"
        if verdict.get("decisive_if") != expected["decisive_if"]:
            return "decisive_if_differs_from_declared_guidance"
        return None
    if verdict["missing_evidence"] or "decisive_if" in verdict:
        return "decisive_verdict_carries_guidance"
    return None


def build_record() -> dict:
    corpus = load_json(HERE / "cases.json")
    guidance = load_json(HERE / "guidance.json")["guidance"]
    ladders = load_json(HERE / "ladders.json")
    default_scope = {"kind": "synthetic_fixture", "suite": SUITE, "bounded": True}
    by_id = {case["id"]: case for case in corpus["cases"]}
    failures: list[str] = []
    guidance_failures: list[str] = []

    def check_guidance(label: str, verdict: dict) -> None:
        problem = guidance_problem(verdict, guidance)
        if problem:
            guidance_failures.append(f"{label}:{problem}")

    # 1. Authored expectations (status + reason), as in v1.
    results = []
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
        check_guidance(case["id"], actual)

    # 2. Indistinguishable worlds, unchanged from v1.
    pairs = []
    for witness in corpus["indistinguishable_worlds"]:
        left, right = witness["worlds"]
        same = canonical(left["visible"]) == canonical(right["visible"])
        lv = assess(witness["claim"], left["visible"], scope={**default_scope, "witness": witness["id"]})
        rv = assess(witness["claim"], right["visible"], scope={**default_scope, "witness": witness["id"]})
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

    # 3. Evidence erasure, as in v1, now also under the guidance contract.
    inconclusive_erasures = 0
    inconclusive_erasure_failures: list[str] = []
    decisive_erasures = 0
    polarity_flip_failures: list[str] = []
    for case in corpus["cases"]:
        base = assess(case["claim"], case["observations"])
        for field in case["observations"]:
            reduced = deepcopy(case["observations"])
            del reduced[field]
            verdict = assess(case["claim"], reduced)
            check_guidance(f"{case['id']}-{field}", verdict.as_dict())
            if base.status is EvidenceStatus.NOT_ESTABLISHED:
                inconclusive_erasures += 1
                if verdict.status is not EvidenceStatus.NOT_ESTABLISHED:
                    inconclusive_erasure_failures.append(f"{case['id']}:{field}")
            else:
                decisive_erasures += 1
                opposite = (
                    EvidenceStatus.VIOLATED
                    if base.status is EvidenceStatus.ESTABLISHED
                    else EvidenceStatus.ESTABLISHED
                )
                if verdict.status is opposite:
                    polarity_flip_failures.append(f"{case['id']}:{field}")
    failures.extend(inconclusive_erasure_failures)
    failures.extend(polarity_flip_failures)

    # 4. Wrong shortcuts, unchanged from v1.
    wrong_shortcuts = {
        "absence_always_means_violation": ("A02", "violated"),
        "refusal_always_means_enforced": ("B03", "established"),
        "matching_state_always_means_verified": ("E04", "established"),
        "tool_ack_means_postcondition": ("E02", "established"),
        "unknown_means_success": ("E03", "established"),
        "unaccepted_effect_means_violation": ("B10", "violated"),
        "truthy_premise_means_true": ("A16", "violated"),
    }
    shortcut_results = {}
    for name, (case_id, wrong_status) in wrong_shortcuts.items():
        actual = assess(by_id[case_id]["claim"], by_id[case_id]["observations"])
        rejected = actual.status.value != wrong_status
        shortcut_results[name] = {"witness": case_id, "rejected": rejected}
        if not rejected:
            failures.append(name)

    # 5. Empty observations never become decisive, and still carry guidance.
    empty = {
        claim: assess(claim, {}, scope=default_scope).as_dict()
        for claim in sorted({case["claim"] for case in corpus["cases"]})
    }
    if any(item["status"] != "not_established" for item in empty.values()):
        failures.append("empty_input_became_decisive")
    for claim, verdict in empty.items():
        check_guidance(f"empty:{claim}", verdict)

    # 6. Reason coverage: every reason the checker can return is an expected reason somewhere.
    vocabulary = reason_vocabulary(CHECKER_PATH.read_text(encoding="utf-8"))
    expected_reasons = {case["expected"]["reason"] for case in corpus["cases"]}
    all_reasons = vocabulary["inconclusive"] | vocabulary["decisive"]
    unreached = sorted(all_reasons - expected_reasons)
    undeclared_guidance = sorted(vocabulary["inconclusive"] - set(guidance))
    orphan_guidance = sorted(set(guidance) - vocabulary["inconclusive"])
    failures.extend(f"unreached_reason:{r}" for r in unreached)
    failures.extend(f"undeclared_guidance:{r}" for r in undeclared_guidance)
    failures.extend(f"orphan_guidance:{r}" for r in orphan_guidance)

    # 7. Precedence witnesses: both guards fail; repairing the earlier surfaces the later.
    precedence = []
    for w in ladders["witnesses"]:
        case = by_id[w["case"]]
        first = assess(case["claim"], deepcopy(case["observations"])).reason
        repaired_obs = {**deepcopy(case["observations"]), **w["repair"]}
        second = assess(case["claim"], repaired_obs).reason
        ok = first == w["earlier"] and second == w["later"]
        precedence.append({"case": w["case"], "earlier": w["earlier"], "later": w["later"], "holds": ok})
        if not ok:
            failures.append(f"precedence:{w['earlier']}>{w['later']}")
    declared_pairs = set()
    for segments in ladders["ladders"].values():
        for seq in segments.values():
            declared_pairs.update(zip(seq, seq[1:]))
    witnessed_pairs = {(w["earlier"], w["later"]) for w in ladders["witnesses"]}
    failures.extend(
        f"unwitnessed_precedence:{a}>{b}" for a, b in sorted(declared_pairs - witnessed_pairs)
    )

    # 8. Isolation witnesses: each inconclusive reason can be the only failing premise.
    isolation = []
    for w in ladders["isolation"]:
        case = by_id[w["case"]]
        alone = assess(case["claim"], deepcopy(case["observations"]))
        repaired = assess(case["claim"], {**deepcopy(case["observations"]), **w["repair"]})
        ok = (
            case["expected"]["reason"] == w["reason"]
            and alone.reason == w["reason"]
            and repaired.status is not EvidenceStatus.NOT_ESTABLISHED
        )
        isolation.append({"reason": w["reason"], "case": w["case"], "holds": ok})
        if not ok:
            failures.append(f"isolation:{w['reason']}")
    failures.extend(
        f"unisolated_reason:{r}"
        for r in sorted(vocabulary["inconclusive"] - {w["reason"] for w in ladders["isolation"]})
    )

    failures.extend(guidance_failures)

    status_counts = Counter(item["property_verdict"]["status"] for item in results)
    gap_counts = Counter(case.get("gap", "v1") for case in corpus["cases"])
    return {
        "suite": SUITE,
        "record_kind": "synthetic-author-run",
        "purpose": "regression evidence for claim-sufficiency inference rules, not system conformance",
        "inputs_sha256": {
            "checker.py (frozen v1)": sha256_file(CHECKER_PATH),
            "cases.json": sha256_file(HERE / "cases.json"),
            "guidance.json": sha256_file(HERE / "guidance.json"),
            "ladders.json": sha256_file(HERE / "ladders.json"),
        },
        "checker_is_frozen_v1": sha256_file(CHECKER_PATH) == FROZEN_CHECKER_SHA256,
        "authored_expectations": {
            "matched": sum(item["case_result"] == "MATCH" for item in results),
            "total": len(results),
            "by_origin": dict(sorted(gap_counts.items())),
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
        "reason_coverage": {
            "checker_reasons": len(all_reasons),
            "unreached": unreached,
            "undeclared_guidance": undeclared_guidance,
            "orphan_guidance": orphan_guidance,
        },
        "precedence_witnesses": precedence,
        "isolation_witnesses": isolation,
        "guidance_contract_failures": guidance_failures,
        "case_results": {item["id"]: item["case_result"] for item in results},
        "failures": failures,
        "limits": [
            "No external implementation was run.",
            "Evidence acceptance, scope and completeness are synthetic fixture premises.",
            "No production, cryptographic, APS or CoSAI conformance claim is made.",
            "No causal effect attribution is implemented.",
            "ESTABLISHED and VIOLATED are bounded property verdicts, not whole-system grades.",
            (
                "Cases G1-G5 were written after an external seeded-fault run named the gaps; "
                "their kills of those faults are not independent evidence."
            ),
            (
                "Cases H1 were written after an external run with withheld faults named the gap; "
                "their kills of those faults are not independent evidence."
            ),
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
            print("committed run-record.json is stale")
            return 1
        print(f"{SUITE} artifact is reproducible")
        return 1 if record["failures"] else 0

    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if record["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
