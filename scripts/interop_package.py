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

``--check`` also enforces the Federation publication gate: FEDERATION.yaml
validates against its schema, every claim in every claim packet carries a
claim ceiling and the packet names explicit non-claims (FED-INV-002), and
every run record under artifacts/interop/runs/ validates against
interop-result-v1, names a known contract and claim, and pins the exact
fixture bytes and package digest it evaluated (FED-INV-003). A record that
fails any of these is refused, so a result without its ceiling or provenance
cannot be published. Every ``bcr-linkage-v1`` record under
artifacts/interop/linkages/ is validated the same way: it must resolve its
source record by path and digest and repeat that record's level, claim and
status verbatim, so a Bounded Claim Reproduction level can never exceed what
the run record itself established.

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

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.interop.package_identity import package_digest  # noqa: E402

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
        problems.extend(_claim_ceiling_problems(contract["id"], packet))
    problems.extend(_federation_problems(index, root))
    problems.extend(_linkage_problems(index, root))
    return problems


def _validator(root: Path, rel: str) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(_load(root / rel))


def _claim_ceiling_problems(contract_id: str, packet: dict[str, Any]) -> list[str]:
    """FED-INV-002: a claim without a ceiling, or a packet without non-claims,
    cannot be published."""
    problems: list[str] = []
    if not packet.get("claims"):
        problems.append(f"{contract_id}: claim packet names no claims")
    for claim in packet.get("claims", []):
        if not str(claim.get("claim_ceiling", "")).strip():
            problems.append(f"{contract_id}: claim {claim.get('claim_id')!r} has no claim_ceiling")
    if not packet.get("explicit_non_claims"):
        problems.append(f"{contract_id}: claim packet has no explicit_non_claims")
    return problems


def _federation_problems(index: dict[str, Any], root: Path) -> list[str]:
    """The manifest, the edges it declares and every run record."""
    problems: list[str] = []
    manifest_rel = index.get("federation_manifest")
    if not manifest_rel:
        return ["index.json names no federation_manifest"]
    manifest = yaml.safe_load((root / manifest_rel).read_text(encoding="utf-8"))
    schema_rel = index["schemas"].get("federation_manifest")
    errors = sorted(_validator(root, schema_rel).iter_errors(manifest), key=lambda e: list(e.path))
    problems.extend(f"{manifest_rel}: {e.message} at {'/'.join(map(str, e.path)) or '<root>'}" for e in errors)
    contracts = {c["id"]: c for c in index["contracts"]}
    for edge in manifest.get("edges", []):
        contract_id = edge.get("contract")
        if contract_id and contract_id not in contracts:
            problems.append(f"{manifest_rel}: edge {edge.get('id')} names unknown contract {contract_id!r}")
        record = edge.get("record")
        if record and not (root / record).is_file():
            problems.append(f"{manifest_rel}: edge {edge.get('id')} names missing record {record}")
    runs = index.get("runs", {})
    run_dir = root / runs.get("directory", "artifacts/interop/runs")
    if not run_dir.is_dir():
        return problems
    validator = _validator(root, index["schemas"]["interop_result"])
    for path in sorted(run_dir.glob("*.json")):
        rel = path.relative_to(root).as_posix()
        record = _load(path)
        errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
        if errors:
            problems.extend(f"{rel}: {e.message} at {'/'.join(map(str, e.path)) or '<root>'}" for e in errors)
            continue
        contract = contracts.get(record["contract_id"])
        if contract is None:
            problems.append(f"{rel}: unknown contract {record['contract_id']!r}")
            continue
        claim_ids = {c["claim_id"] for c in _load(root / contract["claim_packet"])["claims"]}
        if record["claim"] not in claim_ids:
            problems.append(f"{rel}: claim {record['claim']!r} is not in the contract's claim packet")
        if record["edge"] != contract["edge"]:
            problems.append(f"{rel}: edge {record['edge']!r} differs from the contract's {contract['edge']!r}")
        fixture = record["fixture"]
        if fixture["path"] != contract.get("fixtures"):
            problems.append(f"{rel}: fixture path {fixture['path']} is not the contract's fixtures file")
        elif "sha256:" + _sha256_bytes((root / fixture["path"]).read_bytes()) != fixture["digest"]:
            problems.append(f"{rel}: fixture digest does not match the committed bytes; a result over other bytes does not count")
        if fixture["package_digest"] != contract["package_digest"]:
            problems.append(f"{rel}: package_digest differs from the contract's; a result over other bytes does not count")
        for case in record["cases"]:
            if case["claim_id"] != record["claim"]:
                problems.append(f"{rel}: case {case['case_id']} belongs to claim {case['claim_id']!r}, record is {record['claim']!r}")
    return problems


#: The REMORA level a NOT_INDEPENDENT external run record can at most be linked at.
_DIVERSITY_LEVEL = {"REPRODUCTION": "L1_REPRODUCTION", "SECOND_IMPLEMENTATION": "L2_SECOND_IMPLEMENTATION"}


def _linkage_problems(index: dict[str, Any], root: Path) -> list[str]:
    """Every bcr-linkage-v1 record, checked against the run record it links."""
    problems: list[str] = []
    linkages = index.get("linkages")
    schema_rel = index["schemas"].get("bcr_linkage")
    if not linkages or not schema_rel:
        return ["index.json names no linkages directory or bcr_linkage schema"]
    link_dir = root / linkages["directory"]
    if not link_dir.is_dir():
        return problems
    validator = _validator(root, schema_rel)
    contracts = {c["id"]: c for c in index["contracts"]}
    seen: set[str] = set()
    for path in sorted(link_dir.glob("*.json")):
        rel = path.relative_to(root).as_posix()
        record = _load(path)
        errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
        if errors:
            problems.extend(f"{rel}: {e.message} at {'/'.join(map(str, e.path)) or '<root>'}" for e in errors)
            continue
        if record["linkage_id"] in seen:
            problems.append(f"{rel}: linkage_id {record['linkage_id']!r} is used twice")
        seen.add(record["linkage_id"])
        ids = [c["id"] for c in record["conditions"]]
        if len(ids) != len(set(ids)):
            problems.append(f"{rel}: a condition id appears twice; one unmet copy must not hide behind a met one")
        contract = contracts.get(record["contract_id"])
        if contract is None:
            problems.append(f"{rel}: unknown contract {record['contract_id']!r}")
            continue
        if record["package_digest"] != contract["package_digest"]:
            problems.append(f"{rel}: package_digest differs from the contract's; a level over other bytes does not count")
        source = record["source_record"]
        source_path = root / source["path"]
        if not source_path.is_file():
            problems.append(f"{rel}: source record {source['path']} is not committed")
            continue
        if _sha256_bytes(source_path.read_bytes()) != source["sha256"]:
            problems.append(f"{rel}: source record digest does not match the committed bytes")
            continue
        run = _load(source_path)
        if run.get("schema_version") != source["schema_version"]:
            problems.append(f"{rel}: source record is {run.get('schema_version')!r}, linkage says {source['schema_version']!r}")
            continue
        if run.get("contract_id") != record["contract_id"]:
            problems.append(f"{rel}: source record belongs to contract {run.get('contract_id')!r}")
        if source["schema_version"] == "remora-interop-result-v1":
            if run["claim"] != source["claim"]:
                problems.append(f"{rel}: source record is for claim {run['claim']!r}, linkage says {source['claim']!r}")
            if run["independence_level"] != record["remora_independence_level"]:
                problems.append(f"{rel}: level {record['remora_independence_level']} differs from the record's {run['independence_level']}; a linkage never changes a level")
            if run["status"] != record["source_status"]:
                problems.append(f"{rel}: source_status {record['source_status']} differs from the record's {run['status']}; a linkage never translates a status")
        else:
            claim_results = {r["result"] for r in run["results"] if r["claim_id"] == source["claim"]}
            if not claim_results:
                problems.append(f"{rel}: source record has no result for claim {source['claim']!r}")
            elif len(claim_results) > 1:
                problems.append(f"{rel}: source record has mixed results for claim {source['claim']!r}; link one case-level status, not a summary")
            elif record["source_status"] not in claim_results:
                problems.append(f"{rel}: source_status {record['source_status']} is not the record's result for {source['claim']!r}")
            level = record["remora_independence_level"]
            if run["independence"] == "INDEPENDENT":
                if level not in {"L3_INDEPENDENT_RECOMPUTATION", "L4_INDEPENDENT_HOST_RUN"}:
                    problems.append(f"{rel}: an INDEPENDENT run record maps to L3 or L4, not {level}")
            else:
                ceiling = _DIVERSITY_LEVEL.get(run["implementation_diversity"], "L0_SELF_TEST")
                if _LEVELS.index(level) > _LEVELS.index(ceiling):
                    problems.append(f"{rel}: a NOT_INDEPENDENT {run['implementation_diversity']} record is at most {ceiling}, not {level}")
    return problems


_LEVELS = ["L0_SELF_TEST", "L1_REPRODUCTION", "L2_SECOND_IMPLEMENTATION", "L3_INDEPENDENT_RECOMPUTATION", "L4_INDEPENDENT_HOST_RUN"]


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
            print("[PASS] interop package: every digest, pin, lifecycle label, claim ceiling, run record and linkage agrees.")
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
