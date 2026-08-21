# Execution lifecycle and the crash-consistent outbox

How a proposal travels from decision to effect, and what the system
records when that journey is interrupted. Two modules implement it:
`remora/governance/lifecycle.py` (FT-01, the declared state machine as a
runtime authority) and `remora/enforcement/outbox.py` (FT-02, the durable
record of dispatch intent).

**Stability:** both are internal. They are CORE by maturity
([ARCHITECTURE.md §9](../ARCHITECTURE.md#9-module-stability-index)) but
carry no backward-compatibility guarantee — only `remora.sdk` does
([docs/sdk.md](sdk.md)).

## The lifecycle model

`schemas/execution_lifecycle_v1.yaml` is the single source of truth. The
transition table is never duplicated in code: `LifecycleModel.load()`
parses it, and every consumer asks the model.

```
PROPOSED ──engine_decision──> ASSESSED ──┬─ direct_accept_token ──> AUTHORIZED
                                         ├─ verify_or_escalate ───> REVIEW_PENDING
                                         └─ abstain_or_hard_refusal ─> REFUSED

REVIEW_PENDING ──human_approval──> AUTHORIZED ──outbox_row_committed──> DISPATCH_PENDING
DISPATCH_PENDING ──worker_claim──> DISPATCHING ──> SUCCEEDED │ FAILED │ REFUSED │ UNKNOWN
```

Two ways to use it:

```python
from remora.governance.lifecycle import LifecycleTracker, IllegalTransition

tracker = LifecycleTracker()          # starts at PROPOSED
tracker.apply("engine_decision")      # -> ASSESSED
tracker.apply("verify_or_escalate")   # -> REVIEW_PENDING
tracker.is_terminal                   # False
tracker.trail                         # every (from, event, to) so far
```

`apply()` raises `IllegalTransition` on anything the model does not
declare, and leaves the tracker unchanged when it does — a refusal is a
signal, not a state change.

`/v1/execution` uses the second form, `check_transition(state, event)`,
as **defense in depth**: the review queue's own guards stay the primary
refusal path, and this catches drift between the declared machine and
what the endpoints actually do. An undeclared move is an internal
inconsistency surfaced as HTTP 500 (`lifecycle conformance violation`),
never silent divergence.

## The outbox

The execution path used to commit authorization, burn the grant, dispatch
the tool and record the outcome across separate transactions, leaving
crash windows in which a side effect could happen with nothing durable
saying so. The outbox makes one row the source of truth for *a dispatch
was authorized, and this is what became of it*.

| State | Meaning |
|---|---|
| `DISPATCH_PENDING` | Intent committed with the authorization; nothing dispatched |
| `DISPATCHING` | Claimed by exactly one worker; the tool may be running |
| `SUCCEEDED` | Confirmed side effect |
| `FAILED` | No side effect (tool raised, or authorized-but-never-claimed) |
| `REFUSED` | Refused before any effect |
| `UNKNOWN` | Claimed, then silence — undeterminable |

All four right-hand states are terminal and **none auto-retries**.
Re-running a call that may already have taken effect is the one move this
layer must never make, which is why `UNKNOWN` is a first-class outcome
rather than an error to clean up. Resolving one is a manual operator
decision that produces a *new* record; it never rewrites the terminal
state, because the uncertainty genuinely happened.

### Idempotency

`idempotency_key = SHA-256(proposal_id ‖ tool_call_hash ‖ attempt_no)`,
length-prefixed so no concatenation of different components collides. A
retried authorization returns the existing row; a legitimately
re-approved call after `APPROVAL_INVALIDATED` gets its own, because
`attempt_no` differs.

### Adapters

| Adapter | Durable | Use |
|---|---|---|
| `ExecutionOutbox` | No | Development and tests only — a restart loses the record that a dispatch was authorized |
| `SQLiteExecutionOutbox` | Yes | Single node (`REMORA_CHAIN_DB`); `BEGIN IMMEDIATE` makes every transition atomic |
| `PostgresExecutionOutbox` | Yes | Multi-worker (`REMORA_PG_DSN`); `SELECT … FOR UPDATE` gives the same exclusivity |

The durable adapters also expose `record_intent_enlisted(connection, …)`,
which writes the row **inside the caller's open transaction** — that is
what makes "the intent commits with the authorization and rolls back with
it" true rather than aspirational. The in-process store refuses
enlistment with `NotImplementedError` instead of ignoring the connection
and letting a caller believe in a guarantee that does not exist.

### Reconciliation

`servers.execution_api.reconcile_stale_dispatches(tenant)` settles rows
that have been stranded past `REMORA_OUTBOX_STALE_SECONDS` (default 900):

- claimed but silent → `UNKNOWN`, audited as `dispatch_unknown`;
- authorized but never claimed → `FAILED`, audited as
  `dispatch_never_dispatched`. Claiming strictly precedes invocation, so
  such a row provably produced no side effect; calling it `UNKNOWN` would
  overstate the uncertainty.

It runs as a lazy sweep on every execution-path interaction, the same
discipline REM-032 uses for review-queue TTL. That is **not** a claim
that a daemon runs: an idle tenant is never swept, so wall-clock
reconciliation needs a scheduled call.

## What is verified, and what is not

`tests/test_execution_fault_injection.py` executes the crash matrix from
[design/execution-lifecycle-outbox-v1.md](design/execution-lifecycle-outbox-v1.md)
§3.4: each crash point is injected and the promised recovery asserted.
Crashes are injected by making a step raise — the process is not actually
killed — so this validates ordering and rollback semantics, **not**
operating-system-level durability. Matrix rows 3, 4 and 6 are
indistinguishable by design and collapse to `UNKNOWN`; the suite asserts
that conflation rather than hiding it.

`EffectBlock` population (#37) closed on 2026-08-20:
`GET /v1/execution/proposals/{proposal_id}/envelope` derives a
DecisionEnvelope from the tenant audit chain, with `effect` filled from the
dispatch verdict, the outbox row and any recorded effect verification. It is a
projection, not a second store: the chain stays the record, so the envelope
cannot drift from it. `/v1/assess` still leaves the block at its defaults,
because that surface dispatches nothing.

The governed REST dispatch path for direct-ACCEPT proposals (#36) closed on
2026-08-05: `execute_accepted` is in the SDK snapshot and
`/v1/execution/execute-accepted` is a live route.

Still open (see
[assurance/fasttrack_register_v1.yaml](assurance/fasttrack_register_v1.yaml)):
a background reconciler daemon.

## Runnable example

```bash
python examples/execution_lifecycle_demo.py
```

Walks the lifecycle model, shows an illegal transition being refused, and
drives an outbox row through authorize → claim → settle plus the two
reconciliation outcomes — offline, no server required.
