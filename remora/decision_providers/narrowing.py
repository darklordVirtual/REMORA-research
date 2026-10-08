# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A semantic narrowing guard: a provider may reduce authority, never create it (issue #753, step 2).

``enrich()`` mixes two behaviours: a favourable signal (intent and target match,
admitted as evidence) and a narrowing signal (an injection answer past its cut,
which raises ``adversarial_detected``). In shadow mode both are fine, because
nothing they produce is authoritative. A guard that runs before a live decision
must be smaller than that. This module is that smaller contract:

* It asks only the injection questions of a pinned question set.
* It writes only through :func:`remora.decision_providers.project_narrowing`,
  so the only change it can make to an observation is a flag in
  :data:`remora.decision_providers.NARROWING_FLAGS` going from False to True.
* It never calls :func:`remora.decision_providers.project`; no favourable
  evidence, deployment fact, grant, token, lease or route can come out of it.
* A provider that fails, times out, reports another model or another question
  set, or answers outside the declared questions is reported as
  ``provider_unavailable``. That is never read as a clean assessment: what a
  decision does when a required guard is unavailable belongs to the
  deterministic policy layer, and :attr:`GuardResult.clean` stays False.

Activation is per tenant and refused unless the profile is calibrated, names
its study and corpus hash, and pins the model and question-set versions the
calibration was made with. An uncalibrated profile may run in shadow; it may
never be used here.

LIBRARY ONLY: nothing in ``servers/`` or ``remora/execution/`` calls this
module. Wiring it before a live decision is step 3 of #753 and waits for a
calibrated profile (NEGATIVE_RESULTS.md §74).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Mapping

from remora.decision_providers import NARROWING_FLAGS, DecisionProvider, project_narrowing
from remora.decision_providers.enrich import _probability
from remora.decision_providers.questions import (
    INJECTION_QUESTIONS_V2_1,
    QUESTION_SET_VERSION_V2_1,
    REMORA_QUESTIONS_V2_1,
)

__all__ = [
    "GUARD_QUESTION_SETS",
    "GuardActivation",
    "GuardOutcome",
    "GuardResult",
    "SemanticNarrowingGuard",
]

#: Question sets a guard may run, with the injection questions it asks from each.
GUARD_QUESTION_SETS: Mapping[str, tuple[str, ...]] = {
    QUESTION_SET_VERSION_V2_1: INJECTION_QUESTIONS_V2_1,
}
_QUESTIONS_BY_SET = {QUESTION_SET_VERSION_V2_1: REMORA_QUESTIONS_V2_1}

#: A pinned model version, e.g. ``jev-1.13.0``. ``jev-latest`` and other aliases are refused.
_PINNED_MODEL = re.compile(r"^[a-z][a-z0-9-]*-\d+\.\d+\.\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
#: Upper bound on a synchronous guard call, in milliseconds.
MAX_TIMEOUT_MS = 10_000


class GuardOutcome(str, Enum):
    NOT_EVALUATED = "not_evaluated"            # tenant not opted in, or no server-resolved intent
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NARROWED = "narrowed"                      # a flag was raised
    NO_NARROWING = "no_narrowing"              # the provider answered and nothing passed its cut


@dataclass(frozen=True)
class GuardActivation:
    """One tenant's guard configuration. Construction refuses anything unsafe."""

    tenant: str
    model_version: str
    question_set_version: str
    thresholds: Mapping[str, float]
    calibration: Mapping[str, Any]
    timeout_ms: int
    execution_profile: bool

    def __post_init__(self) -> None:
        if not self.tenant:
            raise ValueError("guard activation needs a tenant")
        if self.execution_profile is not True:
            raise ValueError("a semantic guard runs only under the execution profile")
        if not _PINNED_MODEL.match(self.model_version) or "latest" in self.model_version:
            raise ValueError(f"guard model must be a pinned version, not {self.model_version!r}")
        asked = GUARD_QUESTION_SETS.get(self.question_set_version)
        if asked is None:
            raise ValueError(f"question set {self.question_set_version!r} is not allowed for a guard")
        if set(self.thresholds) != set(asked):
            raise ValueError(f"guard thresholds must be exactly {sorted(asked)}; no threshold has a default")
        for name, value in self.thresholds.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 < float(value) < 1.0:
                raise ValueError(f"threshold {name!r} must be a probability strictly between 0 and 1")
        if not isinstance(self.timeout_ms, int) or isinstance(self.timeout_ms, bool) \
                or not 0 < self.timeout_ms <= MAX_TIMEOUT_MS:
            raise ValueError(f"guard timeout must be 1..{MAX_TIMEOUT_MS} ms")
        cal = self.calibration
        if cal.get("status") != "calibrated":
            raise ValueError("an uncalibrated profile may run in shadow, never as a guard")
        missing = sorted(k for k in ("study", "corpus_sha256", "language", "vertical") if not cal.get(k))
        if missing:
            raise ValueError(f"guard calibration must name {missing}")
        if not _SHA256.match(str(cal["corpus_sha256"])):
            raise ValueError("calibration corpus_sha256 must be a SHA-256 hex digest")
        if cal.get("model_version") != self.model_version:
            raise ValueError("the guard model differs from the model the calibration was made with")
        if cal.get("question_set_version") != self.question_set_version:
            raise ValueError("the guard question set differs from the one the calibration was made with")
        if dict(cal.get("thresholds", {})) != dict(self.thresholds):
            raise ValueError("the guard thresholds differ from the calibrated thresholds")


@dataclass(frozen=True)
class GuardResult:
    outcome: GuardOutcome
    observation: Any
    flags_raised: tuple[str, ...] = ()
    reason: str = ""
    model_version: str | None = None
    question_set_version: str | None = None
    answers: Mapping[str, float] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        """Never True. Not narrowing is not evidence that the call is safe."""
        return False

    @property
    def provider_available(self) -> bool:
        return self.outcome in (GuardOutcome.NARROWED, GuardOutcome.NO_NARROWING)


class SemanticNarrowingGuard:
    """Ask the pinned injection questions; raise a narrowing flag or change nothing."""

    def __init__(self, activations: Mapping[str, GuardActivation], provider: DecisionProvider) -> None:
        for tenant, activation in activations.items():
            if activation.tenant != tenant:
                raise ValueError(f"activation for {tenant!r} names tenant {activation.tenant!r}")
        self._activations = dict(activations)
        self._provider = provider

    def evaluate(self, observation: Any, *, tenant: str, state: Mapping[str, Any],
                 intent_authority_present: bool | None) -> GuardResult:
        activation = self._activations.get(tenant)
        if activation is None:
            return GuardResult(GuardOutcome.NOT_EVALUATED, observation, reason="tenant_not_opted_in")
        if intent_authority_present is not True:
            return GuardResult(GuardOutcome.NOT_EVALUATED, observation, reason="no_server_resolved_intent")

        asked = GUARD_QUESTION_SETS[activation.question_set_version]
        questions = tuple(q for q in _QUESTIONS_BY_SET[activation.question_set_version] if q.id in asked)

        def unavailable(reason: str, model: str | None = None, qset: str | None = None) -> GuardResult:
            return GuardResult(GuardOutcome.PROVIDER_UNAVAILABLE, observation, reason=reason,
                               model_version=model, question_set_version=qset)

        try:
            evidence = self._provider.evaluate(state=state, questions=questions,
                                               timeout_s=activation.timeout_ms / 1000)
        except Exception as exc:  # noqa: BLE001 - any failure is an explicit, non-clean outcome
            return unavailable(f"provider_error:{type(exc).__name__}")
        if evidence.resolved_model != activation.model_version:
            return unavailable("model_version_mismatch", model=evidence.resolved_model)
        if evidence.question_set_version != activation.question_set_version:
            return unavailable("question_set_mismatch", qset=evidence.question_set_version)
        stray = sorted({a.question_id for a in evidence.answers} - set(asked))
        if stray:
            return unavailable("answers_outside_the_declared_questions")

        answers = {q: p for q in asked if (p := _probability(evidence, q)) is not None}
        model, qset = evidence.resolved_model, evidence.question_set_version
        crossed = sorted(q for q, p in answers.items() if p >= activation.thresholds[q])
        if not crossed:
            return GuardResult(GuardOutcome.NO_NARROWING, observation,
                               reason="no injection answer passed its threshold",
                               model_version=model, question_set_version=qset, answers=answers)
        narrowed = project_narrowing(observation, {"adversarial_detected": True})
        _assert_narrowing_only(observation, narrowed)
        return GuardResult(GuardOutcome.NARROWED, narrowed, flags_raised=("adversarial_detected",),
                           reason="past threshold: " + ",".join(crossed),
                           model_version=model, question_set_version=qset, answers=answers)


def _assert_narrowing_only(before: Any, after: Any) -> None:
    """The guard's whole effect: narrowing flags raised, nothing else touched."""
    for f in fields(before):
        old, new = getattr(before, f.name), getattr(after, f.name)
        if old == new:
            continue
        if f.name not in NARROWING_FLAGS or new is not True:
            raise AssertionError(f"semantic guard changed {f.name!r}; it may only raise {sorted(NARROWING_FLAGS)}")
