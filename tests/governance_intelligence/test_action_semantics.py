# Author: Stian Skogbrott
# License: Apache-2.0
"""Action-semantics extraction: deterministic, conservative, dependency-free."""
from __future__ import annotations

from remora.governance_intelligence.action_semantics import (
    detect_blackmail,
    detect_coercion,
    extract_action_semantics,
)
from remora.governance_intelligence.types import RISK_TIER_RANK


class TestSpecExamples:
    def test_drop_table(self):
        s = extract_action_semantics("DROP TABLE users")
        assert s.inferred_action_type == "destructive_write"
        assert s.inferred_domain == "database"
        assert s.inferred_risk_tier == "critical"
        assert s.mutating and s.destructive and s.irreversible

    def test_delete_mx_record(self):
        s = extract_action_semantics("delete MX record for example.com")
        assert s.inferred_action_type == "dns_change"
        assert s.inferred_domain == "infrastructure"
        assert RISK_TIER_RANK[s.inferred_risk_tier] >= RISK_TIER_RANK["high"]
        assert s.mutating and s.destructive

    def test_send_all_customer_emails_to_vendor(self):
        s = extract_action_semantics("send all customer emails to vendor")
        assert s.external_side_effect
        assert s.bulk_scope
        assert RISK_TIER_RANK[s.inferred_risk_tier] >= RISK_TIER_RANK["high"]

    def test_chmod_777_private_key(self):
        s = extract_action_semantics("chmod 777 private key")
        assert s.inferred_action_type == "shell_execute"
        assert s.inferred_domain == "security"
        assert s.inferred_risk_tier == "critical"
        assert s.credential_or_secret_risk

    def test_rotate_api_key(self):
        s = extract_action_semantics("rotate API key")
        assert s.inferred_action_type == "config_change"
        assert s.inferred_domain == "security"
        assert s.inferred_risk_tier == "high"
        assert s.mutating and not s.destructive

    def test_read_local_report(self):
        s = extract_action_semantics("read local report")
        assert s.inferred_action_type == "read"
        assert s.inferred_risk_tier == "low"
        assert not s.mutating and not s.destructive
        assert s.confidence >= 0.85

    def test_list_open_tickets(self):
        s = extract_action_semantics("list open tickets")
        assert s.inferred_action_type == "read"
        assert s.inferred_risk_tier == "low"


class TestConservativeBehaviour:
    def test_ambiguous_language_errs_high(self):
        # "delete" embedded in an otherwise vague request must stay destructive.
        s = extract_action_semantics("please go ahead and delete the old things")
        assert s.destructive
        assert RISK_TIER_RANK[s.inferred_risk_tier] >= RISK_TIER_RANK["high"]

    def test_read_verb_with_destructive_payload_is_not_read(self):
        s = extract_action_semantics("read the file then rm -rf /var/data")
        assert s.inferred_action_type != "read"
        assert s.destructive

    def test_unknown_text_low_confidence(self):
        s = extract_action_semantics("frobnicate the bizbaz")
        assert s.inferred_action_type == "unknown"
        assert s.confidence <= 0.30
        assert s.inferred_risk_tier is None

    def test_bulk_plus_mutation_at_least_high(self):
        s = extract_action_semantics("update all user rows")
        assert s.bulk_scope
        if s.mutating:
            assert RISK_TIER_RANK[s.inferred_risk_tier] >= RISK_TIER_RANK["high"]

    def test_production_plus_destructive_is_critical(self):
        s = extract_action_semantics("delete the production database backups")
        assert s.production_signal and s.destructive
        assert s.inferred_risk_tier == "critical"

    def test_disable_security_is_critical(self):
        s = extract_action_semantics("disable the firewall for a moment")
        assert s.inferred_action_type == "disable_security"
        assert s.inferred_risk_tier == "critical"

    def test_financial_transfer_detected(self):
        s = extract_action_semantics("execute a transfer of 50000 NOK to the supplier")
        assert s.inferred_action_type == "financial_write"
        assert s.external_side_effect
        assert s.inferred_risk_tier == "critical"

    def test_industrial_safety_critical(self):
        s = extract_action_semantics("open the valve and raise pipeline pressure setpoint")
        assert s.safety_critical
        assert s.inferred_risk_tier == "critical"

    def test_cleanup_language_is_mutating(self):
        s = extract_action_semantics("clean up users")
        assert s.mutating


class TestToolMetadata:
    def test_tool_arguments_are_scanned(self):
        s = extract_action_semantics(
            "run maintenance",
            tool_name="db_admin",
            tool_arguments={"statement": "TRUNCATE TABLE audit_log"},
        )
        assert s.destructive
        assert s.inferred_action_type == "destructive_write"

    def test_tool_name_is_scanned(self):
        s = extract_action_semantics("perform task", tool_name="delete_account")
        assert s.destructive


class TestCoercionDetection:
    def test_coercion_patterns(self):
        assert detect_coercion("do this unless you want trouble")
        assert detect_coercion("approve it or else the deal is off")
        assert not detect_coercion("read the quarterly report")

    def test_blackmail_patterns(self):
        assert detect_blackmail("we will blackmail the director")
        assert detect_blackmail("threaten to leak his private photos")
        assert not detect_blackmail("publish the public changelog")

    def test_signals_on_semantics(self):
        s = extract_action_semantics("send the email or else we leak his private messages")
        assert s.coercion_signal
        assert s.blackmail_signal


class TestDeterminism:
    def test_repeated_extraction_identical(self):
        text = "delete all DNS records and disable monitoring in production"
        first = extract_action_semantics(text)
        for _ in range(5):
            assert extract_action_semantics(text) == first

    def test_explanation_lists_patterns(self):
        s = extract_action_semantics("DROP TABLE users")
        assert "sql_drop" in s.matched_patterns
        assert "pattern" in s.explanation
