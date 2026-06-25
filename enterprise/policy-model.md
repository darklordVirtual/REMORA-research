# REMORA Policy Model

## Overview

The REMORA policy model governs every request from classification to verdict. It determines which oracles are invoked, what evidence is required, which decision outcomes are permitted, and who (or what) acts on the result.

Policy is evaluated before model calls are made — not after. This ensures governance is structural, not advisory.

---

## Risk Tiers

Every incoming request is assigned a risk tier based on domain, intent classification, and data sensitivity. The tier determines the oracle configuration, evidence requirements, and permitted decision outcomes.

| Tier | Examples | Oracle level | Evidence requirement | Permitted outcomes |
|---|---|---|---|---|
| **Low** | HR FAQ, internal policy lookup, document summarisation | 1–2 models | None or optional | ACCEPT, ABSTAIN |
| **Medium** | Engineering support, contract interpretation, supplier selection, maintenance planning | 2–3 models + RAG | Required from corpus | ACCEPT, RETRIEVE, ESCALATE, ABSTAIN |
| **High** | Production optimisation, safety-critical recommendations, cyber incident response, financial decisions | 3+ models + RAG + verifier | Required, cross-referenced | ACCEPT (with trace), ESCALATE, ABSTAIN |
| **Critical** | Actions against OT/SCADA, life-safety decisions, legally binding outputs | Multi-oracle + hard policy | Mandatory, audited | RECOMMEND ONLY, ESCALATE, ABSTAIN |

**Critical tier never produces an ACT verdict autonomously.** Output at critical tier is always a structured recommendation, not an executable action.

---

## Decision Outcomes

Standard policy verdicts (ACCEPT / VERIFY / ABSTAIN / ESCALATE) from the cascade engine map to enterprise action types:

| Outcome | Meaning | Who acts |
|---|---|---|
| `ACCEPT` | Answer is supported with sufficient confidence and evidence | System returns answer to caller |
| `RETRIEVE` | Insufficient evidence — fetch more before deciding | System triggers additional RAG pass |
| `DEBATE` | Confidence is borderline — escalate to additional oracles | System triggers Stage 4 self-consistency |
| `ESCALATE` | Decision requires human judgment | Routes to subject-matter expert or approval workflow |
| `ABSTAIN` | Models disagree too strongly — no reliable answer | System returns abstention with explanation |
| `ACT` | Approved action can be executed | Only available on pre-approved tool calls at medium tier or below |

`ABSTAIN` is a valid, successful outcome — not a failure. In regulated or high-stakes environments, knowing that the AI cannot reliably answer is more valuable than a forced low-confidence answer.

---

## Policy-as-Code

Risk profiles are machine-readable configurations. Each profile specifies oracle configuration, thresholds, evidence requirements, and permitted actions. See [`risk-profiles.yaml`](risk-profiles.yaml) for the full schema.

Example — high-risk profile:

```yaml
profiles:
  high_risk:
    description: "Safety-critical recommendations, production systems"
    oracle:
      tier: full_consensus         # 3+ oracles, all families
      min_oracles: 3
      require_independent_judge: true
      max_budget_calls: 20
    evidence:
      required: true
      min_sources: 2
      source_types: [procedure, regulation, engineering_standard]
      cross_reference: true
    thresholds:
      fast_gate: 0.95              # higher bar for early accept
      consensus_accept: 0.75
      consensus_abstain: 0.20
      verify_threshold: 0.80
    permitted_outcomes:
      - ACCEPT                     # only with full trace
      - ESCALATE
      - ABSTAIN
    action:
      autonomous_act: false
      require_human_approval: true
      approval_role: domain_expert
    audit:
      log_level: full
      retention_days: 3650         # 10 years for regulated domains
```

---

## Policy Enforcement Points

Policy is enforced at three points in the pipeline:

```
1. Gateway (pre-routing)
   ├── Authenticate tenant and user
   ├── Classify intent and domain
   ├── Select risk profile
   └── Apply input filters (PII, prompt injection detection)

2. Cascade stages (during processing)
   ├── Oracle budget enforcement
   ├── Evidence sufficiency check before Stage 3
   └── Action gate: verify tool-call safety before ACT verdict

3. Output (post-processing)
   ├── Confidence below threshold → downgrade verdict
   ├── Critical tier → strip ACT, enforce RECOMMEND ONLY
   └── Write audit record regardless of outcome
```

---

## Escalation Routing

When `ESCALATE` is the verdict, the routing target depends on the tenant configuration and the domain:

| Domain | Default escalation target |
|---|---|
| Production / process | Operations engineer on-call |
| Maintenance | Maintenance supervisor |
| HSE | HSE manager |
| Cybersecurity | SOC analyst (L2/L3) |
| Legal / compliance | Legal counsel |
| Procurement | Category manager |
| Engineering | Discipline lead |

Escalation routes are defined per tenant in the tenant configuration. The escalation payload includes:
- Original question
- Best answer produced (with confidence)
- Reason for escalation (phase, trust score, policy rule triggered)
- Evidence retrieved (with source citations)
- Full decision trace

---

## Abstain as an Enterprise Feature

In large organisations, the instinct is to maximise AI answer coverage. This is wrong for high-stakes domains.

The right objective is: **AI should answer when it can be trusted; it should not answer when it cannot.**

REMORA's `ABSTAIN` outcome is an explicit, first-class result that:
- Signals that the question is beyond reliable automated resolution
- Preserves the decision for a human without forcing a wrong answer
- Is logged in the audit trail with the reason for abstention
- Can be tracked as a metric (abstention rate by domain) for ongoing calibration

A high abstention rate on a domain is useful information — it means the oracle pool, evidence sources, or risk thresholds need calibration for that domain.

---

## OPA/Rego Integration

For enterprises running REMORA across multiple teams, the Python decision engine
can be delegated to an [Open Policy Agent](https://www.openpolicyagent.org/)
daemon. This separates policy from application code so governance teams can
update rules without redeploying Python services.

### Input document

`remora.policy.opa_adapter.export_opa_context()` produces the canonical input
sent to OPA. Every field maps 1-to-1 to a `PolicyObservation` attribute:

```json
{
  "input": {
    "trust_score": 0.87,
    "phase": "ordered",
    "temperature": 0.14,
    "distribution_shift_detected": false,
    "counterfactual_passed": true,
    "evidence_action": "answer",
    "evidence_confidence": 0.91,
    "evidence_contradictions": 0,
    "contradiction_cycles": 0,
    "require_rag": false,
    "refuse_parametric_verdict": false,
    "claim_graph_betti_1": 0,
    "conformal_score": null
  }
}
```

### Expected OPA output

The Rego package must produce `data.remora.policy.decision` with this shape:

```json
{
  "action": "accept",
  "reasons": ["ordered_high_trust"],
  "confidence": 0.87,
  "risk_estimate": 0.13,
  "explanation": "High-trust ordered-phase query accepted.",
  "policy_version": "opa-remora-v1"
}
```

`action` must be one of `accept`, `verify`, `abstain`, `escalate`.
`reasons` must be a list of valid `DecisionReason` enum values.

### Rego skeleton

```rego
package remora.policy

import future.keywords.if
import future.keywords.in

default decision = {"action": "abstain", "reasons": ["default_safe_abstain"]}

# Hard block: distribution shift detected
decision = result if {
    input.distribution_shift_detected == true
    result := {
        "action": "verify",
        "reasons": ["distribution_shift"],
        "confidence": 0.5,
        "risk_estimate": 0.3,
        "explanation": "Calibration distribution shift detected; route to verification.",
        "policy_version": "opa-remora-v1",
    }
}

# Hard block: counterfactual failed
decision = result if {
    input.counterfactual_passed == false
    result := {
        "action": "escalate",
        "reasons": ["counterfactual_failed"],
        "confidence": 0.0,
        "risk_estimate": 1.0,
        "explanation": "Counterfactual check failed; human review required.",
        "policy_version": "opa-remora-v1",
    }
}

# Accept: ordered phase + high trust
decision = result if {
    input.phase == "ordered"
    input.trust_score >= 0.6
    input.counterfactual_passed != false
    input.distribution_shift_detected == false
    result := {
        "action": "accept",
        "reasons": ["ordered_high_trust"],
        "confidence": input.trust_score,
        "risk_estimate": 1 - input.trust_score,
        "explanation": "High-trust ordered-phase query accepted.",
        "policy_version": "opa-remora-v1",
    }
}

# Verify: critical phase
decision = result if {
    input.phase == "critical"
    result := {
        "action": "verify",
        "reasons": ["critical_phase"],
        "confidence": 0.5,
        "risk_estimate": 0.3,
        "explanation": "Critical-phase query held for external verification.",
        "policy_version": "opa-remora-v1",
    }
}
```

### Adapter usage

```python
from remora.policy.opa_adapter import OPAAdapter
from remora.policy.decision_engine import RemoraDecisionEngine

adapter = OPAAdapter(
    opa_url="http://opa.internal:8181",
    fallback_engine=RemoraDecisionEngine(conformal_trust_threshold=0.72),
)
report, fallback_used = adapter.evaluate(obs)
```

If the OPA daemon is unreachable, `fallback_used=True` and the Python engine
is used transparently. Log the `fallback_used` flag to a metrics endpoint so
OPA outages are visible in your observability stack.

### Deployment checklist

- [ ] Bundle the Rego package: `opa build -b policy/ -o remora-bundle.tar.gz`
- [ ] Serve with OPA daemon: `opa run --server --bundle remora-bundle.tar.gz`
- [ ] Set `opa_url` via environment variable, not hard-coded
- [ ] Enable OPA decision logging to the same audit sink as REMORA's D1 ledger
- [ ] Run `opa test policy/` in CI against golden input/output fixtures

---

## Policy Governance

Policy configurations are version-controlled in this repository (`enterprise/risk-profiles.yaml`). Changes to production policy profiles require:

1. Pull request with diff and stated rationale
2. Review by the domain owner and the AI governance function
3. Regression test against the domain's golden evaluation set
4. Monotone abstention check: new policy must not reduce the abstention rate on high-risk domains without evidence that the reduction is justified

This makes policy change auditable and prevents silent drift toward permissive configurations.
