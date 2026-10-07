#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Validate submitted bytes against base-owned trust; never rerun or admit claims."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.interop.evidence_io import EvidenceError, decode_json
from scripts import interop_operator_statement as statement
from scripts import interop_self_service as runtime

REGISTRY = "artifacts/interop/operators-v1.json"
REGISTRY_SCHEMA = ROOT / "schemas/interop-operator-registry-v1.schema.json"
SUBMISSION_SCHEMA = ROOT / "schemas/interop-submission-v1.schema.json"
PREFIX = "artifacts/interop/submissions/"


def _revision(repo: Path, revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise EvidenceError("admission requires full lowercase commit IDs")
    runtime._git(repo, "cat-file", "-e", f"{revision}^{{commit}}")


def _blob(repo: Path, revision: str, path: str, limit: int = 8_000_000) -> bytes:
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != path or "\\" in path:
        raise EvidenceError(f"unsafe submission path: {path}")
    entry = runtime._git(repo, "ls-tree", "-z", revision, "--", path)
    metadata, separator, name = entry.partition(b"\t")
    if (not separator or name != path.encode() + b"\0"
            or metadata.split()[:2] != [b"100644", b"blob"]):
        raise EvidenceError(f"submission input is not one regular Git blob: {path}")
    size = int(runtime._git(repo, "cat-file", "-s", metadata.split()[2].decode()).decode())
    if size > limit:
        raise EvidenceError(f"submission input exceeds size limit: {path}")
    return runtime._git(repo, "show", f"{revision}:{path}")


def registry(repo: Path, revision: str) -> dict[str, Any]:
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    data = decode_json(_blob(repo, revision, REGISTRY, 1_000_000).decode())
    statement._validate(data, REGISTRY_SCHEMA)
    pairs: set[tuple[str, str]] = set()
    key_ids: set[str] = set()
    for operator in data["operators"]:
        try:
            public = load_pem_public_key(operator["public_key_pem"].encode())
        except UnsupportedAlgorithm as exc:
            raise EvidenceError("operator registry key algorithm is unsupported") from exc
        if not isinstance(public, Ed25519PublicKey):
            raise EvidenceError("operator registry accepts only Ed25519 public keys")
        key_id, _ = statement._public_identity(public)
        pair = (operator["operator_identity"], operator["key_id"])
        if key_id != operator["key_id"] or pair in pairs or key_id in key_ids:
            raise EvidenceError("operator registry has an incorrect, duplicated or ambiguously attributed key")
        pairs.add(pair)
        key_ids.add(key_id)
    return data


def validate(repo: Path, base: str, head: str, directory: str) -> dict[str, Any]:
    _revision(repo, base)
    _revision(repo, head)
    if not re.fullmatch(r"artifacts/interop/submissions/[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", directory):
        raise EvidenceError("submission must name a single bounded submissions directory")
    trusted = registry(repo, base)
    submission = decode_json(_blob(repo, head, f"{directory}/submission.json", 16_000).decode())
    statement._validate(submission, SUBMISSION_SCHEMA)
    observation_data = _blob(repo, head, f"{directory}/{submission['observation']}")
    statement_data = _blob(repo, head, f"{directory}/{submission['operator_statement']}", 64_000)
    envelope = decode_json(statement_data.decode())
    statement._validate(envelope, statement.SCHEMA)
    matches = [
        entry for entry in trusted["operators"]
        if entry["operator_identity"] == submission["operator_identity"]
        and entry["key_id"] == envelope["statement"]["key_id"]
    ]
    if len(matches) != 1 or matches[0]["revoked"]:
        raise EvidenceError("operator key is absent, ambiguous or revoked in the base revision")
    operator = matches[0]
    with tempfile.TemporaryDirectory(prefix="remora-admission-") as temporary:
        work = Path(temporary)
        observation = work / "observation.json"
        observation.write_bytes(observation_data)
        signed = work / "operator-statement.json"
        signed.write_bytes(statement_data)
        public = work / "trusted-public.pem"
        public.write_text(operator["public_key_pem"])
        statement.verify(observation, signed, public, submission["operator_identity"])
        _, report = statement._observation(observation)
        revision = report["runtime_revision"]
        _revision(repo, revision)
        runtime._git(repo, "merge-base", "--is-ancestor", revision, base)
        source = work / "source"
        source.mkdir()
        archive = runtime._git(repo, "archive", revision, *runtime.INPUTS)
        digests = runtime._extract_archive(archive, source)
        if report["source_files"] != digests:
            raise EvidenceError("observation source/runner digests do not match the consumed committed revision")
        runtime._verify_snapshot(source, digests)
        names = [package["contract_id"] for package in report["contracts"]]
        if len(names) != len(set(names)) or not set(names) <= set(runtime.CONTRACTS):
            raise EvidenceError("submission duplicates or exceeds the bounded primitive contracts")
        packages = runtime._packages(source, names, digests)
        if report["boundary"] != runtime._boundary(source, digests):
            raise EvidenceError("observation boundary does not match its referenced revision")
        if submission["boundary_digest"] != report["boundary"]["register_digest"]:
            raise EvidenceError("submission names a different boundary version")
        for actual, expected in zip(report["contracts"], packages, strict=True):
            if {key: value for key, value in actual.items() if key != "cases"} != {
                key: value for key, value in expected.items() if key != "fixtures"
            }:
                raise EvidenceError("package digest, claim ceiling or non-claims have been altered")
        runtime._validate_observations({
            "runtime_modules": report["runtime_modules"], "environment": report["environment"],
            "cases": {
                package["contract_id"]: [
                    {**{key: value for key, value in case.items() if key != "claim_status"},
                     "result": case["claim_status"]}
                    for case in package["cases"]
                ] for package in report["contracts"]
            },
        }, packages, digests)
    return {
        "validation_status": "VALIDATED_FOR_REVIEW",
        "submission": directory,
        "runtime_revision": revision,
        "operator_identity": operator["operator_identity"],
        "operator_role": operator["relationship_to_producer"],
        "trust_revision": base,
        "independence": "NOT_CLASSIFIED", "admission": "UNADMITTED",
        "confers_authority": False, "runtime_rerun": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT, help="Git object repository, not executable source")
    parser.add_argument("--base", required=True, help="trusted registry revision, supplied by base workflow")
    parser.add_argument("--head", required=True, help="submission commit")
    parser.add_argument("--submission", help="one artifacts/interop/submissions/ID directory")
    args = parser.parse_args(argv)
    try:
        _revision(args.repo, args.base)
        _revision(args.repo, args.head)
        registry(args.repo, args.base)
        # Proposed registry edits are structurally checked, never used as trust.
        registry(args.repo, args.head)
        if args.submission:
            directories = [args.submission]
        else:
            changed = runtime._git(
                args.repo, "diff", "--no-ext-diff", "--no-textconv", "--name-only",
                args.base, args.head, "--", PREFIX,
            ).decode().splitlines()
            directories = sorted({str(PurePosixPath(path).parent) for path in changed})
        results = [validate(args.repo, args.base, args.head, directory) for directory in directories]
    except (EvidenceError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({"validation_status": "REFUSED", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({
        "validation_status": "VALIDATED_FOR_REVIEW" if results else "NO_OBSERVATION_SUBMISSIONS",
        "results": results, "admission": "UNADMITTED", "confers_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
