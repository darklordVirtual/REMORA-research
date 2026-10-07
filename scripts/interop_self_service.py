#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run pinned REMORA boundary fixtures in a fresh, credential-free process."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.interop.evidence_io import (
    EvidenceError as RunnerError,
    canonical_json as _json,
    decode_json as _decode,
    digest_bytes as _digest,
    publish_new,
)

CONTRACTS = ("exact-call-binding-v1", "fresh-authority-v1", "effect-evidence-v1")
SCRIPT = "scripts/interop_self_service.py"
SCHEMA = "schemas/runtime-self-service-v1.schema.json"
BOUNDARY = "docs/interop/remora-boundaries-v1.yaml"
SUMMARY = "artifacts/interop/remora-boundary-summary-v1.json"
INPUTS = ("remora", SCRIPT, SCHEMA, "artifacts/interop", BOUNDARY, "requirements-lock.txt", "pyproject.toml")


def _load(path: Path) -> Any:
    return _decode(path.read_text(encoding="utf-8"))


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(root), *args], capture_output=True, check=False,
    )
    if result.returncode:
        raise RunnerError(f"git {' '.join(args[:2])} failed: {result.stderr.decode().strip()}")
    return result.stdout


def _snapshot(root: Path, revision: str, destination: Path) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RunnerError("revision must be a full lowercase Git commit ID")
    if _git(root, "rev-parse", "HEAD").decode().strip() != revision:
        raise RunnerError("checkout HEAD does not match requested revision")
    if _git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", revision, "--", *INPUTS).strip():
        raise RunnerError("tracked runtime, runner or evidence inputs differ from the requested revision")
    if _git(root, "show", f"{revision}:{SCRIPT}") != (root / SCRIPT).read_bytes():
        raise RunnerError("running script differs from committed runner")
    archive = _git(root, "archive", revision, *INPUTS)
    return _extract_archive(archive, destination)


def _extract_archive(archive: bytes, destination: Path) -> dict[str, str]:
    """Extract data only; also used by admission without executing source code."""
    digests = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for member in tree:
            relative = PurePosixPath(member.name)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in member.name
                    or relative.as_posix() != member.name.rstrip("/")):
                raise RunnerError(f"unsafe archive path: {member.name}")
            path = destination / member.name
            if not path.resolve().is_relative_to(destination.resolve()):
                raise RunnerError(f"archive path escapes snapshot: {member.name}")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile() or member.name in digests:
                raise RunnerError(f"unsupported or duplicate archive entry: {member.name}")
            stream = tree.extractfile(member)
            if stream is None:
                raise RunnerError(f"missing archive bytes: {member.name}")
            data = stream.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            digests[member.name] = _digest(data)
    return digests


def _read_snapshot(snapshot: Path, relative: str, digests: dict[str, str]) -> bytes:
    path = PurePosixPath(relative)
    if (path.is_absolute() or ".." in path.parts or "\\" in relative or relative not in digests
            or path.as_posix() != relative):
        raise RunnerError(f"unsafe or unpinned snapshot path: {relative}")
    target = snapshot
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise RunnerError(f"snapshot symlink refused: {relative}")
    if not target.resolve().is_relative_to(snapshot.resolve()):
        raise RunnerError(f"snapshot path escapes source: {relative}")
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RunnerError(f"snapshot non-regular file or hardlink refused: {relative}")
        data = stream.read()
    if _digest(data) != digests[relative]:
        raise RunnerError(f"snapshot digest mismatch: {relative}")
    return data


def _verify_snapshot(snapshot: Path, digests: Any) -> None:
    if (not isinstance(digests, dict) or SCRIPT not in digests
            or any(not isinstance(path, str) or not isinstance(digest, str)
                   or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                   for path, digest in digests.items())):
        raise RunnerError("malformed snapshot digest manifest")
    for relative in digests:
        _read_snapshot(snapshot, relative, digests)


def _packages(snapshot: Path, contracts: list[str], digests: dict[str, str]) -> list[dict[str, Any]]:
    sys.path.insert(0, str(ROOT))
    from remora.interop.package_identity import package_digest

    index = _decode(_read_snapshot(snapshot, "artifacts/interop/index.json", digests).decode())
    result = []
    for name in contracts:
        entries = [entry for entry in index["contracts"] if entry["id"] == name]
        if len(entries) != 1:
            raise RunnerError(f"{name}: expected one indexed contract")
        contract = entries[0]
        manifest = _decode(_read_snapshot(snapshot, contract["manifest"], digests).decode())
        files = manifest["package_files"]
        if not files or len({item["path"] for item in files}) != len(files):
            raise RunnerError(f"{name}: empty or duplicate package entries")
        package_bytes = {}
        for item in files:
            data = _read_snapshot(snapshot, item["path"], digests)
            if _digest(data) != "sha256:" + item["sha256"]:
                raise RunnerError(f"{name}: package digest mismatch for {item['path']}")
            package_bytes[item["path"]] = data
        if package_digest(files) != manifest["package_digest"]:
            raise RunnerError(f"{name}: package fold mismatch")
        if manifest["package_digest"] != contract["package_digest"]:
            raise RunnerError(f"{name}: index and manifest disagree")
        paths = {item["path"] for item in files}
        if not {contract["fixtures"], contract["claim_packet"]} <= paths:
            raise RunnerError(f"{name}: fixture or claim packet is not package-bound")
        fixture_bytes = package_bytes[contract["fixtures"]]
        fixture = _decode(fixture_bytes.decode())
        packet = _decode(package_bytes[contract["claim_packet"]].decode())
        if (manifest["source_revision"] != contract["source_revision"]
                or packet["source_revision"] != contract["source_revision"]
                or packet["contract_id"] != name
                or fixture["schema_version"] != f"remora-{name[:-3]}-fixtures-v1"):
            raise RunnerError(f"{name}: package identity disagreement")
        if not fixture["cases"] or len({case["id"] for case in fixture["cases"]}) != len(fixture["cases"]):
            raise RunnerError(f"{name}: empty or duplicate fixture cases")
        result.append({
            "contract_id": name,
            "fixture_source_revision": contract["source_revision"],
            "fixture_digest": _digest(fixture_bytes),
            "package_digest": contract["package_digest"],
            "fixtures": fixture,
            "claim_ceilings": packet["claims"],
            "does_not_establish": packet["explicit_non_claims"],
        })
    return result


def _worker(contracts: list[str]) -> int:
    digests = _decode(sys.stdin.read())
    _verify_snapshot(ROOT, digests)
    sys.path.insert(0, str(ROOT))
    from remora.interop.boundary_fixtures import evaluate_package

    packages = _packages(ROOT, contracts, digests)
    cases = {package["contract_id"]: evaluate_package(package["fixtures"]) for package in packages}
    modules = {}
    for name, module in tuple(sys.modules.items()):
        if name == "remora" or name.startswith("remora."):
            filename = getattr(module, "__file__", None)
            if filename is None or not Path(filename).resolve().is_relative_to(ROOT):
                raise RunnerError(f"runtime module is not from pinned snapshot: {name}")
            path = Path(filename).resolve()
            relative = path.relative_to(ROOT).as_posix()
            modules[relative] = _digest(_read_snapshot(ROOT, relative, digests))
    _verify_snapshot(ROOT, digests)
    environment = {
        "python": platform.python_version(), "os": platform.system(),
        "machine": platform.machine(),
        "distributions": sorted(
            {f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()}
        ),
    }
    print(_json({"cases": cases, "runtime_modules": modules, "environment": environment}))
    return 0


def _validate_observations(payload: Any, packages: list[dict[str, Any]], digests: dict[str, str]) -> None:
    if not isinstance(payload, dict) or set(payload) != {"cases", "runtime_modules", "environment"}:
        raise RunnerError("malformed runtime result envelope")
    modules = payload["runtime_modules"]
    if not isinstance(modules, dict) or "remora/interop/boundary_fixtures.py" not in modules:
        raise RunnerError("missing actual runtime evaluator provenance")
    if any(not path.startswith("remora/") or digests.get(path) != digest for path, digest in modules.items()):
        raise RunnerError("runtime module digest does not match pinned snapshot")
    observations = payload["cases"]
    if not isinstance(observations, dict) or set(observations) != {p["contract_id"] for p in packages}:
        raise RunnerError("missing, extra or malformed runtime contract results")
    for package in packages:
        cases = observations[package["contract_id"]]
        fixtures = package["fixtures"]["cases"]
        if not isinstance(cases, list) or len(cases) != len(fixtures):
            raise RunnerError("missing or extra runtime cases")
        for record, fixture in zip(cases, fixtures, strict=True):
            if not isinstance(record, dict) or set(record) != {"case_id", "claim_id", "expected", "observed", "result"}:
                raise RunnerError("malformed runtime case")
            expected = fixture["expected"]
            value = expected.get("outcomes")
            if value is None:
                value = {key: expected[key] for key in ("effect_status", "highest_established_state")}
            if (record["case_id"], record["claim_id"], _json(record["expected"])) != (
                fixture["id"], fixture["claim_id"], _json({"value": value}),
            ):
                raise RunnerError("case identity or expected value does not match pinned fixture")
            if not isinstance(record["observed"], dict) or set(record["observed"]) != {"value"}:
                raise RunnerError("malformed observed value")
            observed = record["observed"]["value"]
            if isinstance(value, list):
                if not isinstance(observed, list) or len(observed) != len(value):
                    raise RunnerError("missing or malformed per-presentation observations")
                for outcome in observed:
                    if (not isinstance(outcome, dict) or set(outcome) != {"outcome", "refusal_class"}
                            or not isinstance(outcome["outcome"], str) or not outcome["outcome"]
                            or (outcome["refusal_class"] is not None
                                and not isinstance(outcome["refusal_class"], str))):
                        raise RunnerError("malformed native dispatch or grant outcome")
            elif (not isinstance(observed, dict) or set(observed) != set(value)
                  or any(not isinstance(item, str) or not item for item in observed.values())):
                raise RunnerError("malformed native effect outcome")
            status = expected["claim_result"] if _json(record["observed"]) == _json(record["expected"]) else "CONTRADICTED"
            if record["result"] != status:
                raise RunnerError("runtime case status disagrees with observed evidence")


def _environment(work: Path) -> dict[str, str]:
    env = {
        "HOME": str(work), "TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1",
        "REMORA_ENV": "development", "REMORA_LEASE_SIGNING_KEY": "self-service-fixture-only",
    }
    if os.name == "nt" and "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def _boundary(snapshot: Path, digests: dict[str, str]) -> dict[str, str]:
    boundary_digest = _digest(_read_snapshot(snapshot, BOUNDARY, digests))
    summary = _decode(_read_snapshot(snapshot, SUMMARY, digests).decode())
    if (summary["producer"]["register"] != BOUNDARY
            or summary["producer"]["register_sha256"] != boundary_digest.removeprefix("sha256:")):
        raise RunnerError("boundary register and summary disagree")
    return {
        "register": BOUNDARY, "register_digest": boundary_digest,
        "summary": SUMMARY, "summary_digest": digests[SUMMARY],
        "audited_revision": summary["producer"]["audited_revision"],
    }


def run(
    root: Path, revision: str, contracts: list[str], output: Path,
    operator: str, timeout: int, host: str,
) -> int:
    """Publish a completed observation; distinguish unresolved and contradicted claims."""
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise RunnerError("existing output refused")
    if output.resolve().is_relative_to(root.resolve()):
        raise RunnerError("output must be outside the source checkout")
    started = dt.datetime.now(dt.UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="remora-self-service-") as temporary:
        work = Path(temporary)
        snapshot = work / "source"
        snapshot.mkdir()
        digests = _snapshot(root, revision, snapshot)
        _verify_snapshot(snapshot, digests)
        packages = _packages(snapshot, contracts, digests)
        boundary = _boundary(snapshot, digests)
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(snapshot / SCRIPT), "--worker", *contracts],
            cwd=work, env=_environment(work), capture_output=True, text=True,
            timeout=timeout, check=False, input=_json(digests),
        )
        if completed.returncode:
            raise RunnerError(f"runtime verifier failed ({completed.returncode}): {completed.stderr.strip()}")
        payload = _decode(completed.stdout)
        _verify_snapshot(snapshot, digests)
        _validate_observations(payload, packages, digests)
        report = {
            "schema_version": "remora-runtime-self-service-v1",
            "execution_status": "COMPLETED",
            "host_isolation": "NOT_ESTABLISHED",
            "runtime_revision": revision,
            "operator_declaration": operator,
            "host_declaration": host,
            "independence": "NOT_CLASSIFIED",
            "evaluator": "PRODUCER_RUNTIME",
            "authority": "NONE",
            "boundary": boundary,
            "started_at": started,
            "completed_at": dt.datetime.now(dt.UTC).isoformat(),
            "environment": payload["environment"],
            "source_files": digests,
            "runtime_modules": payload["runtime_modules"],
            "contracts": [
                {**{k: v for k, v in package.items() if k != "fixtures"},
                 "cases": [
                     {**{key: value for key, value in case.items() if key != "result"},
                      "claim_status": case["result"]}
                     for case in payload["cases"][package["contract_id"]]
                 ]}
                for package in packages
            ],
        }
        from jsonschema import Draft202012Validator, FormatChecker, ValidationError

        try:
            schema = _decode(_read_snapshot(snapshot, SCHEMA, digests).decode())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
        except ValidationError as exc:
            raise RunnerError(f"observation failed report schema: {exc.message}") from exc
        encoded = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        publish_new(output, encoded)
    statuses = {case["claim_status"] for p in report["contracts"] for case in p["cases"]}
    if "CONTRADICTED" in statuses:
        return 1
    return 3 if "NOT_ESTABLISHED" in statuses else 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--worker"]:
        if not arguments[1:] or any(name not in CONTRACTS for name in arguments[1:]):
            raise RunnerError("unsupported worker contract")
        return _worker(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list bounded procedures without runtime dependencies")
    parser.add_argument("--revision", help="full commit ID; must match clean tracked inputs at HEAD")
    parser.add_argument("--contract", choices=CONTRACTS, action="append")
    parser.add_argument("--output", type=Path, help="new JSON file outside the source checkout")
    parser.add_argument("--operator", help="operator's own attribution, not authenticated identity")
    parser.add_argument("--host", help="operator's host attribution, not attestation or ownership proof")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(arguments)
    if args.list:
        print(_json({"contracts": CONTRACTS, "report_schema": SCHEMA, "independence": "NOT_CLASSIFIED"}))
        return 0
    if (not args.revision or not args.output or not args.operator or not args.operator.strip()
            or not args.host or not args.host.strip()):
        parser.error("--revision, --output and nonempty --operator and --host are required")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")
    try:
        exit_code = run(ROOT, args.revision, list(dict.fromkeys(args.contract or CONTRACTS)),
                        args.output, args.operator, args.timeout, args.host)
    except (RunnerError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired, ImportError) as exc:
        print(_json({
            "execution_status": "FAILED", "observation_published": False,
            "claim_status": "NOT_EVALUATED",
            "error": f"self-service run failed; no result published: {exc}",
        }), file=sys.stderr)
        return 2
    print(f"COMPLETED observation written to {args.output}; exit {exit_code}; independence NOT_CLASSIFIED.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
