#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Check, freeze and pin a REMORA interop package (artifacts/interop).

A package is identified by content, never by the Git revision that published
it: ``manifest.json`` lists every package file with its SHA-256 and
``package_digest`` is the SHA-256 over those lines. This script keeps the
manifest, the index, the claim packet and the verifier request in step, and
performs the two producer-side lifecycle moves that must not be typed by hand.

    --check                       recompute every digest; exit 1 on any disagreement
    --freeze CONTRACT REVISION    read the package out of REVISION's tree, check the
                                  bytes against the manifest, write freeze_record and
                                  set the lifecycle to FROZEN (index, manifest, README)
    --confirm-pin CONTRACT VERIFIER WHERE
                                  record that the pin was given to VERIFIER at WHERE and
                                  set the lifecycle to EXTERNAL_RUN_PENDING

Nothing here touches policy, enforcement or execution code, and no step can
advance a contract past EXTERNAL_RUN_PENDING: REPRODUCED and
EXTERNALLY_VERIFIED come only from external run records.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "artifacts" / "interop" / "index.json"
SHA40 = re.compile(r"\b[0-9a-f]{40}\b")


class PackageError(Exception):
    """A disagreement that must stop the operation."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_digest(package_files: list[dict[str, str]]) -> str:
    """SHA-256 over '<path> <sha256>\\n' lines sorted by path."""
    lines = "".join(f"{e['path']} {e['sha256']}\n" for e in sorted(package_files, key=lambda e: e["path"]))
    return "sha256:" + _sha256_bytes(lines.encode("utf-8"))


def _contract(index: dict[str, Any], contract_id: str) -> dict[str, Any]:
    for contract in index["contracts"]:
        if contract["id"] == contract_id:
            return contract
    raise PackageError(f"no contract {contract_id!r} in {INDEX.relative_to(ROOT)}")


def check(root: Path = ROOT) -> list[str]:
    """Every disagreement between the package files and their pins."""
    problems: list[str] = []
    index = _load(root / "artifacts" / "interop" / "index.json")
    for contract in index["contracts"]:
        manifest = _load(root / contract["manifest"])
        for entry in manifest["package_files"]:
            path = root / entry["path"]
            if not path.is_file():
                problems.append(f"{contract['id']}: missing package file {entry['path']}")
                continue
            actual = _sha256_bytes(path.read_bytes())
            if actual != entry["sha256"]:
                problems.append(f"{contract['id']}: {entry['path']} is {actual[:12]}, manifest says {entry['sha256'][:12]}")
            text = path.read_text(encoding="utf-8", errors="replace")
            for sha in set(SHA40.findall(text)) - {manifest["source_revision"]}:
                problems.append(f"{contract['id']}: {entry['path']} names revision {sha[:12]}; only source_revision may appear")
        digest = package_digest(manifest["package_files"])
        if manifest.get("package_digest") != digest:
            problems.append(f"{contract['id']}: manifest package_digest is not derived from its package_files")
        if contract.get("package_digest") != digest:
            problems.append(f"{contract['id']}: index package_digest differs from the manifest")
        if manifest.get("lifecycle") != contract["lifecycle"]:
            problems.append(f"{contract['id']}: manifest lifecycle {manifest.get('lifecycle')!r} differs from index {contract['lifecycle']!r}")
        readme = root / Path(contract["manifest"]).parent / "README.md"
        if readme.is_file() and re.search(r"Lifecycle: \*\*`|Status: \*\*", readme.read_text(encoding="utf-8")):
            problems.append(f"{contract['id']}: README carries a state label; the state lives in the index and manifest only")
        packet = _load(root / contract["claim_packet"])
        request = _load(root / contract["verifier_request"])
        pins = {r["path"]: r["sha256"] for r in packet["artifact_refs"]}
        pins.update({v["path"]: v["sha256"] for v in request["inputs"].values()})
        for rel, sha in pins.items():
            actual = _sha256_bytes((root / rel).read_bytes())
            if actual != sha:
                problems.append(f"{contract['id']}: {rel} is pinned as {sha[:12]} but is {actual[:12]}")
        freeze = contract.get("freeze_record")
        if freeze is not None and freeze.get("package_digest") != digest:
            problems.append(f"{contract['id']}: freeze_record names another package_digest; a frozen package must not change")
    return problems


def _git_show(revision: str, rel: str, root: Path) -> bytes:
    result = subprocess.run(["git", "show", f"{revision}:{rel}"], cwd=root, capture_output=True, check=False)
    if result.returncode != 0:
        raise PackageError(f"{rel} is not in revision {revision[:12]}: {result.stderr.decode().strip()}")
    return result.stdout


def revision_carries_package(contract_id: str, revision: str, root: Path = ROOT) -> str:
    """The full sha of ``revision`` if its tree holds exactly the manifest's bytes."""
    resolved = subprocess.run(["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], cwd=root,
                              capture_output=True, text=True, check=False)
    if resolved.returncode != 0:
        raise PackageError(f"{revision!r} is not a commit: {resolved.stderr.strip()}")
    full = resolved.stdout.strip()
    index = _load(root / "artifacts" / "interop" / "index.json")
    contract = _contract(index, contract_id)
    manifest = _load(root / contract["manifest"])
    for entry in manifest["package_files"]:
        actual = _sha256_bytes(_git_show(full, entry["path"], root))
        if actual != entry["sha256"]:
            raise PackageError(f"{entry['path']} at {full[:12]} is {actual[:12]}, manifest says {entry['sha256'][:12]}")
    manifest_at = _sha256_bytes(_git_show(full, contract["manifest"], root))
    if manifest_at != _sha256_bytes((root / contract["manifest"]).read_bytes()):
        raise PackageError(f"the manifest at {full[:12]} differs from the working tree; freeze the committed state")
    return full


def freeze(contract_id: str, revision: str, root: Path = ROOT) -> dict[str, Any]:
    problems = check(root)
    if problems:
        raise PackageError("refusing to freeze an inconsistent package:\n  " + "\n  ".join(problems))
    index_path = root / "artifacts" / "interop" / "index.json"
    index = _load(index_path)
    contract = _contract(index, contract_id)
    if contract["lifecycle"] != "DRAFT":
        raise PackageError(f"{contract_id} is {contract['lifecycle']}, not DRAFT")
    full = revision_carries_package(contract_id, revision, root)
    record = {
        "revision": full,
        "package_digest": contract["package_digest"],
        "recorded_at": dt.date.today().isoformat(),
        "note": "The commit that records this freeze is later than the revision it names; the package never pins itself.",
    }
    contract["freeze_record"] = record
    # The manifest is outside the package digest, so its label may change;
    # the package files carry no label and keep their bytes.
    _set_lifecycle(contract, "FROZEN", root)
    _dump(index_path, index)
    return record


def _set_lifecycle(contract: dict[str, Any], state: str, root: Path) -> None:
    manifest_path = root / contract["manifest"]
    manifest = _load(manifest_path)
    manifest["lifecycle"] = state
    _dump(manifest_path, manifest)
    contract["lifecycle"] = state


def confirm_pin(contract_id: str, verifier: str, where: str, root: Path = ROOT) -> None:
    index_path = root / "artifacts" / "interop" / "index.json"
    index = _load(index_path)
    contract = _contract(index, contract_id)
    if contract["lifecycle"] not in ("FROZEN", "EXTERNAL_RUN_PENDING"):
        raise PackageError(f"{contract_id} is {contract['lifecycle']}; a pin is given only to a frozen package")
    contract["pin_confirmed_to"].append({"verifier": verifier, "where": where, "confirmed_at": dt.date.today().isoformat()})
    _set_lifecycle(contract, "EXTERNAL_RUN_PENDING", root)
    _dump(index_path, index)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--freeze", nargs=2, metavar=("CONTRACT", "REVISION"))
    mode.add_argument("--confirm-pin", nargs=3, metavar=("CONTRACT", "VERIFIER", "WHERE"))
    args = parser.parse_args(argv)
    try:
        if args.check:
            problems = check()
            for problem in problems:
                print(f"[FAIL] {problem}")
            if problems:
                return 1
            print("[PASS] interop package: every digest, pin and lifecycle label agrees.")
            return 0
        if args.freeze:
            record = freeze(*args.freeze)
            print(f"[PASS] {args.freeze[0]} frozen at {record['revision']} with {record['package_digest']}")
            return 0
        confirm_pin(*args.confirm_pin)
        print(f"[PASS] {args.confirm_pin[0]} pin confirmed to {args.confirm_pin[1]}; lifecycle EXTERNAL_RUN_PENDING")
        return 0
    except PackageError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
