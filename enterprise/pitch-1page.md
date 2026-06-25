# REMORA — Enterprise Pitch

**One sentence:** AI agents need operating boundaries — REMORA enforces them.

---

## The Problem

Autonomous AI agents make consequential decisions: deleting records, sending
communications, executing infrastructure changes.  These agents fail in two
ways: they act when they shouldn't, and they stop when they should act.  Both
failures are costly.  Neither is detectable with a single confidence score.

---

## What REMORA Does

REMORA is a governance control layer that sits between an AI agent and the
world.  Before every consequential action it asks:

1. **Do multiple independent models agree?** (multi-oracle consensus)
2. **Is the uncertainty reducible or fundamental?** (epistemic vs. aleatoric decomposition)
3. **Does this action fall within the defined policy envelope?** (Policy-as-Code)
4. **Should a human review this before it executes?** (escalation routing)

If the answer to all four is satisfactory → the agent acts.  Otherwise →
REMORA either requests verification, abstains, or escalates to a human.

---

## Decision Framework

```
Any proposed agent action
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │  Stage 1: Fast confidence gate              │  → ACCEPT (high confidence)
  │  Stage 2: Multi-oracle consensus            │  → ACCEPT / ABSTAIN / ESCALATE
  │  Stage 3: Evidence verifier                 │  → ACCEPT / ABSTAIN
  │  Stage 4: Self-consistency sampling         │  → ACCEPT / ABSTAIN
  │  Stage 6: Mixture-of-Agents synthesis       │  → ACCEPT / ABSTAIN (last resort)
  └─────────────────────────────────────────────┘
        │
        ├─ ACCEPT    → agent acts; decision logged immutably
        ├─ ABSTAIN   → agent stops; human notified
        └─ ESCALATE  → domain expert receives structured escalation payload
```

---

## Key Numbers (research prototype — not production evidence)

| Claim | Value | Scope |
|---|---|---|
| Selective accuracy, top 25% | 94.7% vs 82.8% baseline | N=302 mock oracle benchmark |
| Unsafe tool-call execution rate | 0.0% | 700 cases, deterministic simulator |
| Agent sessions with ΔV ≤ 0 (stable) | 87.2% | 1,000-session simulation |
| Test coverage | 1,195 passing | Deterministic, no API keys |

All numbers are from the committed test suite and artifacts.  They reflect
**mock oracle** performance, not live LLM production measurements.

---

## Why "Operating Boundaries" Are the Right Frame

| Without REMORA | With REMORA |
|---|---|
| Agent acts on single model output | Agent acts only on multi-oracle consensus |
| No audit trail for agent decisions | Immutable per-decision audit log |
| Binary allow/deny | Graduated: accept / verify / abstain / escalate |
| Policy in code comments | Policy-as-Code, externally auditable |
| Unknown failure modes | Measured failure surface (red team pack) |

---

## Target Buyers

- **Regulated industries** (finance, legal, healthcare, energy) where autonomous
  AI actions must be auditable and defensible
- **Infrastructure automation** teams that need AI tooling but cannot accept
  unreviewed destructive actions
- **AI governance teams** at enterprises subject to EU AI Act / NIST AI RMF

---

## Current Status

Research prototype.  The architecture, algorithms, governance mappings, and
test suite are complete.  Not yet externally validated.  Suitable for:
evaluation deployments, internal pilots, proof-of-concept integrations.

**Not yet suitable for:** unmonitored production deployment, medical/legal
decision-making, life-safety systems.

---

## Next Steps for Evaluation

```bash
pip install -e ".[dev]"
make demo      # Three live scenarios: accept, abstain, escalate
make audit     # Full quality gate: lint + tests + claim checkers
python redteam/benchmark_runner.py  # Adversarial test harness
```

Contact: [GitHub Issues](https://github.com/darklordVirtual/REMORA/issues)
