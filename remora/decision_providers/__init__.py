#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Typed semantic judgment from an external model, admitted as evidence only.

A decision provider answers narrow, typed questions about a proposed action:
does the call match the declared intent, is the target the one the request
names, how reversible is the effect. Providers of this shape return calibrated
probabilities rather than free text, which is what makes their output usable
by code instead of by a parser.

What this module exists to prevent
----------------------------------

The policy engine reads two classes of input that behave very differently
under :mod:`remora.policy.whatif`. Model signals (oracle trust, consensus
phase, evidence confidence, quorum, temperature) cannot reach ACCEPT under the
execution profile; that is pinned by
``tests/test_policy_whatif.py::test_execution_profile_never_lets_model_signals_accept``.
Deployment facts can, which is the point of a deployment declaring them.

The danger in wiring an external semantic model to this engine is therefore
specific, and it is not the model being wrong. It is the mapping. The
questions such a model answers best are ``intent_match``,
``target_matches_request`` and ``scope_drift``, and the observation fields
that sound like the place to put those answers are ``tool_matches_goal``,
``expected_effect_matches`` and ``argument_values_grounded``. Those three are
deployment facts. Routing a model answer into one of them would hand the model
the ability to reach ACCEPT, silently, through a field the invariant above
does not cover.

:func:`project` is the only supported way evidence reaches an observation, and
it writes model-signal fields exclusively. The field set is declared here and
pinned against the lever catalogue by
``tests/test_decision_providers.py``, so the two cannot drift apart.

Relationship to the two neighbouring abstractions, stated so a third does not
grow by accident:

``remora.oracles``
    free-text completions from language models, combined by consensus. A
    provider here returns typed values with probabilities and is queried one
    question at a time.

``remora.evidence.provider``
    retrieval. It answers what the record says, not what a model judges.

Scope (declared, not exhaustive): this module defines the contract, the
evidence record and the projection. It ships no network adapter. A hosted
provider is an adapter that implements :class:`DecisionProvider`, and the
security properties here hold for any adapter because they are properties of
the projection rather than of the provider.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Literal, Mapping, Protocol, Sequence, runtime_checkable

__all__ = [
    "PROJECTABLE_FIELDS",
    "DecisionAnswer",
    "DecisionEvidence",
    "DecisionProvider",
    "DecisionProviderError",
    "DecisionQuestion",
    "DeterministicDecisionProvider",
    "QuestionKind",
    "evidence_fingerprint",
    "project",
]


class QuestionKind(Enum):
    """The three answer shapes a provider may return.

    Named for the shape of the answer rather than for any vendor's term, so an
    adapter translates once at its own boundary.
    """

    #: One option from a declared, closed set.
    CHOICE = "choice"
    #: A position on a declared ordered legend, in the legend's own units.
    SCORE = "score"
    #: The probability that a proposition holds. See :class:`DecisionAnswer`.
    BOOLEAN = "boolean"


class DecisionProviderError(RuntimeError):
    """A provider failed to produce an answer.

    Raised by adapters on timeout, transport failure, schema mismatch or an
    unresolvable model version. Callers must treat it as absence of evidence,
    never as a favourable answer.
    """


@dataclass(frozen=True, slots=True)
class DecisionQuestion:
    """One narrow question about a proposed action."""

    id: str
    kind: QuestionKind
    instructions: str
    #: Required for CHOICE, ignored otherwise.
    options: tuple[str, ...] = ()
    #: Ordered labels for SCORE, defining the scale the answer indexes into.
    legend: tuple[str, ...] = ()
    #: Per-option guidance a provider may be given. Keys must be the options
    #: for CHOICE, and "true"/"false" for BOOLEAN.
    criteria: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.kind is QuestionKind.CHOICE and len(self.options) < 2:
            raise ValueError(f"choice question {self.id!r} needs at least two options")
        if self.kind is not QuestionKind.CHOICE and self.options:
            raise ValueError(f"question {self.id!r} declares options but is not a choice")
        if self.kind is QuestionKind.SCORE and len(self.legend) < 2:
            raise ValueError(f"score question {self.id!r} needs a legend of at least two labels")
        if self.kind is not QuestionKind.SCORE and self.legend:
            raise ValueError(f"question {self.id!r} declares a legend but is not a score")


@dataclass(frozen=True, slots=True)
class DecisionAnswer:
    """One provider answer, with whatever uncertainty the provider reports.

    ``value`` is read according to the question kind, and two of the three are
    not what a first reading suggests:

    CHOICE
        the chosen option, a member of the question's declared options.

    BOOLEAN
        **the probability that the answer is true**, not a bool. Providers of
        this shape return a probability, and deciding where to cut it is a
        policy question with a threshold that belongs in a reviewed
        configuration. :meth:`as_bool` therefore demands the threshold rather
        than assuming one, so a 0.51 and a 0.99 cannot silently become the
        same answer.

    SCORE
        a position on ``legend``, in the legend's own units, not normalised to
        [0, 1]. A provider returning 1.04 against a three-point legend means
        slightly past the middle label. Normalising it here would discard the
        labels that give the number its meaning.
    """

    question_id: str
    value: str | float | bool
    #: Per-option or per-position probabilities, or None when none is reported.
    probabilities: Mapping[str, float] | None = None
    #: Provider-reported confidence in [0, 1], or None.
    confidence: float | None = None
    #: The ordered labels a SCORE value indexes into, when the provider reports them.
    legend: tuple[str, ...] | None = None

    def as_bool(self, *, threshold: float) -> bool:
        """Cut a BOOLEAN probability at an explicitly supplied threshold.

        There is no default. A threshold is a policy decision, and a default
        here would make it invisible in exactly the records meant to show it.
        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0, 1], got {threshold}")
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise TypeError(
                f"answer {self.question_id!r} is not a probability; as_bool applies to "
                "BOOLEAN answers only"
            )
        return float(self.value) >= threshold


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """What a provider returned, recorded so the answer can be re-examined.

    The field set is deliberately closed and contains nothing an authority path
    reads. There is no grant, no capability, no credential, no tool identity,
    no tenant and no actor here, and adding one would be the defect this module
    exists to prevent rather than a feature.

    ``model_alias`` and ``resolved_model`` are separate because an alias can be
    repointed at a new model without any code change, which moves every
    threshold that was calibrated against the old one. Recording only the alias
    would make that drift invisible in the audit record.
    """

    provider: str
    model_alias: str
    resolved_model: str
    question_set_version: str
    state_hash: str
    response_hash: str
    answers: tuple[DecisionAnswer, ...]
    latency_ms: float

    #: Never anything else. Present so the record states its own status rather
    #: than relying on a reader knowing this module's rules.
    authoritative: Literal[False] = False

    def answer(self, question_id: str) -> DecisionAnswer | None:
        for candidate in self.answers:
            if candidate.question_id == question_id:
                return candidate
        return None


@runtime_checkable
class DecisionProvider(Protocol):
    """A source of typed semantic judgment.

    An implementation must raise :class:`DecisionProviderError` rather than
    returning a favourable default when it cannot answer. Absence of evidence
    and evidence of safety are different states, and only the caller's policy
    may decide what absence means.
    """

    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Sequence[DecisionQuestion],
        timeout_s: float,
    ) -> DecisionEvidence: ...


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def evidence_fingerprint(state: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical state a provider was shown.

    Recorded so an answer can be re-examined against the exact input that
    produced it. The state sent to a provider should already be minimised; this
    hashes what was sent, not what was held back.
    """
    return hashlib.sha256(_canonical(dict(state))).hexdigest()


#: The observation fields :func:`project` may write.
#:
#: Exactly the model-signal class of ``remora.policy.whatif.LEVERS``. Declared
#: here rather than imported to keep this module free of the engine, and pinned
#: against the catalogue by a test so the two cannot drift.
PROJECTABLE_FIELDS: frozenset[str] = frozenset({
    "evidence_action",
    "evidence_confidence",
    "oracle_failures",
    "phase",
    "temperature",
    "trust_score",
    "valid_oracle_count",
})


def project(observation: Any, assignments: Mapping[str, Any]) -> Any:
    """Apply provider-derived signals to an observation, model signals only.

    ``assignments`` names observation fields and the values to set. A field
    outside :data:`PROJECTABLE_FIELDS` is refused rather than dropped: a caller
    trying to write a deployment fact from model output has made a security
    mistake, and silently ignoring it would leave that caller believing the
    signal had been applied.

    Returns a new observation; the input is not mutated.
    """
    stray = sorted(set(assignments) - PROJECTABLE_FIELDS)
    if stray:
        raise ValueError(
            "a decision provider may only supply model signals; refusing to write "
            f"{stray} from provider output. Those fields are deployment facts, and "
            "a deployment fact reached by model output can reach ACCEPT."
        )
    unknown = sorted(
        name
        for name in assignments
        if name not in {f.name for f in dataclasses.fields(observation)}
    )
    if unknown:
        raise ValueError(f"observation has no such field: {unknown}")
    return replace(observation, **dict(assignments))


class DeterministicDecisionProvider:
    """A provider with no network and no model, for tests and for fail-closed runs.

    Answers come from a fixed table keyed by question id. A question the table
    does not cover raises, because inventing an answer is the failure mode this
    whole module is shaped against.
    """

    provider_name = "deterministic"

    def __init__(
        self,
        answers: Mapping[str, str | float | bool],
        *,
        question_set_version: str = "deterministic-v1",
        confidence: float | None = 1.0,
    ) -> None:
        self._answers = dict(answers)
        self._question_set_version = question_set_version
        self._confidence = confidence

    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Sequence[DecisionQuestion],
        timeout_s: float,
    ) -> DecisionEvidence:
        del timeout_s  # no transport, nothing to time out
        answered: list[DecisionAnswer] = []
        for question in questions:
            if question.id not in self._answers:
                raise DecisionProviderError(
                    f"no deterministic answer declared for question {question.id!r}"
                )
            answered.append(
                DecisionAnswer(
                    question_id=question.id,
                    value=self._answers[question.id],
                    probabilities=None,
                    confidence=self._confidence,
                )
            )
        answers = tuple(answered)
        return DecisionEvidence(
            provider=self.provider_name,
            model_alias=self.provider_name,
            resolved_model=self._question_set_version,
            question_set_version=self._question_set_version,
            state_hash=evidence_fingerprint(state),
            response_hash=hashlib.sha256(
                _canonical([dataclasses.asdict(a) for a in answers])
            ).hexdigest(),
            answers=answers,
            latency_ms=0.0,
        )
