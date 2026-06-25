# Governance Intelligence Layer

Status: research-grade, deterministic, heuristic. Not production-certified.
Does not guarantee safety.

## What it is

The Governance Intelligence Layer (`remora/governance_intelligence/`) is a
pre-execution, pre-policy enrichment stage. It receives raw agent-action
metadata (question/proposed action text, tool name, tool arguments,
caller-supplied risk tier / action type / environment / domain, optional
repetition counts and tenant identity) and returns an enriched
`PolicyObservation` in which governance fields are populated with conservative,
deterministic signals.

Paper-safe contribution statement:

> REMORA's Governance Intelligence Layer enriches raw agent-action metadata
> into conservative governance signals before policy evaluation, reducing
> reliance on caller-supplied labels and making misspecification, causal
> consequence, and policy generalization risks explicit.

## What it does

1. **Fail-closed normalisation** (`normalization.py`): risk tier, action type,
   environment, domain, and tool name are normalised deterministically.
   Missing, empty, or unrecognised values become the explicit string
   `"unknown"` and are listed in `metadata_unknown_fields`. Unknown is never
   coerced to `"low"`, `"read"`, or `"dev"`.
2. **Action-semantics extraction** (`action_semantics.py`): a fixed table of
   compiled regex patterns maps text and tool metadata to signals (mutating,
   destructive, irreversible, external side effect, credential risk, bulk
   scope, production signal, safety-critical) plus an inferred action type,
   domain, and minimum risk tier. Ambiguous language errs toward higher risk.
3. **Misspecification inference** (`misspecification.py`): disagreement between
   supplied labels and inferred semantics becomes explicit risk
   (`model_misspecification_risk`, `classification_alternatives`,
   `environment_mismatch_detected`, `objective_ambiguity`,
   `state_transition_uncertain`). See
   `misspecification_aware_governance.md`.
4. **Causal-consequence signals** (`causal_consequence.py`): blast radius,
   affected assets, irreversibility, downstream effects, and a coarse expected
   loss. See `causal_consequence_gating.md`.
5. **Policy-generalization risk** (`policy_generalization.py`): the
   standing-policy question — would repeatedly ACCEPTing this class of action
   remain safe fleet-wide? See `policy_generalization_risk.md`.
6. **Strengthen-only merge** (`enrichment.py`): the enriched observation only
   ever raises risk floats, lowers confidence floats, raises tiers, and ORs
   hazard flags. It never lowers a supplied tier, never clears a hard-block
   flag, and never resolves an unknown tier to anything below `critical`
   (resolving unknown to a known sub-critical tier would disable the engine's
   unknown-risk-tier gate, which is a weakening).

## What it does not do

- It does **not** decide. ACCEPT/VERIFY/ABSTAIN/ESCALATE remains the exclusive
  responsibility of `RemoraDecisionEngine`. Hard policy blocks remain
  authoritative and unchanged.
- It does **not** call an LLM, the network, or any external service. Every
  signal is a deterministic function of its inputs.
- It does **not** certify safety. Pattern tables can be evaded by phrasing the
  layer has not seen; the layer reduces reliance on caller labels, it does not
  replace verification, evidence, or human review.
- It does **not** change default behaviour. The layer is opt-in via
  `remora.policy.enrich_then_decide(...)` or
  `remora.governance_intelligence.enrich_policy_observation(...)`;
  `RemoraDecisionEngine.decide()` is byte-for-byte unchanged.

## Why pre-policy enrichment matters

The decision engine already has conservative gates for misspecification,
session risk, and policy generalization — but those gates key on observation
fields that, before this layer, only diligent callers populated. A caller that
labels `DROP TABLE users` as `action_type="read", risk_tier="low"` (whether
maliciously or through integration bugs) presented the engine with an
observation whose gates had nothing to fire on. Enrichment closes that gap:
the labels stop being trusted blindly, and inferred-higher risk overrides
supplied-lower risk while the reverse never happens.

## Why unknown metadata must not be treated as safe

A missing risk tier is not evidence of low risk; it is the absence of
evidence. Under fail-closed normalisation every unknown field is (a) explicit,
(b) visible in warnings and audit output, and (c) routed conservatively by the
engine's existing unknown-tier and misspecification gates. The benchmark
(`benchmarks/governance_intelligence/`) asserts that unknown tier plus
mutation never reaches ACCEPT, while complete, consistent, low-risk reads
still do.

## Relationship to decision-theoretic inspiration

- **Infra-Bayesian inspiration:** treating the caller-supplied metadata as one
  hypothesis in a credal set rather than the truth — acting on the worst
  plausible reading (label vs inferred semantics) rather than the most
  convenient one. The layer is *not* infra-Bayesianism: there is no convex set
  of priors, no Knightian update rule; only a deterministic worst-case merge.
- **CDT-inspired causal consequence:** asking "what does executing this action
  cause?" (blast radius, downstream effects, expected loss) rather than only
  "what does this action correlate with?". It is *not* causal decision theory:
  there is no interventional model, only a table-driven consequence heuristic.
- **LDT-inspired policy generalization:** evaluating the decision *policy*
  ("accept this class of action") rather than the single act, asking whether
  the policy generalized across agents, tenants, and time remains safe. It is
  *not* Logical Decision Theory: there are no logical counterfactuals, only a
  deterministic projection over action class and repetition counts.

## Architecture

```
raw metadata (question, tool call, labels, counts)
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ Governance Intelligence Layer (deterministic)        │
│  1 normalization      → NormalizedMetadata           │
│  2 action_semantics   → ActionSemantics              │
│  3 misspecification   → MisspecificationAssessment   │
│  4 causal_consequence → CausalConsequenceAssessment  │
│  5 policy_general.    → PolicyGeneralizationAssessm. │
│  6 enrichment (strengthen-only merge)                │
└──────────────────────────────────────────────────────┘
        │ enriched PolicyObservation (+ warnings, explanation)
        ▼
RemoraDecisionEngine.decide()   ← authoritative, unchanged
        │
        ▼
ACCEPT / VERIFY / ABSTAIN / ESCALATE
```

## Validation

- `tests/governance_intelligence/` — unit and integration tests per module.
- `tests/policy/test_governance_intelligence_never_weakens_policy.py` — grid
  property test: enrichment never converts a non-ACCEPT into an ACCEPT and
  never clears hard-block flags.
- `benchmarks/governance_intelligence/` + 
  `experiments/evaluate_governance_intelligence.py` — 50-task offline routing
  benchmark with a fail-hard gate on unsafe accepts and blocked legitimate
  reads.

## Future work

- Surface the governance-intelligence summary in `DecisionEnvelope`
  (`reviewer_context` or an optional `governance_intelligence` block). The
  envelope schema is intentionally untouched in this iteration; the signals
  are available programmatically via `GovernanceIntelligenceResult` and the
  enriched observation fields that already flow into existing audit paths.
- Calibrate pattern tables against external red-team corpora (AgentHarm
  pipeline) before making any detection-rate claims beyond this benchmark.
- Multilingual pattern tables (current patterns are English-centric).
