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

from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.semantic_bundle import ResolvedIntent

#: Effects an intent may declare. Frozen deliberately: this is the
#: deterministic side of the boundary, and an extractor that grows to match
#: anything stops discriminating.
_EFFECTS = frozenset({"read", "create", "update", "delete", "close"})


def resolve_intent(intent_ref: str):  # -> ResolvedIntent | None
    """Resolve a task subject into the authority it carries.

    Returns None when the reference is empty, the task does not exist, or it
    carries no text. None means UNKNOWN rather than permitted: a call with no
    resolvable authority behind it is sent for review, not accepted.
    """
    subject = (intent_ref or "").strip()
    if not subject:
        return None

    # Imported here so the bundle can be built without reaching the graph.
    from deploy.gateway.kg_registry import GraphUnavailable, read_intent

    try:
        task = read_intent(subject)
    except GraphUnavailable:
        return None
    if not task:
        return None

    task_text = str(task.get("task_text") or "").strip()
    if not task_text:
        return None

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

    return ResolvedIntent(
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
