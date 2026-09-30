# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the evidence-sufficiency-v1.6 corpus against the frozen v1 checker.

v1.6 is v1.5 verbatim plus section 16, a differential test of the whole public
API against an executable contract. Every earlier section compares verdicts
through `as_dict()` or `(status, reason)`, and a held-out probe found a fault
outside that view (NEGATIVE_RESULTS.md §71). Section 16 draws some two thousand
inputs from a seeded generator and compares, for each, every projection a
caller can observe: the returned dictionary with exact types, the verdict
object's value semantics under repetition, copy, pickling and repr, the enum
contract, deep non-mutation of the inputs, and the module's own state before
and after the batch. It names no fault.

v1.5 replaces fault lists with classes. It is v1.4 verbatim plus the cases that
rule-coverage profile v2 derives from `model.json` (gap N1: every value class of
every premise on and off each decisive path, every ordered pair of failing
guards, and a fixed set of state pairs), a wider model lattice, and three
sections whose inputs are generated from type classes rather than listed:
section 13 checks profile v2, section 14 the input contract (container types,
non-JSON values at every position, variants of `premise_source` and the claim),
and section 15 that no returned value aliases the verdict or the caller's input.
The v1.3 spec, section 15, records why: a blind probe (NEGATIVE_RESULTS.md §70)
found the faults that no fault list had reached lay in exactly these classes.

v1.4 is v1.3 verbatim plus the 22 cases (gap L1) that the rule-coverage
derivation of the v1.3 spec, section 14, produces, and one new check: section
12 fails on any rule-coverage obligation of `model.json` that no authored case
discharges. The obligations are defined from the model alone, in the manner of
modified condition/decision coverage per decisive outcome (Chilenski and
Miller, 1994), so a later change to the model creates its own obligations and
needs no new fault list. Everything below about v1.3 still holds.

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

Section 11 is differential (McKeeman, 1998): `model.json` is a table-driven
reference model of the checker, written from the v1 README and the declared
ladders, and the checker must agree with it on every point of a bounded premise
lattice. A fault that changes any verdict on that lattice is therefore caught
whether or not an authored case reaches it, which is what moves the corpus's
discrimination from the cases somebody wrote to the input space itself.

The checker is imported from `../evidence-sufficiency-v1/checker.py`; its
sha256 is recorded, never enforced as a failure, so a seeded-fault measurement
of this runner stays meaningful. `build_record` takes an optional checker module
so a test can score a deliberately faulty checker without touching the file.
"""
from __future__ import annotations

import argparse
import ast
import collections
import copy
import pickle
import random
import dataclasses
import decimal
import enum
import hashlib
import importlib.util
import itertools
import json
import sys
from collections import Counter
from copy import deepcopy
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType, ModuleType

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "evidence-sufficiency-v1"
CHECKER_PATH = V1 / "checker.py"
FROZEN_CHECKER_SHA256 = "c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0"
SUITE = "evidence-sufficiency-v1.6"

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
    "R18_list_subclass_state": {"expected_state": type("List", (list,), {})(["closed"])},
    "R19_dict_subclass_state": {"expected_state": type("Dict", (dict,), {})({"state": "closed"})},
    "R20_str_subclass_key_in_nested_mapping": {"expected_state": {type("Key", (str,), {})("state"): "closed"}},
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


def interpret_model(model: dict, claim: str, obs: dict) -> tuple[str, str]:
    """(status, reason) the table-driven model gives for one observation set."""

    def holds(field: str, predicate: str) -> bool:
        if predicate == "is_true":
            return field in obs and obs[field] is True
        if predicate == "is_false":
            return field in obs and obs[field] is False
        raise ValueError(f"unknown predicate {predicate}")

    def run(steps: list[dict]) -> tuple[str, str]:
        for step in steps:
            if "require" in step:
                if all(holds(f, pred) for f, pred in step["require"].items()):
                    if "then" in step:
                        return step["then"]["status"], step["then"]["reason"]
                    continue
                return "not_established", step["else"]
            if "branch" in step:
                field = step["branch"]
                if field in obs and obs[field] is True:
                    return run(step["when_true"])
                if field in obs and obs[field] is False:
                    return run(step["when_false"])
                return "not_established", step["otherwise"]
            if "compare" in step:
                a, b = step["compare"]
                if a not in obs or b not in obs:
                    return "not_established", step["missing"]
                outcome = step["equal"] if _same_json(obs[a], obs[b]) else step["different"]
                return outcome["status"], outcome["reason"]
            if "terminal" in step:
                return step["terminal"]["status"], step["terminal"]["reason"]
            raise ValueError(f"unknown step {sorted(step)}")
        raise ValueError("ladder ended without a verdict")

    return run(model["claims"][claim]["steps"])


def model_reason_order(steps: list[dict]) -> list[str]:
    """Reasons in the order the model can first fail them, depth first."""
    order: list[str] = []
    for step in steps:
        if "require" in step:
            order.append(step["else"])
        elif "branch" in step:
            order.append(step["otherwise"])
            order.extend(model_reason_order(step["when_true"]))
            order.extend(model_reason_order(step["when_false"]))
        elif "compare" in step:
            order.append(step["missing"])
    return order


def model_reasons(steps: list[dict]) -> set[str]:
    reasons: set[str] = set()
    for step in steps:
        for key in ("else", "otherwise", "missing"):
            if key in step:
                reasons.add(step[key])
        for key in ("then", "terminal", "equal", "different"):
            if key in step:
                reasons.add(step[key]["reason"])
        for key in ("when_true", "when_false"):
            if key in step:
                reasons |= model_reasons(step[key])
    return reasons


def decisive_paths(model: dict) -> list[tuple[str, dict, dict | None, tuple[str, str]]]:
    """(claim, path condition, state pair or None, (status, reason)) for every decisive outcome.

    The same definition as scripts/rule_coverage_evidence_sufficiency.py; a test pins that
    both give the same obligations, so the runner stays standalone.
    """
    out: list[tuple[str, dict, dict | None, tuple[str, str]]] = []

    def walk(claim: str, steps: list[dict], cond: dict) -> None:
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


def rule_obligations(model: dict) -> list[dict]:
    """RC-1 (off-path independence), RC-2 (on-path necessity), RC-3 (on-path typing)."""
    out = []
    for claim, cond, _, outcome in decisive_paths(model):
        fields = model["claims"][claim]["fields"]
        out.extend({"rule": "RC-1", "claim": claim, "outcome": outcome, "premise": f, "path": cond}
                   for f in fields if f not in cond)
        for rule in ("RC-2", "RC-3"):
            out.extend({"rule": rule, "claim": claim, "outcome": outcome, "premise": f, "path": cond}
                       for f in fields if f in cond)
    return out


def rule_discharged(obligation: dict, cases: list[dict]) -> bool:
    premise, cond = obligation["premise"], obligation["path"]
    for case in cases:
        if case["claim"] != obligation["claim"]:
            continue
        obs = case["observations"]
        rest_met = all(f in obs and obs[f] is v for f, v in cond.items() if f != premise)
        if obligation["rule"] == "RC-1":
            if (case["expected"]["status"], case["expected"]["reason"]) == obligation["outcome"] and obs.get(premise) is False:
                return True
        elif obligation["rule"] == "RC-2":
            if rest_met and (premise not in obs or obs[premise] is (not cond[premise])):
                return True
        elif rest_met and premise in obs and type(obs[premise]) is not bool:
            return True
    return False


# ── Rule coverage profile v2 (section 13) ────────────────────────────────────
# The same definitions as scripts/rule_coverage_evidence_sufficiency.py (profile v2);
# a test pins that both give the same obligations, so the runner stays standalone.

VALUE_CLASSES = ("true", "false", "absent", "null", "one", "zero", "truthy", "falsy")
STATE_PAIRS: list[tuple] = [
    (None, None), (0, 0), (False, False), ("", ""), ([], []), ({}, {}), ([None], [None]),
    ({"lock": "held", "state": "closed"}, {"state": "closed", "lock": "held"}),
    ({"outer": {"x": 1, "y": 2}}, {"outer": {"y": 2, "x": 1}}),
    ("closed", "Closed"), ("closed", "closed "), (1, True), (True, 1), (0, False), (False, 0),
    (None, "null"), (None, 0), (None, False), ("", None), ([], {}), (["closed", "locked"], ["locked", "closed"]),
    ("\u00e9", "e\u0301"), ({"a": None}, {}), ([1], [True]), ("1", 1), (10**20, 10**20 + 1),
]


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


def _guard_premises(model: dict) -> list[tuple]:
    out: list[tuple] = []

    def walk(claim: str, steps: list[dict], cond: dict, guards: list[str]) -> None:
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


def rule_obligations_v2(model: dict) -> list[dict]:
    out: list[dict] = []
    for claim, cond, states, outcome in decisive_paths(model):
        for field in model["claims"][claim]["fields"]:
            base_class = "true" if field not in cond else ("true" if cond[field] else "false")
            for cls in VALUE_CLASSES:
                if cls != base_class:
                    out.append({"rule": "RC-V", "claim": claim, "outcome": outcome, "premise": field,
                                "class": cls, "path": cond, "states": states})
    seen: set = set()
    for claim, cond, outcome, guards in _guard_premises(model):
        for i, first in enumerate(guards):
            for second in guards[i + 1:]:
                key = (claim, tuple(sorted(cond.items())), first, second)
                if key not in seen:
                    seen.add(key)
                    out.append({"rule": "RC-P", "claim": claim, "outcome": outcome, "premise": first,
                                "second": second, "path": cond, "states": None})
    for claim, cond, states, outcome in decisive_paths(model):
        if states and outcome[0] == "established":
            a, b = list(states)
            for left, right in STATE_PAIRS:
                out.append({"rule": "RC-S", "claim": claim, "outcome": outcome, "premise": a,
                            "pair": [left, right], "path": cond, "states": {a: left, b: right}})
    return out


def rule_discharged_v2(obligation: dict, cases: list[dict]) -> bool:
    claim, cond = obligation["claim"], obligation["path"]

    def meets(obs: dict, but: tuple) -> bool:
        return all(f in obs and obs[f] is v for f, v in cond.items() if f not in but)

    for case in cases:
        if case["claim"] != claim:
            continue
        obs = case["observations"]
        expected = (case["expected"]["status"], case["expected"]["reason"])
        if obligation["rule"] == "RC-V":
            premise = obligation["premise"]
            if value_class(obs, premise) != obligation["class"] or not meets(obs, (premise,)):
                continue
            if premise in cond or expected == tuple(obligation["outcome"]):
                return True
        elif obligation["rule"] == "RC-P":
            first, second = obligation["premise"], obligation["second"]
            if obs.get(first) is False and obs.get(second) is False and meets(obs, (first, second)):
                return True
        else:
            (a, left), (b, right) = obligation["states"].items()
            if a in obs and b in obs and meets(obs, ()) and _same_json(obs[a], left) and _same_json(obs[b], right):
                return True
    return False


# ── Generated input classes (sections 14 and 15) ─────────────────────────────


class _Str(str):
    pass


class _List(list):
    pass


class _Dict(dict):
    pass


class _Int(enum.IntEnum):
    ONE = 1


class _ReadOnly(Mapping):
    """A Mapping that is not a dict, as a caller's own container type might be."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


def non_json_values() -> dict[str, object]:
    """Values of every Python type class the fixture vocabulary excludes."""
    return {
        "float": 1.0, "negative_zero": -0.0, "nan": float("nan"), "inf": float("inf"),
        "complex": complex(1, 0), "decimal": decimal.Decimal("1"),
        "tuple": ("closed",), "empty_tuple": (), "set": {"closed"}, "frozenset": frozenset({"closed"}),
        "bytes": b"closed", "bytearray": bytearray(b"closed"), "range": range(1), "object": object(),
        "str_subclass": _Str("closed"), "list_subclass": _List(["closed"]), "dict_subclass": _Dict(state="closed"),
        "ordered_dict": collections.OrderedDict(state="closed"), "int_enum": _Int.ONE,
        "int_key": {1: "closed"}, "none_key": {None: "closed"}, "bool_key": {True: "closed"},
        "tuple_key": {("state",): "closed"}, "str_subclass_key": {_Str("state"): "closed"},
    }


def container_variants(obs: dict) -> dict[str, object]:
    return {
        "mapping_proxy": MappingProxyType(dict(obs)),
        "ordered_dict_reversed": collections.OrderedDict(reversed(list(obs.items()))),
        "read_only_mapping": _ReadOnly(dict(obs)),
    }


PREMISE_SOURCE_VARIANTS: list[object] = [
    "Synthetic_Fixture", "SYNTHETIC_FIXTURE", " synthetic_fixture", "synthetic_fixture ", "synthetic_fixture\n",
    "synthetic-fixture", "synthetic fixture", "synthetic_fixtures", "synthetic_fixtur\u0435", "", None, 0,
    b"synthetic_fixture", ["synthetic_fixture"], _Str("production"),
]


def claim_variants(claim: str) -> list[object]:
    return [claim.upper(), claim.title(), " " + claim, claim + " ", claim.replace("_", "-"), claim + "s",
            claim[:-1], None, 0, (claim,), claim.encode()]


# ── API differential (section 16) ─────────────────────────────────────────────

API_SEED = 20261003
#: Premises whose false value opens a second arm; the generator draws both arms.
BRANCH_FIELDS = {"admission_accounting": ("admission_present",), "tested_route_enforcement": ("protected_effect_observed",)}
API_INPUTS = 2000
DEFAULT_SCOPE = {"kind": "synthetic_fixture", "bounded": True}


def _gen_json(rng: random.Random, depth: int = 0):
    """A JSON value: scalars of every kind, Unicode, and lists and mappings to depth three."""
    roll = rng.random()
    if depth >= 3 or roll < 0.55:
        return rng.choice([
            None, True, False, 0, 1, -1, 2, 10**20, "", "closed", "Closed", "closed ", "\u00e9", "e\u0301",
            "null", "true", "0", "\u2603", "a" * rng.randint(1, 4),
        ])
    if roll < 0.78:
        return [_gen_json(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    keys = rng.sample(["a", "b", "state", "lock", "x", "", "\u00e9"], rng.randint(0, 3))
    return {k: _gen_json(rng, depth + 1) for k in keys}


def generated_api_inputs(model: dict, n: int = API_INPUTS, seed: int = API_SEED) -> list[tuple]:
    """(claim, observations, scope) triples: premises in every value class, states and extra keys of any JSON."""
    rng = random.Random(seed)
    premise_values = [True, False, None, 1, 0, "true", "", [True], {"value": True}]
    claims = list(model["claims"])
    out = []
    for i in range(n):
        claim = claims[i % len(claims)]
        spec = model["claims"][claim]
        obs: dict = {}
        if rng.random() < 0.6:
            # One deviation from a configuration that meets every guard: reaches every depth of
            # every ladder, and both arms of a branch premise.
            for field in spec["fields"]:
                obs[field] = True
            for field in BRANCH_FIELDS.get(claim, ()):
                obs[field] = rng.random() < 0.5
            field = rng.choice(spec["fields"])
            if rng.random() < 0.2:
                del obs[field]
            else:
                obs[field] = rng.choice(premise_values)
        else:
            for field in spec["fields"]:
                if rng.random() < 0.8:
                    obs[field] = rng.choice(premise_values)
        for field in spec.get("state_fields", []):
            if rng.random() < 0.92:
                obs[field] = _gen_json(rng)
        state_fields = spec.get("state_fields", [])
        if state_fields and state_fields[0] in obs and rng.random() < 0.5:
            # The same JSON value on both sides, keys in another order: the equal arm.
            obs[state_fields[1]] = _reorder(deepcopy(obs[state_fields[0]]))
        if rng.random() < 0.3:
            obs[rng.choice(["note", "extra", "\u00e9"])] = _gen_json(rng)
        scope_roll = rng.random()
        if scope_roll < 0.35:
            scope = None
        elif scope_roll < 0.45:
            scope = {}
        else:
            scope = {k: rng.choice([None, True, 0, 1, "x", "\u00e9", ""]) for k in rng.sample(["kind", "suite", "case", "t"], rng.randint(1, 3))}
        out.append((claim, obs, scope))
    return out


def reference_envelope(model: dict, guidance: dict, claim: str, obs: dict, scope) -> dict:
    """The verdict the contract prescribes, from model.json and guidance.json alone."""
    status, reason = interpret_model(model, claim, obs)
    out = {
        "claim": claim,
        "status": status,
        "reason": reason,
        "scope": dict(scope) if scope else dict(DEFAULT_SCOPE),
        "missing_evidence": list(guidance[reason]["missing_evidence"]) if status == "not_established" else [],
    }
    if status == "not_established":
        out["decisive_if"] = guidance[reason]["decisive_if"]
    return out


def _typed(value):
    """A value with its exact types spelled out, so 1 and true, list and tuple, stay apart."""
    if isinstance(value, dict):
        return ["dict", sorted((k, _typed(v)) for k, v in value.items())]
    if isinstance(value, (list, tuple)):
        return [type(value).__name__, [_typed(v) for v in value]]
    return [type(value).__name__, value]


def _module_state(module: ModuleType) -> str:
    """A fingerprint of every module-level container: a call must leave them as it found them."""
    parts = []
    for name in sorted(vars(module)):
        value = vars(module)[name]
        if isinstance(value, (dict, list, set, tuple)) and not name.startswith("__"):
            parts.append(f"{name}={value!r}")
    return "\n".join(parts)


def _is_subsequence(short: list[str], long: list[str]) -> bool:
    it = iter(long)
    return all(any(item == candidate for candidate in it) for item in short)


def build_record(checker_module: ModuleType | None = None) -> dict:
    chk = checker_module or checker
    module_state_at_start = _module_state(chk)
    EvidenceStatus = chk.EvidenceStatus
    assess = chk.assess
    canonical = chk.canonical

    corpus = load_json(HERE / "cases.json")
    guidance = load_json(HERE / "guidance.json")["guidance"]
    ladders = load_json(HERE / "ladders.json")
    invariants = load_json(HERE / "invariants.json")
    model = load_json(HERE / "model.json")
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
    reference: dict = {"documents": 0, "lattice_documents": 0, "typed_documents": 0, "authored_cases": 0,
                       "disagreements": [], "disagreement_count": 0, "ladders_consistent": True,
                       "reasons_consistent": True}
    rule_coverage: dict = {"obligations": 0, "discharged": 0, "open": []}
    rule_coverage_v2: dict = {"obligations": 0, "discharged": 0, "open": [], "by_rule": {}}
    contract: dict = {"container_checks": 0, "value_checks": 0, "premise_source_checks": 0, "claim_checks": 0, "failures": []}
    isolation_checks: dict = {"checks": 0, "failures": []}
    api: dict = {"inputs": 0, "projections": 0, "failures": [], "by_projection": {}}
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

    def section_reference_model() -> None:
        # 11. Differential reference model (new in v1.3): the checker must agree with model.json
        #     on every point of the premise lattice, on a typed sweep around each decisive
        #     configuration, and on every authored case. The model compares states
        #     structurally, never through canonical(), so the two disagree on any fault in
        #     either comparison.
        disagreements: list[str] = []

        def compare(claim: str, obs: dict, kind: str) -> tuple[str, str]:
            reference["documents"] += 1
            reference[kind] += 1
            expected = interpret_model(model, claim, obs)
            try:
                verdict = assess(claim, obs)
                actual = (verdict.status.value, verdict.reason)
            except Exception as exc:  # noqa: BLE001 - a raise on a valid lattice point is a disagreement
                actual = ("raised", type(exc).__name__)
            if actual != expected:
                disagreements.append(
                    f"{claim}:{json.dumps(obs, sort_keys=True)}:model={expected[0]}/{expected[1]}:checker={actual[0]}/{actual[1]}"
                )
            return expected

        premise_values = model["lattice"]["premise_values"]
        for claim, spec in model["claims"].items():
            fields = spec["fields"]
            state_fields = spec.get("state_fields", [])
            state_values = model["lattice"]["state_values"] if state_fields else [None]
            decisive_bases: dict[str, dict] = {}
            for combo in itertools.product(premise_values, repeat=len(fields)):
                base = {f: v for f, v in zip(fields, combo) if v != "absent"}
                if not state_fields:
                    status, _ = compare(claim, base, "lattice_documents")
                    if status != "not_established":
                        decisive_bases.setdefault(status, base)
                    continue
                for left in state_values:
                    for right in state_values:
                        obs = dict(base)
                        if left != "absent":
                            obs[state_fields[0]] = deepcopy(left)
                        if right != "absent":
                            obs[state_fields[1]] = deepcopy(right)
                        status, _ = compare(claim, obs, "lattice_documents")
                        if status != "not_established":
                            decisive_bases.setdefault(status, obs)
            # Typed sweep: one premise at a time takes a value outside the boolean vocabulary,
            # around each decisive configuration the lattice reached.
            for base in decisive_bases.values():
                for field in fields:
                    for typed in model["lattice"]["typed_values"]:
                        compare(claim, {**deepcopy(base), field: deepcopy(typed)}, "typed_documents")
        for case in corpus["cases"]:
            reference["authored_cases"] += 1
            expected = interpret_model(model, case["claim"], case["observations"])
            if expected != (case["expected"]["status"], case["expected"]["reason"]):
                disagreements.append(f"authored:{case['id']}:model={expected[0]}/{expected[1]}")
        reference["disagreement_count"] = len(disagreements)
        reference["disagreements"] = disagreements[:25]
        if disagreements:
            failures.append(f"reference_model:disagreements:{len(disagreements)}")
        # Coherence: the model's reason order must contain every declared ladder as a
        # subsequence, and its reason set must equal the checker's vocabulary.
        for claim, segments in ladders["ladders"].items():
            order = model_reason_order(model["claims"][claim]["steps"])
            for name, seq in segments.items():
                if not _is_subsequence(seq, order):
                    reference["ladders_consistent"] = False
                    failures.append(f"model_ladder_mismatch:{claim}:{name}")
        declared_reasons = set()
        for spec in model["claims"].values():
            declared_reasons |= model_reasons(spec["steps"])
        vocabulary_reasons = vocabulary["inconclusive"] | vocabulary["decisive"]
        for reason in sorted(declared_reasons ^ vocabulary_reasons):
            reference["reasons_consistent"] = False
            failures.append(f"model_reason_mismatch:{reason}")

    def section_rule_coverage() -> None:
        # 12. Rule coverage (new in v1.4): every obligation of model.json has an authored witness.
        #     The obligations come from the model's decision ladders, not from a fault list.
        obligations = rule_obligations(model)
        rule_coverage["obligations"] = len(obligations)
        for obligation in obligations:
            if rule_discharged(obligation, corpus["cases"]):
                rule_coverage["discharged"] += 1
                continue
            label = f"{obligation['rule']}:{obligation['claim']}:{obligation['outcome'][1]}:{obligation['premise']}"
            rule_coverage["open"].append(label)
            failures.append(f"rule_coverage:{label}")

    def section_rule_coverage_v2() -> None:
        # 13. Rule coverage profile v2 (new in v1.5): value classes, guard precedence, state pairs.
        obligations = rule_obligations_v2(model)
        rule_coverage_v2["obligations"] = len(obligations)
        counts: Counter = Counter()
        for obligation in obligations:
            counts[obligation["rule"]] += 1
            if rule_discharged_v2(obligation, corpus["cases"]):
                rule_coverage_v2["discharged"] += 1
                continue
            detail = obligation.get("class") or obligation.get("second") or json.dumps(obligation.get("pair"))
            label = f"{obligation['rule']}:{obligation['claim']}:{obligation['outcome'][1]}:{obligation['premise']}:{detail}"
            rule_coverage_v2["open"].append(label)
            failures.append(f"rule_coverage_v2:{label}")
        rule_coverage_v2["by_rule"] = dict(sorted(counts.items()))

    def section_input_contract() -> None:
        # 14. Input contract over generated type classes (new in v1.5).
        def refused(label: str, call) -> None:
            try:
                call()
            except ValueError:
                return
            except Exception as exc:  # noqa: BLE001 - the class of the exception is the finding
                contract["failures"].append(f"{label}:raised_{type(exc).__name__}")
                return
            contract["failures"].append(f"{label}:accepted")

        # a. Any Mapping is observations: the verdict must not depend on the container type.
        for case in corpus["cases"]:
            expected = assess(case["claim"], deepcopy(case["observations"])).as_dict()
            for name, container in container_variants(deepcopy(case["observations"])).items():
                contract["container_checks"] += 1
                try:
                    got = assess(case["claim"], container).as_dict()
                except Exception as exc:  # noqa: BLE001
                    contract["failures"].append(f"container:{case['id']}:{name}:raised_{type(exc).__name__}")
                    continue
                if got != expected:
                    contract["failures"].append(f"container:{case['id']}:{name}:verdict_differs")
        # b. A non-JSON value at any position is refused, by assess and by canonical.
        valid = deepcopy(by_id["E01"]["observations"])
        for name, value in non_json_values().items():
            positions = {
                "premise": ("postcondition_observed", {**valid, "source_accepted": value}, None),
                "state": ("postcondition_observed", {**valid, "observed_state": value}, None),
                "state_list": ("postcondition_observed", {**valid, "observed_state": ["closed", value]}, None),
                "state_mapping": ("postcondition_observed", {**valid, "observed_state": {"inner": value}}, None),
                "scope_value": ("postcondition_observed", dict(valid), {"kind": "synthetic_fixture", "extra": value}),
            }
            for position, (claim, obs, scope) in positions.items():
                contract["value_checks"] += 1
                kwargs = {"scope": scope} if scope is not None else {}
                refused(f"value:{name}:{position}", lambda c=claim, o=obs, k=kwargs: assess(c, o, **k))
            contract["value_checks"] += 1
            refused(f"canonical:{name}", lambda v=value: canonical(v))
        # c. premise_source is compared exactly; every near miss is refused.
        for variant in PREMISE_SOURCE_VARIANTS:
            contract["premise_source_checks"] += 1
            refused(f"premise_source:{variant!r}", lambda v=variant: assess("postcondition_observed", dict(valid), premise_source=v))
        # d. The claim is matched exactly; every near miss is refused. Unhashable claims
        #    are outside the contract: the frozen checker raises TypeError for them.
        for claim_name in sorted({case["claim"] for case in corpus["cases"]}):
            for variant in claim_variants(claim_name):
                contract["claim_checks"] += 1
                refused(f"claim:{variant!r}", lambda v=variant: assess(v, dict(valid)))
        failures.extend(f"input_contract:{f}" for f in contract["failures"])

    def section_return_isolation() -> None:
        # 15. No returned value aliases the verdict, and no later change to the caller's
        #     input reaches it (new in v1.5). Top level only: the frozen checker copies the
        #     scope shallowly, which the record lists under limits.
        for case in corpus["cases"]:
            obs = deepcopy(case["observations"])
            scope = {"kind": "synthetic_fixture", "bounded": True, "case": case["id"]}
            verdict = assess(case["claim"], obs, scope=scope)
            before = json.dumps(verdict.as_dict(), sort_keys=True)
            returned = verdict.as_dict()
            returned["claim"] = "changed"
            returned["status"] = "changed"
            returned["scope"]["injected"] = True
            returned["missing_evidence"].append("injected")
            obs["injected"] = True
            for key in list(obs):
                if obs[key] is True:
                    obs[key] = False
            scope["kind"] = "changed"
            isolation_checks["checks"] += 1
            if json.dumps(verdict.as_dict(), sort_keys=True) != before:
                isolation_checks["failures"].append(case["id"])
        failures.extend(f"return_isolation:{f}" for f in isolation_checks["failures"])

    def section_api_differential() -> None:
        # 16. The whole public API against an executable contract, on generated inputs (new in v1.6).
        found: Counter = Counter()

        def fail(projection: str, index: int, detail: str = "") -> None:
            found[projection] += 1
            if found[projection] <= 3:
                api["failures"].append(f"{projection}:{index}{':' + detail if detail else ''}")

        # The enum contract: three members with fixed values, usable as their strings.
        if {m.value for m in EvidenceStatus} != {"established", "violated", "not_established"}:
            fail("enum_members", -1)
        for member in EvidenceStatus:
            if str(member) != member.value or member != member.value:
                fail("enum_str", -1, member.value)
        # Pickle finds a class through sys.modules; when several runners share a process, the
        # module registered under this checker's name may be another copy. Point it here for the run.
        registered = sys.modules.get(chk.__name__)
        sys.modules[chk.__name__] = chk
        inputs = generated_api_inputs(model)
        api["inputs"] = len(inputs)
        for index, (claim, obs, scope) in enumerate(inputs):
            snapshot = json.dumps(_typed(obs)), json.dumps(_typed(scope))
            kwargs = {"scope": scope} if scope is not None else {}
            try:
                first = assess(claim, obs, **kwargs)
                second = assess(claim, deepcopy(obs), **deepcopy(kwargs))
            except Exception as exc:  # noqa: BLE001 - a valid input must not raise
                fail("raised", index, type(exc).__name__)
                continue
            api["projections"] += 1
            expected = reference_envelope(model, guidance, claim, obs, scope)
            if _typed(first.as_dict()) != _typed(expected):
                fail("as_dict", index)
            if not isinstance(first.status, EvidenceStatus) or first.claim != claim or type(first.missing_evidence) is not tuple:
                fail("fields", index)
            if not (first == second and not (first != second)):
                fail("equality", index)
            if repr(first) != repr(second):
                fail("repr", index)
            if deepcopy(first) != first or copy.copy(first) != first:
                fail("copy", index)
            # Round-trips a verdict this process created a line earlier; no external data is unpickled.
            try:
                if pickle.loads(pickle.dumps(first)) != first:  # noqa: S301
                    fail("pickle", index)
            except Exception as exc:  # noqa: BLE001
                fail("pickle", index, type(exc).__name__)
            if (json.dumps(_typed(obs)), json.dumps(_typed(scope))) != snapshot:
                fail("input_mutated", index)
        # Order independence: the same inputs in another order give the same verdicts.
        shuffled = list(range(0, len(inputs), 7))
        random.Random(API_SEED + 1).shuffle(shuffled)
        for index in shuffled:
            claim, obs, scope = inputs[index]
            kwargs = {"scope": scope} if scope is not None else {}
            try:
                again = assess(claim, deepcopy(obs), **deepcopy(kwargs)).as_dict()
            except Exception as exc:  # noqa: BLE001
                fail("order", index, type(exc).__name__)
                continue
            if _typed(again) != _typed(reference_envelope(model, guidance, claim, obs, scope)):
                fail("order", index)
        if registered is None:
            sys.modules.pop(chk.__name__, None)
        else:
            sys.modules[chk.__name__] = registered
        if _module_state(chk) != module_state_at_start:
            fail("module_state", -1)
        api["by_projection"] = dict(sorted(found.items()))
        failures.extend(f"api_differential:{f}" for f in api["failures"])

    for fn in (section_authored_expectations, section_indistinguishable_worlds, section_evidence_erasure,
               section_wrong_shortcuts, section_empty_observations, section_reason_coverage,
               section_precedence_witnesses, section_isolation_witnesses, section_rejection_contract,
               section_metamorphic_relations, section_reference_model, section_rule_coverage,
               section_rule_coverage_v2, section_input_contract, section_return_isolation,
               section_api_differential):
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
            "model.json": sha256_file(HERE / "model.json"),
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
        "reference_model": reference,
        "rule_coverage": rule_coverage,
        "rule_coverage_v2": rule_coverage_v2,
        "input_contract": {k: (v[:25] if isinstance(v, list) else v) for k, v in contract.items()},
        "return_isolation": {"checks": isolation_checks["checks"], "failures": isolation_checks["failures"][:25]},
        "api_differential": api,
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
            (
                "Cases A26-A36 and B27-B37 (gap L1) were derived by the rule-coverage rule of the v1.3 spec, "
                "section 14, after specification mutation named five of the obligations they discharge "
                "(NEGATIVE_RESULTS.md §68); their kills of those twelve mutants are not independent evidence."
            ),
            (
                "Rule coverage is complete relative to the decision ladders of model.json: an obligation the model "
                "does not express, or a misreading the model shares with the checker, is not covered."
            ),
            (
                "Cases with gap N1 were derived by rule-coverage profile v2 (v1.3 spec, section 15) after a blind "
                "probe (NEGATIVE_RESULTS.md §70) named the classes they cover; their kills of that probe's faults "
                "are not independent evidence."
            ),
            (
                "The frozen checker copies a scope shallowly: a list or mapping nested in the caller's scope is "
                "shared with the verdict and with as_dict(). Section 15 pins top-level isolation only; a v2 checker "
                "should copy deeply. An unhashable claim raises TypeError, not ValueError, and is outside section 14."
            ),
            (
                "Section 16 compares the checker with an executable contract written by the same author from "
                "model.json and guidance.json; a misreading both share is not caught. Its inputs are a seeded sample "
                "of two thousand, not an enumeration. It was written after held-out probe 2 named one fault outside "
                "the as_dict() view (verdict equality); its kill of that fault is not independent evidence."
            ),
            "A metamorphic relation that holds on this corpus is not a proof that it holds on every input.",
            (
                "The reference model in model.json shares its author and its specification with the checker: "
                "agreement on the lattice catches an implementation slip in either and cannot catch a "
                "misreading both share. The lattice is bounded to the declared premise, typed and state values."
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
