#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Validate the provenance ledger and build its snapshot manifest.

The ledger under ``provenance/`` joins each concept (``PROV-xx``) to the
documents, code and tests that express it, to its first recorded commit, to
the conformance suites and interop contracts that test it, and to what
external sources document about it. This script is the gate between those
hand-maintained records and the registers they point at:

* every concept record validates against its schema, carries the id of its
  file name, and matches the first-introduction data in
  ``docs/assurance/provenance_register_v1.json``;
* every path, capability, claim, conformance suite, interop contract, prior-art
  source and external event a record names exists;
* a classification other than ``UNKNOWN`` is refused unless a dated review in
  ``provenance/PRIOR_ART.yaml`` names the concept (POLICY.yaml);
* the manifest digests every expressing file and every register from the tree
  of one recorded snapshot commit, so it reproduces byte for byte until a new
  snapshot is written, and ``--check`` refuses a manifest that no longer does.

    --write [--snapshot REV]   validate, then write the manifest at REV (default HEAD)
    --check                    validate, then rebuild from the recorded snapshot and compare
    --release TAG --out PATH   validate, then write a release manifest for TAG at HEAD

Nothing here establishes that a concept is original. The ledger records
priority and content; legal/PROVENANCE.md says what that does and does not show.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "provenance"
POLICY = LEDGER / "POLICY.yaml"


class LedgerError(Exception):
    """A disagreement that must stop the build."""


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise LedgerError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


def _blob(snapshot: str, rel: str) -> tuple[str, str]:
    """(git blob sha, sha256 of content) for ``rel`` in ``snapshot``'s tree."""
    blob = _git("rev-parse", f"{snapshot}:{rel}")
    data = subprocess.run(["git", "cat-file", "blob", blob], cwd=ROOT, capture_output=True, check=True).stdout
    return blob, hashlib.sha256(data).hexdigest()


def _tree_has(snapshot: str, rel: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{snapshot}:{rel}"], cwd=ROOT, capture_output=True, check=False).returncode == 0


def _validator(name: str) -> jsonschema.Draft202012Validator:
    schema = _json(LEDGER / "schemas" / f"{name}.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _errors(validator: jsonschema.Draft202012Validator, instance: Any, label: str) -> list[str]:
    return [f"{label}: {e.message} at {'/'.join(map(str, e.path)) or '<root>'}"
            for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.path))]


def validate(snapshot: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Every problem in the ledger, and the records keyed by id."""
    problems: list[str] = []
    policy = _yaml(POLICY)
    prior = _yaml(LEDGER / "PRIOR_ART.yaml")
    adoption = _yaml(LEDGER / "EXTERNAL_ADOPTION.yaml")
    problems += _errors(_validator("prior-art-v1"), prior, "PRIOR_ART.yaml")
    problems += _errors(_validator("external-adoption-v1"), adoption, "EXTERNAL_ADOPTION.yaml")
    sources = {s["id"] for s in prior["sources"]}
    reviews = prior["reviews"]
    reviewed_concepts = {c for r in reviews for c in r["concepts"]}
    review_ids = {r["id"] for r in reviews}
    events = {e["id"]: e for e in adoption["events"]}
    register = _json(ROOT / "docs/assurance/provenance_register_v1.json")
    first = {c["id"]: c["first"][0] for c in register["concepts"]}
    concept_ids = {c["id"] for c in _yaml(ROOT / "docs/assurance/provenance_concepts_v1.yaml")["concepts"]}
    caps = {c["id"] for c in _yaml(ROOT / "docs/assurance/capability_register_v1.yaml")["capabilities"]}
    claims = {c["id"] for c in _yaml(ROOT / "docs/assurance/claim_register_v1.yaml")["claims"]}
    contracts = {c["id"] for c in _json(ROOT / "artifacts/interop/index.json")["contracts"]}
    federation = _yaml(ROOT / "artifacts/interop/FEDERATION.yaml")
    produces = set(federation["produces"])
    validator = _validator("concept-record-v1")
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((LEDGER / "concepts").glob("*.yaml")):
        record = _yaml(path)
        label = path.relative_to(ROOT).as_posix()
        errs = _errors(validator, record, label)
        problems += errs
        if errs:
            continue
        cid = record["concept_id"]
        if path.stem != cid:
            problems.append(f"{label}: concept_id {cid} differs from the file name")
        if cid in records:
            problems.append(f"{label}: duplicate concept_id {cid}")
        records[cid] = record
        if cid not in concept_ids:
            problems.append(f"{label}: {cid} is not in docs/assurance/provenance_concepts_v1.yaml")
        elif cid in first:
            fr = record["first_recorded"]
            for key in ("commit", "authored", "committed", "signature"):
                if fr[key] != first[cid][key]:
                    problems.append(f"{label}: first_recorded.{key} differs from provenance_register_v1.json ({fr[key]!r} vs {first[cid][key]!r})")
        for section in ("canonical_spec", "implementation", "tests"):
            for entry in record[section]:
                if not _tree_has(snapshot, entry["path"]):
                    problems.append(f"{label}: {section} path {entry['path']} is not in the tree of {snapshot[:12]}")
        for suite in record["conformance"]:
            if not (ROOT / "conformance" / suite).is_dir():
                problems.append(f"{label}: conformance suite {suite} does not exist")
        for contract in record["interop_contracts"]:
            if contract not in contracts:
                problems.append(f"{label}: interop contract {contract} is not in artifacts/interop/index.json")
        for cap in record["related_capabilities"]:
            if cap not in caps:
                problems.append(f"{label}: capability {cap} is not in the capability register")
        for claim in record["related_claims"]:
            if claim not in claims:
                problems.append(f"{label}: claim {claim} is not in the claim register")
        if record["federation_produces"] is not None and record["federation_produces"] not in produces:
            problems.append(f"{label}: federation_produces {record['federation_produces']!r} is not declared in FEDERATION.yaml")
        for src in record["prior_art"]["review_sources"]:
            if src not in sources:
                problems.append(f"{label}: prior-art source {src} is not in PRIOR_ART.yaml")
        for rev in record["prior_art"]["records"]:
            if rev not in review_ids:
                problems.append(f"{label}: prior-art review {rev} is not in PRIOR_ART.yaml")
        if policy.get("classification_requires_review") and record["classification"] != "UNKNOWN" and cid not in reviewed_concepts:
            problems.append(f"{label}: classification {record['classification']} without a review naming {cid} in PRIOR_ART.yaml")
        if record["classification"] not in policy["classification"] or record["origin"]["status"] not in policy["origin_status"]:
            problems.append(f"{label}: vocabulary outside POLICY.yaml")
        for ext in record["external_adoption"]:
            if ext not in events:
                problems.append(f"{label}: external event {ext} is not in EXTERNAL_ADOPTION.yaml")
            elif cid not in events[ext]["concepts"]:
                problems.append(f"{label}: external event {ext} does not name {cid}")
        for step in record["evolution"]:
            if not _git_commit_exists(step["commit"]):
                message = f"{label}: evolution commit {step['commit'][:12]} is not in this clone's history"
                if _is_shallow():
                    print(f"[WARN] {message} (shallow clone; CI checks with full history)")
                else:
                    problems.append(message + " (fetch more history, or the sha is wrong)")
    missing = concept_ids - set(records)
    if missing:
        problems.append(f"concepts without a record: {sorted(missing)}")
    for event in adoption["events"]:
        for cid in event["concepts"]:
            if cid in records and event["id"] not in records[cid]["external_adoption"]:
                problems.append(f"EXTERNAL_ADOPTION.yaml: {event['id']} names {cid} but the record does not list it")
        if not (ROOT / event["recorded_in"]).exists():
            problems.append(f"EXTERNAL_ADOPTION.yaml: {event['id']} recorded_in {event['recorded_in']} does not exist")
    for rel in policy["manifest"]["registers"]:
        if not _tree_has(snapshot, rel):
            problems.append(f"POLICY.yaml: register {rel} is not in the tree of {snapshot[:12]}")
    return problems, records


def _is_shallow() -> bool:
    return _git("rev-parse", "--is-shallow-repository") == "true"


def _git_commit_exists(sha: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT, capture_output=True, check=False).returncode == 0


def build(snapshot: str, records: dict[str, dict[str, Any]], *, release: str | None = None) -> dict[str, Any]:
    policy = _yaml(POLICY)
    concepts: dict[str, Any] = {}
    for cid, record in sorted(records.items()):
        entry: dict[str, Any] = {}
        lines: list[str] = []
        for section in ("canonical_spec", "implementation", "tests"):
            files = []
            for e in record[section]:
                blob, sha = _blob(snapshot, e["path"])
                files.append({"path": e["path"], "blob": blob, "sha256": sha})
                lines.append(f"{section} {e['path']} {sha}\n")
            entry[section] = files
        entry["first_recorded_commit"] = record["first_recorded"]["commit"]
        entry["classification"] = record["classification"]
        entry["aggregate_sha256"] = hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()
        concepts[cid] = entry
    registers = {}
    for rel in policy["manifest"]["registers"]:
        blob, sha = _blob(snapshot, rel)
        registers[rel] = {"blob": blob, "sha256": sha}
    record_digests = {}
    for path in sorted((LEDGER / "concepts").glob("*.yaml")):
        rel = path.relative_to(ROOT).as_posix()
        blob, sha = _blob(snapshot, rel)
        record_digests[rel] = {"blob": blob, "sha256": sha}
    body = {
        "schema_version": "remora-provenance-manifest-v1",
        "snapshot": snapshot,
        "snapshot_committed": _git("show", "-s", "--format=%cI", snapshot),
        "release": release,
        "rule": policy["manifest"]["rule"],
        "concepts": concepts,
        "concept_records": record_digests,
        "registers": registers,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["ledger_sha256"] = hashlib.sha256(canonical).hexdigest()
    return body


def _differences(a: Any, b: Any, path: str = "", limit: int = 20) -> list[str]:
    """The first ``limit`` leaf paths where two manifests disagree."""
    out: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if len(out) >= limit:
                break
            out += _differences(a.get(key, "<absent>"), b.get(key, "<absent>"), f"{path}/{key}", limit - len(out))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            if len(out) >= limit:
                break
            out += _differences(x, y, f"{path}[{i}]", limit - len(out))
    elif a != b:
        out.append(f"{path}: committed={str(a)[:80]!r} rebuilt={str(b)[:80]!r}")
    return out


def _stable(manifest: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in manifest.items() if k not in ("generated_at",)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--release", metavar="TAG")
    parser.add_argument("--snapshot", default=None, help="revision to digest (default HEAD for --write and --release)")
    parser.add_argument("--out", default=None, help="output path for --release")
    args = parser.parse_args(argv)
    out_path = ROOT / _yaml(POLICY)["manifest"]["path"]
    try:
        if args.check:
            if not out_path.is_file():
                raise LedgerError(f"{out_path.relative_to(ROOT)} is missing; run --write")
            committed = _json(out_path)
            snapshot = committed["snapshot"]
        else:
            snapshot = _git("rev-parse", "--verify", f"{args.snapshot or 'HEAD'}^{{commit}}")
        problems, records = validate(snapshot)
        for problem in problems:
            print(f"[FAIL] {problem}")
        if problems:
            return 1
        if args.check:
            rebuilt = build(snapshot, records, release=committed.get("release"))
            if _stable(rebuilt) != _stable(committed):
                for line in _differences(_stable(committed), _stable(rebuilt)):
                    print(f"[DIFF] {line}")
                print(f"[FAIL] {out_path.relative_to(ROOT)} does not reproduce from snapshot {snapshot[:12]}; run --write to record a new snapshot")
                return 1
            print(f"[PASS] provenance ledger: {len(records)} records valid; manifest reproduces from snapshot {snapshot[:12]} (ledger_sha256 {committed['ledger_sha256'][:16]})")
            return 0
        manifest = build(snapshot, records, release=args.release)
        manifest["generated_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        target = Path(args.out) if args.out else out_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"[WRITE] {target}: snapshot {snapshot[:12]}, {len(records)} concepts, ledger_sha256 {manifest['ledger_sha256']}")
        return 0
    except LedgerError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
