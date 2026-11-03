# SPDX-License-Identifier: BUSL-1.1
"""Sealed-manifest lifecycle for ``--test`` (SAP v7 §10, gate G2).

``locked_never_run`` -> ``in_progress`` (first start, run id recorded) ->
``evaluated`` (after the one run). ``--test`` refuses unless the status is
``locked_never_run``, or ``in_progress`` with ``--resume`` and the same run
id: a crashed run continues from its response cache and ledger, it is not
redrawn. ``evaluated`` refuses every later start. Every file the manifest
lists must still have its recorded LF SHA-256.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiments.sap_v7_addenda.seal import lf_sha256

SEED = 20261017
LOCKED = "locked_never_run"
IN_PROGRESS = "in_progress"
EVALUATED = "evaluated"


class SealRefused(RuntimeError):
    pass


def read_manifest(path: Path) -> dict[str, Any]:
    if not Path(path).is_file():
        raise SealRefused(f"no sealed manifest at {path}")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SealRefused(f"manifest {path} is not JSON: {exc}") from exc


def changed_files(body: Mapping[str, Any], root: Path) -> list[str]:
    files = body.get("files")
    if not isinstance(files, Mapping) or not files:
        return ["<manifest records no file hashes>"]
    out = []
    for rel, digest in sorted(files.items()):
        target = Path(root) / rel
        if not target.is_file():
            out.append(f"{rel} (missing)")
        elif lf_sha256(target) != digest:
            out.append(rel)
    return out


def _write(path: Path, body: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def start_test_run(path: Path, root: Path, required: Iterable[str], run_id: str,
                   resume: bool = False) -> dict[str, Any]:
    body = read_manifest(path)
    status = body.get("status")
    if status == EVALUATED:
        raise SealRefused("manifest status is 'evaluated'; the test split runs once")
    if status == IN_PROGRESS:
        if not resume or body.get("run_id") != run_id:
            raise SealRefused(f"a test run ({body.get('run_id')!r}) is in progress; only "
                              "--resume with the same run id may continue it")
    elif status != LOCKED:
        raise SealRefused(f"manifest status is {status!r}; only {LOCKED!r} may start")
    if body.get("seed") != SEED:
        raise SealRefused(f"manifest seed is {body.get('seed')!r}; the plan fixes {SEED}")
    missing = sorted(set(required) - set(body.get("files") or {}))
    if missing:
        raise SealRefused(f"files the run depends on are not in the manifest: {missing}")
    changed = changed_files(body, root)
    if changed:
        raise SealRefused(f"changed after sealing: {changed}")
    if status == LOCKED:
        body = {**body, "status": IN_PROGRESS, "run_id": run_id,
                "started_utc": datetime.now(UTC).isoformat(timespec="seconds")}
        _write(path, body)
    return body


def finish_test_run(path: Path, run_id: str, **extra: Any) -> None:
    body = read_manifest(path)
    if body.get("status") != IN_PROGRESS or body.get("run_id") != run_id:
        raise SealRefused("only the in-progress run may mark the manifest evaluated")
    body.update(extra)
    body["status"] = EVALUATED
    body["finished_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    _write(path, body)
