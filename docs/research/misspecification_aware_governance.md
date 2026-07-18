# Misspecification-Aware Governance

Status: research-grade, deterministic, heuristic. Not production-certified.

## Problem

A governance overlay that trusts caller-supplied labels inherits every
labelling bug and every labelling attack. The two dominant failure shapes:

1. **Benign misspecification**, integration code maps every tool to
   `action_type="tool_call"` or forgets `risk_tier`, so the engine's gates have
   nothing to key on.
2. **Adversarial misspecification**, a compromised or prompt-injected agent
   labels `DROP TABLE users` as a low-risk read to slip past the policy gate.

## Approach

`remora/governance_intelligence/misspecification.py` computes, deterministically
and without LLM calls:

| Signal | Meaning |
|--------|---------|
| `model_misspecification_risk` | max over mismatch rules in [0, 1] |
| `classification_confidence` | confidence in the supplied/inferred action class |
| `classification_alternatives` | plausible alternative action types with sources |
| `environment_confidence` / `environment_mismatch_detected` | declared vs signalled environment |
| `objective_ambiguity` / `possible_objectives` | underspecified verbs on mutating actions |
| `state_transition_uncertain` | destructive action with unknown rollback |

Rules (each visible in `reasons`, each covered by tests):

- supplied read/low + inferred destructive/high → risk ≥ 0.8, low
  classification confidence, alternative recorded
- environment unknown + production signals in text → mismatch detected
- environment unknown + mutating action → risk ≥ 0.65 (clears the engine's
  misspecification gate)
- tool name implies mutation while action type says read → risk ≥ 0.75
- ambiguous objective ("clean up", "optimize", "fix", "sync", "sort out") on a
  mutating action → ambiguity ≥ 0.5 and risk ≥ 0.65
- destructive action with unknown rollback → `state_transition_uncertain`
- dangerous argument keys (`force`, `cascade`, `recursive`, …) → risk ≥ 0.5

## How it routes

The layer populates the existing v0.9 `PolicyObservation` fields, so the
engine's existing gates fire: `MISSPECIFICATION_VERIFY` (> 0.60),
`LOW_CLASSIFICATION_CONF` (< 0.60), `CRITICAL_ALTERNATIVE` /
`HIGH_RISK_ALTERNATIVE`, `ENV_MISMATCH_ESCALATE`, and
`STATE_TRANSITION_UNCERTAIN` on high/critical tiers. Read-only actions are
exempt from the confidence/risk verify gates by existing engine design, which
is what keeps legitimate reads flowing.

## Limitations

- Pattern-based inference can be evaded by novel phrasing; risk scores are
  heuristic, not calibrated probabilities.
- English-centric pattern tables.
- The mismatch rules compare against deterministic semantics, not ground
  truth; a wrong inference can cause over-review (conservative direction) but
  the strengthen-only merge prevents it from causing under-review.
