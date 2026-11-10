# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Plan-bound flow control as an AgentDojo defence (E_PLAN_WS1, SAP v8 §14 G1′).

E_IFC_WS1 has one agent that reads tool output and then chooses its calls, so
every value it writes after an untrusted read is untrusted, and so is the
choice of call (NEGATIVE_RESULTS §100). This arm separates the two. Control is
fixed first: a :class:`Plan` is written from the user task before any tool
runs, and it names each call and every argument the task itself supplies.
Data comes later: an argument the plan marks :data:`DATA` is filled at run
time from what was read.

The gate is :class:`~experiments.control_eval.remora_ifc.RemoraIfcGate` with
WS1, the same declaration file, labels, resolvers and engine hard floor, and
two changes.

1. Control flow. A call executes only as the next step of the plan: same tool,
   same argument names, and every literal argument equal to the plan's value
   (compared as canonical JSON, so ``1`` is not ``True``). Anything else is
   refused and leaves the cursor where it was. A matching call consumes its
   step whether or not the flow check then lets it run, so a later step can
   run after an earlier one was refused. SAP v8 §14 did not state this
   choice. ``halt_on_refusal`` is the other one, added after the first G1′
   run and outside the gate: once the flow check refuses a planned step,
   every later call of the trajectory is refused.
2. Data flow. An UNTRUSTED value in a ``DATA`` argument is not an integrity
   violation when :func:`relaxable_fields` lists the argument: it is declared
   payload, the recipients rule does not read it, its declared kind is
   ``text``, and the tool is not critical tier. Every other
   ``integrity_required`` argument is checked as in E_IFC_WS1: the arguments
   the recipients rule reads, non-text arguments, and every argument of a
   critical-tier tool. The relaxable set is wider than message bodies. On the
   frozen declaration it also holds ``update_user_info``'s four fields,
   ``invite_user_to_slack.user``, a calendar event's title, description and
   location, and ``send_email.attachments``.

Labels never come from the plan. A literal that is not in the task text is
labelled like any other value, so a plan cannot make a value trusted; it can
only pin it.

What the arm leaves open: the content of a relaxed payload is whatever the
run-time reader produced, so an injection can still change what a planned
write says to the recipient the user named. The arm inherits E_IFC_WS1's
labels with their faults: a number counts as trusted when the task text
holds it anywhere, a file name included, and a resolver proves any earlier
counterparty (NEGATIVE_RESULTS §100, follow-up). The plan here is supplied to
the gate; :func:`oracle_plan` builds it from ground-truth calls for the
no-model replay, and nothing in this module shows that a model can write it
without seeing tool output. For that reason the arm is not in the study
runner's arm registry: the G1′ replay builds it directly.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from experiments.control_eval.policies import ProposedCall, Verdict
from experiments.control_eval.remora_ifc import (
    RemoraIfcGate,
    ToolDeclaration,
    _leaves,
    value_trusted,
)
from remora.flow.check import FlowVerdict
from remora.flow.label import Integrity, Label

__all__ = [
    "DATA",
    "Plan",
    "PlanBoundGate",
    "PlanStep",
    "oracle_plan",
    "relaxable_fields",
]

_DIGEST_DOMAIN: Final = b"REMORA/CONTROL-EVAL/PLAN/v1\x00"


class _Data:
    """The mark for an argument whose value is not known when the plan is written."""

    _instance: _Data | None = None

    def __new__(cls) -> _Data:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "DATA"


DATA: Final = _Data()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=str)


@dataclass(frozen=True)
class PlanStep:
    tool: str
    #: ``(argument name, literal value or DATA)``, sorted by name.
    args: tuple[tuple[str, Any], ...] = ()

    def data_fields(self) -> frozenset[str]:
        return frozenset(name for name, value in self.args if value is DATA)

    def matches(self, name: str, args: Mapping[str, Any]) -> bool:
        if name != self.tool or set(args) != {n for n, _ in self.args}:
            return False
        return all(value is DATA or _canonical(args[field]) == _canonical(value)
                   for field, value in self.args)

    def to_json(self) -> dict[str, Any]:
        return {"tool": self.tool,
                "args": [{"name": n, "data": True} if v is DATA else {"name": n, "literal": v}
                         for n, v in self.args]}


@dataclass(frozen=True)
class Plan:
    steps: tuple[PlanStep, ...]

    @property
    def digest(self) -> str:
        body = _canonical([step.to_json() for step in self.steps]).encode("utf-8")
        return hashlib.sha256(_DIGEST_DOMAIN + body).hexdigest()


def oracle_plan(calls: Iterable[tuple[str, Mapping[str, Any]]], *, task: str,
                own: frozenset[str]) -> Plan:
    """The plan a planner would need for *calls*, from the task text alone.

    An argument is a literal when every leaf value is in the task text or is
    one of the principal's own identifiers; otherwise it is :data:`DATA`. The
    calls are ground truth, so this is an oracle and gives a ceiling.
    """
    steps = []
    for tool, args in calls:
        marked = []
        for name in sorted(args):
            leaves = _leaves(args[name])
            literal = all(value_trusted(leaf, task=task, own=own) for leaf in leaves)
            marked.append((name, args[name] if literal else DATA))
        steps.append(PlanStep(tool, tuple(marked)))
    return Plan(tuple(steps))


def relaxable_fields(decl: ToolDeclaration) -> frozenset[str]:
    """Arguments whose untrusted content a planned step may carry (rule 2 above)."""
    if decl.risk_tier == "critical":
        return frozenset()
    sink = decl.flow.sink
    targets = set(sink.recipients.arguments())
    return frozenset(f for f in (sink.payload_args or ())
                     if f not in targets and decl.flow.argument_kind(f) == "text")


class PlanBoundGate(RemoraIfcGate):
    """Arm E_PLAN_WS1. One instance holds one cursor per trajectory, so a
    trajectory that is run again needs a new gate."""

    def __init__(self, suite: str, plans: Mapping[str, Plan], *, ws1: bool = True,
                 declarations: Mapping[str, ToolDeclaration] | None = None,
                 halt_on_refusal: bool = False) -> None:
        super().__init__(suite, ws1=ws1, declarations=declarations)
        self.name = ("E_PLAN_WS1" if ws1 else "E_PLAN") + ("_halt" if halt_on_refusal else "")
        self._plans = dict(plans)
        self._halt_on_refusal = halt_on_refusal
        self._halted: set[tuple[str, str, str | None]] = set()
        self._cursor: dict[tuple[str, str, str | None], int] = {}
        self._relaxable: frozenset[str] = frozenset()
        self._relaxed: set[str] = set()

    def plan_for(self, user_task_id: str) -> Plan | None:
        return self._plans.get(user_task_id)

    def _check(self, decl: ToolDeclaration, labels: Mapping[str, Label],
               resolved: Mapping[str, Any], context: Label,
               endorsed: Any = None) -> FlowVerdict:
        def allowed(field: str, value: Any) -> bool:
            if field in self._relaxable:
                if labels[field].integrity is Integrity.UNTRUSTED:
                    self._relaxed.add(field)
                return True
            return endorsed is not None and endorsed(field, value)

        return super()._check(decl, labels, resolved, context, endorsed=allowed)

    def decide(self, call: ProposedCall) -> Verdict:
        plan = self._plans.get(call.user_task_id)
        if plan is None:
            return Verdict(False, 100.0, "plan_missing", {"action": "refuse"})
        key = (call.suite, call.user_task_id, call.injection_task_id)
        index = self._cursor.get(key, 0)
        base = {"plan_digest": plan.digest, "plan_step": index}
        if key in self._halted:
            return Verdict(False, 100.0, "plan_halted", {**base, "action": "refuse"})
        if index >= len(plan.steps):
            return Verdict(False, 100.0, "plan_exhausted", {**base, "action": "refuse"})
        step = plan.steps[index]
        if not step.matches(call.name, call.args):
            return Verdict(False, 100.0, "plan_step_mismatch",
                           {**base, "action": "refuse", "planned_tool": step.tool})
        self._cursor[key] = index + 1
        decl = self._decl.get(call.name)
        self._relaxable = (relaxable_fields(decl) & step.data_fields()) if decl else frozenset()
        self._relaxed = set()
        verdict = super().decide(call)
        if self._halt_on_refusal and not verdict.execute:
            self._halted.add(key)
        return Verdict(verdict.execute, verdict.score, verdict.reason,
                       {**verdict.detail, **base, "relaxed_fields": sorted(self._relaxed)})

