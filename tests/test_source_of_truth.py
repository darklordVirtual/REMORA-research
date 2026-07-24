# Author: Stian Skogbrott
# License: Apache-2.0
"""Single source of truth for claims (P0-5).

docs/assurance/claim_register_v1.yaml is the one authoritative claim register.
Narrative docs are companions/views; docs/thermodynamics/claim_ledger.yaml
governs thermodynamics sub-claims only. This guard fails if any live doc
(outside docs/archive/) declares a different overall authority.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
COMPANION = ROOT / "docs" / "claim_register.md"

# The exact unscoped statement that previously made the thermodynamics ledger
# the overall source of truth. It must not reappear in any live doc.
FORBIDDEN = "`docs/thermodynamics/claim_ledger.yaml` is source of truth."


def test_register_declares_itself_authoritative() -> None:
    header = REGISTER.read_text(encoding="utf-8")[:600]
    assert "single authoritative claim register" in header


def test_companion_points_at_the_register() -> None:
    text = COMPANION.read_text(encoding="utf-8")
    assert "docs/assurance/claim_register_v1.yaml`\nis the source of truth" in text
    # Its consistency rule now names the register as overall authority.
    assert "claim_register_v1.yaml` is the source of truth for overall claim" in text


def test_no_live_doc_names_a_competing_authority() -> None:
    offenders = []
    for md in (ROOT / "docs").rglob("*.md"):
        if "archive" in md.parts:
            continue  # archived drift reports may quote the old wording
        if FORBIDDEN in md.read_text(encoding="utf-8"):
            offenders.append(str(md.relative_to(ROOT)))
    assert not offenders, f"docs still name the thermo ledger as overall source of truth: {offenders}"
