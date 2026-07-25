# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REM-014 structural verifier for the imported AgentHarm benchmark (P0-2).

The AgentHarm artifact (CLAIM-002) was produced in the REMORA main implementation
repo with experiments/agentharm/score_guardrail.py and copied here for public
verifiability. It is NOT regenerated from this repository, and
scripts/run_agentharm_benchmark.py here implements a different intent-gating
protocol that yields a different artifact. This gate therefore does NOT claim
reproduction; it validates the imported artifact's structure, headline numbers,
their agreement with the claim register, and its provenance attribution.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "results" / "external_benchmark_agentharm_v1.json"
SIDECAR = ROOT / "results" / "external_benchmark_agentharm_v1.provenance.json"
REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"

pytestmark = pytest.mark.rem014_gate


def _artifact() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _claim_002_block() -> str:
    reg = REGISTER.read_text(encoding="utf-8")
    m = re.search(r"  - id: CLAIM-002.*?(?=\n  - id: |\Z)", reg, re.S)
    assert m, "CLAIM-002 not found in register"
    return m.group(0)


def test_agentharm_artifact_structure_and_numbers() -> None:
    d = _artifact()
    assert d["schema"] == "external_benchmark_agentharm_v1"
    assert d["n_harmful"] == 208
    assert d["n_benign"] == 208
    assert d["n_total"] == 416
    assert d["n_harmful_blocked"] == 208
    assert d["n_harmful_false_accept"] == 0
    assert d["false_accept_rate"] == 0.0
    assert d["gate"] == "PASS"
    assert d["dry_run"] is False


def test_agentharm_numbers_match_claim_register() -> None:
    block = _claim_002_block()
    assert "far_pct: 0.0" in block
    assert "n: 208" in block
    d = _artifact()
    # Registered far_pct (0.0) must equal the artifact's rate as a percentage.
    assert round(d["false_accept_rate"] * 100, 2) == 0.0
    assert d["n_harmful"] == 208


def test_agentharm_is_imported_historical_not_reproduced() -> None:
    """Provenance must attribute the artifact to the main implementation repo,
    matching its reclassification (the local reproduce path is not authoritative)."""
    assert SIDECAR.exists(), "missing provenance sidecar"
    prov = json.loads(SIDECAR.read_text(encoding="utf-8"))
    assert prov["schema"] == "result_provenance_v1"
    assert prov["script"] == "experiments/agentharm/score_guardrail.py"
    assert re.fullmatch(r"[0-9a-f]{40}", prov["commit_hash"]), "expected a 40-char source commit"
    assert "main" in prov["notes"].lower() and "repo" in prov["notes"].lower()
    # The register must NOT present the local script as a faithful reproduction.
    block = _claim_002_block()
    assert "IMPORTED HISTORICAL RESULT" in block
