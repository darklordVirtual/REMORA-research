# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The init-review scaffold, run as three real processes under review/v2.

Security programme stage I (final adversarial retest, 2026-10-07). Every
other test exercises one domain in-process. This one starts the authority,
the execution domain and the effect domain as separate uvicorn processes with
the env files ``remora init-review`` writes, and drives a mediated tool call
through all three: assess, human approval, a v2 grant, a v2 lease forwarded to
the executor, the tool's one mediated effect served by the effect domain.

Running it found three defects that every in-process test missed: the
authority built a tool dispatcher before forwarding (#785), the scaffold's
reviewer could not approve its own demo tool and its authority named no
execution endpoint, and no runtime was bound into a lease without an
execution context, so a strict executor refused every call.

The probes then attack the running system: replaying the approval, presenting
the operator's credential to the executor, calling the effect domain without
a dispatched lease, and widening the tenant by header.
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
pytest.importorskip("uvicorn")
pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parents[1]
CALL = {"tool_name": "send_notification",
        "arguments": {"to": "ops@example.com", "subject": "deploy done"},
        "target_environment": "staging", "intent_ref": "wo-demo-1",
        "task_type": "notify", "schema_valid": True}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _env_file(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("export "):
            key, _, raw = line[len("export "):].partition("=")
            env[key] = shlex.split(raw)[0]
    return env


class Deployment:
    def __init__(self, base: Path) -> None:
        from remora.scaffold import init_review

        self.cfg = base / ".remora"
        init_review(self.cfg)
        self.ports = {name: _free_port() for name in ("authority", "executor", "effect")}
        self.procs: dict[str, subprocess.Popen] = {}
        self.logs: list = []
        self.base = base
        self.executor_env = _env_file(self.cfg / "executor.env")

    def _env(self, name: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("REMORA_")}
        env.update(_env_file(self.cfg / f"{name}.env"))
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(self.cfg)])
        env["REMORA_EXECUTION_ENDPOINT"] = f"http://127.0.0.1:{self.ports['executor']}"
        if name == "executor":
            env["REMORA_EFFECT_ENDPOINT"] = f"http://127.0.0.1:{self.ports['effect']}"
        if name != "authority":
            env.pop("REMORA_EXECUTION_ENDPOINT")
        return env

    def start(self) -> None:
        for name in ("effect", "executor", "authority"):
            log = open(self.base / f"{name}.log", "w", encoding="utf-8")  # noqa: SIM115
            self.logs.append(log)  # closed in stop(), after the process exits
            self.procs[name] = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "servers.api:app",
                 "--port", str(self.ports[name])],
                env=self._env(name), cwd=self.base, stdout=log, stderr=subprocess.STDOUT)
            self._wait(name)

    def _wait(self, name: str) -> None:
        for _ in range(240):
            if self.procs[name].poll() is not None:
                raise RuntimeError(f"{name} exited:\n{self.log(name)}")
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{self.ports[name]}/v1/health", timeout=1)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        raise RuntimeError(f"{name} did not start:\n{self.log(name)}")

    def log(self, name: str) -> str:
        return (self.base / f"{name}.log").read_text(encoding="utf-8", errors="replace")[-4000:]

    def stop(self) -> None:
        for proc in self.procs.values():
            proc.terminate()
        for proc in self.procs.values():
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        for log in self.logs:
            log.close()

    def token(self, name: str) -> str:
        return (self.cfg / "keys" / name).read_text(encoding="utf-8").strip()

    def post(self, domain: str, path: str, token: str, body: dict,
             headers: dict | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.ports[domain]}{path}", data=json.dumps(body).encode(),
            method="POST", headers={"Content-Type": "application/json",
                                    "Authorization": f"Bearer {token}", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, json.loads(raw) if raw else {}

    def outbox(self) -> list[dict]:
        path = self.cfg / "state" / "outbox.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def deployment(tmp_path_factory):
    base = tmp_path_factory.mktemp("strict-v2-e2e")
    previous = os.getcwd()
    os.chdir(base)
    try:
        dep = Deployment(base)
        dep.start()
        yield dep
    finally:
        if "dep" in locals():
            dep.stop()
        os.chdir(previous)


@pytest.fixture(scope="module")
def executed(deployment):
    """One mediated call, assessed, approved by a human and executed."""
    operator, reviewer = deployment.token("operator_token"), deployment.token("reviewer_token")
    status, assessed = deployment.post("authority", "/v1/execution/assess", operator, CALL)
    assert status == 200, assessed
    item = assessed["review_item_id"]
    status, approved = deployment.post("authority", "/v1/execution/approve", reviewer,
                                       {"item_id": item})
    assert status == 200, approved
    status, body = deployment.post("authority", "/v1/execution/execute", operator,
                                   {"item_id": item, "tool_call": CALL})
    assert status == 200, (body, deployment.log("executor"), deployment.log("effect"))
    return item, body


def test_a_mediated_call_runs_through_all_three_domains(deployment, executed) -> None:
    _, body = executed
    run = body["tool_execution"]
    assert run["executed"], run
    assert body["execution_grant"]["format"] == "v2"
    assert run["nested_effects"]["mediated"] and run["nested_effects"]["by_state"] == {
        "EXECUTED": 1}
    (child,) = run["effect_graph"]["children"]
    assert (child["capability"], child["resource"]) == ("notification.send",
                                                         "notification://outbox")
    assert deployment.outbox() == [
        {**deployment.outbox()[0], "to": "ops@example.com", "subject": "deploy done"}]


def test_replaying_the_approval_runs_nothing_twice(deployment, executed) -> None:
    item, _ = executed
    status, body = deployment.post("authority", "/v1/execution/execute",
                                   deployment.token("operator_token"),
                                   {"item_id": item, "tool_call": CALL})
    assert not (status == 200 and body.get("tool_execution", {}).get("executed"))
    assert len(deployment.outbox()) == 1


def test_the_executor_refuses_the_operator_credential(deployment, executed) -> None:
    """The authority's caller credential is not the dispatch hop's."""
    status, body = deployment.post("executor", "/v1/execution/dispatch-leased",
                                   deployment.token("operator_token"),
                                   {"lease": {}, "tool_call": CALL})
    assert status in (401, 403), body


def test_the_effect_domain_refuses_a_lease_never_dispatched(deployment, executed) -> None:
    effect_token = deployment.executor_env["REMORA_EFFECT_TOKEN"]
    forged = {"tenant_id": "default", "tool_name": "send_notification", "nonce": "n-1",
              "signature": "AAAA", "is_signed": True, "sig_alg": "ed25519-domain-v2"}
    status, body = deployment.post("effect", "/v1/execution/effects", effect_token, {
        "lease": forged, "capability_set": {}, "capability": "notification.send",
        "resource": "notification://outbox", "arguments": {"to": "x@example.com"}})
    assert body.get("state") != "EXECUTED", body
    assert len(deployment.outbox()) == 1


def test_the_tenant_cannot_be_widened_by_header(deployment, executed) -> None:
    status, _ = deployment.post("authority", "/v1/execution/assess",
                                deployment.token("operator_token"), CALL,
                                headers={"X-Remora-Tenant": "another-tenant"})
    assert status == 403
