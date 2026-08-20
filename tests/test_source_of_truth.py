# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Single source of truth for claims (P0-5).

docs/assurance/claim_register_v1.yaml is the one authoritative claim register.
Narrative docs are companions/views; docs/archive/legacy/claim_ledger.yaml
governs thermodynamics sub-claims only. This guard fails if any live doc,
YAML file, or credibility-pack file declares a different overall authority.
"""
from __future__ import annotations

import pytest

from pathlib import Path

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
COMPANION = ROOT / "docs" / "claim_register.md"
THERMO_LEDGER = ROOT / "docs" / "archive" / "legacy" / "claim_ledger.yaml"
PACK = ROOT / "artifacts" / "credibility-pack"

# Statements that previously made the thermodynamics ledger the overall source
# of truth. None may reappear in any live doc, YAML, or pack file.
FORBIDDEN = (
    "`docs/archive/legacy/claim_ledger.yaml` is source of truth.",
    "Single source of truth for what is and is not claimed",
    "single source of truth for what is and is not claimed",
)


def _scan_targets() -> list[Path]:
    files = [
        p
        for pattern in ("*.md", "*.yaml", "*.yml")
        for p in (ROOT / "docs").rglob(pattern)
        if "archive" not in p.parts
    ]
    files += [p for p in PACK.rglob("*") if p.is_file()]
    return files


def test_register_declares_itself_authoritative() -> None:
    header = REGISTER.read_text(encoding="utf-8")[:600]
    assert "single authoritative claim register" in header


def test_thermo_ledger_is_scoped_to_thermodynamics_subclaims() -> None:
    header = THERMO_LEDGER.read_text(encoding="utf-8")[:600]
    assert "thermodynamics sub-claims only" in header
    assert "claim_register_v1.yaml" in header


def test_companion_points_at_the_register() -> None:
    text = COMPANION.read_text(encoding="utf-8")
    assert "docs/assurance/claim_register_v1.yaml`\nis the source of truth" in text
    # Its consistency rule now names the register as overall authority.
    assert "claim_register_v1.yaml` is the source of truth for overall claim" in text


def test_no_live_doc_names_a_competing_authority() -> None:
    offenders = []
    for f in _scan_targets():
        if f == Path(__file__):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for phrase in FORBIDDEN:
            if phrase in text:
                offenders.append(f"{f.relative_to(ROOT)}: {phrase!r}")
    assert not offenders, (
        f"files still name a competing overall source of truth: {offenders}"
    )


def test_credibility_pack_carries_the_authoritative_register() -> None:
    """The pack must ship the authoritative register, not only the
    thermodynamics ledger, and both copies must match their sources
    (LF-normalized, matching the pack hash protocol)."""

    def norm(p: Path) -> bytes:
        return p.read_bytes().replace(b"\r\n", b"\n")

    register_copy = PACK / "claim-register.yaml"
    ledger_copy = PACK / "claim-ledger.yaml"
    assert register_copy.exists(), "pack is missing claim-register.yaml"
    assert norm(register_copy) == norm(REGISTER)
    assert norm(ledger_copy) == norm(THERMO_LEDGER)
