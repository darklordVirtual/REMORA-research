#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Build the frontend benchmark snapshot from committed result artifacts.

The frontend cannot import files outside its own project root in Vite builds.
This script creates a deterministic JSON snapshot that the benchmark route can
consume while tests keep the snapshot locked to the canonical artifacts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ARTIFACT_PATHS = [
    "results/toolcall_benchmark_v2_results.json",
    "results/selective_n500_holdout_results.json",
    "results/end_to_end_n500_v3.json",
    "results/conformal_guardrail_holdout.json",
]

OUT_PATH = ROOT / "frontend" / "src" / "content" / "benchmark-snapshot.json"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_snapshot_value(value: object) -> object:
    """Normalize platform-specific path strings for frontend consumption."""
    if isinstance(value, dict):
        return {key: _normalize_snapshot_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_snapshot_value(item) for item in value]
    if isinstance(value, str) and ("\\" in value):
        normalized = value.replace("\\", "/")
        if normalized.startswith(("artifacts/", "results/")):
            return normalized
    return value


def main() -> None:
    artifacts: dict[str, object] = {}
    source_hashes: dict[str, str] = {}

    for relative_path in ARTIFACT_PATHS:
        path = ROOT / relative_path
        data = _normalize_snapshot_value(json.loads(path.read_text(encoding="utf-8")))
        canonical = _canonical_json(data)
        artifacts[relative_path] = data
        source_hashes[relative_path] = _sha256_text(canonical)

    snapshot_basis = _canonical_json(
        {
            "artifact_paths": ARTIFACT_PATHS,
            "source_hashes": source_hashes,
        }
    )
    snapshot = {
        "artifact_paths": ARTIFACT_PATHS,
        "artifacts": artifacts,
        "generated_by": "scripts/build_frontend_benchmark_snapshot.py",
        "snapshot_hash": _sha256_text(snapshot_basis),
        "source_hashes": source_hashes,
    }

    OUT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({len(ARTIFACT_PATHS)} artifacts)")


if __name__ == "__main__":
    main()
