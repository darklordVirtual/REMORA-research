# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Result-provenance sidecar writer (schemas result_provenance_v2 / _v3).

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

v3 (issue #32) is additive and opt-in: v2's single ``worktree_clean`` flag
is evaluated at sidecar-write time — after the run's own outputs exist — so
it reads false for every real round. A caller that (a) captures worktree
state BEFORE the run via :func:`capture_pre_run_state` and (b) declares the
outputs its run is allowed to generate can pass both
``pre_run_worktree_clean`` and ``allowed_generated_outputs`` (both or
neither; a ValueError otherwise). The sidecar is then written as schema
``result_provenance_v3`` with four extra fields:

- ``pre_run_worktree_clean``: the caller-captured pre-run flag.
- ``allowed_generated_outputs``: sorted repo-relative POSIX paths the run
  declares as its own outputs.
- ``post_run_worktree_clean``: true iff nothing outside the declared
  outputs is dirty at write time.
- ``worktree_dirty_beyond_outputs``: the dirty paths not covered by the
  declaration (the drift signal).

The raw ``worktree_clean`` flag is retained in v3 for continuity. Without
the new parameters the writer emits result_provenance_v2 unchanged, so all
existing call sites and committed sidecars stay valid. The manual escape
hatch for a deliberately dirty run (``worktree_diff_sha256`` +
``<artifact>.worktree.diff``, enforced by scripts/check_claim_provenance.py,
issue #88) is supplied via ``extra`` — never auto-generated here.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
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


# Porcelain v1 line: 2-char XY status, one separator space, then the entry.
# _git() strips the overall stdout, which can eat the leading status column
# of the FIRST line (" M path" -> "M path"), so the status is matched as
# 1-2 chars instead of assuming a fixed column.
_PORCELAIN_RE = re.compile(r"^([ MADRCU?!]{1,2})\s(.*)$")


def _worktree_dirty_paths() -> list[str]:
    """Repo-relative POSIX paths reported by ``git status --porcelain``.

    Git prints forward slashes even on Windows. Rename/copy lines record
    both sides; C-style quoted paths (spaces, non-ASCII) are unquoted.
    """
    paths: set[str] = set()
    for line in _git("status", "--porcelain").splitlines():
        if not line.strip():
            continue
        match = _PORCELAIN_RE.match(line)
        if not match:
            continue
        entry = match.group(2)
        parts = entry.split(" -> ") if " -> " in entry else [entry]
        for part in parts:
            part = part.strip()
            if len(part) >= 2 and part[0] == '"' and part[-1] == '"':
                part = (
                    part[1:-1]
                    .encode("latin-1", "backslashreplace")
                    .decode("unicode_escape")
                )
            if part:
                paths.add(part)
    return sorted(paths)


def capture_pre_run_state() -> dict[str, Any]:
    """Snapshot worktree state BEFORE a run generates any outputs (issue #32).

    Call this as the first action of an orchestrated round and pass the
    ``pre_run_worktree_clean`` value through to :func:`write_sidecar`.
    Returns ``{"pre_run_worktree_clean": bool, "pre_run_dirty_paths": [...]}``.
    """
    dirty = _worktree_dirty_paths()
    return {"pre_run_worktree_clean": not dirty, "pre_run_dirty_paths": dirty}


def build_provenance(
    *,
    script: str,
    inputs: Mapping[str, Path] | None = None,
    random_seeds: Iterable[int] | None = None,
    command: str | None = None,
    extra: Mapping[str, Any] | None = None,
    pre_run_worktree_clean: bool | None = None,
    allowed_generated_outputs: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    """Collect code/environment/input provenance for a result artifact.

    Supplying both ``pre_run_worktree_clean`` and
    ``allowed_generated_outputs`` upgrades the record to schema
    result_provenance_v3 (see module docstring); supplying exactly one is a
    ValueError; supplying neither keeps result_provenance_v2 unchanged.
    """
    if (pre_run_worktree_clean is None) != (allowed_generated_outputs is None):
        raise ValueError(
            "result_provenance_v3 requires both pre_run_worktree_clean "
            "(captured before the run) and allowed_generated_outputs"
        )
    v3 = pre_run_worktree_clean is not None
    dirty = _worktree_dirty_paths()
    prov: dict[str, Any] = {
        "schema": "result_provenance_v3" if v3 else "result_provenance_v2",
        "git_commit": _git("rev-parse", "HEAD"),
        "worktree_clean": not dirty,
    }
    if v3:
        assert allowed_generated_outputs is not None
        allowed = sorted(
            {str(p).replace("\\", "/") for p in allowed_generated_outputs}
        )
        beyond = sorted(set(dirty) - set(allowed))
        prov["pre_run_worktree_clean"] = bool(pre_run_worktree_clean)
        prov["allowed_generated_outputs"] = allowed
        prov["post_run_worktree_clean"] = not beyond
        prov["worktree_dirty_beyond_outputs"] = beyond
    prov.update({
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
    })
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
    pre_run_worktree_clean: bool | None = None,
    allowed_generated_outputs: Iterable[str | Path] | None = None,
) -> Path:
    """Write `<artifact>.provenance.json` next to the artifact and return it."""
    artifact_path = Path(artifact_path)
    prov = build_provenance(
        script=script,
        inputs=inputs,
        random_seeds=random_seeds,
        command=command,
        extra=extra,
        pre_run_worktree_clean=pre_run_worktree_clean,
        allowed_generated_outputs=allowed_generated_outputs,
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
