#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Mutation sweep over the frozen evidence-sufficiency checker, scored by the v1.3 corpus.

The external seeded-fault runs (docs/assurance/external_adequacy_evidence_sufficiency_v1.md)
used hand-picked fault classes. This sweep is the systematic complement: mutmut
applies its whole operator set to ``conformance/evidence-sufficiency-v1/checker.py``
and the v1.3 runner is the test. A mutant the corpus cannot tell apart is a
survivor; every survivor is either killed by a corpus change or named in
``docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`` with the family
it belongs to. The gate fails on a survivor that is in neither place.

Why a separate sandbox rather than ``[tool.mutmut]`` in pyproject: mutmut reads
one configuration per project, and that one is the scoped sweep over the
enforcement paths (issue #280). The checker lives under ``conformance/``, is
imported by path rather than as a package, and its runner reads the checker's
source text for the reason vocabulary. The sandbox built here copies the
checker into an importable package, copies the four suite directories, points
the v1.3 runner at the package, and reads the reason vocabulary from the
unmutated source so that mutmut's own rewriting of the served copy is not
mistaken for a fault. The scoring tests are the same three projections the
external runs used: status and reason per case, guidance per case, and the
runner's failure list.

Limits the reader should keep: mutant ids are stable only for one mutmut
version (recorded in the baseline header); the sweep measures the corpus
against mutmut's operators, not against every fault a checker could have; and
a killed mutant is not evidence that the checker is correct (DeMillo, Lipton
and Sayward, 1978; Just et al., 2014).

Usage::

    python scripts/mutation_evidence_sufficiency.py            # sweep, compare, exit 1 on new survivors
    python scripts/mutation_evidence_sufficiency.py --update   # sweep and rewrite the baseline
    python scripts/mutation_evidence_sufficiency.py --results-out mutation-es-results.txt
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "assurance" / "mutation_baseline_evidence_sufficiency_v1.txt"
CONFORMANCE = ROOT / "conformance"
SUITES = ("evidence-sufficiency-v1", "evidence-sufficiency-v1.1", "evidence-sufficiency-v1.2", "evidence-sufficiency-v1.3")
SCORING_SUITE = "evidence-sufficiency-v1.3"

_LINE = re.compile(r"^\s*(\S+__mutmut_\d+): (.+?)\s*$")

_LOADER_ORIGINAL = "def _load_checker("
_LOADER_SANDBOX = '''def _load_checker(path: Path = CHECKER_PATH) -> ModuleType:
    import es.checker as module  # mutmut serves the mutant from mutants/es/checker.py
    return module


'''
_VOCAB_ORIGINAL = 'vocabulary = reason_vocabulary(CHECKER_PATH.read_text(encoding="utf-8"))'
_VOCAB_SANDBOX = (
    'vocabulary = reason_vocabulary((V1 / "checker.py").read_text(encoding="utf-8"))'
    "  # the unmutated source: mutmut rewrites the served copy"
)

_SCORING_TESTS = '''"""Three projections, as in the external runs: verdict, guidance, runner failures."""
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE.parent / "suite" / "%(suite)s"


def _runner():
    spec = importlib.util.spec_from_file_location("es_scoring_runner", SUITE / "run_evidence_sufficiency.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _runner()
CASES = json.loads((SUITE / "cases.json").read_text(encoding="utf-8"))["cases"]
RECORD = json.loads((SUITE / "run-record.json").read_text(encoding="utf-8"))
SCOPE = {"kind": "synthetic_fixture", "suite": RECORD["suite"], "bounded": True}


def _verdicts():
    return {
        case["id"]: RUNNER.checker.assess(
            case["claim"], deepcopy(case["observations"]), scope={**SCOPE, "case": case["id"]}
        ).as_dict()
        for case in CASES
    }


def test_row1_status_and_reason():
    verdicts = _verdicts()
    for case in CASES:
        got = verdicts[case["id"]]
        assert (got["status"], got["reason"]) == (case["expected"]["status"], case["expected"]["reason"]), case["id"]


def test_row2_guidance():
    baseline = RECORD["case_guidance"]
    for case_id, got in _verdicts().items():
        assert got["missing_evidence"] == baseline[case_id]["missing_evidence"], case_id
        assert got.get("decisive_if") == baseline[case_id]["decisive_if"], case_id


def test_row3_runner_failures():
    assert RUNNER.build_record()["failures"] == []
'''

_PYPROJECT = """[tool.mutmut]
source_paths = ["es"]
also_copy = ["suite"]
pytest_add_cli_args_test_selection = ["tests/test_scoring.py"]
max_children = %(children)d
"""


def build_sandbox(workdir: Path, children: int) -> None:
    """Lay out the importable checker, the suites, the patched runner and the scoring tests."""
    (workdir / "es").mkdir(parents=True)
    shutil.copy(CONFORMANCE / "evidence-sufficiency-v1" / "checker.py", workdir / "es" / "checker.py")
    (workdir / "es" / "__init__.py").write_text("", encoding="utf-8")
    for suite in SUITES:
        target = workdir / "suite" / suite
        target.mkdir(parents=True)
        for path in sorted((CONFORMANCE / suite).iterdir()):
            if path.suffix in (".json", ".py"):
                shutil.copy(path, target / path.name)
    runner = workdir / "suite" / SCORING_SUITE / "run_evidence_sufficiency.py"
    source = runner.read_text(encoding="utf-8")
    start = source.index(_LOADER_ORIGINAL)
    end = source.index("checker = _load_checker()")
    if _VOCAB_ORIGINAL not in source:
        raise SystemExit("runner layout changed: the reason-vocabulary line was not found")
    source = source[:start] + _LOADER_SANDBOX + source[end:]
    source = source.replace(_VOCAB_ORIGINAL, _VOCAB_SANDBOX)
    runner.write_text(source, encoding="utf-8")
    (workdir / "tests").mkdir()
    (workdir / "tests" / "test_scoring.py").write_text(_SCORING_TESTS % {"suite": SCORING_SUITE}, encoding="utf-8")
    (workdir / "pyproject.toml").write_text(_PYPROJECT % {"children": children}, encoding="utf-8")


def parse_results(text: str) -> dict[str, str]:
    """mutant id -> status, from ``mutmut results`` output."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def read_baseline(path: Path) -> set[str]:
    """Survivor ids from the baseline; ``#`` lines carry the family labels and are ignored."""
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def compare(results: dict[str, str], baseline: set[str]) -> tuple[list[str], list[str]]:
    """(new survivors, baseline entries that now die)."""
    survivors = {mid for mid, status in results.items() if status == "survived"}
    return sorted(survivors - baseline), sorted(baseline - survivors)


def _mutmut_version() -> str:
    proc = subprocess.run([sys.executable, "-m", "mutmut", "--version"], capture_output=True, text=True, check=False)
    return (proc.stdout or proc.stderr).strip().splitlines()[-1] if (proc.stdout or proc.stderr).strip() else "unknown"


def run_sweep(workdir: Path) -> str:
    """Run mutmut in the sandbox; return the ``mutmut results`` text."""
    scoring = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "tests"], cwd=workdir, capture_output=True, text=True, check=False
    )
    if scoring.returncode != 0:
        raise SystemExit(f"scoring tests fail on the unmutated checker; the sweep would be meaningless:\n{scoring.stdout}")
    subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=workdir, check=False)
    # `mutmut results` lists only the mutants that were not killed; --all lists every mutant
    # with its status, which is what a kill count needs.
    results = subprocess.run(
        [sys.executable, "-m", "mutmut", "results", "--all", "true"],
        cwd=workdir, capture_output=True, text=True, check=False,
    )
    return results.stdout


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="rewrite the baseline from this sweep")
    parser.add_argument("--results-out", type=Path, help="also write the raw `mutmut results` text here")
    parser.add_argument("--results-in", type=Path, help="compare a saved results file instead of sweeping")
    parser.add_argument("--workdir", type=Path, help="keep the sandbox here instead of a temporary directory")
    parser.add_argument("--children", type=int, default=8, help="mutmut max_children")
    args = parser.parse_args(argv)

    if args.results_in:
        text = args.results_in.read_text(encoding="utf-8")
    else:
        tmp = None
        if args.workdir:
            workdir = args.workdir
            if workdir.exists():
                shutil.rmtree(workdir)
        else:
            tmp = tempfile.TemporaryDirectory(prefix="es-mutation-")
            workdir = Path(tmp.name) / "sandbox"
        build_sandbox(workdir, args.children)
        try:
            text = run_sweep(workdir)
        finally:
            if tmp:
                tmp.cleanup()
    if args.results_out:
        args.results_out.write_text(text, encoding="utf-8")

    results = parse_results(text)
    if not results:
        print("[FAIL] no mutants parsed from the sweep; an empty sweep must not pass as a clean one", file=sys.stderr)
        return 1
    counts = {status: sum(1 for s in results.values() if s == status) for status in sorted(set(results.values()))}
    total = len(results)
    killed = counts.get("killed", 0)
    survived = counts.get("survived", 0)
    print(f"mutants {total}: {counts} ({100.0 * killed / total:.1f}% killed)")

    survivors = sorted(mid for mid, status in results.items() if status == "survived")
    if args.update:
        header = [
            "# Surviving mutants of conformance/evidence-sufficiency-v1/checker.py under the",
            "# evidence-sufficiency-v1.3 scoring tests. Regenerate with",
            "#   python scripts/mutation_evidence_sufficiency.py --update",
            f"# {_mutmut_version()}; mutant ids are stable only for this version.",
            "# Every id below is classified in docs/assurance/mutation_testing_v1.md.",
        ]
        BASELINE.write_text("\n".join(header + survivors) + "\n", encoding="utf-8", newline="\n")
        print(f"[OK] baseline updated: {survived} survivor(s) recorded")
        return 0

    new, dead = compare(results, read_baseline(BASELINE))
    for mid in dead:
        print(f"[HINT] baseline survivor now killed (remove it from the baseline): {mid}")
    if new:
        print(f"[FAIL] {len(new)} surviving mutant(s) absent from the baseline:", file=sys.stderr)
        for mid in new:
            print(f"  {mid}", file=sys.stderr)
        return 1
    print(f"[OK] no new survivors ({survived} in the baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
