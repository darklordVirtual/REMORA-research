# REMORA Tool-Call Benchmark v2 Summary

Tasks: 700

| Baseline | Unsafe execution rate | Delta vs remora_full_policy_gate | Mean utility | Accuracy |
|---|---:|---:|---:|---:|
| single_model_heuristic | 0.2000 | +0.2000 | -0.2500 | 0.2000 |
| majority_vote_heuristic | 0.1000 | +0.1000 | 0.0000 | 0.3000 |
| self_consistency_heuristic | 0.1000 | +0.1000 | 0.0000 | 0.3000 |
| verifier_heuristic | 0.2000 | +0.2000 | -0.2500 | 0.2000 |
| remora_temperature_gate_heuristic | 0.1000 | +0.1000 | 0.2700 | 0.7000 |
| remora_full_policy_gate | 0.0000 | +0.0000 | 0.6200 | 0.9000 |

Limitations:
- deterministic simulator benchmark
- no live LLM calls
- no production tool calls
- heuristic baselines only; not real model evaluations
- synthetic adversarial templates require external validation
