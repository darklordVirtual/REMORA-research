# REMORA Release Gates

> **AII is an indicator, not a gate.** The release decision rests on hard
> artifact-backed safety proofs. AII can improve to 0.90+ while a gate
> remains OPEN — the system does not ship until all P0 release blockers are
> DONE.

## Hard release blockers (must all be DONE before v1.0)

| ID | Gate | Status | What "DONE" means |
|----|------|--------|--------------------|
| REM-014 | External benchmark (AgentHarm) | **DONE** | `results/external_benchmark_agentharm_v1.json` committed. n=208 harmful scenarios, FAR=0.0%, gate=PASS. |
| REM-019 | Regression proof — 167 historical false accepts | **DONE** | `results/false_accept_regression_v1.json` committed. n=167, FAR=0.0%, gate=PASS. |

### Why these two gates

**REM-019 (regression proof):** During WARMUP/LEARNING, REMORA made 169
false-accept errors — harmful actions were incorrectly allowed. These
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

### REM-019 — Regression proof

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
now routes to VERIFY — the low-harm ACCEPT path can no longer be reached for these tiers.
Artifact committed: `results/false_accept_regression_v1.json`.

### REM-014 — External benchmark (AgentHarm)

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
FBR=100% on benign variants: expected — benign variants share harm_category with
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

The system holds `deployment_status = SHADOW_ONLY`. Leaving shadow-only mode requires all
three production deployment gates below to be DONE in addition to the P0 safety gates above.

| ID | Gate | Status | What "DONE" means |
|----|------|--------|-------------------|
| REM-020 | Longitudinal stability audit | **IN_PROGRESS** | AII (EMA-smoothed) ≥ 0.80 for 7 calendar days with FAR = 0.0% throughout. Artifact: `results/longitudinal_stability_v1.json` committed. Eligible start date: 2026-06-28. Eligible close date: not before 2026-07-05. Current: 0.43 days, AII EMA [0.9237, 0.9712], FAR=0.0%. **Supplementary anytime-valid bound (2026-07-02):** because this gate is monitored continuously and closes on a data-dependent date, fixed-N intervals are subject to optional-stopping bias; a time-uniform confidence sequence on the cycle-level FA indicator is therefore reported alongside (0/168 cycles → 95% time-uniform upper bound 4.72%; `results/far_confidence_sequence_v1.json`, CLAIM-011, `scripts/compute_far_confidence_sequence.py`). Criterion itself unchanged pending owner sign-off. |
| REM-021 | Independent human review | **NOT STARTED** | Reviewer not on REMORA team reviews: decision engine logic, PDP/PEP separation, REM-019 regression proof, REM-014 AgentHarm benchmark, claim hygiene. Written report committed: `docs/assurance/independent_review_v1.md`. |
| REM-022 | RBAC access control audit | **DONE** (with recorded deviation) | Policy v1 committed: `docs/assurance/rbac_policy_v1.md`. Covers asset inventory, 8-role matrix, key management, D1 access controls, rotation policy, audit log retention. Acknowledged gaps in §8 (KMS/HSM, RFC 3161, CI/CD-only deploy) — consistent with TRL 3–4. Completed 2026-06-30. **Closure deviation (2026-07-02):** rbac_design_v1.md's own DONE criteria (isolation test, admin-wildcard removal, external confirmation) were not met at closure — the unmet steps are tracked as **REM-023 (NOT_STARTED)** in the remediation register. |
| REM-023 | RBAC follow-through | **NOT_STARTED** | The three REM-022 design criteria unmet at closure: `tests/test_rbac_isolation.py` (no cross-tenant leakage), admin-wildcard removal in `servers/api.py`, external confirmation of the RBAC design (may be satisfied via REM-021). |

## Record of gate elevation

| Date | Change | Reason |
|------|--------|--------|
| 2026-06-29 | REM-014 elevated P2→P0 | User direction: external benchmarks must be hard release blockers, not aspirational improvements |
| 2026-06-29 | REM-019 created P0 | User direction: versioned regression proof for 169 historical false accepts is a hard safety floor |
| 2026-06-29 | REM-014 CLOSED | AgentHarm FAR=0.0%, N=208. Both P0 blockers DONE. |
| 2026-06-29 | REM-020/021/022 created P3 | Formal production deployment gates defined for SHADOW_ONLY exit |
| 2026-06-30 | REM-020 IN_PROGRESS | Longitudinal stability audit started; 0.43d/7d, AII EMA [0.9237, 0.9712], FAR=0.0% |
| 2026-06-30 | REM-022 DONE | RBAC policy v1 committed; docs/assurance/rbac_policy_v1.md |
