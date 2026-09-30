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
    args = parser.parse_args(argv)
    model, cases = load_model(args.suite), load_cases(args.suite)
    if args.derive:
        text = json.dumps(derive(model, cases), indent=2, ensure_ascii=False) + "\n"
        if args.sha256:
            print(hashlib.sha256(text.encode("utf-8")).hexdigest())
        else:
            sys.stdout.write(text)
        return 0
    total = obligations(model)
    missing = uncovered(model, cases)
    print(f"{args.suite}: {len(total)} obligations, {len(total) - len(missing)} discharged, {len(missing)} open")
    for o in missing:
        print(f"  {o['rule']} {o['claim']} {o['outcome'][1]} {o['premise']}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
