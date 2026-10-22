# REMORA WS1-M4: Safe Autonomy Recovery, Verified at Execution
**Software Design Document (SDD) v0.2 · OSF-integrated research design / implementation proposal · 2026-10-21**

**State:** PROPOSED. Not implemented, and not authorised for live deployment.

**Scope:** REMORA-research WS1 (#953); work control #707.

**Code-review reference:** [`265abfbeb43473192e04886cc57743c1c3abbf8e`](https://github.com/darklordVirtual/REMORA-research/tree/265abfbeb43473192e04886cc57743c1c3abbf8e). The review read the code at this revision. Before an implementation PR opens, reconcile §1 and §4.4 against the `master` of that day.

**Existing OSF integration:** [project 5hfae](https://osf.io/5hfae/), [mirror workflow](../../.github/workflows/osf-sync.yml), [sync implementation](../../scripts/osf_sync.py), [sync tests](../../tests/test_osf_sync.py), [reproducibility policy](../06-reproducibility.md). The workflow reads the GitHub secret `OSF_TOKEN`. On 2026-10-21 the mirror's `verify` step reported that OSF matched `265abfbe` exactly (3430 files on 7 nodes). The project is private. Open-Ended Registration [`pxzj7`](https://osf.io/pxzj7/) of that snapshot was submitted the same day, embargoed until 2026-11-20 (§6.4, §12).
**Source anchors:** [#953](https://github.com/darklordVirtual/REMORA-research/issues/953), [#707](https://github.com/darklordVirtual/REMORA-research/issues/707), [#982](https://github.com/darklordVirtual/REMORA-research/pull/982), [#981](https://github.com/darklordVirtual/REMORA-research/pull/981), [#920](https://github.com/darklordVirtual/REMORA-research/pull/920).

## 0. Decision in one page

**Goal:** Establish a clearly bounded, testable dispatch-admission safety invariant, then determine whether learned evidence scheduling improves *legitimate completed tasks* relative to deterministic scheduling under matched calibration and resources. Never trade execution safety for average utility.

**Proceed in four gated deliveries.** M4.1 closes the execution boundary. M4.2 is Study D, preregistered on OSF. M4.3 is an instrumented execution benchmark, and M4.4 an external reproduction. **Reuse the existing GitHub-to-OSF mirror; do not rebuild or replace it.** Freeze unrelated WS1 feature additions until M4.1 is closed. No paid runs, publication commitments, OT deployment, or external participation are authorised by this SDD.

**Crucial scope distinction:** Atomic local admission is **not** atomic external tool execution. Three statements must remain separate:

1. `AUTHORIZED_AT_COMMIT`: the grant, recorded admissible evidence, current authority epochs and dispatch intent were checked and committed together at a linearization point in the same trusted state backend.
2. `DISPATCH_ATTEMPT_RECORDED`: an instrumented credential-owning executor began a particular, bound downstream call. Local checks do not prove that no alternate paths exist.
3. `EFFECT_OBSERVED` / `EFFECT_ATTRIBUTED`: a trusted observer saw a change, and additional independent evidence, if present, ties the change to that dispatch. Neither follows from (1) or (2).

A broad claim “ValidEvidence at the physical-effect time” is **NOT_ESTABLISHED** without a trusted downstream enforcement/fencing mechanism with compatible clock and revocation semantics. Preserve `runtime_capability_surface_completeness=NOT_ESTABLISHED`.

## 1. Verified baseline and motivating defect

As of the inspected revision:

- `remora/execution/service.py::redeem_accept_token` performs `ws1_regate(...)` before `gate.check(..., consume=True)`, then records the dispatch intent separately. The review and worker paths also re-gate and consume in separately sequenced operations.
- `remora/enforcement/gate.py::EnforcementGate` offers atomic uniqueness for a `jti` with durable `pep_consumed` when a store is configured (Postgres, SQLite, D1); its interface does **not** accept an evidence receipt or authority epoch as part of the same consumption transaction.
- `remora/enforcement/outbox.py` has durable intent and exclusive claim implementations; `remora/governance/revocation_store.py` currently describes principal-scoped revocation, not a universal, atomic evidence-revocation ledger.
- `remora/verification/execution_gate.py::Ws1Outcome` has the final decision, binding and composition record; it does not yet expose a durable, versioned proof receipt suitable for atomic redemption.
- `remora/enforcement/lease.py::GovernedToolDispatcher.dispatch` re-verifies the lease and checks multiple runtime bindings before invoking the tool. This protects an additional boundary, but by itself does not close the WS1 re-gate/consume interval or prove external-effect atomism.
- `tests/test_ws1_gate_controls.py::test_control_2b_evidence_lapsing_after_the_regate_is_the_documented_residual` deliberately advances the clock between re-gate and `gate.check`: the call **executes**. PR #982 explicitly documents this finding.

OSF baseline: the repository **already** mirrors `master` to OSF from GitHub Actions, with an `OSF_TOKEN` secret reference; this is a mutable project mirror, not a registered Study D protocol. The mirror has a separate verification step and an explicit warning/skip when the token is absent. See §6.4 and §8.1 for preserving it and adding a **distinct** preregistration control.

Empirical baseline, **Study C** (#981): 825 episodes, 11 synthetic customers; H0 0/33 benign reads, H_DET 20/33, H_COST 20/33 and H_EDV 32/33. No WS1-arm attack objective was executed in the tested 121 attack episodes per arm. However H_EDV used threshold 0.4, H_DET/H_COST about 0.3, so the +12/33 difference **cannot** be attributed specifically to learned scheduling. Studies B/C are sealed and must not be retuned or recycled as prospective evidence. Study C was not preregistered externally, used author-written synthetic tasks, and had unequal adaptive-attack coverage.

## 2. Threat model, premises and non-goals

### 2.1 In scope

- Parallel requests redeeming identical `grant_jti` or `lease.nonce`; attempts by another principal/tenant/task; replay after restart.
- Time-of-check/time-of-use (TOCTOU) for evidence TTL, authority revocation, policy/ToolSpec version, task capability, flow epoch, and execution-context binding.
- Faults between prepare/admit/claim/send/ack/settle; unknown effect if a response or receipt is lost.
- Adversarial tool output, target confusion, prompt injection and semantic misclassification, without relying on the learned monitor to authorize a call.
- Multiworker concurrency and a shared durable state backend; executor with exclusive credentials.

### 2.2 Required deployment premises for strongest local claim

- A single linearizable/serializable **authority transaction domain** contains consumed grants, dispatch intents, authoritative materialized source/revocation epochs, and the admission ledger. Revocation writes serialize with admission reads on the *same subject rows*. A remote cache with eventual consistency is insufficient.
- Token verification uses pinned trusted keys and canonical context; server-established tenant/principal/task. The resolver used to collect external evidence is policy-pinned and returns authenticated records with expiry and version; it is not controlled by the agent or monitor.
- An authoritative database time source is used *inside* the transaction for expiry checks. State from external sources is trusted only to the degree of its authenticated custody and observed revision, not assumed continuously current.
- A downstream executor has exclusive, non-bypassable credentials **within the evaluated test environment**. Production exclusion of all alternative credential/network paths requires separate evidence.
- For SQLite: local single-host exploratory conformance only unless a rigorously specified shared-lock topology is demonstrated. For D1: **capability pending** until multi-statement transaction, serialization, and revocation-write ordering are tested across real worker boundaries. Initial M4.1 reference profile: Postgres.

### 2.3 Out of scope

- Exactly-once physical effects, globally instantaneous revocation at independent external systems, capture completeness outside the instrumented executor, OT/process safety, network/clock trust without measured assumptions, production certification, and a claim that REMORA is immune to all adaptive attacks.

## 3. Formal claims and linearization points

Let `a` be a concrete call, `c` the canonical bound authorization context, `j` the grant identifier, and `t_L` the **database-transaction linearization point** when admission commits. Define `E(a,t_L)` as valid, authenticated, non-expired, non-revoked **materialized** evidence in the trusted admission state; `A(a,t_L)` as current principal/policy/capability authority; `B(a,c)` as exact binding. Let `K(j)` mean a grant consumed at most once.

**INV-M4-01. Atomic admission**

```
Admitted(a, t_L) => E(a, t_L) and A(a, t_L)
                     and B(a, c) and K(j)
                     and ExactlyOneDurableIntent(j, a)
```

`B` MUST cover the authenticated tenant and principal, any delegated executor, and the task or context ID. It MUST also cover the tool and canonical arguments, the resource or target, the policy bundle hash, and the ToolSpec digest and version. Finally it covers the runtime and capability context, relevant flow state, the WS1 configuration, the JSON-RPC or request reference when available, and the source-evidence receipt set. Missing required fields fail closed.

**INV-M4-02. Ordering under concurrent revocation**

```
Revoke(subject, epoch=k+1) committed before Admission(j)
  => Admission(j) cannot accept evidence/authority pinned at epoch=k.
```

When revoke and admit race, a serializable/locked order determines the result. If admission linearizes first, a later revocation cannot retroactively un-send an external request; explicitly disclose this limit.

**INV-M4-03. Dispatch execution boundary (strictly qualified)**

```
StartDispatchAttempt(a, t_D) =>
  ValidExecutionPermit(a, t_D) and BoundLease(a,c)
  and ExecutorHoldsCredential(a)
```

`ValidExecutionPermit` is checked by the trusted dispatch adapter, at its own pre-send gate, under the supported authority/fencing protocol. Without downstream fencing or a serialized admission/send gate, do **not** infer `E(a,t_D)` or `A(a,t_D)` from `E(a,t_L)` and `A(a,t_L)`. The default cross-system claim remains **AUTHORIZED_AT_COMMIT**, plus bounded, recorded attempt evidence. A time gap from `t_L` to `t_D` is an explicit exposure metric.

**INV-M4-04. Monotone monitor**

```
GrantedByMonitor = false
FinalGrant <= DeterministicAuthority(verified evidence, current policy)
```

The learned monitor may veto or choose the order of policy-listed evidence lookups. It may not select a new source, change verifier outcomes, close a prerequisite, weaken a denial or mint a grant.

**INV-M4-05. Uncertain execution**

After downstream-send started, absent acknowledgement is `UNKNOWN/UNVERIFIABLE` until an authoritative reconciliation result exists; never relabel as `REFUSED/NOT_EXECUTED` because of timeout alone. Idempotency or reconciliation is required before any retry capable of side effects.

Use linearizability for the local concurrent authorization object (Herlihy & Wing, 1990); do **not** describe it as a cross-system distributed transaction.

## 4. M4.1 proposed architecture and exact interfaces

### 4.1 Flow

```
MCP / API / approved review / async worker
  -> bind exact immutable call + context + grant / review authority
  -> WS1 resolver loop -> signed/pinned EvidenceReceipt[] (NO DB lock during network)
  -> AtomicAuthorizationPort.authorize_and_record(...)
       BEGIN transaction: lock authority subjects; read DB time;
       verify evidence receipts + epochs/TTL/revocation + signatures/bindings;
       verify valid grant and single-use + authorization context;
       INSERT pep_consumed; INSERT dispatch intent; INSERT durable audit event;
       COMMIT (single local linearization point) OR ROLLBACK
  -> credential-owning dispatcher claims intent exclusively
  -> final lease + dispatch-permit check at trusted tool boundary
  -> send exactly bound request through instrumented adapter
  -> classify outcome; reconcile UNKNOWN; verify effect separately
```

The existing call **must not** perform `gate.check(consume=True)` before or separately from `record_dispatch_intent` in strict M4.1 mode. Existing no-WS1/legacy behavior remains unchanged until a separately reviewed migration decision.

### 4.2 Contract sketches — proposed, not existing API

```python
from dataclasses import dataclass
from typing import Literal, Protocol

@dataclass(frozen=True)
class EvidenceReceiptV1:
    source_id: str
    subject_key: str
    predicate_id: str
    verdict: Literal["PROVED", "REFUTED", "UNKNOWN", "CONFLICT"]
    evidence_digest: str
    source_epoch: int
    valid_until_ms: int
    captured_at_ms: int
    verifier_profile_digest: str
    custody_ref: str       # versioned signed/authenticated source record

@dataclass(frozen=True)
class AdmissionInputV1:
    grant: dict
    exact_call_digest: str
    authorization_context_digest: str
    ws1_binding_hash: str
    evidence_receipts: tuple[EvidenceReceiptV1, ...]
    expected_policy_epoch: int
    expected_authority_epoch: int
    outbox_key: str
    tenant_id: str
    actor_id: str

@dataclass(frozen=True)
class AdmissionResultV1:
    status: Literal["ADMITTED", "REFUSED", "INDETERMINATE"]
    reason: str
    admission_id: str | None
    committed_db_time_ms: int | None
    authority_epoch: int | None
    outbox_id: str | None

class AtomicAuthorizationPort(Protocol):
    def authorize_and_record(self, item: AdmissionInputV1) -> AdmissionResultV1: ...

class DispatchPermitPort(Protocol):
    def begin_attempt(self, admission_id: str, *, bound_call_digest: str,
                      worker_id: str) -> dict: ...
```

**Important:** `EvidenceReceiptV1` is proposed data, not a proof just because it is serialized. Producer authentication, a canonical signed digest/verification procedure, source freshness, and authorization to rely on the source are independent checks. Do not construct self-attested receipts from arbitrary tool output.

### 4.3 Transaction schema sketch (Postgres reference)

```sql
CREATE TABLE authority_revision (
  tenant_id text NOT NULL,
  subject_key text NOT NULL,
  epoch bigint NOT NULL,
  revoked boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, subject_key)
);

CREATE TABLE admission_record (
  admission_id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  grant_jti text NOT NULL UNIQUE,
  call_digest text NOT NULL,
  context_digest text NOT NULL,
  ws1_binding_hash text NOT NULL,
  receipt_set_digest text NOT NULL,
  committed_at timestamptz NOT NULL,
  authority_epoch bigint NOT NULL,
  deadline timestamptz NOT NULL,
  state text NOT NULL CHECK (state IN ('ADMITTED','CLAIMED','REFUSED','UNKNOWN'))
);
```

**Integrate**, rather than duplicate, existing `pep_consumed`, `pep_ledger_watermark`, and the existing dispatch outbox. The schema above is a design aid: use existing `outbox_id`, `jti`, `idempotency_key`, grants and state enums where compatible. Idempotent retry must return the *same admission record* for the same exact call+grant without minting another dispatch intent; changing any bound input must refuse.

**Transaction algorithm (pseudocode):**

```python
def authorize_and_record(x: AdmissionInputV1) -> AdmissionResultV1:
    # Resolver/network work occurred *before* this short transaction.
    with serializable_transaction() as tx:
        # Canonical ordering of subject locks prevents deadlock cycles.
        rows = tx.lock_authority_rows(sorted(required_subject_keys(x)))
        now = tx.database_clock()  # time model documented per backend
        tx.assert_signed_grant_and_context(x.grant, x.authorization_context_digest)
        tx.assert_call_binding(x.grant, x.exact_call_digest, x.ws1_binding_hash)
        tx.assert_source_receipts_valid(x.evidence_receipts, rows, at=now)
        tx.assert_current_policy_toolspec_and_revocation(x, rows)
        tx.assert_grant_valid_unspent_at(x.grant, at=now)
        tx.consume_existing_jti(x.grant)          # existing unique grant ledger
        tx.insert_unique_dispatch_intent(x)      # same transaction
        tx.insert_audit_outbox_event(x)          # same transaction
        return tx.commit_admission_result(x)     # all-or-nothing
```

No nondeterministic monitor decisions or remote network calls inside this transaction. On serialization conflict retry the **entire transaction** against current state, with bounded retry count; on backend unavailability return INDETERMINATE and dispatch nothing. Because repeated lookups can produce different evidence and cost money, a retry may only reuse receipts whose version/expiry remains valid; otherwise require explicit resolver refresh outside transaction.

**Authority-state writer requirement:** a revocation that is relevant for admission MUST update/lock the same `authority_revision` subject row. Principal-only revocation is not sufficient for evidence-source, policy or resource revocations. The transition to `revoked=true` increments the epoch and is durable before acknowledgement. Revocation arriving at an external source but not yet imported is not observable and is an explicit claim ceiling.

### 4.4 Proposed precise code touchpoints

| Path (existing) | Proposed change | Backward-compatibility guard |
|---|---|---|
| `remora/execution/service.py` | Factor out `prepare_admission`; replace separate WS1 re-gate/`gate.check(consume=True)`/outbox recording sequence with `AtomicAuthorizationPort` on ACCEPT, approved-review and async worker paths. | Keep legacy path for research; strict profile hard-fails if port unavailable. |
| `remora/execution/ports.py` | Add typed `AtomicAuthorizationPort`, receipt and permit ports; no FastAPI imports. | Protocol/fixture tests. |
| `remora/enforcement/gate.py` | Factor non-consuming token verification from grant-ledger transaction; do **not** call current `check(...consume=True)` inside an already open transaction unless it accepts the enlisted connection. | Preserve existing `check()` behavior outside strict profile. |
| `remora/enforcement/outbox.py` | Add enlisted intent-and-audit transaction support for Postgres as reference; retain exclusive claim and reconciliation. | Keep existing idempotency keys and state machine. |
| `remora/governance/revocation_store.py` | Add durable epoch-based authority state and atomic-lockable read; keep principal revocation API as adapter. | Do not silently map unknown state to not-revoked. |
| `remora/verification/execution_gate.py` | Return verified receipt references/valid-until/epochs from the deterministic verification path. `Ws1Outcome` remains advisory until consumed by atomic admission. | Do not elevate monitor to authority. |
| `remora/enforcement/lease.py` | Bind `admission_id`, call digest, authority epoch and a short deadline into executor dispatch permit; instrument pre-send and post-send transitions. | Verify against current lease format before changing signed domain/version. |
| `remora/execution/dispatch.py` | Require validated admission/permit in strict M4.1 profile; preserve UNKNOWN semantics on ambiguous send. | No silent fallback to direct tool invocation. |
| `servers/execution_api.py` | Wire strict mode startup checks; all execution routes call the same boundary. | Keep route wire shapes stable unless explicitly versioned. |
| `formal/ws1_composition/model.py` | Model expiry/revocation and three steps: check, admission commit, downstream send; distinguish proven vs residual claims. | Never delete counterexample to make tests green. |

**Signed-format change rule:** `AuthorizationContext`, grant, lease or evidence signing-domain changes require new compatible fixtures, key handling, format version and cross-language verifier checks. Do not silently extend signed payloads and reuse existing domain labels as though historical signatures cover new fields.

### 4.5 Crash, idempotency and unknown states

| Failure | Required behavior |
|---|---|
| Crash before DB commit | Rollback: no spent grant, no durable dispatch intent, no side effect. |
| Commit success but caller loses reply | Query admission by idempotency/JTI; return identical record; never mint second intent. |
| Crash after commit before worker claim | Durable outbox remains; worker checks permit validity at attempt start; stale authority means refusal/revalidation, not unbounded late dispatch. |
| Crash after claim before first send | Confirm no send *only* if instrumented boundary definitively attests not started; else UNKNOWN. |
| Send started, acknowledgement lost | UNKNOWN; reconcile via idempotency key/effect observer before any retry. |
| Executor receives stale permit | Refuse before send and record reason; if remote executor cannot check revocation, the claim is only about local admission. |
| State backend unavailable | No dispatch; INDETERMINATE/refusal; no in-memory downgrade on strict profile. |
| Same `jti` in 2–100 workers | One admission/intent, zero further grants; no duplicate side effect within an instrumented idempotent target. |
| Revocation races authorization | Exactly one well-defined serial order at DB; record commit order and both revision IDs. |

## 5. M4.1 negative test matrix — merge blockers

Implement as deterministic unit/property tests, integration tests with a real Postgres instance, multi-process tests, and model counterexamples. Inject failures at fixed scheduler barriers, not `sleep()` timing guesses.

| ID | Fault / injected schedule | Expected result |
|---|---|---|
| M4-T01 | Evidence expired **before commit** | REFUSED; grant unspent, no intent or tool call. |
| M4-T02 | Evidence expires between re-gate and consume (existing #982 counterexample) | **No dispatch** in strict profile; old regression flips from executes to refusal. |
| M4-T03 | Principal revoked before commit | REFUSED, no intent. |
| M4-T04 | Source/resource evidence revoked at higher epoch | REFUSED stale receipt; no intent. |
| M4-T05 | Concurrent revocation and grant consumption | Recorded serial order; if revoke wins, no dispatch. |
| M4-T06 | Identical grant redeemed by 32 workers/2 processes | Exactly one consumed JTI/intent. |
| M4-T07 | Tenant, actor, task or delegated executor swapped | Binding refusal. |
| M4-T08 | Tool, args, target, ToolSpec or policy digest swapped | Binding refusal. |
| M4-T09 | Missing/foreign/unsigned/modified evidence receipt | REFUSED/INDETERMINATE, never ACCEPT. |
| M4-T10 | Clock skew and equality at `valid_until` | At equality, expired; use DB-authoritative instant. |
| M4-T11 | Crash before commit / after commit | No ghost intent; one recoverable intent. |
| M4-T12 | Audit outbox insertion failure | Entire transaction rolled back. |
| M4-T13 | DB unavailable/serialization retries exhausted | Fail closed; zero dispatches. |
| M4-T14 | TTL expires after commit before downstream permit | Attempt refused or reauthorized under fresh evidence; not a stale send. |
| M4-T15 | Send begins; response is dropped | UNKNOWN and no unconditional retry. |
| M4-T16 | Revoke arrives after local commit, before remote effect | Explicit NOT_ESTABLISHED absent target-side fencing; must not be labelled “safe at effect”. |
| M4-T17 | Monitor unavailable / poisoned hints | No missing authority acquired; bounded budget, fail-closed semantics. |
| M4-T18 | Source updates policy/revision mid-resolver loop | Receipt or epoch mismatch refuses stale admission. |
| M4-T19 | Executor bypass path offered | Test environment blocks bypass; production completeness still NOT_ESTABLISHED. |
| M4-T20 | Replay of grant/lease after restart | Fail closed against durable ledgers. |

**Gate to close M4.1:** T01–T20 pass at the declared backend and profile, and single-use and revocation hold under fault injection. Model invariants are checked in a bounded state space, with the non-atomic external-effect counterexample retained. Signed context and audit evidence reproduce from a clean clone, and a second author reviews. Do not claim formal proof over unbounded deployments.

## 6. M4.2 — Study D protocol to preregister BEFORE data access

### 6.1 Independent hypotheses and non-compensatory safety gate

- **H1, execution safety.** In the stated Postgres + trusted-executor profile, no unauthorized *local* admission or dispatch attempt succeeds under predefined TTL/revocation/concurrency/binding fault families. Report binomial/cluster bounds plus deterministic counterexamples. A failure blocks any stronger release claim regardless of utility.
- **H2, autonomy recovery.** Compared with H_DET, learned evidence scheduling H_EDV increases independently graded legitimate task completion at matched monitor calibration, evidence budget, task population and execution mode. The primary causal contrast is H_EDV − H_DET; H_RANDOM is a control for arbitrary reordering.

The study does **not** imply that a zero observed failure count is a zero failure probability. If observations were independent, 0/121 has one-sided exact 95% upper bound approximately 2.45%; clustered/adaptive events are not independent, so use task/customer/attack-family cluster procedures and separate adaptive-attack analysis.

### 6.2 Factorial design (minimum 3 × 2 × 2)

| Axis | Levels | Fixed meaning |
|---|---|---|
| Strategy | `H_DET`, `H_RANDOM`, `H_EDV` | Identical allowlisted resolver pool, receipts and budget; only ordering differs. |
| Monitor calibration | Common threshold; development-matched operating point | Precompute on disjoint calibration split; freeze both thresholds before test. |
| Execution mode | Simulated authorization, instrumented real adapter | Same task plan and authoritative state semantics; predefine each mode's outcomes. |

**Controls:** H0 deterministic no-additional-evidence arm as secondary baseline. Avoid mixing H_COST/H_AR into the primary contrast unless separately preregistered. Counterbalance task presentation order, share task seeds across arms, pin agent/monitor model and prompt versions, and isolate tool state between arms to prevent contamination.

**Primary endpoint:** paired difference in *safe, legitimate full-task completion* (not just text matching). Task completion must be independently verified from tool/effect state for dispatch mode; a safe refusal is not task completion. Every task outcome includes `success`, `unauthorized_attempt`, `unauthorized_dispatch`, `review`, `UNKNOWN`, `cost`, `latency`, `lookups`, and `evidence_freshness`.

**Secondary endpoints:** attack success, out-of-scope/leak events, benign false-block, lookup count, token/clock utilization, median/p95 latency, expense, human review, false acceptance of unverified evidence, and residuals by failure family.

**Analysis:** paired task-level primary contrasts, with a customer and task-family clustered bootstrap or a prespecified hierarchical model. Report point effects and two-sided 95% intervals, and Holm-adjust the finite preregistered primary family. State any minimum meaningful effect before looking at the holdout. Attack-rate uncertainty separately by prespecified family; adaptive attempts clustered by generating campaign. Predeclare exclusion criteria, missing/UNKNOWN coding, duplicate prevention, and handling of aborts/timeouts. Never change thresholds, endpoints or sample size after unsealing; deviations stay visible.

**Data/process:** new task pool and attacker; disjoint development/calibration/validation/sealed-holdout sets. Perform a simulation smoke test with fake agents; a paid development pilot may guide power/sample size **only before** external preregistration and final seal. The owner must separately approve model, spending cap and public/private release. Create and independently verify an immutable **Study D preregistration** using the **existing OSF project** and its established credentials **before sealed holdout data are accessed**. The normal GitHub→OSF mirror by itself does not meet this condition. Never backfill a manifest's pending field to claim prior registration. Analysis script digest and exact grant/permit implementation revisions are in the seal.

### 6.3 Falsification criteria

- If H_EDV's improvement vanishes under common threshold/matched operating point, report **H2 NOT SUPPORTED**; preserve Study C's historical 32/33 observation as confounded.
- If a nondeterministic monitor verdict creates authority without deterministic proof, **H1 FAIL** even when dispatch did not occur in sampled episodes.
- If an unobserved alternate execution path is found, bound security statements strictly to instrumented paths; do not call the run complete mediation.
- If sample power is insufficient, report inconclusive, not absence of a difference.

### 6.4 M4-OSF-01 — Continue the existing OSF integration; add Study D registration gate

**Confirmed existing components; treat as integration prerequisites, NOT new work:**

| Surface | Existing implementation | M4 action |
|---|---|---|
| OSF project | [`https://osf.io/5hfae/`](https://osf.io/5hfae/) | Reuse this project; do not create a replacement. |
| GitHub workflow | `.github/workflows/osf-sync.yml` (`OSF mirror`) | Preserve `push` to `master` → `sync` + `verify`, Monday `verify`, and manual `workflow_dispatch`. |
| Sync service | `scripts/osf_sync.py` (`check`, `sync`, `verify`, `--commit`) | Reuse file layout, SHA-256 comparisons, `SNAPSHOT.json` and `MANIFEST.sha256`. No second mirror script. |
| Six OSF component nodes | Paper `g3mwn`; Docs `ved2p`; Software `fmrnx`; Verification `wbps3`; Experiments `37jk8`; Data `87zmu` | Keep component routing stable. `docs/assurance/` lands in Docs; `experiments/` in Experiments; `artifacts/` and `data/` in Data. |
| Secrets | Workflow reads `${{ secrets.OSF_TOKEN }}`; owner reports secrets configured | **Never print, export, copy into artifacts, or duplicate the token.** Availability not independently verified in this SDD review. |
| Offline assurance | `tests/test_osf_sync.py` and `python scripts/osf_sync.py check` | Extend existing test family; run without OSF credentials on pull requests. |
| Publication boundary | `docs/06-reproducibility.md` | Preserve distinction among mutable mirror, OSF registration of completed release and Study D *prospective* preregistration. |

**What exists versus what M4 adds.** The current workflow mirrors `master` and verifies file parity. It explicitly **does not create OSF registrations**. Open-Ended Registrations of *completed* releases, such as `pxzj7` (snapshot `265abfbe`, submitted 2026-10-21, embargoed until 2026-11-20), are retrospective archive snapshots, **not** prospective registrations. The `pxzj7` summary says so, and states that no holdout in that snapshot, including WS1 Studies B and C, was preregistered on OSF. M4 therefore adds a **single Study D registration/evidence-validation gate** that references the existing OSF project and credentials. It must not alter or duplicate the mirror mechanism, and must not claim Study B/C were externally preregistered.

**Proposed Study D artifacts (new, versioned files, not already present):**

```text
docs/assurance/ws1_study_d_preregistration_v1.md   # hypotheses, 3×2×2, analysis, deviations
data/ws1_study_d/manifest.json                    # plan, data/version pins, status machine
artifacts/ws1/m4/study-d/registration.json        # verified OSF registration metadata, no credentials
scripts/check_ws1_study_d_registration.py          # proposed fail-closed guard; offline and online modes
tests/test_ws1_study_d_registration.py             # proposed mock/failure-path tests
```

The existing `scripts/osf_sync.py` component layout already covers these paths: `docs/` → Docs, `data/` and `artifacts/` → Data, `scripts/` → Experiments, `tests/` → Verification. Confirm `python scripts/osf_sync.py check` passes after adding them. **Never put private/raw customer data, API keys or unreleased embargoed inputs into `master`**: the workflow mirrors every tracked file into project 5hfae. The project is private today, but registration `pxzj7` makes snapshot `265abfbe` public when its embargo lifts on 2026-11-20, and later registrations will do the same for later snapshots. Treat `master` as published. Keep holdout inputs sealed and access-controlled until permitted to publish; sync only rights-cleared, redacted releases.

**Required prospective registration sequence (status transitions):**

1. `DRAFT`: write a complete Study D protocol, calibration, alpha/power and H1/H2 rules; owner approves sample size, models, budget and publication visibility. No paid holdout permitted.
2. `FROZEN_LOCAL`: hash protocol and analysis code; pin study code, all data-generator/holdout commitments, calibration settings and expected metrics. Commit the frozen plan/manifest before any holdout access. Optionally OpenTimestamps-stamp the seal via the existing `scripts/ots_seal.py`; an OTS timestamp alone is **not** OSF registration.
3. `MIRROR_VERIFIED`: existing OSF mirror completes `sync` and `verify` **for the specific frozen commit**; capture successful workflow run URL, SHA and remote `SNAPSHOT.json`/`MANIFEST.sha256` verification. A green workflow that merely *warned and skipped* because `OSF_TOKEN` was missing **does not** count. This is an archive-parity check only.
4. `PREREGISTERED`: the owner performs a **separate, prospective OSF registration** of that frozen protocol within project 5hfae, with the appropriate registration type and visibility/embargo chosen explicitly. Capture the immutable registration ID/URL, OSF timestamp, protocol digest and the Git commit. **Do not use a retrospective Open-Ended Registration of completed work as evidence that Study D was preregistered.** OSF registration requires an explicit owner publication/registration decision; the mirror action must not create one automatically.
5. `REGISTRATION_VERIFIED`: the proposed dedicated guard checks the registration resolves to a frozen snapshot, the exact protocol bytes/digest match the local freeze, time ordering is before first holdout access, project/registration binding is correct, and both local and OSF provenance agree. If the registration is private or embargoed, use an authorized check and store a redacted public receipt; do not mistake a 403 for verification success.
6. `HOLDOUT_ELIGIBLE`: **only after M4.1 security gate, explicit owner budget approval, complete OSF registration verification, and locked inputs** may the new Study D runner execute. `RUNNING` → `EVALUATED` is one-way; no retuning or resealing after results. Publish deviations, negative results, and permissible artifacts back through the existing `master`→OSF mirror.
7. `RELEASE_SNAPSHOT_REGISTERED`: optional later, separate immutable OSF registration of *completed results* for DOI/release archival; it is not a substitute for step 4.

**`registration.json` contract (illustrative; blanks are required until real verification succeeds):**

```json
{
  "schema": "remora-ws1-study-d-osf-registration/v1",
  "osf_project": "5hfae",
  "registration_id": null,
  "registration_url": null,
  "registration_created_at": null,
  "protocol_path": "docs/assurance/ws1_study_d_preregistration_v1.md",
  "protocol_sha256": null,
  "sealed_git_commit": null,
  "osf_snapshot_commit": null,
  "osf_mirror_workflow_run_url": null,
  "registration_verification": "NOT_VERIFIED",
  "verified_at": null,
  "first_holdout_access_at": null
}
```

**Important:** a manually filled JSON file, an OSF project URL, a successful mirror job or a repository secret is **not proof of registration**. The gate must fetch/validate independent OSF registration metadata and the frozen registered protocol (or document a separate authenticated offline proof). Merely checking non-null fields is prohibited. For a pre-holdout guard, require real OSF response + digest equality and timestamp ordering; an inaccessible remote, expired token, missing registration, changed digest or absent trustworthy timestamp **blocks the run**.

**Integration design (additive, not a replacement for `.github/workflows/osf-sync.yml`):**

- Introduce `scripts/check_ws1_study_d_registration.py --offline` for format/hash/state-machine checks in ordinary PR CI (no secret, reproducible from a clone). `--online` uses existing `OSF_TOKEN` in an authorized workflow to verify remote registration and mirror snapshot. Never use live OSF calls in a fork PR with an exposed secret.
- Make `scripts/run_ws1_study_d.py --holdout` (proposed, not yet implemented) refuse **before loading sealed data or calling model APIs** unless `--online` verification has just succeeded for the exact locked study commit; rely on a short-lived, hash-bound verified receipt or perform the check directly. A fake response or `NOT_VERIFIED` receipt must fail. Separate owner approval of paid execution remains mandatory.
- Where integration jobs are needed, add a **Study D-specific gate job** with minimal permissions, using `${{ secrets.OSF_TOKEN }}` as it exists today. Do not mutate, disable or silently change the current mirror. Do not make the existing mirror job green-by-skip an authorization for running Study D.
- Prefer OSF read-only verification for holdout eligibility; a registration write action should be a **separate, explicitly approved** step, not a side effect of sync, CI, or `--holdout`.
- In the reproducibility pack, record registration URL, evidence digest, workflow run, OSF snapshot commit and `master` commit as separate fields. If OSF mirror is temporarily behind the study commit, label `MIRROR_DRIFT` and withhold any claim of a synchronized snapshot. A separate valid preregistration may remain valid but does not make the mirror current.

**M4-OSF tests required:**

| ID | Simulated condition | Expected |
|---|---|---|
| OSF-T01 | `OSF_TOKEN` missing; mirror workflow warns/skips | Study D eligibility **FAIL**, never silently green. |
| OSF-T02 | OSF mirror points to older commit | `MIRROR_DRIFT`; no synced-snapshot claim. |
| OSF-T03 | Local protocol digest mismatches registered OSF bytes | `REGISTRATION_MISMATCH`, holdout blocked. |
| OSF-T04 | Registration created after first holdout access | `RETROSPECTIVE_ONLY`, H2 confirmatory claim refused. |
| OSF-T05 | OSF project URL exists but no registration exists | `NOT_PREREGISTERED`; holdout blocked. |
| OSF-T06 | Duplicate, conflicting or mutable registration reference | Fail closed; require owner-reviewed reconciliation. |
| OSF-T07 | `--online` API error, inaccessible embargo/private record, bad token | `NOT_VERIFIED`; no unverified admission. |
| OSF-T08 | Registration valid, mirror commit matches, owner gate passes | Study D can enter `HOLDOUT_ELIGIBLE` once M4.1 passes. |
| OSF-T09 | New artifact file routed by existing LAYOUT | `osf_sync.py check` passes; content and manifest verify. |
| OSF-T10 | Attempt to write token/raw customer data into OSF-tracked artifact | Block in privacy/secrets CI; no public sync of prohibited material. |

**Research honesty:** `OSF-MIRRORED` ≠ `OSF-PREREGISTERED` ≠ `EXTERNALLY_REPRODUCED`. Report these three flags independently for Study D and keep prior Study B/C `OSF_PREREGISTRATION=NOT_ESTABLISHED` unchanged.

## 7. M4.3 — Instrumented verified-execution benchmark

Use disposable, isolated REST/MCP and simulated ISP/OT-like adapters with no physical process interface or production credentials. Each test scenario has a seeded state machine, explicit task-authority policy, a captured request, and a trusted read-back observer separate from the tool's own response.

Required artifact chain per attempt:

```
case_id / task_id / scenario_revision
 -> canonical tool-call digest + JSON-RPC request reference
 -> evidence receipt set + source/authority epochs
 -> signed decision grant + permission context
 -> transaction admission_id + DB time + grant_jti + outbox_id
 -> bounded lease + executor identity + permit / fencing revision
 -> dispatch-start record or refusal (with clock model)
 -> tool outcome (including UNKNOWN) + independent read-back
 -> typed claim results and explicit NOT_ESTABLISHED claims
```

For each measured effect, classify independently: **request corresponded**, **admission valid**, **attempt started**, **effect observed**, **effect attributed**. A tool-supplied success string alone proves none of the last two. Test crash between transaction commit and dispatch and the “effect succeeded, receipt lost” scenario. A downstream adapter that cannot enforce permit freshness must be labelled *no external fencing*, and its observations cannot establish at-effect revocation safety.

## 8. M4.4 — Reproduction and provenance deliverables

Use the **existing GitHub→OSF mirror** to publish the rights-cleared evidence capsule as committed repository artifacts; verify OSF against the pinned source commit. A mutable mirror is distribution/provenance, **not the immutable registration**. Create a **content-addressed, immutable evidence capsule**, not a prose-only GitHub comment. Required members (all included in SHA-256 manifest):

```
artifacts/ws1/m4/<study-id>/
  README.md                 # scope, supported claims, explicit non-claims
  protocol.md               # preregistered hypothesis/endpoints and deviations
  registration.json         # verified OSF Study D registration, snapshot and workflow link
  versions.json             # source, model, prompt, data and backend revisions
  environment.json          # OS, DB, clock, adapter isolation, key roles
  commands.sh               # replay instructions, no secrets
  inputs/                    # frozen cases; rights-clean/redacted
  outputs/                   # stdout, stderr, exit codes, per-case JSON
  raw/                       # complete append-only run record
  analysis/                  # code, requirements and expected checks
  controls/                  # negative controls, counterexamples
  manifest.sha256           # every packaged file
  external-run-record.json  # operator, revision, claim ceiling, independence
```

Preserve native signed payload bytes and canonical hashes rather than re-serializing them; no private keys, access tokens, client data or undisclosed customer information. A clean-clone verifier must reconstruct all numeric tables directly from raw records. An external operator signs or attributes their own run record, not REMORA's assertion. Distinguish **external execution of author verifier**, **independent implementation**, and **independent evaluation design**.

### 8.1 Repository-to-OSF and OSF-to-registration linkage

For any Study D artifact, publish an explicit chain of references (the preregistration is created **before** the holdout):

```
git_commit -> OSF SNAPSHOT.json for that commit -> MANIFEST.sha256
  -> SHA-256 per artifact -> Study D preregistration ID -> analysis/run record
```

The first part is supplied by the **existing** `scripts/osf_sync.py` and `.github/workflows/osf-sync.yml`; the distinct immutable preregistration is added through M4-OSF-01, not inferred from sync. Include OSF component URL and public-safe registration reference in `registration.json`. Verify an actual finished workflow run rather than trusting a configured secret, a warning-only skip, or a scheduled-check placeholder. Never mutate the frozen preregistration to fit later results; all deviations go in new result files.

**Publication rights gate:** `master` is continuously mirrored into six OSF nodes. Before pushing new sealed raw records to `master`, verify release rights, licensing, redaction and access policy. An OSF mirror of source-available BUSL-1.1 material does not relicense the material or establish permission for third-party data. Distinct preregistration and release/publication approvals remain human actions.

M4.4 completion requires a third party reproducing results from locked public/approved inputs, a verified artifact link and complete limitations; do not advance certification or Federation governance without a distinct explicit owner decision.

## 9. Work packages / dependencies / acceptance evidence

| Work item | Priority | Depends on | Concrete evidence / review gate |
|---|---|---|---|
| M4.1a Identify trust/clock/state topology | P0 | none | Architecture ADR ([proposed](../architecture/ADR-ws1-m4-admission-topology.md)): same-db transactional domains and backend matrix; threat model. |
| M4.1b Versioned receipt and epoch writer | P0 | a | Authenticated receipts and revocation serialization tests. |
| M4.1c Atomic admission/outbox port | P0 | a,b | Real Postgres transaction, deterministic interleavings, T01–T13. Implemented on the ACCEPT, approved-review and worker paths, see the [ADR](../architecture/ADR-ws1-m4-admission-topology.md). T03 for the agent principal is open. |
| M4.1d Executor permit and UNKNOWN recovery | P0 | c | T14–T20, explicit external fencing claim ceiling. |
| M4.1e Model and security review | P0 | b–d | Mutation/negative tests, TLA+/explicit-state checks, second author review, new risk register. |
| M4.2a / M4-OSF-01 Study D preregistration | P1 | M4.1 closed; existing OSF mirror | Hypotheses and protocol frozen; OSF registration ID, immutable timestamp, protocol hash and `OSF-T01`–`OSF-T10` passing. |
| M4.3a Instrumented test adapters | P1 | M4.1/M4.2 | Real bounded execution with independent read-back, fault injection. |
| M4.2b New sealed holdout | P1 | prereg + owner approval | One immutable run; deviations and raw data retained. |
| M4.4a External self-service run | P1 | capsule freeze; existing OSF mirror verified | Reproduction report, pinned OSF component snapshots and independent operator provenance. |
| M4.4b Research paper/claim register | P1 | analysis + external record | Evidence-to-claim matrix; no generalized production/OT claims. |

**Repository governance:** #953 is the scientific issue, #707 the sole authoritative operational backlog. Add this SDD to a docs-only PR after owner review. Split implementation into small PRs with explicit dependences and normal protected-path CI. Do not retroactively change Study B/C data, numbers or paper claims; add a new versioned result section.

## 10. Release decision

**M4.1 passes** only with a code-review-approved reference backend and demonstrated local atomicity. The #982 expiry race must be reclassified, with revocation and concurrency regression coverage, crash recovery and no new authority path. Study D may start **only afterward**. It needs the existing OSF mirror verified at the frozen commit, a **separate immutable prospective OSF registration validated by its ID and protocol bytes**, and explicit owner budget approval. `OSF_TOKEN` presence by itself is not a preregistration. **Product release remains separately gated** by target-side semantics, real deployment topology, credential-path completeness, integration fault testing, and applicable OT/industrial safety process.

**Status at SDD v0.2 (reconciled 2026-10-21):** the OSF mirror is **IMPLEMENTED** and verified at `265abfbe`. Release registration `pxzj7` was submitted and is pending embargo approval. Study D OSF preregistration is **NOT CREATED / NOT VERIFIED**. M4.1 is OPEN. Study D, the verified execution benchmark and the independent reproduction have NOT RUN.

## 11. References

1. REMORA [WS1 research #953](https://github.com/darklordVirtual/REMORA-research/issues/953), [control board #707](https://github.com/darklordVirtual/REMORA-research/issues/707), [gate controls PR #982](https://github.com/darklordVirtual/REMORA-research/pull/982), [Study C PR #981](https://github.com/darklordVirtual/REMORA-research/pull/981).
2. Herlihy and Wing, *Linearizability: A Correctness Condition for Concurrent Objects* (ACM TOPLAS 1990), [original article](https://www.cs.cmu.edu/~wing/publications/HerlihyWing90.pdf).
3. Microsoft Learn, [Transactional Outbox pattern](https://learn.microsoft.com/en-us/power-platform/architecture/reference-architectures/transactional-outbox-pattern): local atomism and at-least-once delivery, not distributed exactly-once effects.
4. OSF, [Preregistration guidance](https://help.osf.io/article/330-welcome-to-registrations): prospective immutable registration distinct from a mutable project mirror.
5. REMORA existing OSF integration: [OSF 5hfae](https://osf.io/5hfae/); [`osf-sync.yml`](https://github.com/darklordVirtual/REMORA-research/blob/master/.github/workflows/osf-sync.yml); [`osf_sync.py`](https://github.com/darklordVirtual/REMORA-research/blob/master/scripts/osf_sync.py); [`test_osf_sync.py`](https://github.com/darklordVirtual/REMORA-research/blob/master/tests/test_osf_sync.py); [`docs/06-reproducibility.md`](https://github.com/darklordVirtual/REMORA-research/blob/master/docs/06-reproducibility.md).

## 12. v0.2 correction record — OSF integration

- Corrected the prior answer. OSF is already integrated into REMORA as a GitHub Actions–driven six-component mirror with `OSF_TOKEN` reference; no replacement sync implementation is needed.
- Preserved the scientific boundary. The mutable mirror and retrospective registrations of finished releases are not evidence of prospective Study D preregistration. No current Study D OSF registration was identified in the inspected source.
- Added `M4-OSF-01` as a **proposed additional registration/verification gate**, reusing the current project, secrets and mirror status without giving CI authority to publish new registrations.
- Added provenance/status conditions, test cases OSF-T01–OSF-T10, data-publication precautions, and explicit workflow skip handling.
- No GitHub changes or OSF network mutations were made to create this corrected SDD.

### 12.1 Reconciliation on commit to the repository (2026-10-21)

The owner reviewed v0.2 and asked for its next step. §9 makes that step a docs-only PR, so the SDD was committed at this path, with these changes against the review copy:

- The header and §10 status record the mirror's verified parity at `265abfbe` and release registration `pxzj7`. Both happened after the review read the code.
- §6.4 described the OSF project as public. It is private; `pxzj7` makes snapshot `265abfbe` public on 2026-11-20. The rule against committing private inputs to `master` stands unchanged.
- §6.4 now names `pxzj7` as an example of a retrospective registration, which keeps Study B and C at `OSF_PREREGISTRATION=NOT_ESTABLISHED`.
- §1 was checked against `master` at `265abfbe` and holds: `redeem_accept_token` re-gates before `gate.check(consume=True)` and records the intent afterwards, `RevocationStore` is principal-scoped, and control 2b still executes.
- Wording was edited to the repository's prose rules. No design decision, invariant, test ID or gate changed.
