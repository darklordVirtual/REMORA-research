# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the evidence-sufficiency-v1.3 corpus against the frozen v1 checker.

v1.3 keeps every v1.1 and v1.2 check and adds three kinds of check that a
systematic mutation sweep over the checker showed the earlier corpora could not
make: the verdict envelope (claim and scope are echoed), the input-rejection
contract, and metamorphic relations declared in `invariants.json`.

The method follows mutation analysis as proposed by DeMillo, Lipton and Sayward
(1978): a corpus is adequate to the degree that small seeded faults in the
checker change what it reports. Survivors of a sweep name the faults the corpus
cannot see; each is then killed by a new case, or recorded as equivalent in
`docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`. The metamorphic
relations follow Chen, Cheung and Yiu (1998): they compare verdicts across
related inputs instead of assuming an oracle for the right verdict.

The checker is imported from `../evidence-sufficiency-v1/checker.py`; its
sha256 is recorded, never enforced as a failure, so a seeded-fault measurement
of this runner stays meaningful. `build_record` takes an optional checker module
so a test can score a deliberately faulty checker without touching the file.
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "evidence-sufficiency-v1"
CHECKER_PATH = V1 / "checker.py"
FROZEN_CHECKER_SHA256 = "c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0"
SUITE = "evidence-sufficiency-v1.3"

#: Rejections that JSON cannot express, so they live here rather than in cases.json.
#: Each is a value the fixture vocabulary excludes; `assess` must refuse it with ValueError.
NON_JSON_REJECTIONS: dict[str, dict] = {
    "R11_tuple_state": {"expected_state": (1, 2)},
    "R12_set_state": {"expected_state": {1, 2}},
    "R13_bytes_state": {"expected_state": b"closed"},
    "R14_int_key_in_nested_mapping": {"expected_state": {1: "closed"}},
    "R15_str_subclass_state": {"expected_state": type("Str", (str,), {})("closed")},
    "R16_nan_state": {"expected_state": float("nan")},
    "R17_int_key_in_observations": {1: "closed"},
}


def _load_checker(path: Path = CHECKER_PATH) -> ModuleType:
    spec = importlib.util.spec_from_file_location("evidence_sufficiency_checker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


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
    if verdict["status"] == "not_established":
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


def _reorder(value, depth: int = 0):
    """The same JSON value with every mapping's keys in reversed order, at every depth."""
    if isinstance(value, dict):
        return {k: _reorder(v, depth + 1) for k, v in reversed(list(value.items()))}
    if isinstance(value, list):
        return [_reorder(v, depth + 1) for v in value]
    return value


def _same_json(a, b) -> bool:
    """Structural equality that keeps 1 and true apart, unlike Python's ==."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same_json(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same_json(x, y) for x, y in zip(a, b))
    return a == b


def _outcome(verdict: dict) -> dict:
    """The part of a verdict that no input transformation may change."""
    return {k: v for k, v in verdict.items() if k in ("status", "reason", "missing_evidence", "decisive_if")}


def build_record(checker_module: ModuleType | None = None) -> dict:
    chk = checker_module or checker
    EvidenceStatus = chk.EvidenceStatus
    assess = chk.assess
    canonical = chk.canonical

    corpus = load_json(HERE / "cases.json")
    guidance = load_json(HERE / "guidance.json")["guidance"]
    ladders = load_json(HERE / "ladders.json")
    invariants = load_json(HERE / "invariants.json")
    default_scope = {"kind": "synthetic_fixture", "suite": SUITE, "bounded": True}
    by_id = {case["id"]: case for case in corpus["cases"]}
    failures: list[str] = []
    guidance_failures: list[str] = []

    def check_guidance(label: str, verdict: dict) -> None:
        problem = guidance_problem(verdict, guidance)
        if problem:
            guidance_failures.append(f"{label}:{problem}")

    # Every section runs under crash capture: a checker that raises on valid input is a
    # finding to report, not a reason for the runner to die (a crash in the external
    # harness is a kill; here it is a named failure).
    results: list[dict] = []
    pairs: list[dict] = []
    shortcut_results: dict = {}
    empty: dict = {}
    precedence: list[dict] = []
    isolation: list[dict] = []
    rejections: list[dict] = []
    relations: list[dict] = []
    crashes: list[str] = []
    erasure = {"inconclusive_erasures": 0, "inconclusive_erasure_failures": [], "decisive_erasures": 0, "polarity_flip_failures": []}
    coverage = {"all_reasons": set(), "unreached": [], "undeclared_guidance": [], "orphan_guidance": []}
    vocabulary = reason_vocabulary(CHECKER_PATH.read_text(encoding="utf-8"))

    def section_authored_expectations() -> None:
        # 1. Authored expectations (status + reason), as in v1.
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

    def section_indistinguishable_worlds() -> None:
        # 2. Indistinguishable worlds, unchanged from v1.
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

    def section_evidence_erasure() -> None:
        # 3. Evidence erasure, as in v1, under the guidance contract since v1.1.
        for case in corpus["cases"]:
            base = assess(case["claim"], case["observations"])
            for field in case["observations"]:
                reduced = deepcopy(case["observations"])
                del reduced[field]
                verdict = assess(case["claim"], reduced)
                check_guidance(f"{case['id']}-{field}", verdict.as_dict())
                if base.status is EvidenceStatus.NOT_ESTABLISHED:
                    erasure["inconclusive_erasures"] += 1
                    if verdict.status is not EvidenceStatus.NOT_ESTABLISHED:
                        erasure["inconclusive_erasure_failures"].append(f"{case['id']}:{field}")
                else:
                    erasure["decisive_erasures"] += 1
                    opposite = (
                        EvidenceStatus.VIOLATED
                        if base.status is EvidenceStatus.ESTABLISHED
                        else EvidenceStatus.ESTABLISHED
                    )
                    if verdict.status is opposite:
                        erasure["polarity_flip_failures"].append(f"{case['id']}:{field}")
        failures.extend(erasure["inconclusive_erasure_failures"])
        failures.extend(erasure["polarity_flip_failures"])

    def section_wrong_shortcuts() -> None:
        # 4. Wrong shortcuts, unchanged from v1.
        wrong_shortcuts = {
            "absence_always_means_violation": ("A02", "violated"),
            "refusal_always_means_enforced": ("B03", "established"),
            "matching_state_always_means_verified": ("E04", "established"),
            "tool_ack_means_postcondition": ("E02", "established"),
            "unknown_means_success": ("E03", "established"),
            "unaccepted_effect_means_violation": ("B10", "violated"),
            "truthy_premise_means_true": ("A16", "violated"),
            "same_members_in_another_key_order_means_disagreement": ("E21", "violated"),
        }
        for name, (case_id, wrong_status) in wrong_shortcuts.items():
            actual = assess(by_id[case_id]["claim"], by_id[case_id]["observations"])
            rejected = actual.status.value != wrong_status
            shortcut_results[name] = {"witness": case_id, "rejected": rejected}
            if not rejected:
                failures.append(name)

    def section_empty_observations() -> None:
        # 5. Empty observations never become decisive, and still carry guidance.
        empty.update(
            {
                claim: assess(claim, {}, scope=default_scope).as_dict()
                for claim in sorted({case["claim"] for case in corpus["cases"]})
            }
        )
        if any(item["status"] != "not_established" for item in empty.values()):
            failures.append("empty_input_became_decisive")
        for claim, verdict in empty.items():
            check_guidance(f"empty:{claim}", verdict)

    def section_reason_coverage() -> None:
        # 6. Reason coverage: every reason the checker can return is an expected reason somewhere.
        expected_reasons = {case["expected"]["reason"] for case in corpus["cases"]}
        coverage["all_reasons"] = vocabulary["inconclusive"] | vocabulary["decisive"]
        coverage["unreached"] = sorted(coverage["all_reasons"] - expected_reasons)
        coverage["undeclared_guidance"] = sorted(vocabulary["inconclusive"] - set(guidance))
        coverage["orphan_guidance"] = sorted(set(guidance) - vocabulary["inconclusive"])
        failures.extend(f"unreached_reason:{r}" for r in coverage["unreached"])
        failures.extend(f"undeclared_guidance:{r}" for r in coverage["undeclared_guidance"])
        failures.extend(f"orphan_guidance:{r}" for r in coverage["orphan_guidance"])

    def section_precedence_witnesses() -> None:
        # 7. Precedence witnesses: both guards fail; repairing the earlier surfaces the later.
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

    def section_isolation_witnesses() -> None:
        # 8. Isolation witnesses: each inconclusive reason can be the only failing premise.
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

    def section_rejection_contract() -> None:
        # 9. Rejection contract (new in v1.3): malformed input is refused with ValueError,
        #    never assessed and never refused with another exception class.

        def try_reject(label: str, call) -> None:
            try:
                outcome = call()
            except ValueError:
                rejections.append({"id": label, "rejected": True})
                return
            except Exception as exc:  # noqa: BLE001 - the class of the exception is the finding
                rejections.append({"id": label, "rejected": False, "raised": type(exc).__name__})
                failures.append(f"rejection:{label}:raised_{type(exc).__name__}")
                return
            returned = outcome.as_dict()["status"] if hasattr(outcome, "as_dict") else type(outcome).__name__
            rejections.append({"id": label, "rejected": False, "returned": returned})
            failures.append(f"rejection:{label}:returned")

        for rejection in corpus["rejections"]:
            kwargs = {}
            if "scope" in rejection:
                kwargs["scope"] = deepcopy(rejection["scope"])
            if "premise_source" in rejection:
                kwargs["premise_source"] = rejection["premise_source"]
            try_reject(
                rejection["id"],
                lambda r=rejection, kw=kwargs: assess(r["claim"], deepcopy(r["observations"]), **kw),
            )
        valid = deepcopy(by_id["E01"]["observations"])
        for label, override in NON_JSON_REJECTIONS.items():
            try_reject(label, lambda o={**valid, **override}: assess("postcondition_observed", o))
            # canonical() is also a module entry point (the runner calls it directly), so it must
            # refuse the same values on its own, not only behind assess().
            try_reject(f"canonical:{label}", lambda v=override: canonical(v))

    def section_metamorphic_relations() -> None:
        # 10. Metamorphic relations (new in v1.3), declared in invariants.json and executed here.
        implemented = {
            "MR-1", "MR-2", "MR-3", "MR-4", "MR-5", "MR-6", "MR-7", "MR-8", "MR-9", "MR-10", "MR-11",
        }
        declared = {r["id"] for r in invariants["relations"]}
        failures.extend(f"unimplemented_relation:{r}" for r in sorted(declared - implemented))
        failures.extend(f"undeclared_relation:{r}" for r in sorted(implemented - declared))
        relation_failures: dict[str, list[str]] = {rid: [] for rid in sorted(declared & implemented)}
        checked: Counter = Counter()
        envelope_keys = set(invariants["envelope_keys"])
        optional_keys = set(invariants["optional_envelope_keys"])
        scopes = invariants["scopes"]

        for case in corpus["cases"]:
            cid, claim = case["id"], case["claim"]
            obs = case["observations"]
            base_verdict = assess(claim, deepcopy(obs))
            base = base_verdict.as_dict()
            outcome = _outcome(base)
            for i, scope in enumerate(scopes):
                v = assess(claim, deepcopy(obs), scope=deepcopy(scope)).as_dict()
                checked["MR-1"] += 1
                if v["claim"] != claim:
                    relation_failures["MR-1"].append(f"{cid}:scope{i}")
                checked["MR-2"] += 1
                expected_scope = dict(scope) if scope else invariants["default_scope"]
                if v["scope"] != expected_scope or _outcome(v) != outcome:
                    relation_failures["MR-2"].append(f"{cid}:scope{i}")
                checked["MR-3"] += 1
                keys = set(v)
                shape_ok = (
                    keys - optional_keys == envelope_keys
                    and ("decisive_if" in v) == (v["status"] == "not_established")
                    and isinstance(v["missing_evidence"], list)
                    and all(isinstance(m, str) for m in v["missing_evidence"])
                    and isinstance(v["scope"], dict)
                    and isinstance(v["status"], str)
                    and isinstance(v["reason"], str)
                )
                if not shape_ok:
                    relation_failures["MR-3"].append(f"{cid}:scope{i}")
            checked["MR-4"] += 1
            if _outcome(assess(claim, _reorder(obs)).as_dict()) != outcome:
                relation_failures["MR-4"].append(cid)
            checked["MR-5"] += 1
            if _outcome(assess(claim, {**deepcopy(obs), "unrelated_fixture_field": "ignored"}).as_dict()) != outcome:
                relation_failures["MR-5"].append(cid)
            checked["MR-6"] += 1
            if assess(claim, deepcopy(obs)).as_dict() != base:
                relation_failures["MR-6"].append(cid)
            checked["MR-7"] += 1
            given_obs = deepcopy(obs)
            given_scope = {"kind": "synthetic_fixture", "bounded": True, "case": cid}
            snapshot_obs, snapshot_scope = deepcopy(given_obs), deepcopy(given_scope)
            v7 = assess(claim, given_obs, scope=given_scope)
            given_scope["case"] = "changed-after-the-call"
            if not (_same_json(given_obs, snapshot_obs) and dict(v7.scope) == snapshot_scope):
                relation_failures["MR-7"].append(cid)
            checked["MR-8"] += 1
            try:
                setattr(base_verdict, "status", EvidenceStatus.ESTABLISHED)
            except dataclasses.FrozenInstanceError:
                pass
            else:
                relation_failures["MR-8"].append(cid)
            if claim == "postcondition_observed" and "expected_state" in obs and "observed_state" in obs:
                checked["MR-9"] += 1
                swapped = deepcopy(obs)
                swapped["expected_state"], swapped["observed_state"] = obs["observed_state"], obs["expected_state"]
                if _outcome(assess(claim, swapped).as_dict()) != outcome:
                    relation_failures["MR-9"].append(cid)
            if base_verdict.status is not EvidenceStatus.NOT_ESTABLISHED:
                opposite = (
                    EvidenceStatus.VIOLATED
                    if base_verdict.status is EvidenceStatus.ESTABLISHED
                    else EvidenceStatus.ESTABLISHED
                )
                for field in invariants["acceptance_premises"][claim]:
                    if field not in obs:
                        continue
                    checked["MR-10"] += 1
                    flipped = {**deepcopy(obs), field: False}
                    if assess(claim, flipped).status is opposite:
                        relation_failures["MR-10"].append(f"{cid}:{field}")

        # MR-11 over the declared distinct pairs and every state value in the corpus.
        for a, b in invariants["distinct_state_pairs"]:
            checked["MR-11"] += 1
            if _same_json(a, b):
                relation_failures["MR-11"].append(f"declared_pair_not_distinct:{json.dumps([a, b])}")
            elif canonical(a) == canonical(b):
                relation_failures["MR-11"].append(f"canonical_merges:{json.dumps([a, b])}")
        state_values = [
            case["observations"][key]
            for case in corpus["cases"]
            for key in ("expected_state", "observed_state")
            if key in case["observations"]
        ]
        for value in state_values:
            checked["MR-11"] += 1
            if canonical(value) != canonical(_reorder(value)):
                relation_failures["MR-11"].append(f"key_order_changes_canonical:{json.dumps(value)}")
        distinct = []
        for value in state_values:
            if not any(_same_json(value, seen) for seen in distinct):
                distinct.append(value)
        for i, a in enumerate(distinct):
            for b in distinct[i + 1:]:
                checked["MR-11"] += 1
                if canonical(a) == canonical(b):
                    relation_failures["MR-11"].append(f"canonical_merges:{json.dumps([a, b])}")

        relations.extend(
            {
                "id": r["id"],
                "name": r["name"],
                "checked": checked[r["id"]],
                "holds": not relation_failures[r["id"]],
                "failures": relation_failures[r["id"]],
            }
            for r in invariants["relations"]
            if r["id"] in relation_failures
        )
        for r in relations:
            failures.extend(f"{r['id']}:{f}" for f in r["failures"])
            if r["checked"] == 0:
                failures.append(f"{r['id']}:never_checked")

    for fn in (section_authored_expectations, section_indistinguishable_worlds, section_evidence_erasure,
               section_wrong_shortcuts, section_empty_observations, section_reason_coverage,
               section_precedence_witnesses, section_isolation_witnesses, section_rejection_contract,
               section_metamorphic_relations):
        name = fn.__name__.removeprefix("section_")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - the crash is the finding
            crashes.append(f"{name}:{type(exc).__name__}")
            failures.append(f"crash:{name}:{type(exc).__name__}")

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
            "invariants.json": sha256_file(HERE / "invariants.json"),
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
            "inconclusive_single_field_removals": erasure["inconclusive_erasures"],
            "inconclusive_strengthening_failures": erasure["inconclusive_erasure_failures"],
            "decisive_single_field_removals": erasure["decisive_erasures"],
            "polarity_flip_failures": erasure["polarity_flip_failures"],
        },
        "wrong_shortcuts": shortcut_results,
        "empty_observations": empty,
        "reason_coverage": {
            "checker_reasons": len(coverage["all_reasons"]),
            "unreached": coverage["unreached"],
            "undeclared_guidance": coverage["undeclared_guidance"],
            "orphan_guidance": coverage["orphan_guidance"],
        },
        "precedence_witnesses": precedence,
        "isolation_witnesses": isolation,
        "rejections": rejections,
        "metamorphic_relations": relations,
        "crashes": crashes,
        "guidance_contract_failures": guidance_failures,
        "case_results": {item["id"]: item["case_result"] for item in results},
        "case_guidance": {
            item["id"]: {
                "missing_evidence": item["property_verdict"]["missing_evidence"],
                "decisive_if": item["property_verdict"].get("decisive_if"),
            }
            for item in results
        },
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
                "Cases E18-E20 (gap H1) were written after an external run with withheld faults named the gap; "
                "their kills of those faults are not independent evidence."
            ),
            (
                "Cases E21-E23 (gap I1), the rejection set (gap J1), the envelope checks and the metamorphic "
                "relations were written after a systematic mutation sweep over the checker named the gaps; "
                "their kills of those mutants are not independent evidence."
            ),
            (
                "The frozen v1 checker coerces a scope through dict(): a sequence of pairs is accepted as a "
                "scope, and a non-mapping scope that dict() cannot convert raises TypeError. That behaviour "
                "is outside the contract this corpus pins, and it is recorded here rather than repaired, "
                "because the checker stays frozen."
            ),
            "A metamorphic relation that holds on this corpus is not a proof that it holds on every input.",
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
