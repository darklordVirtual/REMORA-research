# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An operator signature binds bytes and key possession, not host or claim truth."""
from __future__ import annotations

import copy
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from remora.interop.evidence_io import EvidenceError
from scripts import interop_operator_statement as operator_statement


def test_excessively_nested_json_is_an_explicit_evidence_error():
    from remora.interop.evidence_io import decode_json

    with pytest.raises(EvidenceError, match="nesting exceeds parser limit"):
        decode_json("[" * 10_000 + "0" + "]" * 10_000)


def test_json_nesting_limit_is_exact_and_ignores_brackets_in_strings():
    from remora.interop.evidence_io import MAX_JSON_DEPTH, decode_json

    deepest = "[" * MAX_JSON_DEPTH + "0" + "]" * MAX_JSON_DEPTH
    assert decode_json(deepest) is not None
    with pytest.raises(EvidenceError, match="nesting exceeds parser limit"):
        decode_json("[" + deepest + "]")
    brackets = "[" * (MAX_JSON_DEPTH + 1)
    assert decode_json('{"s": "' + brackets + '", "e": "\\\\\\"' + brackets + '"}') == {
        "s": brackets, "e": '\\"' + brackets,
    }


@pytest.fixture
def observation(tmp_path):
    digest = "sha256:" + "a" * 64
    value = {"value": [{"outcome": "DISPATCHED", "refusal_class": None}]}
    report = {
        "schema_version": "remora-runtime-self-service-v1",
        "execution_status": "COMPLETED", "host_isolation": "NOT_ESTABLISHED",
        "runtime_revision": "b" * 40,
        "operator_declaration": "operator:fixture", "host_declaration": "fixture host",
        "independence": "NOT_CLASSIFIED", "evaluator": "PRODUCER_RUNTIME", "authority": "NONE",
        "started_at": "2026-10-04T12:00:00+00:00", "completed_at": "2026-10-04T12:00:01+00:00",
        "environment": {"python": "3.12", "os": "Linux", "machine": "fixture", "distributions": []},
        "source_files": {operator_statement.RUNNER: digest, "remora/fixture.py": digest},
        "runtime_modules": {"remora/fixture.py": digest},
        "contracts": [{
            "contract_id": "exact-call-binding-v1", "fixture_source_revision": "c" * 40,
            "fixture_digest": digest, "package_digest": digest,
            "claim_ceilings": [{"claim_id": "exact_call_binding",
                               "result_vocabulary": ["ESTABLISHED", "NOT_ESTABLISHED", "CONTRADICTED"],
                               "claim_ceiling": "Synthetic test of statement binding only."}],
            "does_not_establish": ["Actual runtime execution or independent verification."],
            "cases": [{"case_id": "fixture", "claim_id": "exact_call_binding",
                       "expected": value, "observed": copy.deepcopy(value), "claim_status": "ESTABLISHED"}],
        }],
    }
    report["boundary"] = {
        "register": "docs/interop/remora-boundaries-v1.yaml",
        "register_digest": digest,
        "summary": "artifacts/interop/remora-boundary-summary-v1.json",
        "summary_digest": digest, "audited_revision": "c" * 40,
    }
    report["source_files"].update({
        report["boundary"]["register"]: digest, report["boundary"]["summary"]: digest,
    })
    path = tmp_path / "observation.json"
    path.write_text(json.dumps(report))
    return path


@pytest.fixture
def keys(tmp_path):
    key = Ed25519PrivateKey.generate()
    private = tmp_path / "operator-private.pem"
    public = tmp_path / "operator-public.pem"
    private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    private.chmod(0o600)
    public.write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    return private, public


def test_detached_statement_binds_all_requested_fields(observation, keys, tmp_path):
    private, public = keys
    output = tmp_path / "statement.json"
    operator_statement.sign(observation, private, "operator:fixture", output)
    operator_statement.verify(observation, output, public, "operator:fixture")
    body = json.loads(output.read_text())["statement"]
    assert {
        "revision_digest", "runner_digest", "package_digests", "observation_digest",
        "operator_identity", "key_id", "execution_started_at", "execution_completed_at",
    } <= body.keys()
    assert body["host_isolation"] == "NOT_ESTABLISHED"
    assert body["independence"] == "NOT_CLASSIFIED"
    assert body["admission"] == "UNADMITTED"
    assert body["authority"] == "NONE"
    assert private.read_text() not in output.read_text()


@pytest.mark.parametrize("field", [
    "runtime_revision", "revision_digest", "runner_digest", "boundary_digest", "observation_digest",
    "operator_identity", "host_declaration", "execution_started_at", "issued_at", "package_digests",
])
def test_statement_field_tampering_refused(observation, keys, tmp_path, field):
    private, public = keys
    output = tmp_path / "statement.json"
    operator_statement.sign(observation, private, "operator:fixture", output)
    envelope = json.loads(output.read_text())
    if field == "runtime_revision":
        envelope["statement"][field] = "f" * 40
    elif field.endswith("_digest"):
        envelope["statement"][field] = "sha256:" + "f" * 64
    elif field.endswith("_at"):
        envelope["statement"][field] = "2026-10-05T12:00:00+00:00"
    elif field == "package_digests":
        envelope["statement"][field][0]["package_digest"] = "sha256:" + "f" * 64
    else:
        envelope["statement"][field] = "changed attribution"
    output.write_text(json.dumps(envelope))
    with pytest.raises(EvidenceError):
        operator_statement.verify(observation, output, public, "operator:fixture")


def test_exact_observation_bytes_not_only_parsed_values_are_signed(observation, keys, tmp_path):
    private, public = keys
    output = tmp_path / "statement.json"
    operator_statement.sign(observation, private, "operator:fixture", output)
    observation.write_bytes(observation.read_bytes() + b"\n")
    with pytest.raises(EvidenceError, match="does not bind"):
        operator_statement.verify(observation, output, public, "operator:fixture")


def test_embedded_key_never_supplies_its_own_trust(observation, keys, tmp_path):
    private, _ = keys
    output = tmp_path / "statement.json"
    operator_statement.sign(observation, private, "operator:fixture", output)
    different = tmp_path / "different-public.pem"
    different.write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    ))
    with pytest.raises(EvidenceError, match="explicitly trusted key"):
        operator_statement.verify(observation, output, different, "operator:fixture")


def test_key_possession_does_not_supply_operator_identity_mapping(observation, keys, tmp_path):
    private, public = keys
    output = tmp_path / "statement.json"
    operator_statement.sign(observation, private, "operator:fixture", output)
    with pytest.raises(EvidenceError, match="operator identity"):
        operator_statement.verify(observation, output, public, "operator:someone-else")


@pytest.mark.parametrize("change", ["signature", "algorithm", "admission", "independence", "extra_field"])
def test_malformed_or_promoted_operator_statement_refused(observation, keys, tmp_path, change):
    private, public = keys
    output = tmp_path / "statement.json"
    operator_statement.sign(observation, private, "operator:fixture", output)
    envelope = json.loads(output.read_text())
    if change == "signature":
        value = envelope["signature"]["value"]
        envelope["signature"]["value"] = ("A" if value[0] != "A" else "B") + value[1:]
    elif change == "algorithm":
        envelope["signature"]["algorithm"] = "HMAC"
    elif change in ("admission", "independence"):
        envelope["statement"][change] = "ESTABLISHED"
    else:
        envelope["statement"]["confers_authority"] = True
    output.write_text(json.dumps(envelope))
    with pytest.raises(EvidenceError):
        operator_statement.verify(observation, output, public, "operator:fixture")


def test_existing_evidence_never_overwritten(observation, keys, tmp_path):
    private, _ = keys
    output = tmp_path / "statement.json"
    output.write_text("existing operator record")
    with pytest.raises(EvidenceError, match="existing output refused"):
        operator_statement.sign(observation, private, "operator:fixture", output)
    assert output.read_text() == "existing operator record"


def test_other_key_algorithms_refused(observation, tmp_path):
    private = tmp_path / "rsa.pem"
    private.write_bytes(generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption(),
    ))
    with pytest.raises(EvidenceError, match="must be Ed25519"):
        operator_statement.sign(observation, private, "operator:fixture", tmp_path / "statement.json")


def test_duplicate_json_cannot_change_signature_semantics(observation, keys, tmp_path):
    private, public = keys
    output = tmp_path / "statement.json"
    operator_statement.sign(observation, private, "operator:fixture", output)
    original = output.read_text()
    output.write_text(original.replace('"algorithm": "Ed25519"',
                                       '"algorithm": "HMAC", "algorithm": "Ed25519"'))
    with pytest.raises(EvidenceError, match="duplicate"):
        operator_statement.verify(observation, output, public, "operator:fixture")


def test_cli_verification_is_bounded_and_reports_errors(observation, keys, tmp_path, capsys):
    private, public = keys
    output = tmp_path / "statement.json"
    assert operator_statement.main([
        "sign", "--observation", str(observation), "--private-key", str(private),
        "--operator", "operator:fixture", "--output", str(output),
    ]) == 0
    capsys.readouterr()
    arguments = [
        "verify", "--observation", str(observation), "--statement", str(output),
        "--trusted-key", str(public), "--operator", "operator:fixture",
    ]
    assert operator_statement.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["signature_status"] == "VALID"
    assert result["admission"] == "UNADMITTED"
    output.write_text("{}")
    assert operator_statement.main(arguments) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "failed" in captured.err
