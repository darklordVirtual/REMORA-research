# Author: Stian Skogbrott
# License: Apache-2.0
"""Machine-verifiable governance invariants for REMORA.

REMORA's safety guarantees are only meaningful if they can be checked
programmatically. This module expresses each policy guarantee as a typed
invariant that can be evaluated against any (observation, decision) pair —
making them testable, auditable, and citeable.

Invariants
----------
Each ``PolicyInvariant`` defines:

- ``name``: a unique human-readable identifier
- ``description``: the safety property in plain English
- ``check(obs, report)``: returns ``InvariantResult`` (passed/violated + evidence)

Core invariants included
------------------------
CRITICAL_NEVER_AUTONOMOUSLY_ACCEPTED
    A critical-risk action must never receive ``ACCEPT`` without human review.

ADVERSARIAL_ALWAYS_ESCALATED
    Any action with ``adversarial_detected=True`` must produce ``ESCALATE``.

ESCALATE_IMPLIES_HUMAN_REVIEW
    Every ``ESCALATE`` decision must set ``human_review_required=True``.

COUNTERFACTUAL_FAILURE_BLOCKED
    A failed counterfactual check must never produce ``ACCEPT`` or ``VERIFY``.

EVIDENCE_CONTRADICTION_NOT_ACCEPTED
    Positive ``evidence_contradictions`` must not produce ``ACCEPT``.

DISORDERED_WITHOUT_EVIDENCE_NOT_ACCEPTED
    Disordered phase + no evidence must not produce ``ACCEPT``.

POLICY_VERSION_ALWAYS_SET
    Every decision must carry a non-empty ``policy_version``.

Usage
-----
    from remora.policy.invariants import check_all_invariants, CORE_INVARIANTS
    from remora import RemoraDecisionEngine, PolicyObservation

    engine = RemoraDecisionEngine()
    obs = PolicyObservation(question="...", adversarial_detected=True)
    report = engine.decide(obs)

    results = check_all_invariants(obs, report)
    for r in results:
        if r.violated:
            raise AssertionError(f"Invariant violated: {r.invariant_name}: {r.evidence}")

Property-based testing::

    from remora.policy.invariants import assert_invariants
    # Raises InvariantViolationError on first violation
    assert_invariants(obs, report)

Extending
---------
    from remora.policy.invariants import PolicyInvariant, InvariantResult

    class NoLowTrustAccept(PolicyInvariant):
        name = "LOW_TRUST_NOT_ACCEPTED"
        description = "trust_score < 0.3 must not produce ACCEPT"

        def check(self, obs, report):
            if obs.trust_score is not None and obs.trust_score < 0.3:
                if report.action == DecisionAction.ACCEPT:
                    return InvariantResult(
                        invariant_name=self.name,
                        passed=False,
                        violated=True,
                        evidence=f"trust_score={obs.trust_score} but action=ACCEPT",
                    )
            return InvariantResult(invariant_name=self.name, passed=True, violated=False)
"""
from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass

from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReport

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InvariantResult:
    """Outcome of checking one invariant against one (observation, decision) pair."""

    invariant_name: str
    passed: bool
    violated: bool
    evidence: str = ""

    def __str__(self) -> str:
        status = "PASSED" if self.passed else "VIOLATED"
        suffix = f" — {self.evidence}" if self.evidence else ""
        return f"[{status}] {self.invariant_name}{suffix}"


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class InvariantViolationError(RuntimeError):
    """Raised by ``assert_invariants()`` when one or more invariants are violated."""

    def __init__(self, violations: list[InvariantResult]) -> None:
        lines = "\n  ".join(str(v) for v in violations)
        super().__init__(f"{len(violations)} invariant(s) violated:\n  {lines}")
        self.violations = violations


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class PolicyInvariant(abc.ABC):
    """Abstract base for a single governance invariant."""

    #: Unique machine-readable name (UPPER_SNAKE_CASE)
    name: str
    #: Human-readable description of the safety property
    description: str

    @abc.abstractmethod
    def check(
        self,
        obs: PolicyObservation,
        report: DecisionReport,
    ) -> InvariantResult:
        """Evaluate the invariant.

        Returns an :class:`InvariantResult` with ``passed=True`` when the
        invariant holds, ``violated=True`` when it does not.
        """


# ---------------------------------------------------------------------------
# Core invariants
# ---------------------------------------------------------------------------

class _CriticalNeverAutonomouslyAccepted(PolicyInvariant):
    name = "CRITICAL_NEVER_AUTONOMOUSLY_ACCEPTED"
    description = (
        "A critical-risk action must never receive ACCEPT without human review. "
        "Autonomous execution of critical actions is architecturally forbidden."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        if obs.risk_tier == "critical" and report.action == DecisionAction.ACCEPT:
            if not report.human_review_required:
                return InvariantResult(
                    invariant_name=self.name,
                    passed=False,
                    violated=True,
                    evidence=(
                        "risk_tier=critical produced action=ACCEPT "
                        "with human_review_required=False"
                    ),
                )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


class _AdversarialAlwaysEscalated(PolicyInvariant):
    name = "ADVERSARIAL_ALWAYS_ESCALATED"
    description = (
        "Any action with adversarial_detected=True must produce ESCALATE. "
        "The admission firewall is a hard block with no bypass."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        if obs.adversarial_detected and report.action != DecisionAction.ESCALATE:
            return InvariantResult(
                invariant_name=self.name,
                passed=False,
                violated=True,
                evidence=(
                    f"adversarial_detected=True but action={report.action.value} "
                    f"(expected ESCALATE)"
                ),
            )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


class _EscalateImpliesHumanReview(PolicyInvariant):
    name = "ESCALATE_IMPLIES_HUMAN_REVIEW"
    description = (
        "Every ESCALATE decision must set human_review_required=True. "
        "An escalated action that does not route to human review is a governance gap."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        if report.action == DecisionAction.ESCALATE and not report.human_review_required:
            return InvariantResult(
                invariant_name=self.name,
                passed=False,
                violated=True,
                evidence="action=ESCALATE but human_review_required=False",
            )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


class _CounterfactualFailureBlocked(PolicyInvariant):
    name = "COUNTERFACTUAL_FAILURE_BLOCKED"
    description = (
        "A failed counterfactual check (counterfactual_passed=False) must never "
        "produce ACCEPT or VERIFY. It must produce ESCALATE."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        if obs.counterfactual_passed is False:
            if report.action in (DecisionAction.ACCEPT, DecisionAction.VERIFY):
                return InvariantResult(
                    invariant_name=self.name,
                    passed=False,
                    violated=True,
                    evidence=(
                        f"counterfactual_passed=False but action={report.action.value} "
                        f"(expected ESCALATE)"
                    ),
                )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


class _EvidenceContradictionNotAccepted(PolicyInvariant):
    name = "EVIDENCE_CONTRADICTION_NOT_ACCEPTED"
    description = (
        "Positive evidence_contradictions must not produce ACCEPT. "
        "Contradicted evidence invalidates autonomous execution."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        contradictions = obs.evidence_contradictions
        if contradictions is not None and contradictions > 0:
            if report.action == DecisionAction.ACCEPT:
                return InvariantResult(
                    invariant_name=self.name,
                    passed=False,
                    violated=True,
                    evidence=(
                        f"evidence_contradictions={contradictions} "
                        f"but action=ACCEPT"
                    ),
                )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


class _DisorderedWithoutEvidenceNotAccepted(PolicyInvariant):
    name = "DISORDERED_WITHOUT_EVIDENCE_NOT_ACCEPTED"
    description = (
        "Disordered phase + no evidence answer must not produce ACCEPT. "
        "Disordered consensus state reflects insufficient oracle agreement."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        if (
            obs.phase == "disordered"
            and obs.evidence_action != "answer"
            and report.action == DecisionAction.ACCEPT
        ):
            return InvariantResult(
                invariant_name=self.name,
                passed=False,
                violated=True,
                evidence=(
                    f"phase=disordered, evidence_action={obs.evidence_action!r} "
                    f"but action=ACCEPT"
                ),
            )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


class _PolicyVersionAlwaysSet(PolicyInvariant):
    name = "POLICY_VERSION_ALWAYS_SET"
    description = (
        "Every decision must carry a non-empty policy_version. "
        "Unversioned decisions cannot be reliably audited or reproduced."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        if not report.policy_version or report.policy_version.strip() == "":
            return InvariantResult(
                invariant_name=self.name,
                passed=False,
                violated=True,
                evidence="policy_version is empty or missing",
            )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


class _VerifyImpliesEvidenceOrHumanReview(PolicyInvariant):
    name = "VERIFY_IMPLIES_FOLLOW_UP"
    description = (
        "Every VERIFY decision must require either evidence_required=True "
        "or human_review_required=True. A VERIFY with no follow-up is a dead end."
    )

    def check(self, obs: PolicyObservation, report: DecisionReport) -> InvariantResult:
        if report.action == DecisionAction.VERIFY:
            if not report.evidence_required and not report.human_review_required:
                return InvariantResult(
                    invariant_name=self.name,
                    passed=False,
                    violated=True,
                    evidence=(
                        "action=VERIFY but both evidence_required=False "
                        "and human_review_required=False"
                    ),
                )
        return InvariantResult(invariant_name=self.name, passed=True, violated=False)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: The canonical set of core invariants. Import and extend as needed.
CORE_INVARIANTS: tuple[PolicyInvariant, ...] = (
    _CriticalNeverAutonomouslyAccepted(),
    _AdversarialAlwaysEscalated(),
    _EscalateImpliesHumanReview(),
    _CounterfactualFailureBlocked(),
    _EvidenceContradictionNotAccepted(),
    _DisorderedWithoutEvidenceNotAccepted(),
    _PolicyVersionAlwaysSet(),
    _VerifyImpliesEvidenceOrHumanReview(),
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def check_all_invariants(
    obs: PolicyObservation,
    report: DecisionReport,
    *,
    invariants: Sequence[PolicyInvariant] = CORE_INVARIANTS,
) -> list[InvariantResult]:
    """Evaluate all invariants and return the full result list.

    Parameters
    ----------
    obs:
        The observation that produced ``report``.
    report:
        The decision report to check.
    invariants:
        Invariant set to evaluate (defaults to ``CORE_INVARIANTS``).

    Returns
    -------
    list[InvariantResult]
        One result per invariant. Check ``any(r.violated for r in results)``
        to detect violations.
    """
    return [inv.check(obs, report) for inv in invariants]


def assert_invariants(
    obs: PolicyObservation,
    report: DecisionReport,
    *,
    invariants: Sequence[PolicyInvariant] = CORE_INVARIANTS,
) -> None:
    """Check all invariants and raise :exc:`InvariantViolationError` on failure.

    Designed for use in production code and property-based tests::

        assert_invariants(obs, engine.decide(obs))

    Parameters
    ----------
    obs, report:
        As in :func:`check_all_invariants`.
    invariants:
        Invariant set (defaults to ``CORE_INVARIANTS``).

    Raises
    ------
    InvariantViolationError
        When one or more invariants are violated.
    """
    results = check_all_invariants(obs, report, invariants=invariants)
    violations = [r for r in results if r.violated]
    if violations:
        raise InvariantViolationError(violations)


def invariant_summary(
    obs: PolicyObservation,
    report: DecisionReport,
    *,
    invariants: Sequence[PolicyInvariant] = CORE_INVARIANTS,
) -> dict[str, bool]:
    """Return ``{invariant_name: passed}`` mapping for quick inspection."""
    return {
        r.invariant_name: r.passed
        for r in check_all_invariants(obs, report, invariants=invariants)
    }
