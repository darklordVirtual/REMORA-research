# REMORA Tool-Call Benchmark v1 Summary

Tasks: 252

| Baseline | Unsafe execution rate | Mean utility | Accuracy | Critical intercept |
|---|---:|---:|---:|---:|
| single_model_heuristic | 0.1429 | 0.2095 | 0.5952 | 0.8571 |
| majority_vote_heuristic | 0.0238 | 0.4310 | 0.7143 | 0.9286 |
| self_consistency_heuristic | 0.0238 | 0.4310 | 0.7143 | 0.9286 |
| verifier_heuristic | 0.1429 | 0.2095 | 0.5952 | 0.8571 |
| remora_temperature_gate_heuristic | 0.0238 | 0.4310 | 0.7143 | 0.9286 |
| remora_full_policy_gate | 0.0000 | 0.4786 | 0.7143 | 1.0000 |

Limitations:
- deterministic simulator benchmark
- no live LLM calls
- no production tool calls
- heuristic baselines only; not real model evaluations
- task templates are synthetic and require external validation
