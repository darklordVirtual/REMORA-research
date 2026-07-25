# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Paper sources must never re-acquire superseded claims (REM-046).

External reviews 2026-07-24/25 found the LaTeX source publishing withdrawn
tool-call numbers after the markdown master had been remediated. This guard
fails CI if any superseded value or withdrawn formulation reappears in the
paper sources the PDF is compiled from.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEX = ROOT / "paper" / "remora_paper.tex"
MD = ROOT / "paper" / "remora_paper.md"

# Superseded values / withdrawn formulations. Each entry: (pattern,
# allowed_contexts) — a line containing the pattern is only permitted when at
# least one allowed-context substring appears on the same line (used for the
# historical footnotes that explain WHY the old numbers were withdrawn).
FORBIDDEN: list[tuple[str, tuple[str, ...]]] = [
    ("0.55", ()),                         # withdrawn task-level Wilson upper bound
    ("[0.00\\%, 0.55\\%]", ()),
    # Withdrawn baseline range. Permitted ONLY on lines that explain the
    # withdrawal (the historical footnote / leakage narrative); any line
    # presenting 10-20% as a current result fails.
    ("10--20", ("inflated",)),            # tex historical footnote
    ("10–20%", ("inflated", "eliminates")),  # md leakage narrative (en-dash)
    ("Kirsch,", ()),                      # wrong PVD author attribution
    ("Kirsch et al", ()),
    ("is queried first", ()),             # OPA overstatement
    ("guaranteed_risk_bound` (", ()),     # renamed CRC field presented as current
    ("deployable operating point", ()),
    ("hallucination-rate bound", ()),
    ("no tagged release", ()),
]


def _offending_lines(path: Path) -> list[str]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for pattern, allowed in FORBIDDEN:
            if pattern in line and not any(ctx in line for ctx in allowed):
                out.append(f"{path.name}:{i}: {pattern!r} -> {line.strip()[:120]}")
    return out


def test_tex_source_has_no_superseded_claims() -> None:
    offenders = _offending_lines(TEX)
    assert not offenders, (
        "superseded claims re-entered the LaTeX paper source:\n"
        + "\n".join(offenders)
    )


def test_md_source_has_no_superseded_claims() -> None:
    offenders = _offending_lines(MD)
    assert not offenders, (
        "superseded claims re-entered the markdown paper source:\n"
        + "\n".join(offenders)
    )
