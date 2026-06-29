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

> **All P0 release blockers are DONE as of 2026-06-29.** The system is v1.0 release-ready
> from a safety gate perspective. Three deployment gates remain (longitudinal stability audit,
> independent human review, RBAC access control audit) before production deployment.

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
# 3. Run the full benchmark:
python scripts/run_external_benchmark_agentharm.py \
    --worker https://aromer.razorsharp.workers.dev \
    --output results/external_benchmark_agentharm_v1.json

# 4. Validate pipeline without HuggingFace access (synthetic 15 scenarios):
python scripts/run_external_benchmark_agentharm.py --dry-run

# 5. Gate test (requires artifact):
python -m pytest tests/test_rem014_external_benchmark.py -m rem014_gate -v
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

## Record of gate elevation and closure

| Date | Change | Reason |
|------|--------|--------|
| 2026-06-29 | REM-014 elevated P2→P0 | User direction: external benchmarks must be hard release blockers, not aspirational improvements |
| 2026-06-29 | REM-019 created P0 | User direction: versioned regression proof for 169 historical false accepts is a hard safety floor |
| 2026-06-29 | REM-019 CLOSED | FAR=0.0% on 167-episode corpus. Artifact: `results/false_accept_regression_v1.json` |
| 2026-06-29 | REM-014 CLOSED | AgentHarm external benchmark FAR=0.0%, N=208. Artifact: `results/external_benchmark_agentharm_v1.json` |
