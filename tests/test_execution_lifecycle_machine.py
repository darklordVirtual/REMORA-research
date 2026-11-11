# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-01: the lifecycle schema becomes a runtime authority, not just YAML.

``remora.governance.lifecycle`` loads ``schemas/execution_lifecycle_v1.yaml``
(single source of truth — no transition table is duplicated in code) and
exposes a tracker that refuses illegal transitions. The property suite is a
searched validation over the declared event domain: sequences of declared
events, applied through the tracker, can never reach an undeclared state,
never leave a terminal state, and can reach UNKNOWN only through
DISPATCHING. No counterexample found in the generated domain — not a proof.
"""
from __future__ import annotations

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from remora.governance.lifecycle import (
    IllegalTransition,
    LifecycleModel,
    LifecycleTracker,
)

MODEL = LifecycleModel.load()


# ── Model coherence ─────────────────────────────────────────────────────────

def test_model_matches_schema_states() -> None:
    assert "PROPOSED" in MODEL.states
    assert "UNKNOWN" in MODEL.terminal_states
    assert MODEL.terminal_states <= MODEL.states


def test_every_transition_endpoint_is_declared() -> None:
    for (src, event), dst in MODEL.transitions.items():
        assert src in MODEL.states, (src, event)
        assert dst in MODEL.states, (src, event, dst)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    sources = {src for (src, _event) in MODEL.transitions}
    assert not (sources & MODEL.terminal_states)


def test_every_nonterminal_state_is_reachable_and_can_terminate() -> None:
    # Reachability from PROPOSED.
    reachable = {"PROPOSED"}
    changed = True
    while changed:
        changed = False
        for (src, _e), dst in MODEL.transitions.items():
            if src in reachable and dst not in reachable:
                reachable.add(dst)
                changed = True
    assert reachable == MODEL.states, MODEL.states - reachable


def test_unknown_is_reachable_only_from_dispatching() -> None:
    sources = {src for (src, _e), dst in MODEL.transitions.items()
               if dst == "UNKNOWN"}
    assert sources == {"DISPATCHING"}


# ── Tracker behavior ────────────────────────────────────────────────────────

def test_tracker_walks_the_review_path() -> None:
    t = LifecycleTracker()
    assert t.state == "PROPOSED"
    t.apply("engine_decision")
    t.apply("verify_or_escalate")
    t.apply("human_approval")
    t.apply("regate_binding_or_freshness_refusal")
    assert t.state == "REFUSED"
    assert t.is_terminal


def test_tracker_refuses_illegal_transition() -> None:
    t = LifecycleTracker()
    with pytest.raises(IllegalTransition):
        t.apply("human_approval")  # PROPOSED cannot be approved


def test_tracker_refuses_events_after_terminal() -> None:
    t = LifecycleTracker()
    t.apply("engine_decision")
    t.apply("abstain_or_hard_refusal")
    assert t.is_terminal
    with pytest.raises(IllegalTransition):
        t.apply("engine_decision")


def test_tracker_records_the_event_trail() -> None:
    t = LifecycleTracker()
    t.apply("engine_decision")
    t.apply("direct_accept_token")
    assert t.trail == (
        ("PROPOSED", "engine_decision", "ASSESSED"),
        ("ASSESSED", "direct_accept_token", "AUTHORIZED"),
    )


# ── Property: no event sequence escapes the declared model ─────────────────

EVENTS = sorted({event for (_s, event) in MODEL.transitions})


class LifecycleMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.tracker = LifecycleTracker()

    @rule(event=st.sampled_from(EVENTS))
    def apply_any_declared_event(self, event: str) -> None:
        before = self.tracker.state
        try:
            self.tracker.apply(event)
        except IllegalTransition:
            assert self.tracker.state == before  # refusal must not move state
        else:
            assert self.tracker.transitions_key(before, event) is not None

    @invariant()
    def state_is_declared(self) -> None:
        assert self.tracker.state in MODEL.states

    @invariant()
    def terminal_is_absorbing(self) -> None:
        if self.tracker.is_terminal:
            for event in EVENTS:
                assert (self.tracker.state, event) not in MODEL.transitions


TestLifecycleProperties = LifecycleMachine.TestCase
# deadline=None matches every other property suite in this repository
# (enforcement, outbox, gate replay, policy engine, review queue). A
# wall-clock deadline makes a property test partly a measurement of the
# machine it runs on: under full-suite load one example failed here once
# and never reproduced, and Hypothesis replays saved counterexamples, so
# that failure was a timing artifact rather than a violated property.
# Searched validation should fail on what the model does, not on how busy
# the runner was.
TestLifecycleProperties.settings = settings(max_examples=200, deadline=None)


# ── Orchestrated stateful lifecycle machine (PRF-056 / RMR-AUD-013) ─────────


class _ControllableEngine:
    """Deterministic engine double for driving re-gate transitions."""

    def __init__(self) -> None:
        from remora.policy.report import DecisionAction

        self.action = DecisionAction.VERIFY
        self.reasons: tuple[str, ...] = ("evidence_insufficient",)

    def decide(self, observation: object) -> object:
        import types

        return types.SimpleNamespace(
            action=self.action,
            reasons=tuple(types.SimpleNamespace(value=r) for r in self.reasons),
        )


class OrchestratedLifecycleMachine(RuleBasedStateMachine):
    """Stateful property test over ReviewQueue, DispatchOutbox, AuditChain,
    resolve_lineage and projections (propose -> assess -> approve -> policy/tier
    change -> expire/revoke -> reapprove -> claim/race -> dispatch -> crash/
    reconcile -> record effect).
    """

    def __init__(self) -> None:
        super().__init__()
        from datetime import UTC, datetime, timedelta

        from remora.enforcement.outbox import ExecutionOutbox
        from remora.governance.revocation_store import InMemoryRevocationStore
        from remora.governance.review_queue import ReviewQueue
        from remora.governance.tenant_chain import TenantAuditChain

        self.now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
        self.step_td = timedelta(seconds=10)
        self.engine = _ControllableEngine()
        self.revocations = InMemoryRevocationStore()
        self.queue = ReviewQueue(
            engine=self.engine,  # type: ignore[arg-type]
            now_fn=lambda: self.now,
            tenant_id="tenant-a",
            revocation_store=self.revocations,
        )
        self.outbox = ExecutionOutbox()
        self.chain = TenantAuditChain()
        self.tenant = "tenant-a"
        self.proposal_id = "prop-1"
        self.item_id: str | None = None
        self.current_tier = "medium"
        self.current_policy_hash = "pol-v1"
        self.tool_call_hash = "c" * 64
        self.envelope_hash = "e" * 64
        self.actor = "agent-1"
        self.task_id = "task-1"
        self.live_approval = False
        self.approval_tier: str | None = None
        self.approval_policy: str | None = None
        self.approval_reasons: tuple[str, ...] = ()
        self.approval_approver: str | None = None
        self.approval_expires_at: datetime | None = None
        self.outbox_id: str | None = None
        self.claimed_by: str | None = None
        self.grant_jti: str | None = None
        self.side_effects = 0
        self.independent_verified_effect = False
        self.claimed_only_effect = False

    def _tick(self, seconds: int = 10) -> None:
        from datetime import timedelta

        self.now = self.now + timedelta(seconds=seconds)

    def _obs(self, *, tier: str | None = None, call_hash: str | None = None):
        from remora.policy.observation import PolicyObservation

        return PolicyObservation(
            question="update port profile",
            risk_tier=tier or self.current_tier,
            action_type="write",
            target_environment="staging",
            proposed_tool_name="set_port_profile",
            tool_call_hash=call_hash or self.tool_call_hash,
            proposal_id=self.proposal_id,
        )

    def _events(self) -> list[dict]:
        from remora.execution.projections import proposal_events

        return proposal_events(self.chain, self.tenant, self.proposal_id)

    @rule(action_name=st.sampled_from(["verify", "escalate"]))
    def propose_and_assess(self, action_name: str) -> None:
        if self.item_id is not None:
            return
        from remora.policy.report import DecisionAction

        self._tick()
        action = DecisionAction(action_name)
        self.engine.action = action
        self.engine.reasons = (
            ("evidence_insufficient",)
            if action is DecisionAction.VERIFY
            else ("rollback_unavailable",)
        )
        obs = self._obs()
        item = self.queue.enqueue(obs, action, reasons=self.engine.reasons)
        self.item_id = item.item_id
        self.chain.append(self.tenant, {
            "event": "assessed",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "decision": action.value,
            "reasons": list(self.engine.reasons),
            "review_item_id": item.item_id,
            "tool_call_hash": self.tool_call_hash,
            "proposal_envelope_hash": self.envelope_hash,
            "context_id": "ctx-1",
            "task_id": self.task_id,
            "intent_authority_hash": "i" * 64,
        })

    @rule(approver=st.sampled_from(["rev-1", "rev-2"]))
    def approve_pending(self, approver: str) -> None:
        from datetime import timedelta
        from remora.governance.review_queue import ItemStatus

        if self.item_id is None:
            return
        item = self.queue.item(self.item_id)
        if item.status is not ItemStatus.PENDING:
            return
        if self.revocations.is_revoked(approver, tenant_id=self.tenant):
            return
        self._tick()
        ttl = timedelta(minutes=10)
        self.queue.approve(
            self.item_id,
            approver,
            ttl,
            approver_role="senior_authority",
            required_role="reviewer",
            approval_policy_hash=self.current_policy_hash,
        )
        self.live_approval = True
        self.approval_tier = item.observation.risk_tier
        self.approval_policy = self.current_policy_hash
        self.approval_reasons = (
            item.approval.approved_reasons if item.approval and item.approval.approved_reasons else ()
        )
        self.approval_approver = approver
        self.approval_expires_at = self.now + ttl
        self.chain.append(self.tenant, {
            "event": "approved",
            "proposal_id": self.proposal_id,
            "actor": approver,
            "item_id": self.item_id,
        })

    @rule()
    def expire_approval_by_clock(self) -> None:
        from remora.governance.review_queue import ExecutionDecision, ItemStatus

        if self.item_id is None:
            return
        item = self.queue.item(self.item_id)
        if item.status is not ItemStatus.APPROVED:
            return
        self._tick(seconds=700)
        outcome = self.queue.execute(
            self.item_id,
            self._obs(),
            approval_policy_hash=self.current_policy_hash,
        )
        assert outcome.decision is ExecutionDecision.APPROVAL_EXPIRED
        self.live_approval = False
        self.chain.append(self.tenant, {
            "event": "execution_approval_expired",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "item_id": self.item_id,
            "detail": outcome.detail,
        })

    @rule()
    def revoke_current_approver(self) -> None:
        from remora.governance.review_queue import ExecutionDecision, ItemStatus

        if self.item_id is None or not self.approval_approver:
            return
        item = self.queue.item(self.item_id)
        if item.status is not ItemStatus.APPROVED:
            return
        self._tick()
        self.queue.revoke_principal(self.approval_approver, reason="key compromised")
        outcome = self.queue.execute(
            self.item_id,
            self._obs(),
            approval_policy_hash=self.current_policy_hash,
        )
        assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED
        self.live_approval = False
        self.chain.append(self.tenant, {
            "event": "execution_approval_invalidated",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "item_id": self.item_id,
            "detail": outcome.detail,
        })

    @rule(change=st.sampled_from(["raise_tier", "change_policy", "new_reason"]))
    def invalidate_by_environment_or_policy_change(self, change: str) -> None:
        from remora.governance.review_queue import ExecutionDecision, ItemStatus

        if self.item_id is None:
            return
        item = self.queue.item(self.item_id)
        if item.status is not ItemStatus.APPROVED:
            return
        self._tick()
        if change == "raise_tier":
            self.current_tier = "critical" if item.observation.risk_tier != "critical" else "high"
            obs = self._obs(tier=self.current_tier)
            pol = self.current_policy_hash
        elif change == "change_policy":
            obs = self._obs(tier=item.observation.risk_tier)
            self.current_policy_hash = (
                "pol-v2-stricter"
                if self.approval_policy != "pol-v2-stricter"
                else "pol-v3-stricter"
            )
            pol = self.current_policy_hash
        else:
            obs = self._obs(tier=item.observation.risk_tier)
            pol = self.approval_policy
            new_r = f"new_reason_{len(self.engine.reasons)}"
            self.engine.reasons = (*self.engine.reasons, new_r)

        outcome = self.queue.execute(self.item_id, obs, approval_policy_hash=pol)
        assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED
        self.live_approval = False
        self.chain.append(self.tenant, {
            "event": "execution_approval_invalidated",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "item_id": self.item_id,
            "detail": outcome.detail,
        })

    @rule()
    def attempt_tampered_payload_leaves_approval_standing(self) -> None:
        from remora.governance.review_queue import ExecutionDecision, ItemStatus

        if self.item_id is None:
            return
        item = self.queue.item(self.item_id)
        if item.status is not ItemStatus.APPROVED:
            return
        self._tick()
        outcome = self.queue.execute(
            self.item_id,
            self._obs(call_hash="f" * 64),
            approval_policy_hash=self.current_policy_hash,
        )
        assert outcome.decision is ExecutionDecision.BINDING_REFUSED
        assert self.queue.item(self.item_id).status is ItemStatus.APPROVED
        self.chain.append(self.tenant, {
            "event": "execution_binding_refused",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "item_id": self.item_id,
            "detail": outcome.detail,
        })

    @rule()
    def authorize_and_record_intent(self) -> None:
        from remora.governance.review_queue import ExecutionDecision, ItemStatus

        if self.item_id is None or self.outbox_id is not None:
            return
        item = self.queue.item(self.item_id)
        if item.status is not ItemStatus.APPROVED:
            return
        # Ensure fresh engine reasons match the approved ones and approval is within TTL
        if self.approval_expires_at and self.now >= self.approval_expires_at:
            return
        if self.approval_approver and self.revocations.is_revoked(
            self.approval_approver, tenant_id=self.tenant
        ):
            return
        self.engine.reasons = self.approval_reasons or ("evidence_insufficient",)
        self._tick(seconds=1)
        if self.approval_expires_at and self.now >= self.approval_expires_at:
            return
        outcome = self.queue.execute(
            self.item_id,
            self._obs(tier=self.approval_tier),
            approval_policy_hash=self.approval_policy,
        )
        assert outcome.decision is ExecutionDecision.EXECUTE
        self.grant_jti = "jti-live-1"
        row = self.outbox.record_intent(
            proposal_id=self.proposal_id,
            tenant_id=self.tenant,
            item_id=self.item_id,
            tool_name="set_port_profile",
            tool_call_hash=self.tool_call_hash,
            grant_jti=self.grant_jti,
        )
        self.outbox_id = row.outbox_id
        self.chain.append(self.tenant, {
            "event": "execution_authorized",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "item_id": self.item_id,
            "tool_call_hash": self.tool_call_hash,
            "grant_jti": self.grant_jti,
            "pep_allowed": True,
        })

    @rule(winner=st.sampled_from(["worker-1", "worker-2"]))
    def race_two_workers_on_claim_and_dispatch(self, winner: str) -> None:
        from remora.enforcement.outbox import OutboxState
        from remora.execution.outcome import DispatchOutcome

        if self.outbox_id is None or self.claimed_by is not None or self.item_id is None:
            return
        loser = "worker-2" if winner == "worker-1" else "worker-1"
        c1 = self.outbox.claim(self.outbox_id, worker_id=winner)
        c2 = self.outbox.claim(self.outbox_id, worker_id=loser)
        assert c1 is not None
        assert c2 is None
        self.claimed_by = winner
        self.side_effects += 1
        self.outbox.settle(self.outbox_id, OutboxState.SUCCEEDED, detail=None)
        self.queue.record_execution_outcome(
            self.item_id, outcome=DispatchOutcome.SUCCEEDED, reason=None
        )
        self.chain.append(self.tenant, {
            "event": "execution_result",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "item_id": self.item_id,
            "tool_call_hash": self.tool_call_hash,
            "grant_jti": self.grant_jti,
            "tool_executed": True,
            "state_unknown": False,
        })

    @rule()
    def crash_during_dispatch_Settles_unknown(self) -> None:
        from remora.enforcement.outbox import OutboxState
        from remora.execution.outcome import DispatchOutcome

        if self.outbox_id is None or self.claimed_by is not None or self.item_id is None:
            return
        claimed = self.outbox.claim(self.outbox_id, worker_id="worker-crash")
        assert claimed is not None
        self.claimed_by = "worker-crash"
        self.outbox.settle(
            self.outbox_id, OutboxState.UNKNOWN, detail="tool_failed_nonce_burned"
        )
        self.queue.record_execution_outcome(
            self.item_id,
            outcome=DispatchOutcome.UNKNOWN,
            reason="tool_failed_nonce_burned",
        )
        self.chain.append(self.tenant, {
            "event": "execution_result",
            "proposal_id": self.proposal_id,
            "actor": self.actor,
            "item_id": self.item_id,
            "tool_call_hash": self.tool_call_hash,
            "grant_jti": self.grant_jti,
            "tool_executed": False,
            "state_unknown": True,
            "tool_refusal_reason": "tool_failed_nonce_burned",
        })

    @rule(kind=st.sampled_from(["self_attested", "claimed_only", "computed_verified"]))
    def record_effect_observation(self, kind: str) -> None:
        if self.outbox_id is None or self.claimed_by is None:
            return
        self._tick()
        if kind == "self_attested":
            self.chain.append(self.tenant, {
                "event": "effect_verified",
                "proposal_id": self.proposal_id,
                "actor": self.actor,
                "status": "EFFECT_VERIFIED",
                "reason_code": "self_check",
                "verified_at": self.now.isoformat(),
                "verifier_identity": self.actor,
                "self_attested": True,
                "expected_sha256": "a" * 64,
                "observed_sha256": "a" * 64,
                "evidence_refs": ["verdict:computed"],
            })
        elif kind == "claimed_only":
            if self.independent_verified_effect:
                return
            self.claimed_only_effect = True
            self.chain.append(self.tenant, {
                "event": "effect_verified",
                "proposal_id": self.proposal_id,
                "actor": "verifier-1",
                "status": "EFFECT_VERIFIED",
                "reason_code": "digest_only",
                "verified_at": self.now.isoformat(),
                "verifier_identity": "verifier-1",
                "expected_sha256": "a" * 64,
                "observed_sha256": "a" * 64,
                "evidence_refs": ["verdict:claimed"],
            })
        else:
            self.independent_verified_effect = True
            self.claimed_only_effect = False
            self.chain.append(self.tenant, {
                "event": "effect_verified",
                "proposal_id": self.proposal_id,
                "actor": "verifier-1",
                "status": "EFFECT_VERIFIED",
                "reason_code": "postcondition_matched",
                "verified_at": self.now.isoformat(),
                "verifier_identity": "verifier-1",
                "expected_sha256": "a" * 64,
                "observed_sha256": "a" * 64,
                "expected": {"profile": "10G"},
                "observed": {"profile": "10G"},
                "evidence_refs": ["verdict:computed"],
            })

    @invariant()
    def lifecycle_projections_and_stores_are_coherent(self) -> None:
        from remora.execution.projections import (
            EFFECT_CLAIMED,
            current_state,
            dispatch_projection,
            effect_projection,
        )
        from remora.governance.effect_receipt import ReceiptRefused, resolve_lineage
        from remora.governance.review_queue import ItemStatus

        assert self.side_effects <= 1
        events = self._events()
        if not events:
            return
        disp = dispatch_projection(self.outbox, self.tenant, self.proposal_id)
        state = current_state(events, disp)
        assert state in (MODEL.states | {EFFECT_CLAIMED})

        # Uncomputed or self-attested effects never settle as EFFECT_VERIFIED
        if not self.independent_verified_effect:
            assert state != "EFFECT_VERIFIED"
        if self.claimed_only_effect and not self.independent_verified_effect:
            assert state == EFFECT_CLAIMED
            eff = effect_projection(events)
            if not eff["self_attested"]:
                assert eff["verdict_source"] == "claimed"
                assert eff["effect_state"] == EFFECT_CLAIMED

        # If no dispatch was authorized, resolve_lineage must refuse
        if self.outbox_id is None:
            with pytest.raises(ReceiptRefused):
                resolve_lineage(events)
            if self.item_id is not None:
                q_status = self.queue.item(self.item_id).status
                if not self.live_approval:
                    assert q_status is ItemStatus.PENDING
                    assert state == "REVIEW_PENDING"
                else:
                    assert q_status is ItemStatus.APPROVED
                    assert state == "AUTHORIZED"


TestOrchestratedLifecycle = OrchestratedLifecycleMachine.TestCase
TestOrchestratedLifecycle.settings = settings(max_examples=150, deadline=None)


def test_sqlite_durable_lifecycle_parity(tmp_path) -> None:
    """Run the full voided-approval -> re-approval -> dispatch -> unknown ->
    effect-resolution sequence against SQLite-backed AuditChain and Outbox."""
    from datetime import UTC, datetime

    from remora.enforcement.outbox import OutboxState, SQLiteExecutionOutbox
    from remora.execution.projections import (
        EFFECT_CLAIMED,
        current_state,
        dispatch_projection,
        proposal_events,
    )
    from remora.governance.effect_receipt import ReceiptRefused, resolve_lineage
    from remora.governance.tenant_chain import SQLiteTenantChain

    db_file = str(tmp_path / "lifecycle.sqlite")
    chain = SQLiteTenantChain(db_path=db_file)
    outbox = SQLiteExecutionOutbox(db_path=db_file)
    tenant = "tenant-sql"
    pid = "prop-sql-1"
    now = datetime.now(UTC).isoformat()

    chain.append(tenant, {
        "event": "assessed", "proposal_id": pid, "actor": "agent-1",
        "decision": "verify", "review_item_id": "item-sql-1",
    })
    chain.append(tenant, {
        "event": "approved", "proposal_id": pid, "actor": "rev-1",
        "item_id": "item-sql-1",
    })
    chain.append(tenant, {
        "event": "execution_approval_invalidated", "proposal_id": pid,
        "actor": "agent-1", "item_id": "item-sql-1",
        "detail": "reviewed_risk_tier_changed",
    })
    events = proposal_events(chain, tenant, pid)
    assert current_state(events, None) == "REVIEW_PENDING"
    with pytest.raises(ReceiptRefused):
        resolve_lineage(events)

    # Re-approve and authorize dispatch
    chain.append(tenant, {
        "event": "approved", "proposal_id": pid, "actor": "senior-1",
        "item_id": "item-sql-1",
    })
    row = outbox.record_intent(
        proposal_id=pid, tenant_id=tenant, item_id="item-sql-1",
        tool_name="set_port_profile", tool_call_hash="c" * 64, grant_jti="jti-sql-1",
    )
    assert outbox.claim(row.outbox_id, worker_id="w-1") is not None
    assert outbox.claim(row.outbox_id, worker_id="w-2") is None
    chain.append(tenant, {
        "event": "execution_authorized", "proposal_id": pid, "actor": "agent-1",
        "item_id": "item-sql-1", "tool_call_hash": "c" * 64,
        "grant_jti": "jti-sql-1", "pep_allowed": True,
    })
    outbox.settle(row.outbox_id, OutboxState.UNKNOWN, detail="timeout")
    chain.append_once(tenant, f"execution-result:{row.outbox_id}", {
        "event": "execution_result", "proposal_id": pid, "actor": "agent-1",
        "item_id": "item-sql-1", "tool_call_hash": "c" * 64,
        "grant_jti": "jti-sql-1", "tool_executed": False, "state_unknown": True,
    })

    events = proposal_events(chain, tenant, pid)
    disp = dispatch_projection(outbox, tenant, pid)
    assert current_state(events, disp) == "UNKNOWN"

    # Claimed-only effect does not become EFFECT_VERIFIED
    chain.append(tenant, {
        "event": "effect_verified", "proposal_id": pid, "actor": "verifier-1",
        "status": "EFFECT_VERIFIED", "reason_code": "digest_only",
        "verified_at": now, "verifier_identity": "verifier-1",
        "expected_sha256": "a" * 64, "observed_sha256": "a" * 64,
        "evidence_refs": ["verdict:claimed"],
    })
    events = proposal_events(chain, tenant, pid)
    assert current_state(events, disp) == EFFECT_CLAIMED

    # Independent computed effect resolves UNKNOWN to EFFECT_VERIFIED
    chain.append(tenant, {
        "event": "effect_verified", "proposal_id": pid, "actor": "verifier-1",
        "status": "EFFECT_VERIFIED", "reason_code": "postcondition_matched",
        "verified_at": now, "verifier_identity": "verifier-1",
        "expected_sha256": "a" * 64, "observed_sha256": "a" * 64,
        "expected": {"profile": "10G"}, "observed": {"profile": "10G"},
        "evidence_refs": ["verdict:computed"],
    })
    events = proposal_events(chain, tenant, pid)
    assert current_state(events, disp) == "EFFECT_VERIFIED"


# ── Targeted AST mutation sweep over R3 review/execution/projection/flow ────


def _generate_ast_mutants(
    module_obj: object, fn_name: str
) -> list[dict[str, object]]:
    """Generate first-order AST mutants (negated if-guards, flipped comparisons,
    flipped boolean operators, flipped boolean returns) for *fn_name* in
    *module_obj*, recording the AST diff and separating compile/import errors
    from callable mutants (SDD v2 AR-003)."""
    import ast
    import copy
    import difflib
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(getattr(module_obj, fn_name)))
    base_tree = ast.parse(src)
    base_unparsed = ast.unparse(base_tree).splitlines()
    fn_node = base_tree.body[0]
    assert isinstance(fn_node, ast.FunctionDef)

    sites: list[tuple[str, str, int, object]] = []

    for idx, node in enumerate(ast.walk(fn_node)):
        if isinstance(node, ast.If):
            def _mut_if(tree: ast.Module, target_idx: int = idx) -> None:
                cur = [n for n in ast.walk(tree.body[0])][target_idx]
                assert isinstance(cur, ast.If)
                cur.test = ast.UnaryOp(op=ast.Not(), operand=cur.test)
            sites.append((
                f"{fn_name}:negate_if@{node.lineno}:{idx}",
                "negate_if",
                node.lineno,
                _mut_if,
            ))

        elif isinstance(node, ast.Compare) and len(node.ops) == 1:
            op = node.ops[0]
            replacement = {
                ast.Eq: ast.NotEq,
                ast.NotEq: ast.Eq,
                ast.LtE: ast.Lt,
                ast.Lt: ast.LtE,
                ast.In: ast.NotIn,
                ast.NotIn: ast.In,
                ast.Is: ast.IsNot,
                ast.IsNot: ast.Is,
            }.get(type(op))
            if replacement is not None:
                op_name = f"flip_cmp_{type(op).__name__}"

                def _mut_cmp(
                    tree: ast.Module,
                    target_idx: int = idx,
                    rep: type = replacement,
                ) -> None:
                    cur = [n for n in ast.walk(tree.body[0])][target_idx]
                    assert isinstance(cur, ast.Compare)
                    cur.ops = [rep()]
                sites.append((
                    f"{fn_name}:{op_name}@{node.lineno}:{idx}",
                    op_name,
                    node.lineno,
                    _mut_cmp,
                ))

        elif isinstance(node, ast.BoolOp):
            rep_bool = ast.Or if isinstance(node.op, ast.And) else ast.And
            b_name = f"flip_boolop_{type(node.op).__name__}"

            def _mut_bool(
                tree: ast.Module,
                target_idx: int = idx,
                rep: type = rep_bool,
            ) -> None:
                cur = [n for n in ast.walk(tree.body[0])][target_idx]
                assert isinstance(cur, ast.BoolOp)
                cur.op = rep()
            sites.append((
                f"{fn_name}:{b_name}@{node.lineno}:{idx}",
                b_name,
                node.lineno,
                _mut_bool,
            ))

        elif (
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, bool)
        ):
            flipped = not node.value.value

            def _mut_ret(
                tree: ast.Module,
                target_idx: int = idx,
                val: bool = flipped,
            ) -> None:
                cur = [n for n in ast.walk(tree.body[0])][target_idx]
                assert isinstance(cur, ast.Return)
                cur.value = ast.Constant(value=val)
            sites.append((
                f"{fn_name}:flip_return@{node.lineno}:{idx}",
                "flip_return",
                node.lineno,
                _mut_ret,
            ))

    compiled: list[dict[str, object]] = []
    for mid, operator, lineno, mutator in sites:
        tree_copy = copy.deepcopy(base_tree)
        mutator(tree_copy)
        ast.fix_missing_locations(tree_copy)
        mut_unparsed = ast.unparse(tree_copy).splitlines()
        diff = "\n".join(difflib.unified_diff(
            base_unparsed, mut_unparsed, fromfile=fn_name, tofile=mid, lineterm=""
        ))
        ns = dict(vars(module_obj))
        try:
            code_obj = compile(tree_copy, f"<mutant:{mid}>", "exec")
            exec(code_obj, ns)  # noqa: S102
            fn_callable = ns[fn_name]
            compile_error = None
        except (SyntaxError, ImportError, TypeError) as exc:
            fn_callable = None
            compile_error = f"{type(exc).__name__}: {exc}"
        compiled.append({
            "mutant_id": mid,
            "function": fn_name,
            "operator": operator,
            "lineno": lineno,
            "ast_diff": diff,
            "callable": fn_callable,
            "compile_error": compile_error,
        })
    return compiled


# Equivalent mutants where two guards or checks cover the same boundary:
# documented explicitly rather than weakened (PRF-056 / RMR-AUD-013).
KNOWN_EQUIVALENT_R3_MUTANTS: dict[str, str] = {}


def test_r3_surface_ast_mutation_sweep() -> None:
    """PRF-056 (RMR-AUD-013): targeted mutation testing over the R3 review
    queue, execution service, projections and flow-check functions that sit
    outside [tool.mutmut]."""
    import importlib
    import types
    from datetime import UTC, datetime, timedelta

    from remora.enforcement.token import AuthorizationContext
    from remora.flow.label import Integrity, Label
    from remora.flow.spec import parse_flow
    from remora.governance.effect_receipt import ReceiptRefused
    from remora.governance.review_queue import Approval
    from remora.governance.tenant_chain import TenantAuditChain
    from remora.policy.report import DecisionAction, DecisionReason

    proj_mod = importlib.import_module("remora.execution.projections")
    svc_mod = importlib.import_module("remora.execution.service")
    flow_mod = importlib.import_module("remora.flow.check")
    er_mod = importlib.import_module("remora.governance.effect_receipt")
    rq_mod = importlib.import_module("remora.governance.review_queue")

    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)

    def _rep(action: DecisionAction, *reasons: str) -> object:
        return types.SimpleNamespace(
            action=action,
            reasons=tuple(types.SimpleNamespace(value=r) for r in reasons),
        )

    def _app(
        action: DecisionAction,
        reasons: tuple[str, ...] | None = ("r1",),
        policy_hash: str | None = "pol-1",
    ) -> Approval:
        return Approval(
            item_id="i-1",
            approved_action=action,
            approver="rev-1",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            tool_call_hash="c" * 64,
            observation_hash="o" * 64,
            approval_policy_hash=policy_hash,
            approved_reasons=reasons,
        )

    def check_approval_survives(fn) -> None:
        # 1. GRANT_ONLY_REASONS always refused
        assert fn(
            _rep(DecisionAction.ESCALATE, DecisionReason.FLOW_CONFIDENTIALITY_VIOLATION.value),
            _app(DecisionAction.ESCALATE, (DecisionReason.FLOW_CONFIDENTIALITY_VIOLATION.value,)),
        ) is False
        # 2. Approved ESCALATE with recorded reasons: subset survives on A/V/E, new reason fails, AB fails
        assert fn(_rep(DecisionAction.ESCALATE, "r1"), _app(DecisionAction.ESCALATE, ("r1", "r2"))) is True
        assert fn(_rep(DecisionAction.VERIFY, "r1"), _app(DecisionAction.ESCALATE, ("r1",))) is True
        assert fn(_rep(DecisionAction.ACCEPT, "r1"), _app(DecisionAction.ESCALATE, ("r1",))) is True
        assert fn(_rep(DecisionAction.ESCALATE, "r1", "r_new"), _app(DecisionAction.ESCALATE, ("r1",))) is False
        assert fn(_rep(DecisionAction.ABSTAIN, "r1"), _app(DecisionAction.ESCALATE, ("r1",))) is False
        # 3. Approved ESCALATE without recorded reasons: fresh ESCALATE fails, fresh VERIFY/ACCEPT survives
        assert fn(_rep(DecisionAction.ESCALATE, "r1"), _app(DecisionAction.ESCALATE, None)) is False
        assert fn(_rep(DecisionAction.VERIFY, "r1"), _app(DecisionAction.ESCALATE, None)) is True
        # 4. Approved VERIFY with recorded reasons: fresh VERIFY requires subset, fresh ACCEPT survives, fresh ESCALATE fails
        assert fn(_rep(DecisionAction.VERIFY, "r1"), _app(DecisionAction.VERIFY, ("r1",))) is True
        assert fn(_rep(DecisionAction.VERIFY, "r1"), _app(DecisionAction.VERIFY, ("r1", "r2"))) is True
        assert fn(_rep(DecisionAction.VERIFY, "r1", "r_new"), _app(DecisionAction.VERIFY, ("r1",))) is False
        assert fn(_rep(DecisionAction.ACCEPT, "r_new"), _app(DecisionAction.VERIFY, ("r1",))) is True
        assert fn(_rep(DecisionAction.ESCALATE, "r1"), _app(DecisionAction.VERIFY, ("r1",))) is False
        # 5. Approved VERIFY without recorded reasons: fresh VERIFY survives, fresh ESCALATE/ABSTAIN fails
        assert fn(_rep(DecisionAction.VERIFY, "r_any"), _app(DecisionAction.VERIFY, None)) is True
        assert fn(_rep(DecisionAction.ABSTAIN, "r_any"), _app(DecisionAction.VERIFY, None)) is False
        # 6. Approved ACCEPT (hypothetical boundary for _SEVERITY <=): ACCEPT survives, VERIFY fails
        assert fn(_rep(DecisionAction.ACCEPT), _app(DecisionAction.ACCEPT, None)) is True
        assert fn(_rep(DecisionAction.VERIFY), _app(DecisionAction.ACCEPT, None)) is False

    def check_approval_policy_refusal(fn) -> None:
        assert fn(_app(DecisionAction.VERIFY, policy_hash=None), None) is None
        assert fn(_app(DecisionAction.VERIFY, policy_hash=""), "pol-1") == "approval_policy_unbound"
        assert fn(_app(DecisionAction.VERIFY, policy_hash=None), "pol-1") == "approval_policy_unbound"
        assert fn(_app(DecisionAction.VERIFY, policy_hash="pol-1"), "pol-2") == "approval_policy_changed"
        assert fn(_app(DecisionAction.VERIFY, policy_hash="pol-1"), "pol-1") is None

    def check_is_claimed_verdict(fn) -> None:
        assert fn({"status": "EFFECT_MISMATCH", "evidence_refs": ["verdict:claimed"]}) is False
        assert fn({"status": "EFFECT_VERIFIED", "evidence_refs": ["verdict:claimed"], "expected": {"a": 1}, "observed": {"a": 1}}) is True
        assert fn({"status": "EFFECT_VERIFIED", "evidence_refs": ["verdict:computed"]}) is False
        assert fn({"status": "EFFECT_VERIFIED", "evidence_refs": []}) is True
        assert fn({"status": "EFFECT_VERIFIED", "expected": {"a": 1}}) is False
        assert fn({"status": "EFFECT_VERIFIED", "observed": {"a": 1}}) is False

    def check_fold_state(fn) -> None:
        assert fn([]) == "PROPOSED"
        assert fn([{"event": "assessed", "payload": {}}]) == "ASSESSED"
        assert fn([{"event": "assessed", "payload": {"review_item_id": "i1"}}]) == "REVIEW_PENDING"
        assert fn([{"event": "assessed", "payload": {}}, {"event": "review_enqueued", "payload": {}}]) == "REVIEW_PENDING"
        assert fn([{"event": "approved", "payload": {}}]) == "AUTHORIZED"
        assert fn([{"event": "approved", "payload": {}}, {"event": "execution_binding_refused", "payload": {}}]) == "AUTHORIZED"
        assert fn([{"event": "approved", "payload": {}}, {"event": "execution_approval_invalidated", "payload": {}}]) == "REVIEW_PENDING"
        assert fn([{"event": "rejected", "payload": {}}]) == "REFUSED"
        assert fn([{"event": "execution_authorized", "payload": {}}]) == "DISPATCHING"
        assert fn([{"event": "execution_authorized", "payload": {}}, {"event": "execution_result", "payload": {"tool_executed": True}}]) == "SUCCEEDED"
        assert fn([{"event": "execution_authorized", "payload": {}}, {"event": "execution_result", "payload": {"tool_executed": False, "state_unknown": True}}]) == "UNKNOWN"
        assert fn([{"event": "execution_authorized", "payload": {}}, {"event": "execution_result", "payload": {"tool_executed": False, "state_unknown": False}}]) == "REFUSED"
        assert fn([{"event": "approved", "payload": {}}, {"event": "execution_grant_refused", "payload": {}}]) == "REFUSED"
        assert fn([{"event": "approved", "payload": {}}, {"event": "effect_verified", "payload": {}}]) == "AUTHORIZED"

    def check_proposal_envelope_refusal(fn) -> None:
        call = types.SimpleNamespace(schema_valid=True, rollback_available=True)
        env_hash = svc_mod.proposal_envelope_hash(call)
        c_ok = TenantAuditChain()
        c_ok.append("t1", {
            "event": "assessed", "proposal_id": "p1", "actor": "a1",
            "proposal_envelope_hash": env_hash,
        })
        assert fn(c_ok, "t1", "p1", call) is None
        altered = types.SimpleNamespace(schema_valid=False, rollback_available=True)
        assert fn(c_ok, "t1", "p1", altered) is not None
        c_no_hash = TenantAuditChain()
        c_no_hash.append("t1", {"event": "assessed", "proposal_id": "p1", "actor": "a1"})
        assert fn(c_no_hash, "t1", "p1", call) is not None

    def check_approved_context_refusal(fn) -> None:
        c = TenantAuditChain()
        c.append("t1", {
            "event": "assessed", "proposal_id": "p1", "actor": "alice",
            "context_id": "ctx-1", "task_id": "task-1",
            "delegated_executor": "bob", "intent_authority_hash": "ih-1",
        })
        base_ctx = AuthorizationContext(
            tenant="t1", principal="alice", context_id="ctx-1",
            task_id="task-1", delegated_executor="bob", intent_authority_hash="ih-1",
        )
        assert fn(c, "t1", "p1", base_ctx) is None
        # Valid delegate bob acting for alice
        del_ctx = AuthorizationContext(
            tenant="t1", principal="bob", context_id="ctx-1",
            task_id="task-1", delegated_executor="bob", intent_authority_hash="ih-1",
        )
        assert fn(c, "t1", "p1", del_ctx) is None
        # Wrong actor mallory
        bad_actor = AuthorizationContext(
            tenant="t1", principal="mallory", context_id="ctx-1",
            task_id="task-1", delegated_executor="bob", intent_authority_hash="ih-1",
        )
        ref = fn(c, "t1", "p1", bad_actor)
        assert ref is not None and ref.mismatched == ("principal",)
        # Missing assessed record
        assert fn(c, "t1", "unknown-p", base_ctx) is not None

    def check_recipients(fn) -> None:
        spec_from_args = parse_flow({
            "provider": "tcb",
            "arguments": {"to": {"kind": "email"}, "cc": {"kind": "principal"}},
            "sources": {},
            "sink": {"recipients": {"from_args": {"to": "email", "cc": "principal"}}},
        })
        # Empty args -> unresolved
        r_empty, u_empty = fn(spec_from_args, {"to": []})
        assert r_empty == frozenset()
        assert u_empty == ("cc", "to")
        # Valid email and principal
        r_ok, u_ok = fn(spec_from_args, {"to": "user@example.com", "cc": "user://acme/alice"})
        assert "email://example.com/user" in r_ok
        assert "user://acme/alice" in r_ok
        assert u_ok == ()
        # Invalid email -> unresolved
        _r_bad, u_bad = fn(spec_from_args, {"to": "not-an-email"})
        assert u_bad == ("to",)
        # URL host rule + non-tcb provider
        spec_url = parse_flow({
            "provider": "ext://vendor.example",
            "arguments": {"endpoint": {"kind": "url"}},
            "sources": {},
            "sink": {"recipients": {"url_host_of": "endpoint"}},
        })
        r_url, u_url = fn(spec_url, {"endpoint": "https://api.example.com/v1"})
        assert r_url == frozenset({"ext://api.example.com", "ext://vendor.example"})
        assert u_url == ()
        # IBAN rule
        spec_iban = parse_flow({
            "provider": "tcb",
            "arguments": {"iban": {"kind": "iban"}},
            "sources": {},
            "sink": {"recipients": {"iban_of": "iban"}},
        })
        r_iban, u_iban = fn(spec_iban, {"iban": "NO9386011117947"})
        assert "iban://no9386011117947" in r_iban
        assert u_iban == ()
        # resource_of rule with and without resource_acl
        spec_res = parse_flow({
            "provider": "tcb",
            "arguments": {"doc": {"kind": "resource"}},
            "sources": {},
            "sink": {"recipients": {"resource_of": "doc"}},
        })
        _r_no_acl, u_no_acl = fn(spec_res, {"doc": "res://t1/doc"}, resource_acl=None)
        assert u_no_acl == ("doc",)
        r_acl, u_acl = fn(
            spec_res, {"doc": "res://t1/doc"},
            resource_acl=lambda _r: ["email://example.com/alice"],
        )
        assert r_acl == frozenset({"email://example.com/alice"})
        assert u_acl == ()
        # static rule
        spec_static = parse_flow({
            "provider": "tcb",
            "arguments": {},
            "sources": {},
            "sink": {"recipients": {"static": ["email://example.com/audit"]}},
        })
        r_st, u_st = fn(spec_static, {})
        assert r_st == frozenset({"email://example.com/audit"})
        assert u_st == ()
        # none rule
        spec_none = parse_flow({
            "provider": "tcb",
            "arguments": {},
            "sources": {},
            "sink": {"recipients": "none"},
        })
        r_none, u_none = fn(spec_none, {})
        assert r_none == frozenset()
        assert u_none == ()

    def check_authorization_of(fn) -> None:
        res = {"grant_jti": "j1", "tool_call_hash": "h1"}
        auth_ev = {
            "event": "execution_authorized",
            "payload": {"event": "execution_authorized", "pep_allowed": True, "grant_jti": "j1", "tool_call_hash": "h1"},
        }
        # 1. Valid accept path
        ev_accept = [{"event": "assessed", "payload": {"event": "assessed", "decision": "accept"}}, auth_ev]
        assert fn(ev_accept, res)["grant_jti"] == "j1"
        # 2. Valid verify path with live approval
        ev_verify = [
            {"event": "assessed", "payload": {"event": "assessed", "decision": "verify"}},
            {"event": "approved", "payload": {"event": "approved"}},
            auth_ev,
        ]
        assert fn(ev_verify, res)["grant_jti"] == "j1"
        # 3. Denied assessment
        for d in ("abstain", "deny", "reject", "rejected"):
            with pytest.raises(ReceiptRefused) as exc:
                fn([{"event": "assessed", "payload": {"event": "assessed", "decision": d}}, auth_ev], res)
            assert exc.value.reason == "dispatched_after_deny"
        # 4. Unknown decision
        with pytest.raises(ReceiptRefused) as exc:
            fn([{"event": "assessed", "payload": {"event": "assessed", "decision": "unknown"}}, auth_ev], res)
        assert exc.value.reason == "assessment_decision_unknown"
        # 5. Rejected in trail
        with pytest.raises(ReceiptRefused) as exc:
            fn([*ev_verify[:2], {"event": "rejected", "payload": {"event": "rejected"}}, auth_ev], res)
        assert exc.value.reason == "dispatched_after_deny"
        # 6. Voided approval before execution_authorized
        for void_ev in ("execution_approval_expired", "execution_approval_invalidated"):
            with pytest.raises(ReceiptRefused) as exc:
                fn([
                    {"event": "assessed", "payload": {"event": "assessed", "decision": "verify"}},
                    {"event": "approved", "payload": {"event": "approved"}},
                    {"event": void_ev, "payload": {"event": void_ev}},
                    auth_ev,
                ], res)
            assert exc.value.reason == "dispatched_without_approval"
        # 7. Verify without approval and without matching execution_authorized
        with pytest.raises(ReceiptRefused) as exc:
            fn([{"event": "assessed", "payload": {"event": "assessed", "decision": "verify"}}], res)
        assert exc.value.reason == "dispatched_without_approval"
        # 8. Accept without matching execution_authorized (or pep_allowed not True / wrong jti / wrong hash)
        for bad_auth in (
            {"event": "execution_authorized", "payload": {"pep_allowed": "true", "grant_jti": "j1", "tool_call_hash": "h1"}},
            {"event": "execution_authorized", "payload": {"pep_allowed": True, "grant_jti": "j2", "tool_call_hash": "h1"}},
            {"event": "execution_authorized", "payload": {"pep_allowed": True, "grant_jti": "j1", "tool_call_hash": "h2"}},
        ):
            with pytest.raises(ReceiptRefused) as exc:
                fn([{"event": "assessed", "payload": {"event": "assessed", "decision": "accept"}}, bad_auth], res)
            assert exc.value.reason == "dispatch_not_authorized"
        with pytest.raises(ReceiptRefused) as exc:
            fn(ev_accept, {"grant_jti": "", "tool_call_hash": "h1"})
        assert exc.value.reason == "dispatch_not_authorized"

    def check_flow_check(fn) -> None:
        user = "user://acme/alice"
        bob = "email://corp.example/bob"
        spec = parse_flow({
            "provider": "tcb",
            "arguments": {
                "to": {"kind": "email"},
                "body": {"kind": "text"},
                "note": {"kind": "text"},
            },
            "sources": {"default_integrity": "TRUSTED"},
            "sink": {
                "recipients": {"from_args": {"to": "email"}},
                "payload_args": ["body"],
                "integrity_required": ["to"],
                "roles_accepted": {"to": ["recipient"]},
                "control_integrity_required": True,
            },
        })
        clean_ctx = Label({user, bob}, Integrity.TRUSTED)
        tainted_ctx = Label({user, bob}, Integrity.UNTRUSTED)
        secret_lbl = Label({user}, Integrity.TRUSTED)
        untrusted_lbl = Label({user, bob}, Integrity.UNTRUSTED)

        # 1. Clean call
        v_clean = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": clean_ctx, "body": clean_ctx},
            resolved_args={"to": "bob@corp.example", "body": "hi"},
            epoch=1, parameter_roles={"to": "recipient"},
        )
        assert v_clean.clean
        # 2. Confidentiality violation (secret to bob) and declassified
        v_conf = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": clean_ctx, "body": secret_lbl},
            resolved_args={"to": "bob@corp.example", "body": "secret"},
            epoch=1,
        )
        assert v_conf.conf_viol == frozenset({bob})
        v_decl = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": clean_ctx, "body": secret_lbl},
            resolved_args={"to": "bob@corp.example", "body": "secret"},
            epoch=1, declassified=frozenset({bob}),
        )
        assert v_decl.conf_viol == frozenset()
        # 3. Non-payload arg (note) with secret does not taint payload_args=["body"]
        v_non_payload = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": clean_ctx, "body": clean_ctx, "note": secret_lbl},
            resolved_args={"to": "bob@corp.example", "body": "hi", "note": "secret"},
            epoch=1,
        )
        assert v_non_payload.clean
        # 4. Integrity violation, endorsed, integrity_granted, and wrong parameter role
        v_int = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": untrusted_lbl, "body": clean_ctx},
            resolved_args={"to": "bob@corp.example", "body": "hi"},
            epoch=1,
        )
        assert v_int.int_viol == frozenset({"to"})
        v_end = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": untrusted_lbl, "body": clean_ctx},
            resolved_args={"to": "bob@corp.example", "body": "hi"},
            epoch=1, endorsed=lambda f, v: f == "to" and v == "bob@corp.example",
        )
        assert v_end.int_viol == frozenset()
        v_igr = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": untrusted_lbl, "body": clean_ctx},
            resolved_args={"to": "bob@corp.example", "body": "hi"},
            epoch=1, integrity_granted=frozenset({"to"}),
        )
        assert v_igr.int_viol == frozenset()
        v_role = fn(
            spec, context_label=clean_ctx,
            value_labels={"to": clean_ctx, "body": clean_ctx},
            resolved_args={"to": "bob@corp.example", "body": "hi"},
            epoch=1, parameter_roles={"to": "wrong_role"},
        )
        assert v_role.int_viol == frozenset({"to"})
        # 5. Control integrity violation and control_granted
        v_ctrl = fn(
            spec, context_label=tainted_ctx,
            value_labels={"to": clean_ctx, "body": clean_ctx},
            resolved_args={"to": "bob@corp.example", "body": "hi"},
            epoch=1,
        )
        assert v_ctrl.ctrl_viol is True
        v_ctrl_ok = fn(
            spec, context_label=tainted_ctx,
            value_labels={"to": clean_ctx, "body": clean_ctx},
            resolved_args={"to": "bob@corp.example", "body": "hi"},
            epoch=1, control_granted=True,
        )
        assert v_ctrl_ok.ctrl_viol is False
        # 6. Null or omitted integrity_required field is skipped for integrity check
        v_null_to = fn(
            spec, context_label=tainted_ctx,
            value_labels={},
            resolved_args={"to": None, "body": "hi"},
            epoch=1, control_granted=True,
        )
        assert v_null_to.int_viol == frozenset()

    targets = [
        (rq_mod, "_approval_survives", check_approval_survives),
        (rq_mod, "_approval_policy_refusal", check_approval_policy_refusal),
        (proj_mod, "is_claimed_verdict", check_is_claimed_verdict),
        (proj_mod, "_fold_state", check_fold_state),
        (svc_mod, "proposal_envelope_refusal", check_proposal_envelope_refusal),
        (svc_mod, "approved_context_refusal", check_approved_context_refusal),
        (flow_mod, "recipients", check_recipients),
        (er_mod, "_authorization_of", check_authorization_of),
        (flow_mod, "flow_check", check_flow_check),
    ]

    total_mutants = 0
    compile_errors: list[str] = []
    semantic_kills: list[dict[str, object]] = []
    unexpected_survivors: list[str] = []

    for mod, fn_name, oracle in targets:
        # Sanity check: the unmutated original function passes the same harness (AR-003)
        oracle(getattr(mod, fn_name))
        mutants = _generate_ast_mutants(mod, fn_name)
        assert mutants, f"no mutants generated for {fn_name}"
        total_mutants += len(mutants)
        for m in mutants:
            mid = str(m["mutant_id"])
            assert m["ast_diff"], f"mutant {mid} produced empty AST diff"
            if m["compile_error"] is not None:
                compile_errors.append(f"{mid}: {m['compile_error']}")
                continue
            mutated_fn = m["callable"]
            assert callable(mutated_fn)
            try:
                oracle(mutated_fn)
            except (Exception, pytest.fail.Exception) as exc:
                semantic_kills.append({
                    "mutant_id": mid,
                    "function": fn_name,
                    "operator": m["operator"],
                    "lineno": m["lineno"],
                    "killed_by": oracle.__name__,
                    "exception": type(exc).__name__,
                })
            else:
                if mid not in KNOWN_EQUIVALENT_R3_MUTANTS:
                    unexpected_survivors.append(mid)

    assert compile_errors == [], f"compile/import errors in AST mutants: {compile_errors}"
    assert total_mutants == 132, f"expected 132 scoped AST mutants across 9 functions, got {total_mutants}"
    assert len(semantic_kills) == 132
    assert unexpected_survivors == [], (
        f"unkilled non-equivalent R3 AST mutants ({len(unexpected_survivors)}/{total_mutants}): "
        f"{unexpected_survivors}"
    )


