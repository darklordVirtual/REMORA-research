"""Pre-register checker mutations using only the v1 checker and v1 cases."""

from __future__ import annotations

import difflib
import importlib.util
import itertools
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CHECKER = ROOT / "conformance/evidence-sufficiency-v1/checker.py"
CASES = ROOT / "conformance/evidence-sufficiency-v1/cases.json"
source = CHECKER.read_text(encoding="utf-8")
cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def module(text: str, name: str) -> types.ModuleType:
    result = types.ModuleType(name)
    sys.modules[name] = result
    exec(compile(text, name, "exec"), result.__dict__)
    return result


base = module(source, "review_base_checker")


def candidate_inputs(claim: str):
    for case in cases:
        if case["claim"] != claim:
            continue
        original = case["observations"]
        yield original
        for key, value in original.items():
            if type(value) is bool:
                for alternative in (not value, None, 0, 1):
                    changed = dict(original)
                    changed[key] = alternative
                    yield changed
        # Two-field perturbations expose interactions among successive guards.
        bools = [key for key, value in original.items() if type(value) is bool]
        for first, second in itertools.combinations(bools, 2):
            changed = dict(original)
            changed[first] = not changed[first]
            changed[second] = not changed[second]
            yield changed


def assess(mod, claim: str, observations: dict):
    try:
        return mod.assess(claim, observations).as_dict()
    except Exception as exc:
        return {"exception": type(exc).__name__, "message": str(exc)}


def define(fault_id: str, old: str, new: str, *, systematic: bool = False, offset: int | None = None):
    if offset is None:
        if source.count(old) != 1:
            raise RuntimeError(f"{fault_id}: match count {source.count(old)}")
        position = source.index(old)
    else:
        position = offset
        if source[position:position + len(old)] != old:
            raise RuntimeError(f"{fault_id}: wrong offset")
    changed = source[:position] + new + source[position + len(old):]
    mutant = module(changed, "review_" + fault_id)
    witness = None
    for claim in base.ASSESSORS:
        for observations in candidate_inputs(claim):
            correct = assess(base, claim, observations)
            wrong = assess(mutant, claim, observations)
            if correct != wrong:
                witness = {"claim": claim, "observations": observations,
                           "original_output": correct, "expected_wrong_output": wrong}
                break
        if witness:
            break
    if witness is None:
        raise RuntimeError(f"{fault_id}: no observable witness")
    diff = "".join(difflib.unified_diff(source.splitlines(keepends=True), changed.splitlines(keepends=True),
                                        fromfile="checker.py", tofile="checker.py"))
    return {"id": fault_id, "class": "systematic" if systematic else "hand_picked",
            "operator": "is not True -> is not False" if systematic else "single replacement",
            "old": old, "new": new, "offset": position,
            "unified_diff": diff, "witness_input": {"claim": witness["claim"],
            "observations": witness["observations"]},
            "original_output": witness["original_output"],
            "expected_wrong_output": witness["expected_wrong_output"]}


hand_picked = [
    ("H01", 'o.get("effect_source_accepted") is not True or o.get("effect_seen") is not True', 'o.get("effect_seen") is not True or o.get("effect_seen") is not True'),
    ("H02", 'o.get("effect_seen") is not True:', 'o.get("effect_source_accepted") is not True:'),
    ("H03", 'if o.get("scope_accepted") is not True:', 'if o.get("effect_source_accepted") is not True:'),
    ("H04", 'if o.get("admission_source_accepted") is not True:', 'if o.get("scope_accepted") is not True:'),
    ("H05", 'if o.get("admission_matches") is True:', 'if o.get("admission_present") is True:'),
    ("H06", 'if o.get("admission_present") is not False:', 'if o.get("admission_present") is not None:'),
    ("H07", 'if o.get("mandatory_admission") is not True:', 'if o.get("window_finalized") is not True:'),
    ("H08", 'if o.get("window_finalized") is not True:', 'if o.get("admission_coverage_complete") is not True:'),
    ("H09", 'if o.get("admission_coverage_complete") is not True:', 'if o.get("window_finalized") is not True:'),
    ("H10", 'if o.get("route_observation_accepted") is not True:', 'if o.get("effect_observation_accepted") is not True:'),
    ("H11", 'if o.get("same_protected_operation") is not True:', 'if o.get("outside_required_pep") is not True:'),
    ("H12", 'if o.get("outside_required_pep") is not True:', 'if o.get("same_protected_operation") is not True:'),
    ("H13", 'if o.get("effect_observation_accepted") is not True:', 'if o.get("route_observation_accepted") is not True:'),
    ("H14", 'if o.get("protected_effect_observed") is True:', 'if o.get("effect_window_complete") is True:'),
    ("H15", 'if o.get("protected_effect_observed") is not False:', 'if o.get("protected_effect_observed") is None:'),
    ("H16", 'if o.get("effect_window_complete") is not True:', 'if o.get("valid_control_same_context") is not True:'),
    ("H17", 'if o.get("valid_control_same_context") is not True:', 'if o.get("effect_window_complete") is not True:'),
    ("H18", 'if o.get("required_boundary_refusal_accepted") is not True:', 'if o.get("valid_control_same_context") is not True:'),
    ("H19", 'if o.get("readback_available") is not True:', 'if o.get("source_accepted") is not True:'),
    ("H20", 'if o.get("source_accepted") is not True:', 'if o.get("readback_available") is not True:'),
    ("H21", 'if o.get("same_target_and_predicate") is not True:', 'if o.get("fresh_in_declared_window") is not True:'),
    ("H22", 'if o.get("fresh_in_declared_window") is not True:', 'if o.get("settlement_reached") is not True:'),
    ("H23", 'if o.get("settlement_reached") is not True:', 'if o.get("fresh_in_declared_window") is not True:'),
    ("H24", 'canonical(o["expected_state"]) == canonical(o["observed_state"])', 'o["expected_state"] == o["observed_state"]'),
]

faults = [define(*item) for item in hand_picked]
matches = list(re.finditer(r"\bis not True\b", source))
for index, match in enumerate(matches, 1):
    faults.append(define(f"S{index:02d}", "is not True", "is not False",
                         systematic=True, offset=match.start()))

output = {"source_commit": "c9113a0", "source_files": [str(CHECKER.relative_to(ROOT)), str(CASES.relative_to(ROOT))],
          "systematic_operator": "each occurrence of `is not True` replaced by `is not False`",
          "systematic_denominator": len(matches), "faults": faults}
(OUT / "fault-definitions.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"pre-registered {len(hand_picked)} hand-picked and {len(matches)} systematic faults")
