# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Intent resolution from the graph's own intent namespace.

A governed call has to name the authority it acts under. For the GitHub tool
set that authority is an issue. For a deployment that has only the graph,
there is no ticket system to point at — so the authority lives in the graph
itself, in ``urn:remora:intents``, which agents may not write to.

A task is a subject in that namespace carrying predicates a person wrote:

    subject:    task:onboard-acme
    task_text   "Record that Acme is an active customer with a fibre contract."
    operation   "create"
    resource_type "fact"

``intent_ref`` is that subject. The bundle reads it, and the digest of the
text becomes the authority — so a task rewritten after a call was approved
stops matching, rather than silently standing in for the one a human saw.
"""
from __future__ import annotations

import hashlib
import json
import logging

from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.semantic_bundle import IntentResolution, ResolvedIntent

#: Effects an intent may declare. Frozen deliberately: this is the
#: deterministic side of the boundary, and an extractor that grows to match
#: anything stops discriminating.
_log = logging.getLogger("remora.gateway.intent")

_EFFECTS = frozenset({"read", "create", "update", "delete", "close"})

#: Predicates the goal matcher needs before it can contradict anything.
#:
#: Measured 2026-08-23: a task carrying only task_text, operation and
#: resource_type produced identical decisions for the right task, the wrong
#: task and no task at all — every call reached VERIFY with
#: 'evidence_insufficient', so the intent was decorative. Adding source_spans
#: and action_spans made a write proposed under a read-only task come back as
#: ESCALATE with 'expected_effect_contradicted'.
#:
#: A task without these is not rejected — it still resolves and still sends
#: the call for review — but it cannot cause a contradiction, so it buys
#: nothing beyond a human in the loop.
DISCRIMINATING_PREDICATES = ("source_spans", "action_spans")


def resolve_intent_detailed(intent_ref: str) -> IntentResolution:
    """Resolve a task subject into the authority it carries.

    Returns None when the reference is empty, the task does not exist, or it
    carries no text. None means UNKNOWN rather than permitted: a call with no
    resolvable authority behind it is sent for review, not accepted.
    """
    subject = (intent_ref or "").strip()
    if not subject:
        return IntentResolution(None, "intent_not_authorized")

    # Imported here so the bundle can be built without reaching the graph.
    from deploy.gateway.kg_registry import GraphUnavailable, read_intent

    try:
        task = read_intent(subject)
    except GraphUnavailable:
        return IntentResolution(None, "intent_resolution_failed")
    if not task:
        return IntentResolution(None, "intent_not_authorized")

    task_text = str(task.get("task_text") or "").strip()
    if not task_text:
        return IntentResolution(None, "intent_not_authorized")

    operation = str(task.get("operation") or "").strip().lower()
    if operation not in _EFFECTS:
        # A task that does not say plainly what it wants does not get to imply
        # it. The call still resolves, with no declared effect, and lands in
        # review.
        operation = ""

    resource_type = str(task.get("resource_type") or "fact").strip()

    # The digest covers everything a person wrote, so any edit moves it.
    canonical = json.dumps(task, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    authority = f"graph_intent:{subject}:{digest}"

    targets = task.get("target_entities")
    source_spans = task.get("source_spans")
    action_spans = task.get("action_spans")

    # Recorded rather than enforced: an under-specified task is weaker, not
    # invalid, and refusing it would remove the human review it still gets.
    if not any(task.get(k) for k in DISCRIMINATING_PREDICATES):
        _log.warning(
            "intent %s carries none of %s, so it cannot contradict a "
            "mismatched call; every proposal under it will reach review "
            "with no effect check", subject, DISCRIMINATING_PREDICATES)

    resolved = ResolvedIntent(
        intent=TaskIntent(
            operation=operation,
            resource_type=resource_type,
            requested_effect=operation,
            target_entities=tuple(targets) if isinstance(targets, list)
            else ("target_resource",),
            source_spans=tuple(source_spans) if isinstance(source_spans, list)
            else (),
            action_spans=tuple(action_spans) if isinstance(action_spans, list)
            else (),
            proposed_by=authority),
        task_text=task_text,
        authority=authority)
    return IntentResolution(resolved, "resolved")


def resolve_intent(intent_ref: str):  # -> ResolvedIntent | None
    """Backward-compatible public resolver."""
    return resolve_intent_detailed(intent_ref).resolved
