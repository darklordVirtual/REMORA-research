"""Regression test: JSON artifacts in results/ must use forward slashes in path fields.

Prevents the Windows str(Path) backslash regression that broke the frontend
snapshot test in CI (Linux). See experiments/conformal_phase_guardrail.py fix.
"""
from __future__ import annotations

import json
from pathlib import Path

_RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"

# Committed result artifacts that contain file path fields.
_PATH_FIELD_KEYS = {"input", "source", "output", "path", "file"}


def _has_backslash_path(obj: object) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _PATH_FIELD_KEYS and isinstance(v, str) and "\\" in v:
                return True
            if _has_backslash_path(v):
                return True
    elif isinstance(obj, list):
        return any(_has_backslash_path(item) for item in obj)
    return False


def test_results_json_files_use_forward_slashes_in_path_fields() -> None:
    """All committed result JSON files must store path fields with forward slashes."""
    if not _RESULTS_DIR.exists():
        return  # nothing to check

    violations: list[str] = []
    for json_file in sorted(_RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if _has_backslash_path(data):
            violations.append(json_file.name)

    assert violations == [], (
        f"These result JSON files contain Windows backslashes in path fields "
        f"(will fail on Linux CI): {violations}. "
        "Fix: use Path.as_posix() instead of str(Path) when serialising paths."
    )
