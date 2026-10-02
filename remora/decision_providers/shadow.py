# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Shadow mode: ask a decision provider, record what it would have done.

A shadow evaluation runs beside a real decision and changes nothing about it.
It puts the question set to the provider, admits the answers through
:func:`~remora.decision_providers.enrich.enrich` on the side, asks the engine
what it would have decided on that enriched observation, and returns a record
holding both decisions. The caller's observation and decision are never
replaced, and nothing here returns an observation the caller could use.

This is how a provider earns evidence before it is allowed to influence
anything. A deployment logs shadow records next to its real decisions and
later joins them with ground truth: a scope drift the provider caught that
the real path let through counts in its favour, and a legitimate call it
would have stopped is a stop the deployment did not pay for. Those two rates,
with latency and cost, are what decide whether the provider is ever wired
into the real path.

Three properties are pinned by ``tests/test_decision_provider_shadow.py``:

* the observation passed in is the observation left behind, field for field
* every failure, including a provider or engine exception, becomes a record
  with ``error`` set, never an exception in the caller's path
* under the execution profile the counterfactual decision is never ACCEPT

Scope (declared, not exhaustive): the evaluation and the record. Where a
deployment calls it, how it samples and where the records go are the
deployment's choices; :class:`JsonlShadowSink` is a minimal local sink.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from remora.decision_providers import DecisionProvider, DecisionQuestion
from remora.decision_providers.enrich import SemanticThresholds, enrich

__all__ = ["JsonlShadowSink", "ShadowRecord", "shadow_evaluate"]


@dataclass(frozen=True, slots=True)
class ShadowRecord:
    """One shadow evaluation, joinable to the real decision by ``proposal_id``."""

    proposal_id: str
    recorded_at: str
    #: The final action the real path took, after any downgrade.
    actual_action: str
    shadow_action: str | None
    #: True when the provider's admission would have produced a different
    #: action than the real one. The interesting rows for a review.
    would_change: bool
    outcome: str | None
    question_set_version: str | None
    model_alias: str | None
    resolved_model: str | None
    state_hash: str | None
    answers: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    latency_ms: float | None = None
    input_tokens: int | None = None
    error: str | None = None
    tenant: str | None = None
    tool_name: str | None = None
    #: The engine's own action before any downgrade the real path applied
    #: afterwards (loop safety, capability). The counterfactual is computed by
    #: the same engine, so this is the like-for-like comparison.
    engine_action: str | None = None
    #: The cuts the answers were admitted against, so the record can be read
    #: on its own, by a reviewer or a later calibration study.
    thresholds: dict[str, float] | None = None
    #: The deployment profile the call was evaluated under (a vertical, a
    #: language, a customer), its language, and its calibration record
    #: (``status`` is ``uncalibrated`` or ``calibrated``; a calibrated
    #: profile names its study and corpus hash).
    profile: str | None = None
    language: str | None = None
    calibration: dict[str, Any] | None = None
    #: A shadow record is never authority. Stated in the record itself.
    authoritative: bool = False

    def as_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["notes"] = list(self.notes)
        return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def shadow_evaluate(
    observation: Any,
    actual_action: Any,
    provider: DecisionProvider,
    *,
    engine: Any,
    state: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    thresholds: SemanticThresholds,
    questions: Sequence[DecisionQuestion],
    proposal_id: str,
    timeout_s: float = 2.0,
    tenant: str | None = None,
    tool_name: str | None = None,
    engine_action: Any = None,
    profile: str | None = None,
    language: str | None = None,
    calibration: Mapping[str, Any] | None = None,
) -> ShadowRecord:
    """Evaluate in shadow and return the record. Never raises, never mutates.

    ``actual_action`` is the action the real path took, recorded as its name.
    ``engine`` is the engine the real path uses, so the counterfactual is
    computed under the same configuration, execution profile included.
    ``state`` may be a callable that builds it, so a state that refuses to be
    built (a credential-shaped key, say) is recorded like any other failure.
    """
    actual = getattr(actual_action, "name", str(actual_action))
    context: dict[str, Any] = {
        "thresholds": {
            "intent_match": thresholds.intent_match,
            "target_matches_request": thresholds.target_matches_request,
            "possible_injection": thresholds.possible_injection,
            "scope_drift": thresholds.scope_drift,
        },
        "profile": profile,
        "language": language,
        "calibration": dict(calibration) if calibration is not None else None,
        "tenant": tenant,
        "tool_name": tool_name,
        "engine_action": (
            getattr(engine_action, "name", str(engine_action)) if engine_action is not None else None
        ),
    }
    started = time.perf_counter()
    try:
        result = enrich(
            observation,
            provider,
            state=state() if callable(state) else state,
            thresholds=thresholds,
            questions=questions,
            timeout_s=timeout_s,
        )
        evidence = result.evidence
        shadow = engine.decide(result.observation).action.name
        answers = {
            a.question_id: {
                "value": a.value,
                "probabilities": a.probabilities,
                "confidence": a.confidence,
                "legend": list(a.legend) if a.legend else None,
            }
            for a in (evidence.answers if evidence else ())
        }
        return ShadowRecord(
            proposal_id=proposal_id,
            recorded_at=_now(),
            actual_action=actual,
            shadow_action=shadow,
            would_change=shadow != actual,
            outcome=result.outcome,
            question_set_version=evidence.question_set_version if evidence else None,
            model_alias=evidence.model_alias if evidence else None,
            resolved_model=evidence.resolved_model if evidence else None,
            state_hash=evidence.state_hash if evidence else None,
            answers=answers,
            notes=result.notes,
            input_tokens=evidence.input_tokens if evidence else None,
            latency_ms=round(evidence.latency_ms if evidence else (time.perf_counter() - started) * 1000.0, 1),
            **context,
        )
    except Exception as exc:  # noqa: BLE001 - a shadow must never break the real path
        return ShadowRecord(
            proposal_id=proposal_id,
            recorded_at=_now(),
            actual_action=actual,
            shadow_action=None,
            would_change=False,
            outcome=None,
            question_set_version=None,
            model_alias=None,
            resolved_model=None,
            state_hash=None,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 1),
            error=f"{type(exc).__name__}: {exc}",
            **context,
        )


class JsonlShadowSink:
    """Append shadow records to a local JSON Lines file, one per line.

    Writes are serialised with a lock so concurrent callers do not interleave
    lines. A write failure is swallowed and counted, for the same reason a
    provider failure is: the shadow must not stop the real path.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.failed_writes = 0
        self._lock = threading.Lock()

    def write(self, record: ShadowRecord) -> None:
        line = json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
        except OSError:
            self.failed_writes += 1

    def find(self, proposal_id: str, tenant: str) -> dict[str, Any] | None:
        """The latest record for ``proposal_id`` that belongs to ``tenant``.

        A record of another tenant is treated as absent, so a lookup can never
        reveal that someone else's proposal exists. Reads the file from the
        end; records are small and one proposal has at most a few.
        """
        try:
            with self._lock:
                lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("proposal_id") == proposal_id:
                return record if record.get("tenant") == tenant else None
        return None
