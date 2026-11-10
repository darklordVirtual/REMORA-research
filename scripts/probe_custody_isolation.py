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
TECHNIQUES = ("proc_environ", "proc_task_environ", "proc_mem", "process_vm_readv",
              "proc_maps", "proc_auxv", "proc_io", "proc_cmdline", "proc_status", "proc_fd",
              "proc_cwd", "proc_exe", "proc_root", "signal_0", "ptrace_attach")
#: Readable by any uid on Linux by design; they are run to show they hold no credential.
WORLD_READABLE = ("proc_cmdline", "proc_status")

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
import ctypes, json, os, sys
pid, secret = int(sys.argv[1]), sys.stdin.buffer.read().strip()
libc = ctypes.CDLL(None, use_errno=True)
out = []
def attempt(name, fn):
    try:
        data = fn()
        out.append({"technique": name, "read_credential": secret in data, "error": None})
    except Exception as exc:
        out.append({"technique": name, "read_credential": False, "error": type(exc).__name__})
def regions():
    with open(f"/proc/{pid}/maps") as maps:
        for line in maps:
            span, perms = line.split()[:2]
            if "r" in perms:
                start, end = (int(x, 16) for x in span.split("-"))
                yield start, min(end - start, 1 << 24)
def mem():
    with open(f"/proc/{pid}/mem", "rb", 0) as memory:
        for start, size in regions():
            try:
                memory.seek(start)
                chunk = memory.read(size)
            except (OSError, ValueError, OverflowError):
                continue
            if secret in chunk:
                return chunk
    return b""
class IoVec(ctypes.Structure):
    _fields_ = [("base", ctypes.c_void_p), ("len", ctypes.c_size_t)]
def vm_read(start, size):
    buf = ctypes.create_string_buffer(size)
    local, remote = IoVec(ctypes.addressof(buf), size), IoVec(start, size)
    got = libc.process_vm_readv(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
    if got < 0:
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
    return buf.raw[:got]
def vm_readv():
    try:
        spans = list(regions())
    except PermissionError:
        return vm_read(0x10000, 4096)   # no map to aim with: the call itself must be refused
    for start, size in spans:
        try:
            chunk = vm_read(start, min(size, 1 << 20))
        except PermissionError:
            raise
        except OSError:
            continue
        if secret in chunk:
            return chunk
    return b""
def ptrace():
    PTRACE_ATTACH, PTRACE_DETACH = 16, 17
    if libc.ptrace(PTRACE_ATTACH, pid, None, None) != 0:
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
    os.waitpid(pid, 0x40000000)        # __WALL: the tracee stops
    try:
        return open(f"/proc/{pid}/environ", "rb").read()
    finally:
        libc.ptrace(PTRACE_DETACH, pid, None, None)
read = lambda name: (lambda: open(f"/proc/{pid}/{name}", "rb").read())
attempt("proc_environ", read("environ"))
attempt("proc_task_environ", read(f"task/{pid}/environ"))
attempt("proc_mem", mem)
attempt("process_vm_readv", vm_readv)
attempt("proc_maps", read("maps"))
attempt("proc_auxv", read("auxv"))
attempt("proc_io", read("io"))
attempt("proc_cmdline", read("cmdline"))
attempt("proc_status", read("status"))
attempt("proc_fd", lambda: " ".join(os.listdir(f"/proc/{pid}/fd")).encode())
attempt("proc_cwd", lambda: os.readlink(f"/proc/{pid}/cwd").encode())
attempt("proc_exe", lambda: os.readlink(f"/proc/{pid}/exe").encode())
attempt("proc_root", lambda: os.readlink(f"/proc/{pid}/root").encode())
attempt("signal_0", lambda: (os.kill(pid, 0), b"")[1])
attempt("ptrace_attach", ptrace)
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
        # The credential reaches the agent on stdin, so that it is in no
        # command line, and a failed agent is reported without its output.
        agent = subprocess.run(
            [sys.executable, "-c", AGENT, str(holder.pid)], input=secret,
            env={"PATH": env["PATH"]}, user=AGENT_UID, group=AGENT_UID, extra_groups=[],
            capture_output=True, text=True, timeout=60)
        if agent.returncode != 0:
            row.update(holder_started=True, guard=line, agent_failed=agent.returncode)
            return row
        seen = json.loads(agent.stdout)
        row.update(holder_started=True, guard=line, agent_ran_as=seen["uid"],
                   holder_alive_after=holder.poll() is None,
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
    control_attempts = {a["technique"]: a for a in control.get("attempts") or ()}
    split_attempts = {a["technique"]: a for a in split.get("attempts") or ()}
    leaked = sorted(t for t, a in control_attempts.items() if a["read_credential"])
    checks = {
        "control_leaks": bool(control.get("holder_started") and control.get("credential_read")),
        "split_starts_under_strict_profile": bool(split.get("holder_started")),
        "split_uids_differ": split.get("holder_uid") != split.get("agent_uid")
                             and control.get("holder_uid") == control.get("agent_uid"),
        "split_agent_ran_as_agent_uid": split.get("agent_ran_as") == AGENT_UID,
        # Every technique ran in both layouts while the holder was alive, so a
        # denial is a denial and not a holder that had already gone.
        "every_technique_ran_against_a_live_holder": (
            [a["technique"] for a in control.get("attempts") or ()] == list(TECHNIQUES)
            and [a["technique"] for a in split.get("attempts") or ()] == list(TECHNIQUES)
            and control.get("holder_alive_after") is True
            and split.get("holder_alive_after") is True),
        "split_reads_nothing": bool(split.get("holder_started"))
                               and split.get("credential_read") is False,
        # What leaked under one uid is refused by the kernel under two, not
        # missing, empty or failing for another reason.
        "what_leaked_in_the_control_is_denied_in_the_split": bool(leaked) and all(
            split_attempts.get(t, {}).get("error") == "PermissionError" for t in leaked),
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
    name = "remora-custody-probe-" + secrets.token_hex(6)
    try:
        run = subprocess.run(
            ["docker", "run", "--rm", "--name", name, "--network", "none",
             "-v", f"{ROOT}:/src:ro", IMAGE,
             "python", "/src/scripts/probe_custody_isolation.py", "--inside", "--src", "/src"],
            capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        # The timeout stops the docker client, not the container.
        subprocess.run(["docker", "kill", name], capture_output=True)
        print("the probe container did not finish in 300 s and was killed", file=sys.stderr)
        return 2
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
