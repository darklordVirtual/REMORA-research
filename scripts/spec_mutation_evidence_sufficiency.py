#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Specification mutation over the evidence-sufficiency reference model.

The two earlier operator sets (mutmut, and the AST set of
``mutation_evidence_sufficiency_ast.py``) mutate ``checker.py``, so the faults
they seed follow the shape of that one implementation. This script mutates the
specification instead: the rules of ``conformance/evidence-sufficiency-v1.3/model.json``
(Budd and Gopal, 1985, *Program testing by specification mutation*). A mutant is
a wrong reading of the rules, such as a premise read by truthiness, a missing
guard, two guards in the other order or a wrong verdict, whatever code would
carry it.

Each mutant model is turned into a checker: a fresh copy of the frozen checker
whose three assessors are replaced by an interpreter over the mutant model, so
validation, the verdict envelope and the guidance table stay the checker's own.
It is then scored in the three rows of the external runs:

- row 1, ``status`` and ``reason`` of every authored case against its expectation;
- row 2, the guidance of every authored case against the unmutated checker;
- row 3, the v1.3 runner's ``failures`` list, with the checks each kill rests on.

Equivalence is decided, not argued. The model reads a premise only through the
predicates below, and every predicate gives one answer on each of eight value
classes (``true``, ``false``, absent, ``null``, ``1``, ``0``, a truthy
non-boolean, a falsy non-boolean). A premise whose reading no mutant edit
touched is read exactly (``is True`` or ``is False``), where the last five
classes behave as absent. So two models that agree on every combination of
three classes for untouched premises and eight for touched ones agree on every
premise value JSON can carry. The state comparison is decided on the model's
declared state values plus absence; that bound is stated, not proved complete.
A mutant equivalent on that domain is excluded from the denominator by
computation, with no hand label.

The operator catalogue is fixed before any score is read: ``--list`` prints it
and ``--catalogue-sha256`` its digest, which the v1.3 spec records (section 13)
together with the pass criterion.

Usage::

    python scripts/spec_mutation_evidence_sufficiency.py --list
    python scripts/spec_mutation_evidence_sufficiency.py --catalogue-sha256
    python scripts/spec_mutation_evidence_sufficiency.py --json out.json   # score everything
    python scripts/spec_mutation_evidence_sufficiency.py --workers 1       # in process
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "conformance" / "evidence-sufficiency-v1.3"
CHECKER = ROOT / "conformance" / "evidence-sufficiency-v1" / "checker.py"
RUNNER = V13 / "run_evidence_sufficiency.py"
MODEL = V13 / "model.json"
AST_SCRIPT = ROOT / "scripts" / "mutation_evidence_sufficiency_ast.py"

SECOND_ORDER_SAMPLE = 300
SEED = 20261001
STATUSES = ("established", "violated", "not_established")


class _Absent:
    """The value class of a premise that is not in the observations."""

    def __repr__(self) -> str:
        return "ABSENT"


ABSENT = _Absent()
#: One representative per value class, in a fixed order.
ALL_CLASSES: tuple[Any, ...] = (True, False, ABSENT, None, 1, 0, "true", "")
EXACT_CLASSES: tuple[Any, ...] = (True, False, ABSENT)


# ── Predicates ───────────────────────────────────────────────────────────────
# Each predicate is the reading a guard gives one premise. The original model
# uses only is_true and is_false; the others are the misreadings.


def _pred(name: str, present: bool, value: Any) -> bool:
    if name == "is_true":
        return present and value is True
    if name == "is_false":
        return present and value is False
    if name == "truthy":  # `if not o.get(f)` as the guard
        return present and bool(value)
    if name == "falsy":
        return present and not value
    if name == "eq_true":  # `!= True` as the guard: 1 passes
        return present and value == True  # noqa: E712 - the misreading under test
    if name == "eq_false":
        return present and value == False  # noqa: E712 - the misreading under test
    if name == "not_false":  # `is False` as the guard: absent passes
        return not (present and value is False)
    if name == "not_true":
        return not (present and value is True)
    if name == "not_none":  # `is None` as the guard: 0 and "" pass
        return present and value is not None
    if name == "present":  # `f not in o` as the guard
        return present
    if name == "any":
        return True
    raise ValueError(f"unknown predicate {name}")


def _same_json(a: Any, b: Any) -> bool:
    """Structural equality that keeps 1 and true apart (the runner's definition)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same_json(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same_json(x, y) for x, y in zip(a, b))
    return a == b


def _sorted_lists(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sorted_lists(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((_sorted_lists(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def _states_equal(mode: str, a: Any, b: Any) -> bool:
    if mode == "structural":
        return _same_json(a, b)
    if mode == "python_eq":  # raw ==, so 1 equals true
        return bool(a == b)
    if mode == "casefold":
        return json.dumps(a, sort_keys=True).casefold() == json.dumps(b, sort_keys=True).casefold()
    if mode == "unordered_lists":
        return _same_json(_sorted_lists(a), _sorted_lists(b))
    if mode == "keys_only":
        if isinstance(a, dict) and isinstance(b, dict):
            return sorted(a) == sorted(b)
        return _same_json(a, b)
    if mode == "string_form":
        return str(a) == str(b)
    raise ValueError(f"unknown comparison {mode}")


def interpret(model: dict, claim: str, obs: Any) -> tuple[str, str]:
    """(status, reason) of a possibly mutated model for one observation mapping."""

    def read(field: str, predicate: str) -> bool:
        present = field in obs
        return _pred(predicate, present, obs[field] if present else None)

    def run(steps: list[dict]) -> tuple[str, str]:
        for step in steps:
            if "require" in step:
                if all(read(f, p) for f, p in step["require"].items()):
                    if "then" in step:
                        return step["then"]["status"], step["then"]["reason"]
                    continue
                return "not_established", step["else"]
            if "branch" in step:
                field = step["branch"]
                if read(field, step.get("true_pred", "is_true")):
                    return run(step["when_true"])
                if read(field, step.get("false_pred", "is_false")):
                    return run(step["when_false"])
                return "not_established", step["otherwise"]
            if "compare" in step:
                a, b = step["compare"]
                if a not in obs or b not in obs:
                    missing = step.get("missing_as")
                    if missing:
                        return step[missing]["status"], step[missing]["reason"]
                    return "not_established", step["missing"]
                equal = _states_equal(step.get("mode", "structural"), obs[a], obs[b])
                outcome = step["equal"] if equal else step["different"]
                return outcome["status"], outcome["reason"]
            if "terminal" in step:
                return step["terminal"]["status"], step["terminal"]["reason"]
            raise ValueError(f"unknown step {sorted(step)}")
        raise ValueError("ladder ended without a verdict")

    return run(model["claims"][claim]["steps"])


# ── Step identity ────────────────────────────────────────────────────────────
# Every step gets a stable id ("claim/0", "claim/4/when_true/1", ...) so that an
# edit names the step it changes and two edits compose into a second-order mutant.


def _walk(steps: list[dict], prefix: str):
    for index, step in enumerate(steps):
        path = f"{prefix}/{index}"
        yield path, steps, index, step
        for arm in ("when_true", "when_false"):
            if arm in step:
                yield from _walk(step[arm], f"{path}/{arm}")


def tag(model: dict) -> dict:
    """A deep copy of the model with an ``_id`` on every step."""
    tagged = deepcopy(model)
    for claim, spec in tagged["claims"].items():
        for path, _, _, step in _walk(spec["steps"], claim):
            step["_id"] = path
    return tagged


def untag(model: dict) -> dict:
    clean = deepcopy(model)
    for claim, spec in clean["claims"].items():
        for _, _, _, step in _walk(spec["steps"], claim):
            step.pop("_id", None)
    return clean


def _find(model: dict, step_id: str) -> tuple[list[dict], int, dict]:
    claim = step_id.split("/", 1)[0]
    for _, body, index, step in _walk(model["claims"][claim]["steps"], claim):
        if step.get("_id") == step_id:
            return body, index, step
    raise KeyError(step_id)


# ── Operators ────────────────────────────────────────────────────────────────
# Each operator yields edits: (step id, touched premises, description, edit).
# An edit mutates a tagged model in place and raises KeyError when a step it
# names is gone, which is how a conflicting second-order pair is skipped.

Edit = Callable[[dict], None]


def _non_decisive(spec: dict) -> list[str]:
    reasons: list[str] = []
    for _, _, _, step in _walk(spec["steps"], ""):
        for key in ("else", "otherwise", "missing"):
            if key in step and step[key] not in reasons:
                reasons.append(step[key])
    return reasons


def _decisive(spec: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for _, _, _, step in _walk(spec["steps"], ""):
        for key in ("then", "terminal", "equal", "different"):
            if key in step:
                pair = (step[key]["status"], step[key]["reason"])
                if pair not in out:
                    out.append(pair)
    return out


def op_delete_guard(claim: str, spec: dict):
    for path, _, _, step in _walk(spec["steps"], claim):
        if "require" in step and "then" not in step:
            def edit(m: dict, sid: str = path) -> None:
                body, index, _ = _find(m, sid)
                del body[index]
            yield path, (), f"delete the guard failing with `{step['else']}`", edit


def op_swap_guards(claim: str, spec: dict):
    for path, body, index, step in _walk(spec["steps"], claim):
        if index + 1 >= len(body):
            continue
        nxt = body[index + 1]
        if "terminal" in nxt or "terminal" in step:
            continue
        first, second = step.get("_id", path), nxt.get("_id", f"{path.rsplit('/', 1)[0]}/{index + 1}")

        def edit(m: dict, a: str = first, b: str = second) -> None:
            body_a, i, _ = _find(m, a)
            body_b, j, _ = _find(m, b)
            if body_a is not body_b or j != i + 1:
                raise KeyError(b)
            body_a[i], body_a[j] = body_a[j], body_a[i]
        label = step.get("else") or step.get("otherwise") or step.get("missing")
        yield path, (), f"swap the step failing with `{label}` and the next step", edit


def op_drop_premise(claim: str, spec: dict):
    for path, _, _, step in _walk(spec["steps"], claim):
        if "require" in step and len(step["require"]) > 1:
            for field in step["require"]:
                def edit(m: dict, sid: str = path, f: str = field) -> None:
                    _, _, s = _find(m, sid)
                    if f not in s["require"] or len(s["require"]) < 2:
                        raise KeyError(f)
                    del s["require"][f]
                yield path, (), f"drop `{field}` from the guard failing with `{step['else']}`", edit


def op_add_premise(claim: str, spec: dict):
    fields = spec["fields"]
    for path, _, _, step in _walk(spec["steps"], claim):
        if "require" not in step:
            continue
        for field in fields:
            if field in step["require"]:
                continue

            def edit(m: dict, sid: str = path, f: str = field) -> None:
                _, _, s = _find(m, sid)
                if f in s["require"]:
                    raise KeyError(f)
                s["require"][f] = "is_true"
            yield path, (), f"also require `{field}` in the guard failing with `{step['else']}`", edit


REQUIRE_VARIANTS = ("truthy", "eq_true", "not_false", "present", "is_false")


def op_premise_reading(claim: str, spec: dict):
    for path, _, _, step in _walk(spec["steps"], claim):
        if "require" not in step:
            continue
        for field in step["require"]:
            for variant in REQUIRE_VARIANTS:
                def edit(m: dict, sid: str = path, f: str = field, v: str = variant) -> None:
                    _, _, s = _find(m, sid)
                    if f not in s["require"]:
                        raise KeyError(f)
                    s["require"][f] = v
                yield path, (field,), f"read `{field}` as `{variant}`", edit


BRANCH_TRUE_VARIANTS = ("truthy", "eq_true", "not_false")
BRANCH_FALSE_VARIANTS = ("falsy", "eq_false", "not_none", "not_true", "any")


def op_branch_reading(claim: str, spec: dict):
    for path, _, _, step in _walk(spec["steps"], claim):
        if "branch" not in step:
            continue
        field = step["branch"]
        for variant in BRANCH_TRUE_VARIANTS:
            def edit(m: dict, sid: str = path, v: str = variant) -> None:
                _, _, s = _find(m, sid)
                s["true_pred"] = v
            yield path, (field,), f"take the true arm of `{field}` on `{variant}`", edit
        for variant in BRANCH_FALSE_VARIANTS:
            def edit(m: dict, sid: str = path, v: str = variant) -> None:
                _, _, s = _find(m, sid)
                s["false_pred"] = v
            yield path, (field,), f"take the false arm of `{field}` on `{variant}`", edit

        def swap(m: dict, sid: str = path) -> None:
            _, _, s = _find(m, sid)
            s["when_true"], s["when_false"] = s["when_false"], s["when_true"]
        yield path, (), f"swap the arms of `{field}`", swap


def op_reason_swap(claim: str, spec: dict):
    reasons = _non_decisive(spec)
    for path, _, _, step in _walk(spec["steps"], claim):
        for key in ("else", "otherwise", "missing"):
            if key not in step:
                continue
            for other in reasons:
                if other == step[key]:
                    continue

                def edit(m: dict, sid: str = path, k: str = key, r: str = other) -> None:
                    _, _, s = _find(m, sid)
                    s[k] = r
                yield path, (), f"`{step[key]}` becomes `{other}`", edit


def op_verdict_swap(claim: str, spec: dict):
    decisive = _decisive(spec)
    for path, _, _, step in _walk(spec["steps"], claim):
        for key in ("then", "terminal", "equal", "different"):
            if key not in step:
                continue
            for status in STATUSES:
                if status == step[key]["status"]:
                    continue

                def edit(m: dict, sid: str = path, k: str = key, st: str = status) -> None:
                    _, _, s = _find(m, sid)
                    s[k] = {**s[k], "status": st}
                yield path, (), f"`{step[key]['reason']}` gets status `{status}`", edit
            for other_status, other_reason in decisive:
                if other_reason == step[key]["reason"]:
                    continue

                def edit(m: dict, sid: str = path, k: str = key, st: str = other_status, r: str = other_reason) -> None:
                    _, _, s = _find(m, sid)
                    s[k] = {"status": st, "reason": r}
                yield path, (), f"`{step[key]['reason']}` becomes `{other_status}/{other_reason}`", edit


COMPARE_MODES = ("python_eq", "casefold", "unordered_lists", "keys_only", "string_form")


def op_state_comparison(claim: str, spec: dict):
    for path, _, _, step in _walk(spec["steps"], claim):
        if "compare" not in step:
            continue
        for mode in COMPARE_MODES:
            def edit(m: dict, sid: str = path, md: str = mode) -> None:
                _, _, s = _find(m, sid)
                s["mode"] = md
            yield path, (), f"compare states by `{mode}`", edit
        for outcome in ("equal", "different"):
            def edit(m: dict, sid: str = path, o: str = outcome) -> None:
                _, _, s = _find(m, sid)
                s["missing_as"] = o
            yield path, (), f"a missing state counts as `{outcome}`", edit

        def invert(m: dict, sid: str = path) -> None:
            _, _, s = _find(m, sid)
            s["equal"], s["different"] = s["different"], s["equal"]
        yield path, (), "equal and different states swap verdicts", invert


OPERATORS = {
    "delete_guard": op_delete_guard,
    "swap_guards": op_swap_guards,
    "drop_premise": op_drop_premise,
    "add_premise": op_add_premise,
    "premise_reading": op_premise_reading,
    "branch_reading": op_branch_reading,
    "reason_swap": op_reason_swap,
    "verdict_swap": op_verdict_swap,
    "state_comparison": op_state_comparison,
}


def load_model() -> dict:
    return json.loads(MODEL.read_text(encoding="utf-8"))


def catalogue(model: dict | None = None) -> list[dict]:
    """Every first-order mutant: id, operator, claim, touched premises, the mutated model."""
    base = tag(model or load_model())
    mutants: list[dict] = []
    for claim, spec in base["claims"].items():
        for op_name, op in OPERATORS.items():
            for index, (step_id, touched, description, edit) in enumerate(op(claim, spec)):
                mutated = deepcopy(base)
                edit(mutated)
                mutants.append({
                    "id": f"{op_name}:{claim}:{index}",
                    "operator": op_name,
                    "claim": claim,
                    "step": step_id,
                    "touched": list(touched),
                    "description": description,
                    "order": 1,
                    "_edit": edit,
                    "model": untag(mutated),
                })
    return mutants


def second_order(first: list[dict], sample: int, seed: int, model: dict | None = None) -> list[dict]:
    """A fixed-seed sample of pairs on the same claim whose edits compose on distinct steps."""
    base = tag(model or load_model())
    rng = random.Random(seed)
    by_claim: dict[str, list[dict]] = {}
    for m in first:
        by_claim.setdefault(m["claim"], []).append(m)
    claims = sorted(by_claim)
    pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    attempts = 0
    while len(pairs) < sample and attempts < sample * 50:
        attempts += 1
        claim = rng.choice(claims)
        a, b = rng.sample(by_claim[claim], 2)
        key = tuple(sorted((a["id"], b["id"])))
        if key in seen or a["step"] == b["step"]:
            continue
        seen.add(key)  # type: ignore[arg-type]
        mutated = deepcopy(base)
        try:
            a["_edit"](mutated)
            b["_edit"](mutated)
        except KeyError:
            continue
        pairs.append({
            "id": f"second:{key[0]}+{key[1]}",
            "operator": "second_order",
            "claim": claim,
            "step": f"{a['step']}+{b['step']}",
            "touched": sorted(set(a["touched"]) | set(b["touched"])),
            "description": f"{a['description']} and {b['description']}",
            "order": 2,
            "model": untag(mutated),
        })
    return pairs


def _canonical_catalogue(mutants: list[dict]) -> str:
    lines = []
    for m in mutants:
        ladder = json.dumps(m["model"]["claims"][m["claim"]]["steps"], sort_keys=True, separators=(",", ":"))
        lines.append(f"{m['id']}\t{m['touched']}\t{m['description']}\t{ladder}")
    return "\n".join(lines) + "\n"


def catalogue_sha256(sample: int = SECOND_ORDER_SAMPLE, seed: int = SEED) -> str:
    first = catalogue()
    text = _canonical_catalogue(first + second_order(first, sample, seed))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Equivalence on the complete value-class domain ──────────────────────────


def domain(model: dict, claim: str, touched: list[str]):
    """Every observation set on which two models that differ only at ``touched`` can disagree."""
    spec = model["claims"][claim]
    fields = spec["fields"]
    classes = [ALL_CLASSES if f in touched else EXACT_CLASSES for f in fields]
    state_fields = spec.get("state_fields", [])
    states: list[Any] = [ABSENT] + list(model["lattice"]["state_values"][1:]) if state_fields else [None]
    for combo in itertools.product(*classes):
        base = {f: v for f, v in zip(fields, combo) if v is not ABSENT}
        if not state_fields:
            yield base
            continue
        for left in states:
            for right in states:
                obs = dict(base)
                if left is not ABSENT:
                    obs[state_fields[0]] = deepcopy(left)
                if right is not ABSENT:
                    obs[state_fields[1]] = deepcopy(right)
                yield obs


def equivalence_witness(original: dict, mutant: dict) -> dict | None:
    """The first domain point where the mutant and the original disagree, or None."""
    claim = mutant["claim"]
    for obs in domain(original, claim, mutant["touched"]):
        expected = interpret(original, claim, obs)
        actual = interpret(mutant["model"], claim, obs)
        if actual != expected:
            return {"claim": claim, "observations": obs, "model": list(expected), "mutant": list(actual)}
    return None


# ── Scoring ──────────────────────────────────────────────────────────────────

_CACHE: dict[str, Any] = {}


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _runner() -> ModuleType:
    if "runner" not in _CACHE:
        _CACHE["runner"] = _load("es_v1_3_runner_for_spec_mutation", RUNNER)
    return _CACHE["runner"]


def _label_of() -> Callable[[str], str]:
    if "label_of" not in _CACHE:
        _CACHE["label_of"] = _load("es_ast_labels_for_spec_mutation", AST_SCRIPT).label_of
    return _CACHE["label_of"]


def model_checker(model: dict, name: str) -> ModuleType:
    """A fresh copy of the frozen checker whose assessors interpret ``model``."""
    module = _load(name, CHECKER)

    def assessor(claim: str):
        def assess(o, scope):
            status, reason = interpret(model, claim, o)
            return module._result(claim, module.EvidenceStatus(status), reason, scope)
        return assess

    module.ASSESSORS = {claim: assessor(claim) for claim in module.ASSESSORS}
    return module


def _case_rows(module: ModuleType, base: ModuleType, cases: list[dict]) -> tuple[list[str], list[str]]:
    row1, row2 = [], []
    scope = {"kind": "synthetic_fixture", "suite": "evidence-sufficiency-v1.3", "bounded": True}
    for case in cases:
        kwargs = {"scope": {**scope, "case": case["id"]}}
        try:
            got = module.assess(case["claim"], deepcopy(case["observations"]), **kwargs).as_dict()
        except Exception:  # noqa: BLE001 - a crash kills on both rows
            row1.append(case["id"])
            row2.append(case["id"])
            continue
        want = base.assess(case["claim"], deepcopy(case["observations"]), **kwargs).as_dict()
        if (got["status"], got["reason"]) != (case["expected"]["status"], case["expected"]["reason"]):
            row1.append(case["id"])
        if (got["missing_evidence"], got.get("decisive_if")) != (want["missing_evidence"], want.get("decisive_if")):
            row2.append(case["id"])
    return row1, row2


def score(job: tuple[dict, dict]) -> dict:
    """All rows and the equivalence verdict for one mutant."""
    mutant, original = job
    runner = _runner()
    cases = runner.load_json(V13 / "cases.json")["cases"]
    name = "es_spec_mutant_" + hashlib.sha256(mutant["id"].encode()).hexdigest()[:16]
    module = model_checker(mutant["model"], name)
    try:
        row1, row2 = _case_rows(module, runner.checker, cases)
        record = runner.build_record(module)
    finally:
        sys.modules.pop(name, None)
    labels = sorted({_label_of()(f) for f in record["failures"]})
    witness = equivalence_witness(original, mutant)
    return {
        "id": mutant["id"], "operator": mutant["operator"], "claim": mutant["claim"], "order": mutant["order"],
        "description": mutant["description"], "touched": mutant["touched"],
        "equivalent": witness is None, "witness": witness,
        "row1_cases": row1, "row2_cases": row2, "row3_labels": labels,
        "row1_kill": bool(row1), "row2_kill": bool(row2), "row3_kill": bool(record["failures"]),
    }


def _summarise(rows: list[dict]) -> dict:
    def block(selected: list[dict]) -> dict:
        live = [r for r in selected if not r["equivalent"]]
        return {
            "mutants": len(selected),
            "equivalent": len(selected) - len(live),
            "non_equivalent": len(live),
            "row1_killed": sum(r["row1_kill"] for r in live),
            "row2_killed": sum(r["row2_kill"] for r in live),
            "row3_killed": sum(r["row3_kill"] for r in live),
            "row1_survivors": [r["id"] for r in live if not r["row1_kill"]],
            "row3_survivors": [r["id"] for r in live if not r["row3_kill"]],
            "equivalent_killed_on_row3": [r["id"] for r in selected if r["equivalent"] and r["row3_kill"]],
        }

    by_operator = {}
    for op in list(OPERATORS) + ["second_order"]:
        selected = [r for r in rows if r["operator"] == op]
        if selected:
            b = block(selected)
            by_operator[op] = {k: b[k] for k in ("mutants", "equivalent", "non_equivalent", "row1_killed", "row3_killed")}
    live_row3 = [r for r in rows if not r["equivalent"] and r["row3_kill"]]
    return {
        "first_order": block([r for r in rows if r["order"] == 1]),
        "second_order": block([r for r in rows if r["order"] == 2]),
        "by_operator": by_operator,
        "row3_labels_of_kills_missed_on_row1": dict(Counter(
            label for r in live_row3 if not r["row1_kill"] for label in r["row3_labels"]
        ).most_common()),
    }


def sweep(workers: int, sample: int = SECOND_ORDER_SAMPLE, seed: int = SEED, only: str | None = None) -> dict:
    original = load_model()
    first = catalogue(original)
    second = second_order(first, sample, seed, original)
    mutants = [m for m in first + second if not only or m["id"].startswith(only)]
    jobs = [({k: v for k, v in m.items() if k != "_edit"}, original) for m in mutants]
    # The unmutated model, as a checker, must pass the runner; otherwise no kill means anything.
    control = runner_failures_of(original)
    if control:
        raise SystemExit(f"the unmutated model fails the runner: {control[:5]}")
    if workers <= 1:
        rows = [score(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(score, jobs, chunksize=4))
    return {
        "model_sha256": hashlib.sha256(MODEL.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "catalogue_sha256": catalogue_sha256(sample, seed),
        "seed": seed,
        "second_order_sample": sample,
        "summary": _summarise(rows),
        "rows": rows,
    }


def runner_failures_of(model: dict) -> list[str]:
    name = "es_spec_mutation_control"
    module = model_checker(model, name)
    try:
        return list(_runner().build_record(module)["failures"])
    finally:
        sys.modules.pop(name, None)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="print the catalogue and exit")
    parser.add_argument("--catalogue-sha256", action="store_true", help="print the catalogue digest and exit")
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument("--workers", type=int, default=8, help="process pool size; 1 scores in process")
    parser.add_argument("--sample", type=int, default=SECOND_ORDER_SAMPLE, help="second-order pairs")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--only", help="score only mutants whose id starts with this prefix")
    args = parser.parse_args(argv)
    if args.list or args.catalogue_sha256:
        first = catalogue()
        mutants = first + second_order(first, args.sample, args.seed)
        if args.list:
            sys.stdout.write(_canonical_catalogue(mutants))
        else:
            print(hashlib.sha256(_canonical_catalogue(mutants).encode("utf-8")).hexdigest())
        return 0
    report = sweep(args.workers, args.sample, args.seed, args.only)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for order in ("first_order", "second_order"):
        s = report["summary"][order]
        print(f"{order}: {s['mutants']} mutants, {s['equivalent']} equivalent on the domain, "
              f"{s['non_equivalent']} live; killed on row 1 {s['row1_killed']}, row 2 {s['row2_killed']}, "
              f"row 3 {s['row3_killed']}")
        for mid in s["row3_survivors"]:
            print(f"  row-3 survivor {mid}")
        for mid in s["row1_survivors"]:
            print(f"  row-1 survivor {mid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
