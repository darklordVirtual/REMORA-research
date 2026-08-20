# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Remediation §19: the mandated end-to-end security matrix, machine-checked.

Every scenario the productization remediation requires is mapped to the
concrete test that pins it. This meta-test fails if a mapped test is renamed
or deleted, so the matrix cannot silently rot into a list of claims. The
mapped tests themselves run in the ordinary suite; this file only proves the
mapping stays real.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_FRONTEND = _TESTS.parent / "frontend" / "src"

#: §19 scenario -> (file, test name substring that must exist in it)
MATRIX: dict[str, tuple[Path, str]] = {
    "agent cannot self-approve": (
        _TESTS / "test_agent_control_approvals.py",
        "test_same_principal_cannot_self_approve",
    ),
    "agent cannot spoof reviewer": (
        _TESTS / "test_agent_control_approvals.py",
        "test_bearer_with_spoofed_human_headers_stays_workload",
    ),
    "reviewer cannot approve cross-tenant proposal": (
        _TESTS / "test_agent_control_approvals.py",
        "test_cross_tenant_grant_rejected",
    ),
    "approval cannot survive payload mutation": (
        _TESTS / "test_agent_control_approvals.py",
        "test_modified_arguments_rejected",
    ),
    "approval cannot survive ToolSpec mutation": (
        _TESTS / "test_agent_control_approvals.py",
        "test_stale_toolspec_rejected",
    ),
    "approval cannot survive policy mutation": (
        _TESTS / "test_agent_control_approvals.py",
        "test_stale_policy_rejected",
    ),
    "expired approval cannot execute": (
        _TESTS / "test_agent_control_approvals.py",
        "test_expired_approval_rejected",
    ),
    "expired token cannot execute": (
        _TESTS / "test_enforcement_gate_timestamps.py",
        "test_expired_token_fails_closed",
    ),
    "token with wrong audience cannot execute": (
        _TESTS / "test_token_hardening.py",
        "test_audience_binding",
    ),
    "lease with wrong actor cannot execute": (
        _TESTS / "test_execution_lease.py",
        "test_stolen_lease_refused_for_different_actor",
    ),
    "lease with wrong tenant cannot execute": (
        _TESTS / "test_execution_lease.py",
        "test_context_mismatch_refused",
    ),
    "lease with changed args cannot execute": (
        _TESTS / "test_execution_lease.py",
        "test_mutated_arguments_refused",
    ),
    "lease cannot replay": (
        _TESTS / "test_execution_lease.py",
        "test_nonce_ledger_is_atomic_single_use",
    ),
    "stale dispatch becomes UNKNOWN": (
        _TESTS / "test_outbox_reconciler_cli.py",
        "test_wall_clock_sweep_settles_idle_tenant",
    ),
    "UNKNOWN never auto-retries": (
        _TESTS / "test_execution_fault_injection.py",
        "",  # the crash-window matrix pins terminal/absorbing UNKNOWN semantics
    ),
    "audit failure is externally visible": (
        _TESTS / "test_execution_api.py",
        "test_durable_chain_signature_tamper_is_detected",
    ),
    "demo data never presents itself as live": (
        _FRONTEND / "components" / "demo-banner.test.ts",
        "every sim-backed route renders",
    ),
    "default MCP sends no external data": (
        _TESTS / "test_mcp_privacy_profiles.py",
        "test_default_profile_makes_zero_network_calls",
    ),
    "LLM consensus cannot establish legal citation existence": (
        _TESTS / "test_citation_existence.py",
        "test_unanimous_model_hallucination_never_verifies_existence",
    ),
}


@pytest.mark.parametrize("scenario", sorted(MATRIX))
def test_mandated_scenario_is_pinned_by_a_real_test(scenario: str) -> None:
    path, marker = MATRIX[scenario]
    assert path.exists(), f"{scenario}: mapped file missing: {path.name}"
    if marker:
        src = path.read_text(encoding="utf-8", errors="ignore")
        assert marker in src, (
            f"{scenario}: {path.name} no longer contains {marker!r} — update "
            "the matrix to the renamed test, never delete the scenario"
        )


def test_matrix_covers_all_nineteen_mandated_scenarios() -> None:
    assert len(MATRIX) >= 19  # rows are added as controls land; none may vanish
