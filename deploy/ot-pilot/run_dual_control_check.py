# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Dual control on the running pilot: S20's second half-move needs two approvers.

The pilot's PIC-101 limit is 1.60 bar per hour, with a second tier at 0.50 bar
(``dual_control_above`` in ``limits.json``). Each phase runs on a stack reset
with ``down -v``, and every request goes over HTTP with the pilot's own tokens.

* ``one_approver``: S20 as the independent scenario runs it. The first +0.30
  bar move runs on one approval. The second needs two approvers: the
  approver's approval is recorded, the same approver again is refused, the
  execute is refused, and the plant stays at 4.30.
* ``two_approvers``: the same sequence, and the supervisor (admin, a
  different person) approves second. The move runs and the plant is at 4.60.
* ``grew_after_approval``: a move approved by one person while the hour is
  under the tier. Another move then takes the hour past it before the first
  is executed. The reservation at dispatch refuses it as
  ``limit_dual_control_unmet``, and the plant is not moved.
* ``hard_cap``: a move past 1.60 bar is refused at assess, whatever the
  approvals.

The run fails loudly: a phase whose outcome differs from what it expects is
reported as such, not adjusted.

    set -a; . deploy/ot-pilot/.env; set +a
    python deploy/ot-pilot/run_dual_control_check.py --out <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pilot_host as host  # noqa: E402


def _reset() -> None:
    host.compose("down", "-v", check=False)
    host.compose("up", "-d", "--no-build", "--wait", "postgres", "plant", "api", "verifier")
    if not host.wait_healthy():
        raise SystemExit("the API did not become ready")


def _call(value: float) -> dict[str, Any]:
    return {"tool_name": "adjust_setpoint", "arguments": {"loop": "PIC-101", "value": value},
            "target_environment": "prod", "intent_ref": "WO-1201"}


def _setpoint() -> Any:
    return host.plant_object("loop", "PIC-101").get("setpoint")


def _step(name: str, method: str, path: str, token: str, body: Any) -> dict[str, Any]:
    status, answer = host.call(method, path, token, body)
    te = (answer or {}).get("tool_execution") or {}
    keep = {k: answer.get(k) for k in ("decision", "reasons", "review_item_id",
                                       "approvals_required", "dual_control", "status",
                                       "approvals_received", "outcome", "detail")
            if isinstance(answer, dict) and k in answer}
    if te:
        keep["executed"] = te.get("executed")
        keep["refusal_reason"] = te.get("refusal_reason")
    return {"step": name, "http": status, **keep}


def _assess(name: str, value: float) -> dict[str, Any]:
    return _step(name, "POST", "/v1/execution/assess", host.AGENT, _call(value))


def _approve(name: str, item: str, token: str) -> dict[str, Any]:
    return _step(name, "POST", "/v1/execution/approve", token,
                 {"item_id": item, "approval_ttl_seconds": 600})


def _execute(name: str, item: str, value: float) -> dict[str, Any]:
    return _step(name, "POST", "/v1/execution/execute", host.AGENT,
                 {"item_id": item, "tool_call": _call(value)})


def _first_move() -> list[dict[str, Any]]:
    a = _assess("assess +0.30", 4.3)
    return [a, _approve("approve (approver)", a["review_item_id"], host.APPROVER),
            _execute("execute", a["review_item_id"], 4.3)]


def phase_one_approver() -> dict[str, Any]:
    steps = _first_move()
    a = _assess("assess second +0.30", 4.6)
    item = a.get("review_item_id", "")
    steps += [a, _approve("approve (approver)", item, host.APPROVER),
              _approve("approve again (same approver)", item, host.APPROVER),
              _execute("execute", item, 4.6)]
    sp = _setpoint()
    ok = (steps[2].get("executed") is True and a.get("approvals_required") == 2
          and steps[4].get("status") == "approval_recorded"
          and (steps[5]["http"], steps[5].get("detail")) == (409, "approver_already_approved")
          and (steps[6]["http"], steps[6].get("detail")) == (
              409, "dual_control_second_approval_required")
          and sp == 4.3)
    return {"steps": steps, "plant_setpoint_after": sp, "as_expected": ok}


def phase_two_approvers() -> dict[str, Any]:
    steps = _first_move()
    a = _assess("assess second +0.30", 4.6)
    item = a.get("review_item_id", "")
    steps += [a, _approve("approve (approver)", item, host.APPROVER),
              _approve("approve (supervisor)", item, host.SUPERVISOR),
              _execute("execute", item, 4.6)]
    sp = _setpoint()
    ok = (steps[2].get("executed") is True and a.get("approvals_required") == 2
          and steps[4].get("status") == "approval_recorded"
          and steps[5].get("status") == "approved" and steps[6].get("executed") is True
          and sp == 4.6)
    return {"steps": steps, "plant_setpoint_after": sp, "as_expected": ok}


def phase_grew_after_approval() -> dict[str, Any]:
    late = _assess("assess +0.30 (late)", 4.3)
    steps = [late, _approve("approve late (approver)", late["review_item_id"], host.APPROVER)]
    early = _assess("assess -0.30 (early)", 3.7)
    steps += [early, _approve("approve early (approver)", early["review_item_id"], host.APPROVER),
              _execute("execute early", early["review_item_id"], 3.7),
              _execute("execute late: 3.7 -> 4.3 is 0.9 this hour", late["review_item_id"],
                       4.3)]
    sp = _setpoint()
    ok = ("approvals_required" not in late and steps[4].get("executed") is True
          and steps[5].get("executed") is False
          and steps[5].get("refusal_reason") == "limit_dual_control_unmet" and sp == 3.7)
    return {"steps": steps, "plant_setpoint_after": sp, "as_expected": ok}


def phase_hard_cap() -> dict[str, Any]:
    a = _assess("assess +1.40", 5.4)
    item = a.get("review_item_id", "")
    steps = [a, _approve("approve (approver)", item, host.APPROVER),
             _approve("approve (supervisor)", item, host.SUPERVISOR),
             _execute("execute", item, 5.4), _assess("assess +0.30 more: 1.70 > 1.60", 5.7)]
    sp = _setpoint()
    ok = (steps[3].get("executed") is True
          and (steps[4]["http"], steps[4].get("detail")) == (409, "limit_exceeded") and sp == 5.4)
    return {"steps": steps, "plant_setpoint_after": sp, "as_expected": ok}


PHASES = {"one_approver": phase_one_approver, "two_approvers": phase_two_approvers,
          "grew_after_approval": phase_grew_after_approval, "hard_cap": phase_hard_cap}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    host.require_tokens()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"schema": "ot-pilot-dual-control-check/v1",
                              "started_at": datetime.now(UTC).isoformat(), "phases": {}}
    for name, phase in PHASES.items():
        _reset()
        record["phases"][name] = phase()
    record["finished_at"] = datetime.now(UTC).isoformat()
    record["all_as_expected"] = all(p["as_expected"] for p in record["phases"].values())
    (out / "dual-control-check.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(json.dumps({n: p["as_expected"] for n, p in record["phases"].items()}, indent=1))
    return 0 if record["all_as_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
