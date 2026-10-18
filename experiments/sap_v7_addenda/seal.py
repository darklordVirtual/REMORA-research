# SPDX-License-Identifier: BUSL-1.1
"""Run gate for the SAP v7 addenda (§15.1).

A study runner calls :func:`open_locked_manifest` before it reads any
test-split content or calls any model. The gate refuses when:

* the manifest file does not exist;
* its status is ``evaluated`` (a second run is not blind);
* its status is anything other than ``locked_never_run``;
* a file the runner depends on is not listed in it;
* any listed file's LF SHA-256 differs from the recorded value;
* the recorded seed is not the plan's seed.

On success it returns a :class:`LockedManifest`. Only this module creates
one, and the builders ask for it before they release test-split content, so
holding one is the proof that the gate passed.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATUS_LOCKED = "locked_never_run"
STATUS_EVALUATED = "evaluated"
SEED = 20261018
_TOKEN = object()


class RunRefused(RuntimeError):
    """The run gate refused; the message says why."""


def lf_sha256(path: Path) -> str:
    """SHA-256 of *path* with CRLF folded to LF, as ``scripts/ots_seal.py`` computes it."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@dataclass(frozen=True)
class LockedManifest:
    """A manifest that passed the gate. Created only by :func:`open_locked_manifest`."""

    path: Path
    body: Mapping[str, Any]
    _token: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise RunRefused("a LockedManifest is created only by open_locked_manifest")


def open_locked_manifest(manifest_path: Path, root: Path,
                         required: Iterable[str]) -> LockedManifest:
    """Check the manifest at *manifest_path* and return it, or raise :class:`RunRefused`.

    *required* lists repository-relative paths the run depends on; each must
    be recorded under ``files``. Every recorded path is hashed relative to
    *root* and compared.
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise RunRefused(f"no manifest at {path}; the study is not sealed")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RunRefused(f"manifest {path} is not valid JSON: {exc}") from exc
    status = body.get("status")
    if status == STATUS_EVALUATED:
        raise RunRefused("status is 'evaluated'; a second run is not blind")
    if status != STATUS_LOCKED:
        raise RunRefused(f"status is {status!r}; only {STATUS_LOCKED!r} may run")
    if body.get("seed") != SEED:
        raise RunRefused(f"seed is {body.get('seed')!r}; the plan fixes {SEED}")
    files = body.get("files")
    if not isinstance(files, dict) or not files:
        raise RunRefused("manifest records no file hashes")
    missing = sorted(set(required) - set(files))
    if missing:
        raise RunRefused(f"files the run depends on are not in the manifest: {missing}")
    changed = []
    for rel, recorded in sorted(files.items()):
        target = Path(root) / rel
        if not target.is_file():
            changed.append(f"{rel} (missing)")
        elif lf_sha256(target) != recorded:
            changed.append(rel)
    if changed:
        raise RunRefused(f"changed after sealing: {changed}")
    return LockedManifest(path=path, body=body, _token=_TOKEN)


def mark_evaluated(locked: LockedManifest, **extra: Any) -> None:
    """Flip the manifest to ``evaluated`` so the gate refuses every later run."""
    body = dict(locked.body)
    body.update(extra)
    body["status"] = STATUS_EVALUATED
    locked.path.write_bytes((json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def require_lock(lock: LockedManifest | None, what: str) -> LockedManifest:
    """Raise unless *lock* is a gate-issued :class:`LockedManifest`."""
    if not isinstance(lock, LockedManifest) or lock._token is not _TOKEN:
        raise RunRefused(f"{what} needs a locked manifest; none was presented")
    return lock
