# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's simulated plant: state, the six effects and a complete journal.

Standard library only, so the plant service can run in a container that holds
none of REMORA's code or keys (``plant_service.py``). ``ot_registry`` uses the
same model in-process for the unit tests, where no plant service runs.

The journal is the plant's own record of every request the service
answered: writes applied or refused, reads, and refusals before a tool was
named, each with the credential it presented. It is complete for state
changes by construction: ``Plant.apply`` is the only function that
mutates ``state``, and it appends the journal entry under the same lock, with
the state digest after the change. ``replay_digest`` recomputes the state
from the initial state and the applied entries, so an unjournaled mutation
shows up as a digest that does not match (AACP E, observation coverage).

Each object carries a revision that advances on every applied write. An
effect verifier reads it back with the object, so an unchanged revision says
the dispatch changed nothing (AACP G).

Faults are declared at start for the effect-verification run: ``clamp``
applies a different value, ``drop`` acknowledges a write and changes nothing,
``hide`` makes an object unreadable. A fault is journaled with the write it
affected, so the journal stays the truth about the state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections.abc import Mapping
from typing import Any

__all__ = ["INITIAL_STATE", "OBJECT_KINDS", "TOOL_TARGETS", "Plant", "PlantRefused",
           "state_digest"]

INITIAL_STATE: dict[str, Any] = {
    "sensors": {
        "PT-101": {"unit": "bar", "value": 4.10},
        "TT-204": {"unit": "degC", "value": 61.5},
        "VT-330": {"unit": "mm/s", "value": 2.1},
        "LT-410": {"unit": "%", "value": 71.0},
        "FT-220": {"unit": "m3/h", "value": 118.0},
    },
    "loops": {"PIC-101": {"setpoint": 4.00}, "FIC-220": {"setpoint": 120.0}},
    "valves": {"V-12": {"pct": 15}, "V-18": {"pct": 40}},
    "alarms": {"LT-410-HI": {"acked": False}, "PT-101-HH": {"acked": False}},
    "work_orders": {"WO-1201": {"status": "open"}},
}

#: Object kind in the read API -> state collection.
OBJECT_KINDS: dict[str, str] = {
    "sensor": "sensors", "loop": "loops", "valve": "valves",
    "alarm": "alarms", "work_order": "work_orders",
}

#: Tool -> (argument naming its object, object kind, writes?).
TOOL_TARGETS: dict[str, tuple[str, str, bool]] = {
    "read_sensor": ("sensor_id", "sensor", False),
    "adjust_setpoint": ("loop", "loop", True),
    "set_valve_position": ("valve", "valve", True),
    "acknowledge_alarm": ("alarm_id", "alarm", True),
    "create_work_order": ("wo_id", "work_order", True),
    "close_work_order": ("wo_id", "work_order", True),
}

_FAULT_KINDS = ("clamp", "drop", "hide")


class PlantRefused(Exception):
    """A request the plant does not apply. ``status`` is the HTTP answer."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def state_digest(state: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _number(value: Any, name: str) -> int | float:
    # bool is an int; a setpoint of True is not a number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlantRefused(400, f"{name} must be a number")
    return value


def _mutate(state: dict[str, Any], tool: str, args: Mapping[str, Any],
            fault: tuple[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Apply one effect to ``state``. Returns (object key, tool result)."""
    arg, kind, _ = TOOL_TARGETS[tool]
    ident = args.get(arg)
    if not isinstance(ident, str) or not ident:
        raise PlantRefused(400, f"{arg} must be a non-empty string")
    coll = state[OBJECT_KINDS[kind]]
    key = f"{kind}:{ident}"
    if tool == "create_work_order":
        # As the in-process plant did: a create of an existing id reopens it.
        # The fault-injection run counts two approved identical creates as two
        # operations (no idempotency key declared); refusing the second here
        # would measure the plant instead of REMORA.
        if fault and fault[0] == "drop":
            return key, {"wo_id": ident, "status": "open"}
        coll[ident] = {"status": "open"}
        return key, {"wo_id": ident, "status": "open"}
    obj = coll.get(ident)
    if obj is None:
        raise PlantRefused(404, f"unknown {kind} {ident!r}")
    if tool == "adjust_setpoint":
        new = _number(args.get("value"), "value")
        old = obj["setpoint"]
        applied = fault[1] if fault and fault[0] == "clamp" else new
        if not (fault and fault[0] == "drop"):
            obj["setpoint"] = applied
        return key, {"loop": ident, "old_setpoint": old, "new_setpoint": new}
    if tool == "set_valve_position":
        new = _number(args.get("position_pct"), "position_pct")
        old = obj["pct"]
        applied = fault[1] if fault and fault[0] == "clamp" else new
        if not (fault and fault[0] == "drop"):
            obj["pct"] = applied
        return key, {"valve": ident, "old_pct": old, "new_pct": new}
    if tool == "acknowledge_alarm":
        if not (fault and fault[0] == "drop"):
            obj["acked"] = True
        return key, {"alarm_id": ident, "acked": True}
    if tool == "close_work_order":
        if not (fault and fault[0] == "drop"):
            obj["status"] = "closed"
        return key, {"wo_id": ident, "status": "closed"}
    raise PlantRefused(404, f"unknown tool {tool!r}")  # pragma: no cover


class Plant:
    """One plant: state, revisions, journal. Thread-safe."""

    def __init__(self, faults: Mapping[str, Any] | None = None,
                 clock: Any = time.time) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self.state: dict[str, Any] = copy.deepcopy(INITIAL_STATE)
        self.revisions: dict[str, int] = {}
        #: Each object's state at each revision it reached, as the plant
        #: recorded it when the write applied (a historian). Revision 0 is the
        #: initial state and is read from ``INITIAL_STATE``.
        self.history: dict[str, dict[int, dict[str, Any]]] = {}
        self.journal: list[dict[str, Any]] = []
        self.started_at = clock()
        self.faults = self._parse_faults(faults or {})

    @staticmethod
    def _parse_faults(raw: Mapping[str, Any]) -> dict[str, tuple[str, Any]]:
        """``{"valve:V-18": ["clamp", 30], "alarm:PT-101-HH": ["drop"], ...}``."""
        parsed: dict[str, tuple[str, Any]] = {}
        for key, spec in raw.items():
            if not isinstance(spec, list) or not spec or spec[0] not in _FAULT_KINDS:
                raise ValueError(f"fault {key!r}: expected [clamp, value], [drop] or [hide]")
            if spec[0] == "clamp" and (len(spec) != 2 or isinstance(spec[1], bool)
                                       or not isinstance(spec[1], (int, float))):
                raise ValueError(f"fault {key!r}: clamp needs a number")
            parsed[str(key)] = (spec[0], spec[1] if len(spec) > 1 else None)
        return parsed

    # ── writes ────────────────────────────────────────────────────────────

    def apply(self, tool: str, args: Mapping[str, Any], *, credential: str,
              dispatch_ref: str = "", source: str = "",
              credential_id: str = "") -> dict[str, Any]:
        """Apply one tool call and journal it. Raises ``PlantRefused``.

        ``credential`` is who the transport authenticated (``none`` and
        ``invalid`` are journaled too); only an authorised writer reaches the
        state. ``dispatch_ref`` is the executor's reference to the dispatch,
        recorded for attribution and never trusted for authority.
        ``credential_id`` says which credential of that role it was, as the
        transport names it (a digest, never the credential): two holders of a
        write credential are told apart by it, and a caller cannot choose it.
        """
        with self._lock:
            entry: dict[str, Any] = {
                "seq": len(self.journal) + 1, "at": self._clock(), "tool": tool,
                "arguments": json.loads(json.dumps(dict(args), default=str)),
                "credential": credential, "dispatch_ref": str(dispatch_ref or ""),
                "source": source, "credential_id": str(credential_id or ""),
            }
            changed = False
            try:
                if tool not in TOOL_TARGETS or not TOOL_TARGETS[tool][2]:
                    raise PlantRefused(404, f"unknown write tool {tool!r}")
                if credential != "writer":
                    raise PlantRefused(401 if credential in ("none", "invalid") else 403,
                                       f"credential {credential!r} may not write")
                arg, kind, _ = TOOL_TARGETS[tool]
                key = f"{kind}:{args.get(arg)}"
                fault = self.faults.get(key)
                before = self.revisions.get(key, 0)
                key, result = _mutate(self.state, tool, args, fault)
                changed = not (fault and fault[0] == "drop")
                if changed:
                    self.revisions[key] = before + 1
                    kind_, ident_ = key.split(":", 1)
                    self.history.setdefault(key, {})[before + 1] = copy.deepcopy(
                        self.state[OBJECT_KINDS[kind_]][ident_])
                entry.update(outcome="applied", object=key, rev_before=before,
                             rev_after=self.revisions.get(key, 0), result=result,
                             fault=list(fault) if fault else None,
                             state_digest=state_digest(self.state))
                return {**result, "revision": self.revisions.get(key, 0)}
            except PlantRefused as exc:
                entry.update(outcome="refused", status=exc.status, reason=exc.reason,
                             state_digest=state_digest(self.state))
                raise
            finally:
                self.journal.append(entry)

    def note_request(self, method: str, path: str, *, credential: str, source: str,
                     status: int, reason: str = "", outcome: str = "refused") -> None:
        """Journal a request that is not a tool write: a read, or a refusal
        before a tool was named (bad path, no token). Writes are journaled by
        ``apply``. Together every request the service answers is journaled."""
        with self._lock:
            self.journal.append({
                "seq": len(self.journal) + 1, "at": self._clock(), "tool": None,
                "request": f"{method} {path}", "credential": credential,
                "dispatch_ref": "", "source": source, "outcome": outcome,
                "status": status, "reason": reason,
                "state_digest": state_digest(self.state)})

    #: Kept for callers written before reads were journaled.
    def note_refused(self, method: str, path: str, *, credential: str, source: str,
                     status: int, reason: str) -> None:
        self.note_request(method, path, credential=credential, source=source,
                          status=status, reason=reason)

    # ── reads ─────────────────────────────────────────────────────────────

    def read_object(self, kind: str, ident: str,
                    revision: int | None = None) -> dict[str, Any]:
        """The object now, or as it was at ``revision`` (the plant's own record).

        An effect verifier reads a write's effect at the revision that write
        produced, so a later write to the same object is not mistaken for it.
        A revision the object never reached, or one later than its current
        revision, is refused rather than answered with the nearest one.
        """
        coll_name = OBJECT_KINDS.get(kind)
        if coll_name is None:
            raise PlantRefused(404, f"unknown object kind {kind!r}")
        key = f"{kind}:{ident}"
        with self._lock:
            fault = self.faults.get(key)
            obj = self.state[coll_name].get(ident)
            if obj is None or (fault and fault[0] == "hide"):
                raise PlantRefused(404, f"unknown {kind} {ident!r}")
            current = self.revisions.get(key, 0)
            if revision is None or revision == current:
                return {"kind": kind, "id": ident, **copy.deepcopy(obj), "revision": current}
            if revision == 0:
                initial = INITIAL_STATE[coll_name].get(ident)
                if initial is None:
                    raise PlantRefused(404, f"{kind} {ident!r} did not exist at revision 0")
                return {"kind": kind, "id": ident, **copy.deepcopy(initial), "revision": 0}
            recorded = self.history.get(key, {}).get(revision)
            if recorded is None:
                raise PlantRefused(404, f"{kind} {ident!r} has no revision {revision}")
            return {"kind": kind, "id": ident, **copy.deepcopy(recorded), "revision": revision}

    def read_sensor(self, sensor_id: str) -> dict[str, Any]:
        obj = self.read_object("sensor", sensor_id)
        return {"sensor_id": sensor_id, "unit": obj["unit"], "value": obj["value"]}

    def observe(self, quantity: str, resource: str) -> float:
        """The plant's value for a cumulative limit's meter."""
        with self._lock:
            if quantity == "setpoint_movement":
                return float(self.state["loops"][resource]["setpoint"])
            if quantity == "valve_travel":
                return float(self.state["valves"][resource]["pct"])
        raise KeyError(f"no observation for {quantity!r}")

    def journal_since(self, seq: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self.journal[seq:])

    def digest(self) -> str:
        with self._lock:
            return state_digest(self.state)

    def replay_digest(self) -> str:
        """State digest recomputed from the initial state and the applied journal."""
        with self._lock:
            entries = copy.deepcopy(self.journal)
        state = copy.deepcopy(INITIAL_STATE)
        for entry in entries:
            if entry.get("outcome") != "applied":
                continue
            fault = tuple(entry["fault"]) if entry.get("fault") else None
            _mutate(state, entry["tool"], entry["arguments"], fault)  # type: ignore[arg-type]
        return state_digest(state)
