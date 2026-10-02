# SPDX-License-Identifier: BUSL-1.1
"""Processing failures stay separate from evidence property conclusions."""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

import pytest

from remora.evidence.admission import (
    EvidenceAdmission,
    ProcessingStatus,
    process_evidence_payload,
    processing_failure,
    TrustConfig,
)


def _parse_records(_: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "manifest": None,
        "coverage": None,
        "vantage": None,
        "binding": None,
        "prior_commitment": None,
    }


def _process(
    raw: bytes,
    *,
    parse: Any = _parse_records,
) -> EvidenceAdmission:
    return process_evidence_payload(
        raw,
        schema="v1",
        parse=parse,
        trust=TrustConfig(),
        expected_invocation={"invocation_id": "inv-1"},
        execution_started_at=10,
        evaluated_fields=(),
        evaluated_interval=(0, 1),
        now=20,
    )


def _assert_processing_only(result: EvidenceAdmission, status: ProcessingStatus) -> None:
    assert result.processing is status
    assert result.established_facts == {}
    assert result.evidence_digest == ""
    assert result.scope == {}


@pytest.mark.parametrize("raw", [b"{", b"\xff", b'{"schema":"v1","schema":"v1"}'])
def test_malformed_payload_is_rejected_without_property_facts(raw: bytes) -> None:
    result = _process(raw)

    _assert_processing_only(result, ProcessingStatus.REJECTED_EVIDENCE)
    assert result.reason_codes == ("malformed_evidence",)


def test_unsupported_schema_is_not_a_property_conclusion() -> None:
    result = _process(b'{"schema":"v2"}')

    _assert_processing_only(result, ProcessingStatus.UNSUPPORTED)
    assert result.reason_codes == ("unsupported_evidence_schema",)


def test_parser_error_is_rejected_without_leaking_exception_text() -> None:
    def parse(_: Mapping[str, Any]) -> None:
        raise ValueError("credential-bearing parser detail")

    result = _process(b'{"schema":"v1"}', parse=parse)

    _assert_processing_only(result, ProcessingStatus.REJECTED_EVIDENCE)
    assert result.reason_codes == ("malformed_evidence",)
    assert "credential-bearing" not in repr(result)


def test_verifier_exception_is_not_not_established(monkeypatch: pytest.MonkeyPatch) -> None:
    import remora.evidence.admission.admission as admission_module

    def fail_verifier(**_: Any) -> EvidenceAdmission:
        raise RuntimeError("sensitive verifier detail")

    monkeypatch.setattr(admission_module, "admit_evidence", fail_verifier)
    result = _process(b'{"schema":"v1"}')

    _assert_processing_only(result, ProcessingStatus.VERIFIER_FAILED)
    assert result.reason_codes == ("verifier_failed",)
    assert "sensitive" not in repr(result)


def test_successful_payload_digest_is_derived_from_raw_bytes() -> None:
    raw = b'{"schema":"v1"}'
    result = _process(raw)

    assert result.processing is ProcessingStatus.COMPLETED
    assert not result.is_established("source_accepted")

    assert result.evidence_digest == hashlib.sha256(raw).hexdigest()


def test_acquisition_failure_has_no_property_facts() -> None:
    result = processing_failure(
        ProcessingStatus.ACQUISITION_FAILED, "acquisition_failed",
    )

    _assert_processing_only(result, ProcessingStatus.ACQUISITION_FAILED)
    assert not result.is_established("source_accepted")
