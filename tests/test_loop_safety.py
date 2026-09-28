# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Loop safety state keyed on the context, non-decaying, reset only by policy (Q7.2).

Design property 4 of docs/design/task-bound-execution-authority-v1.md: state
accumulated in one process is visible to another, and an unreadable store
refuses rather than reporting nothing accumulated. Two separate
``DurableLoopSafetyStore`` instances on one SQLite file stand in for two
processes; the in-memory store is the control that must not share.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.governance.loop_safety import (
    AUTHORITY_PROBE,
    DENIED_INTENT,
    IRREVERSIBLE_EFFECT,
    TOOL_SWITCH_AFTER_DENIAL,
    DurableLoopSafetyStore,
    InMemoryLoopSafetyStore,
    LoopEvent,
    LoopSafetyMonitor,
    LoopSafetyPolicy,
    LoopSafetyStore,
    LoopSafetyStoreUnavailable,
    fold,
)
from remora.governance.task_identity import TaskIdentity

TENANT = "acme"
ITERATION_1 = TaskIdentity(context_id="ctx-1", task_id="iteration-1")
ITERATION_2 = TaskIdentity(context_id="ctx-1", task_id="iteration-2")
ITERATION_3 = TaskIdentity(context_id="ctx-1", task_id="iteration-3")
OTHER_CONTEXT = TaskIdentity(context_id="ctx-2", task_id="iteration-1")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path) -> LoopSafetyStore:
    if request.param == "memory":
        return InMemoryLoopSafetyStore()
    return DurableLoopSafetyStore(db_path=str(tmp_path / "loop.db"))


class TestStateDoesNotDecayAcrossIterations:
    """The failure Wu et al. describe: each iteration under threshold, the loop not."""

    def test_denials_in_separate_tasks_accumulate_in_one_context(self, store):
        monitor = LoopSafetyMonitor(store)
        for task in (ITERATION_1, ITERATION_2, ITERATION_3):
            verdict = monitor.observe(TENANT, task, "wo_close", denied=True)
        assert verdict.state.count(DENIED_INTENT) == 3
        assert verdict.state.tasks == ("iteration-1", "iteration-2", "iteration-3")
        assert verdict.action == "escalate"
        assert verdict.reached == (DENIED_INTENT,)

    def test_a_per_task_view_would_have_stayed_under_every_limit(self, store):
        """The control: each iteration alone has one denial, below the limit of 3."""
        monitor = LoopSafetyMonitor(store)
        for task in (ITERATION_1, ITERATION_2, ITERATION_3):
            monitor.observe(TENANT, task, "wo_close", denied=True)
        events = store.events(tenant_id=TENANT, context_id="ctx-1")
        per_task = [fold(TENANT, "ctx-1", [e for e in events if e.task_id == t])
                    for t in ("iteration-1", "iteration-2", "iteration-3")]
        assert all(LoopSafetyPolicy().assess(s).action == "continue" for s in per_task)

    def test_contexts_do_not_share_state(self, store):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        assert monitor.state(TENANT, OTHER_CONTEXT.context_id).count(DENIED_INTENT) == 0

    def test_tenants_do_not_share_state(self, store):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        assert monitor.state("other-tenant", "ctx-1").count(DENIED_INTENT) == 0


class TestSignals:
    def test_a_different_tool_right_after_a_denial_is_a_switch(self, store):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        verdict = monitor.observe(TENANT, ITERATION_2, "wo_delete", denied=False)
        assert verdict.state.count(TOOL_SWITCH_AFTER_DENIAL) == 1

    def test_retrying_the_same_tool_is_not_a_switch(self, store):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        verdict = monitor.observe(TENANT, ITERATION_1, "wo_close", denied=False)
        assert verdict.state.count(TOOL_SWITCH_AFTER_DENIAL) == 0

    def test_only_the_call_immediately_after_a_denial_counts(self, store):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        monitor.observe(TENANT, ITERATION_1, "wo_read", denied=False)
        verdict = monitor.observe(TENANT, ITERATION_1, "wo_list", denied=False)
        assert verdict.state.count(TOOL_SWITCH_AFTER_DENIAL) == 1

    def test_one_authority_probe_escalates_by_default(self, store):
        verdict = LoopSafetyMonitor(store).observe(
            TENANT, ITERATION_1, "grant_role", denied=True, authority_probe=True)
        assert AUTHORITY_PROBE in verdict.reached

    def test_irreversible_effects_are_counted_but_unlimited_by_default(self, store):
        monitor = LoopSafetyMonitor(store)
        for _ in range(5):
            verdict = monitor.observe(TENANT, ITERATION_1, "send_payment",
                                      denied=False, irreversible=True)
        assert verdict.state.count(IRREVERSIBLE_EFFECT) == 5
        assert verdict.action == "continue"

    def test_a_denied_call_caused_no_irreversible_effect(self, store):
        verdict = LoopSafetyMonitor(store).observe(
            TENANT, ITERATION_1, "send_payment", denied=True, irreversible=True)
        assert verdict.state.count(IRREVERSIBLE_EFFECT) == 0


class TestOnlyPolicyResets:
    def test_a_new_task_does_not_reset(self, store):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        verdict = monitor.observe(TENANT, ITERATION_2, "wo_close", denied=False)
        assert verdict.state.count(DENIED_INTENT) == 1

    def test_a_policy_reset_starts_the_count_again_and_keeps_history(self, store):
        monitor = LoopSafetyMonitor(store)
        for task in (ITERATION_1, ITERATION_2, ITERATION_3):
            monitor.observe(TENANT, task, "wo_close", denied=True)
        monitor.reset(TENANT, "ctx-1", policy_ref="decision-42", reason="reviewed")
        assert monitor.assess(TENANT, "ctx-1").action == "continue"
        history = store.events(tenant_id=TENANT, context_id="ctx-1")
        assert len(history) == 4
        assert history[-1].detail == "policy_ref=decision-42; reason=reviewed"

    @pytest.mark.parametrize("policy_ref", ["", "   "])
    def test_an_anonymous_reset_is_refused(self, store, policy_ref):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        with pytest.raises(ValueError, match="policy decision"):
            monitor.reset(TENANT, "ctx-1", policy_ref=policy_ref)
        assert monitor.state(TENANT, "ctx-1").count(DENIED_INTENT) == 1

    def test_a_reset_clears_a_pending_switch(self, store):
        monitor = LoopSafetyMonitor(store)
        monitor.observe(TENANT, ITERATION_1, "wo_close", denied=True)
        monitor.reset(TENANT, "ctx-1", policy_ref="decision-42")
        verdict = monitor.observe(TENANT, ITERATION_2, "wo_delete", denied=False)
        assert verdict.state.count(TOOL_SWITCH_AFTER_DENIAL) == 0


class TestDurability:
    """Design property 4."""

    def test_state_recorded_by_one_process_is_read_by_another(self, tmp_path):
        path = str(tmp_path / "loop.db")
        LoopSafetyMonitor(DurableLoopSafetyStore(db_path=path)).observe(
            TENANT, ITERATION_1, "wo_close", denied=True)
        LoopSafetyMonitor(DurableLoopSafetyStore(db_path=path)).observe(
            TENANT, ITERATION_2, "wo_close", denied=True)
        state = LoopSafetyMonitor(DurableLoopSafetyStore(db_path=path)).state(TENANT, "ctx-1")
        assert state.count(DENIED_INTENT) == 2

    def test_the_in_memory_control_does_not_share(self):
        LoopSafetyMonitor(InMemoryLoopSafetyStore()).observe(
            TENANT, ITERATION_1, "wo_close", denied=True)
        fresh = LoopSafetyMonitor(InMemoryLoopSafetyStore()).state(TENANT, "ctx-1")
        assert fresh.count(DENIED_INTENT) == 0

    def test_an_unreadable_store_refuses_and_records_nothing(self, tmp_path):
        unreadable = DurableLoopSafetyStore(db_path=str(tmp_path))  # a directory
        with pytest.raises(LoopSafetyStoreUnavailable):
            LoopSafetyMonitor(unreadable).observe(TENANT, ITERATION_1, "wo_close", denied=True)
        with pytest.raises(LoopSafetyStoreUnavailable):
            unreadable.events(tenant_id=TENANT, context_id="ctx-1")

    def test_an_unconfigured_durable_store_is_refused(self):
        with pytest.raises(ValueError, match="in-memory store wearing the durable name"):
            DurableLoopSafetyStore()

    def test_an_in_memory_sqlite_path_is_refused(self):
        with pytest.raises(ValueError):
            DurableLoopSafetyStore(db_path=":memory:")


class TestScope:
    @pytest.mark.parametrize("tenant,context", [("", "ctx-1"), ("acme", ""), (" ", "ctx-1")])
    def test_state_needs_a_tenant_and_a_context(self, store, tenant, context):
        with pytest.raises(ValueError):
            store.events(tenant_id=tenant, context_id=context)

    def test_both_stores_satisfy_the_protocol(self, store):
        assert isinstance(store, LoopSafetyStore)


class TestFold:
    def test_the_last_reset_wins(self):
        events = [
            LoopEvent(1, "t1", "a", (DENIED_INTENT,)),
            LoopEvent(2, "", "", ("reset",)),
            LoopEvent(3, "t2", "a", (DENIED_INTENT,)),
            LoopEvent(4, "", "", ("reset",)),
            LoopEvent(5, "t3", "b", (DENIED_INTENT,)),
        ]
        state = fold(TENANT, "ctx-1", events)
        assert state.count(DENIED_INTENT) == 1
        assert state.tasks == ("t3",)
        assert state.last_denied_tool == "b"

    def test_the_counts_are_read_only(self):
        state = fold(TENANT, "ctx-1", [])
        with pytest.raises(TypeError):
            state.counts[DENIED_INTENT] = 0  # type: ignore[index]
