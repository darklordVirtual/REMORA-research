# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Result-provenance sidecar writer (schema result_provenance_v2).

Research audit 2026-07-27: result artifacts lacked code/environment binding
(no git commit, worktree state, Python version, lock hash or input hashes).
Every future result should be written together with a sidecar produced here:

    from result_provenance import write_sidecar
    write_sidecar(result_path, script="experiments/x.py",
                  inputs={"tasks": tasks_path, "labels": labels_path},
                  random_seeds=[42], command="python experiments/x.py")

v2 extends result_provenance_v1 (commit_hash/generated_at/script/n_samples)
with worktree state, environment binding and content hashes. Hashes are
LF-normalized, matching the artifact-manifest hash protocol.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "requirements-lock.txt"


def _sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout.strip()


def build_provenance(
    *,
    script: str,
    inputs: Mapping[str, Path] | None = None,
    random_seeds: Iterable[int] | None = None,
    command: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect code/environment/input provenance for a result artifact."""
    prov: dict[str, Any] = {
        "schema": "result_provenance_v2",
        "git_commit": _git("rev-parse", "HEAD"),
        "worktree_clean": _git("status", "--porcelain") == "",
        "python_version": platform.python_version(),
        "dependency_lock_sha256": (
            _sha256_lf(LOCK_FILE) if LOCK_FILE.exists() else None
        ),
        "script": script,
        "input_sha256": {
            name: _sha256_lf(Path(p)) for name, p in (inputs or {}).items()
        },
        "random_seeds": list(random_seeds) if random_seeds is not None else None,
        "command": command,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        prov.update(extra)
    return prov


def write_sidecar(
    artifact_path: Path,
    *,
    script: str,
    inputs: Mapping[str, Path] | None = None,
    random_seeds: Iterable[int] | None = None,
    command: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Write `<artifact>.provenance.json` next to the artifact and return it."""
    artifact_path = Path(artifact_path)
    prov = build_provenance(
        script=script,
        inputs=inputs,
        random_seeds=random_seeds,
        command=command,
        extra=extra,
    )
    prov["artifact"] = artifact_path.name
    # LF-normalized, matching _sha256_lf for inputs and the LF hash protocol
    # of docs/assurance/artifact_manifest_v1.md — a raw-bytes hash diverged
    # from the manifest on Windows working trees (self-review 2026-07-28).
    prov["artifact_sha256"] = _sha256_lf(artifact_path)
    sidecar = artifact_path.with_name(
        artifact_path.name.rsplit(".", 1)[0] + ".provenance.json"
    )
    sidecar.write_text(json.dumps(prov, indent=2), encoding="utf-8", newline="\n")
    return sidecar
