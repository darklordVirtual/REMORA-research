#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Score a committed list of held-out checker faults against evidence-sufficiency corpora.

Section 8 of ``docs/design/evidence-sufficiency-v1.3.md`` asks for a blind
external run: faults chosen without reading the newest corpus, their
definitions hashed and committed publicly before the run, three rows per
fault, survivors labelled before any corpus change, and one pass criterion.
Every external run so far brought its own harness. This one is committed, so
that a run under section 8 needs only a fault file and a public commitment,
and so that the maintainer's reproduction of a run is itself committed.

A fault file is JSON with a ``faults`` list. Each fault has an ``id``, a
``class`` (``hand_picked`` or ``systematic``, reported in separate tables) and
either ``offset``, ``old`` and ``new`` (one edit of the frozen checker's
source) or ``edits``, a list of such triples. The format is the one the
independent analysis of 2026-09-30 used, so its package scores unchanged.

Rows, as in every earlier run:

- row 1: ``status`` and ``reason`` of every authored case against its expectation;
- row 2: ``missing_evidence`` and ``decisive_if`` of every case against the unmutated checker;
- row 3: the suite runner's ``failures`` list, or a crash of the runner.

The criterion (section 8, item 6) is applied to the newest suite scored:
every fault not labelled ``equivalent`` in ``--labels`` must be killed on row
3. A fault without a label that survives is an open gap, never excluded.
Since the v1.8 spec (D-25) an ``out_of_scope`` label also leaves the
denominator, but only as ``{"label": "out_of_scope", "contract_ref": "..."}``
with the clause of the frozen checker's contract it rests on; a bare
``out_of_scope`` string still counts as an open gap, so every earlier label
file scores as it did.

Row 2 also reports how many faults it cannot see by contract: a fault whose
every row-1 change lies on a case that is decisive under the unmutated checker
has no guidance to compare (rule R-6). The raw row-2 count stays beside it.

The suites scored by default are every ``conformance/evidence-sufficiency-v1.N/``
from v1.2 to the newest on disk; ``--newest`` scores the newest alone.

Usage::

    python scripts/score_heldout_faults.py FAULTS.json --expect-sha256 <digest> --json out.json
    python scripts/score_heldout_faults.py FAULTS.json --expect-sha256 <digest> --labels labels.json --require-pass
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
CHECKER = CONFORMANCE / "evidence-sufficiency-v1" / "checker.py"
LABELS = ("equivalent", "out_of_scope", "open_gap")
OLDEST_DEFAULT = (1, 2)


def suite_version(name: str) -> tuple[int, ...]:
    return tuple(int(part) for part in name.removeprefix("evidence-sufficiency-v").split("."))


def discover_suites(oldest: tuple[int, ...] = OLDEST_DEFAULT) -> tuple[str, ...]:
    """Every ``conformance/evidence-sufficiency-v1.N/`` from ``oldest`` on, oldest first.

    The default used to be a fixed triple (v1.2, v1.3, v1.4) and went stale three
    suites later; the newest suite is now found on disk so that a run cannot be
    scored against a superseded corpus by omission (v1.8 spec, D-21 and R-37).
    """
    found = []
    for path in CONFORMANCE.glob("evidence-sufficiency-v1.*"):
        if (path / "run_evidence_sufficiency.py").exists() and (path / "cases.json").exists():
            version = suite_version(path.name)
            if version >= oldest:
                found.append((version, path.name))
    return tuple(name for _, name in sorted(found))


DEFAULT_SUITES = discover_suites()


def normalise_label(value: object) -> dict[str, str]:
    """A label as ``{"label": ..., "contract_ref": ...}``.

    A bare string is the pre-v1.8 form. ``out_of_scope`` leaves the criterion's
    denominator only with a non-empty ``contract_ref`` naming the clause of the
    frozen checker's contract; a bare ``out_of_scope`` is scored as it always was,
    as an open gap, so earlier label files keep their recorded results.
    """
    if isinstance(value, str):
        return {"label": value, "contract_ref": ""}
    if isinstance(value, dict) and isinstance(value.get("label"), str):
        return {"label": value["label"], "contract_ref": str(value.get("contract_ref", "") or "")}
    raise ValueError(f"malformed label {value!r}")


def leaves_denominator(label: dict[str, str]) -> bool:
    if label["label"] == "equivalent":
        return True
    return label["label"] == "out_of_scope" and bool(label["contract_ref"].strip())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_fault(source: str, fault: dict) -> str:
    """The checker source with the fault's edits applied; refuses an edit that does not match."""
    edits = fault.get("edits") or [{"offset": fault["offset"], "old": fault["old"], "new": fault["new"]}]
    for edit in sorted(edits, key=lambda e: e["offset"], reverse=True):
        at, old = edit["offset"], edit["old"]
        if source[at:at + len(old)] != old:
            raise ValueError(f"{fault['id']}: the edit at offset {at} does not match the checker source")
        source = source[:at] + edit["new"] + source[at + len(old):]
    return source


def load_source_module(text: str, name: str) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(CHECKER)
    sys.modules[name] = module
    try:
        exec(compile(text, str(CHECKER), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


_RUNNERS: dict[str, ModuleType] = {}


def runner(suite: str) -> ModuleType:
    if suite not in _RUNNERS:
        path = CONFORMANCE / suite / "run_evidence_sufficiency.py"
        name = "heldout_runner_" + suite.replace("-", "_").replace(".", "_")
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _RUNNERS[suite] = module
    return _RUNNERS[suite]


def runner_failures(suite: str, checker: ModuleType) -> tuple[list[str], str | None]:
    """(failures, crash) of the suite runner against ``checker``.

    Runners from v1.3 on take the checker as an argument. Earlier ones bind it at
    import, so their module globals are swapped for the call and restored after.
    """
    run = runner(suite)
    try:
        if "checker_module" in run.build_record.__code__.co_varnames[: run.build_record.__code__.co_argcount]:
            return list(run.build_record(checker)["failures"]), None
        names = ("checker", "EvidenceStatus", "assess", "canonical")
        saved = {n: getattr(run, n) for n in names if hasattr(run, n)}
        replacement = {"checker": checker, "EvidenceStatus": checker.EvidenceStatus,
                       "assess": checker.assess, "canonical": checker.canonical}
        for n in saved:
            setattr(run, n, replacement[n])
        try:
            return list(run.build_record()["failures"]), None
        finally:
            for n, value in saved.items():
                setattr(run, n, value)
    except Exception as exc:  # noqa: BLE001 - a crash of the runner is a kill on row 3
        return [], type(exc).__name__


def _verdict(checker: ModuleType, case: dict, scope: dict) -> dict[str, Any]:
    try:
        return checker.assess(case["claim"], deepcopy(case["observations"]), scope=scope).as_dict()
    except Exception as exc:  # noqa: BLE001 - a crash kills on rows 1 and 2
        return {"crash": type(exc).__name__}


def score_fault(suite: str, base: ModuleType, mutant: ModuleType) -> dict:
    cases = runner(suite).load_json(CONFORMANCE / suite / "cases.json")["cases"]
    row1, row2 = [], []
    decisive_under_base: set[str] = set()
    for case in cases:
        scope = {"kind": "synthetic_fixture", "suite": suite, "bounded": True, "case": case["id"]}
        got, want = _verdict(mutant, case, scope), _verdict(base, case, scope)
        expected = (case["expected"]["status"], case["expected"]["reason"])
        if "crash" in got or (got["status"], got["reason"]) != expected:
            row1.append(case["id"])
        if "crash" in got or (got.get("missing_evidence"), got.get("decisive_if")) != (
            want.get("missing_evidence"), want.get("decisive_if")
        ):
            row2.append(case["id"])
        if "crash" not in want and want["status"] != "not_established":
            decisive_under_base.add(case["id"])
    failures, crash = runner_failures(suite, mutant)
    # Row 2 cannot see a fault whose every row-1 change lies on a case that is
    # decisive under the unmutated checker: rule R-6 gives decisive verdicts no
    # guidance. The predicate reads the unmutated verdicts only (v1.8 spec, D-21);
    # the raw row-2 count is reported beside it and never replaced.
    row2_applicable = bool(row2) or not row1 or any(c not in decisive_under_base for c in row1)
    return {"row1_cases": row1, "row2_cases": row2, "row3_failures": failures[:50],
            "row3_failure_count": len(failures), "row3_crash": crash,
            "row1_kill": bool(row1), "row2_kill": bool(row2), "row2_applicable": row2_applicable,
            "row3_kill": bool(failures) or crash is not None}


def score(definitions: dict, suites: tuple[str, ...], labels: dict[str, object]) -> dict:
    normalised = {fid: normalise_label(value) for fid, value in labels.items()}
    source = CHECKER.read_text(encoding="utf-8")
    base = load_source_module(source, "heldout_base_checker")
    for suite in suites:
        failures, crash = runner_failures(suite, base)
        if failures or crash:
            raise SystemExit(f"the unmutated checker fails {suite}: {crash or failures[:5]}")
    rows: dict[str, list[dict]] = {suite: [] for suite in suites}
    for fault in definitions["faults"]:
        text = apply_fault(source, fault)
        name = "heldout_fault_" + sha256(fault["id"].encode())[:16]
        mutant = load_source_module(text, name)
        try:
            for suite in suites:
                rows[suite].append({"id": fault["id"], "class": fault.get("class", "hand_picked"),
                                    **score_fault(suite, base, mutant)})
        finally:
            sys.modules.pop(name, None)
    tables: dict[str, dict[str, dict[str, int]]] = {}
    for suite in suites:
        tables[suite] = {}
        for group in sorted({r["class"] for r in rows[suite]}):
            selected = [r for r in rows[suite] if r["class"] == group]
            tables[suite][group] = {
                "faults": len(selected),
                "row1": sum(r["row1_kill"] for r in selected),
                "row2": sum(r["row2_kill"] for r in selected),
                "row2_applicable": sum(r["row2_applicable"] for r in selected),
                "row2_not_applicable_by_r6": sum(not r["row2_applicable"] for r in selected),
                "row3": sum(r["row3_kill"] for r in selected),
            }
    newest = suites[-1]
    survivors = [r["id"] for r in rows[newest] if not r["row3_kill"]]
    open_gaps = [fid for fid in survivors if not leaves_denominator(normalised.get(fid, {"label": "", "contract_ref": ""}))]
    out_of_scope = [fid for fid in survivors if normalised.get(fid, {}).get("label") == "out_of_scope"]
    return {
        "checker_sha256": sha256(source.replace("\r\n", "\n").encode("utf-8")),
        "suites": list(suites),
        "tables": tables,
        "criterion": {
            "suite": newest,
            "rule": ("every fault not labelled equivalent, or out_of_scope with a cited contract_ref, "
                     "is killed on row 3 (v1.3 spec, section 8, item 6; v1.8 spec, D-25)"),
            "row3_survivors": survivors,
            "open_gaps": open_gaps,
            "out_of_scope": {fid: normalised[fid]["contract_ref"] for fid in out_of_scope},
            "met": not open_gaps,
        },
        "row1_only_on_runner": {
            suite: [r["id"] for r in rows[suite] if r["row3_kill"] and not r["row1_kill"]] for suite in suites
        },
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("faults", type=Path, help="the committed fault-definition file")
    parser.add_argument("--expect-sha256", required=True,
                        help="the digest committed before the run; the file must match it byte for byte")
    parser.add_argument("--suite", action="append", dest="suites",
                        help="a corpus to score, oldest first (default: every suite from v1.2 to the newest on disk)")
    parser.add_argument("--newest", action="store_true",
                        help="score only the newest suite on disk")
    parser.add_argument("--labels", type=Path,
                        help='JSON {fault id: equivalent|out_of_scope|open_gap, or {"label": ..., "contract_ref": ...}}')
    parser.add_argument("--json", type=Path, help="write the full record here")
    parser.add_argument("--require-pass", action="store_true", help="exit 1 unless the criterion is met")
    args = parser.parse_args(argv)
    data = args.faults.read_bytes()
    digest = sha256(data)
    if digest != args.expect_sha256:
        print(f"[FAIL] {args.faults} has sha256 {digest}, not the committed {args.expect_sha256}", file=sys.stderr)
        return 2
    definitions = json.loads(data.decode("utf-8"))
    labels = json.loads(args.labels.read_text(encoding="utf-8")) if args.labels else {}
    try:
        bad = {k: v for k, v in labels.items() if normalise_label(v)["label"] not in LABELS}
    except ValueError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    if bad:
        print(f"[FAIL] unknown labels {bad}; allowed: {LABELS}", file=sys.stderr)
        return 2
    if args.newest and args.suites:
        print("[FAIL] --newest and --suite exclude each other", file=sys.stderr)
        return 2
    if not DEFAULT_SUITES:
        print("[FAIL] no evidence-sufficiency suite found under conformance/", file=sys.stderr)
        return 2
    suites = (DEFAULT_SUITES[-1],) if args.newest else tuple(args.suites or DEFAULT_SUITES)
    record = score(definitions, suites, labels)
    record["fault_definitions_sha256"] = digest
    record["source_commit"] = definitions.get("source_commit")
    if args.json:
        args.json.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for suite in suites:
        for group, t in record["tables"][suite].items():
            print(f"{suite} {group}: {t['faults']} faults; killed on row 1 {t['row1']}, row 2 {t['row2']} "
                  f"(n/a by R-6 {t['row2_not_applicable_by_r6']}), row 3 {t['row3']}")
    c = record["criterion"]
    print(f"criterion on {c['suite']}: {'met' if c['met'] else 'NOT met'}; row-3 survivors {c['row3_survivors']}; "
          f"open gaps {c['open_gaps']}; out of scope {c['out_of_scope']}")
    return 1 if args.require_pass and not c["met"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
