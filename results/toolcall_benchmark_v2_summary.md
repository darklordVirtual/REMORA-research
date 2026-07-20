# REMORA Tool-Call Benchmark v2 Summary

Tasks: 700

| Baseline | Unsafe execution rate | Delta vs remora_full_policy_gate | Mean utility | Accuracy |
|---|---:|---:|---:|---:|
| single_model_heuristic | 0.0143 | +0.0143 | 0.1643 | 0.2857 |
| majority_vote_heuristic | 0.0143 | +0.0143 | 0.1643 | 0.2857 |
| self_consistency_heuristic | 0.0143 | +0.0143 | 0.1643 | 0.2857 |
| verifier_heuristic | 0.0143 | +0.0143 | 0.1643 | 0.2857 |
| remora_temperature_gate_heuristic | 0.0143 | +0.0143 | 0.3614 | 0.6000 |
| remora_full_policy_gate | 0.0000 | +0.0000 | 0.6200 | 0.9000 |

Limitations:
- deterministic simulator benchmark
- no live LLM calls
- no production tool calls
- heuristic baselines only; not real model evaluations
- synthetic adversarial templates require external validation
