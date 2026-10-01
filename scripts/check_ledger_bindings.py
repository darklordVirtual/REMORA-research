#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Numbers in the thermodynamics claim ledger must come from their artifacts (Q1.5).

No claim gate read ``docs/thermodynamics/claim_ledger.yaml``. Three entries
cited 98 accepted / 88.78 % for months while the artifact they named held
101 / 96.04 %, and nothing failed (NEGATIVE_RESULTS.md §58, §59).

For each entry whose ``artifact`` (and optional ``also_cites``) names JSON
files, every percentage (``88.78%``) and every decimal fraction (``0.1972``) in
its ``wording`` must equal a numeric field of one of those files, compared at
the precision the number is written with. A number that is not a measurement
of those files is declared on the entry itself. An integer ratio (``5/20``)
is bound when both of its integers are integer fields of those files, which
catches a wrong count without having to know which field is the numerator.

``parameters``      thresholds, targets and test bars the text quotes
``retired_values``  numbers from a run whose file is no longer in results/

Numbers that were already unbound when this gate landed are listed in
``docs/assurance/ledger_binding_baseline.json``. The baseline only shrinks: a
new unbound number fails, and a baseline entry that no longer occurs fails
until it is removed.

    python scripts/check_ledger_bindings.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path("docs/thermodynamics/claim_ledger.yaml")
BASELINE = Path("docs/assurance/ledger_binding_baseline.json")
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*%|(?<![\d.])(0\.\d{2,})(?![\d.])")
_RATIO = re.compile(r"(?<![\d.])(\d+)\s*/\s*(\d+)(?![\d.%])")


def _values(node: Any) -> Iterator[float]:
    if isinstance(node, dict):
        for v in node.values():
            yield from _values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _values(v)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield float(node)


def _json_paths(field: Any) -> list[str]:
    items = field if isinstance(field, list) else re.split(r"[,\s]+", str(field or ""))
    return [p.strip() for p in items if str(p).strip().endswith(".json")]


def _matches(token: str, is_pct: bool, values: list[float]) -> bool:
    decimals = len(token.split(".")[1]) if "." in token else 0
    target = float(token)
    for v in values:
        # The sign is written in the text ("rho = -0.0102"); compare magnitudes.
        for candidate in ((abs(v) * 100, abs(v)) if is_pct else (abs(v),)):
            if round(candidate, decimals) == target:
                return True
    return False


def unbound_numbers(root: Path) -> tuple[list[str], list[str]]:
    """(unbound ids, errors). An id is ``claim:number`` as written."""
    ledger = yaml.safe_load((root / LEDGER).read_text(encoding="utf-8"))["claims"]
    unbound: list[str] = []
    errors: list[str] = []
    for cid, claim in ledger.items():
        paths = _json_paths(claim.get("artifact")) + _json_paths(claim.get("also_cites"))
        if not paths:
            continue
        values: list[float] = []
        integers: set[int] = set()
        for rel in paths:
            path = root / rel
            if not path.exists():
                errors.append(f"{cid}: cited artifact {rel} does not exist")
                continue
            found = list(_values(json.loads(path.read_text(encoding="utf-8"))))
            values += found
            integers |= {int(v) for v in found if float(v).is_integer()}
        declared = {str(x) for x in (claim.get("parameters") or []) + (claim.get("retired_values") or [])}
        for m in _NUMBER.finditer(str(claim.get("wording", ""))):
            token, is_pct = (m.group(1), True) if m.group(1) else (m.group(2), False)
            written = f"{token}%" if is_pct else token
            if written in declared or token in declared:
                continue
            if not _matches(token, is_pct, values):
                unbound.append(f"{cid}:{written}")
        for m in _RATIO.finditer(str(claim.get("wording", ""))):
            written = f"{m.group(1)}/{m.group(2)}"
            if written in declared:
                continue
            if not {int(m.group(1)), int(m.group(2))} <= integers:
                unbound.append(f"{cid}:{written}")
    return unbound, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="thermodynamics ledger number bindings")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--update-baseline", action="store_true",
                        help="write the current unbound set; review the diff, it may only shrink")
    args = parser.parse_args(argv)
    unbound, errors = unbound_numbers(args.root)
    baseline_path = args.root / BASELINE
    if args.update_baseline:
        entries = [{"id": u, "reason": "unbound when the Q1.5 gate landed (2026-09-28); not yet reviewed"}
                   for u in sorted(set(unbound))]
        baseline_path.write_text(json.dumps({"schema_version": 1, "entries": entries}, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"baseline written: {len(entries)} entries")
        return 0
    baselined = {e["id"] for e in json.loads(baseline_path.read_text(encoding="utf-8"))["entries"]}
    new = sorted(set(unbound) - baselined)
    stale = sorted(baselined - set(unbound))
    for e in errors:
        print(f"[FAIL] {e}")
    for u in new:
        print(f"[FAIL] {u}: not a field of the entry's artifacts; declare it under parameters or retired_values, or fix it")
    for s in stale:
        print(f"[FAIL] {s}: baselined but now bound or gone; remove it from {BASELINE}")
    if errors or new or stale:
        return 1
    print(f"[PASS] ledger numbers bound to their artifacts ({len(baselined)} baselined, unreviewed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
