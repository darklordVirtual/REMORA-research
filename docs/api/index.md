# API Reference

REMORA exposes a minimal, stable public API. Zero dependencies required for core use.

## Quick start

```python
from remora import RemoraDecisionEngine, PolicyObservation, DecisionAction

engine = RemoraDecisionEngine()
obs = PolicyObservation(
    question="deploy payment service to production",
    phase="critical",
    trust_score=0.62,
    final_H=0.88,
    final_D=0.44,
    risk_tier="high",
    domain="infrastructure",
    action_type="deploy",
    target_environment="prod",
)
report = engine.decide(obs)
print(report.action)                 # DecisionAction.VERIFY
print(report.human_review_required)  # True
```

## Module stability

| Module | Stability | Purpose |
|--------|-----------|---------|
| `remora.policy.decision_engine` | **CORE** | Maps observations to decisions |
| `remora.policy.observation` | **CORE** | Input type for the decision engine |
| `remora.safety.adversarial` | **CORE** | Adversarial input detection |
| `remora.engine` | **CORE** | Multi-oracle consensus engine |
| `remora.lyapunov` | EXPERIMENTAL | Lyapunov stability controller |
| `remora.zkp` | RESEARCH_ONLY | Zero-knowledge proof traces |

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full stability index.
