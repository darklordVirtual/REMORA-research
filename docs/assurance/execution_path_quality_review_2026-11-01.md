# Execution-path integrity and utility review — 2026-11-01

## Scope and evidence status

This change is a bounded engineering correction, not a certification or a claim
that the complete execution path has been independently audited. The baseline
is REMORA `dev` at `3456972b928181d5eace896eced7823f131d0340`.
The existing CI run on that revision passed; new tests require a new CI run.

The historical local OT pilot battery recorded 16/16 expected policy scenarios
and six reported executed tool calls on 2026-10-25
(`artifacts/pilot-pack/runs/ot-battery-2026-10-25/manifest.json`). However,
all five authorized monitoring-round read requests returned VERIFY with
`argument_values_grounded: false`. They were not dispatched or observed as
completed reads. That is **zero completed monitoring reads among five requests**,
not a successful five-read monitoring task. The historical run's revision is
recorded as `local`; do not impute a precise commit identity.

## Changes

1. The consumed-grant ledger verifier now reports both missing rows
   (`consumed_rows < high_water_mark`) and unaccounted surplus rows
   (`consumed_rows > high_water_mark`) as inconsistent. This is a detection
   improvement, **not** a tamper-proof ledger or an automatic replay stop.
2. The OT battery records legitimate monitoring-read requests, ACCEPTs,
   review routes, confirmed dispatch completions and unfinished requests
   separately from policy-case pass/fail counts.
3. If an authorized monitoring read receives ACCEPT, the battery actually
   redeems the single-use grant at `/v1/execution/execute-accepted`, checks
   the tool execution result, and attempts replay. Missing grants and
   unsuccessful execution fail the case. VERIFY/ABSTAIN remain non-executing.
4. Regression tests cover surplus ledger rows, a missing watermark, a
   successful direct-ACCEPT read, a missing ACCEPT grant, and utility accounting.

## Required end-to-end verification before claims change

- Run unit tests for the touched modules and the full deterministic CI suite.
- Re-run the OT battery against an isolated, pinned deployment and archive the
  fresh evidence manifest, measured utility and chain-verification output.
- Reconcile the monitoring work order's argument provenance against a
  deployment-owned authoritative sensor inventory. Do **not** set a read to
  ACCEPT solely because the request contains a familiar sensor identifier.
- Prove that authorized reads really execute, and that unknown/surplus
  ledger states surface as operational findings; otherwise keep them open.
- Verify credential-path exclusivity and effect verification separately.
  Neither property is established by this PR.

## Interpretation

A policy-correct non-execution remains a policy-correct result, but contributes
zero task completions. The battery's `utility.monitoring_read_completion_rate`
is defined only when monitoring cases are present. It is not a general
agent-utility benchmark. No new field-deployment or independent replication
claim is made.
