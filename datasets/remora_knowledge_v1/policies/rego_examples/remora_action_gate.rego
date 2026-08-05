# REMORA Action Gate — Rego policy example
# Demonstrates how REMORA gate rules can be expressed as OPA/Rego policies.
# This is an illustrative example, not the canonical REMORA policy engine.
# The authoritative gate logic lives in remora/policy/decision_engine.py.
#
# Input contract: the full OPAContext exported by
# remora/policy/opa_adapter.py:export_opa_context — every field the Python
# decision path reads is present in `input` (enforced by
# tests/test_opa_parity.py). Policies must check the hard-block signals
# below; the adapter additionally floors any result that is weaker than the
# Python engine's hard-guard verdict, so omitting a check here can tighten
# but never loosen enforcement.
#
# Conformance: scripts/opa_conformance.py evaluates this policy against a
# golden observation set and compares it with the Python engine.

package remora.action_gate

import rego.v1

# Default: deny (conservative)
default gate := "ESCALATE"

# ---------------------------------------------------------------------------
# Hard blocks — mirror remora.policy.decision_engine.hard_guard_floor()
# ---------------------------------------------------------------------------

hard_escalate if { input.adversarial_detected == true }

hard_escalate if { input.schema_valid == false }

hard_escalate if { input.tool_forbidden == true }

hard_escalate if { input.coercion_detected == true }

hard_escalate if { input.blackmail_pattern_detected == true }

hard_escalate if { input.counterfactual_passed == false }

# Contradicting evidence with contradiction cycles → ESCALATE
hard_escalate if {
	input.evidence_contradictions > 0
	input.contradiction_cycles > 0
}

# Critical destructive action targeting production → ESCALATE
hard_escalate if {
	critical_destructive_action
	input.target_environment in {"production", "prod", "live"}
}

# Tainted argument at CRITICAL risk → ESCALATE, never an approvable VERIFY
# (engine parity: issue #40 decision, 2026-07-30).
hard_escalate if {
	input.argument_tainted == true
	input.risk_tier == "critical"
}

# Tainted arguments must never auto-accept (VERIFY floor in the engine;
# critical tier is caught by the hard_escalate rule above).
tainted_floor if { input.argument_tainted == true }

# Contradicting evidence without cycles → ABSTAIN (engine parity)
contradiction_abstain if {
	input.evidence_contradictions > 0
	not input.contradiction_cycles > 0
}

# ---------------------------------------------------------------------------
# Gate — hard blocks first, then risk-tier routing
# ---------------------------------------------------------------------------

gate := "ESCALATE" if { hard_escalate }

gate := "ABSTAIN" if {
	contradiction_abstain
	not hard_escalate
}

gate := "VERIFY" if {
	tainted_floor
	not hard_escalate
	not contradiction_abstain
}

# ACCEPT: low risk, read-only, ordered phase, clean signals
gate := "ACCEPT" if {
	clean_signals
	input.risk_tier == "low"
	input.action_type in {"read", "query", "list", "describe", "metrics"}
	input.phase == "ordered"
	input.trust_score >= 0.8
}

# ACCEPT: dry-run in non-production, outside the fail-closed risk band.
#
# The risk-tier exclusion is required, not cosmetic: without it a HIGH or
# CRITICAL simulate-family action outside production matched both this rule
# and the "missing evidence on high/critical" VERIFY rule below. Two complete
# rules producing different values is an `eval_conflict_error` in Rego, so OPA
# returned NO decision at all for that input — a policy crash, not a verdict
# (found by the OT/Rego test set, 2026-08-04; golden set only carried a MEDIUM
# dry-run, so CI never reached it). Precedence resolves the same way the
# disordered-ABSTAIN rule already documents: the risk-tier evidence floor wins.
gate := "ACCEPT" if {
	clean_signals
	input.action_type in {"dry_run", "plan", "preview", "simulate"}
	not input.target_environment in {"production", "prod", "live"}
	not input.risk_tier in {"high", "critical"}
	not disordered_abstain
}

# VERIFY: medium risk in a known phase (dry-runs are handled by ACCEPT above)
gate := "VERIFY" if {
	clean_signals
	input.risk_tier == "medium"
	input.phase in {"ordered", "critical"}
	not critical_destructive_action
	not input.action_type in {"dry_run", "plan", "preview", "simulate"}
}

# VERIFY: high risk with evidence present
gate := "VERIFY" if {
	clean_signals
	input.risk_tier == "high"
	input.evidence_action == "verify"
	input.evidence_confidence >= 0.5
}

# VERIFY: missing evidence on high/critical
# (full-export contract: absent fields arrive as null, so test for null
# explicitly — `not input.evidence_action` never succeeds on null)
gate := "VERIFY" if {
	clean_signals
	input.risk_tier in {"high", "critical"}
	input.evidence_action == null
	not critical_destructive_action
}

# ABSTAIN: disordered phase, no evidence, low trust.
# High/critical risk routes to the VERIFY rule above instead (engine parity:
# the risk-tier evidence floor has priority over the disordered abstain).
#
# Expressed as a named condition so the dry-run ACCEPT rule above can exclude
# it explicitly. Without that exclusion the two rules co-fired on
# simulate-family actions in a disordered, low-trust, non-production state
# (six inputs, found by scripts/opa_conflict_sweep.py on 2026-08-04) and the
# policy produced no verdict at all. Precedence goes to the stricter rule:
# a disordered phase with no evidence and low trust is not a state to act
# autonomously in, dry run or not.
disordered_abstain if {
	input.phase == "disordered"
	input.evidence_action == null
	input.trust_score < 0.4
	not input.risk_tier in {"high", "critical"}
}

gate := "ABSTAIN" if {
	clean_signals
	disordered_abstain
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# No hard-block, taint, or contradiction signal fired.
clean_signals if {
	not hard_escalate
	not tainted_floor
	not contradiction_abstain
}

critical_destructive_action if {
	input.risk_tier == "critical"
	input.action_type in {
		"destructive_write", "delete", "purge", "drop",
		"truncate", "terraform_destroy", "bulk_delete",
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
