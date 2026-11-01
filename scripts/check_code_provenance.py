#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Register every Git-tracked file; refuse missing or stale content in CI.

The live register binds paths, exact bytes, Git blob ids, modes and explicit
concept links. It has no extension/directory allowlist. Its sole exclusion is
itself, to avoid a self-hash. Stage new/deleted paths before running --write.
Snapshots read only the named Git tree, including that tree's concept records.
Neither a Git blob nor a concept link establishes authorship or originality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = "provenance/code-register-v1.json"


class ProvenanceError(Exception):
    """The inventory cannot make a complete statement about the selected tree."""


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, input=data, capture_output=True)
    if result.returncode:
        raise ProvenanceError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def _entries(root: Path, snapshot: str | None) -> dict[str, tuple[str, str]]:
    args = ("ls-tree", "-rz", "--full-tree", snapshot) if snapshot else ("ls-files", "--stage", "-z")
    entries = {}
    for line in _git(root, *args).split(b"\0"):
        if not line:
            continue
        metadata, path_bytes = line.split(b"\t", 1)
        path = path_bytes.decode("utf-8")
        fields = metadata.decode("ascii").split()
        mode, blob = (fields[0], fields[2]) if snapshot else (fields[0], fields[1])
        if not snapshot and fields[2] != "0":
            raise ProvenanceError(f"unmerged index entry: {path!r}")
        if mode not in {"100644", "100755", "120000"}:
            raise ProvenanceError(f"unsupported Git mode {mode}: {path!r}; submodule contents are not covered")
        if path != REGISTER:
            entries[path] = mode, blob
    return entries


def _snapshot_bytes(root: Path, entries: dict[str, tuple[str, str]]) -> dict[str, bytes]:
    blobs = sorted({blob for _, blob in entries.values()})
    data = _git(root, "cat-file", "--batch", data="".join(f"{blob}\n" for blob in blobs).encode())
    offset = 0
    contents = {}
    for blob in blobs:
        end = data.index(b"\n", offset)
        oid, kind, size_text = data[offset:end].split()
        if oid.decode() != blob or kind != b"blob":
            raise ProvenanceError(f"not a blob: {blob}")
        size = int(size_text)
        offset = end + 1
        contents[blob] = data[offset:offset + size]
        offset += size + 1
    return {path: contents[blob] for path, (_, blob) in entries.items()}


def _working_bytes(root: Path, entries: dict[str, tuple[str, str]]) -> dict[str, bytes]:
    contents = {}
    for path, (mode, _) in entries.items():
        source = root / path
        actual = source.lstat().st_mode
        if mode == "120000" and stat.S_ISLNK(actual):
            contents[path] = os.fsencode(os.readlink(source))
        elif mode != "120000" and stat.S_ISREG(actual):
            contents[path] = source.read_bytes()
        else:
            raise ProvenanceError(f"worktree type differs from index: {path!r}; stage the change first")
    return contents


def _concept_links(contents: dict[str, bytes]) -> dict[str, list[str]]:
    links: dict[str, set[str]] = {}
    for path, data in contents.items():
        if not path.startswith("provenance/concepts/") or not path.endswith(".yaml"):
            continue
        record = yaml.safe_load(data)
        cid = record["concept_id"]
        if Path(path).stem != cid:
            raise ProvenanceError(f"concept id differs from filename: {path}")
        for section in ("canonical_spec", "implementation", "tests"):
            for entry in record[section]:
                target = entry["path"]
                if target not in contents:
                    raise ProvenanceError(f"{path}: {section} path {target!r} is missing from current coverage")
                links.setdefault(target, set()).add(cid)
    return {path: sorted(ids) for path, ids in links.items()}


def build(root: Path, snapshot: str | None = None) -> dict[str, Any]:
    if snapshot:
        snapshot = _git(root, "rev-parse", "--verify", "--end-of-options", f"{snapshot}^{{commit}}").decode().strip()
    entries = _entries(root, snapshot)
    contents = _snapshot_bytes(root, entries) if snapshot else _working_bytes(root, entries)
    links = _concept_links(contents)
    algorithm = _git(root, "rev-parse", "--show-object-format").decode().strip()
    files = {}
    for path, data in sorted(contents.items()):
        # Git's raw blob id, with no clean filters or newline normalisation.
        oid = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        files[path] = {
            "mode": entries[path][0], "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": oid, "concepts": links.get(path, []),
        }
    body = {
        "schema_version": "remora-code-provenance-v1",
        "scope": "all Git-tracked files except the live register itself",
        "excluded_self": REGISTER,
        "snapshot": snapshot,
        "git_object_format": algorithm,
        "files": files,
    }
    body["register_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return body


def render(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _check(committed: dict[str, Any], rebuilt: dict[str, Any]) -> int:
    if committed == rebuilt:
        print(f"[PASS] code provenance: {len(rebuilt['files'])} tracked files, register_sha256 {rebuilt['register_sha256']}")
        return 0
    old, new = committed.get("files", {}), rebuilt["files"]
    for label, paths in (
        ("unregistered", new.keys() - old.keys()), ("removed", old.keys() - new.keys()),
        ("changed", {p for p in old.keys() & new.keys() if old[p] != new[p]}),
    ):
        if paths:
            print(f"[FAIL] {label}: " + ", ".join(repr(p) for p in sorted(paths)[:20]))
    print("[FAIL] code provenance is stale; stage paths, run python scripts/check_code_provenance.py --write, and commit the register")
    return 1


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-snapshot", type=Path)
    parser.add_argument("--snapshot", help="freeze a Git commit, instead of reading the working tree")
    parser.add_argument("--out", type=Path, help="required with --snapshot; never replace the live register with a frozen one")
    args = parser.parse_args(argv)
    if (args.snapshot or args.out) and not (args.write and args.snapshot and args.out):
        parser.error("--snapshot and --out must be used together with --write")
    target = args.check_snapshot or args.out or root / REGISTER
    if not target.is_absolute():
        target = root / target
    if args.snapshot and target.resolve() == (root / REGISTER).resolve():
        parser.error("a frozen snapshot cannot replace the live register")
    try:
        if args.check_snapshot:
            committed = json.loads(target.read_text(encoding="utf-8"))
            if not committed.get("snapshot"):
                raise ProvenanceError("snapshot record has no pinned commit")
            return _check(committed, build(root, snapshot=committed["snapshot"]))
        rebuilt = build(root, snapshot=args.snapshot)
        if args.check:
            return _check(json.loads(target.read_text(encoding="utf-8")), rebuilt)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(rebuilt), encoding="utf-8", newline="\n")
        print(f"[WRITE] {target}: {len(rebuilt['files'])} files, register_sha256 {rebuilt['register_sha256']}")
        return 0
    except (ProvenanceError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"[FAIL] code provenance: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
