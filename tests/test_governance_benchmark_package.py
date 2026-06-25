from __future__ import annotations

import json
from pathlib import Path

from scripts.build_governance_benchmark_package import build_package


def test_build_package_writes_manifest_and_zip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    # Create minimal subset of expected files.
    for rel in [
        "artifacts/benchmark_summary.json",
        "docs/results_snapshot.md",
        "docs/claim_register.md",
        "NEGATIVE_RESULTS.md",
        "README.md",
    ]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")

    out_dir = tmp_path / "pack"
    zip_path = tmp_path / "pack.zip"

    result = build_package(repo_root=repo, out_dir=out_dir, zip_path=zip_path, include_zip=True)

    assert result["copied_files"] > 0
    assert zip_path.exists()

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "governance overlay" in manifest["scope"]
    assert "not agent replacement" in manifest["scope_note"]
    assert "README.md" in manifest["copied_files"]
