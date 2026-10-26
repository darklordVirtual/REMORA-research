#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Inject faults into a running OT pilot and record what the chain did.

Usage, from the repository root, on a fresh stack::

    docker compose -f deploy/ot-pilot/docker-compose.yml down -v
    docker compose -f deploy/ot-pilot/docker-compose.yml up --build -d
    python deploy/ot-pilot/run_fault_injection.py --evidence-root artifacts/pilot-pack/runs

The battery (``run_ot_battery.py``) shows what the system does when nothing
goes wrong. This runner breaks things while it works: it restarts the API
between an approval and its execution, stops PostgreSQL in the middle of a
governed write, races four executions of one approval, proposes the same
write twice, revokes an approver, stops execution, and runs a tool that fails
after dispatch began. Each fault states what the system must do, and the
report says whether it did. A fault that does not behave as stated is a
FAILURE, printed as one.

It drives the API over HTTP and the stack through ``docker compose``, so it
exercises the deployed service, not the local checkout. It also freezes the
configuration it ran against: the sha256 of every file the stack is built
from, the API image id, the checkout's commit, and the policy identity the
API reports. Two runs with the same fingerprint ran the same deployment.

It measures what an operator would: the latency of every call by route, how
many writes meant to run did run, how many were refused although they
should have run, and how many human steps (approvals, revocations, stops,
resolutions) the run needed.

The plant is simulated in the API process. A restart resets it to its
starting values while the limit ledger and the audit chain persist; the
evidence names that, and the faults are written so it does not decide them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import run_ot_battery as battery  # noqa: E402

BASE = os.environ.get("REMORA_PILOT_URL", "http://127.0.0.1:8080")
COMPOSE = os.environ.get("REMORA_PILOT_COMPOSE", str(HERE / "docker-compose.yml"))
PROJECT = os.environ.get("REMORA_PILOT_PROJECT", "")
AGENT, APPROVER, SUPERVISOR, VIEWER = "ot-agent", "ot-approver", "ot-supervisor", "ot-viewer"

#: The files the pilot is built and configured from. Their digests are the
#: frozen configuration; a change to any of them is a different deployment.
CONFIG_FILES = (
    "deploy/ot-pilot/docker-compose.yml",
    "deploy/ot-pilot/Dockerfile",
    "deploy/ot-pilot/limits.json",
    "deploy/ot-pilot/work_orders.json",
    "deploy/ot-pilot/ot_registry.py",
    "deploy/ot-pilot/ot_bundle.py",
)

LATENCIES: dict[str, list[float]] = defaultdict(list)
#: Set while a fault is in force, so calls made then are timed apart: a
#: request waiting on a stopped database is the fault, not the latency.
IN_FAULT_WINDOW = threading.Event()
HUMAN_STEPS: list[str] = []


def call(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, Any]:
    """One HTTP call, timed under its route (path without ids)."""
    route = "/".join("{id}" if len(part) >= 32 else part for part in path.split("/"))
    started = time.perf_counter()
    try:
        return _call(method, path, token, body)
    finally:
        prefix = "[fault window] " if IN_FAULT_WINDOW.is_set() else ""
        LATENCIES[f"{prefix}{method} {route}"].append((time.perf_counter() - started) * 1000)


def _call(method: str, path: str, token: str, body: dict | None) -> tuple[int, Any]:
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
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:200]}
    except (urllib.error.URLError, OSError) as exc:
        return 0, {"error": str(exc)}


def compose(*args: str) -> str:
    cmd = ["docker", "compose", "-f", COMPOSE, *(["-p", PROJECT] if PROJECT else []), *args]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {done.stderr.strip()[-300:]}")
    return done.stdout


def wait_healthy(timeout_s: int = 120) -> bool:
    """Liveness only: /v1/health does not read the store."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, body = _call("GET", "/v1/health", AGENT, None)
        if status == 200 and body.get("status") == "ok":
            return True
        time.sleep(1)
    return False


def wait_store(timeout_s: int = 120) -> bool:
    """Until a call that reads the store answers 200 again."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _call("GET", "/v1/execution/stop", VIEWER, None)[0] == 200:
            return True
        time.sleep(1)
    return False


# ── Configuration fingerprint ───────────────────────────────────────────────

def file_digests(root: Path, names: tuple[str, ...] = CONFIG_FILES) -> dict[str, str | None]:
    """sha256 of each named file over its bytes; None for a missing file."""
    out: dict[str, str | None] = {}
    for name in names:
        path = root / name
        out[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return out


def fingerprint_digest(fingerprint: dict[str, Any]) -> str:
    """One digest over the parts of the fingerprint that define the deployment."""
    core = {k: fingerprint.get(k) for k in ("files", "api_image_id", "policy_hash",
                                             "manifest_digest")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def frozen_configuration() -> dict[str, Any]:
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=False)
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *CONFIG_FILES],
                           capture_output=True, text=True, check=False)
    image = compose("images", "-q", "api").strip().splitlines()
    _, version = call("GET", "/v1/policy/version", VIEWER)
    _, caps = call("GET", "/v1/system/capabilities", VIEWER)
    manifest = (caps or {}).get("manifest") or {}
    fingerprint = {
        "commit_sha": git.stdout.strip() or None,
        "config_files_modified": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        "files": file_digests(ROOT),
        "api_image_id": image[0] if image else None,
        "policy_hash": (version or {}).get("policy_hash"),
        "runtime_mode": (version or {}).get("runtime_mode"),
        "manifest_loaded": bool(manifest.get("loaded")),
        "manifest_digest": manifest.get("digest"),
    }
    fingerprint["fingerprint_sha256"] = fingerprint_digest(fingerprint)
    return fingerprint


# ── Steps the faults are built from ─────────────────────────────────────────

def tool_call(tool: str, args: dict, intent: str) -> dict:
    return {"tool_name": tool, "arguments": args, "target_environment": "prod",
            "intent_ref": intent}


def propose(tc: dict) -> tuple[int, Any]:
    return call("POST", "/v1/execution/assess", AGENT, tc)


def approve(item: str, token: str = APPROVER) -> int:
    HUMAN_STEPS.append(f"approve by {token}")
    return call("POST", "/v1/execution/approve", token,
                {"item_id": item, "approval_ttl_seconds": 900})[0]


def execute(item: str, tc: dict) -> tuple[int, Any]:
    return call("POST", "/v1/execution/execute", AGENT, {"item_id": item, "tool_call": tc})


def approved_item(tc: dict, token: str = APPROVER) -> str:
    status, body = propose(tc)
    if status != 200 or not body.get("review_item_id"):
        raise RuntimeError(f"assess refused the setup call: {status} {body}")
    if approve(body["review_item_id"], token) != 200:
        raise RuntimeError("approval of the setup call failed")
    return str(body["review_item_id"])


def executed(body: Any) -> bool | None:
    return ((body or {}).get("tool_execution") or {}).get("executed") if isinstance(body, dict) else None


# ── Faults ──────────────────────────────────────────────────────────────────

class Fault:
    def __init__(self, name: str, expect: str, run: Callable[[dict], bool],
                 intended_writes: int = 0) -> None:
        self.name, self.expect, self.run = name, expect, run
        #: Writes the fault means to complete; used for the completion rate.
        self.intended_writes = intended_writes


def f_restart_between_approve_and_execute(rec: dict) -> bool:
    tc = tool_call("create_work_order", {"wo_id": "WO-1401"}, "WO-1205")
    item = approved_item(tc)
    compose("restart", "api")
    rec["api_back"] = wait_healthy()
    s1, b1 = execute(item, tc)
    s2, _ = execute(item, tc)
    rec.update(execute=s1, executed=executed(b1), replay=s2)
    rec["completed_writes"] = int(executed(b1) is True)
    return s1 == 200 and executed(b1) is True and s2 == 409


def f_spent_grant_stays_spent_across_restart(rec: dict) -> bool:
    tc = tool_call("create_work_order", {"wo_id": "WO-1402"}, "WO-1205")
    item = approved_item(tc)
    s1, b1 = execute(item, tc)
    compose("restart", "api")
    rec["api_back"] = wait_healthy()
    s2, _ = execute(item, tc)
    rec.update(execute=s1, executed=executed(b1), replay_after_restart=s2)
    rec["completed_writes"] = int(executed(b1) is True)
    return executed(b1) is True and s2 == 409


def f_limits_survive_restart(rec: dict) -> bool:
    # valve-travel allows 60 % of travel per hour across every valve. 50 now,
    # a restart, then 11 more must refuse; 10 more must not.
    tc = tool_call("set_valve_position", {"valve": "V-12", "position_pct": 65}, "WO-1204")
    item = approved_item(tc)
    s1, b1 = execute(item, tc)
    compose("restart", "api")
    rec["api_back"] = wait_healthy()
    # The simulated plant restarted at V-12 = 15, so movement is measured from 15.
    over_status, over = propose(tool_call("set_valve_position",
                                          {"valve": "V-12", "position_pct": 26}, "WO-1204"))
    under_status, _ = propose(tool_call("set_valve_position",
                                        {"valve": "V-12", "position_pct": 25}, "WO-1204"))
    rec.update(first_move_executed=executed(b1), over_cap=over_status,
               over_cap_reason=(over or {}).get("detail"), under_cap=under_status)
    rec["completed_writes"] = int(executed(b1) is True)
    return (s1 == 200 and executed(b1) is True and over_status == 409
            and (over or {}).get("detail") == "limit_exceeded" and under_status == 200)


def f_store_outage_during_execute(rec: dict) -> bool:
    tc = tool_call("adjust_setpoint", {"loop": "FIC-220", "value": 121.0}, "WO-1201")
    item = approved_item(tc)
    compose("stop", "postgres")
    IN_FAULT_WINDOW.set()
    try:
        s_exec, b_exec = execute(item, tc)
        s_assess, b_assess = propose(tool_call("create_work_order", {"wo_id": "WO-1403"}, "WO-1205"))
    finally:
        IN_FAULT_WINDOW.clear()
        compose("start", "postgres")
    rec["store_back"] = wait_store()
    s_after, b_after = execute(item, tc)
    s_replay, _ = execute(item, tc)
    result = ((b_after or {}).get("tool_execution") or {}).get("result") or {}
    rec.update(during_execute=s_exec, during_execute_detail=(b_exec or {}).get("detail"),
               during_assess=s_assess, during_assess_detail=(b_assess or {}).get("detail"),
               after=s_after, executed_after=executed(b_after), replay=s_replay,
               old_setpoint_after=result.get("old_setpoint"))
    rec["completed_writes"] = int(executed(b_after) is True)
    unavailable = "durable_state_unavailable"
    # The effect ran once: the old setpoint after recovery is the plant's
    # starting value, so nothing moved it while the store was down.
    return (s_exec == 503 and (b_exec or {}).get("detail") == unavailable
            and s_assess == 503 and (b_assess or {}).get("detail") == unavailable
            and s_after == 200 and executed(b_after) is True
            and result.get("old_setpoint") == 120.0 and s_replay == 409)


def f_concurrent_executions_of_one_approval(rec: dict) -> bool:
    tc = tool_call("create_work_order", {"wo_id": "WO-1404"}, "WO-1205")
    item = approved_item(tc)
    barrier, out = threading.Barrier(4), []

    def go() -> None:
        barrier.wait()
        out.append(execute(item, tc))

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ran = sum(1 for s, b in out if s == 200 and executed(b) is True)
    rec.update(statuses=sorted(s for s, _ in out), executed_count=ran)
    rec["completed_writes"] = ran
    return ran == 1 and sorted(s for s, _ in out) == [200, 409, 409, 409]


def f_same_proposal_twice(rec: dict) -> bool:
    # The pilot's limit policy declares no idempotency.key_arguments, so two
    # separately approved identical proposals are two operations. This fault
    # records that documented behaviour; it is not a guarantee.
    tc = tool_call("create_work_order", {"wo_id": "WO-1405"}, "WO-1205")
    items = [approved_item(tc), approved_item(tc)]
    results = [execute(item, tc) for item in items]
    ran = sum(1 for s, b in results if s == 200 and executed(b) is True)
    rec.update(executed_count=ran, human_approvals=2,
               note="no idempotency key declared: each approval is its own operation")
    rec["completed_writes"] = ran
    return ran == 2


def f_stop_between_approve_and_execute(rec: dict) -> bool:
    tc = tool_call("create_work_order", {"wo_id": "WO-1406"}, "WO-1205")
    item = approved_item(tc)
    HUMAN_STEPS.append("stop")
    s_stop, _ = call("POST", "/v1/execution/stop", SUPERVISOR, {"reason": "fault injection"})
    s1, b1 = execute(item, tc)
    HUMAN_STEPS.append("resume")
    s_resume, _ = call("POST", "/v1/execution/resume", SUPERVISOR, {"reason": "fault injection done"})
    s2, b2 = execute(item, tc)
    rec.update(stop=s_stop, while_stopped=s1, while_stopped_detail=(b1 or {}).get("detail"),
               resume=s_resume, after_resume=s2, executed_after_resume=executed(b2))
    rec["completed_writes"] = int(executed(b2) is True)
    return (s_stop == 200 and s1 == 409 and (b1 or {}).get("detail") == "execution_stopped"
            and s_resume == 200 and s2 == 200 and executed(b2) is True)


def f_tool_fails_after_dispatch_began(rec: dict) -> bool:
    tc = tool_call("close_work_order", {"wo_id": "WO-9999"}, "WO-1203")
    item = approved_item(tc)
    s1, b1 = execute(item, tc)
    te = (b1 or {}).get("tool_execution") or {}
    proposal = (b1 or {}).get("proposal_id", "")
    _, lifecycle = call("GET", f"/v1/execution/proposals/{proposal}", VIEWER)
    _, unresolved = call("GET", "/v1/execution/limits/unresolved", SUPERVISOR)
    ops = [op for op in (unresolved or {}).get("operations", []) if op.get("tool") == "close_work_order"]
    resolved = None
    if ops:
        HUMAN_STEPS.append("resolve unknown outcome")
        resolved = call("POST", "/v1/execution/limits/resolve", SUPERVISOR, {
            "operation_id": ops[0]["operation_id"], "executed": False,
            "evidence_ref": "plant-log:close_work_order:WO-9999",
            "reason": "the tool raised before closing anything"})[0]
    _, after = call("GET", "/v1/execution/limits/unresolved", SUPERVISOR)
    left = [op for op in (after or {}).get("operations", []) if op.get("tool") == "close_work_order"]
    s_replay, _ = execute(item, tc)
    rec.update(execute=s1, executed=te.get("executed"), state_unknown=te.get("state_unknown"),
               refusal=te.get("refusal_reason"), lifecycle_state=(lifecycle or {}).get("current_state"),
               unresolved_before=len(ops), resolve=resolved, unresolved_after=len(left),
               replay=s_replay)
    return (s1 == 200 and te.get("executed") is False and te.get("state_unknown") is True
            and (lifecycle or {}).get("current_state") == "UNKNOWN" and len(ops) == 1
            and resolved == 200 and not left and s_replay == 409)


def f_approver_revoked_after_approval(rec: dict) -> bool:
    # Last: the approver stays revoked for the rest of the stack's life.
    tc = tool_call("create_work_order", {"wo_id": "WO-1407"}, "WO-1205")
    item = approved_item(tc)
    HUMAN_STEPS.append("revoke")
    s_rev, _ = call("POST", "/v1/execution/revoke-principal", SUPERVISOR,
                    {"principal": APPROVER, "reason": "fault injection"})
    s1, b1 = execute(item, tc)
    s_self, _ = call("POST", "/v1/execution/revoke-principal", SUPERVISOR,
                     {"principal": SUPERVISOR, "reason": "self"})
    rec.update(revoke=s_rev, execute=s1, outcome=(b1 or {}).get("outcome"),
               executed=executed(b1), self_revoke=s_self)
    return (s_rev == 200 and s1 == 200 and (b1 or {}).get("outcome") == "approval_invalidated"
            and executed(b1) is not True and s_self == 409)


FAULTS = [
    Fault("Restart between approval and execution", "runs once after the restart",
          f_restart_between_approve_and_execute, intended_writes=1),
    Fault("Spent grant across a restart", "the replay after the restart is refused",
          f_spent_grant_stays_spent_across_restart, intended_writes=1),
    Fault("Cumulative limits across a restart", "the ledger still counts the earlier move",
          f_limits_survive_restart, intended_writes=1),
    Fault("PostgreSQL stopped during a governed write", "503, no effect; runs once after recovery",
          f_store_outage_during_execute, intended_writes=1),
    Fault("Four concurrent executions of one approval", "exactly one runs",
          f_concurrent_executions_of_one_approval, intended_writes=1),
    Fault("The same proposal made and approved twice", "two operations (no key declared)",
          f_same_proposal_twice, intended_writes=2),
    Fault("Stop between approval and execution", "409 while stopped; runs after resume",
          f_stop_between_approve_and_execute, intended_writes=1),
    Fault("Tool fails after dispatch began", "UNKNOWN, reservation held until resolved",
          f_tool_fails_after_dispatch_began),
    Fault("Approver revoked after approving", "approval invalidated, nothing runs",
          f_approver_revoked_after_approval),
]


# ── Measurement ─────────────────────────────────────────────────────────────

def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(q / 100 * len(ordered))))
    return round(ordered[rank - 1], 1)


def latency_summary(latencies: dict[str, list[float]]) -> dict[str, dict[str, Any]]:
    return {route: {"calls": len(v), "p50_ms": percentile(v, 50), "p95_ms": percentile(v, 95),
                    "max_ms": round(max(v), 1), "mean_ms": round(statistics.fmean(v), 1)}
            for route, v in sorted(latencies.items()) if v}


def operations_summary(results: list[dict], human_steps: list[str]) -> dict[str, Any]:
    intended = sum(r.get("intended_writes", 0) for r in results)
    completed = sum(min(r.get("completed_writes", 0), r.get("intended_writes", 0)) for r in results)
    return {
        "intended_writes": intended,
        "completed_writes": completed,
        "completion_rate": round(completed / intended, 3) if intended else None,
        # A write the fault meant to complete that did not: a false refusal.
        "false_refusals": intended - completed,
        "human_steps": len(human_steps),
        "human_steps_by_kind": dict(sorted(
            {k: human_steps.count(k) for k in set(human_steps)}.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence-root", help="write an immutable run directory here")
    args = parser.parse_args()

    if not wait_healthy():
        print("FAILED: the API never became healthy.", file=sys.stderr)
        return 2
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    config = frozen_configuration()
    print(f"Configuration fingerprint: {config['fingerprint_sha256'][:16]}... "
          f"(commit {str(config['commit_sha'])[:8]}, image {str(config['api_image_id'])[:12]})")

    results: list[dict] = []
    print(f"\nInjecting {len(FAULTS)} faults\n" + "-" * 78)
    for fault in FAULTS:
        rec: dict[str, Any] = {"name": fault.name, "expect": fault.expect,
                               "intended_writes": fault.intended_writes}
        try:
            rec["ok"] = bool(fault.run(rec))
        except Exception as exc:  # a fault that cannot be set up is a failure, loudly
            rec.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        results.append(rec)
        print(f"[{'ok  ' if rec['ok'] else 'FAIL'}] {fault.name[:46]:46s} {fault.expect}")

    _, verify = call("GET", "/v1/execution/audit/verify", VIEWER)
    _, cpv = call("GET", "/v1/audit/chain/verify", VIEWER)
    operations = operations_summary(results, HUMAN_STEPS)
    latency = latency_summary(LATENCIES)
    failures = [r for r in results if not r["ok"]]
    print("-" * 78)
    print(f"Faults behaving as specified: {len(results) - len(failures)}/{len(results)}")
    print(f"Writes completed: {operations['completed_writes']}/{operations['intended_writes']}, "
          f"false refusals {operations['false_refusals']}, human steps {operations['human_steps']}")
    print(f"Execution chain valid: {verify.get('valid')} ({verify.get('records_checked')} records); "
          f"envelope chain valid: {cpv.get('chain_valid')}")
    for r in failures:
        print(f"  FAILED {r['name']}: {json.dumps({k: v for k, v in r.items() if k not in ('name',)})[:300]}")

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    chains_ok = bool(verify.get("valid")) and bool(cpv.get("chain_valid"))
    bundle = battery.build_evidence_bundle(
        results, verify=verify, control_plane_verify=cpv,
        suite_id="ot-fault-injection-v1", started_at=started_at, finished_at=finished_at,
        exit_code=0 if not failures and chains_ok else 1,
        limitations=[
            "The plant is simulated inside the API process; a restart resets it while the "
            "limit ledger and the audit chain persist.",
            "One host, one API replica, the SQLite limit ledger; no network partition "
            "between replicas was injected.",
            "The pilot's limit policy declares no idempotency keys, so a proposal approved "
            "twice runs twice.",
            "Latencies are from one local Docker host and are not a performance claim.",
        ])
    bundle["source"]["commit_sha"] = config["commit_sha"] or "unknown"
    bundle["source"]["dirty_worktree"] = config["config_files_modified"]
    # The battery counts tool_execution blocks; these records carry counts instead.
    bundle["summary"]["confirmed_side_effects"] = operations["completed_writes"]
    bundle["frozen_configuration"] = config
    bundle["operations"] = operations
    bundle["latency_ms"] = latency
    if args.evidence_root:
        bundle["run_id"] = f"fault-injection-{time.strftime('%Y-%m-%d', time.gmtime())}-{uuid4().hex[:8]}"
        layout = battery.write_run_directory(bundle, args.evidence_root)
        print(f"\nEvidence: {layout['run_dir']}")
    return 0 if not failures and chains_ok else 1


if __name__ == "__main__":
    sys.exit(main())
