#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Check that headline claims in docs align with canonical benchmark metrics."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "artifacts" / "benchmark_summary.json"
README = ROOT / "README.md"
WHITEPAPER = ROOT / "paper" / "whitepaper.md"
RESULTS_SNAPSHOT = ROOT / "docs" / "results_snapshot.md"


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def ensure_contains(text: str, needle: str, where: str) -> None:
    if needle not in text:
        fail(f"Missing '{needle}' in {where}")


def ensure_pattern(text: str, pattern: str, where: str) -> None:
    if not re.search(pattern, text, flags=re.IGNORECASE):
        fail(f"Missing pattern /{pattern}/ in {where}")


def ensure_absent_pattern(text: str, pattern: str, where: str) -> None:
    if re.search(pattern, text, flags=re.IGNORECASE):
        fail(f"Forbidden claim pattern /{pattern}/ found in {where}")


def ensure_no_unqualified_majority_superiority(text: str, where: str) -> None:
    """Disallow unqualified superiority claims over majority voting.

    Negated contexts like "does not outperform majority" are allowed.
    """
    lower = text.lower()
    for m in re.finditer(r"\b(?:beat(?:s)?|outperform(?:s)?)\s+majority\b", lower):
        window = lower[max(0, m.start() - 40):m.start()]
        if any(neg in window for neg in ("does not", "do not", "not ", "never")):
            continue
        fail(f"Unqualified majority-superiority claim found in {where}: '{m.group(0)}'")


def read_utf8(path: Path) -> str:
    # Robust on local Windows and CI; avoids cp1252 decoding surprises.
    return path.read_text(encoding="utf-8", errors="replace")


def ensure_pct_pattern(text: str, value: float, where: str) -> None:
    # Accept both "57.0%" and "57.0 %" to avoid format-only false negatives.
    pattern = rf"{value:.1f}\s*%"
    ensure_pattern(text, pattern, where)


def main() -> None:
    if not SUMMARY.exists():
        fail("Missing artifacts/benchmark_summary.json. Run scripts/generate_results_snapshot.py first.")
    if not RESULTS_SNAPSHOT.exists():
        fail("Missing docs/results_snapshot.md. Run scripts/generate_results_snapshot.py first.")

    summary = json.loads(read_utf8(SUMMARY))
    h = summary["headline"]

    readme = read_utf8(README)
    whitepaper = read_utf8(WHITEPAPER)
    results_snapshot = read_utf8(RESULTS_SNAPSHOT)

    # Canonical percentages must appear in technical artifacts.
    technical_pcts = [
        h["A_single_accuracy_pct"],
        h["B_majority_accuracy_pct"],
        h["C_remora_accuracy_pct"],
        h["D2_balanced_accuracy_pct"],
        h["D3_hybrid_accuracy_pct"],
        h["C_remora_etr_pct"],
        h["D2_balanced_etr_pct"],
        h["D3_hybrid_etr_pct"],
    ]
    for v in technical_pcts:
        ensure_pct_pattern(results_snapshot, float(v), "docs/results_snapshot.md")
        ensure_pct_pattern(whitepaper, float(v), "paper/whitepaper.md")

    # README is narrative and should include at least baseline anchors from the
    # canonical benchmark, but does not need every ablation percentage.
    ensure_pct_pattern(readme, float(h["A_single_accuracy_pct"]), "README.md")
    ensure_pct_pattern(readme, float(h["B_majority_accuracy_pct"]), "README.md")

    # Benchmark size consistency.
    n_items = int(summary["n_items"])
    ensure_pattern(readme, rf"N\s*=\s*{n_items}", "README.md")
    ensure_pattern(whitepaper, rf"N\s*=\s*{n_items}", "paper/whitepaper.md")
    ensure_pattern(results_snapshot, rf"N\s*=\s*{n_items}", "docs/results_snapshot.md")

    # Claim hygiene guardrail.
    ensure_no_unqualified_majority_superiority(readme, "README.md")
    ensure_no_unqualified_majority_superiority(whitepaper, "paper/whitepaper.md")

    print("[OK] Claim consistency checks passed")


if __name__ == "__main__":
    main()
