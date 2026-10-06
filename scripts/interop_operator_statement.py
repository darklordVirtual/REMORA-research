#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Sign or verify a detached operator statement; never admit or authorize evidence."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.interop.evidence_io import EvidenceError, decode_json, digest_bytes, publish_new
from remora.interop.jcs import CANONICAL_FORMAT, canonicalise

SCHEMA = ROOT / "schemas/interop-operator-statement-v1.schema.json"
OBSERVATION_SCHEMA = ROOT / "schemas/runtime-self-service-v1.schema.json"
RUNNER = "scripts/interop_self_service.py"
DOMAIN = b"REMORA-operator-statement-v1\0"


def _validate(value: Any, schema: Path) -> None:
    from jsonschema import Draft202012Validator, FormatChecker, ValidationError

    try:
        Draft202012Validator(decode_json(schema.read_text()), format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        raise EvidenceError(f"invalid {schema.name}: {exc.message}") from exc


def _observation(path: Path) -> tuple[bytes, dict[str, Any]]:
    data = path.read_bytes()
    report = decode_json(data.decode("utf-8"))
    _validate(report, OBSERVATION_SCHEMA)
    if RUNNER not in report["source_files"]:
        raise EvidenceError("observation lacks pinned runner digest")
    if len({p["contract_id"] for p in report["contracts"]}) != len(report["contracts"]):
        raise EvidenceError("observation contains duplicate contracts")
    if any(report["source_files"].get(path) != digest for path, digest in report["runtime_modules"].items()):
        raise EvidenceError("observation runtime modules disagree with source digests")
    boundary = report["boundary"]
    if (report["source_files"].get(boundary["register"]) != boundary["register_digest"]
            or report["source_files"].get(boundary["summary"]) != boundary["summary_digest"]):
        raise EvidenceError("observation boundary disagrees with source digests")
    return data, report


def _base_statement(data: bytes, report: dict[str, Any], operator: str) -> dict[str, Any]:
    if not operator.strip() or operator != report["operator_declaration"]:
        raise EvidenceError("operator identity must match observation attribution")
    return {
        "schema_version": "remora-operator-statement-v1",
        "canonical_format": CANONICAL_FORMAT,
        "runtime_revision": report["runtime_revision"],
        "revision_digest": digest_bytes(canonicalise({
            "runtime_revision": report["runtime_revision"], "source_files": report["source_files"],
        })),
        "runner_digest": report["source_files"][RUNNER],
        "boundary_digest": report["boundary"]["register_digest"],
        "package_digests": sorted(
            [{"contract_id": p["contract_id"], "package_digest": p["package_digest"],
              "fixture_digest": p["fixture_digest"]} for p in report["contracts"]],
            key=lambda item: item["contract_id"],
        ),
        "observation_digest": digest_bytes(data),
        "operator_identity": operator,
        "host_declaration": report["host_declaration"],
        "execution_started_at": report["started_at"],
        "execution_completed_at": report["completed_at"],
        "host_isolation": "NOT_ESTABLISHED",
        "independence": "NOT_CLASSIFIED",
        "admission": "UNADMITTED",
        "authority": "NONE",
    }


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    value = base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    if _b64(value) != text:
        raise EvidenceError("non-canonical base64url value")
    return value


def _public_identity(public: Any) -> tuple[str, dict[str, str]]:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    raw = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return digest_bytes(raw), {"kty": "OKP", "crv": "Ed25519", "x": _b64(raw)}


def sign(observation: Path, private_key: Path, operator: str, output: Path) -> None:
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    if output.exists() or output.is_symlink():
        raise EvidenceError("existing output refused")
    data, report = _observation(observation)
    try:
        key = load_pem_private_key(private_key.read_bytes(), password=None)
    except UnsupportedAlgorithm as exc:
        raise EvidenceError("operator key algorithm is unsupported") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise EvidenceError("operator signing key must be Ed25519")
    key_id, jwk = _public_identity(key.public_key())
    statement = {
        **_base_statement(data, report, operator),
        "key_id": key_id,
        "issued_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    envelope = {
        "statement": statement,
        "signature": {
            "algorithm": "Ed25519", "public_key_jwk": jwk,
            "value": _b64(key.sign(DOMAIN + canonicalise(statement))),
        },
    }
    _validate(envelope, SCHEMA)
    publish_new(output, (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode())


def verify(observation: Path, statement_path: Path, trusted_key: Path, operator: str) -> None:
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    data, report = _observation(observation)
    envelope = decode_json(statement_path.read_text(encoding="utf-8"))
    _validate(envelope, SCHEMA)
    try:
        public = load_pem_public_key(trusted_key.read_bytes())
    except UnsupportedAlgorithm as exc:
        raise EvidenceError("trusted operator key algorithm is unsupported") from exc
    if not isinstance(public, Ed25519PublicKey):
        raise EvidenceError("trusted operator verification key must be Ed25519")
    key_id, jwk = _public_identity(public)
    statement = envelope["statement"]
    if statement["key_id"] != key_id or envelope["signature"]["public_key_jwk"] != jwk:
        raise EvidenceError("statement signer does not match the explicitly trusted key")
    expected = _base_statement(data, report, operator)
    if any(statement[name] != value for name, value in expected.items()):
        raise EvidenceError("statement does not bind the supplied observation and operator")
    try:
        public.verify(_unb64(envelope["signature"]["value"]), DOMAIN + canonicalise(statement))
    except InvalidSignature as exc:
        raise EvidenceError("operator signature invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    signing = commands.add_parser("sign", help="sign only the supplied observation under an operator-owned key")
    signing.add_argument("--private-key", type=Path, required=True, help="unencrypted Ed25519 PEM, never REMORA lease keys")
    signing.add_argument("--output", type=Path, required=True, help="new detached statement file")
    verification = commands.add_parser("verify", help="verify against an independently selected public key")
    verification.add_argument("--trusted-key", type=Path, required=True, help="explicit Ed25519 public PEM; no embedded-key trust")
    verification.add_argument("--statement", type=Path, required=True)
    for command in (signing, verification):
        command.add_argument("--observation", type=Path, required=True)
        command.add_argument("--operator", required=True, help="expected operator attribution for this key")
    args = parser.parse_args(argv)
    try:
        if args.command == "sign":
            sign(args.observation, args.private_key, args.operator, args.output)
            print("Operator statement published; admission UNADMITTED, independence NOT_CLASSIFIED.")
        else:
            verify(args.observation, args.statement, args.trusted_key, args.operator)
            print(json.dumps({
                "signature_status": "VALID", "observation_binding": "MATCHED",
                "operator_identity": args.operator, "host_isolation": "NOT_ESTABLISHED",
                "independence": "NOT_CLASSIFIED", "admission": "UNADMITTED", "authority": "NONE",
            }, sort_keys=True))
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        print(f"operator statement {args.command} failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
