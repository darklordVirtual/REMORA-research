# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Opt-in research adapter for authenticated, bounded read-back observations.

Not imported by the runtime or by the frozen conformance checkers. This local
HMAC experiment authenticates a statement from a deployment-selected key holder;
it does not prove that the source is truthful, independent or uncompromised.
The envelope is an experimental format, not a public API or standards profile.
No network, credential discovery, dispatch, retry or evidence-file writes occur
here. The deployment supplies the reader, key, contract and clock out of band.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

SCHEMA = "remora.readback-experiment.v1"
MAX_BYTES = 65_536
_BINDINGS = ("tenant", "target", "operation", "attempt", "request_id")
_PAYLOAD_KEYS = {
    "schema", "source_id", "key_id", "observed_at", "state", *_BINDINGS,
}


class ProcessingStatus(StrEnum):
    COMPLETED = "completed"
    REJECTED_EVIDENCE = "rejected_evidence"
    ACQUISITION_FAILED = "acquisition_failed"
    VERIFIER_FAILED = "verifier_failed"


class PropertyVerdict(StrEnum):
    ESTABLISHED = "established"
    VIOLATED = "violated"
    NOT_ESTABLISHED = "not_established"


def _json_value(value: Any, depth: int = 0) -> None:
    # Keep the prototype's comparison domain explicit: no floats or objects
    # coerced with default=str, and bool must not collapse into int.
    if depth > 16:
        raise ValueError("JSON nesting limit exceeded")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise ValueError("unsupported JSON value")


def _canonical(value: Any) -> bytes:
    """Local signing/comparison encoding; not an RFC 8785 implementation."""
    _json_value(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _decode(raw: bytes) -> Any:
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ValueError("invalid evidence size or type")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    _canonical(value)
    return value


def _identifier(value: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError("nonempty identifier required")


@dataclass(frozen=True)
class SourcePolicy:
    """Local trust configuration, never taken from the observed envelope.

    Both source and verifier know this symmetric key and can forge statements.
    Do not use this prototype as independently verifiable third-party evidence.
    """

    source_id: str
    key_id: str
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _identifier(self.source_id)
        _identifier(self.key_id)
        if type(self.key) is not bytes or len(self.key) < 32:
            raise ValueError("deployment key must contain at least 32 bytes")


@dataclass(frozen=True)
class ReadbackContract:
    """Deployment-owned scope and expected delta, not agent assertions.

    request_id is a fresh deployment-issued observation challenge for this
    attempt. Re-checking the same evidence is intentionally allowed; this is
    not a single-use execution grant. Times are UTC epoch seconds.
    """

    tenant: str
    target: str
    operation: str
    attempt: str
    request_id: str
    expected_json: str
    not_before: int
    expires_at: int
    max_age_seconds: int = 30

    def __post_init__(self) -> None:
        for name in _BINDINGS:
            _identifier(getattr(self, name))
        if type(self.expected_json) is not str:
            raise ValueError("expected_json must be text")
        expected = _decode(self.expected_json.encode("utf-8"))
        if type(expected) is not dict or not expected:
            raise ValueError("a nonempty declared delta is required")
        for value in (self.not_before, self.expires_at, self.max_age_seconds):
            if type(value) is not int or value < 0:
                raise ValueError("nonnegative integer time required")
        if self.expires_at <= self.not_before or self.max_age_seconds == 0:
            raise ValueError("invalid observation window")


@dataclass(frozen=True)
class ReadbackResult:
    processing: ProcessingStatus
    verdict: PropertyVerdict | None
    reason: str
    evidence_sha256: str | None = None
    missing_evidence: tuple[str, ...] = ()
    claim: str = field(default="postcondition_observed", init=False)


def verify_readback(
    raw: bytes | None,
    *,
    contract: ReadbackContract,
    source: SourcePolicy,
    now: int,
) -> ReadbackResult:
    """Verify one source statement about a declared delta at an observed time.

    ESTABLISHED is conditional on the pinned source and trusted clock. It does
    not establish causation, lasting state, authorization or non-bypassability.
    Missing fields are insufficient evidence, not an observed mismatch.
    Malformed/untrusted records receive no property verdict.
    """
    if type(now) is not int or now < 0:
        raise ValueError("trusted clock must supply nonnegative UTC seconds")
    if raw is None:
        return ReadbackResult(
            ProcessingStatus.COMPLETED, PropertyVerdict.NOT_ESTABLISHED,
            "readback_unavailable", missing_evidence=("bound source observation",),
        )
    try:
        envelope = _decode(raw)
        if type(envelope) is not dict or set(envelope) != {"payload", "mac"}:
            raise ValueError("invalid envelope")
        payload, mac = envelope["payload"], envelope["mac"]
        if type(payload) is not dict or set(payload) != _PAYLOAD_KEYS:
            raise ValueError("invalid payload")
        if payload["schema"] != SCHEMA:
            raise ValueError("unsupported schema")
        if type(mac) is not str or len(mac) != 64 or any(c not in "0123456789abcdef" for c in mac):
            raise ValueError("invalid MAC")
        if type(payload["observed_at"]) is not int or payload["observed_at"] < 0:
            raise ValueError("invalid timestamp")
        if type(payload["state"]) is not dict:
            raise ValueError("invalid state")
        for name in (*_BINDINGS, "source_id", "key_id"):
            _identifier(payload[name])
    except (ValueError, TypeError, RecursionError):
        return ReadbackResult(ProcessingStatus.REJECTED_EVIDENCE, None, "malformed_evidence")

    if payload["source_id"] != source.source_id or payload["key_id"] != source.key_id:
        return ReadbackResult(ProcessingStatus.REJECTED_EVIDENCE, None, "untrusted_source")
    expected_mac = hmac.new(source.key, _canonical(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected_mac):
        return ReadbackResult(ProcessingStatus.REJECTED_EVIDENCE, None, "invalid_signature")
    if any(payload[name] != getattr(contract, name) for name in _BINDINGS):
        return ReadbackResult(ProcessingStatus.REJECTED_EVIDENCE, None, "scope_mismatch")

    digest = hashlib.sha256(raw).hexdigest()

    def unresolved(reason: str, missing: tuple[str, ...]) -> ReadbackResult:
        return ReadbackResult(
            ProcessingStatus.COMPLETED, PropertyVerdict.NOT_ESTABLISHED,
            reason, digest, missing,
        )

    observed_at = payload["observed_at"]
    if now > contract.expires_at:
        return unresolved("contract_expired", ("new deployment-approved observation contract",))
    if now < contract.not_before or observed_at < contract.not_before:
        return unresolved("settlement_not_observed", ("observation at or after settlement",))
    if observed_at > now:
        return unresolved("future_observation", ("observation consistent with trusted clock",))
    if now - observed_at > contract.max_age_seconds:
        return unresolved("stale_observation", ("fresh source observation",))

    expected = _decode(contract.expected_json.encode("utf-8"))
    observed = payload["state"]
    missing = tuple(sorted(set(expected) - set(observed)))
    # A present contradicting field is sufficient to refute the conjunction,
    # even when other expected fields are absent. Absence alone is not.
    mismatch = any(
        _canonical(expected[key]) != _canonical(observed[key])
        for key in expected if key in observed
    )
    if mismatch:
        return ReadbackResult(
            ProcessingStatus.COMPLETED, PropertyVerdict.VIOLATED,
            "declared_delta_mismatch", digest,
        )
    if missing:
        return unresolved("declared_fields_unobserved", missing)
    return ReadbackResult(
        ProcessingStatus.COMPLETED, PropertyVerdict.ESTABLISHED,
        "declared_delta_observed", digest,
    )


def read_once(
    reader: Callable[[], bytes | None],
    *,
    contract: ReadbackContract,
    source: SourcePolicy,
    clock: Callable[[], int],
) -> ReadbackResult:
    """Acquire once; sample the deployment clock AFTER acquisition.

    The caller must supply a read-only reader with its own bounded timeout.
    There are no retries or write credentials here. Exceptions are deliberately
    not copied into results: transport errors may contain URLs or credentials.
    """
    try:
        raw = reader()
    except Exception:
        return ReadbackResult(ProcessingStatus.ACQUISITION_FAILED, None, "reader_failed")
    try:
        return verify_readback(raw, contract=contract, source=source, now=clock())
    except Exception:
        return ReadbackResult(ProcessingStatus.VERIFIER_FAILED, None, "verification_failed")
