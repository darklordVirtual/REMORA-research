"""Guard the frontend benchmark page against stale result artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "frontend" / "src" / "content" / "benchmark-snapshot.json"

ARTIFACT_PATHS = [
    "results/toolcall_benchmark_v2_results.json",
    "results/selective_n500_holdout_results.json",
    "results/end_to_end_n500_v3.json",
    "results/conformal_guardrail_holdout.json",
]


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_snapshot_value(value: object) -> object:
    if isinstance(value, dict):
        return {key: _normalize_snapshot_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_snapshot_value(item) for item in value]
    if isinstance(value, str) and ("\\" in value):
        normalized = value.replace("\\", "/")
        if normalized.startswith(("artifacts/", "results/")):
            return normalized
    return value


def test_frontend_benchmark_snapshot_matches_result_artifacts() -> None:
    snapshot = _load_json(SNAPSHOT_PATH)

    assert snapshot["artifact_paths"] == ARTIFACT_PATHS
    for relative_path in ARTIFACT_PATHS:
        artifact = _normalize_snapshot_value(_load_json(ROOT / relative_path))
        assert snapshot["artifacts"][relative_path] == artifact


def test_frontend_benchmark_snapshot_source_hashes_match() -> None:
    snapshot = _load_json(SNAPSHOT_PATH)

    for relative_path in ARTIFACT_PATHS:
        artifact = _normalize_snapshot_value(_load_json(ROOT / relative_path))
        assert snapshot["source_hashes"][relative_path] == _sha256(artifact)
