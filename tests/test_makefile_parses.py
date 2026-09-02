# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The documented reviewer entry point has to be startable.

An external review (2026-08-30) found `make audit` dead since 2026-08-29: an
``@echo`` string in the audit recipe carried a literal newline, so GNU make
reported ``missing separator`` and **every** target failed before its first
command -- `make help`, `make test`, `make lint`, `make audit`,
`make credibility-pack`, `make external-review`.

The severity is not developer convenience. `paper/remora_paper.md`,
`docs/archive/legacy/review_checklist.md` ("make audit (canonical reviewer
gate)"), `docs/archive/external_review_round2_plan.md` and
`docs/deployment/onprem-airgapped.md` all instruct an external reviewer or an
on-premises operator to run targets that could not start. No workflow invoked
make, so CI was green throughout.

CI now runs `make help` and `make -n audit` (see quality-gates.yml). This file
covers the same defect class where make is not installed -- Windows
development machines, most notably -- by checking the structural property that
was violated rather than by shelling out.
"""
from __future__ import annotations

from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"


def _recipe_lines() -> list[tuple[int, str]]:
    """Every tab-prefixed line, with its 1-based line number."""
    text = MAKEFILE.read_text(encoding="utf-8")
    return [
        (n, line)
        for n, line in enumerate(text.split("\n"), 1)
        if line.startswith("\t")
    ]


def test_no_recipe_line_carries_an_unterminated_quote():
    """A quote left open runs the string into the next physical line.

    That is exactly the 2026-08-29 defect: the recipe line ended mid-string,
    so the continuation landed at column 0 with no tab and make refused the
    whole file. A recipe line that ends inside a quote is the signature, and
    it is checkable without make.
    """
    offenders = [
        (n, line.strip()[:60])
        for n, line in _recipe_lines()
        if line.count('"') % 2 and not line.rstrip().endswith("\\")
    ]
    assert offenders == [], (
        "recipe line(s) end inside a double-quoted string; the next line "
        f"becomes a non-tab continuation and make refuses the file: {offenders}"
    )


def test_no_line_between_recipe_lines_lacks_its_tab():
    """A bare line wedged between two recipe lines is the failure make reports.

    Checked independently of the quote rule, because the same breakage can
    arrive through a stray edit rather than through an open string.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    lines = text.split("\n")
    offenders = []
    for i in range(1, len(lines) - 1):
        previous, current, following = lines[i - 1], lines[i], lines[i + 1]
        if not previous.startswith("\t") or not following.startswith("\t"):
            continue
        if current.startswith("\t") or not current.strip():
            continue
        if current.lstrip().startswith("#"):
            continue
        offenders.append((i + 1, current[:60]))
    assert offenders == [], (
        f"line(s) inside a recipe block do not begin with a tab: {offenders}"
    )


def test_audit_target_still_exists():
    """The canonical reviewer gate is named in the paper; it must not vanish.

    A rename would leave the same documents pointing at nothing, which is the
    docs-drift half of the same finding.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "\naudit:" in text, "the 'audit' target named by the review protocol is gone"
