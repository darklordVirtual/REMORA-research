# Tool-Call Consensus Benchmark v2

**Tasks:** 700  
**Artifact:** `artifacts/toolcall_benchmark_v2.json`

This document records the benchmark-v2 metrics for the REMORA tool-call gating
evaluation under harder, more ambiguous action-gating conditions. All evaluation
is simulator-only, no real shell, network, database, git, or file mutations are
executed.

## Committed metrics (remora_full_policy_gate)

- unsafe_execution_rate: 0.0000
- mean_utility: 0.6200
- accuracy: 0.9000

## Finding

`remora_full_policy_gate` reduces unsafe execution compared to heuristic
baselines (which reach 0.1–0.2 unsafe execution rate on v2) while maintaining
positive mean utility. Statistical significance is documented in
`results/toolcall_benchmark_v2_significance.json`.

See `docs/toolcall_benchmarks.md` for the full combined benchmark report.
