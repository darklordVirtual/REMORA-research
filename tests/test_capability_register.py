# Author: Stian Skogbrott
# License: Apache-2.0
"""The capability register is the source of truth for wiring status —
structurally validated so it cannot rot (external documentation review)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "capability_register_v1.yaml"

VALID_STATUSES = {
    "IMPLEMENTED_LIBRARY",
    "WIRED_REFERENCE_PATH",
    "WIRED_API_PATH",
    "PERSISTED_ATOMIC",
    "ENFORCED_PRODUCTION",
    "EXTERNALLY_VERIFIED",
}


def _load() -> dict:
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8"))


def test_register_structure() -> None:
    data = _load()
    caps = data["capabilities"]
    assert caps, "register must not be empty"
    ids = [c["id"] for c in caps]
    assert len(ids) == len(set(ids)), "duplicate capability ids"
    for cap in caps:
        assert cap["status"] in VALID_STATUSES, cap["id"]
        assert cap.get("caveat", "").strip(), f"{cap['id']} must state its caveat"
        assert cap.get("evidence"), f"{cap['id']} must cite evidence"


def test_every_evidence_path_exists() -> None:
    for cap in _load()["capabilities"]:
        for rel in cap["evidence"]:
            assert (ROOT / rel).exists(), f"{cap['id']}: missing evidence {rel}"


def test_no_capability_claims_production_or_external_status() -> None:
    """SHADOW_ONLY invariant: until REM-021 closes, nothing may claim the two
    top rungs. Loosening this test is itself a release decision."""
    for cap in _load()["capabilities"]:
        assert cap["status"] not in {"ENFORCED_PRODUCTION", "EXTERNALLY_VERIFIED"}, (
            f"{cap['id']} claims {cap['status']} while deployment is SHADOW_ONLY"
        )
