# Author: Stian Skogbrott
# License: Apache-2.0
"""Fail-closed normalization: unknown is explicit and never coerced to safe."""
from __future__ import annotations

import pytest

from remora.governance_intelligence.normalization import (
    UNKNOWN,
    normalize_action_type,
    normalize_domain,
    normalize_environment,
    normalize_metadata,
    normalize_risk_tier,
    normalize_tool_name,
)


class TestRiskTierNormalization:
    @pytest.mark.parametrize("value,expected", [
        ("low", "low"), ("medium", "medium"), ("high", "high"), ("critical", "critical"),
        ("LOW", "low"), ("  Critical  ", "critical"), ("HiGh", "high"),
    ])
    def test_known_tiers(self, value, expected):
        assert normalize_risk_tier(value) == expected

    @pytest.mark.parametrize("value", [
        None, "", "  ", "hgih", "CRITICAL_RISK", "sev1", "0", "none", "unknown",
    ])
    def test_unknown_tiers(self, value):
        assert normalize_risk_tier(value) == UNKNOWN

    def test_unknown_never_maps_to_low(self):
        for value in (None, "", "typo", "med", "lo", "safe"):
            assert normalize_risk_tier(value) != "low"


class TestEnvironmentNormalization:
    @pytest.mark.parametrize("value,expected", [
        ("prod", "prod"), ("production", "prod"), ("live", "prod"), ("PROD", "prod"),
        ("stage", "staging"), ("staging", "staging"), ("test", "staging"),
        ("dev", "dev"), ("local", "dev"), ("development", "dev"),
    ])
    def test_aliases(self, value, expected):
        assert normalize_environment(value) == expected

    @pytest.mark.parametrize("value", [None, "", "qa-cluster", "produciton"])
    def test_unknown(self, value):
        assert normalize_environment(value) == UNKNOWN

    def test_unknown_never_maps_to_dev(self):
        assert normalize_environment("mystery") != "dev"


class TestActionTypeNormalization:
    @pytest.mark.parametrize("value,expected", [
        ("read", "read"), ("get", "read"), ("list", "read"), ("fetch", "read"),
        ("create", "write"), ("insert", "write"),
        ("update", "write"), ("patch", "write"), ("modify", "write"),
        ("delete", "destructive_write"), ("drop", "destructive_write"),
        ("truncate", "destructive_write"), ("wipe", "destructive_write"),
        ("shell", "shell_execute"), ("exec", "shell_execute"), ("run_command", "shell_execute"),
        ("dns", "dns_change"), ("update_dns", "dns_change"), ("cloudflare_dns", "dns_change"),
        ("firewall", "firewall_change"), ("security_rule", "firewall_change"),
        ("grant_access", "grant_permission"), ("add_user", "grant_permission"),
        ("invite_user", "grant_permission"),
        ("revoke_access", "revoke_permission"), ("remove_user", "revoke_permission"),
        ("transfer", "financial_write"), ("payment", "financial_write"),
        ("payout", "financial_write"),
    ])
    def test_aliases(self, value, expected):
        assert normalize_action_type(value) == expected

    @pytest.mark.parametrize("value", [None, "", "frobnicate", "maintenance_request"])
    def test_unknown(self, value):
        assert normalize_action_type(value) == UNKNOWN

    def test_unknown_never_maps_to_read(self):
        assert normalize_action_type("mystery_op") != "read"


class TestDomainAndToolNormalization:
    def test_domain(self):
        assert normalize_domain("  Finance ") == "finance"
        assert normalize_domain(None) is None
        assert normalize_domain("   ") is None

    def test_tool_name(self):
        assert normalize_tool_name(" Delete_Account ") == "delete_account"
        assert normalize_tool_name(None) is None


class TestDerivedFlags:
    def test_complete_metadata(self):
        meta = normalize_metadata(
            risk_tier="high", action_type="delete", target_environment="prod",
            domain="database", tool_name="drop_table",
        )
        assert meta.metadata_complete
        assert meta.metadata_unknown_fields == ()
        assert meta.mutating_action
        assert meta.production_like_environment
        assert meta.destructive_or_irreversible

    def test_missing_metadata_is_visible(self):
        meta = normalize_metadata()
        assert not meta.metadata_complete
        assert set(meta.metadata_unknown_fields) == {
            "risk_tier", "action_type", "target_environment",
        }
        assert meta.risk_tier == UNKNOWN
        assert meta.action_type == UNKNOWN
        assert meta.target_environment == UNKNOWN

    def test_unknown_action_is_not_mutating_but_not_safe(self):
        # Unknown action type cannot prove mutation, but it normalises to the
        # explicit "unknown" sentinel that downstream gates treat as risk.
        meta = normalize_metadata(action_type="mystery")
        assert meta.action_type == UNKNOWN
        assert not meta.mutating_action
        assert "action_type" in meta.metadata_unknown_fields

    def test_read_is_not_destructive(self):
        meta = normalize_metadata(
            risk_tier="low", action_type="read", target_environment="dev",
        )
        assert not meta.mutating_action
        assert not meta.destructive_or_irreversible

    def test_raw_values_preserved_for_audit(self):
        meta = normalize_metadata(risk_tier="HiGh", action_type="Drop",
                                  target_environment="LIVE")
        assert meta.raw_risk_tier == "HiGh"
        assert meta.raw_action_type == "Drop"
        assert meta.raw_target_environment == "LIVE"
