# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What REMORA records between a decision and its effect.

Offline, no server, no configuration. Two halves:

1. the lifecycle model (FT-01) — the declared state machine, and what
   happens when something tries a move it does not declare;
2. the crash-consistent outbox (FT-02) — dispatch intent recorded,
   claimed, settled, and what reconciliation does with the two ways a
   dispatch can be left stranded.

Everything printed is computed from the same code the execution API runs;
nothing here is illustrative-only.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from remora.enforcement.outbox import (
    ExecutionOutbox,
    OutboxState,
    idempotency_key,
)
from remora.governance.lifecycle import (
    IllegalTransition,
    LifecycleTracker,
    default_model,
)


def lifecycle_demo() -> None:
    print("=" * 66)
    print("1. The lifecycle model — declared once, enforced everywhere")
    print("=" * 66)
    model = default_model()
    print(f"   schema v{model.version}: {len(model.states)} states, "
          f"{len(model.transitions)} declared transitions")
    print(f"   terminal states: {', '.join(sorted(model.terminal_states))}")

    print("\n   A proposal routed to human review:")
    tracker = LifecycleTracker()
    for event in ("engine_decision", "verify_or_escalate", "human_approval"):
        state = tracker.apply(event)
        print(f"     --{event}--> {state}")
    print(f"   terminal? {tracker.is_terminal}")

    print("\n   A move the model does not declare is refused, not absorbed:")
    try:
        tracker.apply("engine_decision")
    except IllegalTransition as exc:
        print(f"     refused: {exc}")
    print(f"   state after the refusal is unchanged: {tracker.state}")


def outbox_demo() -> None:
    print("\n" + "=" * 66)
    print("2. The outbox — a durable record of what a dispatch became")
    print("=" * 66)
    # In-process store: fine for a demo, explicitly NOT durable. A real
    # deployment sets REMORA_CHAIN_DB or REMORA_PG_DSN and gets the same
    # contract from a store that survives a restart.
    outbox = ExecutionOutbox()
    tenant, call_hash = "acme", "a" * 64

    print("\n   [happy path] authorize -> claim -> settle")
    row = outbox.record_intent(
        proposal_id="p-1", tenant_id=tenant, item_id="item-1",
        tool_name="store_artifact", tool_call_hash=call_hash, grant_jti="j-1",
    )
    print(f"     intent recorded: {row.state.value}")
    claimed = outbox.claim(row.outbox_id, worker_id="worker-a")
    print(f"     claimed by {claimed.worker_id}: {claimed.state.value}")
    lost = outbox.claim(row.outbox_id, worker_id="worker-b")
    print(f"     a second worker claiming the same row gets: {lost}")
    settled = outbox.settle(row.outbox_id, OutboxState.SUCCEEDED,
                            detail="artifact written")
    print(f"     settled: {settled.state.value} ({settled.detail})")

    print("\n   [idempotency] a retried authorization is not a second dispatch")
    again = outbox.record_intent(
        proposal_id="p-1", tenant_id=tenant, item_id="item-1",
        tool_name="store_artifact", tool_call_hash=call_hash, grant_jti="j-1",
    )
    print(f"     same row returned: {again.outbox_id == row.outbox_id}")
    print(f"     key = {idempotency_key('p-1', call_hash, 1)[:16]}...")
    retry = outbox.record_intent(
        proposal_id="p-1", tenant_id=tenant, item_id="item-1",
        tool_name="store_artifact", tool_call_hash=call_hash, grant_jti="j-1",
        attempt_no=2,
    )
    print(f"     but a re-approved attempt gets its own row: "
          f"{retry.outbox_id != row.outbox_id}")

    print("\n   [stranded, claimed] the worker never reported back")
    silent = outbox.record_intent(
        proposal_id="p-2", tenant_id=tenant, item_id="item-2",
        tool_name="store_artifact", tool_call_hash="b" * 64, grant_jti="j-2",
    )
    outbox.claim(silent.outbox_id, worker_id="worker-c",
                 now=datetime.now(UTC) - timedelta(hours=1))
    for r in outbox.reconcile_stale(tenant, older_than=timedelta(minutes=15)):
        print(f"     -> {r.state.value}: {r.detail}")
    print("     the tool MAY have run; UNKNOWN says so instead of guessing,")
    print("     and it is never retried.")

    print("\n   [stranded, unclaimed] authorized, but nothing was dispatched")
    never = outbox.record_intent(
        proposal_id="p-3", tenant_id=tenant, item_id="item-3",
        tool_name="store_artifact", tool_call_hash="c" * 64, grant_jti="j-3",
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    for r in outbox.reconcile_unclaimed(tenant, older_than=timedelta(minutes=15)):
        print(f"     -> {r.state.value}: {r.detail}")
    print("     claiming precedes invocation, so no effect happened —")
    print("     FAILED is provable here, and UNKNOWN would overstate it.")
    assert outbox.get(never.outbox_id).state is OutboxState.FAILED

    # Exactly one row is still legitimately pending: the attempt-2 intent
    # created above, which is fresh and therefore not stranded. Ending on
    # "nothing is left in flight" would read better and be false.
    pending = outbox.pending(tenant)
    print(f"\n   Still pending (fresh, not stranded): {len(pending)}")
    for r in pending:
        print(f"     {r.proposal_id} attempt {r.attempt_no}: {r.state.value}")


def main() -> int:
    lifecycle_demo()
    outbox_demo()
    print("\nFull contract: docs/execution-lifecycle.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
