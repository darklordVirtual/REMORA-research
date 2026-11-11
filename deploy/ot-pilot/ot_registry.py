# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's tool registry: six tools, executed at the plant service.

With ``OT_PLANT_URL`` set, every tool is a call to the plant service
(``plant_service.py``) authenticated with ``OT_PLANT_WRITE_TOKEN``. That
token is held by this process only, so the governed dispatcher in the API is
the only holder of a path to the plant's state (AACP E; the deployment's
credential register is ``credential_topology.yaml``). Each write carries the
current proposal id as ``dispatch_ref``, which the plant journals for
attribution; it is not authority, and REMORA binds the effect to the call by
the approved arguments' hash, not by this reference. The id is read from the
execution API's request holder, so it is present on the synchronous execute
path the pilot uses. The async dispatch worker (``REMORA_ASYNC_DISPATCH``) has
no request holder: there every write would reach the plant without a
reference, and the journal reconciliation would report it as unattributed.
The pilot does not run that worker.

Without ``OT_PLANT_URL`` the plant is an in-process ``plant_model.Plant``,
for the unit tests only. Production mode refuses that configuration at
import: an in-process plant can be changed by any code beside REMORA, which
is the bypass this split exists to remove (AACP v0.1 section 12.3: answered
by refusing the configuration, and the refusal is tested).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plant_model import TOOL_TARGETS, Plant, PlantRefused  # noqa: E402

__all__ = ["PLANT", "PLANT_STARTED_AT", "PlantUnavailable", "acknowledge_alarm",
           "adjust_setpoint", "check_limit_evidence", "close_work_order", "create_work_order",
           "observe_limit_value", "read_sensor", "register_tools", "set_valve_position"]

_TIMEOUT_S = 5.0


def _plant_url() -> str:
    return os.environ.get("OT_PLANT_URL", "").strip().rstrip("/")


if not _plant_url() and os.environ.get("REMORA_ENV", "").strip().lower() == "production":
    raise RuntimeError(
        "ot_registry refuses an in-process plant in production: set OT_PLANT_URL "
        "and OT_PLANT_WRITE_TOKEN so the plant runs in its own trust domain")

#: The in-process plant (unit tests only). ``PLANT`` is its state, which the
#: tests read and change directly to stand for a change made at the plant.
_LOCAL: Plant | None = None if _plant_url() else Plant()
PLANT: dict[str, Any] = _LOCAL.state if _LOCAL is not None else {}

#: When this plant started. The journal covers nothing earlier.
PLANT_STARTED_AT: float = _LOCAL.started_at if _LOCAL is not None else 0.0


class PlantUnavailable(RuntimeError):
    """The plant service could not be reached or did not answer."""


def _dispatch_ref() -> str:
    """The proposal being executed, from the execution API's request holder."""
    module = sys.modules.get("servers.execution_api")
    var = getattr(module, "CURRENT_PROPOSAL_ID", None)
    holder = var.get() if var is not None else None
    return str((holder or {}).get("id") or "")


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    token = os.environ.get("OT_PLANT_WRITE_TOKEN", "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{_plant_url()}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            reason = json.loads(exc.read().decode("utf-8")).get("error", "")
        except ValueError:
            reason = ""
        raise PlantRefused(exc.code, reason or f"plant answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PlantUnavailable(f"plant service unavailable: {exc}") from exc


def _write(tool: str, a: dict[str, Any]) -> dict[str, Any]:
    if _LOCAL is not None:
        result = _LOCAL.apply(tool, dict(a), credential="writer",
                              dispatch_ref=_dispatch_ref(), source="in-process",
                              credential_id="in-process")
    else:
        result = _request("POST", f"/tools/{tool}",
                          {"arguments": dict(a), "dispatch_ref": _dispatch_ref()})
    result.pop("revision", None)
    return result


def _known(tool: str, error: PlantRefused) -> Exception:
    # A 404 for the object is the tool's own "unknown loop" error, as before.
    return ValueError(error.reason) if error.status in (400, 404, 409) else error


def read_sensor(a: dict[str, Any]) -> dict[str, Any]:
    sid = str(a.get("sensor_id", ""))
    try:
        if _LOCAL is not None:
            return _LOCAL.read_sensor(sid)
        return _request("GET", f"/sensors/{urllib.parse.quote(sid, safe='')}")
    except PlantRefused as exc:
        raise _known("read_sensor", exc) from exc


def adjust_setpoint(a: dict[str, Any]) -> dict[str, Any]:
    try:
        return _write("adjust_setpoint", a)
    except PlantRefused as exc:
        raise _known("adjust_setpoint", exc) from exc


def set_valve_position(a: dict[str, Any]) -> dict[str, Any]:
    try:
        return _write("set_valve_position", a)
    except PlantRefused as exc:
        raise _known("set_valve_position", exc) from exc


def acknowledge_alarm(a: dict[str, Any]) -> dict[str, Any]:
    try:
        return _write("acknowledge_alarm", a)
    except PlantRefused as exc:
        raise _known("acknowledge_alarm", exc) from exc


def create_work_order(a: dict[str, Any]) -> dict[str, Any]:
    try:
        return _write("create_work_order", a)
    except PlantRefused as exc:
        raise _known("create_work_order", exc) from exc


def close_work_order(a: dict[str, Any]) -> dict[str, Any]:
    try:
        return _write("close_work_order", a)
    except PlantRefused as exc:
        raise _known("close_work_order", exc) from exc


#: What a plant identifier looks like. The limit observer runs at assess, on
#: the call's own target argument, before the scope guard has refused anything,
#: so an agent-chosen string must not become a path at the plant (adversarial
#: review 2026-11-06: ``V-12?dispatch_ref=x`` and ``../`` reached it as
#: writer-credential requests).
_PLANT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_QUANTITIES = frozenset({"setpoint_movement", "valve_travel"})


def observe_limit_value(tenant: str, quantity: str, resource: str) -> float:
    """The value the plant reports, for cumulative limits.

    Reads the plant, not REMORA's ledger. An unknown quantity or resource
    raises, and the limit then refuses the call. A resource that is not a
    plant identifier raises before any request is made.
    """
    if quantity not in _QUANTITIES or not isinstance(resource, str) \
            or not _PLANT_ID.fullmatch(resource):
        raise KeyError(f"no observation for {quantity!r} on {resource!r}")
    if _LOCAL is not None:
        return _LOCAL.observe(quantity, resource)
    try:
        return float(_request("GET", f"/observe/{quantity}/"
                                     f"{urllib.parse.quote(resource, safe='')}")["value"])
    except PlantRefused as exc:
        raise KeyError(f"no observation for {quantity!r} on {resource!r}") from exc


def _journal() -> tuple[float, list[dict[str, Any]]]:
    if _LOCAL is not None:
        return PLANT_STARTED_AT, _LOCAL.journal_since(0)
    body = _request("GET", "/journal")
    return float(body["started_at"]), list(body["entries"])


def check_limit_evidence(tenant: str, operation: Any, evidence_ref: str) -> dict[str, Any]:
    """What the plant's journal says an operation with an unknown outcome did.

    ``REMORA_LIMITS_EVIDENCE_MODULE`` names this module, so a reviewer's
    ``POST /v1/execution/limits/resolve`` is checked against the plant rather
    than taken on trust. ``evidence_ref`` is ``plant-log:<tool>:<resource>``
    and must name the operation's tool. The answer is whether the journal
    holds an applied entry for that tool and resource at or after the
    operation was reserved.

    Raises, so the resolution refuses as ``limit_evidence_unavailable``, when
    the reference is malformed or names another tool, and when the plant
    started after the operation: its journal is in memory and cannot tell.
    """
    kind, _, rest = evidence_ref.partition(":")
    tool, _, resource = rest.partition(":")
    if kind != "plant-log" or not resource or tool != operation.get("tool") \
            or tool not in TOOL_TARGETS:
        raise ValueError(f"evidence_ref {evidence_ref!r} is not plant-log:<tool>:<resource> "
                         "for this operation's tool")
    started_at, entries = _journal()
    reserved_at = float(operation.get("at") or 0.0)
    if reserved_at < started_at:
        raise LookupError("the plant restarted after this operation; its journal cannot tell")
    field = TOOL_TARGETS[tool][0]
    ran = any(entry.get("tool") == tool and entry.get("outcome") == "applied"
              and str((entry.get("arguments") or {}).get(field)) == resource
              and float(entry.get("at") or 0.0) >= reserved_at
              for entry in entries)
    return {"executed": ran, "source": "ot-plant-journal"}


def register_tools(register: Callable[[str, Callable[[Any], Any]], None]) -> None:
    for name, fn in (
        ("read_sensor", read_sensor),
        ("adjust_setpoint", adjust_setpoint),
        ("set_valve_position", set_valve_position),
        ("acknowledge_alarm", acknowledge_alarm),
        ("create_work_order", create_work_order),
        ("close_work_order", close_work_order),
    ):
        register(name, fn)
