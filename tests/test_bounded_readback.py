# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Offline adapter regressions; no frozen vectors or live services are used."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace

import pytest

from experiments.bounded_readback import (
    MAX_BYTES,
    SCHEMA,
    ProcessingStatus as Processing,
    PropertyVerdict as Verdict,
    ReadbackContract,
    SourcePolicy,
    read_once,
    verify_readback,
)


@pytest.fixture
def source(signing_key):
    return SourcePolicy("work-order-store", "test-key-v1", signing_key)


@pytest.fixture
def contract():
    return ReadbackContract(
        tenant="tenant-a", target="order-17", operation="update-status",
        attempt="attempt-4", request_id="deployment-challenge-9",
        expected_json='{"status":"closed"}', not_before=100,
        expires_at=160, max_age_seconds=20,
    )


@pytest.fixture
def payload(contract, source):
    return {
        "schema": SCHEMA, "source_id": source.source_id, "key_id": source.key_id,
        "tenant": contract.tenant, "target": contract.target,
        "operation": contract.operation, "attempt": contract.attempt,
        "request_id": contract.request_id, "observed_at": 110,
        "state": {"status": "closed", "unrelated_counter": 7},
    }


def signed(payload, key):
    # Encode independently of the verifier helper to exercise the wire boundary.
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    mac = hmac.new(key, body, hashlib.sha256).hexdigest()
    return json.dumps({"payload": payload, "mac": mac}).encode()


def check(payload, source, contract, now=120):
    return verify_readback(signed(payload, source.key), contract=contract, source=source, now=now)


def test_declared_delta_only_and_digest(payload, source, contract):
    raw = signed(payload, source.key)
    result = verify_readback(raw, contract=contract, source=source, now=120)
    assert result.processing is Processing.COMPLETED
    assert result.verdict is Verdict.ESTABLISHED
    assert result.evidence_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.claim == "postcondition_observed"
    assert not result.missing_evidence
    assert result == verify_readback(raw, contract=contract, source=source, now=120)


def test_missing_field_is_not_mismatch(payload, source, contract):
    payload["state"] = {}
    result = check(payload, source, contract)
    assert result.verdict is Verdict.NOT_ESTABLISHED
    assert result.missing_evidence == ("status",)


def test_observed_contradiction_refutes_even_with_other_fields_missing(payload, source, contract):
    contract = replace(contract, expected_json='{"status":"closed","owner":"alice"}')
    payload["state"] = {"status": "open"}
    assert check(payload, source, contract).verdict is Verdict.VIOLATED


@pytest.mark.parametrize("expected,observed", [
    ('{"flag":true}', {"flag": 1}),
    ('{"flag":1}', {"flag": True}),
    ('{"flag":null}', {}),
    ('{"flag":null}', {"flag": None}),
    ('{"nested":{"a":1,"b":[true,null]}}', {"nested": {"b": [True, None], "a": 1}}),
])
def test_typed_json_comparison(payload, source, contract, expected, observed):
    contract = replace(contract, expected_json=expected)
    payload["state"] = observed
    result = check(payload, source, contract)
    if not observed:
        assert result.verdict is Verdict.NOT_ESTABLISHED
    elif expected in ('{"flag":true}', '{"flag":1}'):
        assert result.verdict is Verdict.VIOLATED
    else:
        assert result.verdict is Verdict.ESTABLISHED


@pytest.mark.parametrize("field", ["tenant", "target", "operation", "attempt", "request_id"])
def test_cross_scope_signed_replay_has_no_verdict(payload, source, contract, field):
    payload[field] = "different"
    result = check(payload, source, contract)
    assert result.processing is Processing.REJECTED_EVIDENCE
    assert result.reason == "scope_mismatch"
    assert result.verdict is None


@pytest.mark.parametrize("field", ["source_id", "key_id"])
def test_envelope_cannot_choose_trust_anchor(payload, source, contract, field):
    payload[field] = "self-declared-trusted"
    result = check(payload, source, contract)
    assert result.reason == "untrusted_source"
    assert result.verdict is None


def test_tampering_and_wrong_key_have_no_verdict(payload, source, contract):
    envelope = json.loads(signed(payload, source.key))
    envelope["payload"]["state"]["status"] = "tampered"
    for raw in [json.dumps(envelope).encode(), signed(payload, b"x" * 32)]:
        result = verify_readback(raw, contract=contract, source=source, now=120)
        assert result.reason == "invalid_signature"
        assert result.processing is Processing.REJECTED_EVIDENCE
        assert result.verdict is None


@pytest.mark.parametrize("observed_at,now,reason", [
    (99, 120, "settlement_not_observed"),
    (110, 99, "settlement_not_observed"),
    (121, 120, "future_observation"),
    (100, 121, "stale_observation"),
    (150, 161, "contract_expired"),
])
def test_time_bounds_do_not_become_mismatches(payload, source, contract, observed_at, now, reason):
    payload["observed_at"] = observed_at
    payload["state"]["status"] = "open"
    result = check(payload, source, contract, now)
    assert result.processing is Processing.COMPLETED
    assert result.verdict is Verdict.NOT_ESTABLISHED
    assert result.reason == reason
    assert result.missing_evidence


@pytest.mark.parametrize("observed_at,now", [(100, 100), (100, 120), (160, 160)])
def test_inclusive_time_boundaries(payload, source, contract, observed_at, now):
    payload["observed_at"] = observed_at
    assert check(payload, source, contract, now).verdict is Verdict.ESTABLISHED


@pytest.mark.parametrize("raw", [
    b"", b"not JSON", b"\xff", b"[]", b"{}", b"null", b" " * (MAX_BYTES + 1),
    b'{"payload":{},"payload":{},"mac":"x"}',
    b'{"x":{"a":1,"a":2}}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1.2}',
    b'{"a":"\\ud800"}', b"[" * 2000 + b"]" * 2000,
    "not bytes", bytearray(b"{}"),
])
def test_malformed_input_is_nonverdict(source, contract, raw):
    result = verify_readback(raw, contract=contract, source=source, now=120)
    assert result.processing is Processing.REJECTED_EVIDENCE
    assert result.verdict is None
    assert result.reason == "malformed_evidence"


@pytest.mark.parametrize("field,value", [
    ("schema", "unrecognized"), ("observed_at", True), ("observed_at", -1),
    ("observed_at", "110"), ("state", []), ("state", {"x": 1.0}),
    ("target", ""), ("tenant", 1), ("source_id", " "),
])
def test_invalid_signed_payload_is_nonverdict(payload, source, contract, field, value):
    payload[field] = value
    result = check(payload, source, contract)
    assert result.reason == "malformed_evidence"
    assert result.verdict is None


@pytest.mark.parametrize("mutation", ["extra", "missing", "nonobject", "short_mac", "uppercase_mac", "numeric_mac"])
def test_strict_envelope(payload, source, contract, mutation):
    envelope = json.loads(signed(payload, source.key))
    if mutation == "extra":
        envelope["payload"]["source_accepted"] = True
    elif mutation == "missing":
        del envelope["payload"]["attempt"]
    elif mutation == "nonobject":
        envelope["payload"] = []
    elif mutation == "short_mac":
        envelope["mac"] = "abc"
    elif mutation == "uppercase_mac":
        envelope["mac"] = envelope["mac"].upper()
    else:
        envelope["mac"] = 123
    result = verify_readback(json.dumps(envelope).encode(), contract=contract, source=source, now=120)
    assert result.reason == "malformed_evidence"
    assert result.verdict is None


def test_missing_readback_is_distinct_from_acquisition_failure(source, contract):
    missing = read_once(lambda: None, contract=contract, source=source, clock=lambda: 120)
    assert missing.processing is Processing.COMPLETED
    assert missing.verdict is Verdict.NOT_ESTABLISHED

    calls = []

    def broken_reader():
        calls.append("read")
        raise TimeoutError("https://secret:password@private-host")

    failed = read_once(broken_reader, contract=contract, source=source, clock=lambda: 120)
    assert calls == ["read"]  # no retry of a potentially expensive reader
    assert failed.processing is Processing.ACQUISITION_FAILED
    assert failed.verdict is None
    assert "password" not in repr(failed)


def test_clock_sampled_after_read(payload, source, contract):
    calls = []

    def reader():
        calls.append("read")
        return signed(payload, source.key)

    def clock():
        calls.append("clock")
        return 161  # contract expired while acquiring the evidence

    result = read_once(reader, contract=contract, source=source, clock=clock)
    assert calls == ["read", "clock"]
    assert result.reason == "contract_expired"


@pytest.mark.parametrize("now", [True, -1, 120.0, "120", None])
def test_bad_clock_is_verifier_failure_not_property_verdict(source, contract, now):
    result = read_once(lambda: None, contract=contract, source=source, clock=lambda: now)
    assert result.processing is Processing.VERIFIER_FAILED
    assert result.verdict is None


def test_clock_exception_is_not_leaked(source, contract):
    def broken_clock():
        raise RuntimeError("private diagnostic")

    result = read_once(lambda: None, contract=contract, source=source, clock=broken_clock)
    assert result.processing is Processing.VERIFIER_FAILED
    assert "private diagnostic" not in repr(result)


@pytest.mark.parametrize("changes", [
    {"expected_json": "{}"}, {"expected_json": "[]"}, {"expected_json": "invalid"},
    {"expected_json": '{"x":1,"x":2}'}, {"expected_json": '{"x":0.5}'},
    {"expected_json": {"x": 1}}, {"expected_json": "x" * (MAX_BYTES + 1)},
    {"tenant": ""}, {"request_id": " "}, {"not_before": -1},
    {"expires_at": 100}, {"max_age_seconds": 0}, {"max_age_seconds": True},
])
def test_invalid_contract_refused(contract, changes):
    with pytest.raises(ValueError):
        replace(contract, **changes)


def test_bounded_nesting_and_key_custody(source, contract, payload):
    nested = {}
    for _ in range(20):
        nested = {"nested": nested}
    payload["state"] = nested
    assert check(payload, source, contract).processing is Processing.REJECTED_EVIDENCE
    with pytest.raises(ValueError):
        replace(source, key=b"short")
    with pytest.raises(ValueError):
        replace(source, key="x" * 32)
    assert source.key.decode() not in repr(source)


def test_no_network_or_artifact_writes(payload, source, contract, monkeypatch):
    import builtins
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected external side effect")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    raw = signed(payload, source.key)
    result = read_once(lambda: raw, contract=contract, source=source, clock=lambda: 120)
    assert result.verdict is Verdict.ESTABLISHED
