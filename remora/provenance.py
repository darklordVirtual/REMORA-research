"""Provenance metadata builder for REMORA result artifacts.

Implements the schema defined in docs/assurance/artifact_provenance_spec_v1.md.
Required fields: schema, schema_version, commit_hash, generated_at, script, n_samples.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA = "result_provenance_v1"
_SCHEMA_VERSION = "1"


def _get_commit_hash() -> str:
    """Return full 40-char HEAD commit hash, or 'unknown' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            if len(sha) == 40:
                return sha
    except Exception:
        pass
    return "unknown"


def build_provenance(
    script: str,
    generated_at: str,
    n_samples: int,
    *,
    commit_hash: str | None = None,
    gate: str | None = None,
    model_version: str | None = None,
    notes: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a provenance metadata dict for a result artifact.

    Args:
        script: Relative path of the producing script from repo root.
        generated_at: UTC ISO-8601 timestamp string of when the artifact was produced.
        n_samples: Total number of items evaluated.
        commit_hash: Full 40-char SHA of the system commit used. Defaults to HEAD.
        gate: Safety gate result ("PASS", "FAIL", "CONDITIONAL", or None).
        model_version: Model identifier when a model was used; None if not applicable.
        notes: Free-form human-readable notes.
        **extra: Additional fields passed through verbatim.

    Returns:
        Dict conforming to result_provenance_v1 schema.
    """
    if commit_hash is None:
        commit_hash = _get_commit_hash()

    record: dict[str, Any] = {
        "schema": _SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "commit_hash": commit_hash,
        "generated_at": generated_at,
        "script": script,
        "n_samples": n_samples,
    }
    if model_version is not None:
        record["model_version"] = model_version
    if gate is not None:
        record["gate"] = gate
    if notes is not None:
        record["notes"] = notes
    record.update(extra)
    return record
