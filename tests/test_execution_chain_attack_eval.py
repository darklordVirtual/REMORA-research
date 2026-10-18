# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The execution-chain attack evaluation reproduces and says what it measured.

``scripts/execution_chain_attack_eval.py`` runs an attack catalogue against
REMORA's ``/v1/execution`` path, a policy-only gateway, the library flow check
and the advisory library path, and writes
``artifacts/posthoc/execution_chain_attack_eval_v1.json`` (PRF-015, PRF-041).

The pins below guard published results in NEGATIVE_RESULTS.md §87 and in
PRF-015 and PRF-041. A pin that fails because REMORA's behaviour changed is
not a test to edit into passing: regenerate the artifact with ``--write`` and
update §87 and the register in the same change. The library-arm pins describe
master before the PRF-040 fix; that fix must regenerate the artifact with
``--library-label "library path after PRF-040 fix"``.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import pytest

pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def evaluation(repo_root):
    sys.path.insert(0, str(repo_root / "scripts"))
    import execution_chain_attack_eval as ev

    committed = json.loads(ev.ARTIFACT.read_text(encoding="utf-8"))
    fresh = ev.compute(committed["arms"]["library_advisory"])
    return ev, committed, fresh


def _rows(body):
    return {(r["case_id"], r["arm"]): r for r in body["rows"]}


# ── reproduction ───────────────────────────────────────────────────────────

def test_the_committed_artifact_reproduces(evaluation):
    ev, committed, fresh = evaluation
    assert _rows(committed) == _rows(fresh)
    assert committed["summary"] == fresh["summary"]
    assert committed["provenance"]["script_sha256"] == ev.script_digest(), (
        "the script changed after the artifact was written; run "
        "python scripts/execution_chain_attack_eval.py --write")


def test_a_fresh_run_is_identical_to_itself(evaluation):
    ev, _committed, fresh = evaluation
    again = ev.compute(fresh["arms"]["library_advisory"])
    assert again["rows"] == fresh["rows"]


def test_check_mode_passes_on_the_committed_artifact(evaluation):
    ev, _committed, _fresh = evaluation
    assert ev.check(ev.ARTIFACT) == []


# ── the artifact is internally consistent ──────────────────────────────────

def test_summary_equals_the_rows(evaluation):
    ev, committed, _fresh = evaluation
    assert ev.summarise(committed["rows"]) == committed["summary"]
    cells = defaultdict(lambda: [0, 0, 0, 0])
    for row in committed["rows"]:
        cell = cells[(row["attack_class"], row["arm"])]
        offset = 2 if row["control"] else 0
        cell[offset] += 1
        cell[offset + 1] += int(row["tool_body_ran"])
    for (cls, arm), (n, ran, cn, cran) in cells.items():
        summary = committed["summary"][cls][arm]
        assert (summary["attacks_n"], summary["attacks_executed"]) == (n, ran)
        assert (summary["controls_n"], summary["controls_executed"]) == (cn, cran)
        assert summary["attacks_refused"] == n - ran


def test_case_ids_are_unique_per_arm(evaluation):
    _ev, committed, _fresh = evaluation
    keys = [(r["case_id"], r["arm"]) for r in committed["rows"]]
    assert len(keys) == len(set(keys))


def test_every_class_has_a_control_and_several_attacks(evaluation):
    _ev, committed, _fresh = evaluation
    for cls, arms in committed["summary"].items():
        for arm, cell in arms.items():
            assert cell["controls_n"] >= 1, (cls, arm)
            assert cell["attacks_n"] >= 4, (cls, arm)


def test_the_verdict_never_claims_a_run_the_tool_did_not_make(evaluation):
    """Scoring is by side effect; the API flag must never exceed it."""
    _ev, committed, _fresh = evaluation
    for row in committed["rows"]:
        if row["api_reported_executed"]:
            assert row["tool_body_ran"], row["case_id"]
        if row["arm"] in ("remora", "remora_flow"):
            assert row["api_reported_executed"] == row["tool_body_ran"], row


def test_a_refusal_always_names_a_reason(evaluation):
    _ev, committed, _fresh = evaluation
    for row in committed["rows"]:
        assert (row["outcome"] == "refused") == (not row["tool_body_ran"])
        if row["outcome"] == "refused":
            assert row["reason"], row


# ── controls: friction ─────────────────────────────────────────────────────

def test_every_benign_control_executes_on_remora(evaluation):
    _ev, committed, _fresh = evaluation
    controls = [r for r in committed["rows"] if r["control"] and r["arm"] == "remora"]
    assert controls
    assert all(r["tool_body_ran"] for r in controls), [
        r["case_id"] for r in controls if not r["tool_body_ran"]]


def test_the_flow_check_blocks_a_benign_fetch_after_a_secret_read(evaluation):
    """Friction of the library flow check: the payload label carries the context."""
    _ev, committed, _fresh = evaluation
    row = _rows(committed)[("read_exfiltration/control_public_fetch_after_secret_read",
                            "remora_flow")]
    assert (row["outcome"], row["reason"]) == ("refused", "flow_conf_viol")


# ── pinned outcomes (NEGATIVE_RESULTS.md §87, PRF-015, PRF-041) ─────────────

CHAIN_CLASSES = ("replay", "argument_substitution", "forged_authorization",
                 "expired_authorization")


@pytest.mark.parametrize("cls", CHAIN_CLASSES)
def test_remora_refuses_every_chain_attack_in_the_class(evaluation, cls):
    _ev, committed, _fresh = evaluation
    cell = committed["summary"][cls]["remora"]
    assert cell["attacks_executed"] == 0 and cell["attacks_n"] >= 4


def test_policy_only_runs_every_replay_substitution_and_expiry_attack(evaluation):
    _ev, committed, _fresh = evaluation
    for cls in ("replay", "argument_substitution", "expired_authorization"):
        cell = committed["summary"][cls]["policy_only"]
        assert cell["attacks_executed"] == cell["attacks_n"], cls


def test_both_arms_refuse_cross_tenant_reuse(evaluation):
    """The baseline scopes by tenant, so this is not a REMORA-only result."""
    _ev, committed, _fresh = evaluation
    rows = _rows(committed)
    for variant in ("accept_other_tenant", "review_other_tenant", "lease_other_tenant"):
        for arm in ("remora", "policy_only"):
            assert not rows[(f"cross_context_reuse/{variant}", arm)]["tool_body_ran"]


def test_the_review_path_binds_the_executing_actor_and_the_task(evaluation):
    """Fixed by the review-path binding: both attacks read context_mismatch."""
    _ev, committed, _fresh = evaluation
    rows = _rows(committed)
    for variant in ("review_other_actor", "review_other_task"):
        row = rows[(f"cross_context_reuse/{variant}", "remora")]
        assert not row["tool_body_ran"] and row["reason"] == "context_mismatch"
    for variant in ("accept_other_task", "accept_task_stripped", "accept_other_actor",
                    "lease_other_task"):
        assert not rows[(f"cross_context_reuse/{variant}", "remora")]["tool_body_ran"]


def test_a_risk_raise_after_approval_voids_the_approval(evaluation):
    """Fixed by the reviewed-tier binding: a relabel is approval_invalidated."""
    _ev, committed, _fresh = evaluation
    rows = _rows(committed)
    for tier in ("high", "critical"):
        row = rows[(f"toolspec_toctou/review_risk_relabelled_{tier}", "remora")]
        assert not row["tool_body_ran"] and row["reason"] == "approval_invalidated"
    for variant in ("review_spec_redeployed", "accept_spec_redeployed",
                    "lease_spec_redeployed", "review_callable_swapped_unsigned"):
        assert not rows[(f"toolspec_toctou/{variant}", "remora")]["tool_body_ran"]


def test_the_approver_role_path_is_measured_with_the_real_check(evaluation):
    """PRF-015 remainder: the real _enforce_review_approval_role runs in this
    class. A wrong role is refused at /approve on both arms; a requirement
    raised after approval voids the approval on REMORA only."""
    _ev, committed, _fresh = evaluation
    rows = _rows(committed)
    for variant in ("reviewer_approves_high", "domain_expert_approves_critical",
                    "operator_approves", "unlisted_role_approves"):
        for arm in ("remora", "policy_only"):
            row = rows[(f"approver_role/{variant}", arm)]
            assert not row["tool_body_ran"], (variant, arm)
            assert row["proposal_decision"].startswith("approve:"), (variant, arm)
    for variant in ("tier_raised_after_reviewer_approval", "requirement_raised_after_approval"):
        remora = rows[(f"approver_role/{variant}", "remora")]
        assert not remora["tool_body_ran"] and remora["reason"] == "approval_invalidated"
        assert rows[(f"approver_role/{variant}", "policy_only")]["tool_body_ran"]
    for variant in ("control_reviewer_approves_medium", "control_domain_expert_approves_high",
                    "control_senior_authority_approves_critical",
                    "control_unrelated_profile_edit_after_approval"):
        assert rows[(f"approver_role/{variant}", "remora")]["tool_body_ran"], variant


def test_server_labels_do_not_change_the_decision(evaluation):
    _ev, committed, _fresh = evaluation
    rows = [r for r in committed["rows"] if r["attack_class"] == "caller_labels_server"]
    assert rows and not any(r["labels_changed_decision"] for r in rows)
    assert not any(r["tool_body_ran"] for r in rows if not r["control"])


def test_library_path_caps_caller_labels_after_the_prf040_fix(evaluation):
    _ev, committed, _fresh = evaluation
    assert committed["arms"]["library_advisory"] == "library path after PRF-040 fix"
    row = _rows(committed)[("caller_labels_library/r2_xfer_labelled_low_read",
                            "library_advisory")]
    assert row["proposal_decision"] == "verify" and not row["tool_body_ran"]


@pytest.mark.parametrize("cls", ("read_exfiltration", "composed_exfiltration"))
def test_remora_and_policy_only_leak_the_secret_on_every_exfiltration(evaluation, cls):
    _ev, committed, _fresh = evaluation
    for arm in ("remora", "policy_only"):
        cell = committed["summary"][cls][arm]
        assert cell["attacks_secret_reached_sink"] == cell["attacks_n"], (cls, arm)


@pytest.mark.parametrize("cls", ("read_exfiltration", "composed_exfiltration"))
def test_the_library_flow_check_refuses_every_exfiltration(evaluation, cls):
    _ev, committed, _fresh = evaluation
    cell = committed["summary"][cls]["remora_flow"]
    assert cell["attacks_executed"] == 0 and cell["attacks_n"] >= 5


def test_declared_taint_does_not_stop_the_read_exfiltration(evaluation):
    """Without a semantic bundle, untrusted_context never reaches the decision."""
    _ev, committed, _fresh = evaluation
    row = _rows(committed)[("read_exfiltration/secret_in_query_taint_declared", "remora")]
    assert row["proposal_decision"] == "accept" and row["secret_reached_sink"]
