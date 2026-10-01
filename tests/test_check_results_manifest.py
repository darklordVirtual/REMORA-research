# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The results manifest gate fails on each way a result can lose its class."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_results_manifest as gate  # noqa: E402


def _tree(tmp_path: Path, results: list[str], entries: list[dict]) -> Path:
    for rel in results:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("{}", encoding="utf-8")
    manifest = tmp_path / gate.MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(yaml.safe_dump({"schema_version": "1", "results": entries}), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


REGEN = {"path": "results/a.json", "class": "regenerable",
         "generator": "python experiments/a.py", "verified_by": "ci"}


def test_complete_manifest_passes(tmp_path):
    errors, counts = gate.check(_tree(tmp_path, ["results/a.json"], [REGEN]))
    assert errors == [] and counts["regenerable"] == 1


def test_unlisted_result_fails(tmp_path):
    errors, _ = gate.check(_tree(tmp_path, ["results/a.json", "results/b.json"], [REGEN]))
    assert errors == ["results/b.json: committed result with no manifest entry"]


def test_entry_without_file_fails(tmp_path):
    errors, _ = gate.check(_tree(tmp_path, [], [REGEN]))
    assert errors == ["results/a.json: manifest entry for a file that is not tracked"]


def test_drifted_needs_what_differs_and_who_tracks_it(tmp_path):
    entry = {"path": "results/a.json", "class": "drifted", "generator": "python a.py"}
    errors, _ = gate.check(_tree(tmp_path, ["results/a.json"], [entry]))
    assert "results/a.json: class drifted needs 'drift'" in errors
    assert "results/a.json: class drifted needs 'tracking'" in errors


def test_unknown_class_and_orphan_sidecar_fail(tmp_path):
    entries = [{"path": "results/a.json", "class": "probably_fine"},
               {"path": "results/a.provenance.json", "class": "sidecar", "of": "results/gone.json"}]
    errors, _ = gate.check(_tree(tmp_path, ["results/a.json", "results/a.provenance.json"], entries))
    assert "results/a.json: unknown class 'probably_fine'" in errors
    assert any("sidecar of 'results/gone.json'" in e for e in errors)


def test_the_repository_manifest_passes():
    errors, counts = gate.check(ROOT)
    assert errors == []
    assert sum(counts.values()) == len(gate._tracked_results(ROOT))


def _sidecar_tree(tmp_path: Path, sidecar: dict) -> Path:
    import json

    entries = [REGEN, {"path": "results/a.provenance.json", "class": "sidecar",
                       "of": "results/a.json"}]
    root = _tree(tmp_path, ["results/a.json", "results/a.provenance.json"], entries)
    (root / "results/a.json").write_bytes(b'{\n  "n": 1\n}\n')
    (root / "results/a.provenance.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return root


def _lf_sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def test_sidecar_hash_matching_the_result_passes(tmp_path):
    root = _sidecar_tree(tmp_path, {"artifact_sha256": _lf_sha(b'{\n  "n": 1\n}\n')})
    errors, _ = gate.check(root)
    assert errors == []


def test_sidecar_hash_taken_over_crlf_bytes_fails(tmp_path):
    """The 2026-07 defect: a hash over CRLF bytes never matches the LF file."""
    import hashlib

    crlf = hashlib.sha256(b'{\r\n  "n": 1\r\n}\r\n').hexdigest()
    errors, _ = gate.check(_sidecar_tree(tmp_path, {"artifact_sha256": crlf}))
    assert errors == [
        "results/a.provenance.json: artifact_sha256 does not match results/a.json"
    ]


def test_sidecar_without_a_hash_is_not_checked(tmp_path):
    """Older sidecar schemas carry no artifact hash; absence is not a mismatch."""
    errors, _ = gate.check(_sidecar_tree(tmp_path, {"schema": "old"}))
    assert errors == []
