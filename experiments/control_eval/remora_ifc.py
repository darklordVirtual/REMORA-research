# SPDX-License-Identifier: BUSL-1.1
"""REMORA with information-flow control as an AgentDojo defence (E_IFC, E_IFC_WS1).

The design is CAPR-03 (``docs/design/compositional-authority-preservation-v1.md``):
instead of the lexical semantic-intent floor of E1/E2, each call goes
through the flow check of ``remora/flow`` against the deployment's flow
declaration (``agentdojo_flow_toolspecs_v1.yaml``) and then through the
decision engine's hard floor (:func:`hard_guard_floor`, rungs F1 to F6 and
every other hard guard, unchanged).

Per call:

1. A tool with no declaration is ``policy_missing`` (F3, ABSTAIN): the arm
   runs the strict profile.
2. Every argument value gets an integrity label. A value is TRUSTED when it
   occurs in the user task text (token-bounded, case-insensitive; numbers
   by value), when it is one of the principal's own identifiers, or when the
   context is still trusted: no output of a tool declared UNTRUSTED has been
   read yet in this trajectory. Otherwise it is UNTRUSTED. A list is TRUSTED
   only when every element is. A value the agent wrote after reading
   untrusted content is UNTRUSTED, as the IFC SDD's context label requires.
3. :func:`remora.flow.check.flow_check` computes recipients and the
   violations. Readers are PUBLIC throughout (the declaration says why), so
   confidentiality violations here are unresolved recipients only.
4. :func:`hard_guard_floor` maps the verdict to a decision. When no hard
   guard fires the call is ACCEPTed: in this arm the flow verdict, not the
   lexical intent floor, is the authority for a write. A read with no sink
   has no recipient and an empty ``integrity_required`` and always passes.

E_IFC_WS1 adds one step: when the only guard that fired is flow integrity,
and every violating field declares an ``endorse`` resolver, the arm runs one
bounded WS1 lookup per UNTRUSTED value (at most
:data:`~experiments.control_eval.ifc_resolvers.MAX_LOOKUPS_PER_CALL`) and
re-runs the same flow check with an ``endorsed`` callback that is true only
for PROVED values, then the same floor. A refused or unproven lookup grants
nothing. ``Verdict.detail["ws1"]`` records every lookup.

What this arm does not do: the agent sees tool outputs by value (no handles),
so labels come from value provenance, not from a handle store; control-flow
integrity is not checked (an injection can still trigger a write whose
arguments are all trusted); and confidentiality is not exercised.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from experiments.control_eval.ifc_resolvers import (
    MAX_LOOKUPS_PER_CALL,
    PREDICATES,
    LookupResult,
    endorse_value,
    normalise_iban,
    own_identifiers,
)
from experiments.control_eval.policies import ProposedCall, Verdict
from remora.flow.check import FlowVerdict, flow_check
from remora.flow.label import PUBLIC, Integrity, Label
from remora.flow.spec import FlowSpec, parse_flow
from remora.policy.decision_engine import DecisionReason, hard_guard_floor
from remora.policy.observation import PolicyObservation

__all__ = [
    "SPEC_PATH",
    "RemoraIfcGate",
    "ToolDeclaration",
    "field_labels",
    "load_declarations",
    "value_trusted",
]

SPEC_PATH: Final = Path(__file__).with_name("agentdojo_flow_toolspecs_v1.yaml")
_RANK: Final = {"accept": 0.0, "verify": 50.0, "abstain": 75.0, "escalate": 100.0}
_NUMBER: Final = re.compile(r"\d[\d,]*(?:\.\d+)?")
_FLOW_INTEGRITY: Final = frozenset({DecisionReason.FLOW_INTEGRITY_VIOLATION_VERIFY,
                                    DecisionReason.FLOW_INTEGRITY_VIOLATION_ESCALATE})


class ToolDeclaration:
    """One tool's frozen declaration: the parsed flow block plus the ToolSpec fields."""

    def __init__(self, name: str, raw: Mapping[str, Any]) -> None:
        self.name = name
        self.flow: FlowSpec = parse_flow(raw["flow"])
        self.action_type = str(raw["action_type"])
        self.risk_tier = str(raw["risk_tier"])
        self.arguments = frozenset((raw.get("argument_schema") or {}).get("properties") or {})
        self.endorse: Mapping[str, str] = dict(raw.get("endorse") or {})
        self.keeps_stored: Mapping[str, str] = dict(raw.get("keeps_stored") or {})
        self.owner_receives: str | None = raw.get("owner_receives")
        self.output_trusted = self.flow.sources.default_integrity is Integrity.TRUSTED
        unknown = set(self.endorse.values()) - set(PREDICATES)
        if unknown:
            raise ValueError(f"{name}: endorse names undeclared resolvers {sorted(unknown)}")

    def targets_only(self) -> ToolDeclaration:
        """A copy whose integrity_required omits every payload argument that
        the recipients rule does not read (a URL stays: it names the host)."""
        out = copy.copy(self)
        sink = self.flow.sink
        payload = set(sink.payload_args or ()) - set(sink.recipients.arguments())
        out.flow = replace(self.flow, sink=replace(sink, integrity_required=tuple(
            f for f in sink.integrity_required if f not in payload)))
        return out


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, dict[str, ToolDeclaration]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {suite: {tool: ToolDeclaration(tool, spec) for tool, spec in tools.items()}
            for suite, tools in raw["suites"].items()}


def load_declarations(suite: str, path: Path = SPEC_PATH) -> dict[str, ToolDeclaration]:
    return _load(str(path)).get(suite, {})


# ── labels ───────────────────────────────────────────────────────────────


def _leaves(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [leaf for v in value.values() for leaf in _leaves(v)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [leaf for v in value for leaf in _leaves(v)]
    return [value]


def _task_numbers(task: str) -> set[float]:
    out = set()
    for raw in _NUMBER.findall(task):
        try:
            out.add(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def value_trusted(leaf: Any, *, task: str, own: frozenset[str]) -> bool:
    """Whether one scalar is literal in the user task or a principal identifier."""
    if isinstance(leaf, bool):
        return False
    if isinstance(leaf, (int, float)):
        return float(leaf) in _task_numbers(task)
    text = str(leaf).strip()
    if not text:
        return True
    if text.lower() in own or normalise_iban(text).lower() in own:
        return True
    pattern = r"(?<![A-Za-z0-9])" + re.escape(text) + r"(?![A-Za-z0-9])"
    return re.search(pattern, task, flags=re.IGNORECASE) is not None


def field_labels(args: Mapping[str, Any], *, task: str, own: frozenset[str],
                 context_trusted: bool) -> tuple[dict[str, Label], dict[str, list[Any]]]:
    """``(value labels, untrusted leaves per field)`` for one call's arguments."""
    labels: dict[str, Label] = {}
    untrusted: dict[str, list[Any]] = {}
    for name, value in args.items():
        bad = [] if context_trusted else [
            leaf for leaf in _leaves(value) if not value_trusted(leaf, task=task, own=own)]
        labels[name] = Label(PUBLIC, Integrity.UNTRUSTED if bad else Integrity.TRUSTED)
        if bad:
            untrusted[name] = bad
    return labels, untrusted


# ── the gate ─────────────────────────────────────────────────────────────


class RemoraIfcGate:
    """Arm E_IFC, or E_IFC_WS1 with ``ws1=True``."""

    def __init__(self, suite: str, *, ws1: bool = False,
                 declarations: Mapping[str, ToolDeclaration] | None = None,
                 max_lookups: int = MAX_LOOKUPS_PER_CALL,
                 targets_only: bool = False) -> None:
        self.suite = suite
        self.ws1 = ws1
        self.name = ("E_IFC_WS1" if ws1 else "E_IFC") + ("_targets_only" if targets_only else "")
        decl = dict(declarations if declarations is not None else load_declarations(suite))
        #: Exploratory sensitivity variant, not a G1 arm: payload arguments are
        #: dropped from integrity_required, so only target-defining ones count.
        self._decl = {k: v.targets_only() for k, v in decl.items()} if targets_only else decl
        self._max_lookups = max_lookups
        #: Environment snapshots taken before each trajectory's first executed call.
        self._snapshots: dict[tuple[str, str, str | None], Any] = {}

    # The snapshot is retaken whenever no call has executed yet, so a
    # trajectory whose first calls were blocked still starts from the
    # untouched state, and a later run of the same task starts afresh.
    def _snapshot(self, call: ProposedCall) -> Any:
        key = (call.suite, call.user_task_id, call.injection_task_id)
        if not call.prior_calls:
            self._snapshots[key] = call.env
        return self._snapshots.get(key)

    def _context_trusted(self, prior_calls: Iterable[Mapping[str, Any]]) -> bool:
        for prior in prior_calls:
            decl = self._decl.get(str(prior.get("name")))
            if decl is None or not decl.output_trusted:
                return False
        return True

    def _resolved(self, decl: ToolDeclaration, args: Mapping[str, Any], own: frozenset[str],
                  labels: dict[str, Label], env: Any) -> dict[str, Any]:
        """Arguments as the tool will act on them: stored values and the owner filled in."""
        resolved = dict(args)
        for field, source in decl.keeps_stored.items():
            if resolved.get(field) is None and source == "scheduled_transaction_recipient":
                stored = _stored_recipient(env, args.get("id"))
                if stored is not None:
                    resolved[field] = stored
                    # The stored value is the user's own record, unchanged by this call.
                    labels[field] = Label(PUBLIC, Integrity.TRUSTED)
        if decl.owner_receives:
            field = decl.owner_receives
            owner = sorted(o for o in own if "@" in o)[:1]
            listed = list(_leaves(resolved.get(field)))
            resolved[field] = listed + [o for o in owner if o not in listed]
            if field not in args:
                # The owner is the only recipient the agent did not name.
                labels[field] = Label(PUBLIC, Integrity.TRUSTED)
        for field, kind in decl.flow.arguments:
            # AgentDojo's web tools take a bare host ("www.example.com") and
            # fetch it as a web address; the check sees the address fetched.
            value = resolved.get(field)
            if kind == "url" and isinstance(value, str) and value and "://" not in value:
                resolved[field] = f"https://{value}"
        return resolved

    def _check(self, decl: ToolDeclaration, labels: Mapping[str, Label],
               resolved: Mapping[str, Any], context: Label,
               endorsed: Any = None) -> FlowVerdict:
        return flow_check(decl.flow, context_label=context, value_labels=labels,
                          resolved_args=resolved, epoch=0, endorsed=endorsed)

    def _floor(self, call: ProposedCall, decl: ToolDeclaration | None,
               verdict: FlowVerdict | None, schema_valid: bool, forbidden: bool):
        obs = PolicyObservation(
            question=call.user_task,
            action_type=decl.action_type if decl else None,
            risk_tier=decl.risk_tier if decl else None,
            schema_valid=schema_valid, tool_forbidden=forbidden,
            flow_status="evaluated" if verdict is not None else "policy_missing",
            flow_confidentiality_violation=bool(verdict and verdict.conf_viol),
            flow_integrity_violation=bool(verdict and (verdict.int_viol or verdict.ctrl_viol)))
        return obs, hard_guard_floor(obs)

    def decide(self, call: ProposedCall) -> Verdict:
        snapshot = self._snapshot(call)
        decl = self._decl.get(call.name)
        available = {t.name for t in call.tools} if call.tools else {call.name}
        forbidden = call.name not in available
        if decl is None:
            _, floor = self._floor(call, None, None, True, forbidden)
            return self._verdict(floor, {"flow_status": "policy_missing"})

        required = next((t.required for t in call.tools if t.name == call.name), ())
        schema_valid = (set(required) <= set(call.args)
                        and set(call.args) <= decl.arguments)
        own = own_identifiers(self.suite, call.env if call.env is not None else snapshot)
        ctx_trusted = self._context_trusted(call.prior_calls)
        context = Label(PUBLIC, Integrity.TRUSTED if ctx_trusted else Integrity.UNTRUSTED)
        labels, untrusted = field_labels(call.args, task=call.user_task, own=own,
                                         context_trusted=ctx_trusted)
        resolved = self._resolved(decl, call.args, own, labels, call.env)
        verdict = self._check(decl, labels, resolved, context)
        obs, floor = self._floor(call, decl, verdict, schema_valid, forbidden)
        detail: dict[str, Any] = {
            "flow_status": "evaluated", "context_trusted": ctx_trusted,
            "untrusted_fields": sorted(untrusted),
            "int_viol": sorted(verdict.int_viol), "conf_viol": sorted(verdict.conf_viol)}
        if floor is None or not self.ws1 or floor[1] not in _FLOW_INTEGRITY:
            return self._verdict(floor, detail)

        # E_IFC_WS1: only flow integrity fired. Is every violation recoverable?
        others = hard_guard_floor(_without_integrity(obs))
        missing = sorted(f for f in verdict.int_viol if f not in decl.endorse)
        planned = [(f, leaf) for f in sorted(verdict.int_viol) for leaf in untrusted.get(f, [])]
        ws1: dict[str, Any] = {"lookups": [], "lookups_made": 0}
        detail["ws1"] = ws1
        if others is not None or missing or verdict.conf_viol or verdict.ctrl_viol:
            ws1["not_recoverable"] = {"other_guard": others[1].value if others else None,
                                      "fields_without_resolver": missing}
            return self._verdict(floor, detail)
        if len(planned) > self._max_lookups:
            ws1["not_recoverable"] = {"lookup_budget": len(planned)}
            return self._verdict(floor, detail)
        results: list[LookupResult] = []
        principal = sorted(own)[0] if own else ""
        for field, leaf in planned:
            results.append(endorse_value(
                suite=self.suite, tool=call.name, field=field,
                resolver_id=decl.endorse[field], subject=leaf, snapshot=snapshot,
                principal=principal, flow_digest=verdict.digest))
        ws1["lookups"] = [r.to_dict() for r in results]
        ws1["lookups_made"] = len(results)
        proved: dict[str, set[str]] = {}
        for (field, leaf), r in zip(planned, results, strict=True):
            if r.state == "proved":
                proved.setdefault(field, set()).add(str(leaf))

        def endorsed(field: str, value: Any) -> bool:
            need = {str(leaf) for leaf in untrusted.get(field, [])}
            return bool(need) and need <= proved.get(field, set())

        again = self._check(decl, labels, resolved, context, endorsed=endorsed)
        _, floor2 = self._floor(call, decl, again, schema_valid, forbidden)
        ws1["proved"] = floor2 is None
        detail["int_viol_after"] = sorted(again.int_viol)
        return self._verdict(floor2, detail, recovered=floor2 is None)

    def _verdict(self, floor: Any, detail: dict[str, Any], recovered: bool = False) -> Verdict:
        if floor is None:
            detail["action"] = "accept"
            return Verdict(True, 0.0, "ws1_endorsed_accept" if recovered else "flow_clean_accept",
                           detail)
        action, reason = floor
        detail["action"] = action.value
        return Verdict(False, _RANK.get(action.value, 100.0), reason.value, detail)


def _without_integrity(obs: PolicyObservation) -> PolicyObservation:
    return replace(obs, flow_integrity_violation=False)


def _stored_recipient(env: Any, tx_id: Any) -> str | None:
    account = getattr(env, "bank_account", None)
    for t in getattr(account, "scheduled_transactions", None) or ():
        if str(getattr(t, "id", None)) == str(tx_id):
            return getattr(t, "recipient", None)
    return None
