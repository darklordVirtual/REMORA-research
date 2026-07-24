# REMORA Causal Policy Explanations

**Scope:** `decision_scope = "policy_only"`

The `remora.causal` module explains why a REMORA policy decision was
ACCEPT, VERIFY, ABSTAIN, or ESCALATE, and identifies the concrete operational
changes that would produce a different outcome.

This document describes what REMORA explains, what it does not explain,
and how to use the module correctly.

---

## What REMORA explains

REMORA explains **policy-level causality**: which rule in the
`RemoraDecisionEngine` fired, and which operational conditions, if changed,
would remove that rule trigger.

The explanation has three parts:

| Part | Question answered |
|------|------------------|
| `direct_policy_causes` | Which policy rules triggered and caused this verdict? |
| `actionable_requirements` | Which operational conditions, if established, would remove a trigger? |
| `counterfactual_paths` | If those conditions were in place, what would the policy decide? |

**Example (network change management):**

A production BGP route change with no rollback plan, unverified arguments, and
no approved change window:

```
original_verdict: escalate
direct_policy_causes:
  - "No verified rollback plan for high/critical-risk action"
actionable_requirements:
  - "Rollback Plan Verified: addresses 'No verified rollback plan...'"
  - "Approved Change Window: addresses 'Evidence is insufficient...'"
```

After applying three concept interventions (approved change window + dual
control + rollback plan), the policy-modelled counterfactual:

```
counterfactual_verdict: verify
remaining_blockers:
  - "Action arguments derive from untrusted source (provenance unverified)"
```

This means: with those three operational conditions in place, the policy engine
would reach VERIFY rather than ESCALATE. ACCEPT is still blocked because source
provenance is not verified (`argument_tainted=True` remains).

---

## What REMORA does not explain

| Claim | Why it is out of scope |
|-------|------------------------|
| Real-world safety guarantees | REMORA governs policy decisions, not system outcomes |
| Causal effect on network/system state | Requires a validated domain SCM; not in v1 |
| That ACCEPT means "safe" | ACCEPT means the policy engine found no blocking reason; real safety depends on the domain |
| That policy conformance implies regulatory compliance | Compliance requires external validation |
| Formal causal proof | This is a policy-modelled counterfactual; see Bjøru (2026) §5 on partially specified causal models |

These are captured in every explanation's `non_claims` field, which must be
included when citing any finding externally.

---

## The difference between policy causality and world causality

**Policy causality** (what REMORA models):
> "If `rollback_plan_verified` were True, the policy engine would not trigger
> `ROLLBACK_UNAVAILABLE`, and the decision would be VERIFY instead of ESCALATE."

**World causality** (out of scope for REMORA v1):
> "If a rollback plan were deployed, the probability of a successful rollback
> after this change would increase by X%."

World causality requires a validated Structural Causal Model (SCM) for the
domain, including real-world interventional distributions, not just policy
signal mappings. REMORA's `CausalDecisionModel` is a *partially specified*
causal model in the sense of Bjøru (2026) §5: it captures the concepts and
their approximate policy-level consequences, bounded by explicit assumptions.

---

## What an actionable policy intervention is

An **actionable policy requirement** is an operational condition that:

1. Is represented as a concept in the `CausalDecisionModel` with `actionable=True`
2. Has a `signal_mapping` that overrides at least one `PolicyObservation` field
3. That field override removes a blocking `DecisionReason`

**Actionable (can be intervened on):**
- `approved_change_window`, requires completing a formal change-window approval
- `dual_control_verified`, requires a second human operator to attest
- `rollback_plan_verified`, requires a rollback plan to be written and reviewed
- `source_provenance_verified`, requires auditing the argument-provenance chain

**Non-actionable (cannot be intervened on):**
- `trust_score`, computed by the oracle ensemble; cannot be set
- Entropy H and dissensus D, computed from oracle response distributions
- `risk_tier`, derived signal; the *concept* `approved_change_window` may reduce
  effective risk tier as a consequence, but risk_tier itself is not directly settable
- Oracle disagreement and Lyapunov V(t), runtime telemetry, not controllable

---

## Decision outcome examples

### ACCEPT

All policy gates passed. No blocking reason fired. The decision was reached via
one of:
- Conformal trust threshold: `trust_score >= τ_conformal`
- Temperature accept: `temperature <= T*`
- Evidence accept: `evidence_action="answer"` + `evidence_confidence >= 0.7`
  + `phase="ordered"` or `trust_score >= 0.72`

**Causal explanation:** direct_policy_causes is the accept reason (e.g.
`EVIDENCE_SUPPORTED`). actionable_requirements is empty, no changes needed.

### VERIFY

A moderate blocking condition fired. Action is held for human review.

**Common causes and their actionable requirements:**

| Cause | Actionable requirement |
|-------|----------------------|
| `argument_tainted` | `source_provenance_verified=True` |
| `distribution_shift_detected` | Out-of-scope for v1 (requires domain SCM) |
| `evidence_insufficient` (high risk) | `approved_change_window=True` (sets `evidence_action`) |

### ABSTAIN

No accept path matched and no hard block fired. System is uncertain.

**Common causes:**
- `phase="disordered"` with no evidence
- `trust_score < 0.2` with no evidence

actionable_requirements may be empty, the uncertainty is systemic, not
removable by a single concept change.

### ESCALATE

A hard blocking condition fired. Action is routed to human escalation queue.

**Common causes and their actionable requirements:**

| Cause | Actionable requirement |
|-------|----------------------|
| `rollback_available=False` + high/critical risk | `rollback_plan_verified=True` |
| `adversarial_detected=True` | `source_provenance_verified=True` (clears if provenance is confirmed) |
| `coercion_detected=True` | `operator_authority_verified=True` |
| `schema_valid=False` | Fix the tool call schema (not a concept intervention) |

---

## Shadow Mode and counterfactual policy replay

Shadow Mode (`make shadow-replay`) replays a historical agent action log
through the current policy engine without blocking any real actions. Combined
with the causal module, you can:

1. Run Shadow Mode on a production action log → get `DecisionEnvelope` per action
2. For any ESCALATE or VERIFY decision, call `generate_explanation()` with the
   logged `PolicyObservation`
3. Try interventions to understand what operational changes would have altered
   the governance outcome

This is a post-hoc audit tool. The replay is deterministic: same observation
and same interventions always produce the same counterfactual verdict.

```bash
# Run shadow replay
make shadow-replay INPUT=artifacts/demo/shadow_mode_sample_agent_action_log.jsonl

# Output: artifacts/shadow_mode/decision_envelopes.jsonl
```

Then in Python:

```python
from remora.causal import generate_explanation, PolicyIntervention
from remora.causal.domains import load_domain
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation

engine = RemoraDecisionEngine()
model = load_domain("network_change_management_v1")

# obs = PolicyObservation.from_json_record(replay_record)
obs = PolicyObservation(
    question="Deploy BGP route change to core router",
    risk_tier="critical",
    action_type="network_change",
    target_environment="prod",
    rollback_available=False,
    argument_tainted=True,
)

# What would happen with approved change window + dual control + rollback?
explanation = generate_explanation(obs, engine, model, interventions=[
    PolicyIntervention("approved_change_window", True),
    PolicyIntervention("dual_control_verified", True),
    PolicyIntervention("rollback_plan_verified", True),
])

print(f"Original: {explanation.original_verdict}")       # escalate
print(f"Counterfactual: {explanation.counterfactual_verdict}")  # verify
print(f"Remaining blockers: {explanation.remaining_blockers}")  # [provenance]
print(f"Non-claims: {explanation.non_claims}")           # always present
```

---

## What still requires domain SCM and external validation

The following are out of scope for REMORA causal v1 and require an externally
validated domain Structural Causal Model (SCM) before any claim can be made:

| Gap | Required before claim |
|-----|-----------------------|
| Real-world safety effect of accepting a network change | Validated SCM for network-change consequences |
| Transfer to a different network domain or risk taxonomy | Domain-specific calibration and held-out evaluation |
| Probability that an approved change window prevents outage | Empirical study outside REMORA's scope |
| Causal inference under confounding (non-policy variables) | Full SCM with confounders identified and measured |
| Regulatory compliance from policy conformance | External legal/compliance review |

REMORA's causal module is designed for **operational governance transparency**:
helping operators understand and improve policy decisions, not for establishing
real-world safety properties.

---

## References

- Bjøru, A. R. (2026). *Causal Post-hoc Explainable AI*. PhD thesis, NTNU.
  Defines internally and externally causal XAI; partially specified causal models;
  counterfactual explanation with bounded approximations.
- Pearl, J. (2009). *Causality*. Cambridge University Press.
  Formal basis for do-calculus and counterfactual reasoning.
- REMORA paper §4–9: experimental results and policy engine architecture.
- `NEGATIVE_RESULTS.md` finding #3: token-fingerprint backend (SE backend not yet benchmarked).
