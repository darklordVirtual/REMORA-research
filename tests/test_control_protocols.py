# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Safety properties of the AI-control VERIFY-resolution protocols (RF-04).

Covers the five in-code invariants of ``remora/governance/control_protocols.py``:
VERIFY-only scope, flag-gated status quo, earned monitored accept, loud budget
exhaustion, and the adaptive-attack (suspicion-suppression) guard — plus the
rationale-channel rule (the agent-visible message leaks nothing) and a
never-weakens property test following
``tests/policy/test_governance_intelligence_never_weakens_policy.py``.
"""
from __future__ import annotations

import itertools

import pytest

from remora.governance.control_protocols import (
    AGENT_MESSAGE_PROCEED,
    AGENT_MESSAGE_REVIEW,
    AGENT_MESSAGE_UNCHANGED,
    AGENT_MESSAGES,
    ControlProtocolConfig,
    TrustedVerdict,
    VerifyResolution,
    VerifyStrategy,
    resolve_verify,
)
from remora.policy.report import DecisionAction

_SUMMARY = {"question": "update billing config flag", "tool_call_hash": "abc"}

_NON_VERIFY = [a for a in DecisionAction if a is not DecisionAction.VERIFY]
_INTERVENTIONS = (
    VerifyStrategy.DEFER_TO_TRUSTED,
    VerifyStrategy.TRUSTED_EDIT,
    VerifyStrategy.DEFER_TO_RESAMPLE,
)


def _config(**kwargs) -> ControlProtocolConfig:
    kwargs.setdefault("strategy", VerifyStrategy.DEFER_TO_TRUSTED)
    kwargs.setdefault("audit_budget", 10)
    kwargs.setdefault("resample_k", 3)
    kwargs.setdefault("enabled", True)
    return ControlProtocolConfig(**kwargs)


def _approvals(n: int, suspicions: tuple[float, ...] | None = None):
    suspicions = suspicions or tuple(0.2 if i % 2 else 0.4 for i in range(n))
    return tuple(
        TrustedVerdict(approved=True, suspicion=s, source=f"gate_{i}")
        for i, s in enumerate(suspicions[:n])
    )


# Named verdict fixtures reused across the grid-based property test.
_VERDICT_FIXTURES: dict[str, tuple[TrustedVerdict, ...]] = {
    "empty": (),
    "unanimous_k": _approvals(3),
    "one_disapproval": _approvals(2)
    + (TrustedVerdict(approved=False, suspicion=0.9, source="gate_x"),),
    "suppression_k_plus_2": _approvals(5, (0.9, 0.7, 0.5, 0.3, 0.1)),
}


class TestPassthrough:
    """Invariant (a): the protocol acts only on VERIFY."""

    @pytest.mark.parametrize("action", _NON_VERIFY)
    @pytest.mark.parametrize("strategy", list(VerifyStrategy))
    @pytest.mark.parametrize("enabled", [True, False])
    def test_non_verify_identical_out(self, action, strategy, enabled):
        result = resolve_verify(
            action, _SUMMARY, _approvals(3),
            _config(strategy=strategy, enabled=enabled),
        )
        assert result.resolution is action
        assert result.agent_message == AGENT_MESSAGE_UNCHANGED

    def test_passthrough_ignores_verdicts(self):
        for name, verdicts in _VERDICT_FIXTURES.items():
            result = resolve_verify(
                DecisionAction.ESCALATE, _SUMMARY, verdicts, _config()
            )
            assert result.resolution is DecisionAction.ESCALATE, name


class TestDisabledFlag:
    """Invariant (b): disabled means status-quo route to review (ESCALATE)."""

    @pytest.mark.parametrize("name", sorted(_VERDICT_FIXTURES))
    @pytest.mark.parametrize("strategy", list(VerifyStrategy))
    def test_disabled_escalates_regardless_of_verdicts(self, name, strategy):
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _VERDICT_FIXTURES[name],
            _config(strategy=strategy, enabled=False),
        )
        assert result.resolution is VerifyResolution.ESCALATE
        assert result.agent_message == AGENT_MESSAGE_REVIEW
        assert result.audit_detail["reason"] == "protocols_disabled"

    def test_disabled_result_is_verdict_independent(self):
        results = [
            resolve_verify(
                DecisionAction.VERIFY, _SUMMARY, verdicts,
                _config(enabled=False),
            )
            for verdicts in _VERDICT_FIXTURES.values()
        ]
        assert all(r == results[0] for r in results)

    def test_seek_evidence_is_status_quo_even_when_enabled(self):
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _approvals(3),
            _config(strategy=VerifyStrategy.SEEK_EVIDENCE, enabled=True),
        )
        assert result.resolution is VerifyResolution.ESCALATE

    def test_enabled_defaults_from_env_flag(self, monkeypatch):
        monkeypatch.delenv("REMORA_CONTROL_PROTOCOLS", raising=False)
        assert ControlProtocolConfig().enabled is False
        for raw in ("1", "true", "yes", " TRUE "):
            monkeypatch.setenv("REMORA_CONTROL_PROTOCOLS", raw)
            assert ControlProtocolConfig().enabled is True, raw
        monkeypatch.setenv("REMORA_CONTROL_PROTOCOLS", "0")
        assert ControlProtocolConfig().enabled is False


class TestMonitoredAccept:
    """Invariants (c) and (d): MONITORED_ACCEPT is earned, budget is loud."""

    @pytest.mark.parametrize("strategy", _INTERVENTIONS)
    def test_unanimous_approval_within_budget_accepts(self, strategy):
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _approvals(3),
            _config(strategy=strategy),
        )
        assert result.resolution is VerifyResolution.MONITORED_ACCEPT
        assert result.agent_message == AGENT_MESSAGE_PROCEED

    def test_single_disapproval_escalates(self):
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY,
            _VERDICT_FIXTURES["one_disapproval"], _config(),
        )
        assert result.resolution is VerifyResolution.ESCALATE
        assert result.audit_detail["reason"] == "verdict_disapproval"

    def test_empty_verdicts_escalate(self):
        result = resolve_verify(DecisionAction.VERIFY, _SUMMARY, (), _config())
        assert result.resolution is VerifyResolution.ESCALATE
        assert result.audit_detail["reason"] == "no_trusted_verdicts"

    def test_k_minus_1_resamples_escalate(self):
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _approvals(2),
            _config(strategy=VerifyStrategy.DEFER_TO_RESAMPLE, resample_k=3),
        )
        assert result.resolution is VerifyResolution.ESCALATE
        assert result.audit_detail["reason"] == "insufficient_resamples"

    def test_budget_exhaustion_escalates_never_silent(self):
        config = _config(audit_budget=1)
        first = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _approvals(3), config
        )
        assert first.resolution is VerifyResolution.MONITORED_ACCEPT
        assert config.audit_spent == 1
        second = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _approvals(3), config
        )
        assert second.resolution is VerifyResolution.ESCALATE
        assert second.audit_detail["reason"] == "audit_budget_exhausted"
        assert second.audit_detail["budget"]["remaining"] == 0

    def test_accept_spends_budget_and_records_state(self):
        config = _config(audit_budget=5)
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _approvals(3), config
        )
        assert config.audit_spent == 1
        assert result.audit_detail["budget"]["audit_spent"] == 1


class TestAdaptiveAttackGuard:
    """Invariant (e): the suspiciousness-suppression pattern escalates."""

    def test_k_plus_2_decreasing_suspicion_escalates(self):
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY,
            _VERDICT_FIXTURES["suppression_k_plus_2"],
            _config(strategy=VerifyStrategy.DEFER_TO_RESAMPLE, resample_k=3),
        )
        assert result.resolution is VerifyResolution.ESCALATE
        assert result.audit_detail["reason"] == "suspicion_suppression_guard"
        assert result.audit_detail["adaptive_guard_triggered"] is True

    def test_non_monotonic_k_plus_2_accepts(self):
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY,
            _approvals(5, (0.2, 0.4, 0.1, 0.3, 0.2)),
            _config(strategy=VerifyStrategy.DEFER_TO_RESAMPLE, resample_k=3),
        )
        assert result.resolution is VerifyResolution.MONITORED_ACCEPT

    def test_exactly_k_decreasing_is_within_quorum(self):
        # The guard requires a sequence SPANNING MORE than resample_k; exactly
        # k verdicts is the ordinary resample quorum.
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY,
            _approvals(3, (0.5, 0.3, 0.1)),
            _config(strategy=VerifyStrategy.DEFER_TO_RESAMPLE, resample_k=3),
        )
        assert result.resolution is VerifyResolution.MONITORED_ACCEPT

    def test_guard_is_resample_specific(self):
        # DEFER_TO_TRUSTED has no resample sequence to suppress.
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY,
            _VERDICT_FIXTURES["suppression_k_plus_2"],
            _config(strategy=VerifyStrategy.DEFER_TO_TRUSTED),
        )
        assert result.resolution is VerifyResolution.MONITORED_ACCEPT


class TestRationaleLeak:
    """The agent channel is a fixed neutral sentence — no monitor scores, no
    rule identifiers, no strategy names, no budget state (arXiv:2510.09462,
    arXiv:2605.26047)."""

    _FORBIDDEN = (
        ["suspicion", "score", "monitor", "budget", "resample", "verdict",
         "strategy", "rule", "guard", "quorum", "threshold"]
        + [s.value for s in VerifyStrategy]
        + [s.value.replace("_", " ") for s in VerifyStrategy]
    )

    def _results_for_every_code_path(self):
        return {
            "approve": resolve_verify(
                DecisionAction.VERIFY, _SUMMARY, _approvals(3), _config()
            ),
            "deny": resolve_verify(
                DecisionAction.VERIFY, _SUMMARY,
                _VERDICT_FIXTURES["one_disapproval"], _config(),
            ),
            "budget_exhausted": resolve_verify(
                DecisionAction.VERIFY, _SUMMARY, _approvals(3),
                _config(audit_budget=0),
            ),
            "attack_guard": resolve_verify(
                DecisionAction.VERIFY, _SUMMARY,
                _VERDICT_FIXTURES["suppression_k_plus_2"],
                _config(strategy=VerifyStrategy.DEFER_TO_RESAMPLE),
            ),
            "disabled": resolve_verify(
                DecisionAction.VERIFY, _SUMMARY, (), _config(enabled=False)
            ),
            "status_quo": resolve_verify(
                DecisionAction.VERIFY, _SUMMARY, (),
                _config(strategy=VerifyStrategy.SEEK_EVIDENCE),
            ),
            "passthrough": resolve_verify(
                DecisionAction.ESCALATE, _SUMMARY, (), _config()
            ),
        }

    def test_agent_message_leaks_nothing(self):
        for path, result in self._results_for_every_code_path().items():
            message = result.agent_message
            assert message in AGENT_MESSAGES, path
            assert not any(ch.isdigit() for ch in message), path
            lowered = message.lower()
            for token in self._FORBIDDEN:
                assert token not in lowered, (path, token)

    def test_all_escalate_paths_share_one_sentence(self):
        # Indistinguishability: the agent cannot tell a disapproval from an
        # exhausted budget from the adaptive-attack guard.
        results = self._results_for_every_code_path()
        for path in ("deny", "budget_exhausted", "attack_guard", "disabled",
                     "status_quo"):
            assert results[path].agent_message == AGENT_MESSAGE_REVIEW, path

    def test_internal_channel_still_carries_the_audit_record(self):
        # Channel separation, not opacity: the audit side keeps everything.
        result = resolve_verify(
            DecisionAction.VERIFY, _SUMMARY, _approvals(3),
            _config(audit_budget=0),
        )
        assert result.audit_detail["reason"] == "audit_budget_exhausted"
        assert result.audit_detail["strategy"] == "defer_to_trusted"
        assert result.audit_detail["verdicts"]["total"] == 3


class TestNeverWeakensProperty:
    """Property (stated precisely): over a deterministic grid of inputs,

    1. the protocol NEVER changes a non-VERIFY decision — the input action
       comes back as the resolution for every strategy × enabled × verdict
       combination;
    2. the protocol NEVER emits plain ACCEPT — the least severe VERIFY
       resolution is MONITORED_ACCEPT (execution under audit);
    3. with ``enabled=False`` the result is bit-identical to the status quo:
       ESCALATE-to-review, one fixed agent sentence, and no dependence on the
       verdicts whatsoever.

    Deliberately NOT claimed: that every resolution is at least as severe as
    the status quo — MONITORED_ACCEPT is by design less severe than ESCALATE
    for benign VERIFYs; that utility trade is the point of RF-04 and is only
    ever taken inside the invariants above.
    """

    def _grid(self):
        for action, strategy, enabled, name in itertools.product(
            list(DecisionAction), list(VerifyStrategy), (True, False),
            sorted(_VERDICT_FIXTURES),
        ):
            yield action, strategy, enabled, _VERDICT_FIXTURES[name]

    def test_non_verify_decisions_never_change(self):
        changed = []
        for action, strategy, enabled, verdicts in self._grid():
            if action is DecisionAction.VERIFY:
                continue
            result = resolve_verify(
                action, _SUMMARY, verdicts,
                _config(strategy=strategy, enabled=enabled),
            )
            if result.resolution is not action:
                changed.append((action, strategy, enabled, result.resolution))
        assert not changed, f"protocol changed {len(changed)}: {changed[:5]}"

    def test_never_emits_plain_accept(self):
        assert "accept" not in {r.value for r in VerifyResolution}
        for action, strategy, enabled, verdicts in self._grid():
            if action is not DecisionAction.VERIFY:
                continue
            result = resolve_verify(
                action, _SUMMARY, verdicts,
                _config(strategy=strategy, enabled=enabled),
            )
            assert result.resolution is not DecisionAction.ACCEPT
            assert result.resolution.value != DecisionAction.ACCEPT.value
            assert isinstance(result.resolution, VerifyResolution)

    def test_disabled_is_bit_identical_to_status_quo(self):
        for strategy in VerifyStrategy:
            baseline = resolve_verify(
                DecisionAction.VERIFY, _SUMMARY, (),
                _config(strategy=strategy, enabled=False),
            )
            assert baseline.resolution is VerifyResolution.ESCALATE
            assert baseline.agent_message == AGENT_MESSAGE_REVIEW
            for verdicts in _VERDICT_FIXTURES.values():
                result = resolve_verify(
                    DecisionAction.VERIFY, _SUMMARY, verdicts,
                    _config(strategy=strategy, enabled=False),
                )
                assert result == baseline


class TestContractValidation:
    """Constructor contracts fail loudly, mirroring the review queue."""

    def test_suspicion_out_of_range_raises(self):
        with pytest.raises(ValueError, match="suspicion"):
            TrustedVerdict(approved=True, suspicion=1.2, source="gate_0")
        with pytest.raises(ValueError, match="suspicion"):
            TrustedVerdict(approved=True, suspicion=-0.1, source="gate_0")

    def test_negative_audit_budget_raises(self):
        with pytest.raises(ValueError, match="audit_budget"):
            _config(audit_budget=-1)

    def test_resample_k_below_one_raises(self):
        with pytest.raises(ValueError, match="resample_k"):
            _config(resample_k=0)

    def test_negative_audit_spent_raises(self):
        with pytest.raises(ValueError, match="audit_spent"):
            _config(audit_spent=-1)
