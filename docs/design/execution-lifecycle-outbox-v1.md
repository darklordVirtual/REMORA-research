# Execution Lifecycle + Crash-Consistent Outbox — Design v1

**Status: DRAFT, for human review.** Every decision in this document is a
**PROPOSAL**. Nothing described here is implemented; no code in this repo
mints a `proposal_id`, writes an outbox row, or runs a reconciler today.
Read "the design does X" as "the design proposes X" throughout. This file
must be added to `docs/assurance/document_register_v1.yaml` before merge
(no entry exists yet) with `status: draft` — a design doc has nothing to
sync against until something is built from it.

**Source issues:** #37 (bind `DecisionEnvelope` lifecycle to the execution
path), #82 / F-02 (crash-consistent outbox, production blocker), #36
(state-machine ID for direct-ACCEPT proposals), #45 (decision-to-execution
correlation). Per the cluster note on #37/#82, this is one program: #82's
outbox schema is the source of the lifecycle ID, #36 assigns it to every
proposal, #37 binds the envelope to it, #45 logs it. This document covers
#37 (Design A) and #82 (Design B) fully; it defines the ID #36/#45 need
without re-litigating their scope.

---

## 1. Problem

**No single ID follows a proposal from decision to effect.**
`POST /v1/execution/assess` mints a token with `request_id =
f"{tenant}:{obs.tool_call_hash}"` (`servers/execution_api.py:802`).
`POST /v1/execution/execute` mints a **second, different** token with
`request_id = f"{tenant}:{req.item_id}"` (`:997`). Assess and execute
cannot be joined by `request_id` alone — exactly the gap #45 calls the
"defining observability failure." Direct ACCEPT gets no `item_id` at all
(`servers/execution_api.py:798-808`), and `/execute` requires one
(`:930`), so it has no governed dispatch path today (#36).

**`DecisionEnvelope` is never built on the execution path.**
`EffectBlock` (`remora/governance/envelope.py:214-230`) exists to carry
decision-to-effect state but its own docstring says: "no producer sets
these fields." `/v1/execution/*` records outcomes as dict events in the
tenant chain (`event: "execution_result"`, `:1088-1106`), never as an
envelope.

**The execution path is four separate transactions around one dispatch.**
Tracing `/execute` in `servers/execution_api.py`: (1) `db_transaction_state`
commits `q.execute()` → `AUTHORIZED` (`:961-967`); (2) `_GATE.check(...,
consume=True)` durably burns the PDP `jti` (`:1004`); (3) the tenant chain
append for `execution_authorized` happens **after** that, as a separate
write (`:1011-1020`); (4) `ExecutionLease.issue()` mints a **third**
identifier, the lease `nonce`, consumed by `NonceLedger`, which has "no
durable adapter at all" (`remora/enforcement/lease.py:297-309`); (5)
`dispatcher.dispatch()` runs the actual side effect (`:1052-1059`); (6)
`q.record_execution_outcome()` commits in a **separate**
`db_transaction_state` (`:1080-1086`); (7) the `execution_result` chain
append happens after that, as yet another separate write (`:1088-1106`).
Steps 2/3, 4/5, and 6/7 are non-atomic pairs across different stores. This
matches #82 verbatim: three crash windows, "a plain retry is neither safe
nor possible" once the item leaves `APPROVED`.

**`EffectBlock` predates the chain-hash carve-out pattern it will need.**
`remora/governance/envelope.py:184-211` (`POST_V2_AUDIT_KEYS`,
`normalize_audit_for_hash`) already establishes "fields added after a
chain's preimage was fixed must be omitted from the hash when unset."
`EffectBlock` has no such carve-out yet, because nothing populates it —
see §5.

---

## 2. Design A — Unified execution lifecycle

### 2.1 One `proposal_id`, minted once

**Proposal:** `proposal_id` (UUIDv4 or ULID — Open Decision 8) is minted
once, at `/v1/execution/assess`, for every decision outcome (ACCEPT,
VERIFY, ESCALATE, ABSTAIN). It replaces both ad hoc `request_id` schemes
in §1 as the join key for `PolicyDecisionToken.request_id` at both assess
and execute time, and is the ID direct-ACCEPT proposals get under #36.
It does not remove `tool_call_hash` or `item_id` — `tool_call_hash`
legitimately changes when a proposal is re-queued after
`APPROVAL_INVALIDATED` (`remora/governance/review_queue.py:387-407`);
`proposal_id` is the thing that stays constant across that change.

### 2.2 Event taxonomy

One append-only stream per `proposal_id`, projected into one auditable
view. Mapped onto **existing** tenant-chain event names — nothing shipped
is renamed:

| # | Event | Where written today | Stage |
|---|---|---|---|
| 1 | `assessed` | `execution_api.py:777-791` | Assessment |
| 2 | `review_enqueued` | `review_queue.py:185-193` (ReviewQueue log, not tenant chain) | Decision → review |
| 3 | `approved` | `execution_api.py:910-916` | Review |
| 4 | `execution_{expired\|binding_refused\|approval_invalidated}` | `:976-982` | Review / re-gate |
| 5 | `execution_authorized` | `:1011-1020` | Authorization (pre-effect) |
| 6 | *(new)* `dispatch_pending` | proposed — outbox insert, §3 | Dispatch intent |
| 7 | *(new)* `dispatch_started` | proposed — worker update, §3 | Side effect (attempt) |
| 8 | `execution_result` | `:1088-1106` | Observed effect |
| 9 | *(new)* `lifecycle_closed` | proposed — projector, terminal outbox state | Final outcome |

### 2.3 Projection, not a fourth store of record

**Proposal:** the stores of record stay as they are — tenant audit chain,
outbox table (§3), control-plane envelope store. A read-side **projection**
(view or materializer, not a transactional store) joins them on
`proposal_id` for a human/auditor timeline, keeping the already-tested
chain schemas untouched. Mechanism (SQL view vs. batch job vs. read-time
fan-out) is Open Decision 3.

### 2.4 Binding to `DecisionEnvelope` without breaking it

Additive only, per CLAUDE.md:

- `RequestBlock.request_id` (`envelope.py:32`) becomes `proposal_id`'s
  value for envelopes built on the execution path — no field added or
  removed; `/v1/execution` builds no envelope today, so there is no
  existing producer contract to break.
- `EffectBlock` gets its first real producer: once an outbox row reaches a
  terminal state, a projector populates `executed`, `tool_call_hash`,
  `effect_outcome`, `ledger_entry` — the schema already reserves exactly
  this shape.
- `envelope_hash()` (`envelope.py:282-298`) does not cover `effect.*`
  today, so populating `EffectBlock` later does not invalidate it. The
  **chain** hash (`AuditBlock.hash`, SHA-256 over the full envelope JSON)
  does cover the whole payload — an envelope already chained cannot be
  mutated in place without breaking the chain. That is why §2.5 proposes
  revisions as the default, flagged as Open Decision 7.

### 2.5 Envelope revisioning (proposed default)

**Proposal:** once an envelope's chain hash is appended, later stages
append a **new revision** for the same `proposal_id` instead of mutating
the original — the same discipline `POST_V2_AUDIT_KEYS` uses for field
evolution, applied to whole-envelope evolution. A revision carries
`proposal_id`, `revision_no`, `previous_envelope_hash`, chained the way
`TenantAuditChain` chains entries (`tenant_chain.py:71-90`). The latest
revision is the current envelope; the full sequence is the trail. This is
the most contract-touching choice in this document — see Open Decision 7.

---

## 3. Design B — Crash-consistent outbox

### 3.1 State machine

```
APPROVED --(authorize tx)--> DISPATCH_PENDING --(worker claims)--> DISPATCHING
                                                                        |
                                        +---------------+--------------+---------------+
                                        v               v              v               v
                                   SUCCEEDED         FAILED         REFUSED         UNKNOWN
                                (effect ran,      (effect did    (refused        (may or may not
                                 result captured)   not run)      pre-effect)     have run — undeterminable)
```

All four right-hand states are **terminal**; none auto-retries. `UNKNOWN`
is first-class, not an error path — it is what the reconciler produces
when it cannot prove `SUCCEEDED` vs. `FAILED` (§3.4), per #82's explicit
requirement.

Maps onto the **existing** `ItemStatus` enum
(`remora/governance/review_queue.py:61-75`), proposed additive:

| Outbox state | `ItemStatus` | Relationship |
|---|---|---|
| pre-`DISPATCH_PENDING` | `APPROVED` | unchanged |
| `DISPATCH_PENDING` | `AUTHORIZED` | outbox row inserted in the **same transaction** that sets `AUTHORIZED` (today two separate writes at `:961-967`/`:1011-1020`, proposed merged, §3.5) |
| `DISPATCHING` | `AUTHORIZED` (unchanged) | worker claims the row |
| `SUCCEEDED` | `EXECUTED` | existing terminal state |
| `FAILED` | `DISPATCH_FAILED` | existing terminal state |
| `REFUSED` | `DISPATCH_REFUSED` | existing terminal state |
| `UNKNOWN` | *(new)* `DISPATCH_UNKNOWN` | new `ItemStatus` member |

`record_execution_outcome()` (`review_queue.py:414-451`) already refuses
any transition from a non-`AUTHORIZED` item and already distinguishes
`executed`/`failed`/refused; this extends its boolean pair to a 4-way
outcome rather than replacing the method.

### 3.2 Idempotency key

**Proposal:** `idempotency_key = SHA-256(proposal_id ‖ tool_call_hash ‖
attempt_no)`. Folding in `attempt_no` means a legitimately re-approved
identical call after `APPROVAL_INVALIDATED` gets a fresh key instead of
colliding with a stale row from a prior approval cycle. Whether
`attempt_no` belongs in the key, or a re-approval should instead force a
new `proposal_id`, is Open Decision 8.

### 3.3 Schema sketch (Postgres — sketch, not a migration)

```sql
-- PROPOSED. No migration exists. Names/types are a sketch for review.
CREATE TABLE execution_outbox (
    outbox_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id     TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    item_id         TEXT NOT NULL,      -- ReviewQueue item, FK by convention
    idempotency_key TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_call_hash  TEXT NOT NULL,
    grant_jti       TEXT NOT NULL,      -- PolicyDecisionToken.jti, already burned
    state           TEXT NOT NULL CHECK (
        state IN ('DISPATCH_PENDING','DISPATCHING',
                  'SUCCEEDED','FAILED','REFUSED','UNKNOWN')
    ),
    attempt_no        INTEGER NOT NULL DEFAULT 1,
    worker_id         TEXT,             -- set on claim
    claimed_at        TIMESTAMPTZ,
    heartbeat_at      TIMESTAMPTZ,      -- reconciler staleness check
    result_sha256     TEXT,             -- mirrors capture_tool_result()
    result_size_bytes INTEGER,
    result_truncated  BOOLEAN,
    refusal_reason    TEXT,
    last_error        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX execution_outbox_pending_idx
    ON execution_outbox (state, created_at) WHERE state = 'DISPATCH_PENDING';
CREATE INDEX execution_outbox_stale_dispatching_idx
    ON execution_outbox (state, heartbeat_at) WHERE state = 'DISPATCHING';
```

`UNIQUE (tenant_id, idempotency_key)` is what makes "outbox row written in
the same transaction as authorization" also mean a retried authorize call
cannot insert a second dispatch intent for the same attempt
(`INSERT ... ON CONFLICT DO NOTHING`) — independent of the worker-side
idempotency the state machine provides.

### 3.4 Crash matrix

| # | Crash point | Resulting state | Recovery |
|---|---|---|---|
| 1 | Before the authorize+outbox transaction commits | Rolled back: item stays `APPROVED`, no outbox row, no `execution_authorized` event | Safe: client re-calls `/execute`; approval unconsumed, re-gate runs fresh |
| 2 | After commit (`DISPATCH_PENDING` visible), before any worker claim | Item `AUTHORIZED`, row `DISPATCH_PENDING`, no side effect | Reconciler polls for stale `DISPATCH_PENDING`, hands to a worker — normal-path recovery |
| 3 | After claim (`DISPATCHING`), before invoking the tool | Row `DISPATCHING`, no side effect | Stale row, no invocation evidence → safe to re-claim (caveat below) |
| 4 | During/after the tool call, before the worker writes the result | Row `DISPATCHING`, side-effect state genuinely unknown | **Not** auto-retried; transitions to `UNKNOWN` after a staleness threshold — F-02's window (c) verbatim |
| 5 | After a terminal state, before the projector writes `record_execution_outcome()` / `execution_result` / `EffectBlock` | Outbox row terminal (source of truth); downstream projections stale | Projector re-runs idempotently off the terminal row — replay-safe, visibility lag only. **Implemented 2026-08-26 (issue #416)**: the projection payload commits WITH settlement (`projection_json`), `project_terminal_intent` replays queue outcome + `execution_result` keyed on the outbox id, wired into the lazy sweep, the reconciler and the worker; crash-injected in `tests/test_terminal_projection.py` |
| 6 | Worker process crashes mid-heartbeat (not the tool call) | Row `DISPATCHING`, heartbeat stale | Indistinguishable from #3/#4; collapses into `UNKNOWN` unless a reconciliation probe exists (Open Decision 5) |

Row #3's retry is safe only if "claimed but never invoked" is
distinguishable from "invoked," which requires the worker to log claim and
invocation as separate evidence. If a dispatcher cannot make that
distinction, row #3 should also collapse into #4/#6's `UNKNOWN` handling —
flagged so a reviewer can push back on the optimistic case.

### 3.5 What changes in `servers/execution_api.py`

**Proposal**, per §1's trace: merge `q.execute()` → `AUTHORIZED`, PDP `jti`
consumption, and the `execution_authorized` chain append with the new
outbox insert into **one** transaction via `db_transaction_state`
(`:235-309`, extended) — satisfies #82's "atomic authorization + outbox
job." `ExecutionLease.issue()` / `dispatcher.dispatch()` move out of the
request thread into a worker claiming `DISPATCH_PENDING` rows — #82's
"dispatch from a worker, not the request thread." `POST /execute` returns
once the outbox row is inserted (`outcome: "dispatch_pending"`, a new
response shape, §4), not once the tool has run; synchronous callers poll
`GET /v1/execution/outbox/{outbox_id}` (new) or long-poll with a bounded
timeout — sync-vs-async is Open Decision 6. `record_execution_outcome()` /
`execution_result` become the projector step driven by the outbox row's
terminal state.

---

## 4. Migration and compatibility

- **Existing tenant chains are not rewritten.** Chains recorded before
  this ships keep verifying exactly as today; new event types are
  additive rows, not retroactive edits.
- **`DecisionEnvelope` stays additive-only.** No block removed or renamed;
  `RequestBlock.request_id` gains a value convention, not a field;
  `EffectBlock` gains a producer, not new fields. The revision-vs-mutation
  question (§2.5) is the one place this design could be genuinely
  contract-touching — Open Decision 7.
- **API additivity, with one caveat.** `/execute`'s response gains a new
  `outcome` value (`dispatch_pending`, alongside `execute` /
  `approval_expired` / `binding_refused` / `approval_invalidated`,
  `execution_api.py:420-421`) and an optional `outbox_id`. But if `/execute`
  stops returning `tool_execution` synchronously (§3.5), that is a
  **breaking** change for any caller reading it inline today, not merely
  additive — must be resolved explicitly (Open Decision 6).
- **New enum member.** `ItemStatus.DISPATCH_UNKNOWN` is additive to the
  enum; any exhaustive match on `ItemStatus` needs a default/`unknown`
  branch (not found in this pass, but not verified for every caller).
- **Degradation ladder interaction, flagged not designed.** If the
  reconciler cannot reach its outbox store, that is a degradation event
  and should route through `DegradationRecorder`
  (`remora/governance/degradation.py`) rather than fail silently — out of
  scope here (§6).

---

## 5. Test plan

Per repository convention: **searched validation**, never proof. Fault
injection over an enumerated set of crash points (§3.4) and bounded
random property checks are evidence the invariant held on the cases
exercised, not a guarantee for every interleaving.

**Fault injection.** For each row in §3.4: run the authorize→outbox→
dispatch→result path against a real SQLite/Postgres backend; inject a
process-kill or exception at the named commit boundary (monkey-patch
`conn.execute`/`conn.commit` to raise after N calls, or `os._exit()` a
worker subprocess at a checkpoint); restart against the same durable
store and assert the row/item lands in the state column 3 predicts, never
an unlisted state; assert recovery (column 4) resolves within a bounded
number of reconciler passes — except rows 4/6, which must assert the row
does **not** self-resolve without an operator action or explicit
reconciliation probe.

**Property-style invariants (bounded random search):**
- *No double-dispatch*: across randomized crash/retry sequences at
  points 1–3, the tool callable is invoked at most once per
  `idempotency_key` — structurally enforced by the `UNIQUE` constraint
  (§3.3), checked empirically via a test tool's call counter.
- *No silent effect loss*: after point 4, the outbox row is never
  observed back in `DISPATCH_PENDING` or deleted — only `DISPATCHING` →
  `UNKNOWN` or a correctly terminal state.
- *Envelope/chain agreement*: for any `proposal_id` reaching a terminal
  outbox state, `EffectBlock.effect_outcome` and the tenant chain's
  `execution_result` event agree on outcome, checked field-by-field over
  N generated lifecycles.
- *Hash-chain integrity under the merged transaction*: tenant-chain
  `verify()` still passes after every fault-injection run in §5.1 — the
  outbox change must not break the *existing* chain invariant even when
  the *new* outbox invariant is violated by an injected fault.

**Regression coverage.** Existing tests for the approve/execute path
(`db_transaction_state` rollback tests, restart-proven item→tenant
binding tests, `docs/07-api-reference.md:335-337`) continue passing
unmodified where a code path is unchanged, and are updated — not deleted
— where a path is intentionally replaced (e.g., inline
`record_execution_outcome()` moving to the projector).

---

## 6. Open decisions for the maintainer

No default is picked on any **[contract]** item.

1. **Where is `proposal_id` minted?** Only at `/assess` (every outcome
   including ABSTAIN, full #45 observability, higher minting volume) vs.
   only for proposals that could execute (lower volume, ABSTAIN stays
   uncorrelated).
2. **[contract] Is `proposal_id` the same value as
   `DecisionEnvelope.request_id`, or a separate field?** Reuse fixes the
   two-ID gap directly but couples the outbox schema to envelope
   internals living in a different store than the tenant chain.
3. **Projection mechanism (§2.3):** SQL view, periodic materializer, or
   read-time API fan-out — staleness tolerance vs. operational complexity
   vs. load on primary stores.
4. **Outbox reconciler ownership:** in-process with
   `GovernedToolDispatcher`, or a separate service. Simpler ops vs. fault
   isolation from the process most likely to be the one that crashed.
5. **UNKNOWN resolution path:** manual operator decision only (matches
   #82 literally), or an additional deployment-supplied reconciliation
   probe to auto-resolve `UNKNOWN`. Faster recovery vs. REMORA reporting
   an outcome derived from an unverified second integration (CLAUDE.md:
   no invented results applies to inferred outcomes too).
6. **[contract] Does `/execute` stay synchronous or become
   pending+poll?** Immediate `dispatch_pending` (§3.5) breaks any caller
   reading `tool_execution` inline today. Staying synchronous (block until
   terminal or timeout) preserves the wire contract but reintroduces the
   "dispatch from the request thread" problem #82 exists to remove.
7. **[contract] Envelope revisioning vs. in-place mutation (§2.5).**
   Revisioning never recomputes a published chain hash but turns "the
   envelope" into an ordered series. In-place mutation keeps one envelope
   but needs `effect.*` permanently excluded from the chain-hash preimage
   (an explicit exception) or accepts the hash is only final once the
   effect is known — conflicting with "durable INTENT record BEFORE the
   side effect" (`execution_api.py:1008-1010`), a property the current
   code deliberately protects.
8. **Idempotency key composition (§3.2):** fold `attempt_no` into the key
   (one `proposal_id`, multiple attempts across re-approval cycles) vs.
   mint a new `proposal_id` per re-approval (simpler key, weaker
   single-thread guarantee across `APPROVAL_INVALIDATED`).

---

## 7. Explicit non-goals

- **Not a durable multi-process `NonceLedger`.** The `ExecutionLease`
  nonce (REM-025) is separate from the outbox idempotency key; a
  multi-dispatcher deployment still needs REM-025 independently.
- **Not a promise every external effect becomes provably recoverable.**
  `UNKNOWN` is the acknowledged limit for non-idempotent tools with no
  downstream dedup key, not a stepping stone to eliminating it.
- **Not the full #45 observability layer.** This defines the ID (
  `proposal_id`) #45 needs threaded through leases/tokens/logs, not the
  structured-logging baseline, exception taxonomy, or metrics counters
  #45 also asks for.
- **Not a change to RBAC, the semantic bundle (SHELF-020), or AROMER.**
  `proposal_id` appears as an additional correlation field only.
- **Not a performance or SLA commitment.** No polling interval,
  staleness threshold, or throughput number is a real proposed value —
  any such number needs its own benchmark artifact first.
- **Not a finished SQLite outbox schema.** §3.3 sketches Postgres only;
  single-node SQLite parity is required (precedent: `SQLiteTenantChain`)
  but its DDL is left as follow-up work.
