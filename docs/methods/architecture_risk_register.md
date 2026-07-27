# REMORA Architecture Risk Register

This document is a reviewer-facing bridge between REMORA's strongest design
ideas and the limitations that still matter before production deployment or
top-tier academic claims.

REMORA's central thesis is:

> Governed autonomy requires explicit routing of uncertainty, not suppression
> of uncertainty.

The current implementation supports that thesis as a research-grade control
layer. It is not a production certification.

## What is architecturally strong

| Strength | Why it matters | Implementation anchor |
|---|---|---|
| Explicit uncertainty routing | The system does not force an answer when uncertainty is high. It routes to `ACCEPT`, `VERIFY`, `ABSTAIN`, or `ESCALATE`. | `remora/policy/decision_engine.py`, `remora/engine.py` |
| Phase-aware trust handling | Ordered, critical, and disordered regimes behave differently. Critical-phase trust inversion is preserved instead of hidden. | `remora/selective/guardrail.py`, `remora/selective/crc.py` |
| Hard-block precedence | Deterministic policy rules run before probabilistic model routing, so an oracle swarm cannot bypass hard safety constraints. | `remora/policy/invariants.py`, `remora/policy/opa_adapter.py` |
| Conformal risk control under shift | Standard conformal assumptions are documented as insufficient in the critical phase; CRC is used as a bounded research response. | `remora/selective/crc.py`, `tests/test_crc.py` |
| Session stability monitoring | `V(t) = H + lambda D` tracks whether entropy and dissensus grow across an agent session. | `remora/lyapunov.py`, `scripts/remora_hook.py` |
| Claim hygiene | Results, negative findings, and scope limits are tied to artifacts and tests. | `docs/claim_register.md`, `docs/thermodynamics/claim_ledger.yaml` |

## Decision matrix

| Phase | Low-risk action | High/critical action | Primary mechanism |
|---|---|---|---|
| Ordered | `ACCEPT` when trust and policy thresholds pass | `VERIFY` or constrained `ACCEPT` only with evidence and policy allowance | Oracle consensus plus conformal guardrail |
| Critical | Phase-aware gating; often `VERIFY` | `ESCALATE` or `ABSTAIN` unless independent evidence resolves the case | Prover-verifier deliberation, CRC, evidence gating |
| Disordered | `ABSTAIN` | `ESCALATE` | Thermodynamic shutdown plus hard policy blocks |

## Active architecture risks

| Risk | Why it matters | Current mitigation | Current status | Next acceptance gate |
|---|---|---|---|---|
| Live evidence quality | A retrieval system can return stale, noisy, irrelevant, or contradictory evidence. Poor evidence should not create false confidence. | Evidence providers are pluggable; `RAGEvidenceProvider` and `StaticJsonlEvidenceProvider` separate retrieval from policy. | Partial. Live semantic retrieval is not the headline evidence result. | Evaluate citation coverage, contradiction false-accept rate, source reliability, and retrieval latency on a locked document corpus. |
| Oracle swarm cost and latency | Three or more model calls per action can become expensive in long tool-call loops. | Adaptive cascade short-circuits easy cases; `budget_oracle_calls` returns `VERIFY` when the cap is exhausted. | Implemented, but not optimized for every deployment. | Add tiered gating policy: policy-only or single-oracle for low risk, full swarm only for high/critical or contested cases. |
| Canonicalization brittleness | Token-hash equivalence is fast but can miss synonymy, negation nuance, and domain-specific phrasing. | Polarity keys now separate binary agreement from claim-text fingerprint diversity; lexical canonicalization remains transparent. | Implemented heuristic. | Add optional NLI/cross-encoder clustering benchmark and compare against canonical hash clusters. |
| Correlated oracle failure | Multiple models can agree and still be wrong, especially when trained on similar data or exposed to the same prompt framing. | Diversity weighting, phase classification, hard-block precedence, and evidence routing reduce but do not eliminate this risk. | Known limitation. | Measure provider/family correlation on a live multi-provider benchmark with cached outputs. |
| Critical-phase trust inversion | Higher trust can be worse in the critical phase, so ordinary confidence thresholds can fail. | `PhaseAwareGuardrail` inverts critical-phase selection and rejects high-trust groupthink boundary cases. | Implemented and tested internally. | Reproduce on external benchmarks and report phase-conditioned confidence curves. |
| Simulator-scoped tool-call safety | Deterministic dry-run benchmarks are useful harnesses but do not prove field safety. | README and claim ledger scope tool-call safety as simulator results. | Honest research artifact. | Run live-agent shadow replay with cached model outputs and no real destructive execution. |
| Audit tamper prevention | Hash chains detect tampering but do not prevent full-chain replacement if storage is compromised. | Hash-chain integrity is implemented; immutable storage is documented as an external deployment requirement. | Structural implementation. | Add append-only external storage profile and replay verification test. |

## Scalable gating pattern

REMORA should not pay the full oracle-swarm cost for every action. A practical
enterprise deployment should use risk-tiered escalation:

| Risk tier | Suggested gate | Rationale |
|---|---|---|
| Low | Policy invariants plus fast/single oracle | Preserve automation and low latency. |
| Medium | FastGate plus consensus only on uncertainty | Spend model calls only when needed. |
| High | Full consensus plus evidence requirement | Reduce silent unsafe actions. |
| Critical | Hard-block precedence, evidence, human approval, audit | Do not allow autonomous execution unless explicitly bounded by policy. |

## Research next steps

1. Build a locked live-evidence benchmark with noisy retrieval, contradictions,
   stale sources, and missing citations.
2. Add an optional semantic canonicalization layer and benchmark it against the
   current transparent claim-hash heuristic.
3. Measure latency/cost tradeoffs for tiered gating across 1,000+ simulated and
   live-shadow tool-call decisions.
4. Publish phase-conditioned trust curves for external benchmarks.
5. Keep negative findings visible when a component fails to generalize.

## What reviewers should not infer

Do not infer that REMORA:

- proves correctness of arbitrary agent actions
- certifies deployment readiness
- makes consensus equivalent to truth
- has live semantic evidence retrieval as its current headline result
- eliminates the need for human approval in critical domains

The defensible claim is narrower and stronger:

> REMORA implements a reproducible control architecture that turns
> disagreement, uncertainty, missing evidence, policy constraints, and session
> instability into explicit governance outcomes.
