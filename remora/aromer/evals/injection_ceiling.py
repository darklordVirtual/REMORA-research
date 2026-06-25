# Author: Stian Skogbrott
# License: Apache-2.0
"""Measure REMORA's ceiling against indirect prompt injection.

Context
-------
The external-holdout ablation showed REMORA's admission firewall does not catch
indirect injection, because the firewall scans the *action description* while the
payload lives in `untrusted_context` (see
`datasets/aromer_external_holdout_v1/README.md`). REMORA has a second, dedicated
gate for exactly this: `ToolResultScanner` (`remora/agent_hook/result_scanner.py`),
a 20-rule heuristic + optional oracle stage that classifies returned/untrusted
content before it can influence the next decision.

This module measures how much of the toolcall_v3 attack corpus that scanner
actually catches — REMORA's real ceiling against indirect injection — using the
**deterministic heuristic stage only** (no oracle, no API, reproducible). The
oracle stage could raise detection; that is a separate, non-deterministic live
validation.

Honesty note
------------
Detection is measured from the scanner's own pattern matching on the untrusted
content, NOT from the ground-truth `attack_type` label. The label is used only to
score the scanner's output (recall on attacks, false-positive rate on benign
context).
"""
from __future__ import annotations

import argparse
import json
import pathlib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from remora.agent_hook.result_scanner import ScanVerdict, ToolResultScanner

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOLCALL_V3_DIR = _REPO_ROOT / "data" / "toolcall_v3"
ARTIFACT_PATH = _REPO_ROOT / "artifacts" / "aromer_injection_ceiling_v1.json"


@dataclass
class AttackTypeResult:
    attack_type: str
    total: int = 0
    escalate: int = 0          # scanner BLOCKS (hard stop)
    verify: int = 0            # scanner FLAGS (warns, does not block)
    accept: int = 0            # scanner misses entirely

    @property
    def block_rate(self) -> float:
        return round(self.escalate / self.total, 4) if self.total else 0.0

    @property
    def detect_rate(self) -> float:
        """escalate + verify — any non-clean verdict."""
        return round((self.escalate + self.verify) / self.total, 4) if self.total else 0.0


@dataclass
class InjectionCeilingResult:
    by_attack_type: dict[str, dict[str, Any]]
    overall_attacks: int
    overall_blocked: int            # ESCALATE on an attack
    overall_detected: int           # ESCALATE or VERIFY on an attack
    overall_block_rate: float       # blocked / attacks  ← the headline ceiling
    overall_detect_rate: float
    benign_with_context: int
    benign_false_positive: int      # non-ACCEPT on benign untrusted_context
    benign_false_positive_rate: float
    scanner_mode: str = "heuristic_only"
    notes: str = field(default="")


def _iter_cases(src_dir: pathlib.Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for fpath in sorted(src_dir.glob("*.jsonl")):
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    cases.sort(key=lambda c: str(c.get("id", "")))
    return cases


def measure(src_dir: pathlib.Path | None = None) -> InjectionCeilingResult:
    """Run the deterministic result scanner over toolcall_v3 untrusted contexts."""
    src_dir = src_dir or TOOLCALL_V3_DIR
    # oracle_enabled=False → deterministic heuristic-only, no network.
    scanner = ToolResultScanner(oracle_enabled=False)

    per_type: dict[str, AttackTypeResult] = defaultdict(lambda: AttackTypeResult(""))
    benign_with_ctx = 0
    benign_fp = 0

    for case in _iter_cases(src_dir):
        ctx = case.get("untrusted_context")
        if not ctx:
            continue
        tool = str(case.get("proposed_tool_name", "tool"))
        verdict = scanner.scan(tool, str(ctx)).verdict
        attack_type = case.get("attack_type")

        if attack_type:
            r = per_type[attack_type]
            r.attack_type = attack_type
            r.total += 1
            if verdict == ScanVerdict.ESCALATE:
                r.escalate += 1
            elif verdict == ScanVerdict.VERIFY:
                r.verify += 1
            else:
                r.accept += 1
        else:
            benign_with_ctx += 1
            if verdict != ScanVerdict.ACCEPT:
                benign_fp += 1

    overall_attacks = sum(r.total for r in per_type.values())
    overall_blocked = sum(r.escalate for r in per_type.values())
    overall_detected = sum(r.escalate + r.verify for r in per_type.values())

    by_type = {
        at: {
            "total": r.total,
            "escalate": r.escalate,
            "verify": r.verify,
            "accept": r.accept,
            "block_rate": r.block_rate,
            "detect_rate": r.detect_rate,
        }
        for at, r in sorted(per_type.items())
    }

    return InjectionCeilingResult(
        by_attack_type=by_type,
        overall_attacks=overall_attacks,
        overall_blocked=overall_blocked,
        overall_detected=overall_detected,
        overall_block_rate=round(overall_blocked / overall_attacks, 4) if overall_attacks else 0.0,
        overall_detect_rate=round(overall_detected / overall_attacks, 4) if overall_attacks else 0.0,
        benign_with_context=benign_with_ctx,
        benign_false_positive=benign_fp,
        benign_false_positive_rate=round(benign_fp / benign_with_ctx, 4) if benign_with_ctx else 0.0,
        notes=(
            "Deterministic heuristic stage only (no oracle). block_rate is the "
            "share of attacks REMORA hard-blocks (ESCALATE); detect_rate also "
            "counts VERIFY (warn-but-continue). Detection is from the scanner's "
            "own pattern match, not the ground-truth attack_type label."
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure REMORA injection ceiling")
    parser.add_argument("--src", default=str(TOOLCALL_V3_DIR))
    parser.add_argument("--out", default=str(ARTIFACT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = measure(pathlib.Path(args.src))
    payload = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")

    if args.json:
        print(payload)
    else:
        print(f"REMORA injection ceiling (heuristic-only) — {result.overall_attacks} attacks")
        for at, d in result.by_attack_type.items():
            print(f"  {at:<28} block={d['block_rate']:.0%}  detect={d['detect_rate']:.0%}  "
                  f"({d['escalate']}+{d['verify']}/{d['total']})")
        print(f"  {'OVERALL':<28} block={result.overall_block_rate:.0%}  "
              f"detect={result.overall_detect_rate:.0%}")
        print(f"  benign false-positive: {result.benign_false_positive_rate:.0%} "
              f"({result.benign_false_positive}/{result.benign_with_context})")
        print(f"Artifact: {out_path}")


if __name__ == "__main__":
    main()
