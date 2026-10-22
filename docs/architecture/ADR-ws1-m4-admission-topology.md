# ADR: WS1-M4 admission topology (trust, clock and state)

- Status: **accepted** (2026-10-22), with the owner decisions below. Work
  package M4.1a of the
  [WS1-M4 SDD](../design/ws1-m4-safe-autonomy-recovery-v0.2.md) §9. M4.1b
  (receipts and epochs) is implemented and not yet wired; M4.1c wires it.
- Deciders: repository owner
- Related: SDD §2.2 and §4, `docs/design/execution-lifecycle-outbox-v1.md`,
  [ADR: authority custody and lease durability](ADR-authority-custody-and-lease-durability.md),
  `tests/test_ws1_gate_controls.py` control 2b (#982)

## Context

INV-M4-01 in the SDD asks for one linearization point at which the grant is
consumed, the evidence and authority are checked, and the dispatch intent is
recorded. Before any M4.1 code is written, this ADR records which durable
stores exist today, which of them can join one transaction, which clock each
uses, and which backend can carry the invariant. Every statement below was read
from `master` at `265abfbe`; line numbers refer to that revision.

### Stores that take part in admission

| Store | Backends | Joins a caller's transaction? | Clock | Uniqueness |
|---|---|---|---|---|
| Consumed-grant ledger, `EnforcementGate` (`remora/enforcement/gate.py`) | PG, SQLite, D1, memory | No. `check()` takes no connection and opens its own (gate.py:283-290, 457-513) | token age from `datetime.now(UTC)` (gate.py:399-402) | `pep_consumed.jti` primary key (gate.py:56) |
| Dispatch outbox (`remora/enforcement/outbox.py`) | PG, SQLite, memory; no D1 adapter | Yes, `record_intent_enlisted(connection, ...)` never commits (outbox.py:937-970, 1126-1148) | injected `now` or `datetime.now(UTC)` (outbox.py:196) | `UNIQUE (tenant_id, idempotency_key)`; PG `FOR UPDATE`, SQLite `BEGIN IMMEDIATE` |
| Principal revocation, `DurableRevocationStore` (`remora/governance/revocation_store.py`) | PG, SQLite, D1, memory | Yes, through `connection_provider` (revocation_store.py:161-164, 205-243) | none; `revoked_at` is DB time | primary key (tenant_id, principal) |
| Lease nonces, `DurableNonceStore` (`remora/enforcement/nonce_store.py`) | PG, SQLite, D1, memory | No; `try_consume` commits on its own connection | lease expiry from injected `now` or `datetime.now(UTC)` (lease.py:525, 1021) | primary key (tenant_id, nonce) |
| Audit chain (`remora/governance/tenant_chain.py`) and audit outbox (`remora/governance/audit_outbox.py`) | PG, SQLite, memory | The chain no; the audit outbox yes, via `enqueue(conn, ...)` (audit_outbox.py:138) | `now_fn`, default `datetime.now(UTC)` | head row `FOR UPDATE` / `BEGIN IMMEDIATE` |
| WS1 task ledger, `TaskCallLedger` (`remora/verification/planner.py:171`) | SQLite only, single host | No | not used | primary key (task_id, operation_id) |

The shared seam already exists. `transaction_state` (`remora/persistence/execution_state.py:139`)
opens one transaction per tenant and publishes its connection through the
`_ACTIVE_TX_CONNECTION` context variable (`servers/execution_api.py:417`).
On Postgres it first takes `SELECT ... FOR UPDATE` on the tenant's
`global_state` row, so every transaction for one tenant is serialized behind
that lock. On SQLite it opens `BEGIN EXCLUSIVE`. The outbox, the revocation
store and the audit outbox read the context variable; the gate and the nonce
store do not.

### How the three execution paths order their steps

None of the three paths runs the WS1 re-gate, the grant consumption and the
intent in one transaction.

- `redeem_accept_token` re-gates (service.py:2086), consumes the grant on the
  gate's own connection (:2152), then records the intent outside any
  transaction (:2179). Control 2b advances the WS1 clock between the first two
  steps, and the call executes.
- The approved-review path re-gates outside the transaction (:849). It then
  records the intent inside `transaction_state` together with the queue change
  and the audit row (:885-926), and consumes the grant after the claim, on its
  own connection (:1034).
- The worker path re-gates (:1518), claims the intent (:1602) and consumes the
  grant (:1628), each in its own transaction.

### Clocks

Four clocks meet at admission. The WS1 evidence clock is the deployment's
injected `clock_ms` (execution_gate.py:182). A PROVED result expires at the
earliest `min(valid_until, acquired_at + max_age_s)` over its hits
(check.py:226, 297-306), and resolvers stamp `valid_until = now_s + ttl_s`
from their own clock (resolvers.py:86-98). The gate and the outbox use the
application host's `datetime.now(UTC)`. Revocation and consumption timestamps
come from the database's `CURRENT_TIMESTAMP`. No component today compares an
evidence expiry with database time.

## Decision

1. **One authority transaction domain per tenant, on Postgres.** M4.1's
   reference profile is a single Postgres database holding `global_state`,
   `pep_consumed`, the dispatch outbox, the audit outbox, the revocation rows
   and the new authority-epoch rows. Admission runs inside
   `transaction_state`, extended so that the grant ledger and the epoch reads
   enlist through `_ACTIVE_TX_CONNECTION` like the outbox already does. The
   linearization point `t_L` of INV-M4-01 is that transaction's commit.
2. **The tenant row lock is the serialization mechanism for M4.1.** Because
   `transaction_state` already holds `global_state ... FOR UPDATE` for the
   tenant, two admissions for one tenant cannot interleave, and a revocation
   written inside `transaction_state` for that tenant orders strictly before or
   after any admission. Per-subject row locks (SDD §4.3) are a later throughput
   change. A revocation that does not run inside `transaction_state` does not
   get INV-M4-02, so the strict profile must route every admission-relevant
   revocation writer through it.
3. **Database time decides expiry at admission.** Inside the transaction,
   after the lock is held, admission reads `clock_timestamp()` once and uses
   that instant for grant age, evidence `valid_until` and epoch checks.
   Equality at `valid_until` counts as expired (M4-T10). Receipts keep their
   resolver-stamped times; admission subtracts a declared
   `max_clock_skew_ms` from each `valid_until` before comparing. The strict
   profile refuses to start without that value; it has no default.
4. **No network or monitor call inside the transaction.** Resolver lookups and
   monitor scoring finish before `transaction_state` opens. A serialization
   retry may reuse only receipts that are still valid at the retry's database
   time; otherwise admission refuses and the caller refreshes outside.
5. **Backend matrix for the strict M4.1 profile.**

   | Backend | M4.1 status | Reason |
   |---|---|---|
   | Postgres | reference profile | interactive transactions, row locks, one clock per transaction |
   | SQLite | single-host exploratory | `BEGIN EXCLUSIVE` serializes one file on one host; no claim for shared or networked files |
   | Cloudflare D1 | refused by the strict profile (capability pending) | no interactive transaction; a read flushes buffered writes as a separate batch (`d1_connection.py:125-131`); no outbox adapter; isolation rests on one container instance |
   | In-memory | tests only | already refused in production (`servers/api.py:616-658`) |

6. **The claim stops at local admission.** `AUTHORIZED_AT_COMMIT` is what this
   topology can establish. The dispatcher's pre-send permit check (INV-M4-03)
   runs against the same database, so a revocation committed after `t_L` and
   before the permit check is caught. A revocation after the send starts is
   not, and the SDD's `NOT_ESTABLISHED` label for effect-time validity stays.

## Consequences

- M4.1b and M4.1c (SDD §9) have a fixed target. The gate needs a consumption
  call that takes the enlisted connection; the nonce store and the WS1 task
  ledger stay outside the domain, and the ADR records that as a boundary.
- `redeem_accept_token` and the worker path must move their consume and intent
  steps into `transaction_state`, as the review path already does for the
  intent. The order inside becomes: lock, read database time, verify receipts
  and epochs, consume the grant, insert the intent, enqueue the audit row,
  commit.
- Control 2b becomes M4-T02. In the strict profile it must refuse; outside the
  strict profile it keeps documenting the residual.
- Throughput is serialized per tenant. This is acceptable for the research
  profile and is measured before any per-subject locking is proposed.
- D1 deployments keep today's behaviour and cannot claim INV-M4-01 or
  INV-M4-02. Lifting that needs real-worker tests of multi-statement batches
  and revocation ordering.

## Findings recorded while mapping (not fixed here)

- `DurableRevocationStore` and `DurableNonceStore` accept `state_endpoint` but
  call `d1_connection.connect()` without it (revocation_store.py:174,
  nonce_store.py:154), so they use `REMORA_STATE_ENDPOINT` from the
  environment. Production wiring passes the same variable
  (`servers/execution_api.py:994`, `:1525`), so deployments are not affected;
  a caller passing a different endpoint would be.
- Outside production, a D1 `transaction_state` sets the context variable
  (execution_state.py:181) while the outbox is `UnbackedExecutionOutbox`,
  which inherits the base `record_intent_enlisted` that raises
  `NotImplementedError` (dispatch.py:460, outbox.py:370).

Both need a test and a fix in their own PR.

## Owner decisions (2026-10-22)

The owner asked for the recommendations to be followed.

- **Review path.** The approved-review path consumes the grant in the same
  admission transaction as the claim, after the receipt and epoch checks. All
  three paths then share one linearization point. The token is still issued at
  claim time, so a review approval stays a separate authority until then.
- **Clock skew.** `max_clock_skew_ms` is a deployment parameter. The strict
  profile requires it, has no default, and accepts at most 5000 ms
  (`MAX_CLOCK_SKEW_MS` in `remora/verification/receipts.py`). A deployment
  whose clocks drift further must fix them, not widen the window.

## M4.1b, implemented (not wired)

- `remora/verification/receipts.py`: `EvidenceReceiptV1`, built only from a
  composition record's PROVED and completed results, with the subject epoch
  read before the lookups. `admission_refusal` is the pure admission check.
  It refuses expiry at database time, with equality expired and the skew
  subtracted, and a stale or revoked epoch. It also refuses a foreign,
  duplicated, missing or modified receipt
  (`tests/verification/test_evidence_receipts.py`, M4-T01, T03, T04, T07, T09,
  T10).
- `remora/governance/authority_epochs.py`: `AuthorityEpochs` over Postgres or
  SQLite. Every advance moves the epoch by one; it joins the caller's
  transaction; a locked read outside a transaction is refused; an unreachable
  store raises. Revoke-first and admit-first orderings are tested with two
  contending SQLite transactions (`tests/test_authority_epochs.py`).

Nothing on an execution path calls either module yet, so no claim or
capability changes.

## M4.1c: all three paths admit atomically

- With `REMORA_WS1_MODE=enforce` and `REMORA_WS1_MAX_CLOCK_SKEW_MS` declared,
  `redeem_accept_token` runs one `transaction_state`. Inside it, in the order
  above, admission reads the database instant once, reads the epochs under
  lock, and runs `admission_refusal`. It then consumes the grant on the same
  connection (`EnforcementGate.check(..., connection=)`), records the
  dispatch intent and enqueues `execution_admitted` on the audit outbox. A
  refusal or a backend error rolls all of it back, and the grant stays
  unspent.
- The epochs are read without a lock before the re-gate's lookups, and the
  receipts are built from the re-gate's composition record and those epochs.
  `remora/verification/admission.py` holds the checks. The execution core
  reaches it only through `Ws1AdmissionPort`.
- A precondition whose resolvers span several sources has no single subject.
  Admission refuses it (`evidence_receipt_unbuildable`) rather than pick one.
- The strict profiles refuse to start under WS1 enforce without the declared
  skew, or with a D1 state endpoint (`_check_ws1_admission`).
- The approved-review and async worker paths follow the owner decision.
  The intent is recorded when the approval is honoured, as before. The claim
  is a second transaction: receipt and epoch checks, the exclusive claim on
  the same connection (`claim_enlisted`), the grant minted and consumed there,
  and the admission event. A refusal rolls the claim back. The row then
  settles REFUSED under the admission reason, and no grant was spent.
- A REVIEW precondition's subject is `review:<role>`. An approval carries no
  evidence expiry (`NO_EVIDENCE_EXPIRY_MS`), because the review queue owns its
  lifetime and re-checks it before the claim. Advancing the role's epoch
  refuses the approved call.
- Tests: `tests/test_ws1_m4_admission.py`, every case on SQLite and on
  Postgres, the reference backend, in the coverage job's Postgres pass.
  - ACCEPT path: M4-T02, T04, T05 (admit first), T06, T10, T11, T12 and T13,
    plus replay on the enlisted ledger.
  - Review path: admission at the claim, a lapse after its re-gate, a REVIEW
    precondition under its role epoch, and a revoked role.
  - Worker path: admission at the claim, a lapse that settles the row, and
    four concurrent workers on one row.

  Control 2b (`tests/test_ws1_gate_controls.py`) still runs without a
  declared skew, so the residual stays pinned where admission is off.
- M4-T03 is covered for approvers only. The review queue checks approver
  revocation inside its transaction. The ACCEPT path has no revocation store
  for the agent principal, so its revocation has to be modelled as an
  epoch subject first. T07 and T08 (binding swaps) refuse before admission,
  through the existing context and toolspec binding. T09 is the pure check
  of M4.1b.
- Approval expiry between the intent transaction and the claim is not
  re-checked inside the claim. The grant minted there is capped by the
  authorization expiry the intent recorded (issue #418).

The M4.1 gate (SDD §5) also needs M4.1d (T14 to T20) and M4.1e; it stays
closed.
