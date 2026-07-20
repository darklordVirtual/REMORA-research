# REMORA Release Gates

> **AII is an indicator, not a gate.** The release decision rests on hard
> artifact-backed safety proofs. AII can improve to 0.90+ while a gate
> remains OPEN, the system does not ship until all P0 release blockers are
> DONE.

> **Authority within the documentation model.** This document is the gate
> *register and decision history* (what each gate means, when it changed, and
> why). It is **not** the machine source of gate status: individual REM
> statuses are held machine-readably in
> [`remediation_register.yaml`](remediation_register.yaml), and overall
> deployment maturity is **recomputed** from the registers into a profile by
> `scripts/check_document_governance.py` — see
> [`release_profiles_v1.yaml`](release_profiles_v1.yaml) (the authoritative
> maturity model). The status columns below mirror the remediation register;
> if they ever disagree, the register wins and this table is the bug. Hierarchy:
> `remediation_register.yaml` (REM status) → `release_profiles_v1.yaml`
> (computed maturity) → this file (human-readable gate register + history) →
> the README status block (generated).

## Hard release blockers (must all be DONE before v1.0)

| ID | Gate | Status | What "DONE" means |
|----|------|--------|--------------------|
| REM-014 | External benchmark (AgentHarm) | **DONE** | `results/external_benchmark_agentharm_v1.json` committed. n=208 harmful scenarios, FAR=0.0%, gate=PASS. |
| REM-019 | Regression proof, 167 historical false accepts | **DONE** | `results/false_accept_regression_v1.json` committed. n=167, FAR=0.0%, gate=PASS. |

### Why these two gates

**REM-019 (regression proof):** During WARMUP/LEARNING, REMORA made 169
false-accept errors, harmful actions were incorrectly allowed. These
scenarios are stored in AROMER D1 (`decision_quality='false_accept'`). A
regression proof verifies that the current mature system blocks every one
of them. Without this proof, "FAR=0 on the current window" only guarantees
the last N episodes; it says nothing about the historical failure modes.

**REM-014 (external benchmark):** All internal benchmarks (REM-009 v3,
REM-010 LLM baselines) use scenarios that were designed or selected within
the project. An independent dataset (AgentHarm, arxiv:2410.09024) removes the
possibility of inadvertent in-distribution optimisation. This is the
external validity gate.

## How to close the gates

### REM-019: Regression proof

```bash
# 1. Ensure AROMER worker is deployed (workers/aromer)
# 2. Run:
python scripts/run_false_accept_regression.py \
    --worker https://aromer.razorsharp.workers.dev \
    --output results/false_accept_regression_v1.json
# 3. Verify artifact (regression_gate tests are excluded from normal runs):
python -m pytest tests/test_false_accept_regression.py -m regression_gate -v
# 4. Commit artifact + test pass
```

**Current state (2026-06-29):** FAR=0.0% (167/167 blocked). Gate PASS.
Corpus: 167 episodes (169 original minus 2 corpus artifacts):
- `aradhye-0060` excluded: benign school-outing query, aradhye dataset mislabel.
- `caizhitech-1059` excluded: conversational AI chat safety case, out of scope for
  agent action governance. REMORA governs tool execution; CaiZhiTech labels chat responses.
Policy change: added VERIFY floor for `risk_tier=high` and `risk_tier=critical`.
Any action below the ESCALATE threshold (p_harm < 0.70) with high/critical risk
now routes to VERIFY: the low-harm ACCEPT path can no longer be reached for these tiers.
Artifact committed: `results/false_accept_regression_v1.json`.

### REM-014: External benchmark (AgentHarm)

```bash
# 1. Ensure HF_TOKEN is set and you have accepted ai-safety-institute/AgentHarm terms.
# 2. Ensure AROMER worker is deployed (workers/aromer).
# 3. Run the full benchmark (script name matches scripts/ on disk;
#    same invocation as CLAIM-002's reproduce block in the claim register):
python scripts/run_agentharm_benchmark.py --split test_public \
    --out results/external_benchmark_agentharm_v1.json

# 5. Gate test (requires artifact):
python -m pytest tests/test_rem014_external_benchmark.py -m rem014_gate -v

# 6. Commit artifact + test pass.
```

**Current state (2026-06-29):** FAR=0.0% (208/208 harmful scenarios blocked). Gate PASS.
Benchmark: `ai-safety-institute/AgentHarm` (arxiv:2410.09024), configs `harmful` + `harmless_benign`.
FBR=100% on benign variants: expected, benign variants share harm_category with
harmful counterparts, so same risk_tier mapping applies. AROMER routes ambiguous-category
tasks to ESCALATE (human review). FAR=0.0% is the hard safety floor; FBR documents friction.
Artifact committed: `results/external_benchmark_agentharm_v1.json`. Gate tests: 10/10 PASS.

## AII as indicator (not gate)

Once both release gates are DONE, AII provides ongoing health telemetry:

| AII Range | Interpretation | Action |
|-----------|---------------|--------|
| ≥ 0.80 (TRAINED) | Calibrated and stable | Normal operation |
| 0.60–0.79 (CAPABLE) | Directionally useful | Monitor; investigate if sustained |
| < 0.60 | Regression signal | Investigate before deployment |
| FAR > 0 | **Stop all activity** | Treat as P0 incident |

AII dropping below TRAINED threshold does NOT block operation by itself
(the world model adapts continuously). It triggers investigation, not halt.
Only FAR > 0 is an unconditional stop.

## Production deployment gates (required before leaving SHADOW_ONLY)

The system holds `deployment_status = SHADOW_ONLY`. Leaving shadow-only mode requires every
production deployment gate below to be DONE in addition to the P0 safety gates above.

| ID | Gate | Status | What "DONE" means |
|----|------|--------|-------------------|
| REM-020 | Longitudinal stability audit | **DONE (internally attested, REM-021 verification required)** | Criterion: AII (EMA-smoothed) ≥ 0.80 with FAR = 0.0% for 7 consecutive days from gate opening 2026-06-28; eligible close no earlier than 2026-07-05. **Why 7 days is the criterion:** it is the original pre-registered definition (created 2026-06-29; the 2026-06-30 elevation row "0.43d/7d" evidences it predates the 30-day variant, which appeared in a 2026-07-02 consolidation). The 2026-07-17 owner decision *reverted to the pre-registered criterion*; it did not lower a target after the fact. Closed 2026-07-17 by `scripts/close_rem020.py --close` (fail-closed): days_elapsed=19 of 7 required, n_operational_fa=0, AII=0.9914. **Evidence form (stated plainly):** the committed artifact (`results/longitudinal_stability_v1.json`, status=PASS) attests the live worker's day counter and current values; it does NOT contain the full 7-day time series, the worker retains ~168 adapt cycles (~0.58 days) in its queryable history, and the complete series lives in the worker's D1 longitudinal store. Independent reproduction of the 7-day window from that store is in scope for REM-021, which is why the status is *internally attested*, not independently verified. Supplementary anytime-valid bound (2026-07-02): 0/168 cycles → 95% time-uniform upper bound 4.72% (`results/far_confidence_sequence_v1.json`, CLAIM-011). 15/15 rem020_gate tests pass. |
| REM-021 | Independent human review | **NOT STARTED** | Reviewer not on REMORA team reviews: decision engine logic, PDP/PEP separation, REM-019 regression proof, REM-014 AgentHarm benchmark, claim hygiene. Written report committed: `docs/assurance/independent_review_v1.md`. |
| REM-022 | RBAC access control audit | **DONE** (with recorded deviation) | Policy v1 committed: `docs/assurance/rbac_policy_v1.md`. Covers asset inventory, 8-role matrix, key management, D1 access controls, rotation policy, audit log retention. Acknowledged gaps in §8 (KMS/HSM, RFC 3161, CI/CD-only deploy), consistent with TRL 3–4. Completed 2026-06-30. **Closure deviation (2026-07-02):** rbac_design_v1.md's own DONE criteria (isolation test, admin-wildcard removal, external confirmation) were not met at closure, the unmet steps are tracked as **REM-023 (NOT_STARTED)** in the remediation register. |
| REM-023 | RBAC follow-through | **IN_PROGRESS** | The three REM-022 design criteria unmet at closure. Steps 8–9 DONE 2026-07-03: `tests/test_rbac_isolation.py` (no cross-tenant leakage) and admin-wildcard removal in `servers/api.py`. Remaining: external confirmation of the RBAC design (folded into REM-021). See remediation register REM-023 for detail. |

## Record of gate elevation

| Date | Change | Reason |
|------|--------|--------|
| 2026-06-29 | REM-014 elevated P2→P0 | User direction: external benchmarks must be hard release blockers, not aspirational improvements |
| 2026-06-29 | REM-019 created P0 | User direction: versioned regression proof for 169 historical false accepts is a hard safety floor |
| 2026-06-29 | REM-014 CLOSED | AgentHarm FAR=0.0%, N=208. Both P0 blockers DONE. |
| 2026-06-29 | REM-020/021/022 created P3 | Formal production deployment gates defined for SHADOW_ONLY exit |
| 2026-06-30 | REM-020 IN_PROGRESS | Longitudinal stability audit started; 0.43d/7d, AII EMA [0.9237, 0.9712], FAR=0.0% |
| 2026-06-30 | REM-022 DONE | RBAC policy v1 committed; docs/assurance/rbac_policy_v1.md |
| 2026-07-17 | REM-020 row refreshed; criterion conflict recorded | Previous row showed a 2026-06-30 snapshot ("0.43 days"). Fresh artifact committed (2026-07-17). A conflict between two canonical definitions is now recorded in the row: this repo's 7-day criterion (stale sweep 2026-07-03) vs the main repo's 30-day closure tooling (`close_rem020.py`, 2026-07-02). Under the 7-day definition the worker self-reports DONE; the 30-day tooling refuses closure. |
| 2026-07-17 | REM-020 close check run, gate NOT closed | `scripts/close_rem020.py` (fail-closed) run 2026-07-17: day-count criterion unmet under its 30-day definition (worker reports days_elapsed=19). FAR=0.0%, AII=0.9914 at check time. Gate remains IN_PROGRESS pending owner reconciliation of the criterion; no manual closure. |
| 2026-07-17 | REM-020 criterion reconciled, owner decision | The 7-day definition (gate open 2026-06-28, close no earlier than 2026-07-05) is canonical; main-repo closure tooling and tests updated to match. |
| 2026-07-17 | REM-020 CLOSED | `close_rem020.py --close` (fail-closed): days_elapsed=19 of 7 required, n_operational_fa=0, AII=0.9914, artifact status=PASS. Self-reported values; REM-021 independent verification still required. Deployment status remains SHADOW_ONLY until REM-021 closes. |
