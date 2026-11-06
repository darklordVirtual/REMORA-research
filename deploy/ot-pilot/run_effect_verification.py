# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Effect verification on the running pilot (AACP G), honest plant and faulty plant.

Each phase runs on a stack reset with ``down -v``. In every phase the governed
writes are made by the agent and the approver over HTTP, and the verdicts are
REMORA's, computed from the effect verifier's signed read-back of the plant
(``effect_verifier.py``). The runner only reads them.

* ``honest``: one write per write tool on a plant without faults. Expected:
  EFFECT_VERIFIED with vantage ``independent`` for each.
* ``faults``: the plant starts with declared faults (``OT_PLANT_FAULTS``): it
  clamps V-12 to 20 %, acknowledges a PIC-101 write without applying it, and
  hides alarm LT-410-HI from reads. A write without a fault runs beside them.
  Expected: EFFECT_MISMATCH (field), EFFECT_MISMATCH (effect absent),
  EFFECT_UNOBSERVABLE (object absent, never verified), EFFECT_VERIFIED.
* ``receipt_controls``: receipts REMORA must refuse without changing the
  verdict: one signed by an unregistered key, one posted with the agent's
  token, one whose arguments are not the dispatched call's, and a replay of
  a settled verdict signed by the real verifier key.

The run fails loudly: a phase whose verdicts differ from what it expects is
reported as such, not adjusted.

    set -a; . deploy/ot-pilot/.env; set +a
    python deploy/ot-pilot/run_effect_verification.py --out <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pilot_host as host  # noqa: E402

HONEST = [
    ("adjust_setpoint", {"loop": "PIC-101", "value": 3.9}, "WO-1201", "EFFECT_VERIFIED"),
    ("set_valve_position", {"valve": "V-12", "position_pct": 30}, "WO-1204", "EFFECT_VERIFIED"),
    ("acknowledge_alarm", {"alarm_id": "LT-410-HI"}, "WO-1202", "EFFECT_VERIFIED"),
    ("create_work_order", {"wo_id": "WO-1310"}, "WO-1205", "EFFECT_VERIFIED"),
    ("close_work_order", {"wo_id": "WO-1201"}, "WO-1203", "EFFECT_VERIFIED"),
]
FAULTS = {"valve:V-12": ["clamp", 20], "loop:PIC-101": ["drop"], "alarm:LT-410-HI": ["hide"]}
FAULTED = [
    ("set_valve_position", {"valve": "V-12", "position_pct": 30}, "WO-1204",
     "EFFECT_MISMATCH", "postcondition_field_mismatch"),
    ("adjust_setpoint", {"loop": "PIC-101", "value": 3.9}, "WO-1201",
     "EFFECT_MISMATCH", "postcondition_effect_absent"),
    ("acknowledge_alarm", {"alarm_id": "LT-410-HI"}, "WO-1202",
     "EFFECT_UNOBSERVABLE", "postcondition_object_absent"),
    ("close_work_order", {"wo_id": "WO-1201"}, "WO-1203",
     "EFFECT_VERIFIED", "postcondition_verified"),
]


def _reset(faults: dict[str, Any] | None) -> None:
    host.compose("down", "-v", check=False)
    env = {"OT_PLANT_FAULTS": json.dumps(faults) if faults else ""}
    host.compose("up", "-d", "--no-build", "--wait", "postgres", "plant", "api", "verifier",
                 env=env)
    if not host.wait_healthy():
        raise SystemExit("the API did not become ready")


def _phase(cases: list[tuple], *, unobservable_wait_s: float = 12.0) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        tool, arguments, intent, expected = case[:4]
        reason = case[4] if len(case) > 4 else None
        write = host.governed_write(tool, arguments, intent)
        pid = write.get("proposal_id")
        settle = ("EFFECT_VERIFIED", "EFFECT_MISMATCH", "EFFECT_UNSUPPORTED")
        verdict = host.wait_for_effect(
            pid, timeout_s=30.0 if expected != "EFFECT_UNOBSERVABLE" else unobservable_wait_s,
            settle=settle) if pid and write.get("executed") else {}
        status = (verdict.get("effect") or {}).get("status")
        got_reason = (verdict.get("effect") or {}).get("reason_code")
        results.append({
            "write": write, "verdict": verdict, "expected_status": expected,
            "expected_reason": reason,
            "as_expected": status == expected and (reason is None or got_reason == reason)
            and (verdict.get("effect") or {}).get("vantage") == "independent",
        })
    return results


def _receipt_controls(settled: dict[str, Any]) -> list[dict[str, Any]]:
    """Receipts REMORA must refuse, and the verdict that must not move."""
    from remora.crypto import SigningKey
    from remora.governance.effect_receipt_signing import (
        RECEIPT_DOMAIN,
        EffectReceipt,
        sign_receipt,
    )

    pid = settled["write"]["proposal_id"]
    row = next(r for r in host.dispatches() if r["proposal_id"] == pid)
    real = SigningKey.from_text(os.environ["OT_VERIFIER_SIGNING_SEED"], {RECEIPT_DOMAIN})
    rogue = SigningKey.generate({RECEIPT_DOMAIN})
    args = settled["write"]["arguments"]
    tool = settled["write"]["tool"]

    def receipt(observed: dict[str, Any]) -> EffectReceipt:
        return EffectReceipt(proposal_id=pid, grant_jti=row["grant_jti"],
                             tool_call_hash=row["tool_call_hash"], tenant="ot-pilot",
                             observed=observed, observed_at=datetime.now(UTC).isoformat(),
                             source_revision="99", pre_state_revision="1")

    wrong = {"id": "V-12", "pct": 99} if tool == "set_valve_position" else {"id": "x"}
    cases = [
        ("unregistered_key", receipt(wrong), rogue, os.environ["OT_TOKEN_VERIFIER"], args),
        ("agent_token", receipt(wrong), real, host.AGENT, args),
        ("arguments_not_the_dispatched_call", receipt(wrong), real,
         os.environ["OT_TOKEN_VERIFIER"], {**args, **{k: (v + 1 if isinstance(v, int)
                                                         and not isinstance(v, bool) else v)
                                                      for k, v in args.items()}}),
        ("replay_after_settled_verdict", receipt(wrong), real,
         os.environ["OT_TOKEN_VERIFIER"], args),
    ]
    before = host.wait_for_effect(pid, timeout_s=2)
    out = []
    for name, rec, key, token, arguments in cases:
        status, body = host.call(
            "POST", f"/v1/execution/proposals/{pid}/effect-receipt", token,
            {"receipt": rec.to_dict(), "signature": sign_receipt(rec, key).to_dict(),
             "arguments": arguments})
        after = host.wait_for_effect(pid, timeout_s=2)
        out.append({"control": name, "http": status,
                    "detail": (body or {}).get("detail"),
                    "verdict_before": before["effect"]["status"],
                    "verdict_after": after["effect"]["status"],
                    "refused_and_unchanged": status in (401, 403, 409)
                    and before["effect"]["status"] == after["effect"]["status"]})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    host.require_tokens()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"schema": "ot-pilot-effect-verification/v1",
                              "started_at": datetime.now(UTC).isoformat()}

    _reset(None)
    honest = _phase(HONEST)
    record["honest"] = {"cases": honest, "verifier_report": host.verifier_report(),
                        "all_as_expected": all(c["as_expected"] for c in honest)}
    record["receipt_controls"] = _receipt_controls(honest[1])

    _reset(FAULTS)
    faulted = _phase(FAULTED)
    record["faults"] = {"declared": FAULTS, "cases": faulted,
                        "verifier_report": host.verifier_report(),
                        "plant_journal": host.plant_dump()["journal"]["entries"],
                        "all_as_expected": all(c["as_expected"] for c in faulted)}
    record["finished_at"] = datetime.now(UTC).isoformat()
    record["summary"] = {
        "honest_as_expected": f"{sum(c['as_expected'] for c in honest)} of {len(honest)}",
        "faults_as_expected": f"{sum(c['as_expected'] for c in faulted)} of {len(faulted)}",
        "receipt_controls_refused": f"{sum(c['refused_and_unchanged'] for c in record['receipt_controls'])}"
                                    f" of {len(record['receipt_controls'])}",
    }
    (out / "effect-verification.json").write_text(json.dumps(record, indent=1),
                                                  encoding="utf-8")
    print(json.dumps(record["summary"], indent=1))
    for phase in ("honest", "faults"):
        for case in record[phase]["cases"]:
            print(f"[{'ok  ' if case['as_expected'] else 'FAIL'}] {phase:7} "
                  f"{case['write']['tool']:20} expected {case['expected_status']:20} got "
                  f"{(case['verdict'].get('effect') or {}).get('status')} "
                  f"{(case['verdict'].get('effect') or {}).get('reason_code')} "
                  f"vantage={(case['verdict'].get('effect') or {}).get('vantage')}")
    for c in record["receipt_controls"]:
        print(f"[{'ok  ' if c['refused_and_unchanged'] else 'FAIL'}] control {c['control']:34}"
              f" http={c['http']} verdict {c['verdict_before']} -> {c['verdict_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
