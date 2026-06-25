# REMORA Action Gate — Rego policy example
# Demonstrates how REMORA gate rules can be expressed as OPA/Rego policies.
# This is an illustrative example, not the canonical REMORA policy engine.
# The authoritative gate logic lives in remora/policy/decision_engine.py.

package remora.action_gate

import rego.v1

# Default: deny (conservative)
default gate := "ESCALATE"

# ACCEPT: low risk, read-only, ordered phase, no adversarial
gate := "ACCEPT" if {
    input.risk_tier == "low"
    input.action_type in {"read", "query", "list", "describe", "metrics"}
    input.phase == "ordered"
    not input.adversarial_detected
    input.trust_score >= 0.8
}

# ACCEPT: dry-run in non-production
gate := "ACCEPT" if {
    input.action_type in {"dry_run", "plan", "preview", "simulate"}
    not input.target_environment in {"production", "prod"}
}

# VERIFY: medium risk or critical phase
gate := "VERIFY" if {
    input.risk_tier == "medium"
    input.phase in {"ordered", "critical"}
    not input.adversarial_detected
    not critical_destructive_action
}

# VERIFY: high risk with evidence present
gate := "VERIFY" if {
    input.risk_tier == "high"
    input.evidence_action == "verify"
    input.evidence_confidence >= 0.5
    not input.adversarial_detected
}

# VERIFY: missing evidence on high/critical
gate := "VERIFY" if {
    input.risk_tier in {"high", "critical"}
    not input.evidence_action
    not input.adversarial_detected
    not critical_destructive_action
}

# ABSTAIN: disordered phase, no evidence
gate := "ABSTAIN" if {
    input.phase == "disordered"
    not input.evidence_action
    input.trust_score < 0.4
}

# ABSTAIN: contradicting evidence
gate := "ABSTAIN" if {
    input.evidence_contradictions > 0
    input.risk_tier in {"high", "critical"}
}

# ESCALATE: adversarial always
gate := "ESCALATE" if {
    input.adversarial_detected == true
}

# ESCALATE: critical destructive in production
gate := "ESCALATE" if {
    critical_destructive_action
    input.target_environment in {"production", "prod"}
}

# ESCALATE: counterfactual failed
gate := "ESCALATE" if {
    input.counterfactual_passed == false
}

# Helper: critical destructive action
critical_destructive_action if {
    input.risk_tier == "critical"
    input.action_type in {
        "destructive_write", "delete", "purge", "drop",
        "truncate", "terraform_destroy", "bulk_delete"
    }
}

# Audit fields
requires_human_review if {
    gate in {"ESCALATE", "VERIFY"}
}

requires_evidence if {
    gate in {"VERIFY", "ESCALATE"}
    input.risk_tier in {"high", "critical"}
}
