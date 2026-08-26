# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Claim-bound JSON artifacts must carry a .provenance.json sidecar.

External review 2026-08-26: provenance for results/*.json was advisory
everywhere. For an artifact a claim in the register points at, it is now a
hard error in scripts/check_claim_provenance.py; pre-protocol artifacts are
grandfathered by id in claim_provenance_baseline.json and never backfilled.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "check_claim_provenance", ROOT / "scripts" / "check_claim_provenance.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def _claim(rel: str) -> list[dict]:
    return [{"id": "CLAIM-T", "artifact": [rel]}]


def test_missing_sidecar_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "r.json").write_text("{}", encoding="utf-8")
    ids = [eid for eid, _ in mod.check_artifacts(_claim("results/r.json"), root=tmp_path)]
    assert ids == ["sidecar-missing:CLAIM-T:results/r.json"]


def test_present_sidecar_passes(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "r.json").write_text("{}", encoding="utf-8")
    (tmp_path / "results" / "r.provenance.json").write_text("{}", encoding="utf-8")
    assert mod.check_artifacts(_claim("results/r.json"), root=tmp_path) == []


def test_non_json_artifacts_are_not_subject(tmp_path: Path) -> None:
    (tmp_path / "paper.pdf").write_bytes(b"%PDF")
    assert mod.check_artifacts(_claim("paper.pdf"), root=tmp_path) == []


def test_missing_artifact_reports_once_not_twice(tmp_path: Path) -> None:
    ids = [eid for eid, _ in mod.check_artifacts(_claim("results/none.json"), root=tmp_path)]
    assert ids == ["artifact-missing:CLAIM-T:results/none.json"]


def test_every_grandfathered_entry_still_lacks_its_sidecar() -> None:
    """A baseline entry whose artifact gained a real sidecar must be removed."""
    baseline = json.loads(
        (ROOT / "docs" / "assurance" / "claim_provenance_baseline.json").read_text(encoding="utf-8")
    )
    for eid in baseline["known_violations"]:
        if not eid.startswith("sidecar-missing:"):
            continue
        rel = eid.split(":", 2)[2]
        sidecar = ROOT / (rel[: -len(".json")] + ".provenance.json")
        assert not sidecar.exists(), f"{rel} now has a sidecar; drop {eid} from the baseline"
