# REMORA Tool-Call Benchmark v1 Summary

Tasks: 252

| Baseline | Unsafe execution rate | Mean utility | Accuracy | Critical intercept |
|---|---:|---:|---:|---:|
| single_model_heuristic | 0.0000 | 0.5167 | 0.6190 | 1.0000 |
| majority_vote_heuristic | 0.0000 | 0.6286 | 0.8571 | 1.0000 |
| self_consistency_heuristic | 0.0000 | 0.6286 | 0.8571 | 1.0000 |
| verifier_heuristic | 0.0000 | 0.5452 | 0.6905 | 1.0000 |
| remora_temperature_gate_heuristic | 0.0000 | 0.6762 | 0.9524 | 1.0000 |
| remora_full_policy_gate | 0.0000 | 0.5690 | 0.7619 | 1.0000 |

Limitations:
- deterministic simulator benchmark
- no live LLM calls
- no production tool calls
- heuristic baselines only; not real model evaluations
- task templates are synthetic and require external validation
