# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Documentation contract only; not a proof of REMORA execution."""
from pathlib import Path
import pytest

pytestmark = pytest.mark.docgate
ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/design/formal-mathematical-assurance-v1.md"
ROADMAP = ROOT / "docs/13-research-frontier-roadmap.md"
MATRIX = ROOT / "docs/research/research_control_matrix_v1.yaml"

def test_sdd_exists_and_links_real_current_sources():
    text = SPEC.read_text(encoding="utf-8")
    for path in ["remora/lyapunov.py", "remora/selective/confidence_sequence.py",
                 "tests/test_confidence_sequence.py", "remora/federation/",
                 "docs/research/research_control_matrix_v1.yaml"]:
        assert (ROOT / path).exists(), path
        assert path in text

def test_no_premature_proof_or_runtime_claim():
    text = SPEC.read_text(encoding="utf-8")
    assert "PROPOSED / NOT IMPLEMENTED" in text
    assert "not a replacement" in text
    assert "MODEL_PROVEN" in text and "TESTED_REFINEMENT" in text
    assert "NOT_ESTABLISHED" in text

def test_roadmap_and_matrix_follow_existing_governance():
    assert "## RF-16" in ROADMAP.read_text(encoding="utf-8")
    assert "formal-mathematical-assurance-v1.md" in ROADMAP.read_text(encoding="utf-8")
    assert "RF-16" in MATRIX.read_text(encoding="utf-8")
    assert "NOT by an invented RES entry" in MATRIX.read_text(encoding="utf-8")

def test_acceptance_ids_and_sources_are_documented():
    text = SPEC.read_text(encoding="utf-8")
    for i in range(1,13):
        assert f"FM-AC{i:02}" in text
    for i in range(1,7):
        assert f"FM-T{i:02}" in text
    assert "https://github.com/openai/math" in text
