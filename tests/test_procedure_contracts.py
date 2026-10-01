# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Procedure obligations online and in replay; completion derived (quality program Q7.7).

The acceptance criterion: a small finite-state obligation contract runs
online and in replay, and completion is derived from satisfied obligations
and can return NOT_ESTABLISHED. The property that makes "online and in
replay" one thing rather than two is pinned by
``TestOnlineAndReplayAgree``: stepping a trace live and replaying it give
identical verdicts, on every prefix.
"""
from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.governance.procedure import (
    CompletionStatus,
    ProcedureContract,
    ProcedureMonitor,
    Step,
    StepPattern,
    absence,
    derive_completion,
    existence,
    precedence,
    replay,
    response,
)

MAINTENANCE = ProcedureContract("maintenance_v1", (
    precedence("backup_asset", "delete_asset"),
    absence("write_config", after="close_change_window"),
    response("close_work_order", "file_report"),
    existence("close_work_order"),
))


def _trace(*tools: str) -> list[Step]:
    return [Step(tool) for tool in tools]


class TestObligations:
    def test_precedence_is_violated_at_the_offending_step(self):
        monitor = replay(MAINTENANCE, _trace("delete_asset"))
        assert monitor.violations == ((0, "precedence(backup_asset, delete_asset)"),)

    def test_precedence_is_met_when_the_first_step_came_earlier(self):
        assert replay(MAINTENANCE, _trace("backup_asset", "delete_asset")).violations == ()

    def test_absence_applies_only_after_its_trigger(self):
        assert replay(MAINTENANCE, _trace("write_config")).violations == ()
        monitor = replay(MAINTENANCE, _trace("close_change_window", "write_config"))
        assert monitor.violations == ((1, "absence(write_config, close_change_window)"),)

    def test_an_unconditional_absence_is_violated_anywhere(self):
        contract = ProcedureContract("c", (absence("drop_database"),))
        assert replay(contract, _trace("drop_database")).violations

    def test_response_is_pending_until_discharged(self):
        monitor = replay(MAINTENANCE, _trace("close_work_order"))
        assert "response(close_work_order, file_report)" in monitor.pending()
        monitor.step(Step("file_report"))
        assert "response(close_work_order, file_report)" not in monitor.pending()

    def test_a_second_trigger_reopens_a_discharged_response(self):
        monitor = replay(MAINTENANCE, _trace("close_work_order", "file_report",
                                             "close_work_order"))
        assert "response(close_work_order, file_report)" in monitor.pending()

    def test_argument_patterns_narrow_a_step(self):
        contract = ProcedureContract("c", (
            precedence(StepPattern("backup_asset", {"asset": "P-1"}),
                       StepPattern("delete_asset", {"asset": "P-1"})),))
        wrong_backup = [Step("backup_asset", {"asset": "P-2"}), Step("delete_asset", {"asset": "P-1"})]
        assert replay(contract, wrong_backup).violations
        right = [Step("backup_asset", {"asset": "P-1"}), Step("delete_asset", {"asset": "P-1"})]
        assert replay(contract, right).violations == ()


class TestCompletion:
    def test_everything_satisfied_is_established(self):
        verdict = derive_completion(MAINTENANCE, _trace("close_work_order", "file_report"))
        assert verdict.status is CompletionStatus.ESTABLISHED

    def test_a_pending_obligation_is_not_established(self):
        verdict = derive_completion(MAINTENANCE, _trace("close_work_order"))
        assert verdict.status is CompletionStatus.NOT_ESTABLISHED
        assert verdict.pending == ("response(close_work_order, file_report)",)

    def test_an_empty_trace_is_not_established(self):
        assert derive_completion(MAINTENANCE, []).status is CompletionStatus.NOT_ESTABLISHED

    def test_a_violation_is_violated_even_if_everything_else_was_met(self):
        verdict = derive_completion(MAINTENANCE, _trace(
            "delete_asset", "close_work_order", "file_report"))
        assert verdict.status is CompletionStatus.VIOLATED

    @pytest.mark.parametrize("trace,overclaim", [
        (("close_work_order", "file_report"), False),
        (("close_work_order",), True),
        (("delete_asset", "close_work_order", "file_report"), True),
    ])
    def test_a_completion_claim_the_trace_does_not_establish_is_an_overclaim(self, trace, overclaim):
        verdict = derive_completion(MAINTENANCE, _trace(*trace), claimed_complete=True)
        assert verdict.overclaim is overclaim

    def test_no_claim_is_no_overclaim(self):
        assert derive_completion(MAINTENANCE, _trace("close_work_order")).overclaim is None


TOOLS = ["backup_asset", "delete_asset", "close_change_window", "write_config",
         "close_work_order", "file_report"]


class TestOnlineAndReplayAgree:
    """Exhaustive over every trace of length 4 from six tools (1296 traces)."""

    def test_stepping_live_matches_replaying_every_prefix(self):
        for trace in itertools.product(TOOLS, repeat=4):
            live = ProcedureMonitor(MAINTENANCE)
            for n, tool in enumerate(trace, start=1):
                live.step(Step(tool))
                replayed = replay(MAINTENANCE, _trace(*trace[:n]))
                assert (live.violations, live.pending()) == (
                    replayed.violations, replayed.pending()), trace[:n]

    def test_admits_predicts_exactly_the_safety_violations_step_records(self):
        for trace in itertools.product(TOOLS, repeat=3):
            monitor = replay(MAINTENANCE, _trace(*trace[:-1]))
            predicted = monitor.admits(Step(trace[-1]))
            recorded = monitor.step(Step(trace[-1]))
            assert set(predicted) == {v for v in recorded
                                      if v.startswith(("precedence", "absence"))}, trace


class TestTheDispatcherRefusesOnline:
    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "procedure-key")
        for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                     "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
            monkeypatch.delenv(name, raising=False)

    def _run(self, tool, history):
        lease = ExecutionLease.issue(
            decision="accept", tenant_id="acme", actor_identity="agent-1", tool_name=tool,
            arguments={}, target_environment="prod", policy_bundle_hash="b1",
            issued_at=datetime.now(UTC).isoformat())
        calls: list = []
        dispatcher = GovernedToolDispatcher("b1")
        dispatcher.register(tool, lambda args: calls.append(tool) or "ok")
        dispatcher.bind_procedure(MAINTENANCE, history)
        result = dispatcher.dispatch(lease, tool, {}, tenant_id="acme",
                                     target_environment="prod", actor_identity="agent-1")
        return result, calls

    def test_a_step_that_would_violate_is_refused_before_it_runs(self):
        result, calls = self._run("delete_asset", lambda lease: [])
        assert (result.executed, result.refusal_reason) == (False, "procedure_violation")
        assert calls == []

    def test_the_same_step_after_its_precondition_runs(self):
        result, calls = self._run("delete_asset", lambda lease: [Step("backup_asset")])
        assert result.executed and calls == ["delete_asset"]

    def test_a_pending_liveness_obligation_never_blocks(self):
        result, _ = self._run("write_config", lambda lease: [Step("close_work_order")])
        assert result.executed

    def test_an_unreadable_history_refuses(self):
        def broken(lease):
            raise ConnectionError("trace store down")

        assert self._run("file_report", broken)[0].refusal_reason == "procedure_trace_unavailable"
