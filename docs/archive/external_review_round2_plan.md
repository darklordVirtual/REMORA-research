# REMORA External Review Round 2 Plan

> **ARCHIVED — historical document.** Superseded; preserved as record only. Do not cite as current. Current documentation index: [`../README.md`](../README.md).


This plan defines the next external-review cycle as a governed delivery process.
Scope is REMORA as a governance overlay for agent actions, not an agent-replacement system.

## 1. Review Objectives

1. Verify that production-hardening claims are backed by code paths and tests.
2. Verify that benchmark-sensitive claims remain benchmark-qualified and reproducible.
3. Verify that governance controls (RBAC, policy profile, evidence routing, audit anchoring) are externally auditable.
4. Produce a reviewer-ready evidence bundle with deterministic reproduction commands.

## 2. Review Window and Milestones

- D-10 to D-7: Freeze review scope, pin commit SHA, regenerate benchmark package.
- D-7 to D-3: Internal preflight against review checklist and claim-sync checks.
- D-3 to D-1: Package handoff and reviewer Q&A prep.
- D-day: External review walkthrough and issue capture.
- D+1 to D+5: Triage, fixes, and closure report.

## 3. Entry Criteria (Must Pass Before Handoff)

1. `make audit` passes on pinned commit.
2. `make benchmark-package` produces governance bundle with manifest.
3. `make credibility-pack` includes repro guide and limitations.
4. `python scripts/check_claim_sync.py` passes.
5. `todo.md` includes current status and completed hardening steps through S25.

## 4. Reviewer Evidence Package

Deliver these artifacts as a single handoff set:

1. `artifacts/governance-benchmark-pack/manifest.json`
2. `artifacts/governance-benchmark-pack.zip`
3. `artifacts/credibility-pack/`
4. `docs/external_review_round2_plan.md`
5. `docs/review_checklist.md`
6. `EXTERNAL_REVIEW_REMORA.md`

## 5. Required Command Transcript

Run and capture output for the following commands:

```bash
make audit
make benchmark-package
make credibility-pack
pytest -q -m live_replay_heavy \
  tests/test_toolcall_live_exec_results.py \
  tests/test_toolcall_live_cache_replay.py
python scripts/check_claim_sync.py
```

## 6. Role and Ownership Matrix

- Review lead:
  - Owns scope freeze, reviewer comms, final sign-off.
- Engineering owner:
  - Owns code-level remediation and test fixes.
- Benchmark owner:
  - Owns artifact regeneration and benchmark manifest integrity.
- Documentation owner:
  - Owns claim wording parity across README, paper, and claim ledgers.
- Security owner:
  - Owns RBAC/policy/audit control verification and threat-model alignment.

## 7. Exit Criteria (Round 2 Complete)

1. All critical/high findings have owner, status, and due date.
2. No unqualified risky claims remain (`0% unsafe`, production-safe language, guarantee language).
3. Reviewer can reproduce core checks from command transcript.
4. Signed closure note is added to changelog/review log with accepted residual risks.

## 8. Residual-Risk Ledger for Round 2

Track explicitly during review:

1. Synthetic benchmark scope versus live production behavior.
2. Optional dependency paths (FastAPI/OTel/OPA) and fail-closed behavior in production mode.
3. Audit chain tamper-evident versus tamper-proof guarantees.
4. Retrieval evidence quality in proxy versus live external evidence scenarios.

## 9. Post-Review Deliverables

1. `docs/review_round2_closure.md` with findings triage and closure state.
2. Updated `todo.md` with accepted follow-up tasks.
3. Updated `docs/claim_register.md` if evidence level changes.
4. Optional PR label set: `external-review-round2`, `claim-sync`, `governance-hardening`.
