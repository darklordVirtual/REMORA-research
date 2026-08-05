# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA SDK quickstart — the governed tool-call loop from the integrator's seat.

Everything here goes through ``remora.sdk`` only; no REMORA-internal
imports. An *agent* credential proposes tool calls, REMORA decides
(ACCEPT / VERIFY / ABSTAIN / BLOCK), a *reviewer* credential approves
what needs a human, and every operation lands in a hash-chained,
verifiable audit trail. Roles are separated server-side: the agent
cannot approve its own calls, and the demo shows the typed refusal
when it tries.

Two ways to run it:

* **Against your control plane** — set ``REMORA_URL`` and
  ``REMORA_API_TOKEN`` (agent credential); optionally
  ``REMORA_REVIEWER_TOKEN`` to complete the review loop::

      REMORA_URL=https://remora.internal python examples/sdk_quickstart.py

* **Offline demo (default)** — with no ``REMORA_URL`` set, the script
  starts the real REMORA ASGI app in-process in development mode
  (single-token auth, shipped research tool registry: a sandboxed
  artifact write and a read-only telemetry read). Zero configuration,
  no network access.

Install: ``pip install "remora[api,sdk]"`` (the demo needs ``api`` for
the in-process server; a pure remote client needs only ``sdk``).
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile

DEMO_TOKEN = "sdk-quickstart-demo"  # noqa: S105 - offline demo only


def _make_clients():
    """Return (agent_client, reviewer_client_or_None)."""
    from remora.sdk import RemoraClient

    remote = os.environ.get("REMORA_URL", "").strip()
    if remote:
        print(f"mode: remote control plane at {remote}")
        agent = RemoraClient(remote, token=os.environ.get("REMORA_API_TOKEN"))
        reviewer_token = os.environ.get("REMORA_REVIEWER_TOKEN", "").strip()
        reviewer = (
            RemoraClient(remote, token=reviewer_token) if reviewer_token else None
        )
        return agent, reviewer

    # Offline demo: development single-token mode + research tool registry.
    # Environment must be set before the server module is imported.
    os.environ.setdefault("REMORA_ENV", "development")
    os.environ.setdefault("REMORA_API_BEARER_TOKEN", DEMO_TOKEN)
    # Ephemeral signing key: without it the PEP rejects every execution
    # grant (token_verification_failed:no_signing_key) — fail closed.
    os.environ.setdefault("REMORA_PDP_SIGNING_KEY", secrets.token_hex(32))
    os.environ.setdefault(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    os.environ.setdefault(
        "REMORA_EXECUTION_ARTIFACT_DIR",
        tempfile.mkdtemp(prefix="remora-sdk-demo-"),
    )
    from fastapi.testclient import TestClient

    import servers.api as api

    print("mode: offline demo (in-process ASGI app, development mode)")
    # Development single-token mode honors the client-declared role, which
    # is exactly what a two-persona demo needs. In production the server
    # ignores self-asserted roles; role separation then requires the
    # token-table mode (REMORA_API_TOKENS).
    agent = RemoraClient(
        base_url="http://demo", token=DEMO_TOKEN, role="operator",
        http_client=TestClient(api.app),
    )
    reviewer = RemoraClient(
        base_url="http://demo", token=DEMO_TOKEN, role="reviewer",
        http_client=TestClient(api.app),
    )
    return agent, reviewer


def main() -> int:
    from remora.sdk import (
        AuthorizationError,
        DecisionAction,
        RemoraUnavailableError,
        ToolCall,
    )

    try:
        agent, reviewer = _make_clients()
    except RemoraUnavailableError as exc:
        print(f"cannot reach REMORA: {exc}", file=sys.stderr)
        return 1

    with agent:
        # 1. A read-only call in staging. There is no server-side evidence
        #    configured, so even a low-risk read lands on ABSTAIN: client-
        #    asserted trust (schema_valid=True) can never buy an ACCEPT.
        print("\n[1] governed read (read_telemetry, staging)")
        reading = agent.assess(ToolCall(
            tool_name="read_telemetry",
            arguments={"asset": "pump-7"},
            target_environment="staging",
            schema_valid=True,
        ))
        print(f"    decision: {reading.action.name}   proposal: {reading.proposal_id}")
        print(f"    execution token granted: {reading.execution_token is not None}")

        # 2. A production write: routed to human review, never silently run.
        print("\n[2] governed write (store_artifact, prod)")
        write = ToolCall(
            tool_name="store_artifact",
            arguments={"artifact_id": "demo-report-1",
                       "content": {"status": "draft"}},
            target_environment="prod",
            intent_ref="WO-1204",
            schema_valid=True,
            rollback_available=True,
        )
        assessment = agent.assess(write)
        print(f"    decision: {assessment.action.name}   proposal: {assessment.proposal_id}")

        if assessment.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE):
            print(f"    review item queued: {assessment.review_item_id}")

            # The agent trying to approve its own call is a typed refusal —
            # role separation is enforced server-side, not by convention.
            try:
                agent.approve(assessment.review_item_id)
                print("    UNEXPECTED: agent credential approved a review")
            except AuthorizationError as exc:
                print(f"    agent approval refused ({exc.code}): {exc}")

            if reviewer is not None:
                with reviewer:
                    approval = reviewer.approve(assessment.review_item_id)
                print(f"    reviewer approved until {approval.expires_at}")
                outcome = agent.execute(assessment.review_item_id, write)
                print(f"    execution outcome: {outcome.outcome}")
                if outcome.tool_execution is not None:
                    print(f"    tool executed: {outcome.tool_execution.get('executed')}")
            else:
                print("    no reviewer credential (set REMORA_REVIEWER_TOKEN) "
                      "- review item left pending")

        # 3. A tool REMORA has never heard of is never waved through:
        #    depending on risk it abstains or queues for review; it never
        #    gets an execution token.
        print("\n[3] unknown tool (export_customer_db, prod)")
        unknown = agent.assess(ToolCall(
            tool_name="export_customer_db",
            arguments={"table": "customers"},
            target_environment="prod",
        ))
        print(f"    decision: {unknown.action.name}")
        print(f"    execution token granted: {unknown.execution_token is not None}")

        # 4. The audit chain covers everything above and is verifiable.
        print("\n[4] audit verification")
        audit = agent.verify_audit_chain()
        print(f"    audit chain valid: {audit.valid}   "
              f"records checked: {audit.records_checked}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
