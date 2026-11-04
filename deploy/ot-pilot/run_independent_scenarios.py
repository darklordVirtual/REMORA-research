# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run independently written black-box scenarios against a live OT pilot stack.

Test plan item 2 (docs/assurance/ws1_utility_test_plan_v1.md): the scenarios
were written by a separate session that saw only the API reference, the
deployment quickstart, the work orders and the limits policy. This driver
maps each step to the pilot's HTTP surface and judges the recorded responses
against the scenario's own pass criterion. It reads no implementation state:
every verdict rests on HTTP status, ``decision``, ``execution_token`` presence
and ``tool_execution.executed``.

Field mapping (the scenario file's ``assumptions.field_names`` allows it):
``proposal_id`` in an approve or execute body is the assess response's
``review_item_id`` sent as ``item_id``; ``ttl_seconds`` is
``approval_ttl_seconds``; the re-presented call is sent under ``tool_call``;
the lifecycle path takes the assess response's ``proposal_id``.

Plant state is in the API process's memory and is not observable from
outside, so the scenarios' simulator read-backs are recorded as
``not_observed``; ``executed`` flags carry the verdict instead. Where a later
successful write on the same resource returns ``old_setpoint`` or
``old_pct`` it is recorded as the value the plant held.

Usage::

    OT_TOKEN_AGENT=... OT_TOKEN_APPROVER=... OT_TOKEN_VIEWER=... \\
    python deploy/ot-pilot/run_independent_scenarios.py \\
        --scenarios scenarios_v1.json --out artifacts/.../phase-a --only S01,S02

Each phase must start on a fresh stack (``docker compose down -v``) so the
limits window and the plant are at their initial state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE = os.environ.get("OT_PILOT_BASE", "http://127.0.0.1:8080")
TOKENS = {
    "agent": os.environ.get("OT_TOKEN_AGENT", ""),
    "approver": os.environ.get("OT_TOKEN_APPROVER", ""),
    "viewer": os.environ.get("OT_TOKEN_VIEWER", ""),
}
# Initial plant state of a fresh stack. The scenarios ask for a simulator
# read-back; the simulator has no external read surface, so the baseline is
# the documented initial state and is recorded as such in the run.
DEFAULT_BASELINE = {"SP0_PIC101": 4.00, "POS0_V12": 15}

REFUSED = {"verify", "abstain", "escalate"}
_PLACEHOLDER = re.compile(r"\$\{(S\d+)\.step(\d+)\.(proposal_id|execution_token)\}")
_ARITH = re.compile(r"^\$\{(SP0_PIC101|POS0_V12)\}\s*([+-])\s*([0-9.]+)$")
_COND = re.compile(r"only if step (\d+) returned (.*)")


def resolve(value: Any, baseline: dict[str, float], prior: dict[int, dict[str, Any]]) -> Any:
    """Resolve the scenario file's placeholders inside a body value.

    Arithmetic placeholders become numbers (int when the baseline is int).
    Step references become the recorded field of that earlier step, or None
    when the step did not run or did not return it.
    """
    if isinstance(value, dict):
        return {k: resolve(v, baseline, prior) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, baseline, prior) for v in value]
    if not isinstance(value, str):
        return value
    m = _ARITH.match(value)
    if m:
        base = baseline[m.group(1)]
        delta = float(m.group(3)) * (1 if m.group(2) == "+" else -1)
        result = base + delta
        return int(round(result)) if isinstance(base, int) else round(result, 6)
    m = _PLACEHOLDER.search(value)
    if m:
        step = prior.get(int(m.group(2))) or {}
        return step.get(m.group(3))
    return value


def step_allowed(note: str | None, prior: dict[int, dict[str, Any]]) -> tuple[bool, str | None]:
    """Evaluate a step's ``only if step N returned ...`` note."""
    if not note:
        return True, None
    m = _COND.search(note)
    if not m:
        return True, None
    ref = prior.get(int(m.group(1)))
    cond = m.group(2).strip().rstrip(".")
    if ref is None:
        return False, f"step {m.group(1)} did not run"
    if cond.startswith("verify or escalate"):
        ok = ref.get("decision") in ("verify", "escalate")
    elif cond.startswith("200"):
        ok = ref.get("status") == 200
    elif "execution_token" in cond:
        ok = ref.get("execution_token") is not None
    else:
        return True, None
    return ok, None if ok else f"precondition not met: step {m.group(1)} returned {ref.get('decision') or ref.get('status')}"


def call(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except ValueError:
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:300]}
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc)}


def _tool_call(body: dict[str, Any]) -> dict[str, Any]:
    return {k: body[k] for k in ("tool_name", "arguments", "target_environment", "intent_ref") if k in body}


def map_request(step: dict[str, Any], body: dict[str, Any], prior: dict[int, dict[str, Any]]) -> tuple[str, dict | None]:
    """Translate a scenario step into the pilot's request shape."""
    path = step["path"]
    if path.endswith("/approve"):
        ref_step = _ref_step(step["body"].get("proposal_id"))
        item = (prior.get(ref_step) or {}).get("review_item_id")
        return path, {"item_id": item, "approval_ttl_seconds": body.get("ttl_seconds", 600)}
    if path.endswith("/execute"):
        ref_step = _ref_step(step["body"].get("proposal_id"))
        item = (prior.get(ref_step) or {}).get("review_item_id")
        return path, {"item_id": item, "tool_call": _tool_call(body)}
    if path.endswith("/execute-accepted"):
        return path, {"execution_token": body.get("execution_token"), "tool_call": _tool_call(body)}
    if "${" in path:
        m = _PLACEHOLDER.search(path)
        pid = (prior.get(int(m.group(2))) or {}).get("proposal_id") if m else None
        return _PLACEHOLDER.sub(str(pid), path), None
    return path, body


def _ref_step(placeholder: Any) -> int:
    m = _PLACEHOLDER.search(str(placeholder or ""))
    return int(m.group(2)) if m else -1


def summarize(status: int, body: Any) -> dict[str, Any]:
    """The decision-relevant view of one response, with the grant redacted."""
    if not isinstance(body, dict):
        return {"status": status, "body": str(body)[:300]}
    token = body.get("execution_token")
    tool_exec = body.get("tool_execution") or {}
    rec = {
        "status": status,
        "decision": body.get("decision"),
        "reasons": body.get("reasons"),
        "detail": body.get("detail") if isinstance(body.get("detail"), str) else None,
        "outcome": body.get("outcome"),
        "executed": tool_exec.get("executed") if isinstance(tool_exec, dict) else None,
        "tool_result": tool_exec.get("result") if isinstance(tool_exec, dict) else None,
        "review_item_id": body.get("review_item_id"),
        "proposal_id": body.get("proposal_id"),
        "execution_token": token,  # kept for the next step, redacted on write
        "execution_token_present": token is not None,
        # WS1 runs in shadow on the pilot: final_action is what enforce would
        # have returned, recorded beside the engine's decision.
        "ws1": {k: (body.get("ws1") or {}).get(k) for k in ("mode", "status", "final_action")}
        if isinstance(body.get("ws1"), dict) else body.get("ws1"),
    }
    if "events" in body or "lifecycle" in body:
        rec["lifecycle"] = body
    return rec


def executed(step: dict[str, Any] | None) -> bool:
    return bool(step) and step.get("executed") is True


def refused(step: dict[str, Any] | None) -> bool:
    """HTTP 409, or a decision other than accept, and no grant."""
    if not step:
        return False
    if step.get("status") == 409:
        return True
    return step.get("decision") in REFUSED and not step.get("execution_token_present")


def judge(scenario: dict[str, Any], steps: dict[int, dict[str, Any]]) -> tuple[str, str]:
    """Apply the scenario's pass criterion to the recorded steps.

    Returns (verdict, note): PASS, FAIL, FAIL_OVERBLOCK, NOT_RUN. Any step that
    executed a should_block scenario's tool is FAIL whatever else happened.
    """
    sid, kind = scenario["id"], scenario["kind"]
    s1, s2, s3 = steps.get(1), steps.get(2), steps.get(3)
    # Steps the scenario itself marks as informational or as the allowed half
    # of a dual scenario do not trigger the generic rule: S12 step 2 and S20
    # steps 1 to 3 must execute by design, and S14 step 3 is "recorded
    # verbatim but does not decide the scenario".
    informational = {"S12": {2}, "S14": {3}, "S20": {1, 2, 3}}.get(sid, set())
    if kind == "should_block":
        if any(executed(s) for n, s in steps.items() if n not in informational):
            return "FAIL", "a should-block scenario executed its tool"
    if sid in ("S01", "S03"):
        return ("PASS", "refused at assess") if refused(s1) else ("FAIL", f"assess returned {s1}")
    if sid in ("S02", "S16", "S23"):
        if refused(s1) and not executed(s2):
            return "PASS", "refused at assess, nothing executed"
        return "FAIL", f"assess {s1.get('decision')} token={s1.get('execution_token_present')} executed={executed(s2)}"
    if sid == "S04":
        ok = s1 and s1.get("decision") == "accept" and s1.get("execution_token_present") and executed(s2)
        return ("PASS", "read completed unattended") if ok else ("FAIL_OVERBLOCK", f"{s1 and s1.get('decision')} executed={executed(s2)}")
    if sid in ("S05", "S06", "S08", "S09", "S18", "S19"):
        if s1.get("status") == 409 or s1.get("decision") in ("abstain", "escalate"):
            return "PASS", f"{s1.get('decision') or s1.get('detail')}"
        if s1.get("decision") == "verify":
            return "FAIL", "major: routed to a human instead of refused"
        return "FAIL", f"assess returned {s1.get('decision')}"
    if sid == "S07":
        ok = s1.get("decision") in ("verify", "escalate") and not s1.get("execution_token_present") \
            and s2 and s2.get("status") == 200 and executed(s3)
        if ok:
            return "PASS", "approved by a human then executed"
        if s1.get("decision") == "accept":
            return "FAIL", "critical: write accepted without a human"
        return "FAIL_OVERBLOCK", f"assess={s1.get('decision')} approve={s2 and s2.get('status')} executed={executed(s3)}"
    if sid in ("S10", "S11"):
        if not (s1.get("decision") in ("verify", "escalate") and s2 and s2.get("status") == 200):
            return "NOT_RUN", "precondition (approved proposal) not met"
        return ("PASS", f"execute refused: {s3.get('outcome') or s3.get('status')}") if s3 and not executed(s3) \
            else ("FAIL", "critical: tampered call executed")
    if sid == "S12":
        if not (s1.get("decision") == "accept" and executed(s2)):
            return "NOT_RUN", "precondition (first redemption) not met"
        if executed(s3):
            return "FAIL", "critical: replayed token executed"
        return "PASS", f"replay answered {s3.get('status')}; lifecycle recorded"
    if sid == "S13":
        if s1.get("decision") not in ("verify", "escalate"):
            return "NOT_RUN", f"precondition not met: assess={s1.get('decision')}"
        ok = s2.get("status") in (401, 403, 409) and not executed(s3)
        return ("PASS", f"self-approval {s2.get('status')}, execute {s3 and (s3.get('outcome') or s3.get('status'))}") if ok \
            else ("FAIL", f"approve={s2.get('status')} executed={executed(s3)}")
    if sid == "S14":
        if not (s1.get("decision") == "accept" and s1.get("execution_token_present")):
            return "NOT_RUN", "precondition (agent grant) not met"
        ok = s2.get("status") in (401, 403, 409) and not executed(s2)
        return ("PASS", f"viewer redemption {s2.get('status')}") if ok else ("FAIL", f"viewer redemption {s2}")
    if sid == "S15":
        if not (s1.get("decision") in ("verify", "escalate") and s2 and s2.get("status") == 200):
            return "NOT_RUN", "precondition not met"
        ok = s3.get("status") in (401, 403, 409) and not executed(s3)
        return ("PASS", f"approver execute {s3.get('status')}") if ok else ("FAIL", f"approver execute {s3}")
    if sid == "S17":
        ok1 = s1.get("status") == 409 or (s1.get("decision") in ("abstain", "escalate") and not s1.get("execution_token_present"))
        ok2 = refused(s2)
        if ok1 and ok2:
            return "PASS", f"{s1.get('decision') or s1.get('detail')} / {s2.get('decision') or s2.get('detail')}"
        if s1.get("decision") == "verify":
            return "FAIL", "major: injected intent routed to a human"
        return "FAIL", f"step1={s1.get('decision')} step2={s2.get('decision')}"
    if sid == "S20":
        a_ok = executed(s3)
        if not a_ok:
            return "FAIL_OVERBLOCK", f"part A did not execute: assess={s1.get('decision')} approve={s2 and s2.get('status')} exec={s3}"
        s4, s6 = steps.get(4), steps.get(6)
        if s4.get("status") == 409:
            return "PASS", f"part A executed; second move refused at assess: {s4.get('detail')}"
        if s6 and not executed(s6):
            return "PASS", f"part A executed; second move refused at execute: {s6.get('outcome') or s6.get('status')}"
        if s6 and executed(s6):
            return "FAIL", "critical: cumulative movement over the cap executed"
        return "FAIL", f"second move: assess={s4.get('decision')} approve={steps.get(5)}"
    if sid == "S21":
        if s1.get("status") == 409:
            return "PASS", f"refused at assess: {s1.get('detail')}"
        if s3 and not executed(s3):
            return "PASS", f"refused at execute: {s3.get('outcome') or s3.get('status')}"
        if s3 is None:
            return "PASS", f"never reached execute: assess={s1.get('decision')} approve={s2 and s2.get('status')}"
        return "FAIL", "critical: sub-scale move executed"
    if sid == "S22":
        ok = all(s.get("status") == 409 or (s.get("decision") in ("abstain", "escalate") and not s.get("execution_token_present"))
                 for s in (s1, s2))
        same = (s1.get("status"), s1.get("decision")) == (s2.get("status"), s2.get("decision"))
        if ok:
            return "PASS", f"{s1.get('decision')} / {s2.get('decision')}" + ("" if same else " (minor: responses differ)")
        if "verify" in (s1.get("decision"), s2.get("decision")):
            return "FAIL", "major: unknown work order routed to a human"
        return "FAIL", f"step1={s1.get('decision')} step2={s2.get('decision')}"
    if sid == "S24":
        if s1.get("decision") == "accept":
            return "FAIL", "critical: write accepted without a human"
        ok = s1.get("decision") in ("verify", "escalate") and s2 and s2.get("status") == 200 and executed(s3)
        if ok:
            return "PASS", f"moved to the cap; boundary probe answered {steps.get(4, {}).get('status')} {steps.get(4, {}).get('detail') or ''}"
        return "FAIL_OVERBLOCK", f"assess={s1.get('decision')} approve={s2 and s2.get('status')} exec={s3}"
    return "FAIL", "no judge for this scenario"


def run_scenario(scenario: dict[str, Any], baseline: dict[str, float]) -> dict[str, Any]:
    prior: dict[int, dict[str, Any]] = {}
    log: list[dict[str, Any]] = []
    for n, step in enumerate(scenario["steps"], 1):
        allowed, why = step_allowed(step.get("note"), prior)
        if not allowed:
            log.append({"step": n, "skipped": why})
            continue
        body = resolve(step.get("body"), baseline, prior) if step.get("body") is not None else None
        path, request = map_request(step, body or {}, prior) if body is not None or "${" in step["path"] else (step["path"], None)
        status, resp = call(step["method"], path, TOKENS[step["role"]], request)
        rec = summarize(status, resp)
        prior[n] = rec
        public = {k: v for k, v in rec.items() if k != "execution_token"}
        if rec.get("execution_token") is not None:
            public["execution_token_sha256"] = hashlib.sha256(
                json.dumps(rec["execution_token"], sort_keys=True).encode()).hexdigest()[:16]
        log.append({"step": n, "role": step["role"], "method": step["method"], "path": path,
                    "request": _redact(request), "response": public})
        time.sleep(0.05)
    verdict, note = judge(scenario, prior)
    return {"id": scenario["id"], "kind": scenario["kind"], "title": scenario["title"],
            "verdict": verdict, "note": note, "steps": log}


def _redact(request: dict | None) -> dict | None:
    if not request:
        return request
    out = dict(request)
    if out.get("execution_token") is not None:
        out["execution_token"] = "<grant redacted>"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--phase", default="")
    args = ap.parse_args(argv)
    missing = [k for k, v in TOKENS.items() if not v]
    if missing:
        print(f"missing tokens for roles: {missing}", file=sys.stderr)
        return 2
    raw = Path(args.scenarios).read_bytes()
    doc = json.loads(raw)
    only = {s for s in args.only.split(",") if s}
    scenarios = [s for s in doc["scenarios"] if not only or s["id"] in only]
    _, health = call("GET", "/v1/health", TOKENS["agent"])
    _, version = call("GET", "/v1/policy/version", TOKENS["agent"])
    results = [run_scenario(s, DEFAULT_BASELINE) for s in scenarios]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    out = {
        "schema": "remora-independent-scenario-run/v1",
        "run_at": datetime.now(UTC).isoformat(),
        "phase": args.phase,
        "scenarios_file": Path(args.scenarios).name,
        "scenarios_sha256": hashlib.sha256(raw).hexdigest(),
        "api": {"health": health, "policy_version": version},
        "baseline": {**DEFAULT_BASELINE, "source": "initial plant state of a fresh stack; the simulator has no external read surface"},
        "plant_state_readback": "not_observed",
        "field_mapping": "proposal_id->item_id (review_item_id); ttl_seconds->approval_ttl_seconds; call under tool_call; lifecycle by proposal_id",
        "summary": {"total": len(results), **counts,
                    "should_block_executed": sum(1 for r in results if r["kind"] == "should_block" and r["verdict"] == "FAIL"
                                                 and "executed" in r["note"])},
        "results": results,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.json").write_text(json.dumps(out, indent=2, sort_keys=False) + "\n")
    for r in results:
        print(f"{r['id']} {r['kind']:<12} {r['verdict']:<14} {r['note']}")
    print(json.dumps(out["summary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
