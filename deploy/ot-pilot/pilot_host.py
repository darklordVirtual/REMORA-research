# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Helpers for the assessor's runners on the host (boundary and effect runs).

The host is the operator and assessor domain: it holds deploy/ot-pilot/.env
and drives the stack with ``docker compose``. Nothing here runs in the agent
zone. The plant is read through ``docker compose exec plant`` with the
container's own read token, so the host adds no route to the plant.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = os.environ.get("REMORA_PILOT_URL", "http://127.0.0.1:8080")
VERIFIER_URL = os.environ.get("REMORA_PILOT_VERIFIER_URL", "http://127.0.0.1:8082")
COMPOSE = os.environ.get("REMORA_PILOT_COMPOSE", str(HERE / "docker-compose.yml"))

AGENT = os.environ.get("OT_TOKEN_AGENT", "")
APPROVER = os.environ.get("OT_TOKEN_APPROVER", "")
VIEWER = os.environ.get("OT_TOKEN_VIEWER", "")
#: The dispatch listing needs verify_effect, which of the host's tokens only
#: the supervisor (admin) holds.
SUPERVISOR = os.environ.get("OT_TOKEN_SUPERVISOR", "")


def require_tokens() -> None:
    missing = [n for n, v in (("OT_TOKEN_AGENT", AGENT), ("OT_TOKEN_APPROVER", APPROVER),
                              ("OT_TOKEN_VIEWER", VIEWER), ("OT_TOKEN_SUPERVISOR", SUPERVISOR))
               if not v]
    if missing:
        raise SystemExit(f"missing pilot credentials {missing}: source deploy/ot-pilot/.env")


def call(method: str, path: str, token: str, body: Any = None,
         base: str = BASE) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except ValueError:
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:300]}
    except (urllib.error.URLError, OSError) as exc:
        return 0, {"error": str(exc)}


def compose(*args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    done = subprocess.run(["docker", "compose", "-f", COMPOSE, *args], capture_output=True,
                          text=True, env={**os.environ, **(env or {})}, check=False)
    if check and done.returncode:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {done.stderr[-800:]}")
    return done.stdout


def plant_dump() -> dict[str, Any]:
    """The plant's journal and digests, read inside the plant container."""
    return json.loads(compose("exec", "-T", "plant", "python", "/plant/plant_dump.py"))


def plant_health() -> dict[str, Any]:
    """The plant's /health, including the faults it reports active."""
    code = ("import json,urllib.request;print(urllib.request.urlopen("
            "'http://127.0.0.1:9100/health',timeout=5).read().decode())")
    return json.loads(compose("exec", "-T", "plant", "python", "-c", code))


def dispatches() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    after = 0
    while True:
        status, body = call("GET", f"/v1/execution/dispatches?after_sequence={after}&limit=500",
                            SUPERVISOR)
        if status != 200:
            raise RuntimeError(f"dispatch listing answered {status}: {body}")
        rows.extend(body["dispatches"])
        if not body["dispatches"]:
            return rows
        after = int(body["next_after_sequence"])


def governed_write(tool: str, arguments: dict[str, Any], intent: str) -> dict[str, Any]:
    """Assess as the agent, approve as the approver, execute as the agent."""
    tc = {"tool_name": tool, "arguments": arguments, "target_environment": "prod",
          "intent_ref": intent}
    s_assess, assessed = call("POST", "/v1/execution/assess", AGENT, tc)
    out: dict[str, Any] = {"tool": tool, "arguments": arguments, "intent_ref": intent,
                           "assess_status": s_assess, "decision": assessed.get("decision"),
                           "reasons": assessed.get("reasons"),
                           "proposal_id": assessed.get("proposal_id"),
                           "detail": assessed.get("detail")}
    item = assessed.get("review_item_id")
    if not item:
        return out
    s_approve, _ = call("POST", "/v1/execution/approve", APPROVER,
                        {"item_id": item, "approval_ttl_seconds": 600})
    s_exec, executed = call("POST", "/v1/execution/execute", AGENT,
                            {"item_id": item, "tool_call": tc})
    te = executed.get("tool_execution") or {}
    out.update(approve_status=s_approve, execute_status=s_exec,
               outcome=executed.get("outcome"), executed=te.get("executed"),
               tool_result=te.get("result"))
    return out


def wait_for_effect(proposal_id: str, *, timeout_s: float = 30.0,
                    settle: tuple[str, ...] = ("EFFECT_VERIFIED", "EFFECT_MISMATCH",
                                               "EFFECT_UNSUPPORTED")) -> dict[str, Any]:
    """The proposal's effect section once it settles, or as it stands at timeout."""
    deadline = time.time() + timeout_s
    effect: dict[str, Any] = {}
    while time.time() < deadline:
        status, body = call("GET", f"/v1/execution/proposals/{proposal_id}", VIEWER)
        effect = (body or {}).get("effect") or {}
        if effect.get("status") in settle:
            break
        time.sleep(1)
    status, body = call("GET", f"/v1/execution/proposals/{proposal_id}", VIEWER)
    return {"current_state": (body or {}).get("current_state"),
            "effect": {k: ((body or {}).get("effect") or {}).get(k)
                       for k in ("status", "reason_code", "vantage", "scope",
                                 "verdict_source", "verifier_identity", "verified_at",
                                 "effect_state")},
            "history": [{k: h.get(k) for k in ("status", "reason_code", "vantage",
                                               "verified_at")}
                        for h in (((body or {}).get("effect") or {}).get("history") or [])]}


def verifier_report() -> dict[str, Any]:
    status, body = call("GET", "/report", "", base=VERIFIER_URL)
    return body if status == 200 else {"error": status, "body": body}


def wait_healthy(timeout_s: int = 120) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, _ = call("GET", "/v1/ready", AGENT)
        if status == 200:
            return True
        time.sleep(2)
    return False


def env_secret_values() -> dict[str, str]:
    """Every value of 16+ characters in deploy/ot-pilot/.env, by name."""
    values: dict[str, str] = {}
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            if len(value.strip()) >= 16:
                values[name.strip()] = value.strip()
    return values
