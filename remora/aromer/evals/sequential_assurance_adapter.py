# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evaluation-layer adapter: AROMER episode records to an RF-14 outcome stream.

This is where ground-truth labels are interpreted. The runtime monitor in
``remora/selective/sequential_assurance.py`` only counts ``event`` flags; it
is scanned by ``scripts/check_no_evaluation_leakage.py`` and must not read
label vocabulary. Mapping a label onto the monitored event therefore lives
here, beside the other AROMER evaluation code.
"""
from __future__ import annotations

from typing import Any, Iterable

from remora.selective.sequential_assurance import AssuranceEpoch, DecisionOutcome

#: Ground-truth label that makes an in-population decision a monitored event.
ADVERSE_LABEL = "harmful"
#: Ground-truth labels that count as resolved; anything else is unresolved.
RESOLVED_LABELS = frozenset({"harmful", "benign"})


def outcomes_from_episode_records(
    records: Iterable[dict[str, Any]],
    *,
    epoch: AssuranceEpoch,
    population: str = "accept",
) -> list[DecisionOutcome]:
    """Build the per-decision stream from exported AROMER episode records.

    Each record is one parsed JSONL row from an episode store export (for
    example ``artifacts/aromer_holdout_episodes.jsonl``). The monitored event
    is the false accept: verdict ACCEPT on an action whose ground truth is
    harmful. ``population`` selects the verdict subset under monitoring;
    "accept" is the operationally relevant one, because only accepted actions
    reach the user without a gate stop.

    Records whose ground truth is not a resolved benign/harmful label come
    out with ``resolved=False`` so the monitor excludes and counts them.
    Verdicts and labels are case-normalized; the store has carried both
    casings. Rows without an ``id`` raise: a decision without identity cannot
    enter a stream whose premise is per-decision identity.

    The epoch comes from the caller, not the records: the committed fixtures
    predate epoch tagging, so the deployment (or the demo script) declares
    which population the stream belongs to.
    """
    outcomes: list[DecisionOutcome] = []
    for i, record in enumerate(records):
        decision_id = record.get("id") or record.get("episode_id")
        if not decision_id:
            raise ValueError(f"record {i} has no id; per-decision identity is required")
        verdict = str(record.get("verdict", "")).strip().lower()
        if population != "all" and verdict != population:
            continue
        truth = str(record.get("ground_truth", "")).strip().lower()
        resolved = truth in RESOLVED_LABELS
        event = resolved and truth == ADVERSE_LABEL
        outcomes.append(
            DecisionOutcome(
                decision_id=str(decision_id),
                event=event,
                loss=float(event),
                epoch=epoch,
                resolved=resolved,
                verdict=verdict,
                cluster_id=record.get("cluster_id"),
                tenant=str(record.get("tenant", "")),
                task_id=str(record.get("task_id", "")),
                dispatch_id=str(record.get("dispatch_id", "")),
                executed=record.get("executed"),
                effect_status=str(record.get("effect_status", "")),
                ground_truth_source=str(record.get("label_source", "")),
                ground_truth_provenance=str(record.get("source", "")),
                policy_sha=str(record.get("policy_sha", "")),
                toolspec_digest=str(record.get("toolspec_digest", "")),
                toolcall_digest=str(record.get("toolcall_digest", "")),
                resolved_at=str(record.get("resolved_at", "")),
                resolver=str(record.get("resolver", "")),
                resolution_provenance=str(record.get("resolution_provenance", "")),
            )
        )
    return outcomes
