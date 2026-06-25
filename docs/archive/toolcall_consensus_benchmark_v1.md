# Tool-Call Consensus Benchmark v1

> **Superseded.** This v1 record is retained for provenance. The current
> evaluation is **`toolcall_consensus_benchmark_v2.md`**; see also
> `docs/toolcall_benchmarks.md`. Cite v2 for any external reference.
> (Flagged by `docs/DOCS_CONSOLIDATION_AUDIT.md`, C-3.)

**Tasks:** 252  
**Artifact:** `artifacts/toolcall_benchmark_v1.json`

This document records the benchmark-v1 metrics for the REMORA tool-call gating
evaluation. All evaluation is simulator-only — no real shell, network, database,
git, or file mutations are executed.

## Committed metrics (remora_temperature_gate_heuristic)

- mean_utility: 0.6762

## Committed metrics (remora_full_policy_gate)

- mean_utility: 0.5690
- accuracy: 0.7619

## Finding

Unsafe-execution reduction is not yet demonstrated on benchmark v1 — all
heuristic baselines already reach zero unsafe executions on this dataset.
Benchmark v2 was designed to address this limitation.

See `docs/toolcall_benchmarks.md` for the full combined benchmark report and
`docs/toolcall_consensus_benchmark_v2.md` for the v2 results.
