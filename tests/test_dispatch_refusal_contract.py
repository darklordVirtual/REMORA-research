# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The dispatcher's refusal contract, branch by branch.

The 2026-10-13 mutation sweep left 246 survivors in
``GovernedToolDispatcher.dispatch``. Most rewrote a field of a
``dispatch.refused`` event or a ``DispatchResult`` on a branch no test
asserted in full: the earlier contract suites
(``test_dispatcher_contract.py``, ``test_governance_event_contract.py``)
pinned the common refusals and left the later ones (execution context,
the aggregated runtime refusal, the final-hop re-check, the recorder and
the durable nonce store) checked only for ``executed``. The rest were
behaviour that nothing drove: a shallow copy where the code makes a deep
one, a registry re-check that a same-object re-registration must trip, a
nonce consumed under ``None``.

Every refusal here is asserted as a whole: ``executed is False`` (identity,
because ``None`` would read as a refusal to a truthiness check and break a
settlement that compares with ``False``), ``dispatch_began``, the exact
reason, the lifecycle identity fields, and exactly one ``dispatch.refused``
event with its level and full payload. The level matters: WARNING is a
refusal of the caller's request, ERROR is a fault in the deployment, and
operators alert on the second.

Survivors that cannot change observable behaviour are listed with their
reasons in ``tests/data/mutation_equivalent_dispatch.txt`` instead of being
given vacuous tests.
"""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from remora.audit.recorder import RecorderUnavailable
from remora.capabilities.model import CapabilityEpochs, EffectiveCapabilitySet
from remora.enforcement import lease_signing
from remora.enforcement.lease import (
    DispatchResult,
    ExecutionLease,
    GovernedToolDispatcher,
    ToolExecutionStateUnknown,
)
from remora.enforcement.nonce_store import NonceStoreUnavailable
from remora.enforcement.resolved_effect import ClosedWorldResolver, ResolvedEffect
from remora.enforcement.runtime_identity import (
    current_runtime_identity_hash,
    reset_runtime_identity,
)
from remora.governance.execution_identity import ExecutionContextV1
from remora.governance.procedure import ProcedureContract, StepPattern, absence
from remora.governance.task_identity import TaskIdentity
from remora.policy.observation import canonical_tool_call_hash
from tests.test_execution_context_binding import BUILD, Provider

LOGGER = "remora.governance"
#: Far enough in the past that the wall clock is outside every validity
#: window below: a mutant that drops ``now`` and reads the clock instead
#: refuses rather than passing by coincidence.
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
BUNDLE = "bundle-refusal-1"
TOOL = "wo_close"
ARGS = {"id": "WO-1"}
TENANT = "acme"
ACTOR = "agent-1"
TARGET = "staging"
PROPOSAL = "6f1c1f0e-5d2a-4c3b-9a8e-1b2c3d4e5f60"
JTI = "jti-rc-1"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "refusal-contract-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE",
                 "REMORA_SIGNATURE_FORMAT"):
        monkeypatch.delenv(name, raising=False)


# ── helpers ────────────────────────────────────────────────────────────────


def _lease(*, arguments: Any = ARGS, tenant: str = TENANT, target: str = TARGET,
           actor: str = ACTOR, issued_at: datetime = NOW, **extra: Any) -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id=tenant, actor_identity=actor, tool_name=TOOL,
        arguments=arguments, target_environment=target, policy_bundle_hash=BUNDLE,
        issued_at=issued_at.isoformat(), proposal_id=PROPOSAL, grant_jti=JTI, **extra)


def _dispatcher(fn: Callable[..., Any] | None = None, *, mediated: bool = False,
                **kwargs: Any) -> GovernedToolDispatcher:
    d = GovernedToolDispatcher(BUNDLE, **kwargs)
    d.register(TOOL, fn or (lambda args: {"ok": True}), mediated=mediated)
    return d


def _dispatch(d: GovernedToolDispatcher, lease: ExecutionLease | None,
              arguments: Any = ARGS, **overrides: Any) -> DispatchResult:
    kwargs: dict[str, Any] = dict(tenant_id=TENANT, target_environment=TARGET,
                                  actor_identity=ACTOR, now=NOW.isoformat())
    kwargs.update(overrides)
    return d.dispatch(lease, TOOL, arguments, **kwargs)


def _name(record: logging.LogRecord) -> str:
    return record.getMessage().split(" ", 1)[0]


@pytest.fixture()
def events(caplog) -> Iterator[Callable[[str], list[logging.LogRecord]]]:
    """Records on the governance logger, by event name."""
    caplog.set_level(logging.INFO, logger=LOGGER)

    def named(name: str) -> list[logging.LogRecord]:
        return [r for r in caplog.records if r.name == LOGGER and _name(r) == name]

    yield named


def _identity(r: DispatchResult) -> tuple:
    return (r.executed, r.dispatch_began, r.refusal_reason, r.proposal_id,
            r.execution_context_hash, r.execution_id, r.dispatch_check)


def _assert_refused(result: DispatchResult, events, *, reason: str, level: int,
                    payload: dict[str, Any], proposal_id: str = PROPOSAL,
                    execution_context_hash: str = "", execution_id: str = "",
                    dispatch_check: Any = None) -> None:
    """The whole refusal: result identity and the one event that records it."""
    assert result.executed is False
    assert result.dispatch_began is False
    assert _identity(result) == (False, False, reason, proposal_id,
                                 execution_context_hash, execution_id, dispatch_check)
    (record,) = events("dispatch.refused")
    assert record.levelno == level
    assert record.remora == payload  # type: ignore[attr-defined]


def _refusal_payload(reason: str, *, grant: bool = True, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"reason": reason, "tenant_id": TENANT, "tool_name": TOOL,
                               "proposal_id": PROPOSAL}
    if grant:
        payload["grant_jti"] = JTI
    payload.update(extra)
    return payload


class _Uncopyable:
    def __deepcopy__(self, memo: Any) -> Any:
        raise TypeError("no exact form")

    def __copy__(self) -> Any:
        raise TypeError("no exact form")


def _capability_set(*, tools: tuple[str, ...] = (TOOL,), environment: str = TARGET,
                    constraints: dict[str, Any] | None = None,
                    cls: type[EffectiveCapabilitySet] = EffectiveCapabilitySet,
                    ) -> EffectiveCapabilitySet:
    return cls(
        capability_set_id="cs-rc-1", principal_id=ACTOR, tenant_id=TENANT,
        environment=environment, task_type="maintenance", allowed_tools=tools,
        policy_version="p1", registry_version="r1",
        issued_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
        constraints=constraints if constraints is not None else {},
    )


#: The argument scope the capability tests run under. A call that reaches the
#: argument check with anything but a mapping of ``id`` refuses.
ONLY_ID = {TOOL: {"allowed_fields": ["id"], "conditions": []}}


class _Recorder:
    """An in-memory recorder that can refuse one phase."""

    def __init__(self, fail_phase: str | None = None) -> None:
        self.entries: list[tuple[str, dict[str, Any]]] = []
        self.fail_phase = fail_phase

    def append(self, kind: str, payload: dict[str, Any]) -> SimpleNamespace:
        if payload["phase"] == self.fail_phase:
            raise RecorderUnavailable("recorder down")
        self.entries.append((kind, dict(payload)))
        return SimpleNamespace(seq=len(self.entries) - 1)


class _Store:
    """A durable nonce store double: consumes once, or is down."""

    def __init__(self, *, down: bool = False) -> None:
        self.down = down
        self.consumed: set[str] = set()

    def try_consume(self, nonce: str, *, tenant_id: str) -> bool:
        if self.down:
            raise NonceStoreUnavailable("store down")
        if nonce in self.consumed:
            return False
        self.consumed.add(nonce)
        return True


class _BareLedger:
    """A ledger with ``consume`` only: ``failure`` is optional by contract."""

    def __init__(self) -> None:
        self.consumed: set[str] = set()

    def consume(self, nonce: str) -> bool:
        if nonce in self.consumed:
            return False
        self.consumed.add(nonce)
        return True


def _raise(exc: BaseException) -> Callable[..., Any]:
    def fn(*_args: Any) -> Any:
        raise exc

    return fn


class _Resolver:
    """An effect resolver that runs a side effect, then resolves nothing bound."""

    def __init__(self, side_effect: Callable[[Any], None]) -> None:
        self.side_effect = side_effect

    def resolve(self, tool_name: str, arguments: Any,
                target_environment: str) -> ResolvedEffect:
        self.side_effect(arguments)
        return ResolvedEffect(tool_name, "impl/v1", f"env:{target_environment}", "write")


class _ActorPolicy:
    """A binding policy that requires an actor and nothing else."""

    def required(self, binding: str, tool_name: str | None = None) -> bool:
        return binding == "actor"

    def state(self, binding: str, tool_name: str | None = None) -> str:
        return "REQUIRED" if binding == "actor" else "UNVERIFIABLE"


class _Revocations:
    """An epoch source whose revocation list can change mid-execution."""

    def __init__(self) -> None:
        self.revoked_ids: set[str] = set()

    def current(self, tenant_id: str, principal_id: str) -> CapabilityEpochs:
        return CapabilityEpochs()

    def revoked(self, capability_set_id: str) -> bool:
        return capability_set_id in self.revoked_ids


# ── refusals before a lease is verified ───────────────────────────────────


def test_missing_lease(events) -> None:
    result = _dispatcher().dispatch(None, TOOL, ARGS, tenant_id=TENANT,
                                    now=NOW.isoformat())
    _assert_refused(result, events, reason="missing_lease", level=logging.WARNING,
                    proposal_id="",
                    payload={"reason": "missing_lease", "tenant_id": TENANT,
                             "tool_name": TOOL, "proposal_id": ""})


def test_unknown_tool(events) -> None:
    d = GovernedToolDispatcher(BUNDLE)
    d.register("other_tool", lambda args: None)
    _assert_refused(_dispatch(d, _lease()), events, reason="unknown_tool",
                    level=logging.WARNING,
                    payload=_refusal_payload("unknown_tool", grant=False))


def test_uncopyable_arguments_have_no_exact_form(events) -> None:
    """The tool runs on a private copy; a payload that cannot be copied has no
    form that could be verified and then executed unchanged."""
    calls: list[Any] = []
    d = _dispatcher(calls.append)
    result = _dispatch(d, _lease(), {"id": "WO-1", "handle": _Uncopyable()})
    _assert_refused(result, events, reason="tool_args_not_canonical",
                    level=logging.WARNING,
                    payload=_refusal_payload("tool_args_not_canonical", grant=False))
    assert calls == []


def test_a_raising_spec_resolver_is_an_error_not_a_refusal(events) -> None:
    d = _dispatcher()
    d.bind_toolspec_identity(_raise(RuntimeError("bundle store down")))
    _assert_refused(_dispatch(d, _lease()), events, reason="toolspec_unresolvable",
                    level=logging.ERROR,
                    payload=_refusal_payload("toolspec_unresolvable",
                                             detail="bundle store down"))


def test_task_identity_required(events) -> None:
    d = _dispatcher(require_task_identity=True)
    _assert_refused(_dispatch(d, _lease()), events, reason="task_identity_required",
                    level=logging.WARNING,
                    payload=_refusal_payload("task_identity_required"))


@pytest.mark.parametrize("overrides, reason", [
    (dict(tenant_id="globex"), "tenant_mismatch"),
    (dict(actor_identity="agent-2"), "actor_identity_mismatch"),
    (dict(target_environment="prod"), "target_environment_mismatch"),
    (dict(now=(NOW + timedelta(days=1)).isoformat()), "lease_expired"),
], ids=["tenant", "actor", "target", "expired"])
def test_a_failed_verification_is_a_warning_with_the_verify_reason(
        events, overrides, reason) -> None:
    result = _dispatch(_dispatcher(), _lease(), **overrides)
    payload = _refusal_payload(reason)
    payload["tenant_id"] = overrides.get("tenant_id", TENANT)
    _assert_refused(result, events, reason=reason, level=logging.WARNING,
                    payload=payload)


# ── dispatch.task_unchecked ────────────────────────────────────────────────


def test_a_task_bound_lease_run_without_a_task_is_recorded(events) -> None:
    task = TaskIdentity(context_id="ctx-1", task_id="task-1")
    result = _dispatch(_dispatcher(), _lease(task_identity=task))
    assert result.executed is True
    (record,) = events("dispatch.task_unchecked")
    assert record.levelno == logging.INFO
    assert record.remora == {  # type: ignore[attr-defined]
        "tenant_id": TENANT, "tool_name": TOOL, "proposal_id": PROPOSAL,
        "grant_jti": JTI, "context_id": "ctx-1", "task_id": "task-1",
    }


def test_a_task_checked_against_the_lease_is_not_reported_unchecked(events) -> None:
    task = TaskIdentity(context_id="ctx-1", task_id="task-1")
    result = _dispatch(_dispatcher(), _lease(task_identity=task), task_identity=task)
    assert result.executed is True
    assert events("dispatch.task_unchecked") == []


def test_an_unbound_lease_run_without_a_task_has_nothing_unchecked(events) -> None:
    assert _dispatch(_dispatcher(), _lease()).executed is True
    assert events("dispatch.task_unchecked") == []


def test_a_lease_signed_with_half_a_task_never_reaches_the_task_check(events) -> None:
    """Only one of context_id/task_id set: verify() refuses the lease as
    malformed, so the task_unchecked branch only ever sees both or neither
    (why the ``or``→``and`` mutant of that condition is equivalent)."""
    task = TaskIdentity(context_id="ctx-1", task_id="task-1")
    half = dataclasses.replace(_lease(task_identity=task), task_id="")
    signed = dataclasses.replace(half, signature=lease_signing.sign_payload(
        ExecutionLease._canonical_payload(half._signed_fields()), alg=half.sig_alg))
    result = _dispatch(_dispatcher(), signed)
    _assert_refused(result, events, reason="task_identity_malformed",
                    level=logging.WARNING,
                    payload=_refusal_payload("task_identity_malformed"))
    assert events("dispatch.task_unchecked") == []


# ── the aggregated runtime refusal ─────────────────────────────────────────


def _no_actor_lease() -> ExecutionLease:
    return _lease(actor="")


def _bound(d: GovernedToolDispatcher, bind: Callable[[GovernedToolDispatcher], None]
           ) -> GovernedToolDispatcher:
    bind(d)
    return d


@pytest.mark.parametrize("make, reason", [
    (lambda: _bound(_dispatcher(), lambda d: d.bind_binding_policy(_ActorPolicy())),
     "actor_unbound"),
    (lambda: _dispatcher(require_capability_set=True), "capability_set_required"),
    (lambda: _bound(_dispatcher(), lambda d: d.bind_effect_resolver(
        _Resolver(_raise(OSError("registry down"))))), "resolved_effect_unresolvable"),
    (lambda: _bound(_dispatcher(), lambda d: d.bind_procedure(
        ProcedureContract("c", ()), _raise(OSError("trace store down")))),
     "procedure_trace_unavailable"),
], ids=["policy", "capability", "effect", "procedure"])
def test_runtime_refusals_carry_the_execution_identity(events, make, reason) -> None:
    """Refused after the lease verified: the result names the execution it
    refused, and there is no execution context to report a check for."""
    d = make()
    result = _dispatch(d, _no_actor_lease(), actor_identity=None)
    _assert_refused(result, events, reason=reason, level=logging.WARNING,
                    payload=_refusal_payload(reason), execution_id=JTI)


def test_a_runtime_identity_mismatch_is_a_runtime_refusal(events) -> None:
    lease = _lease(runtime_identity_hash="f" * 64)
    _assert_refused(_dispatch(_dispatcher(), lease), events,
                    reason="runtime_identity_mismatch", level=logging.WARNING,
                    payload=_refusal_payload("runtime_identity_mismatch"),
                    execution_id=JTI)


def test_a_plan_bound_lease_without_its_plan_is_a_runtime_refusal(events) -> None:
    from remora.governance.plan_binding import PlanBinding

    plan = PlanBinding.capture("plan-1", ["workorder/WO-1"], ["workorder/WO-1"],
                               lambda resource: "7")
    _assert_refused(_dispatch(_dispatcher(), _lease(plan=plan)), events,
                    reason="plan_binding_required", level=logging.WARNING,
                    payload=_refusal_payload("plan_binding_required"), execution_id=JTI)


def test_an_unobservable_enforced_surface_is_a_runtime_refusal(events) -> None:
    d = _dispatcher()
    d.bind_surface_observer(_raise(OSError("no surface")), enforce=True)
    _assert_refused(_dispatch(d, _lease(surface_digest="s-1")), events,
                    reason="surface_unobservable", level=logging.WARNING,
                    payload=_refusal_payload("surface_unobservable"), execution_id=JTI)


def test_a_procedure_violation_depends_on_the_arguments(events) -> None:
    """The procedure sees the call's arguments, not an empty step: the
    forbidden step here is ``wo_close`` on WO-1 only."""
    contract = ProcedureContract("no_wo1", (absence(StepPattern(TOOL, {"id": "WO-1"})),))
    d = _dispatcher()
    d.bind_procedure(contract, lambda lease: [])
    _assert_refused(_dispatch(d, _lease()), events, reason="procedure_violation",
                    level=logging.WARNING,
                    payload=_refusal_payload("procedure_violation"), execution_id=JTI)

    other = {"id": "WO-2"}
    assert _dispatch(d, _lease(arguments=other), other).executed is True


# ── IFC-06: the invocation form goes through the same runtime checks ───────
#
# A resolved handle can carry a value the wire form could not name. The
# dispatcher therefore runs the capability, effect and procedure checks a
# second time over the invocation form. The 2026-11-04 sweep found that
# second pass unpinned: each of its arguments could be replaced by None, and
# the procedure check could be skipped, without a test noticing.


def test_a_procedure_violated_only_by_the_invocation_form_refuses(events) -> None:
    contract = ProcedureContract("no_wo1", (absence(StepPattern(TOOL, {"id": "WO-1"})),))
    d = _dispatcher()
    d.bind_procedure(contract, lambda lease: [])
    wire = {"id": "WO-2"}
    _assert_refused(_dispatch(d, _lease(arguments=wire), wire, invocation_arguments={"id": "WO-1"}),
                    events, reason="procedure_violation", level=logging.WARNING,
                    payload=_refusal_payload("procedure_violation"), execution_id=JTI)
    assert _dispatch(d, _lease(arguments=wire), wire,
                     invocation_arguments={"id": "WO-3"}).executed is True


def test_a_capability_constraint_violated_only_by_the_invocation_form_refuses(events) -> None:
    cs = _capability_set(constraints=ONLY_ID)
    lease = _lease(capability_set=cs)
    result = _dispatch(_dispatcher(), lease, ARGS, capability_set=cs,
                       invocation_arguments={"id": "WO-1", "amount": 5})
    _assert_refused(result, events, reason="capability_argument_mismatch",
                    level=logging.WARNING,
                    payload=_refusal_payload("capability_argument_mismatch"), execution_id=JTI)
    assert _dispatch(_dispatcher(), _lease(capability_set=cs), ARGS, capability_set=cs,
                     invocation_arguments={"id": "WO-1"}).executed is True


def test_an_effect_refused_only_for_the_invocation_form_refuses(events) -> None:
    """The resolver sees the invocation form, and refuses it on its value."""
    from remora.enforcement.resolved_effect import UnresolvedReference

    class Picky:
        def resolve(self, tool_name: str, arguments: Any, target_environment: str) -> ResolvedEffect:
            if arguments.get("id") == "WO-9":
                raise UnresolvedReference("WO-9 names no work order")
            return ResolvedEffect(tool_name, "impl/v1", f"env:{target_environment}", "write")

    d = _dispatcher()
    d.bind_effect_resolver(Picky())
    result = _dispatch(d, _lease(), ARGS, invocation_arguments={"id": "WO-9"})
    assert result.executed is False
    assert result.refusal_reason == "unresolved_reference"
    assert _dispatch(d, _lease(), ARGS, invocation_arguments={"id": "WO-2"}).executed is True


def test_the_caller_cannot_reach_nested_invocation_arguments_after_dispatch_began() -> None:
    """The invocation form is copied as deeply as the wire form."""
    meta = {"note": "resolved"}
    received: list[Any] = []
    d = _dispatcher(received.append)
    d.bind_effect_resolver(_Resolver(lambda _private: meta.update(note="tampered")))
    result = _dispatch(d, _lease(arguments={"id": "WO-1", "meta": {"note": "wire"}}),
                       {"id": "WO-1", "meta": {"note": "wire"}},
                       invocation_arguments={"id": "WO-1", "meta": meta})
    assert result.executed is True, result.refusal_reason
    assert received == [{"id": "WO-1", "meta": {"note": "resolved"}}]


def test_the_invocation_form_resolves_to_the_effect_the_lease_signed() -> None:
    """The resolver sees the invocation form under the lease's tool and
    target; the effect it names must be the one the authority bound."""
    asked: list[tuple[str, Any, str]] = []

    class Resolver:
        def resolve(self, tool_name: str, arguments: Any, target_environment: str) -> ResolvedEffect:
            asked.append((tool_name, dict(arguments), target_environment))
            return ResolvedEffect(tool_name, "impl/v1", f"env:{target_environment}", "write")

    effect = ResolvedEffect(TOOL, "impl/v1", f"env:{TARGET}", "write")
    d = _dispatcher()
    d.bind_effect_resolver(Resolver())
    result = _dispatch(d, _lease(resolved_effect=effect), ARGS,
                       invocation_arguments={"id": "WO-1", "note": "resolved"})
    assert result.executed is True, result.refusal_reason
    assert asked == [(TOOL, ARGS, TARGET), (TOOL, {"id": "WO-1", "note": "resolved"}, TARGET)]
    # An absent target is the empty string in the second pass as in the first.
    asked.clear()
    bare = ResolvedEffect(TOOL, "impl/v1", "env:", "write")
    result = _dispatch(d, _lease(target="", resolved_effect=bare), ARGS, target_environment=None,
                       invocation_arguments={"id": "WO-1", "note": "resolved"})
    assert result.executed is True, result.refusal_reason
    assert asked == [(TOOL, ARGS, ""), (TOOL, {"id": "WO-1", "note": "resolved"}, "")]


# ── capability sets: every argument of the check is load-bearing ───────────


def test_a_call_inside_its_capability_set_executes() -> None:
    """Tool, tenant, environment, the dispatch clock and the arguments all
    reach the capability check; dropping any of them refuses this call."""
    cs = _capability_set(constraints=ONLY_ID)
    result = _dispatch(_dispatcher(), _lease(capability_set=cs), capability_set=cs)
    assert result.executed is True, result.refusal_reason


@pytest.mark.parametrize("cs_kwargs, call, reason", [
    (dict(tools=("other_tool",)), {}, "capability_not_allowed"),
    (dict(environment="prod"), {}, "capability_environment_mismatch"),
    (dict(constraints=ONLY_ID), dict(arguments={"id": "WO-1", "amount": 5}),
     "capability_argument_mismatch"),
], ids=["tool", "environment", "arguments"])
def test_a_call_outside_its_capability_set_refuses(events, cs_kwargs, call, reason) -> None:
    cs = _capability_set(**cs_kwargs)
    arguments = call.get("arguments", ARGS)
    lease = _lease(capability_set=cs, arguments=arguments)
    result = _dispatch(_dispatcher(), lease, arguments, capability_set=cs)
    _assert_refused(result, events, reason=reason, level=logging.WARNING,
                    payload=_refusal_payload(reason), execution_id=JTI)


def test_a_capability_set_from_another_tenant_refuses() -> None:
    cs = dataclasses.replace(_capability_set(), tenant_id="globex")
    result = _dispatch(_dispatcher(), _lease(capability_set=cs), capability_set=cs)
    assert result.refusal_reason == "capability_tenant_mismatch"


def test_the_capability_check_sees_the_target_the_lease_was_verified_against() -> None:
    """An absent target is the empty environment everywhere in dispatch, the
    capability check included; it is never a placeholder value."""
    seen: list[str] = []

    @dataclasses.dataclass(frozen=True)
    class Recording(EffectiveCapabilitySet):
        def check(self, tool_name, *, principal_id, tenant_id, environment, now):
            seen.append(environment)
            return super().check(tool_name, principal_id=principal_id,
                                 tenant_id=tenant_id, environment=environment, now=now)

    cs = _capability_set(cls=Recording)
    lease = _lease(capability_set=cs, target="")
    result = _dispatch(_dispatcher(), lease, capability_set=cs, target_environment=None)
    assert seen == [""]
    assert result.refusal_reason == "capability_environment_mismatch"


#: A scope whose condition is a fact only the deployment's state reader knows.
OPEN_ORDER = {TOOL: {"conditions": [{"argument": "id", "equals_state": "wo.open_id"}]}}


def test_a_state_condition_is_read_through_the_bound_reader() -> None:
    """The dispatcher hands its trusted-state reader to the capability check;
    without it a state condition is unverifiable and refuses."""
    reads: list[tuple[str, Any]] = []
    cs = _capability_set(constraints=OPEN_ORDER)
    d = _dispatcher()

    def reader(source: str, args: Any) -> str:
        reads.append((source, args))
        return "WO-1"

    d.bind_capability_state(reader)
    result = _dispatch(d, _lease(capability_set=cs), capability_set=cs)
    assert result.executed is True, result.refusal_reason
    assert reads == [("wo.open_id", ARGS)]


def test_a_revoked_set_refuses_at_dispatch(events) -> None:
    """Revocation is read from the bound epoch source for the presented set."""
    cs = _capability_set()
    source = _Revocations()
    source.revoked_ids.add(cs.capability_set_id)
    d = _dispatcher()
    d.bind_capability_epochs(source)
    _assert_refused(_dispatch(d, _lease(capability_set=cs), capability_set=cs), events,
                    reason="capability_revoked", level=logging.WARNING,
                    payload=_refusal_payload("capability_revoked"), execution_id=JTI)


def test_a_current_set_under_a_bound_epoch_source_executes() -> None:
    """A source that answers and revokes nothing lets the call run; the
    revocation check must be asked about the set, not about nothing."""
    cs = _capability_set()
    d = _dispatcher()
    d.bind_capability_epochs(_Revocations())
    result = _dispatch(d, _lease(capability_set=cs), capability_set=cs)
    assert result.executed is True, result.refusal_reason


# ── mediation ──────────────────────────────────────────────────────────────


def test_a_mediated_tool_receives_the_arguments_and_the_real_mediator() -> None:
    from remora.enforcement.capability_mediator import CapabilityMediator

    seen: dict[str, Any] = {}

    def tool(arguments: Any, mediator: Any) -> str:
        seen["arguments"], seen["mediator"] = arguments, mediator
        return "done"

    cs = _capability_set()
    lease = _lease(capability_set=cs)
    d = _dispatcher(tool, mediated=True, require_downstream_declaration=False)
    result = _dispatch(d, lease, capability_set=cs)
    assert result.executed is True, result.refusal_reason
    assert result.result == "done"
    assert seen["arguments"] == ARGS
    assert isinstance(seen["mediator"], CapabilityMediator)
    assert seen["mediator"].context.parent_lease_digest == lease.digest()
    # A lease naming no runtime gives the context none, not a placeholder.
    assert seen["mediator"].context.runtime_identity_hash == ""
    assert result.nested_effects["mediated"] is True
    assert result.nested_effects["count"] == 0
    assert result.effect_graph is not None
    assert result.nested_effects["graph_sha256"] == result.effect_graph.digest()


def test_a_mediated_tool_without_a_capability_set_refuses(events) -> None:
    calls: list[Any] = []
    d = _dispatcher(lambda a, m: calls.append(a), mediated=True,
                    require_downstream_declaration=False)
    _assert_refused(_dispatch(d, _lease()), events, reason="capability_set_required",
                    level=logging.WARNING,
                    payload=_refusal_payload("capability_set_required"))
    assert calls == []


def test_a_mediated_tool_needs_the_set_bound_into_the_lease(events) -> None:
    """A set presented at dispatch is not enough: effect authority derives
    from the set the lease signed, so a lease that signed none refuses."""
    calls: list[Any] = []
    d = _dispatcher(lambda a, m: calls.append(a), mediated=True,
                    require_downstream_declaration=False)
    result = _dispatch(d, _lease(), capability_set=_capability_set())
    _assert_refused(result, events, reason="capability_set_required",
                    level=logging.WARNING,
                    payload=_refusal_payload("capability_set_required"))
    assert calls == []


REPORT = "database://reporting/monthly"
TASK = TaskIdentity(context_id="ctx-m", task_id="task-m")
SPEC = ("spec-m", 3)


def _ceiling(tool: str = TOOL) -> Any:
    from remora.capabilities.ceiling import DownstreamCeiling

    return DownstreamCeiling.from_dict(tool, [{
        "capability": "database.read", "resources": ["database://reporting/*"],
        "purpose": "read the monthly report"}])


def _reading_tool(seen: dict[str, Any]) -> Callable[[Any, Any], str]:
    """A mediated tool that asks for one read and keeps what it got."""
    def tool(arguments: Any, mediator: Any) -> str:
        seen["mediator"] = mediator
        seen["effect"] = mediator.invoke("database.read", REPORT, {"query": "q"})
        return "done"

    return tool


def _mediated(seen: dict[str, Any], *, ceilings_asked: list[Any] | None = None,
              **kwargs: Any) -> GovernedToolDispatcher:
    """A dispatcher for a mediated tool with a declared ceiling and a local
    executor whose answer names it as local."""
    d = _dispatcher(_reading_tool(seen), mediated=True, **kwargs)
    asked = ceilings_asked if ceilings_asked is not None else []

    def ceilings(name: str) -> Any:
        asked.append(name)
        return _ceiling() if name == TOOL else None

    d.bind_downstream_ceilings(ceilings)
    d.bind_effect_executors({"database.read": lambda resource, args: ("local", resource,
                                                                      dict(args))})
    return d


def _live() -> tuple[EffectiveCapabilitySet, datetime]:
    """A set valid around the wall clock, and that instant.

    Mediated tests run on the real clock: the mediator checks each effect
    against ``datetime.now``, so effect authority derived at the fixed NOW
    (sixty seconds long) has expired by the time an effect asks.
    """
    current = datetime.now(UTC)
    cs = dataclasses.replace(_capability_set(),
                             issued_at=(current - timedelta(minutes=5)).isoformat(),
                             expires_at=(current + timedelta(minutes=5)).isoformat())
    return cs, current


def _fully_bound_lease(cs: EffectiveCapabilitySet, issued_at: datetime, runtime: str,
                       ) -> tuple[ExecutionLease, ResolvedEffect]:
    effect = ResolvedEffect(TOOL, "impl/v1", f"env:{TARGET}", "write")
    lease = _lease(capability_set=cs, task_identity=TASK, resolved_effect=effect,
                   toolspec_hash=SPEC[0], toolspec_version=SPEC[1],
                   runtime_identity_hash=runtime, issued_at=issued_at)
    return lease, effect


@pytest.fixture()
def declared_runtime(monkeypatch) -> Iterator[str]:
    """A process that declares its runtime, so a lease can bind a real one."""
    monkeypatch.setenv("REMORA_RUNTIME_KIND", "test-worker")
    monkeypatch.setenv("REMORA_DEPLOYMENT_GENERATION", "generation-1")
    reset_runtime_identity()
    runtime = current_runtime_identity_hash()
    assert runtime
    yield runtime
    reset_runtime_identity()


def test_the_mediator_carries_every_identity_the_lease_signed(
        events, declared_runtime: str) -> None:
    """The context a mediated effect runs under is built from the verified
    lease, field by field: the proposal, bundle, spec, parent lease, task and
    runtime. Each one is what an effect record and the effect domain key
    on; a blank or swapped field attributes the effect to something else."""
    from remora.enforcement.capability_mediator import EffectState
    from remora.enforcement.execution_context import ExecutionContext

    seen: dict[str, Any] = {}
    asked: list[Any] = []
    cs, current = _live()
    lease, effect = _fully_bound_lease(cs, current, declared_runtime)
    d = _mediated(seen, ceilings_asked=asked)
    d.bind_toolspec_identity(lambda name: SPEC)
    d.bind_effect_resolver(_Resolver(lambda _args: None))
    result = _dispatch(d, lease, capability_set=cs, task_identity=TASK,
                       now=current.isoformat())
    assert result.executed is True, result.refusal_reason

    context = seen["mediator"].context
    assert context == ExecutionContext(
        execution_id=context.execution_id, proposal_id=PROPOSAL, tenant_id=TENANT,
        principal_id=ACTOR, target_environment=TARGET, context_id="ctx-m",
        task_id="task-m", tool_name=TOOL, toolspec_hash="spec-m",
        policy_bundle_hash=BUNDLE, capability_digest=cs.digest,
        runtime_identity_hash=declared_runtime, parent_lease_digest=lease.digest())
    # The declared ceiling was asked for this tool and granted the read.
    assert asked == [TOOL]
    assert seen["effect"].state is EffectState.EXECUTED
    assert seen["effect"].refusal is None
    assert seen["effect"].result == ("local", REPORT, {"query": "q"})
    # The graph hangs off the effect the lease resolved to.
    assert result.effect_graph.root_effect_digest == effect.digest()
    # No effect domain is bound, so there is none to close.
    assert events("dispatch.effect_domain_close_failed") == []


class _EffectDomain:
    """A remote effect domain double: hands out executors, records the close."""

    def __init__(self) -> None:
        self.asked: list[tuple[Any, Any, list[str]]] = []
        self.closed: list[Any] = []

    def executors_for(self, lease: Any, capability_set: Any,
                      capabilities: list[str]) -> dict[str, Callable[..., Any]]:
        self.asked.append((lease, capability_set, capabilities))
        return {c: (lambda resource, args: ("remote", resource, dict(args)))
                for c in capabilities}

    def close(self, lease: Any) -> None:
        self.closed.append(lease)


def test_a_bound_effect_domain_runs_the_effects_and_is_closed() -> None:
    """With an effect domain bound, the local executors are not used: the
    domain is asked for executors for this lease, this set and the ceiling's
    capabilities, and is told when the execution ends."""
    seen: dict[str, Any] = {}
    cs, current = _live()
    lease = _lease(capability_set=cs, issued_at=current)
    d = _mediated(seen)
    domain = _EffectDomain()
    d.bind_effect_domain(domain)
    result = _dispatch(d, lease, capability_set=cs, now=current.isoformat())
    assert result.executed is True, result.refusal_reason
    assert seen["effect"].result == ("remote", REPORT, {"query": "q"})
    assert domain.asked == [(lease, cs, ["database.read"])]
    assert domain.asked[0][0] is lease and domain.asked[0][1] is cs
    assert domain.closed == [lease]


def test_a_mediated_dispatch_without_a_clock_reads_utc_now() -> None:
    """``now`` is optional; without it the effect authority is derived at the
    current UTC instant, inside a set valid now."""
    from remora.enforcement.capability_mediator import EffectState

    cs, current = _live()
    seen: dict[str, Any] = {}
    lease = _lease(capability_set=cs, issued_at=current - timedelta(seconds=5))
    result = _dispatch(_mediated(seen), lease, capability_set=cs, now=None)
    assert result.executed is True, result.refusal_reason
    assert seen["effect"].state is EffectState.EXECUTED


def test_a_set_revoked_while_the_tool_runs_refuses_its_next_effect() -> None:
    """The mediator re-reads revocation at every effect, so a set revoked
    after dispatch began stops the effects still to come (Q8.6 cascade)."""
    from remora.enforcement.capability_mediator import EffectState

    cs, current = _live()
    source = _Revocations()
    seen: dict[str, Any] = {}

    def tool(arguments: Any, mediator: Any) -> str:
        source.revoked_ids.add(cs.capability_set_id)
        seen["effect"] = mediator.invoke("database.read", REPORT, {"query": "q"})
        return "done"

    d = _mediated({})
    d.register(TOOL, tool, mediated=True)
    d.bind_capability_epochs(source)
    result = _dispatch(d, _lease(capability_set=cs, issued_at=current), capability_set=cs,
                       now=current.isoformat())
    assert result.executed is True, result.refusal_reason
    assert seen["effect"].state is EffectState.REFUSED
    assert seen["effect"].refusal == "capability_revoked"


# ── the final hop: the call that runs is the call that verified ─────────────


def test_a_hook_rewriting_the_private_arguments_refuses(events) -> None:
    calls: list[Any] = []
    d = _dispatcher(calls.append)
    d.bind_effect_resolver(_Resolver(lambda args: args.update(id="WO-2")))
    _assert_refused(_dispatch(d, _lease()), events,
                    reason="tool_args_changed_after_verify", level=logging.ERROR,
                    payload=_refusal_payload("tool_args_changed_after_verify"))
    assert calls == []


def test_re_registering_the_same_callable_during_dispatch_refuses(events) -> None:
    """Same object, new generation: the registry moved, and identity of the
    callable alone must not hide that."""
    calls: list[Any] = []
    d = _dispatcher(calls.append)
    fn = d._tools[TOOL]
    d.bind_effect_resolver(_Resolver(lambda args: d.register(TOOL, fn)))
    _assert_refused(_dispatch(d, _lease()), events, reason="tool_registry_changed",
                    level=logging.ERROR,
                    payload=_refusal_payload("tool_registry_changed"))
    assert calls == []


def test_the_caller_cannot_reach_nested_arguments_after_dispatch_began() -> None:
    """The private copy is deep. A caller mutating its own nested object while
    dispatch runs (here from inside a hook) changes nothing that executes."""
    meta = {"note": "verified"}
    arguments = {"id": "WO-1", "meta": meta}
    received: list[Any] = []
    d = _dispatcher(received.append)
    d.bind_effect_resolver(_Resolver(lambda _private: meta.update(note="tampered")))
    result = _dispatch(d, _lease(arguments={"id": "WO-1", "meta": {"note": "verified"}}),
                       arguments)
    assert result.executed is True, result.refusal_reason
    assert received == [{"id": "WO-1", "meta": {"note": "verified"}}]


# ── the independent recorder ───────────────────────────────────────────────


def _recorded(d: GovernedToolDispatcher, recorder: _Recorder) -> None:
    d.bind_recorder(recorder, lambda tool: tool == TOOL)  # type: ignore[arg-type]


def test_an_unavailable_recorder_refuses_before_the_nonce(events) -> None:
    d = _dispatcher()
    _recorded(d, _Recorder(fail_phase="intent"))
    lease = _lease()
    _assert_refused(_dispatch(d, lease), events, reason="recorder_unavailable",
                    level=logging.ERROR,
                    payload=_refusal_payload("recorder_unavailable", detail="recorder down"))
    assert lease.nonce not in d._ledger._consumed


def _intent(lease: ExecutionLease) -> dict[str, Any]:
    return {"phase": "intent", "tenant_id": TENANT, "tool_name": TOOL,
            "proposal_id": PROPOSAL, "grant_jti": JTI,
            "tool_args_hash": lease.tool_args_hash, "nonce": lease.nonce}


def test_the_recorder_receives_intent_then_executed() -> None:
    d = _dispatcher()
    recorder = _Recorder()
    _recorded(d, recorder)
    lease = _lease()
    result = _dispatch(d, lease)
    assert result.executed is True and result.recorder_seq == 0
    assert recorder.entries == [
        ("dispatch", _intent(lease)),
        ("dispatch", {**_intent(lease), "phase": "outcome", "intent_seq": 0,
                      "outcome": "executed"}),
    ]


def test_the_recorder_receives_state_unknown_when_the_tool_raises() -> None:
    d = _dispatcher(_raise(OSError("db down")))
    recorder = _Recorder()
    _recorded(d, recorder)
    lease = _lease()
    with pytest.raises(ToolExecutionStateUnknown):
        _dispatch(d, lease)
    assert recorder.entries == [
        ("dispatch", _intent(lease)),
        ("dispatch", {**_intent(lease), "phase": "outcome", "intent_seq": 0,
                      "outcome": "state_unknown"}),
    ]


# ── single use: the in-process ledger and the durable store ────────────────


def test_two_leases_for_the_same_call_each_execute_once() -> None:
    """The ledger is keyed by each lease's own nonce, not by the call."""
    d = _dispatcher()
    first, second = _lease(), _lease()
    assert first.nonce != second.nonce
    assert _dispatch(d, first).executed is True
    assert _dispatch(d, second).executed is True
    assert _dispatch(d, first).refusal_reason == "nonce_already_consumed"


def test_an_in_process_replay_is_a_warning(events) -> None:
    d = _dispatcher()
    lease = _lease()
    assert _dispatch(d, lease).executed is True
    _assert_refused(_dispatch(d, lease), events, reason="nonce_already_consumed",
                    level=logging.WARNING,
                    payload=_refusal_payload("nonce_already_consumed"))


def test_a_replay_on_a_ledger_without_failure_is_a_plain_replay(events) -> None:
    """``failure`` is optional on a ledger; its absence means no failure was
    recorded, not a crash and not a failed execution."""
    d = _dispatcher(ledger=_BareLedger())  # type: ignore[arg-type]
    lease = _lease()
    assert _dispatch(d, lease).executed is True
    _assert_refused(_dispatch(d, lease), events, reason="nonce_already_consumed",
                    level=logging.WARNING,
                    payload=_refusal_payload("nonce_already_consumed"))


def test_an_unavailable_nonce_store_is_an_error(events) -> None:
    d = _dispatcher(nonce_store=_Store(down=True))  # type: ignore[arg-type]
    _assert_refused(_dispatch(d, _lease()), events, reason="nonce_store_unavailable",
                    level=logging.ERROR,
                    payload=_refusal_payload("nonce_store_unavailable", detail="store down"))


def test_a_durable_replay_is_a_warning(events) -> None:
    d = _dispatcher(nonce_store=_Store())  # type: ignore[arg-type]
    lease = _lease()
    assert _dispatch(d, lease).executed is True
    _assert_refused(_dispatch(d, lease), events, reason="nonce_already_consumed",
                    level=logging.WARNING,
                    payload=_refusal_payload("nonce_already_consumed"))


def test_a_durable_replay_on_a_ledger_without_failure_is_a_plain_replay(events) -> None:
    d = _dispatcher(nonce_store=_Store(), ledger=_BareLedger())  # type: ignore[arg-type]
    lease = _lease()
    assert _dispatch(d, lease).executed is True
    _assert_refused(_dispatch(d, lease), events, reason="nonce_already_consumed",
                    level=logging.WARNING,
                    payload=_refusal_payload("nonce_already_consumed"))


def test_a_durable_retry_after_a_failed_execution_names_the_failure(events) -> None:
    d = _dispatcher(_raise(OSError("db down")),
                    nonce_store=_Store())  # type: ignore[arg-type]
    lease = _lease()
    with pytest.raises(ToolExecutionStateUnknown):
        _dispatch(d, lease)
    _assert_refused(_dispatch(d, lease), events,
                    reason="nonce_consumed_by_failed_execution", level=logging.WARNING,
                    payload=_refusal_payload("nonce_consumed_by_failed_execution"))


# ── terminal outcomes ──────────────────────────────────────────────────────


def test_an_unmediated_success_reports_no_check_and_no_graph() -> None:
    result = _dispatch(_dispatcher(), _lease())
    assert _identity(result) == (True, True, None, PROPOSAL, "", JTI, None)
    assert result.nested_effects == {"mediated": False, "count": 0, "settled": True}
    assert result.effect_graph is None


def test_state_unknown_carries_the_execution_identity() -> None:
    d = _dispatcher(_raise(OSError("db down")))
    with pytest.raises(ToolExecutionStateUnknown) as info:
        _dispatch(d, _lease())
    unknown = info.value
    assert str(unknown) == ("Tool execution failed, nonce burned and state "
                            "unknown/failed: db down")
    assert (unknown.proposal_id, unknown.tenant_id, unknown.tool_name) == (
        PROPOSAL, TENANT, TOOL)
    assert unknown.execution_id == JTI
    assert unknown.execution_context_hash == ""
    assert unknown.dispatch_check is None


# ── defaults: an absent tenant and target are the empty string ─────────────


def test_a_lease_for_no_tenant_and_no_target_dispatches_with_neither() -> None:
    lease = _lease(tenant="", target="")
    result = _dispatcher().dispatch(lease, TOOL, ARGS, actor_identity=ACTOR,
                                    now=NOW.isoformat())
    assert result.executed is True, result.refusal_reason


def test_the_effect_resolver_sees_an_absent_target_as_empty() -> None:
    resolver = ClosedWorldResolver(tools={TOOL: ("impl/v1", "write")}, resources={},
                                   resource_argument={})
    lease = _lease(target="", resolved_effect=resolver.resolve(TOOL, ARGS, ""))
    d = _dispatcher()
    d.bind_effect_resolver(resolver)
    result = _dispatch(d, lease, target_environment=None)
    assert result.executed is True, result.refusal_reason


# ── execution context ──────────────────────────────────────────────────────


@pytest.fixture()
def provider(monkeypatch) -> Iterator[Provider]:
    monkeypatch.setenv("REMORA_RUNTIME_KIND", "test-worker")
    monkeypatch.setenv("REMORA_DEPLOYMENT_GENERATION", "generation-1")
    reset_runtime_identity()
    yield Provider()
    reset_runtime_identity()


def _context(provider: Provider) -> ExecutionContextV1:
    return provider.capture(
        proposal_id=PROPOSAL, tenant=TENANT, principal=ACTOR,
        tool_call_hash=canonical_tool_call_hash(name=TOOL, arguments=ARGS,
                                                tenant=TENANT, target=TARGET))


def _check(runtime: str, *, result: str, checked_at: str = NOW.isoformat(),
           **extra: Any) -> dict[str, Any]:
    return {"expected_runtime_identity_hash": runtime,
            "observed_runtime_identity_hash": current_runtime_identity_hash(),
            "checked_at": checked_at, "result": result, **extra}


def test_a_matched_context_reports_the_full_dispatch_check(provider) -> None:
    ctx = _context(provider)
    lease = _lease(execution_context=ctx)
    d = _dispatcher(execution_context_provider=provider)
    result = _dispatch(d, lease, execution_context=ctx)
    runtime = current_runtime_identity_hash()
    assert _identity(result) == (
        True, True, None, PROPOSAL, ctx.digest(), JTI,
        _check(runtime, result="matched", expected_build_provenance_digest=BUILD,
               observed_build_provenance_digest=BUILD))


def test_a_missing_context_refuses_with_the_check(provider, events) -> None:
    ctx = _context(provider)
    lease = _lease(execution_context=ctx)
    d = _dispatcher(execution_context_provider=provider)
    runtime = current_runtime_identity_hash()
    _assert_refused(
        _dispatch(d, lease), events, reason="execution_context_missing",
        level=logging.WARNING,
        payload=_refusal_payload("execution_context_missing", grant=False),
        execution_context_hash=ctx.digest(), execution_id=JTI,
        dispatch_check=_check(runtime, result="refused",
                              reason="execution_context_missing"))


def test_a_build_mismatch_reports_both_builds(provider, events) -> None:
    ctx = _context(provider)
    lease = _lease(execution_context=ctx)
    provider.build = "b" * 64
    d = _dispatcher(execution_context_provider=provider)
    runtime = current_runtime_identity_hash()
    _assert_refused(
        _dispatch(d, lease, execution_context=ctx), events,
        reason="build_provenance_mismatch", level=logging.WARNING,
        payload=_refusal_payload("build_provenance_mismatch", grant=False),
        execution_context_hash=ctx.digest(), execution_id=JTI,
        dispatch_check=_check(runtime, result="refused",
                              expected_build_provenance_digest=BUILD,
                              observed_build_provenance_digest="b" * 64,
                              reason="build_provenance_mismatch"))


def test_a_context_presented_for_a_lease_bound_to_none_refuses(provider, events) -> None:
    """Either side naming a context is enough to compare them. A lease with no
    context hash and a call that brings one do not match."""
    ctx = _context(provider)
    calls: list[Any] = []
    d = _dispatcher(calls.append, execution_context_provider=provider)
    _assert_refused(
        _dispatch(d, _lease(), execution_context=ctx), events,
        reason="execution_context_hash_mismatch", level=logging.WARNING,
        payload=_refusal_payload("execution_context_hash_mismatch", grant=False),
        execution_id=JTI,
        dispatch_check=_check("", result="refused",
                              reason="execution_context_hash_mismatch"))
    assert calls == []


def test_a_runtime_refusal_after_a_matched_context_keeps_the_check(provider, events) -> None:
    ctx = _context(provider)
    lease = _lease(execution_context=ctx)
    d = _dispatcher(execution_context_provider=provider, require_capability_set=True)
    runtime = current_runtime_identity_hash()
    _assert_refused(
        _dispatch(d, lease, execution_context=ctx), events,
        reason="capability_set_required", level=logging.WARNING,
        payload=_refusal_payload("capability_set_required"),
        execution_context_hash=ctx.digest(), execution_id=JTI,
        dispatch_check=_check(runtime, result="matched",
                              expected_build_provenance_digest=BUILD,
                              observed_build_provenance_digest=BUILD))


def test_a_check_without_a_dispatch_clock_is_stamped_in_utc(provider) -> None:
    ctx = _context(provider)
    lease = _lease(execution_context=ctx, issued_at=datetime.now(UTC))
    d = _dispatcher(execution_context_provider=provider)
    result = _dispatch(d, lease, execution_context=ctx, now=None)
    assert result.executed is True, result.refusal_reason
    assert result.dispatch_check is not None
    stamped = datetime.fromisoformat(result.dispatch_check["checked_at"])
    assert stamped.utcoffset() == timedelta(0)


def test_state_unknown_after_a_matched_context_keeps_the_check(provider) -> None:
    ctx = _context(provider)
    lease = _lease(execution_context=ctx)
    d = _dispatcher(_raise(OSError("db down")), execution_context_provider=provider)
    with pytest.raises(ToolExecutionStateUnknown) as info:
        _dispatch(d, lease, execution_context=ctx)
    assert info.value.execution_context_hash == ctx.digest()
    assert info.value.execution_id == JTI
    assert info.value.dispatch_check == _check(
        current_runtime_identity_hash(), result="matched",
        expected_build_provenance_digest=BUILD, observed_build_provenance_digest=BUILD)

