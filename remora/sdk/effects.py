# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The product-facing surface for postconditions and effect verification.

A consuming product must be able to declare what an approved action will
change, verify it against what it observes, and hand the resulting record
back to REMORA — without importing ``remora.governance``,
``remora.policy`` or ``remora.enforcement``. Those are internals we intend
to keep changing; a product coupled to them cannot be upgraded
independently, which defeats the point of having an SDK at all.

So this module owns the vocabulary the product sees. It wraps the
governance implementation rather than re-exporting it: the wrapper is the
contract, and the thing behind it is free to move.

Verification runs **in the product's process**, because the reader holds
the credentials. REMORA never reaches into a customer's system of record
to check on it. What crosses back is the record — who observed what, when,
and how both sides hash — and REMORA stores that as an attestation by the
named verifier. It is evidence of what the verifier claims to have seen,
not an independent proof by REMORA, and the verifier identity in every
record is what keeps that distinction legible to an auditor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

__all__ = [
    "EffectStatus",
    "EffectVerificationView",
    "PostconditionSpec",
    "build_postcondition",
    "content_digest",
    "verify_effect",
]


class EffectStatus(str, Enum):
    """Five outcomes, kept distinct on purpose.

    Collapsing any pair loses a distinction an operator needs in order to
    decide what to do next — above all the difference between *we looked
    and it was wrong* and *we could not look*, only one of which
    justifies compensating an action that may already have happened.
    """

    VERIFIED = "EFFECT_VERIFIED"
    MISMATCH = "EFFECT_MISMATCH"
    UNOBSERVABLE = "EFFECT_UNOBSERVABLE"
    VERIFIER_FAILED = "EFFECT_VERIFIER_FAILED"
    UNSUPPORTED = "EFFECT_UNSUPPORTED"

    @property
    def is_terminal(self) -> bool:
        """UNOBSERVABLE and VERIFIER_FAILED mean *not yet known*. Treating
        them as terminal would close an incident that is still open."""
        return self in (EffectStatus.VERIFIED, EffectStatus.MISMATCH,
                        EffectStatus.UNSUPPORTED)


@dataclass(frozen=True)
class PostconditionSpec:
    """The delta an approved action declares it will produce.

    Only the named fields are compared. Everything else is out of scope by
    construction, not by tolerance: a system of record has other
    legitimate writers, and reporting their changes would make mismatch a
    noise channel that operators learn to ignore.
    """

    tool_id: str
    target_selector: Mapping[str, Any]
    expected_fields: Mapping[str, Any]
    #: field -> ``exact`` | ``hash`` | ``present`` | ``absent`` |
    #: ``version_increment``. Unlisted fields use ``exact``.
    comparison_rules: Mapping[str, str] = field(default_factory=dict)
    reader: str = ""
    observation_deadline_seconds: int = 30

    def __post_init__(self) -> None:
        for name in ("target_selector", "expected_fields", "comparison_rules"):
            object.__setattr__(
                self, name, MappingProxyType(dict(getattr(self, name)))
            )


@dataclass(frozen=True)
class EffectVerificationView:
    """One verification, as the product sees it.

    Both sides are hashed so a later reader can re-derive the comparison
    instead of trusting this record's verdict.
    """

    proposal_id: str
    execution_id: str
    tool_id: str
    toolspec_hash: str
    status: EffectStatus
    reason_code: str
    verifier_identity: str
    expected_sha256: str
    observed_sha256: str
    verified_at: str
    detail: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "EffectVerificationView":
        return cls(
            proposal_id=str(payload.get("proposal_id", "")),
            execution_id=str(payload.get("execution_id", "")),
            tool_id=str(payload.get("tool_id", "")),
            toolspec_hash=str(payload.get("toolspec_hash", "")),
            status=EffectStatus(payload["status"]),
            reason_code=str(payload.get("reason_code", "")),
            verifier_identity=str(payload.get("verifier_identity", "")),
            expected_sha256=str(payload.get("expected_sha256", "")),
            observed_sha256=str(payload.get("observed_sha256", "")),
            verified_at=str(payload.get("verified_at", "")),
            detail=str(payload.get("detail", "")),
            raw=MappingProxyType(dict(payload)),
        )

    def to_dict(self) -> dict[str, Any]:
        """The wire form, ready to hand back to REMORA for recording."""
        return {
            "proposal_id": self.proposal_id,
            "execution_id": self.execution_id,
            "tool_id": self.tool_id,
            "toolspec_hash": self.toolspec_hash,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "verifier_identity": self.verifier_identity,
            "expected_sha256": self.expected_sha256,
            "observed_sha256": self.observed_sha256,
            "verified_at": self.verified_at,
            "detail": self.detail,
        }


def content_digest(value: Any) -> str:
    """The digest a ``hash`` comparison rule expects.

    Exposed because a product that declares a hashed field has to produce
    the same digest REMORA will compute, and guessing the canonical form
    is not a reasonable thing to ask of a consumer.
    """
    from remora.governance.effect_verification import _digest

    return _digest(value)


def build_postcondition(
    *,
    tool_id: str,
    target_selector: Mapping[str, Any],
    expected_fields: Mapping[str, Any],
    comparison_rules: Mapping[str, str] | None = None,
    reader: str = "",
    observation_deadline_seconds: int = 30,
) -> PostconditionSpec:
    """Declare the delta an approved action will produce."""
    return PostconditionSpec(
        tool_id=tool_id,
        target_selector=target_selector,
        expected_fields=expected_fields,
        comparison_rules=comparison_rules or {},
        reader=reader,
        observation_deadline_seconds=observation_deadline_seconds,
    )


def verify_effect(
    spec: PostconditionSpec,
    observed: Mapping[str, Any] | None,
    *,
    proposal_id: str,
    execution_id: str,
    toolspec_hash: str,
    verifier_identity: str,
) -> EffectVerificationView:
    """Compare an observation against the declared delta.

    ``observed=None`` means the reader could not see the object. That is
    ``UNOBSERVABLE``, never ``MISMATCH``: not knowing is a different fact
    from knowing it is wrong, and this function will not guess which.

    It reads only. Re-running the action is the one thing this layer must
    never do, because the side effect may already have happened.
    """
    from remora.governance.effect_verification import (
        PostconditionContract,
        verify_declared_delta,
    )

    contract = PostconditionContract(
        tool_id=spec.tool_id,
        reader=spec.reader,
        target_selector=spec.target_selector,
        expected_fields=spec.expected_fields,
        comparison_rules=spec.comparison_rules,
        observation_deadline_seconds=spec.observation_deadline_seconds,
    )
    record = verify_declared_delta(
        contract, observed,
        proposal_id=proposal_id, execution_id=execution_id,
        toolspec_hash=toolspec_hash, verifier_identity=verifier_identity,
    )
    return EffectVerificationView.from_payload(record.to_dict())
