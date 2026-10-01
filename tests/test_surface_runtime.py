# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The runtime's served list and dispatch evidence come from the same process."""
from datetime import UTC, datetime

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.toolcall.runtime_surface import RuntimeTool, SurfaceVerdict
from remora.toolcall.surface_runtime import SurfaceRuntime


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "surface-test-key")
    dispatcher = GovernedToolDispatcher("policy")
    rt = SurfaceRuntime(dispatcher, {"write": "a" * 64}, mode="enforce",
                        trusted_verifiers={"reader": "read-principal"})
    rt.register(RuntimeTool("write", "native", True, True, "a" * 64), lambda args: args)
    return rt


def assess(rt, **kwargs):
    return rt.assess("write", {"value": 1}, tenant="t", principal="actor", target="test", **kwargs)


def lease():
    return ExecutionLease.issue(
        decision="accept", tenant_id="t", actor_identity="actor", tool_name="write",
        arguments={"value": 1}, target_environment="test", policy_bundle_hash="policy",
        issued_at=datetime.now(UTC).isoformat(),
    )


def dispatch(rt, assessment, **kwargs):
    return rt.dispatch(assessment.assessment_id, lease(), "write", {"value": 1},
                       tenant="t", principal="actor", target="test", **kwargs)


def test_actual_served_list_and_governed_dispatch(runtime):
    assert [t["name"] for t in runtime.offered_tools()] == ["write"]
    assessment = assess(runtime)
    outcome = dispatch(runtime, assessment)
    assert outcome.execution.executed
    assert outcome.continuity.verdict is SurfaceVerdict.MATCHED_OBSERVATION
    assert outcome.runtime_outcome == "SUCCEEDED"
    assert outcome.effect_verdict == "NOT_ESTABLISHED"


def test_injected_dispatcher_tool_is_observed_and_refused(runtime):
    assessment = assess(runtime)
    runtime.dispatcher.register("shell", lambda args: args)
    outcome = dispatch(runtime, assessment)
    assert not outcome.execution.executed
    assert outcome.surface.unexpected_tools == ("shell",)
    assert outcome.continuity.verdict is SurfaceVerdict.MISMATCH


def test_shadow_records_drift_but_still_requires_a_lease(runtime):
    runtime.mode = "shadow"
    assessment = assess(runtime)
    runtime.dispatcher.register("shell", lambda args: args)
    outcome = dispatch(runtime, assessment)
    assert outcome.execution.executed
    assert outcome.surface.verdict is SurfaceVerdict.MISMATCH
    refused = runtime.dispatch(assess(runtime).assessment_id, None, "write", {"value": 1},
                               tenant="t", principal="actor", target="test")
    assert refused.runtime_outcome == "REFUSED"
    assert refused.execution.refusal_reason == "missing_lease"


def test_assessment_cannot_move_to_another_actor_or_action(runtime):
    assessment = assess(runtime)
    with pytest.raises(ValueError, match="assessment_binding_mismatch"):
        runtime.dispatch(assessment.assessment_id, lease(), "write", {"value": 2},
                         tenant="t", principal="actor", target="test")


def test_unknown_or_replayed_assessment_cannot_dispatch(runtime):
    assessment = assess(runtime)
    dispatch(runtime, assessment)
    with pytest.raises(ValueError, match="assessment_not_found"):
        dispatch(runtime, assessment)


def test_missing_metadata_never_invents_a_toolspec(runtime):
    runtime.dispatcher.register("extra", lambda args: args)
    snapshot = runtime.snapshot()
    extra = next(t for t in snapshot.tools if t.tool_id == "extra")
    assert extra.toolspec_hash is None
    assert extra.callable_at_dispatch is True


def test_same_name_callable_replacement_is_drift(runtime):
    assessment = assess(runtime)
    runtime.dispatcher.register("write", lambda args: {"different": True})
    outcome = dispatch(runtime, assessment)
    assert outcome.continuity.verdict is SurfaceVerdict.MISMATCH
    assert outcome.runtime_outcome == "REFUSED"


def test_expired_assessment_cannot_execute(runtime):
    assessment = assess(runtime)
    runtime._clock = lambda: assessment.expires_at
    with pytest.raises(ValueError, match="assessment_expired"):
        dispatch(runtime, assessment)


def test_runtime_records_and_rechecks_real_effect(runtime):
    from remora.governance.effect_verification import PostconditionContract
    state = {}
    runtime.register(RuntimeTool("write", "native", True, True, "a" * 64),
                     lambda args: state.update(args))
    assessment = assess(runtime, postcondition=PostconditionContract(
        "write", "reader", {"id": "row"}, {"value": 1}))
    outcome = dispatch(runtime, assessment)
    assert outcome.runtime_outcome == "SUCCEEDED"
    evidence = runtime.record_effect(assessment.assessment_id, tenant="t",
                                    principal="read-principal", verifier_identity="reader",
                                    observed=dict(state))
    assert evidence["property_verdict"] == "EFFECT_VERIFIED"
    assert runtime.recheck_effect(assessment.assessment_id, tenant="t") == evidence
    assert runtime.audit_valid("t")
    with pytest.raises(ValueError, match="effect_already_settled"):
        runtime.record_effect(assessment.assessment_id, tenant="t", principal="read-principal",
                              verifier_identity="reader", observed={"value": 2})


def test_effect_is_tenant_bound_and_contract_is_detached(runtime):
    from remora.governance.effect_verification import PostconditionContract
    expected = {"value": {"nested": 1}}
    assessment = assess(runtime, postcondition=PostconditionContract("write", "reader", {}, expected))
    expected["value"]["nested"] = 2
    dispatch(runtime, assessment)
    with pytest.raises(ValueError, match="execution_not_found"):
        runtime.record_effect(assessment.assessment_id, tenant="other", principal="reader",
                              verifier_identity="reader", observed={"value": 1})


def test_partial_execution_is_unknown_and_cannot_be_retried(runtime):
    def partial(args):
        raise RuntimeError("response lost after possible effect")
    runtime.register(RuntimeTool("write", "native", True, True, "a" * 64), partial)
    assessment = assess(runtime)
    assert dispatch(runtime, assessment).runtime_outcome == "UNKNOWN"
    with pytest.raises(ValueError, match="assessment_not_found"):
        dispatch(runtime, assessment)


def test_registration_waits_for_dispatch_transaction(runtime):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release, attempted = Event(), Event(), Event()
    def blocking(args):
        entered.set()
        assert release.wait(5)
        return args
    def register():
        attempted.set()
        runtime.dispatcher.register("write", lambda args: args)
    runtime.register(RuntimeTool("write", "native", True, True, "a" * 64), blocking)
    assessment = assess(runtime)
    with ThreadPoolExecutor(max_workers=2) as pool:
        call = pool.submit(dispatch, runtime, assessment)
        assert entered.wait(5)
        mutation = pool.submit(register)
        assert attempted.wait(5)
        assert not mutation.done()
        release.set()
        assert call.result(timeout=5).runtime_outcome == "SUCCEEDED"
        mutation.result(timeout=5)


def test_export_does_not_mutate_retained_audit(runtime):
    dispatch(runtime, assess(runtime))
    exported = runtime.audit_entries("t")
    exported[0]["payload"]["event"] = "forged"
    assert runtime.audit_valid("t")
    assert runtime.audit_entries("t")[0]["payload"]["event"] == "surface_assessment"


def test_undispatched_postconditions_do_not_outlive_their_assessment(runtime):
    from remora.governance.effect_verification import PostconditionContract

    contract = PostconditionContract("write", "reader", {"id": "record"}, {"value": 1})
    stale = [assess(runtime, postcondition=contract) for _ in range(3)]
    runtime._clock = lambda: stale[-1].expires_at
    with pytest.raises(ValueError, match="assessment_expired"):
        dispatch(runtime, stale[0])
    live = assess(runtime, postcondition=contract)
    assert set(runtime._contracts) == {live.assessment_id}
