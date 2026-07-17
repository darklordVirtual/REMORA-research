# Baseline Snapshot

> **HISTORICAL SNAPSHOT (2026-06-28).** Locked baseline; gate statuses and
> metrics reflect that date and are intentionally preserved unedited. Current
> gate status: [`release_gates.md`](release_gates.md).

Locked baseline state as of 2026-06-28. This document records the exact
quantitative state of REMORA at the point when active assurance work began
against intern_forbedring.txt. All numbers are traceable to committed artifacts.

See `docs/assurance/remediation_register.yaml` for ongoing remediation status.

---

## AII and Component Scores

| Component | Score | Weight | Artifact |
|-----------|-------|--------|----------|
| T1 (calibration) | 0.6817 | 0.30 | `artifacts/aromer/intelligence_after_v020.json` |
| T2 (friction) | 0.9393 | 0.25 | live AROMER endpoint |
| T3 (metajudge) | 0.7987 | 0.20 | live AROMER endpoint |
| T4 (transfer) | 1.000 | 0.15 | `artifacts/aromer/replay_arena_report.json` |
| T5 (stability) | 0.7748 | 0.10 | live AROMER endpoint |
| **AII** | **0.8266** | — | TRAINED_SHADOW_ONLY |

AII formula: `AII = 0.30·T1 + 0.25·T2 + 0.20·T3 + 0.15·T4 + 0.10·T5`

---

## Toolcall Benchmark v2

| Metric | Value | Artifact |
|--------|-------|----------|
| N tasks | 700 (560 harmful + 140 benign) | `remora/toolcall/benchmark_v2.py` |
| FAR (false accept rate) | 0.0000 | `results/toolcall_benchmark_v2_results.json` |
| Utility | 0.620 | `results/toolcall_benchmark_v2_results.json` |
| Structural flag coverage | 75.0% of harmful | `results/m1_flag_coverage.json` |
| Keyword heuristic coverage | 25.0% of harmful | `results/m1_flag_coverage.json` |

---

## M1 Leakage Status (at baseline)

Prior to assurance remediation:
- `remora_gate.py:169` accessed `task.is_unsafe_if_executed` when `use_contradiction_flags=True`
- Clean-signal eval (2026-06-28): FAR=0 with flags disabled → leakage not load-bearing
- **Fix applied 2026-06-28**: `is_unsafe_if_executed` branch removed entirely
- AST leakage detector added: `scripts/check_no_evaluation_leakage.py`
- Mutation tests added: `tests/test_m1_leakage_absent.py`

---

## Test Suite

| Stat | Value |
|------|-------|
| Collected | 3081 |
| Passed | 3081 |
| Skipped | 14 |
| Deselected | 36 |
| FAR during tests | 0 |

---

## Three Production Gates Remaining

These gates must pass before REMORA can be deployed in production:

1. **Longitudinal stability audit** — 30-day shadow-mode observation period *(historical: the REM-020 gate as later defined in release_gates.md uses a 7-day AII-EMA criterion)*
2. **Independent human review** — external expert governance review
3. **RBAC access control audit** — role-based authorization for policy mutations

---

## Known Gaps at Baseline

1. Blinded benchmark v3 not yet created (`benchmarks/toolcall_blind_v3/` — §3)
2. Real baselines not yet integrated (§4 — currently deterministic heuristics)
3. Import boundary enforcement not yet architectural (§2 — AST detector in place)
4. PDP/PEP separation not yet implemented (§5)
5. Locked environment (uv.lock/SBOM) not yet committed (§11)
6. External benchmark integration not yet complete (§10 — τ-bench, ToolEmu)
