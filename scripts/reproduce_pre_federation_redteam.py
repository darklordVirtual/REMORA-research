#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reproduce the pre-Federation red-team count of NEGATIVE_RESULTS §76, and read it today.

    python scripts/reproduce_pre_federation_redteam.py --out RESULT.json

§76 says 36 of 46 targeted attacks succeeded against ``master`` at 9a3d321.
No artifact listed the 46 or their outcomes. This script runs three things and
writes each probe's outcome:

``at_baseline``
    The probe files of draft PR #744 (commit ab573075) on a temporary
    worktree of 9a3d321. This is the run §76 reports.
``original_probes_today``
    The same probe bytes against the working tree. A probe that still fails
    is listed with the first line of its failure, because a failure here is
    either a target that was kept on purpose or a probe whose setup no
    longer reaches its target, and the two must not be confused with a
    regression.
``repository_probes_today``
    ``tests/test_pre_federation_*.py`` as they are now.

The PR head is not on any branch. If the commit is not in the local object
store the script fetches ``pull/744/head`` from ``origin``, which needs
network access. Nothing else leaves the machine. The worktree and the copied
probe files are removed afterwards. Every run uses the interpreter that runs
this script, so a dependency that changed since 2026-10-06 can change a
baseline outcome; the counts are compared with §76's in the result.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "9a3d321"
PROBES_COMMIT = "ab573075cbd26467defd150386616a03b99ed576"
PROBES_REF = "pull/744/head"
PATTERN = "test_pre_federation_"
STATED = {"probes": 46, "red": 36, "green": 10}


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def _have(commit: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT,
                          capture_output=True).returncode == 0


def probe_files() -> list[str]:
    if not _have(PROBES_COMMIT):
        _git("fetch", "--quiet", "origin", PROBES_REF)
    names = _git("ls-tree", "-r", "--name-only", PROBES_COMMIT, "tests").split()
    return sorted(n for n in names if Path(n).name.startswith(PATTERN))


def parse_junit(path: Path, strip_prefix: str = "") -> list[dict[str, Any]]:
    """One row per test case: file, name, outcome and the first line of a failure."""
    rows = []
    for case in ET.parse(path).getroot().iter("testcase"):  # noqa: S314 - our own pytest output
        module = case.get("classname", "").rsplit(".", 1)[-1]
        if strip_prefix and module.startswith(strip_prefix):
            module = module[len(strip_prefix):]
        problem = next((c for c in case if c.tag in ("failure", "error")), None)
        skipped = any(c.tag == "skipped" for c in case)
        row: dict[str, Any] = {"file": f"tests/{module}.py", "test": case.get("name", ""),
                               "outcome": ("failed" if problem is not None
                                           else "skipped" if skipped else "passed")}
        if problem is not None:
            message = " ".join((problem.get("message") or "").split())
            row["failure"] = message[:2000]
        rows.append(row)
    return sorted(rows, key=lambda r: (r["file"], r["test"]))


def _pytest(cwd: Path, files: list[str], strip_prefix: str = "") -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        done = subprocess.run([sys.executable, "-m", "pytest", *files, "-q", "-p",
                               "no:cacheprovider", f"--junitxml={report}"],
                              cwd=cwd, capture_output=True, text=True)
        # 0: all passed. 1: some test failed. Anything else (a collection
        # error, a usage error, an interrupt) is not a result about the probes.
        if done.returncode not in (0, 1):
            raise RuntimeError(f"pytest exited {done.returncode} in {cwd}: "
                               f"{done.stdout[-400:]}{done.stderr[-400:]}")
        return parse_junit(report, strip_prefix)


def counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = Counter(r["outcome"] for r in rows)
    per_file: dict[str, dict[str, int]] = {}
    for r in rows:
        per_file.setdefault(r["file"], Counter())[r["outcome"]] += 1  # type: ignore[index]
    return {"probes": len(rows), "failed": by["failed"], "passed": by["passed"],
            "skipped": by["skipped"],
            "per_file": {f: dict(sorted(c.items())) for f, c in sorted(per_file.items())}}


def summary(result: dict[str, Any]) -> dict[str, Any]:
    """What the three runs say together. Pure, so it is tested without git."""
    base = counts(result["at_baseline"])
    today = counts(result["original_probes_today"])
    repo = counts(result["repository_probes_today"])
    return {
        "at_baseline": base, "original_probes_today": today, "repository_probes_today": repo,
        "reproduces_the_stated_count": (base["probes"], base["failed"], base["passed"]) == (
            STATED["probes"], STATED["red"], STATED["green"]),
        "original_probes_still_failing": [
            {k: r[k] for k in ("file", "test", "failure")}
            for r in result["original_probes_today"] if r["outcome"] == "failed"],
        "probes_added_since": repo["probes"] - base["probes"],
    }


def run() -> dict[str, Any]:
    # A run that was killed leaves a worktree registration and copied probes behind.
    _git("worktree", "prune")
    for stale in (ROOT / "tests").glob("zz_original_" + PATTERN + "*.py"):
        stale.unlink()
    files = probe_files()
    with tempfile.TemporaryDirectory(prefix="remora-redteam-") as tmp:
        tree = Path(tmp) / "baseline"
        _git("worktree", "add", "--quiet", "--detach", str(tree), BASELINE)
        try:
            for name in files:
                (tree / name).write_text(_git("show", f"{PROBES_COMMIT}:{name}"), encoding="utf-8")
            at_baseline = _pytest(tree, files)
        finally:
            _git("worktree", "remove", "--force", str(tree))
    prefix = "zz_original_"
    copies = []
    try:
        for name in files:
            copy = ROOT / "tests" / (prefix + Path(name).name)
            copy.write_text(_git("show", f"{PROBES_COMMIT}:{name}"), encoding="utf-8")
            copies.append(copy)
        original_today = _pytest(ROOT, [str(c.relative_to(ROOT)) for c in copies], prefix)
    finally:
        for copy in copies:
            copy.unlink(missing_ok=True)
    current = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob(PATTERN + "*.py"))
    result: dict[str, Any] = {
        "schema": "remora-pre-federation-redteam-reproduction/v1",
        "section": "NEGATIVE_RESULTS §76", "stated": STATED,
        "baseline_commit": BASELINE, "probes_commit": PROBES_COMMIT,
        "probes_source": "draft PR #744, closed; its head is fetched as " + PROBES_REF,
        "working_tree_commit": _git("rev-parse", "HEAD").strip(),
        "working_tree_dirty": bool(_git("status", "--porcelain", "--untracked-files=no").strip()),
        "python": sys.version.split()[0],
        "at_baseline": at_baseline, "original_probes_today": original_today,
        "repository_probes_today": _pytest(ROOT, current),
    }
    result["summary"] = summary(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = run()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        s = result["summary"]
        print(f"wrote {args.out}: baseline {s['at_baseline']['failed']} red of "
              f"{s['at_baseline']['probes']}; original probes today "
              f"{s['original_probes_today']['failed']} red; repository probes today "
              f"{s['repository_probes_today']['failed']} red of "
              f"{s['repository_probes_today']['probes']}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
