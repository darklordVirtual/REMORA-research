# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Research-profile semantic bundle for the governed execution API (SHELF-020).

Deployment-configuration module for the ``REMORA_SEMANTIC_BUNDLE_MODULE``
contract (see ``remora/toolcall/semantic_bundle.py``). It declares the
task-tool semantics for exactly the tools the research tool registry
(``servers/tool_registry_research.py``) exposes, so the assess path judges the
same tools the dispatcher can execute:

  store_artifact  — declared mutating create on ``artifact``
  read_telemetry  — declared read on ``telemetry``

Nothing here is inferred from a tool's name; every contract field is written
from the tool's documented behavior (the module docstrings in
``tool_registry_research.py``), which is the deployment-author position the
contract layer requires.

Intent source (``resolve_intent``): an approved-workflow-template file named
by ``REMORA_INTENT_SOURCE_FILE`` — a JSON object mapping ``intent_ref`` to the
intent fields plus the task text. This is the "approved workflow template"
primary source of ``docs/research/task_intent_authority_v1.md`` §2.1: the file
is deployment-controlled and version-locked, and the authority string binds
the resolved intent to the exact file content
(``workflow_template:<sha256-of-file>``). Without the variable, no intent
resolves and the goal-match fields stay ``None`` — authoritative absence,
never a fabricated signal.

Enable with: ``REMORA_SEMANTIC_BUNDLE_MODULE=servers.semantic_bundle_research``
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from remora.toolcall.routing.compatibility import StateIndex
from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature
from remora.toolcall.semantic_bundle import ResolvedIntent, SemanticBundle


def build_semantic_bundle() -> SemanticBundle:
    registry = ToolRegistry(signatures={
        "store_artifact": ToolSignature(
            name="store_artifact",
            required_params=("artifact_id", "content"),
            effect="write",
        ),
        "read_telemetry": ToolSignature(
            name="read_telemetry",
            required_params=(),
            effect="read",
        ),
    })
    contracts = ToolContractRegistry([
        ToolContract(
            tool="store_artifact",
            capability="artifact_storage",
            effect="create",
            resource_type="artifact",
            mutation=True,
            argument_roles={"artifact_id": "target_resource"},
            state_delta={"artifact.stored": "true"},
        ),
        ToolContract(
            tool="read_telemetry",
            capability="telemetry",
            effect="read",
            resource_type="telemetry",
            mutation=False,
        ),
    ])
    # The research profile has no system of record to index and declares no
    # validator bindings; both stay honestly absent rather than fabricated.
    return SemanticBundle.build(
        registry=registry,
        contracts=contracts,
        validators=None,
        state=StateIndex(frozenset()),
    )


def resolve_intent(intent_ref: str) -> ResolvedIntent | None:
    configured = os.environ.get("REMORA_INTENT_SOURCE_FILE", "").strip()
    if not configured or not intent_ref:
        return None
    path = Path(configured)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        table = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    entry = table.get(intent_ref)
    if not isinstance(entry, dict):
        return None
    authority = f"workflow_template:{hashlib.sha256(raw).hexdigest()}"
    task_text = str(entry.get("task_text", ""))
    if not task_text:
        return None
    intent = TaskIntent(
        operation=str(entry.get("operation", "")),
        resource_type=str(entry.get("resource_type", "")),
        requested_effect=str(entry.get("requested_effect", "")),
        target_entities=tuple(entry.get("target_entities", ())),
        source_spans=tuple(entry.get("source_spans", ())),
        action_spans=tuple(entry.get("action_spans", ())),
        proposed_by=authority,
    )
    return ResolvedIntent(intent=intent, task_text=task_text, authority=authority)
