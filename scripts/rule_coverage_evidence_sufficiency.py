#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Rule coverage: adequacy obligations the reference model imposes on the authored cases.

Every earlier adequacy measure of the evidence-sufficiency corpus is a list of
faults, and each list was scored after the cases it measured were written.
This module defines adequacy from the specification alone, in the manner of
modified condition/decision coverage (Chilenski and Miller, 1994) applied to
the decision ladders of ``model.json``. It needs no fault list.

For each claim, every decisive outcome ``t`` of the model has a path
condition: the premises the ladder reads on the way to ``t``, each with the
boolean it must have (``true`` for a ``require`` step, the arm's value for a
``branch`` step). Three obligations follow for the authored cases:

- RC-1, off-path independence: for every premise of the claim that the path
  to ``t`` does not read, some case expecting ``t`` sets it to ``false``. A
  checker that also required that premise would then disagree with the case.
- RC-2, on-path necessity: for every premise on the path, some case meets the
  path condition on every other premise and has this one at the opposite
  boolean or absent. That case shows the premise matters to ``t`` itself, not
  only to some other outcome that shares the guard.
- RC-3, on-path typing: the same, with the premise at a non-boolean value.

``derive`` turns every obligation a corpus leaves open into one case, by a
fixed rule: start from the configuration that meets the path condition with
every off-path premise ``true`` (both states ``"closed"`` for an equal
comparison, ``"closed"`` and ``"open"`` for a different one), then set the one
premise to ``false`` (RC-1), to the opposite boolean (RC-2) or to ``1`` for a
``true`` requirement and ``0`` for a ``false`` one (RC-3). The expected
verdict is the model's. Identical observation sets are merged, and case ids
continue each claim's numbering. The rule was fixed and pre-registered before
the cases it produces were scored against anything (v1.3 spec, section 14).

Usage::

    python scripts/rule_coverage_evidence_sufficiency.py --suite evidence-sufficiency-v1.3          # open obligations
    python scripts/rule_coverage_evidence_sufficiency.py --suite evidence-sufficiency-v1.3 --derive  # the cases that close them
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
PREFIX = {"admission_accounting": "A", "tested_route_enforcement": "B", "postcondition_observed": "E"}


def decisive_paths(model: dict) -> list[tuple[str, dict[str, bool], dict | None, tuple[str, str]]]:
    """(claim, path condition, state pair or None, (status, reason)) for every decisive outcome."""
    out: list[tuple[str, dict[str, bool], dict | None, tuple[str, str]]] = []

    def walk(claim: str, steps: list[dict], cond: dict[str, bool]) -> None:
        cond = dict(cond)
        for step in steps:
            if "require" in step:
                for field in step["require"]:
                    cond[field] = True
                if "then" in step:
                    out.append((claim, dict(cond), None, (step["then"]["status"], step["then"]["reason"])))
                    return
                continue
            if "branch" in step:
                walk(claim, step["when_true"], {**cond, step["branch"]: True})
                walk(claim, step["when_false"], {**cond, step["branch"]: False})
                return
            if "compare" in step:
                a, b = step["compare"]
                out.append((claim, dict(cond), {a: "closed", b: "closed"}, (step["equal"]["status"], step["equal"]["reason"])))
                out.append((claim, dict(cond), {a: "closed", b: "open"}, (step["different"]["status"], step["different"]["reason"])))
                return
            if "terminal" in step:
                out.append((claim, dict(cond), None, (step["terminal"]["status"], step["terminal"]["reason"])))
                return

    for claim, spec in model["claims"].items():
        walk(claim, spec["steps"], {})
    return out


def obligations(model: dict) -> list[dict]:
    """Every RC-1, RC-2 and RC-3 obligation of the model, in a fixed order."""
    out = []
    for claim, cond, states, outcome in decisive_paths(model):
        fields = model["claims"][claim]["fields"]
        for field in fields:
            if field not in cond:
                out.append({"rule": "RC-1", "claim": claim, "outcome": list(outcome), "premise": field,
                            "path": cond, "states": states})
        for kind in ("RC-2", "RC-3"):
            for field in fields:
                if field in cond:
                    out.append({"rule": kind, "claim": claim, "outcome": list(outcome), "premise": field,
                                "path": cond, "states": states})
    return out


def _meets(obs: dict, cond: dict[str, bool], but: str) -> bool:
    return all(field in obs and obs[field] is value for field, value in cond.items() if field != but)


def covered(obligation: dict, cases: list[dict]) -> bool:
    """Whether some authored case discharges the obligation."""
    claim, premise, cond = obligation["claim"], obligation["premise"], obligation["path"]
    outcome = tuple(obligation["outcome"])
    for case in cases:
        if case["claim"] != claim:
            continue
        obs = case["observations"]
        expected = (case["expected"]["status"], case["expected"]["reason"])
        if obligation["rule"] == "RC-1":
            if expected == outcome and obs.get(premise, None) is False:
                return True
        elif obligation["rule"] == "RC-2":
            if _meets(obs, cond, premise) and (premise not in obs or obs[premise] is (not cond[premise])):
                return True
        elif obligation["rule"] == "RC-3":
            if _meets(obs, cond, premise) and premise in obs and type(obs[premise]) is not bool:
                return True
    return False


def uncovered(model: dict, cases: list[dict]) -> list[dict]:
    return [o for o in obligations(model) if not covered(o, cases)]


def _interpret(model: dict, claim: str, obs: dict) -> tuple[str, str]:
    """The v1.3 runner's reading of the model (exact premises, structural states)."""

    def same(a: Any, b: Any) -> bool:
        if type(a) is not type(b):
            return False
        if isinstance(a, dict):
            return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
        if isinstance(a, list):
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        return a == b

    def run(steps: list[dict]) -> tuple[str, str]:
        for step in steps:
            if "require" in step:
                if all(f in obs and obs[f] is (p == "is_true") for f, p in step["require"].items()):
                    if "then" in step:
                        return step["then"]["status"], step["then"]["reason"]
                    continue
                return "not_established", step["else"]
            if "branch" in step:
                value = obs.get(step["branch"], None) if step["branch"] in obs else None
                if step["branch"] in obs and value is True:
                    return run(step["when_true"])
                if step["branch"] in obs and value is False:
                    return run(step["when_false"])
                return "not_established", step["otherwise"]
            if "compare" in step:
                a, b = step["compare"]
                if a not in obs or b not in obs:
                    return "not_established", step["missing"]
                outcome = step["equal"] if same(obs[a], obs[b]) else step["different"]
                return outcome["status"], outcome["reason"]
            if "terminal" in step:
                return step["terminal"]["status"], step["terminal"]["reason"]
        raise ValueError("ladder ended without a verdict")

    return run(model["claims"][claim]["steps"])


def derive(model: dict, cases: list[dict]) -> list[dict]:
    """One case per open obligation, by the fixed rule of the module docstring."""
    next_number = {claim: 0 for claim in PREFIX}
    for case in cases:
        prefix = PREFIX[case["claim"]]
        if case["id"].startswith(prefix) and case["id"][1:].isdigit():
            next_number[case["claim"]] = max(next_number[case["claim"]], int(case["id"][1:]))
    derived: list[dict] = []
    by_obs: dict[str, dict] = {}
    for obligation in uncovered(model, cases):
        claim, premise, cond = obligation["claim"], obligation["premise"], obligation["path"]
        fields = model["claims"][claim]["fields"]
        obs: dict[str, Any] = {field: cond.get(field, True) for field in fields}
        if obligation["states"]:
            obs.update(obligation["states"])
        if obligation["rule"] == "RC-1":
            obs[premise] = False
        elif obligation["rule"] == "RC-2":
            obs[premise] = not cond[premise]
        else:
            obs[premise] = 1 if cond[premise] else 0
        key = claim + json.dumps(obs, sort_keys=True)
        label = f"{obligation['rule']} {obligation['outcome'][1]} {premise}"
        if key in by_obs:
            by_obs[key]["obligations"].append(label)
            continue
        next_number[claim] += 1
        status, reason = _interpret(model, claim, obs)
        case = {
            "id": f"{PREFIX[claim]}{next_number[claim]:02d}",
            "claim": claim,
            "gap": "L1",
            "derived_from": "model.json rule-coverage obligations (v1.3 spec, section 14)",
            "observations": dict(sorted(obs.items())),
            "expected": {"status": status, "reason": reason},
            "obligations": [label],
            "rationale": _rationale(obligation, status, reason),
        }
        by_obs[key] = case
        derived.append(case)
    return derived


def _rationale(obligation: dict, status: str, reason: str) -> str:
    premise, outcome = obligation["premise"], obligation["outcome"][1]
    if obligation["rule"] == "RC-1":
        return (f"`{premise}` is not read on the path to `{outcome}`, so setting it to false must leave "
                f"that verdict; a checker that also required it would say otherwise")
    if obligation["rule"] == "RC-2":
        return (f"`{premise}` is on the path to `{outcome}`; with every other premise of that path met and "
                f"this one at the opposite boolean the verdict is `{status}/{reason}`, which shows the premise "
                f"matters to this outcome itself")
    return (f"`{premise}` is on the path to `{outcome}` and holds a non-boolean here; the verdict is "
            f"`{status}/{reason}`, so the premise must be read exactly on this path too")


# ── Profile v2 (v1.3 spec, section 15): value classes, precedence, state classes ──
#
# Profile v1 (RC-1 to RC-3) asks for one witness per premise and outcome. The blind
# probe of 2026-09-30 (NEGATIVE_RESULTS.md §70) found the three shapes it misses:
# absence as the third arm of a premise, the order of two failing guards, and state
# values outside the declared vocabulary. Profile v2 replaces the single witness with
# every value class, adds every ordered pair of guards on a path, and adds a fixed set
# of state pairs. The obligations still come from the model's ladders alone.

#: The value classes a premise can be in, with one representative each. Every
#: predicate a guard can apply (identity, equality, truthiness, presence) is constant
#: on each class, so a witness per class separates every such reading.
VALUE_CLASSES: dict[str, Any] = {
    "true": True,
    "false": False,
    "absent": None,  # the representative is "leave the key out"
    "null": None,
    "one": 1,
    "zero": 0,
    "truthy": "true",
    "falsy": "",
}


def value_class(obs: dict, field: str) -> str:
    if field not in obs:
        return "absent"
    value = obs[field]
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if type(value) is int and value == 1:
        return "one"
    if type(value) is int and value == 0:
        return "zero"
    return "truthy" if value else "falsy"


def _set_class(obs: dict, field: str, cls: str) -> None:
    if cls == "absent":
        obs.pop(field, None)
    else:
        obs[field] = VALUE_CLASSES[cls]


#: State pairs the postcondition comparison must decide as the model does. Each
#: pair is a value and a neighbour a normalising, loose or order-blind comparison
#: would confuse with it, or two spellings of one JSON value it must not tell apart.
STATE_PAIRS: list[tuple[Any, Any]] = [
    (None, None), (0, 0), (False, False), ("", ""), ([], []), ({}, {}), ([None], [None]),
    ({"lock": "held", "state": "closed"}, {"state": "closed", "lock": "held"}),
    ({"outer": {"x": 1, "y": 2}}, {"outer": {"y": 2, "x": 1}}),
    ("closed", "Closed"), ("closed", "closed "), (1, True), (True, 1), (0, False), (False, 0),
    (None, "null"), (None, 0), (None, False), ("", None), ([], {}), (["closed", "locked"], ["locked", "closed"]),
    ("é", "é"), ({"a": None}, {}), ([1], [True]), ("1", 1), (10**20, 10**20 + 1),
]


def _guard_premises(model: dict) -> list[tuple[str, dict[str, bool], tuple[str, str], list[str]]]:
    """(claim, path condition, outcome, the first premise of each require step on the path, in order)."""
    out = []

    def walk(claim: str, steps: list[dict], cond: dict[str, bool], guards: list[str]) -> None:
        cond, guards = dict(cond), list(guards)
        for step in steps:
            if "require" in step:
                for field in step["require"]:
                    cond[field] = True
                guards.append(next(iter(step["require"])))
                if "then" in step:
                    out.append((claim, dict(cond), (step["then"]["status"], step["then"]["reason"]), guards))
                    return
                continue
            if "branch" in step:
                walk(claim, step["when_true"], {**cond, step["branch"]: True}, guards)
                walk(claim, step["when_false"], {**cond, step["branch"]: False}, guards)
                return
            if "compare" in step:
                out.append((claim, dict(cond), (step["equal"]["status"], step["equal"]["reason"]), guards))
                return
            if "terminal" in step:
                out.append((claim, dict(cond), (step["terminal"]["status"], step["terminal"]["reason"]), guards))
                return

    for claim, spec in model["claims"].items():
        walk(claim, spec["steps"], {}, [])
    return out


def obligations_v2(model: dict) -> list[dict]:
    """RC-V (value classes), RC-P (guard precedence) and RC-S (state pairs), in a fixed order."""
    out: list[dict] = []
    for claim, cond, states, outcome in decisive_paths(model):
        for field in model["claims"][claim]["fields"]:
            base_class = "true" if field not in cond else ("true" if cond[field] else "false")
            for cls in VALUE_CLASSES:
                if cls == base_class:
                    continue
                out.append({"rule": "RC-V", "claim": claim, "outcome": list(outcome), "premise": field,
                            "class": cls, "path": cond, "states": states})
    seen: set[tuple] = set()
    for claim, cond, outcome, guards in _guard_premises(model):
        for i, first in enumerate(guards):
            for second in guards[i + 1:]:
                key = (claim, tuple(sorted(cond.items())), first, second)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"rule": "RC-P", "claim": claim, "outcome": list(outcome), "premise": first,
                            "second": second, "path": cond, "states": None})
    for claim, cond, states, outcome in decisive_paths(model):
        if not states or outcome[0] != "established":
            continue
        a, b = list(states)
        for left, right in STATE_PAIRS:
            out.append({"rule": "RC-S", "claim": claim, "outcome": list(outcome), "premise": a,
                        "pair": [left, right], "path": cond, "states": {a: left, b: right}})
    return out


def _same(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return bool(a == b)


def covered_v2(obligation: dict, cases: list[dict]) -> bool:
    claim, cond = obligation["claim"], obligation["path"]
    for case in cases:
        if case["claim"] != claim:
            continue
        obs = case["observations"]
        expected = (case["expected"]["status"], case["expected"]["reason"])
        if obligation["rule"] == "RC-V":
            premise, cls = obligation["premise"], obligation["class"]
            if value_class(obs, premise) != cls:
                continue
            if premise in cond:
                if _meets(obs, cond, premise):
                    return True
            elif expected == tuple(obligation["outcome"]) and _meets(obs, cond, premise):
                return True
        elif obligation["rule"] == "RC-P":
            first, second = obligation["premise"], obligation["second"]
            rest = {f: v for f, v in cond.items() if f not in (first, second)}
            if obs.get(first) is False and obs.get(second) is False and all(
                f in obs and obs[f] is v for f, v in rest.items()
            ):
                return True
        elif obligation["rule"] == "RC-S":
            (a, left), (b, right) = obligation["states"].items()
            if a in obs and b in obs and _meets(obs, cond, "") and _same(obs[a], left) and _same(obs[b], right):
                return True
    return False


def uncovered_v2(model: dict, cases: list[dict]) -> list[dict]:
    return [o for o in obligations_v2(model) if not covered_v2(o, cases)]


def _label_v2(o: dict) -> str:
    if o["rule"] == "RC-V":
        return f"RC-V {o['outcome'][1]} {o['premise']}={o['class']}"
    if o["rule"] == "RC-P":
        return f"RC-P {o['claim']} {o['premise']}>{o['second']}"
    return f"RC-S {o['claim']} {json.dumps(o['pair'])}"


def derive_v2(model: dict, cases: list[dict], gap: str = "N1") -> list[dict]:
    """One case per open profile-v2 obligation, by the same construction rule as ``derive``."""
    next_number = {claim: 0 for claim in PREFIX}
    for case in cases:
        prefix = PREFIX[case["claim"]]
        if case["id"].startswith(prefix) and case["id"][1:].isdigit():
            next_number[case["claim"]] = max(next_number[case["claim"]], int(case["id"][1:]))
    derived: list[dict] = []
    by_obs: dict[str, dict] = {}
    for o in uncovered_v2(model, cases):
        claim, cond = o["claim"], o["path"]
        fields = model["claims"][claim]["fields"]
        obs: dict[str, Any] = {field: cond.get(field, True) for field in fields}
        if o["rule"] == "RC-V":
            if o["states"]:
                obs.update(o["states"])
            _set_class(obs, o["premise"], o["class"])
        elif o["rule"] == "RC-P":
            if claim == "postcondition_observed":
                obs.update({"expected_state": "closed", "observed_state": "closed"})
            obs[o["premise"]] = False
            obs[o["second"]] = False
        else:
            obs.update(deepcopy(o["states"]))
        key = claim + json.dumps(obs, sort_keys=True)
        label = _label_v2(o)
        if key in by_obs:
            by_obs[key]["obligations"].append(label)
            continue
        next_number[claim] += 1
        status, reason = _interpret(model, claim, obs)
        case = {
            "id": f"{PREFIX[claim]}{next_number[claim]:02d}",
            "claim": claim,
            "gap": gap,
            "derived_from": "model.json rule-coverage profile v2 (v1.3 spec, section 15)",
            "observations": dict(sorted(obs.items())),
            "expected": {"status": status, "reason": reason},
            "obligations": [label],
            "rationale": f"derived to discharge {label}; the expected verdict is the model's",
        }
        by_obs[key] = case
        derived.append(case)
    return derived


def load_cases(suite: str) -> list[dict]:
    return json.loads((CONFORMANCE / suite / "cases.json").read_text(encoding="utf-8"))["cases"]


def load_model(suite: str) -> dict:
    path = CONFORMANCE / suite / "model.json"
    if not path.exists():
        path = CONFORMANCE / "evidence-sufficiency-v1.3" / "model.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", default="evidence-sufficiency-v1.3")
    parser.add_argument("--derive", action="store_true", help="print the cases that close every open obligation")
    parser.add_argument("--sha256", action="store_true", help="with --derive, print only the digest of the derived cases")
    parser.add_argument("--profile", choices=("v1", "v2"), default="v1",
                        help="v1: RC-1 to RC-3 (section 14); v2: RC-V, RC-P and RC-S (section 15)")
    args = parser.parse_args(argv)
    model, cases = load_model(args.suite), load_cases(args.suite)
    if args.derive:
        rows = derive(model, cases) if args.profile == "v1" else derive_v2(model, cases)
        text = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
        if args.sha256:
            print(hashlib.sha256(text.encode("utf-8")).hexdigest())
        else:
            sys.stdout.buffer.write(text.encode("utf-8"))
        return 0
    if args.profile == "v2":
        total, missing = obligations_v2(model), uncovered_v2(model, cases)
    else:
        total, missing = obligations(model), uncovered(model, cases)
    print(f"{args.suite} ({args.profile}): {len(total)} obligations, {len(total) - len(missing)} discharged, {len(missing)} open")
    for o in missing:
        print(f"  {o['rule']} {o['claim']} {o['outcome'][1]} {o['premise']}" if args.profile == "v1" else f"  {_label_v2(o)}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
