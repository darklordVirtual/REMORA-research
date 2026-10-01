# Superseded: tool-call results from before the label-leakage fixes

**Status: superseded.** These five files are the versions committed on
2026-06-25 (`1314769`). They were produced by code that still read the
benchmark answer key: the runtime gate read `is_unsafe_if_executed` until
`d8d7f5a`, and the gate and every baseline read author-annotated severity,
flags and tags until `9c6eea0` (REM-038). Those fixes regenerated the v2, v3
and M1 artifacts but not these, so the numbers here outlived the code that
made them.

The current versions live at `results/` root under the same filenames,
regenerated on 2026-09-28 at `090d534`. What changed and why is in
`NEGATIVE_RESULTS.md` §58.

| File | Leakage-era reading that no longer holds |
|---|---|
| `toolcall_benchmark_v1_results.json` | every strategy at 0 % unsafe execution and 100 % critical interception |
| `toolcall_benchmark_v1_summary.md` | the same, as a table |
| `toolcall_ablation_results.json` | ablation conditions on the leakage-era gate |
| `toolcall_benchmark_v2_live_results.json` | `verifier_model` 0.2000 and `REMORA_temperature_gate` 0.0857 unsafe execution |
| `toolcall_benchmark_v2_live_exec_results.json` | the same gates in the sandbox pass |

Kept so the earlier readings stay auditable. Do not cite these as current results.
