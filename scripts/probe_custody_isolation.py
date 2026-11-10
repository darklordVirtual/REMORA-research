#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Probe custody rule 4 with real OS users, and with a same-user control beside it.

    python scripts/probe_custody_isolation.py --out RESULT.json

AACP finding E-01: an agent process read the executor's effect credential from
its launch environment because both ran as one OS user. Custody rule 4
(remora/enforcement/custody.py) makes the credential holder declare its
isolation, and checks ``os_user`` against the uid it runs as. The conformance
tests K20 to K27 exercise that check with ``os.getuid`` replaced, which tests
the guard and not the isolation. This probe runs both for real, in one Linux
container and one PID namespace, which is the hardest case for a uid split:

``same_user``
    The control. Holder and agent run as one uid under the ``review``
    profile. The agent is expected to read the credential.
``os_user``
    Holder and agent run as different uids under ``controlled_pilot``. The
    agent tries every technique below and is expected to read nothing.
``os_user_declared_but_shared``
    The holder declares ``os_user`` and runs as the agent's uid. The guard is
    expected to refuse to start it.
``os_user_as_root``
    The holder declares ``os_user`` and runs as root. Expected: refused.

A layout whose control does not leak proves nothing, so the result is
``isolation_shown`` only when the same-user agent read the credential and the
other-user agent did not.

The credential is synthetic and generated per run. The host entry point
starts the container with the repository mounted read-only; ``--inside`` is
what runs in it, as root, and is the only part that changes uid. Scope: one
kernel, one container runtime, the techniques listed. It says nothing about a
container escape, a shared volume, or a credential fetched from a metadata
service, and it is not the OT pilot, whose compose file declares no isolation.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "python:3.13-slim"
AGENT_UID, HOLDER_UID = 10001, 10003
CREDENTIAL_ENV = "PROBE_EFFECT_TOKEN"
TECHNIQUES = ("proc_environ", "proc_mem", "proc_cmdline", "proc_fd", "proc_cwd", "signal_0")

HOLDER = r"""
import sys, time
from remora.enforcement.custody import CustodyViolation, assert_custody_split
try:
    role = assert_custody_split()
except CustodyViolation as exc:
    print("REFUSED " + " ".join(str(exc).split()), flush=True)
    sys.exit(3)
print("READY " + role, flush=True)
time.sleep(120)
"""

AGENT = r"""
import json, os, sys
pid, secret = int(sys.argv[1]), sys.argv[2].encode()
out = []
def attempt(name, fn):
    try:
        data = fn()
        out.append({"technique": name, "read_credential": secret in data, "error": None})
    except Exception as exc:
        out.append({"technique": name, "read_credential": False, "error": type(exc).__name__})
def mem():
    found = b""
    with open(f"/proc/{pid}/maps") as maps, open(f"/proc/{pid}/mem", "rb", 0) as memory:
        for line in maps:
            span, perms = line.split()[:2]
            if "r" not in perms:
                continue
            start, end = (int(x, 16) for x in span.split("-"))
            try:
                memory.seek(start)
                chunk = memory.read(min(end - start, 1 << 24))
            except (OSError, ValueError, OverflowError):
                continue
            if secret in chunk:
                return chunk
    return found
attempt("proc_environ", lambda: open(f"/proc/{pid}/environ", "rb").read())
attempt("proc_mem", mem)
attempt("proc_cmdline", lambda: open(f"/proc/{pid}/cmdline", "rb").read())
attempt("proc_fd", lambda: " ".join(os.listdir(f"/proc/{pid}/fd")).encode())
attempt("proc_cwd", lambda: os.readlink(f"/proc/{pid}/cwd").encode())
attempt("signal_0", lambda: (os.kill(pid, 0), b"")[1])
print(json.dumps({"uid": os.getuid(), "attempts": out}))
"""

LAYOUTS: tuple[dict[str, Any], ...] = (
    {"name": "same_user", "profile": "review", "isolation": "same_user",
     "holder_uid": AGENT_UID},
    {"name": "os_user", "profile": "controlled_pilot", "isolation": "os_user",
     "holder_uid": HOLDER_UID},
    {"name": "os_user_declared_but_shared", "profile": "controlled_pilot",
     "isolation": "os_user", "holder_uid": AGENT_UID},
    {"name": "os_user_as_root", "profile": "controlled_pilot", "isolation": "os_user",
     "holder_uid": 0},
)


def run_layout(layout: dict[str, Any], src: Path) -> dict[str, Any]:
    """Start the holder under the layout's uid, then the agent; return what each did."""
    secret = "probe-" + secrets.token_hex(16)
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1",
        "REMORA_RUNTIME_PROFILE": layout["profile"],
        "REMORA_EXECUTION_DOMAIN_ROLE": "executor",
        "REMORA_EXECUTION_ISOLATION": layout["isolation"],
        "REMORA_AGENT_OS_UIDS": str(AGENT_UID),
        "REMORA_EFFECT_CREDENTIAL_ENV_NAMES": CREDENTIAL_ENV,
        CREDENTIAL_ENV: secret,
        # Rule 3 wants the executor to hold a lease verify key. The guard checks
        # that it is present; no lease is verified here, so the bytes are random.
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC": secrets.token_hex(32),
    }
    holder = subprocess.Popen([sys.executable, "-c", HOLDER], env=env, user=layout["holder_uid"],
                              group=layout["holder_uid"], extra_groups=[],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None
        line = holder.stdout.readline().strip()
        row: dict[str, Any] = {"layout": layout["name"], "profile": layout["profile"],
                               "declared_isolation": layout["isolation"],
                               "holder_uid": layout["holder_uid"], "agent_uid": AGENT_UID}
        if not line.startswith("READY"):
            holder.wait(timeout=10)
            stderr = holder.stderr.read() if holder.stderr else ""
            row.update(holder_started=False, guard=line or "no output",
                       holder_stderr_tail=stderr.strip().splitlines()[-1:] if stderr else [])
            return row
        agent = subprocess.run(
            [sys.executable, "-c", AGENT, str(holder.pid), secret],
            env={"PATH": env["PATH"]}, user=AGENT_UID, group=AGENT_UID, extra_groups=[],
            capture_output=True, text=True, timeout=60, check=True)
        seen = json.loads(agent.stdout)
        row.update(holder_started=True, guard=line, agent_ran_as=seen["uid"],
                   attempts=seen["attempts"],
                   credential_read=any(a["read_credential"] for a in seen["attempts"]))
        return row
    finally:
        holder.kill()
        holder.wait(timeout=10)


def _refused_for(row: dict[str, Any], phrase: str) -> bool:
    """The guard refused this layout, and for the isolation reason, not another rule."""
    guard = str(row.get("guard", ""))
    return (row.get("holder_started") is False and guard.startswith("REFUSED")
            and "the process holding the effect credentials runs as" in guard
            and phrase in guard)


def verdict(layouts: list[dict[str, Any]]) -> dict[str, Any]:
    """What the four layouts show together. Pure, so it is tested without a container."""
    by = {row["layout"]: row for row in layouts}
    control = by.get("same_user", {})
    split = by.get("os_user", {})
    checks = {
        "control_leaks": bool(control.get("holder_started") and control.get("credential_read")),
        "split_starts_under_strict_profile": bool(split.get("holder_started")),
        "split_agent_ran_as_agent_uid": split.get("agent_ran_as") == AGENT_UID,
        "split_reads_nothing": bool(split.get("holder_started"))
                               and split.get("credential_read") is False,
        "shared_uid_refused_by_guard": _refused_for(
            by.get("os_user_declared_but_shared", {}), f"uid {AGENT_UID}"),
        "root_holder_refused_by_guard": _refused_for(by.get("os_user_as_root", {}), "root"),
    }
    return {"checks": checks, "isolation_shown": all(checks.values()),
            "reading": "A control that does not leak proves nothing: isolation_shown needs "
                       "the same-user agent to read the credential and the other-user agent "
                       "to read nothing with the same techniques."}


def inside(src: Path) -> dict[str, Any]:
    if os.getuid() != 0:
        raise SystemExit("--inside changes uid and must start as root in the probe container")
    layouts = [run_layout(layout, src) for layout in LAYOUTS]
    return {"schema": "remora-custody-isolation-probe/v1",
            "finding": "AACP-E-01", "rule": "remora/enforcement/custody.py rule 4",
            "kernel": platform.release(), "python": platform.python_version(),
            "pid_namespace": "shared by holder and agent",
            "techniques": list(TECHNIQUES), "layouts": layouts, **verdict(layouts)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--inside", action="store_true", help="run in the container, as root")
    parser.add_argument("--src", type=Path, default=Path("/src"))
    args = parser.parse_args(argv)
    if args.inside:
        print(json.dumps(inside(args.src), indent=2, sort_keys=True))
        return 0
    started = time.time()
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{ROOT}:/src:ro", IMAGE,
         "python", "/src/scripts/probe_custody_isolation.py", "--inside", "--src", "/src"],
        capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        print(run.stderr, file=sys.stderr)
        return run.returncode
    result = json.loads(run.stdout)
    result["container"] = {"image": IMAGE, "network": "none", "repository_mount": "read-only",
                           "seconds": round(time.time() - started, 1)}
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: isolation_shown={result['isolation_shown']}")
    else:
        sys.stdout.write(text)
    return 0 if result["isolation_shown"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
