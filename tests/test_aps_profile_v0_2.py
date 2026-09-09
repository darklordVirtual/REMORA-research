# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from remora.interop.aps.adapter_v0_2 import (
    run_accountability_schema_layer,
    run_token_exchange_attenuation_p1,
)

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def test_token_exchange_p1_uses_remora_delegation_verifier(tmp_path: Path) -> None:
    vectors = {
        "family": "token-exchange-attenuation-v0",
        "cases": [
            {
                "id": "valid-subset",
                "properties": ["P1", "P2"],
                "vector_valid": True,
                "subject_token_claims": {"scope": "read write"},
                "exchanged_token_claims": {"scope": "read"},
            },
            {
                "id": "invalid-widening",
                "properties": ["P1"],
                "vector_valid": False,
                "invalid_reason": "t2_scope_not_subset_of_t1",
                "subject_token_claims": {"scope": "read"},
                "exchanged_token_claims": {"scope": "read write"},
            },
            {
                "id": "p3-only",
                "properties": ["P3"],
                "vector_valid": True,
                "subject_token_claims": {"scope": "read"},
                "exchanged_token_claims": {"scope": "read"},
            },
        ],
    }
    path = tmp_path / "vectors.json"
    path.write_text(json.dumps(vectors), encoding="utf-8")

    report = run_token_exchange_attenuation_p1(path)

    assert report["summary"] == {"cases": 2, "passed": 2, "divergences": 0}
    by_id = {item["id"]: item for item in report["results"]}
    assert by_id["valid-subset"]["observed_scope_widening"] is False
    assert by_id["valid-subset"]["effective_scope"] == ["read"]
    assert by_id["invalid-widening"]["observed_scope_widening"] is True
    assert any(
        failure.startswith("scope_widened_at_link:1")
        for failure in by_id["invalid-widening"]["remora_failures"]
    )
    assert report["not_run"]["properties"] == ["P2", "P3"]


def _write_schema_suite(root: Path, *, pinned_digest: str | None = None) -> None:
    pytest.importorskip("jsonschema")
    fixture_dir = root / "fixtures/accountability-record"
    fixture_dir.mkdir(parents=True)

    schema = {
        "$schema": DRAFT_2020_12,
        "type": "object",
        "required": ["decision", "sig_alg"],
        "properties": {
            "decision": {"enum": ["allow", "deny", "halt"]},
            "sig_alg": {"const": "Ed25519"},
        },
    }
    schema_bytes = (json.dumps(schema, separators=(",", ":")) + "\n").encode()
    schema_path = fixture_dir / "accountability-record.schema.json"
    schema_path.write_bytes(schema_bytes)
    digest = hashlib.sha256(schema_bytes).hexdigest()

    fixture = {
        "vectors": [
            {
                "name": "positive",
                "record": {"decision": "allow", "sig_alg": "Ed25519"},
                "expected_verification": True,
            },
            {
                "name": "decision-negative",
                "record": {"decision": "permit", "sig_alg": "Ed25519"},
                "expected_verification": False,
                "rejection_kind": "schema",
                "expected_error_code": "DECISION_NOT_IN_ENUM",
            },
            {
                "name": "sig-alg-negative",
                "record": {"decision": "allow", "sig_alg": "ed25519"},
                "expected_verification": False,
                "rejection_kind": "schema",
                "expected_error_code": "SIG_ALG_NOT_CANONICAL",
            },
            {
                "name": "crypto-negative",
                "record": {"decision": "allow", "sig_alg": "Ed25519"},
                "expected_verification": False,
                "rejection_kind": "signature",
                "expected_error_code": "SIGNATURE_INVALID",
            },
        ]
    }
    (fixture_dir / "accountability-record-fixture-v1.json").write_text(
        json.dumps(fixture), encoding="utf-8"
    )

    manifest = {
        "fixtures": [
            {
                "category": "accountability-record",
                "required_layers": ["crypto", "schema"],
                "layers": {
                    "schema": {
                        "kind": "json-schema",
                        "dialect": DRAFT_2020_12,
                        "schema_path": (
                            "accountability-record/"
                            "accountability-record.schema.json"
                        ),
                        "schema_sha256": pinned_digest or digest,
                        "owns_rejection_kinds": ["schema"],
                        "error_bindings": {
                            "DECISION_NOT_IN_ENUM": {
                                "instance_path": "/decision",
                                "keyword": "enum",
                            },
                            "SIG_ALG_NOT_CANONICAL": {
                                "instance_path": "/sig_alg",
                                "keyword": "const",
                            },
                        },
                    }
                },
            }
        ]
    }
    (root / "fixtures/manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_accountability_schema_layer_matches_aps_error_bindings(
    tmp_path: Path,
) -> None:
    _write_schema_suite(tmp_path)

    report = run_accountability_schema_layer(tmp_path)

    assert report["status"] == "RUN"
    assert report["summary"] == {
        "decisive_checks": 3,
        "passed": 3,
        "divergences": 0,
        "non_decisive": 1,
    }
    by_name = {item["name"]: item for item in report["results"]}
    assert by_name["decision-negative"]["observed_errors"] == [
        {"instance_path": "/decision", "keyword": "enum"}
    ]
    assert by_name["sig-alg-negative"]["observed_errors"] == [
        {"instance_path": "/sig_alg", "keyword": "const"}
    ]
    assert by_name["crypto-negative"]["outcome"] == "NON_DECISIVE"


def test_accountability_schema_layer_fails_closed_on_pin_drift(
    tmp_path: Path,
) -> None:
    _write_schema_suite(tmp_path, pinned_digest="0" * 64)

    report = run_accountability_schema_layer(tmp_path)

    assert report["status"] == "BLOCKED"
    assert report["summary"]["divergences"] == 1
    assert "schema digest mismatch" in report["reason"]
