# AROMER Quickstart, the learning loop in 10 minutes

AROMER is REMORA's closed-loop meta-cognitive layer: every governance decision
becomes an episode, every observed outcome becomes a learning signal, and a
4-hourly cycle adapts thresholds, oracle ranking, and Bayesian harm priors.
Research-grade and experimental, not production-certified.

## 1. Offline in 60 seconds (no API keys)

```bash
python examples/aromer_quickstart.py
```

This runs the full loop locally: three governance decisions → ground-truth
recording → one adaptation cycle → world-model summary. Everything is written
to a temp episodic store; nothing leaves your machine.

The same loop in your own code:

```python
from remora.aromer import AromerOrchestrator
from remora.aromer.experience.episode import GroundTruth
from remora.policy import PolicyObservation

aromer = AromerOrchestrator(run_meta_judge=False)   # offline mode

report, episode_id = aromer.decide(PolicyObservation(
    question="DROP TABLE customer_orders",
    domain="database", risk_tier="critical", action_type="destructive_write",
    target_environment="prod", trust_score=0.41,
))
# ... after you observe what actually happened:
aromer.record_ground_truth(episode_id, GroundTruth.HARMFUL)
aromer.adapt()                                       # one learning cycle
```

Minimal observations are supported: thermodynamic state (`final_H`,
`final_D`) is optional, and episodes without it still feed the threshold and
bandit learners (the λ-coupling learner is skipped, it needs the
dissensus signal).

## 2. Reading the live intelligence score (AII)

```bash
curl "https://aromer.razorsharp.workers.dev/intelligence?history=24"
```

```python
from remora.aromer.intelligence.client import IntelligenceClient
print(IntelligenceClient().current(history_hours=24).summary())
```

Key fields:

| Field | Meaning |
|---|---|
| `current.aii` | Raw AII for the latest cycle (carries window-composition noise) |
| `aii_smoothed` | EMA-smoothed AII (α=0.35), **read this one** |
| `trend` | Computed on the smoothed series |
| `meta.transfer_source` | `python_replay_arena` (measured) or `static_seed_expectation` (fallback) |

The raw per-cycle AII samples a sliding episode window whose composition
varies between cycles; single-cycle swings are measurement noise, not
learning. Use `aii_smoothed` and `trend` for any decision about trusting
adapted thresholds (AII ≥ 0.60 → adapted values are directionally useful).

## 3. Keeping the transfer score honest

The AII transfer component must come from a measurement, not a constant. Run
the real replay arena and publish the result:

```bash
python scripts/aromer_publish_replay.py            # run + local artifact
python scripts/aromer_publish_replay.py --publish  # also POST to the worker
```

The worker prefers a posted real report for up to 7 days, then falls back to
the static seed expectation and says so in `meta.transfer_source`. The script
refuses to publish if the arena detects any false accept.

## 4. Loop health monitoring

```bash
python experiments/aromer_loop_health.py
```

Deterministic checks against the live history: transfer provenance, AII
volatility, episode-window movement, stability liveness, and the
zero-false-accept safety floor. Writes `artifacts/aromer/loop_health.json`
and exits non-zero on safety failures: suitable as a cron/CI guard.

## 5. Scaling posture

The learning plane is a Cloudflare Worker (edge-distributed) over D1 + KV:
episode ingestion is a single INSERT per decision, the heavy work happens in
the 4-hourly scheduled cycle, and reads (`/intelligence`, `/world`, `/stats`)
are bounded queries. The Python library is stateless per process except for
the JSONL episodic store. Multi-tenant hardening (per-tenant auth and
isolation on the POST endpoints) is documented future work, the current
worker is a research deployment, not a hardened multi-tenant service.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| AII jumps between cycles | Window-composition noise | Read `aii_smoothed`, not `current.aii` |
| `transfer_source: static_seed_expectation` | No recent real replay | `python scripts/aromer_publish_replay.py --publish` |
| `stability_score` near 0.10 | Pre-v2 formula (dead bandit-entropy term) | Redeploy worker ≥ 0.2.0; needs 2+ cycles of history |
| AII < 0.40 (WARMUP) | Insufficient labelled episodes | Record outcomes (`record_ground_truth`), the loop can only learn what you tell it |
