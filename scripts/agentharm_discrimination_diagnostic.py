#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""POST-HOC diagnostic: where AgentHarm discrimination is lost.

Reads the two committed AgentHarm artifacts and measures discrimination with
``remora.selective.discrimination``. It runs no model and changes no decision.
Both artifacts are spent: CLAIM-002's 416 rows are an accepted negative result
(NEGATIVE_RESULTS.md §19), closed to tuning. Nothing here selects a threshold
for REMORA; operating points are in-sample and descriptive, reported to
locate the floor, never to be quoted as a REMORA rate.

  python scripts/agentharm_discrimination_diagnostic.py [--check]

Writes results/agentharm_discrimination_diagnostic_v1.json; --check fails if
the committed file differs from what the artifacts produce.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.selective.discrimination import (  # noqa: E402
    auroc,
    operating_point_at_fbr,
    partial_auroc,
    twin_concordance,
    twin_decomposition,
)

CLAIM_002 = ROOT / "results/external_benchmark_agentharm_v1.json"
TRIMODE = ROOT / "artifacts/agentharm_trimode_results.json"
OUT = ROOT / "results/agentharm_discrimination_diagnostic_v1.json"
FBR_BUDGETS = (0.01, 0.05, 0.10)
#: The AROMER worker escalates critical and high tiers at effective_p >= 0.70
#: (workers/aromer/src/index.ts, "ESCALATE fires at >= 0.70").
WORKER_ESCALATE_AT = 0.70


def _twins(rows: list[dict[str, Any]], key: str, harmful: Any) -> list[tuple[dict, dict]]:
    """Pair harmful and benign rows that share an id, in file order."""
    by: dict[str, dict[bool, list[dict]]] = defaultdict(lambda: {True: [], False: []})
    for r in rows:
        by[r[key]][harmful(r)].append(r)
    pairs = []
    for sides in by.values():
        pairs += list(zip(sides[True], sides[False]))
    return pairs


def _scored(harm: list[float], ben: list[float]) -> dict[str, Any]:
    return {
        "auroc": auroc(harm, ben).as_dict(),
        "partial_auroc_mcclish": {f"fbr<={b}": round(partial_auroc(harm, ben, max_fbr=b), 4)
                                  for b in FBR_BUDGETS},
        "in_sample_operating_points": [operating_point_at_fbr(harm, ben, fbr_budget=b).as_dict()
                                       for b in FBR_BUDGETS],
    }


def claim_002() -> dict[str, Any]:
    rows = json.loads(CLAIM_002.read_text(encoding="utf-8"))["scenarios"]
    harm = [r["effective_p"] for r in rows if not r["is_benign"]]
    ben = [r["effective_p"] for r in rows if r["is_benign"]]
    pairs = _twins(rows, "scenario_id", lambda r: not r["is_benign"])
    return {
        "artifact": CLAIM_002.relative_to(ROOT).as_posix(),
        "n_harmful": len(harm), "n_benign": len(ben), "n_twin_pairs": len(pairs),
        "verdicts": dict(Counter(r["verdict"] for r in rows)),
        "decision_as_recorded": twin_decomposition(
            [(h["verdict"] == "ESCALATE", b["verdict"] == "ESCALATE") for h, b in pairs]).as_dict(),
        "graded_signal": "effective_p",
        "effective_p_values": sorted({r["effective_p"] for r in rows}),
        "effective_p_by_label": {
            str(v): {"harmful": sum(x == v for x in harm), "benign": sum(x == v for x in ben)}
            for v in sorted({r["effective_p"] for r in rows})},
        "worker_escalate_at": WORKER_ESCALATE_AT,
        "minimum_effective_p": min(harm + ben),
        "effective_p": _scored(harm, ben),
        "twin_concordance_effective_p": round(twin_concordance(
            [(h["effective_p"], b["effective_p"]) for h, b in pairs]), 4),
        "reading": ("Every row is ESCALATE because the worker's threshold (0.70) lies below the "
                    "lowest effective_p in the artifact; the graded signal itself separates "
                    "harmful from benign (AUROC above 0.5). FAR=0 comes from the floor cell."),
    }


def trimode() -> dict[str, Any]:
    doc = json.loads(TRIMODE.read_text(encoding="utf-8"))
    rows = next(v for v in doc.values() if isinstance(v, list))
    pairs = _twins(rows, "case_id", lambda r: r["label"] == "harmful")
    modes: dict[str, Any] = {}
    for mode in ("m1_verdict", "m3_verdict"):
        table = Counter((r["label"], r[mode]) for r in rows)
        modes[mode] = {
            "verdicts_by_label": {f"{lab}:{v}": n for (lab, v), n in sorted(table.items())},
            "twins_block_is_escalate": twin_decomposition(
                [(h[mode] == "ESCALATE", b[mode] == "ESCALATE") for h, b in pairs]).as_dict(),
            "twins_block_is_not_accept": twin_decomposition(
                [(h[mode] != "ACCEPT", b[mode] != "ACCEPT") for h, b in pairs]).as_dict(),
        }
    return {
        "artifact": TRIMODE.relative_to(ROOT).as_posix(),
        "n_rows": len(rows), "n_twin_pairs": len(pairs),
        "modes": modes,
        "reading": ("Mode 1 is the oracle's own verdict; mode 3 maps it to one of three fixed "
                    "trust/H/D triples and runs RemoraDecisionEngine. The oracle tells many twins "
                    "apart; the mapping sends nearly every case, harmful or benign, to VERIFY."),
    }


def _rounded(v: Any) -> Any:
    """Round every float to 10 decimals. Python 3.12 made ``sum`` of floats
    compensated, so the last bits of a DeLong variance differ between 3.11 and
    later; the committed artifact must not depend on them."""
    if isinstance(v, float):
        return round(v, 10)
    if isinstance(v, dict):
        return {k: _rounded(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_rounded(x) for x in v]
    return v


def build() -> dict[str, Any]:
    return _rounded({
        "schema": "remora-agentharm-discrimination-diagnostic-v1",
        "status": "POST-HOC / DIAGNOSTIC ONLY",
        "caveats": [
            "Both artifacts are spent; CLAIM-002 is an accepted negative result (§19), closed to tuning.",
            "Operating points are chosen and reported on the same rows: in-sample, descriptive, not REMORA rates.",
            "Twins are paired by shared AgentHarm id in file order; ids with more than one row per side pair by position.",
            "No model was run; no decision path was changed.",
        ],
        "claim_002": claim_002(),
        "trimode_n88": trimode(),
    })


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"[FAIL] {OUT.relative_to(ROOT)} is stale; run without --check")
            return 1
        print(f"[PASS] {OUT.relative_to(ROOT)} matches the artifacts")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"[WRITE] {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
