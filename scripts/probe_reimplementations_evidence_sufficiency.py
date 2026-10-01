#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Score independent reimplementations of the evidence-sufficiency assessors against the corpora.

Every other adequacy measure seeds faults into ``checker.py`` or into
``model.json``. This one takes implementations written by someone else from a
prose specification, without the checker or the corpus in view, including
variants that each carry one misreading of that specification. Their faults
are the ones a second implementer makes, not the ones an operator generates.

Each module defines ``admission_accounting``, ``tested_route_enforcement`` and
``postcondition_observed``, each taking the observations and returning
``(status, reason)``. The module is plugged into a fresh copy of the frozen
checker in place of its three assessors, so validation, the verdict envelope
and the guidance table stay the checker's own, and scored in the three rows
of ``scripts/score_heldout_faults.py``.

Whether a variant is a fault at all is decided by differential testing against
``model.json`` on a probe domain: every premise at ``true``, ``false`` or
absent, then each premise in turn at each of eight value classes with the
others on that lattice, and the state pair over the model's declared state
values plus extra values a normalising comparison would confuse. A variant
that agrees with the model on the whole domain is reported as not a fault on
that domain; the domain is bounded, so that is not a proof of equivalence.

Usage::

    python scripts/probe_reimplementations_evidence_sufficiency.py DIR [DIR ...] --json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
MODEL = CONFORMANCE / "evidence-sufficiency-v1.3" / "model.json"
SUITES = ("evidence-sufficiency-v1.2", "evidence-sufficiency-v1.3", "evidence-sufficiency-v1.4", "evidence-sufficiency-v1.5", "evidence-sufficiency-v1.6", "evidence-sufficiency-v1.7")
CLAIMS = ("admission_accounting", "tested_route_enforcement", "postcondition_observed")
_ABSENT = object()
EXACT = (True, False, _ABSENT)
CLASSES = (True, False, _ABSENT, None, 1, 0, "true", "")
EXTRA_STATES = ["closed ", "CLOSED", None, 0, False, "", [], {}, ["closed"], [True], [1], {"state": "CLOSED"}]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _harness() -> ModuleType:
    return _load("probe_heldout_harness", ROOT / "scripts" / "score_heldout_faults.py")


def _model_runner() -> ModuleType:
    return _load("probe_model_runner", CONFORMANCE / "evidence-sufficiency-v1.3" / "run_evidence_sufficiency.py")


def implementation_checker(impl: ModuleType, name: str) -> ModuleType:
    """A fresh copy of the frozen checker whose assessors call ``impl``."""
    checker = _load(name, CONFORMANCE / "evidence-sufficiency-v1" / "checker.py")

    def wrap(claim: str):
        fn = getattr(impl, claim)

        def assess(o, scope):
            status, reason = fn(dict(o))
            return checker._result(claim, checker.EvidenceStatus(status), reason, scope)
        # Named after the claim, like the assessor it replaces, so the claim table of the
        # public API surface (runner section 17) is unchanged by the substitution itself.
        assess.__name__ = assess.__qualname__ = claim
        return assess

    setattr(checker, "ASSESSORS", {claim: wrap(claim) for claim in CLAIMS})
    return checker


def probe_domain(model: dict, claim: str):
    spec = model["claims"][claim]
    fields = spec["fields"]
    state_fields = spec.get("state_fields", [])
    states: list[Any] = [_ABSENT] + list(model["lattice"]["state_values"][1:]) + EXTRA_STATES if state_fields else [None]

    def with_states(base: dict):
        if not state_fields:
            yield base
            return
        for left in states:
            for right in states:
                obs = dict(base)
                if left is not _ABSENT:
                    obs[state_fields[0]] = deepcopy(left)
                if right is not _ABSENT:
                    obs[state_fields[1]] = deepcopy(right)
                yield obs

    for combo in itertools.product(EXACT, repeat=len(fields)):
        yield from with_states({f: v for f, v in zip(fields, combo) if v is not _ABSENT})
    for i, field in enumerate(fields):
        others = [f for f in fields if f != field]
        for value in CLASSES[3:]:
            for combo in itertools.product(EXACT, repeat=len(others)):
                base = {f: v for f, v in zip(others, combo) if v is not _ABSENT}
                base[field] = value
                if state_fields:
                    base["expected_state"], base["observed_state"] = "closed", "closed"
                yield base


def fault_witness(impl: ModuleType, model: dict, interpret) -> dict | None:
    """The first probe point where the implementation disagrees with the model, or None."""
    for claim in CLAIMS:
        fn = getattr(impl, claim)
        for obs in probe_domain(model, claim):
            expected = interpret(model, claim, obs)
            try:
                actual = tuple(fn(deepcopy(obs)))
            except Exception as exc:  # noqa: BLE001 - a raise on valid input is a disagreement
                actual = ("raised", type(exc).__name__)
            if actual != expected:
                return {"claim": claim, "observations": obs, "model": list(expected), "implementation": list(actual)}
    return None


def score_module(path_str: str) -> dict:
    path = Path(path_str)
    tag = hashlib.sha256(str(path).encode()).hexdigest()[:12]
    impl = _load("probe_impl_" + tag, path)
    runner = _model_runner()
    model = runner.load_json(MODEL)
    witness = fault_witness(impl, model, runner.interpret_model)
    harness = _harness()
    base = _load("probe_base_" + tag, CONFORMANCE / "evidence-sufficiency-v1" / "checker.py")
    checker = implementation_checker(impl, "probe_checker_" + tag)
    rows = {suite: harness.score_fault(suite, base, checker) for suite in SUITES}
    return {
        "module": path.parent.name + "/" + path.name,
        "sha256": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "fault": witness is not None,
        "witness": witness,
        "rows": {suite: {k: v for k, v in r.items() if k != "row3_failures"} | {"row3_failures": r["row3_failures"][:10]}
                 for suite, r in rows.items()},
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dirs", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    modules = sorted(str(p.resolve()) for d in args.dirs for p in d.glob("*.py"))
    if args.workers <= 1:
        results = [score_module(m) for m in modules]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(score_module, modules))
    if args.json:
        args.json.write_text(json.dumps({"modules": results}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for r in results:
        cells = " | ".join(
            f"{s.split('-')[-1]} {int(r['rows'][s]['row1_kill'])}{int(r['rows'][s]['row2_kill'])}{int(r['rows'][s]['row3_kill'])}"
            for s in SUITES
        )
        print(f"{r['module']:28} fault={int(r['fault'])}  {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
