#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regenerate the resolved-effect fixtures (quality program Q7.4).

Each case authorises one call under a closed registry, changes the registry
the way an adapter could between approval and dispatch, and dispatches the
unchanged call through ``GovernedToolDispatcher``. The artifact records what
the dispatcher did. The three changes the acceptance criterion names (alias,
redirect, remapping) must refuse; an unchanged registry and a change to an
unrelated entry must execute; a reference the registry never knew must
refuse before anything runs.

    python scripts/generate_resolved_effect_fixtures.py [--check]

``--check`` regenerates in memory and fails if the committed artifact
differs. Deterministic: no clock, randomness or signature enters the
artifact, only outcomes and effect digests.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "resolved_effect" / "fixtures_v1.json"

BUNDLE = "bundle-fixture"
TOOLS = {"close_wo": ("workorder.close@1", "write"),
         "workorder.close": ("workorder.close@1", "write"),
         "workorder.delete": ("workorder.delete@1", "delete")}
RESOURCES = {("prod", "WO-1"): "tenant-a/workorders/WO-1",
             ("prod", "WO-2"): "tenant-a/workorders/WO-2"}
ARGUMENT = {"close_wo": "id", "workorder.close": "id", "workorder.delete": "id"}

#: name, the call, the registry change between approval and dispatch.
CASES: tuple[dict[str, Any], ...] = (
    {"name": "unchanged_registry", "tool": "close_wo", "id": "WO-1", "change": {}},
    {"name": "unrelated_entry_changed", "tool": "close_wo", "id": "WO-1",
     "change": {"resources": {("prod", "WO-2"): "tenant-b/workorders/WO-2"}}},
    {"name": "alias_retargeted", "tool": "close_wo", "id": "WO-1",
     "change": {"tools": {"close_wo": ("workorder.delete@1", "delete")}}},
    {"name": "resource_redirected", "tool": "close_wo", "id": "WO-1",
     "change": {"resources": {("prod", "WO-1"): "tenant-b/workorders/WO-1"}}},
    {"name": "implementation_remapped", "tool": "close_wo", "id": "WO-1",
     "change": {"tools": {"close_wo": ("workorder.close@2", "write")}}},
    {"name": "unknown_alias", "tool": "close_workorder", "id": "WO-1", "change": {}},
    {"name": "unknown_resource", "tool": "close_wo", "id": "WO-404", "change": {}},
)


def _run(case: dict[str, Any]) -> dict[str, Any]:
    from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
    from remora.enforcement.resolved_effect import ClosedWorldResolver, UnresolvedReference

    resolver = ClosedWorldResolver(tools=TOOLS, resources=RESOURCES, resource_argument=ARGUMENT)
    arguments = {"id": case["id"]}
    try:
        authorised = resolver.resolve(case["tool"], arguments, "prod")
    except UnresolvedReference:
        return {"name": case["name"], "authorised_effect": None, "executed": False,
                "refusal_reason": "unresolved_reference", "stage": "issue"}
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name=case["tool"], arguments=arguments, target_environment="prod",
        policy_bundle_hash=BUNDLE, issued_at=datetime.now(UTC).isoformat(),
        resolved_effect=authorised)
    # The executor's registry: the authority's, with this case's change.
    executor_registry = resolver.with_changes(**case["change"])
    calls: list[Any] = []
    dispatcher = GovernedToolDispatcher(BUNDLE)
    dispatcher.register(case["tool"], lambda args: calls.append(args) or "ok")
    dispatcher.bind_effect_resolver(executor_registry)
    result = dispatcher.dispatch(lease, case["tool"], arguments, tenant_id="acme",
                                 target_environment="prod", actor_identity="agent-1")
    return {"name": case["name"], "authorised_effect": authorised.digest(),
            "executed": result.executed, "refusal_reason": result.refusal_reason,
            "stage": "dispatch", "tool_ran": bool(calls)}


def build() -> dict[str, Any]:
    os.environ.setdefault("REMORA_LEASE_SIGNING_KEY", "resolved-effect-fixture-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        os.environ.pop(name, None)
    cases = [_run(case) for case in CASES]
    must_refuse = {"alias_retargeted", "resource_redirected", "implementation_remapped",
                   "unknown_alias", "unknown_resource"}
    return {
        "artifact": "resolved_effect_fixtures_v1",
        "generator": "scripts/generate_resolved_effect_fixtures.py",
        "claim": ("A lease binds the effect its call resolved to when authorised; a changed "
                  "resolution refuses at dispatch and an unknown reference refuses outright."),
        "cases": cases,
        "summary": {
            "refused_as_required": sorted(c["name"] for c in cases
                                          if c["name"] in must_refuse and not c["executed"]),
            "executed_as_required": sorted(c["name"] for c in cases
                                           if c["name"] not in must_refuse and c["executed"]),
            "all_as_required": all((c["name"] in must_refuse) != c["executed"] for c in cases),
        },
        "scope": ("Library dispatcher with an in-memory closed registry. Says nothing about "
                  "whether a deployment's registry is correct, or about an adapter that "
                  "resolves differently from the registry it declares."),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not ARTIFACT.exists() or ARTIFACT.read_text(encoding="utf-8") != text:
            print(f"[FAIL] {ARTIFACT.relative_to(ROOT)} is stale; regenerate it")
            return 1
        print(f"[PASS] {ARTIFACT.relative_to(ROOT)} reproduces")
        return 0
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(text, encoding="utf-8")
    print(f"wrote {ARTIFACT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
