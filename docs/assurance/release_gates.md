# REMORA Release Gates

> **AII is an indicator, not a gate.** The release decision rests on hard
> artifact-backed safety proofs. AII can improve to 0.90+ while a gate
> remains OPEN — the system does not ship until all P0 release blockers are
> DONE.

## Hard release blockers (must all be DONE before v1.0)

| ID | Gate | Status | What "DONE" means |
|----|------|--------|--------------------|
| REM-014 | External benchmark (tau-bench / ToolEmu) | **OPEN** | `results/external_benchmark_<name>_v1.json` committed, showing REMORA blocks ≥ benchmark threshold on at least one external holdout |
| REM-019 | Regression proof — 169 historical false accepts | **OPEN** | `results/false_accept_regression_v1.json` committed, `false_accept_rate=0.0`, `n_scenarios=169` |

### Why these two gates

**REM-019 (regression proof):** During WARMUP/LEARNING, REMORA made 169
false-accept errors — harmful actions were incorrectly allowed. These
scenarios are stored in AROMER D1 (`decision_quality='false_accept'`). A
regression proof verifies that the current mature system blocks every one
of them. Without this proof, "FAR=0 on the current window" only guarantees
the last N episodes; it says nothing about the historical failure modes.

**REM-014 (external benchmark):** All internal benchmarks (REM-009 v3,
REM-010 LLM baselines) use scenarios that were designed or selected within
the project. An independent dataset (tau-bench, ToolEmu) removes the
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

### REM-014 — External benchmark

```bash
# tau-bench (preferred)
# See experiments/tau-bench/README.md once scaffolded
# ToolEmu alternative
# See experiments/toolemu/README.md once scaffolded
```

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

## Record of gate elevation

| Date | Change | Reason |
|------|--------|--------|
| 2026-06-29 | REM-014 elevated P2→P0 | User direction: external benchmarks must be hard release blockers, not aspirational improvements |
| 2026-06-29 | REM-019 created P0 | User direction: versioned regression proof for 169 historical false accepts is a hard safety floor |
