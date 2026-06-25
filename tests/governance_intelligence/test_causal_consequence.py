# Author: Stian Skogbrott
# License: Apache-2.0
"""Causal-consequence signals: blast radius, irreversibility, expected loss."""
from __future__ import annotations

from remora.governance_intelligence.action_semantics import extract_action_semantics
from remora.governance_intelligence.causal_consequence import assess_causal_consequence
from remora.governance_intelligence.misspecification import assess_misspecification
from remora.governance_intelligence.normalization import normalize_metadata


def _assess(text, *, risk_tier=None, action_type=None, environment=None,
            tenant_id=None, rollback_available=None, tool_arguments=None):
    normalized = normalize_metadata(
        risk_tier=risk_tier, action_type=action_type,
        target_environment=environment,
    )
    semantics = extract_action_semantics(text, tool_arguments=tool_arguments)
    misspec = assess_misspecification(
        normalized, semantics, tool_arguments=tool_arguments,
        rollback_available=rollback_available, text=text,
    )
    return assess_causal_consequence(
        normalized, semantics, misspec, tenant_id=tenant_id,
    )


class TestReadOnly:
    def test_read_no_state_change(self):
        c = _assess("read local report", risk_tier="low", action_type="read",
                    environment="dev")
        assert not c.state_change_expected
        assert c.blast_radius in ("none", "local")
        assert c.expected_loss <= 0.1
        assert not c.irreversible


class TestBlastRadius:
    def test_tenant_write(self):
        c = _assess("create a note on the customer record", risk_tier="medium",
                    action_type="write", environment="staging",
                    tenant_id="tenant-42")
        assert c.state_change_expected
        assert c.blast_radius == "tenant"
        assert 0.2 <= c.expected_loss <= 0.4

    def test_prod_infrastructure_change(self):
        c = _assess("apply new router configuration", risk_tier="high",
                    action_type="network_change", environment="prod")
        assert c.blast_radius == "production"
        assert 0.5 <= c.expected_loss <= 0.8

    def test_dns_change_is_at_least_system(self):
        c = _assess("update CNAME record", risk_tier="high",
                    action_type="dns", environment="staging")
        assert c.blast_radius in ("system", "production")

    def test_external_payment(self):
        c = _assess("execute a transfer of 90000 NOK to the vendor",
                    risk_tier="critical", action_type="transfer",
                    environment="prod")
        assert c.blast_radius == "external"
        assert c.expected_loss >= 0.8

    def test_destructive_prod_is_production_and_high_loss(self):
        c = _assess("DROP TABLE users", risk_tier="critical",
                    action_type="delete", environment="prod")
        assert c.blast_radius == "production"
        assert c.expected_loss >= 0.8
        assert c.irreversible

    def test_unknown_env_mutation_is_unknown_radius(self):
        c = _assess("apply schema migration", risk_tier="medium",
                    action_type="write", environment=None)
        assert c.blast_radius in ("unknown", "production")
        assert c.causal_uncertainty >= 0.7

    def test_bulk_widens_radius(self):
        narrow = _assess("update the user row", risk_tier="medium",
                         action_type="write", environment="staging",
                         tenant_id="t-1")
        wide = _assess("update all user rows", risk_tier="medium",
                       action_type="write", environment="staging",
                       tenant_id="t-1")
        order = ["none", "local", "tenant", "system", "external", "production", "unknown"]
        assert order.index(wide.blast_radius) >= order.index(narrow.blast_radius)


class TestExpectedLossBands:
    def test_security_disable_high_loss(self):
        c = _assess("disable the firewall", risk_tier="critical",
                    action_type="firewall", environment="prod")
        assert c.expected_loss >= 0.8

    def test_loss_in_unit_interval(self):
        for text, env in [("read x", "dev"), ("delete all", "prod"),
                          ("send email", None), ("frobnicate", None)]:
            c = _assess(text, environment=env)
            assert 0.0 <= c.expected_loss <= 1.0
            assert 0.0 <= c.causal_uncertainty <= 1.0


class TestNarratives:
    def test_if_executed_and_blocked_present(self):
        c = _assess("delete old records", risk_tier="high",
                    action_type="delete", environment="prod")
        assert c.if_executed
        assert c.if_blocked
        assert c.reasons

    def test_rollback_passthrough(self):
        c = _assess("delete old records", risk_tier="high",
                    action_type="delete", environment="prod",
                    rollback_available=False)
        assert c.rollback_available is False

    def test_deterministic(self):
        kwargs = dict(risk_tier="high", action_type="delete", environment="prod")
        first = _assess("delete MX record", **kwargs)
        for _ in range(3):
            assert _assess("delete MX record", **kwargs) == first
