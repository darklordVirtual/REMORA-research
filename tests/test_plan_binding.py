# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A write refuses when the state its plan depended on moved (quality program Q7.5).

The acceptance criterion has two halves and both are pinned: a relevant
revision that moved refuses, and an irrelevant one that moved is ignored.
Validating against everything would refuse far more than it should, and a
control that refuses correct work gets turned off.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.governance.plan_binding import PlanBinding, revalidate

BUNDLE = "b1"
ARGS = {"id": "WO-1", "status": "closed"}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "plan-binding-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


class State:
    """A revisioned store the plan reads from."""

    def __init__(self):
        self.revisions = {"workorder/WO-1": "7", "asset/P-1": "3", "calendar/today": "12"}
        self.down: set[str] = set()

    def __call__(self, resource: str) -> str:
        if resource in self.down:
            raise ConnectionError(resource)
        return self.revisions[resource]


def _plan(state) -> PlanBinding:
    """Read three things, depend on two of them."""
    return PlanBinding.capture(
        "plan-1", ["workorder/WO-1", "asset/P-1", "calendar/today"],
        ["workorder/WO-1", "asset/P-1"], state)


def _lease(plan: PlanBinding | None) -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name="wo_close", arguments=ARGS, target_environment="prod",
        policy_bundle_hash=BUNDLE, issued_at=datetime.now(UTC).isoformat(), plan=plan)


def _dispatch(lease, plan, state):
    calls: list = []
    dispatcher = GovernedToolDispatcher(BUNDLE)
    dispatcher.register("wo_close", lambda args: calls.append(args) or "ok")
    if state is not None:
        dispatcher.bind_state_revisions(state)
    result = dispatcher.dispatch(lease, "wo_close", ARGS, tenant_id="acme",
                                 target_environment="prod", actor_identity="agent-1",
                                 plan=plan)
    return result, calls


class TestRelevantAndIrrelevant:
    def test_unchanged_premises_execute(self):
        state = State()
        plan = _plan(state)
        result, calls = _dispatch(_lease(plan), plan, state)
        assert result.executed and calls == [ARGS]

    @pytest.mark.parametrize("resource", ["workorder/WO-1", "asset/P-1"])
    def test_a_moved_dependency_refuses_and_nothing_runs(self, resource):
        state = State()
        plan = _plan(state)
        state.revisions[resource] = "99"
        result, calls = _dispatch(_lease(plan), plan, state)
        assert (result.executed, result.refusal_reason) == (False, "stale_plan")
        assert calls == []

    def test_a_moved_read_the_write_does_not_depend_on_is_ignored(self):
        state = State()
        plan = _plan(state)
        state.revisions["calendar/today"] = "13"
        result, _ = _dispatch(_lease(plan), plan, state)
        assert result.executed

    def test_revalidate_reports_both_kinds_of_movement(self):
        state = State()
        plan = _plan(state)
        state.revisions.update({"asset/P-1": "4", "calendar/today": "13"})
        check = revalidate(plan, state)
        assert check.moved_dependencies == ("asset/P-1",)
        assert check.moved_other_reads == ("calendar/today",)


class TestFailClosed:
    def test_an_unreadable_dependency_refuses(self):
        state = State()
        plan = _plan(state)
        state.down.add("workorder/WO-1")
        assert _dispatch(_lease(plan), plan, state)[0].refusal_reason == "plan_state_unverifiable"

    def test_an_unreadable_irrelevant_read_does_not(self):
        state = State()
        plan = _plan(state)
        state.down.add("calendar/today")
        assert _dispatch(_lease(plan), plan, state)[0].executed

    def test_a_plan_bound_lease_without_its_plan_refuses(self):
        state = State()
        assert _dispatch(_lease(_plan(state)), None, state)[0].refusal_reason == (
            "plan_binding_required")

    def test_a_different_plan_refuses(self):
        state = State()
        signed = _plan(state)
        other = PlanBinding("plan-1", signed.reads, ("workorder/WO-1",))  # drops a dependency
        assert _dispatch(_lease(signed), other, state)[0].refusal_reason == "plan_binding_mismatch"

    def test_a_process_that_cannot_read_state_refuses_a_plan_bound_lease(self):
        state = State()
        plan = _plan(state)
        assert _dispatch(_lease(plan), plan, None)[0].refusal_reason == "plan_state_unverifiable"

    def test_a_refusal_does_not_burn_the_nonce(self):
        state = State()
        plan = _plan(state)
        lease = _lease(plan)
        dispatcher = GovernedToolDispatcher(BUNDLE)
        dispatcher.register("wo_close", lambda args: "ok")
        dispatcher.bind_state_revisions(state)
        kwargs = dict(tenant_id="acme", target_environment="prod",
                      actor_identity="agent-1", plan=plan)
        state.revisions["workorder/WO-1"] = "8"
        assert not dispatcher.dispatch(lease, "wo_close", ARGS, **kwargs).executed
        state.revisions["workorder/WO-1"] = "7"
        assert dispatcher.dispatch(lease, "wo_close", ARGS, **kwargs).executed


class TestUnchangedWithoutAPlan:
    def test_a_lease_without_a_plan_is_not_checked(self):
        result, _ = _dispatch(_lease(None), None, State())
        assert result.executed

    def test_an_unbound_lease_signs_no_plan(self):
        assert "plan_binding_hash" not in _lease(None)._signed_fields()


class TestTheBinding:
    def test_a_dependency_the_plan_did_not_read_is_refused_at_construction(self):
        with pytest.raises(ValueError, match="did not read"):
            PlanBinding("p", (("a", "1"),), ("b",))

    def test_a_resource_recorded_twice_is_refused(self):
        with pytest.raises(ValueError, match="once"):
            PlanBinding("p", (("a", "1"), ("a", "2")), ())

    def test_the_digest_is_order_independent_through_from_dict(self):
        one = PlanBinding.from_dict({"plan_id": "p", "reads": {"a": "1", "b": "2"},
                                     "depends_on": ["b", "a"]})
        two = PlanBinding.from_dict({"plan_id": "p", "reads": {"b": "2", "a": "1"},
                                     "depends_on": ["a", "b"]})
        assert one.digest() == two.digest()

    def test_the_digest_is_frozen(self):
        plan = PlanBinding("p", (("a", "1"),), ("a",))
        import hashlib

        canonical = '{"depends_on":["a"],"plan_id":"p","reads":[["a","1"]]}'
        assert plan.digest() == hashlib.sha256(canonical.encode()).hexdigest()
