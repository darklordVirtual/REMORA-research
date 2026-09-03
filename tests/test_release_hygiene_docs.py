from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]


def test_citation_release_metadata_stays_in_sync() -> None:
    yaml = pytest.importorskip("yaml")
    cff = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    zenodo = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    paper = (ROOT / "paper" / "remora_paper.md").read_text(encoding="utf-8")

    assert cff["version"] == zenodo["version"]
    assert cff["date-released"] == zenodo["publication_date"]
    assert cff["url"] == f"https://github.com/darklordVirtual/REMORA-research/releases/tag/v{cff['version']}"
    assert f"Paper version v{cff['version']}" in paper
    assert f"repository release tag `v{cff['version']}`" in paper

    preferred = cff["preferred-citation"]
    assert preferred["type"] == "software"
    assert preferred["title"] == cff["title"]
    assert preferred["version"] == cff["version"]
    assert preferred["date-released"] == cff["date-released"]
    assert preferred["url"] == cff["url"]
    assert preferred["authors"] == cff["authors"]
    assert zenodo["creators"] == [{"name": "Skogbrott, Stian"}]


def test_reproducibility_scorecard_no_longer_claims_sboms_are_missing() -> None:
    text = (
        ROOT / "docs" / "assurance" / "reproducibility_scorecard_v1.md"
    ).read_text(encoding="utf-8")
    assert "no `uv.lock`, no SBOM" not in text
    assert "| SBOM / Docker digests | Missing |" not in text
    assert "- **SPDX/CycloneDX SBOM**, not present." not in text
    assert "| `quality-gates.yml` | push/PR to main |" not in text
    assert "CycloneDX SBOMs are generated in CI" in text
    assert "future tags can carry this attested release bundle" in text
