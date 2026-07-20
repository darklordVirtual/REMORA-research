# Tool-Call Consensus Benchmark v2

**Tasks:** 700 (70 unique templates × 10 cosmetic variants; effective N = 70)
**Artifact:** `artifacts/toolcall_benchmark_v2.json`

This document records the benchmark-v2 metrics for the REMORA tool-call gating
evaluation under harder, more ambiguous action-gating conditions. All evaluation
is simulator-only, no real shell, network, database, git, or file mutations are
executed.

## Committed metrics (remora_full_policy_gate, 2026-07-20 leakage-free re-run)

- unsafe_execution_rate: 0.0000 (cluster-level Wilson 95% CI [0.0%, 5.2%])
- mean_utility: 0.6200
- accuracy: 0.9000

## Finding

Under the leakage-free input contract (REM-038: gate and baselines restricted
to the observable task surface plus platform-fact context), heuristic baselines
show 0.0143 unsafe execution rate; the unsafe-rate delta vs.
`remora_full_policy_gate` is **not statistically significant** at the
template-cluster level (one-sided p = 0.50). The gate's statistically supported
advantages are mean utility (+0.456, p ≈ 1×10⁻⁴) and accuracy (90% vs. ≤60%).
Pre-fix numbers (baselines 0.1–0.2 unsafe) were inflated by author-annotated
severity/oracle-flag reads and must not be quoted. Statistics:
`results/toolcall_benchmark_v2_significance.json`.

See `docs/toolcall_benchmarks.md` for the full combined benchmark report.
