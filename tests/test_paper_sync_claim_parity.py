# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every CLAIM id in the paper .md must reach the .tex (and thus the PDF).

The .md is the version authority but the PDF is what reviewers cite. A claim
id that lives only in the .md means the shipped PDF asserts a result without
naming the register entry that governs it. Added 2026-09-03 with the paper
truth pass.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

#: Documentation/register consistency gate, not a behaviour test.
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "check_paper_sync", ROOT / "scripts" / "check_paper_sync.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_paper_sync = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_paper_sync)


def test_repository_paper_sources_have_claim_id_parity() -> None:
    md = (ROOT / "paper" / "remora_paper.md").read_text(encoding="utf-8")
    tex = (ROOT / "paper" / "remora_paper.tex").read_text(encoding="utf-8")
    assert check_paper_sync._claim_id_parity_errors(md, tex) == []


def test_md_only_claim_id_is_reported() -> None:
    errors = check_paper_sync._claim_id_parity_errors(
        "the abstract cites CLAIM-042 and CLAIM-019", "only CLAIM-019 here"
    )
    assert len(errors) == 1
    assert "CLAIM-042" in errors[0]


def test_tex_only_claim_id_is_allowed() -> None:
    assert check_paper_sync._claim_id_parity_errors(
        "cites CLAIM-019", "CLAIM-019 and a figure-only CLAIM-013"
    ) == []


def test_withdrawn_ablation_attribution_is_a_stale_phrase() -> None:
    phrases = {phrase for phrase, _ in check_paper_sync.STALE_PHRASES}
    assert {"attributable entirely", "attributes that zero"} <= phrases


def test_paper_sources_carry_no_ablation_attribution_wording() -> None:
    for name in ("remora_paper.md", "remora_paper.tex"):
        text = (ROOT / "paper" / name).read_text(encoding="utf-8")
        for phrase in ("attributable entirely", "attributes that zero"):
            assert phrase not in text, f"{name} carries {phrase!r}"


def test_every_md_claim_id_is_well_formed() -> None:
    md = (ROOT / "paper" / "remora_paper.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"CLAIM-\d{3}", md))
    assert ids, "the paper cites no claim ids at all"
