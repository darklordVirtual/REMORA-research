# WS1-M4.1 closure record, v1

- Status: owner decision recorded 2026-11-03. Second-author review requested on the PR that carries this file.
- Parent: [M4 SDD §4, §5](../design/ws1-m4-safe-autonomy-recovery-v0.2.md), gate "to close M4.1".
- Decision owner: [#953](https://github.com/darklordVirtual/REMORA-research/issues/953).
- Evidence: `artifacts/ws1/m4/m4_1_closure/sec99-20261103T194032Z-dee87d1a/` and `artifacts/ws1/m4/sec99-reproduction/sec99-20261103T194032Z-dee87d1a/`.
- Source: `dee87d1a` (= `dev` `53e04f47` plus PR #1162's unwired `remora/verification/monitor_discharge.py`, which none of the suites below import)

## 1. What the gate asks

The M4 SDD closes M4.1 on five conditions. T01 to T20 pass at the declared backend and profile. Single-use and revocation hold under fault injection. Model invariants are checked in a bounded state space, with the non-atomic external-effect counterexample retained. Signed context and audit evidence reproduce from a clean clone. A second author reviews. It forbids claiming formal proof over unbounded deployments.

## 2. Test matrix at the reference backend

Backend: PostgreSQL 16 (`postgres:16-alpine` in Docker 28.4.0), `REMORA_PG_DSN` set, so every parameterized case ran on both SQLite and Postgres. Suites: `tests/test_atomic_admission.py`, `tests/test_ws1_m4_fault_matrix.py`, `tests/test_ws1_atomic_admission_route.py`, `tests/test_ws1_gate_controls.py`, `tests/test_audit_outbox_atomicity.py`, `tests/test_effect_receipt_atomicity.py`, `tests/test_admission_gate.py`, `tests/test_review_admission_grant_withheld.py`, `tests/test_execution_fault_injection.py`. JUnit record: `m41-postgres-junit.xml`; per-case summary: `m41-postgres-summary.json`.

| Measure | Value |
|---|---|
| Tests collected | 179 |
| Passed | 173 |
| Failed | 6, all in `tests/test_ws1_gate_controls.py` (§3) |
| Skipped | 0 |
| Postgres-parameterized cases run | 44 |
| Cases labelled with an M4-T id | 70, all passed |

| ID | Fault | Labelled tests (passed, SQLite and Postgres where parameterized) | Ceiling |
|---|---|---|---|
| T01 | Evidence expired before commit | `test_m4_t01_evidence_expired_before_commit_refuses_unspent` | |
| T02 | Evidence lapses between re-gate and consume | `test_m4_t02_*` in `test_atomic_admission.py` and `test_ws1_atomic_admission_route.py` | Legacy admission still executes (control 2b); the strict profile requires atomic admission |
| T03 | Principal revoked before commit | `test_m4_t03_*` (6 cases) | |
| T04 | Evidence revoked at a higher epoch | `test_m4_t04_*` (3 cases) | |
| T05 | Concurrent revocation and consumption | `test_m4_t05_*` (4 cases) | Serial order recorded in one process |
| T06 | One grant redeemed concurrently | `test_m4_t06_one_grant_redeemed_by_eight_admitters_spends_once`, `test_eight_workers_on_one_row_claim_and_spend_once` | Eight workers in one process. The SDD's 32 workers over two processes is not demonstrated |
| T07, T08 | Swapped tenant, actor, task, tool, args, target or digest | `test_m4_t07_t08_a_swapped_binding_refuses_unspent` (3 swaps) plus the WS1 binding suite | |
| T09 | Missing, foreign, unsigned or modified receipt | No test carries the T09 label. Covered by `test_an_outcome_without_receipts_is_not_admitted`, `test_m4_t18_a_source_revision_mid_lookup_refuses_the_stale_receipt`, `test_m4_t04_an_epoch_advanced_after_the_lookups_refuses` and the receipt binding tests under `tests/verification/` (226 passed) | A labelled receipt-forgery case is a follow-up |
| T10 | Clock skew and equality at `valid_until` | `test_m4_t10_the_declared_skew_is_subtracted_at_the_database_instant`, `test_the_grant_expires_the_declared_skew_early` | |
| T11 | Crash before or after commit | `test_m4_t11_a_failed_intent_rolls_the_spend_back` | Crash injected at a fixed barrier, not a process kill |
| T12 | Audit outbox insertion failure | `test_m4_t12_*` (10 cases) | |
| T13 | Database unavailable | `test_m4_t13_an_unreachable_epoch_store_refuses_unspent` | |
| T14 | TTL expires after commit, before the permit | `test_m4_t14_*` (8 cases) | |
| T15 | Send begins, response dropped | `test_m4_t15_*` (2 cases) | UNKNOWN, no unconditional retry |
| T16 | Revoke after local commit, before remote effect | `test_m4_t16_*` (9 cases) | The test keeps the label NOT_ESTABLISHED absent target-side fencing |
| T17 | Monitor unavailable or poisoned | `test_m4_t17_*` (4 cases) | |
| T18 | Source revises itself mid-loop | `test_m4_t18_*` (2 cases) | |
| T19 | Executor bypass offered | `test_m4_t19_*` (5 cases); the pilot reproduction in §5 | Production completeness NOT_ESTABLISHED |
| T20 | Replay after restart | `test_m4_t20_a_grant_replayed_after_a_restart_is_refused`; pilot fault case "Spent grant across a restart" | |

## 3. The six failures, and why they do not count against the matrix

`tests/test_ws1_gate_controls.py` is the legacy-admission control suite behind `artifacts/ws1/gate_controls_v1.json`. On SQLite its seven tests pass. With `REMORA_PG_DSN` set, six fail, and they fail even when the suite runs alone on a freshly created database, each with:

```
ValueError: outbox row <id> is terminal (SUCCEEDED); a settled dispatch is never re-claimed
```

The suite mints every grant for proposal `p-ws1-1` (`tests/test_ws1_execution_binding.py::_mint`). On SQLite each test gets a new store. On Postgres the outbox row that the first test settled is still there when the next test redeems a grant for the same proposal, and the outbox refuses to re-claim a settled row. That refusal is the exclusivity property the outbox exists for, so the failure is a test-isolation gap under Postgres, not a product defect, and the SQLite results stand. Follow-up: give each control its own proposal id, or skip the suite under Postgres. Not changed in this PR.

## 4. Model check and fault injection

- Bounded model: `tests/test_ws1_formal_typed.py` passes (39 tests together with the §99 route suites, `m41-model-and-sec99-junit.xml`). It drives `formal/ws1_composition/model.py` over every configuration in `expected.json`; `nonatomic_consume` is kept as the counterexample that records the re-gate-to-consume window.
- Fault injection in tests: `tests/test_execution_fault_injection.py` is part of the 173 passing tests above.
- Fault injection on the rebuilt pilot: `deploy/ot-pilot/run_fault_injection.py`, see the §99 capsule README. Spent-grant replay across a restart, four concurrent executions of one approval and approver revocation after approval behaved as specified.

## 5. Execution boundary on a rebuilt pilot

NEGATIVE_RESULTS §99 is reproduced against a rebuilt OT pilot in `artifacts/ws1/m4/sec99-reproduction/sec99-20261103T194032Z-dee87d1a/`. The authority domain answers 404 to self-signed leases under every pilot credential. The executor refuses the agent token and unlinked leases, records `lease_dispatch_admitted` before and `lease_dispatch_result` after each admitted lease in the shared tenant chain, and refuses a tampered call and a replayed lease. The 16-case OT battery passed 16/16 on the same build.

## 6. Clean clone

The CI job "Sealed track and replication pack reproduce from a clean clone" passed on `96c22627` (PR #1161), which `dev` `53e04f47` merges, and on the heads of PR #1160.

## 7. Second-author review

Requested on the PR that carries this record. The record is complete without it; the gate is not.

## 8. Owner decision

Recorded at the owner's instruction on 2026-11-03: **M4.1 is closed** at the ceilings in §2, subject to the second-author review in §7. Specifically:

- The reference backend is PostgreSQL. SQLite remains single-host exploratory conformance.
- T06 is demonstrated for eight workers in one process; multi-process exclusivity is not claimed.
- T16's "safe at effect" remains NOT_ESTABLISHED, and T19's production completeness remains NOT_ESTABLISHED.
- Nothing here is a formal proof over an unbounded deployment.

This closure lifts the M4.1 freeze on unrelated WS1 feature work. It does not start Study D, which still needs its own OSF registration, budget approval and locked inputs (M4 SDD §6, §7). It does not merge PR #1162, which also waits for the INV-M4-04 ruling to be reflected in the M4 SDD.
