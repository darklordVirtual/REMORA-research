# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Closed-loop effect verification (FT-04) — did the approved thing happen?

Everything upstream governs *authorization*: what may run, bound to an
exact payload, under a signed spec. None of it observes the world
afterwards. Without that observation, "executed" means only "the
dispatcher returned without raising" — which is not the same claim, and
the difference is exactly where an ungoverned outcome hides.

The comparison rule is the load-bearing decision (architect review
2026-08-05, frozen in ``schemas/postcondition_contract_v1.yaml``):

    compare the DECLARED DELTA against the version your own write
    produced — never global unchangedness.

A system of record has other legitimate writers. Checking that nothing
else changed makes every concurrent update an EFFECT_MISMATCH, the
mismatch rate becomes dominated by noise, and operators learn to ignore
the signal. A verification nobody trusts is worse than none, because it
still costs attention.

Two refusals to conflate, both encoded in the status set rather than left
to a caller's judgement:

- **not observed is not mismatch.** Failing to READ a result is not
  evidence that the wrong thing happened, and collapsing them would make
  a genuine mismatch indistinguishable from a network timeout;
- **verification never re-executes.** The verifier reads. A side effect
  that may already have happened is the one thing this layer must never
  repeat.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

__all__ = [
    "EffectStatus",
    "EffectVerification",
    "PostconditionContract",
    "verify_declared_delta",
]


class EffectStatus(str, Enum):
    """Five outcomes. Collapsing any pair loses a distinction an operator
    needs in order to choose what to do next."""

    VERIFIED = "EFFECT_VERIFIED"
    MISMATCH = "EFFECT_MISMATCH"
    UNOBSERVABLE = "EFFECT_UNOBSERVABLE"
    VERIFIER_FAILED = "EFFECT_VERIFIER_FAILED"
    UNSUPPORTED = "EFFECT_UNSUPPORTED"

    @property
    def is_terminal(self) -> bool:
        """UNOBSERVABLE and VERIFIER_FAILED mean *we do not know yet*.
        Marking them terminal would freeze an unknown into a verdict."""
        return self in (EffectStatus.VERIFIED, EffectStatus.MISMATCH,
                        EffectStatus.UNSUPPORTED)


@dataclass(frozen=True)
class PostconditionContract:
    """What the deployment declared this action would change."""

    tool_id: str
    reader: str
    target_selector: Mapping[str, Any]
    #: field -> expected value. The DECLARED DELTA and nothing else: fields
    #: absent here are out of scope by construction, not by tolerance.
    expected_fields: Mapping[str, Any]
    comparison_rules: Mapping[str, str] = field(default_factory=dict)
    observation_deadline_seconds: int = 30
    repeatable: bool = True
    evidence_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "target_selector", MappingProxyType(dict(self.target_selector))
        )
        object.__setattr__(
            self, "expected_fields", MappingProxyType(dict(self.expected_fields))
        )
        object.__setattr__(
            self, "comparison_rules", MappingProxyType(dict(self.comparison_rules))
        )


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class EffectVerification:
    """The immutable record of what was observed after an execution."""

    proposal_id: str
    execution_id: str
    tool_id: str
    toolspec_hash: str
    status: EffectStatus
    reason_code: str
    verifier_identity: str
    expected: Mapping[str, Any]
    observed: Mapping[str, Any]
    expected_sha256: str
    observed_sha256: str
    verified_at: str
    detail: str = ""
    evidence_refs: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        proposal_id: str,
        execution_id: str,
        tool_id: str,
        toolspec_hash: str,
        status: EffectStatus,
        reason_code: str,
        verifier_identity: str,
        expected: Mapping[str, Any] | None = None,
        observed: Mapping[str, Any] | None = None,
        detail: str = "",
        evidence_refs: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> "EffectVerification":
        """Both sides are hashed, so a later reader can re-check the
        comparison rather than trust this record's verdict."""
        expected_map = dict(expected or {})
        observed_map = dict(observed or {})
        return cls(
            proposal_id=proposal_id,
            execution_id=execution_id,
            tool_id=tool_id,
            toolspec_hash=toolspec_hash,
            status=status,
            reason_code=reason_code,
            verifier_identity=verifier_identity,
            expected=MappingProxyType(expected_map),
            observed=MappingProxyType(observed_map),
            expected_sha256=_digest(expected_map),
            observed_sha256=_digest(observed_map),
            verified_at=(now or datetime.now(UTC)).isoformat(),
            detail=detail,
            evidence_refs=evidence_refs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "execution_id": self.execution_id,
            "tool_id": self.tool_id,
            "toolspec_hash": self.toolspec_hash,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "verifier_identity": self.verifier_identity,
            "expected": dict(self.expected),
            "observed": dict(self.observed),
            "expected_sha256": self.expected_sha256,
            "observed_sha256": self.observed_sha256,
            "verified_at": self.verified_at,
            "detail": self.detail,
            "evidence_refs": list(self.evidence_refs),
        }


def verify_declared_delta(
    contract: PostconditionContract,
    observed: Mapping[str, Any] | None,
    *,
    proposal_id: str,
    execution_id: str,
    toolspec_hash: str,
    verifier_identity: str,
    now: datetime | None = None,
) -> EffectVerification:
    """Compare the observed object against the DECLARED DELTA only.

    ``observed=None`` means the reader could not see the object. That is
    ``EFFECT_UNOBSERVABLE``, never ``EFFECT_MISMATCH``: not knowing is a
    different fact from knowing it is wrong, and only one of them
    justifies compensation.

    Fields the contract does not name are ignored on purpose. A concurrent
    legitimate write to an unrelated column is not this action's problem,
    and reporting it would train operators to dismiss the signal.
    """
    def _build(status: EffectStatus, reason: str, detail: str = "") -> EffectVerification:
        return EffectVerification.build(
            proposal_id=proposal_id, execution_id=execution_id,
            tool_id=contract.tool_id, toolspec_hash=toolspec_hash,
            status=status, reason_code=reason,
            verifier_identity=verifier_identity,
            expected=contract.expected_fields, observed=observed or {},
            detail=detail, now=now,
        )

    if observed is None:
        return _build(
            EffectStatus.UNOBSERVABLE, "postcondition_object_absent",
            "the reader did not return the target object; the effect status "
            "is unknown, not failed",
        )

    problems: list[str] = []
    for name, expected_value in contract.expected_fields.items():
        rule = contract.comparison_rules.get(name, "exact")
        actual = observed.get(name)
        if rule == "present":
            if name not in observed:
                problems.append(f"{name}: expected to be present")
            continue
        if rule == "absent":
            if name in observed:
                problems.append(f"{name}: expected to be absent")
            continue
        if rule == "version_increment":
            try:
                if actual is None:
                    raise TypeError("absent")
                if not (int(actual) > int(expected_value)):
                    problems.append(
                        f"{name}: expected to advance beyond {expected_value}, "
                        f"got {actual}"
                    )
            except (TypeError, ValueError):
                problems.append(f"{name}: not comparable as a version")
            continue
        if rule == "hash":
            if _digest(actual) != str(expected_value):
                problems.append(f"{name}: content hash differs")
            continue
        if actual != expected_value:
            problems.append(f"{name}: expected {expected_value!r}, got {actual!r}")

    if problems:
        version_only = all("advance beyond" in p for p in problems)
        return _build(
            EffectStatus.MISMATCH,
            "postcondition_version_not_advanced" if version_only
            else "postcondition_field_mismatch",
            "; ".join(problems),
        )
    return _build(EffectStatus.VERIFIED, "postcondition_verified")
