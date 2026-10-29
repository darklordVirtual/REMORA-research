# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Observe what a tool implementation reaches, in a fresh interpreter.

Slice 1 of effect contract verification
(``docs/design/effect-contract-verification-v1.md``). A signed ToolSpec says
what an implementation reaches; this module watches what it does, for bounded
calls, under Python's audit hooks (PEP 578), and reports the effects in a
normalised vocabulary. It does not compare them with a spec and gives no
verdict: that is slice 2.

How it observes
---------------
Each observation runs in a new interpreter, because an audit hook cannot be
removed. The hook is installed before the tool's module is imported, so the
``load`` phase (the import) and the ``call`` phase (each case) are recorded
apart. An effect performed at import time is an effect.

What it cannot see
------------------
An audit hook sees Python calling the standard library and nothing lower.
These are reported as ``blinding`` events, never silently dropped, and a case
that has one cannot support "no undeclared effect" later:

- ``native_code``: ``ctypes`` loading a library, or a non-standard-library
  extension module imported during the observation;
- ``observer_tampering``: the tool installing an audit hook of its own,
  replacing channel functions or ``json.dumps``/``sys.stdout``/``sys.stderr``,
  or replacing or
  closing the event channel (checked by descriptor identity after each
  case — CPython emits no ``os.dup2`` audit event, so a descriptor swap
  that leaves the channel intact is a documented blind spot);
- ``timeout`` and ``crash``: the case did not complete.

A process the tool starts is observed as ``process.spawn``; what that child
does is outside this vantage. Reads are counted, not reported as effects:
reading is not reaching.

This is a same-interpreter diagnostic, not a sandbox for hostile Python.
The closure removes the old public record list; Python frame/closure
introspection and mutation of serializer internals remain outside the
tamper checks. A nonce on this channel authenticates completion only against
stdout forgery, not against code that introspects the harness itself.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = ["EFFECT_CLASSES", "BLINDING", "CaseObservation", "Observation", "observe"]

#: The normalised effect vocabulary. ``fs.write`` covers create, truncate and append.
EFFECT_CLASSES = ("fs.write", "fs.delete", "fs.rename", "fs.mkdir", "process.spawn",
                  "net.connect", "net.resolve", "env.write")
BLINDING = ("native_code", "observer_tampering", "timeout", "crash")

# The harness runs in the child. It is source, not an import, so the child
# loads nothing from REMORA before the hook is installed.
#
# SEC-09 (SR-09): events stream to the parent over an inherited pipe, one
# JSON line each, from inside the hook. Nothing is stored in __main__
# globals, closing the direct ``__main__.records.clear()`` attack. This
# does not isolate the closure against Python introspection. Every case ends with a
# terminator carrying a per-run nonce the parent generated; a missing or
# mismatched terminator is blinding, never a clean run, and stdout carries
# nothing the parent trusts (pre-fix PoC: forged @@OBSERVATION@@ marker plus
# os._exit(0)).
_HARNESS = r'''
import json, os, sys, sysconfig, time


def _main():
    spec = json.loads(sys.stdin.read())
    sys.path[:0] = spec["path"]
    nonce = spec["nonce"]
    efd = spec["event_fd"]
    # Pinned references: a tool that replaces json.dumps or sys.stdout after
    # this point does not reach the channel, and the swap is reported.
    _dumps = json.dumps
    _write = os.write
    _fstat = os.fstat
    _stdout = sys.stdout
    _stderr = sys.stderr
    state = {"phase": "load", "reads": 0}

    def emit(obj):
        try:
            _write(efd, _dumps(obj).encode() + b"\n")
        except Exception:
            pass

    def _note(cls, detail, kind="effect"):
        emit({"ev": "event", "phase": state["phase"], "kind": kind,
              "class": cls, "detail": detail})

    _STD = tuple(os.path.normcase(os.path.abspath(p)) for p in {
        sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["platstdlib"]} if p)
    _WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

    def _hook(event, args):
        try:
            if event == "open":
                path, mode, flags = (list(args) + [None, None, None])[:3]
                writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                    isinstance(flags, int) and flags & _WRITE_FLAGS)
                if writes:
                    _note("fs.write", str(path))
                else:
                    state["reads"] += 1
            elif event in ("os.remove", "os.rmdir", "shutil.rmtree"):
                _note("fs.delete", str(args[0]))
            elif event in ("os.rename",):
                _note("fs.rename", f"{args[0]} -> {args[1]}")
            elif event == "os.mkdir":
                _note("fs.mkdir", str(args[0]))
            elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
                           "os.spawn", "os.fork", "os.forkpty", "os.startfile"):
                _note("process.spawn", str(args[0])[:200])
            elif event in ("socket.connect", "socket.sendto", "http.client.connect"):
                _note("net.connect", str(args[1] if event != "http.client.connect" else args[1:3])[:200])
            elif event == "urllib.Request":
                _note("net.connect", str(args[0])[:200])
            elif event in ("socket.getaddrinfo", "socket.gethostbyname"):
                _note("net.resolve", str(args[0])[:200])
            elif event in ("os.putenv", "os.unsetenv"):
                _note("env.write", str(args[0]))
            elif event.startswith("ctypes.dlopen"):
                _note("native_code", str(args[0])[:200], "blinding")
            elif event == "sys.addaudithook":
                _note("observer_tampering", "the tool installed an audit hook", "blinding")
            elif event == "import":
                filename = args[1] if len(args) > 1 else None
                if isinstance(filename, str) and filename.lower().endswith((".so", ".pyd", ".dylib")):
                    where = os.path.normcase(os.path.abspath(filename))
                    if not where.startswith(_STD):
                        _note("native_code", where, "blinding")
        except Exception as exc:  # the hook must never raise into the tool
            _note("crash", f"observer error: {type(exc).__name__}", "blinding")

    sys.addaudithook(_hook)

    # CPython emits no os.dup2 audit event, so descriptor-table attacks are
    # caught structurally: the event fd's identity is checked after each
    # case. A tool that dup2's over the channel (or closes it) turns every
    # later write into a missing terminator, which the parent reports as
    # blinding — but the fstat check names it earlier and precisely.
    _fd_identity = _fstat(efd)

    def _integrity():
        """Channel self-check after each case: a replaced serialiser, stream
        or event descriptor is tampering, reported as blinding, never
        papered over."""
        if os.write is not _write or os.fstat is not _fstat:
            _note("observer_tampering", "the tool replaced channel functions", "blinding")
        if json.dumps is not _dumps:
            _note("observer_tampering", "the tool replaced json.dumps", "blinding")
        if sys.stdout is not _stdout:
            _note("observer_tampering", "the tool replaced sys.stdout", "blinding")
        if sys.stderr is not _stderr:
            _note("observer_tampering", "the tool replaced sys.stderr", "blinding")
        try:
            now = _fstat(efd)
            if (now.st_dev, now.st_ino) != (_fd_identity.st_dev, _fd_identity.st_ino):
                _note("observer_tampering", "the event descriptor was replaced", "blinding")
        except OSError:
            _note("observer_tampering", "the event descriptor was closed", "blinding")

    try:
        import importlib
        module = importlib.import_module(spec["module"])
        fn = getattr(module, spec["function"])
        _integrity()
        emit({"ev": "load_end", "completed": True, "reads": state["reads"]})
    except BaseException as exc:
        fn = None
        _integrity()
        emit({"ev": "load_end", "completed": False,
              "error": f"{type(exc).__name__}: {exc}"[:300], "reads": state["reads"]})

    for index, case in enumerate(spec["cases"] if fn is not None else []):
        state["phase"] = f"call:{index}"
        state["reads"] = 0
        emit({"ev": "case_begin", "index": index})
        raised = ""
        try:
            fn(case)
        except BaseException as exc:
            raised = f"{type(exc).__name__}"
        _integrity()
        emit({"ev": "case_end", "index": index, "nonce": nonce,
              "raised": raised, "reads": state["reads"]})
    emit({"ev": "end", "nonce": nonce})


try:
    _main()
except BaseException:
    # A dead harness reports nothing; the parent treats the missing
    # terminator as blinding, never as a clean run.
    pass
'''


def _child_env(extra: Mapping[str, str] | None, workdir: str) -> dict[str, str]:
    """Allowlisted environment for the observed child (SR-16 / SEC-09).

    The observed code no longer inherits the parent process environment —
    signing keys, DSNs and PYTHONPATH stay out. ``extra`` is caller-supplied
    additions (merged over the allowlist), not a full replacement; TMPDIR
    always points at the child's fresh working directory.
    """
    base = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": os.environ.get("LANG", "C"),
        "LC_ALL": os.environ.get("LC_ALL", "C"),
    }
    if extra:
        base.update(extra)
    base["TMPDIR"] = workdir
    return base


@dataclass(frozen=True)
class CaseObservation:
    """What one phase did. ``effects`` and ``blinding`` are (class, detail) pairs."""

    phase: str
    completed: bool
    effects: tuple[tuple[str, str], ...] = ()
    blinding: tuple[tuple[str, str], ...] = ()
    reads: int = 0
    raised: str = ""

    @property
    def effect_classes(self) -> frozenset[str]:
        return frozenset(c for c, _ in self.effects)

    @property
    def blinded(self) -> bool:
        return bool(self.blinding) or not self.completed


@dataclass(frozen=True)
class Observation:
    """One observer run over one callable: the import, then each case."""

    module: str
    function: str
    vantage: str
    interpreter: str
    platform: str
    load: CaseObservation
    cases: tuple[CaseObservation, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        def one(c: CaseObservation) -> dict[str, Any]:
            return {"phase": c.phase, "completed": c.completed, "effects": [list(e) for e in c.effects],
                    "blinding": [list(b) for b in c.blinding], "reads": c.reads, "raised": c.raised}
        return {"module": self.module, "function": self.function, "vantage": self.vantage,
                "interpreter": self.interpreter, "platform": self.platform,
                "load": one(self.load), "cases": [one(c) for c in self.cases]}


def _phase(raw: Mapping[str, Any], name: str) -> CaseObservation:
    records = raw.get("records", [])
    return CaseObservation(
        phase=name, completed=bool(raw.get("completed")),
        effects=tuple((r["class"], r["detail"]) for r in records if r["kind"] == "effect"),
        blinding=tuple((r["class"], r["detail"]) for r in records if r["kind"] == "blinding"),
        reads=int(raw.get("reads", 0)), raised=str(raw.get("raised", "")))


def _blind_all(module: str, function: str, cases: Sequence[Any], interpreter: str,
               platform: str, cls: str, detail: str) -> Observation:
    """Every phase blinded with the same cause: timeout, crash or tamper."""
    load = CaseObservation(phase="load", completed=False, blinding=((cls, detail),))
    return Observation(module, function, "python_audit_hook", interpreter, platform, load,
                       tuple(CaseObservation(phase=f"call:{i}", completed=False,
                                             blinding=((cls, "not reached"),))
                             for i in range(len(cases))))


def observe(module: str, function: str, cases: Sequence[Any], *, timeout_s: float = 30.0,
            path: Sequence[str] = (), env: Mapping[str, str] | None = None) -> Observation:
    """Import ``module`` and call ``function(case)`` for each case, under observation.

    Runs in a fresh, isolated (``-I``) interpreter with ``path`` prepended to
    ``sys.path``, a fresh working directory and an allowlisted environment
    (SR-16). Events arrive over an inherited pipe, each case closing with a
    nonce terminator (SR-09): a timeout, a crash, a missing terminator, a
    mismatched nonce or a corrupted channel is reported as blinding on the
    phases that did not close cleanly, never as a clean run. ``env`` is a set
    of caller extras merged over the allowlist, not a full replacement.
    """
    import secrets
    import tempfile
    import threading

    nonce = secrets.token_hex(16)
    platform = f"{sys.platform}"
    interpreter = f"{sys.implementation.name} {sys.version.split()[0]}"

    event_r, event_w = os.pipe()
    os.set_inheritable(event_w, True)  # Windows needs the handle inheritable
    lines: list[str] = []

    def _drain() -> None:
        with os.fdopen(event_r, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                lines.append(line)

    try:
        with tempfile.TemporaryDirectory(prefix="remora-observe-") as workdir:
            spec = json.dumps({
                "module": module, "function": function, "cases": list(cases),
                "path": [os.path.abspath(p) for p in path],
                "nonce": nonce, "event_fd": event_w,
            })
            proc = subprocess.Popen(
                [sys.executable, "-I", "-c", _HARNESS],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True,
                cwd=workdir, env=_child_env(env, workdir), pass_fds=(event_w,),
            )
            # The parent's own write end must close so the reader sees EOF
            # when the child exits (cleanly or not).
            os.close(event_w)
            event_w = -1
            reader = threading.Thread(target=_drain, daemon=True)
            reader.start()
            timed_out = False
            try:
                _, stderr = proc.communicate(input=spec, timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                _, stderr = proc.communicate()
            reader.join(timeout=5)
    finally:
        if event_w >= 0:
            os.close(event_w)

    if timed_out:
        return _blind_all(module, function, cases, interpreter, platform,
                          "timeout", f"no result within {timeout_s}s")

    # ── Parse the event channel ───────────────────────────────────────────
    channel_corrupt = False
    load_end: dict[str, Any] | None = None
    phase_events: dict[str, list[dict[str, Any]]] = {}
    case_ends: dict[int, dict[str, Any]] = {}
    terminated = False
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            # Non-JSON on the channel: the observed code wrote to the pipe.
            channel_corrupt = True
            continue
        if not isinstance(ev, dict):
            channel_corrupt = True
            continue
        kind = ev.get("ev")
        # Everything crossing this boundary is untrusted, including valid
        # JSON. Reject malformed/duplicate records before indexing or coercion.
        if kind == "event":
            if (not isinstance(ev.get("phase"), str)
                    or ev.get("kind") not in ("effect", "blinding")
                    or not isinstance(ev.get("class"), str)
                    or not isinstance(ev.get("detail"), str)):
                channel_corrupt = True
                continue
            phase_events.setdefault(ev["phase"], []).append(ev)
        elif kind == "load_end":
            if (load_end is not None or type(ev.get("completed")) is not bool
                    or type(ev.get("reads")) is not int or ev["reads"] < 0):
                channel_corrupt = True
                continue
            load_end = ev
        elif kind == "case_begin":
            if type(ev.get("index")) is not int or not 0 <= ev["index"] < len(cases):
                channel_corrupt = True
        elif kind == "case_end":
            index = ev.get("index")
            if (type(index) is not int or not 0 <= index < len(cases)
                    or index in case_ends or ev.get("nonce") != nonce
                    or type(ev.get("reads")) is not int or ev["reads"] < 0
                    or not isinstance(ev.get("raised"), str)):
                channel_corrupt = True
                continue
            case_ends[index] = ev
        elif kind == "end":
            if terminated or ev.get("nonce") != nonce:
                channel_corrupt = True
            else:
                terminated = True
        else:
            channel_corrupt = True

    def _case(index: int) -> CaseObservation:
        phase = f"call:{index}"
        records = phase_events.get(phase, [])
        effects = tuple((r["class"], r["detail"]) for r in records if r.get("kind") == "effect")
        blinding = [(r["class"], r["detail"]) for r in records if r.get("kind") == "blinding"]
        if channel_corrupt:
            blinding.append(("observer_tampering", "channel corruption"))
        end = case_ends.get(index)
        if end is None or end.get("nonce") != nonce:
            # Missing or forged terminator: os._exit, a killed process or a
            # tool that reached the channel. Never a clean run (SR-09).
            reason = "forged channel terminator" if end is not None else (
                "channel corruption" if channel_corrupt else "missing case terminator"
            )
            blinding.append(("observer_tampering" if end is not None or channel_corrupt
                             else "crash", reason))
            return CaseObservation(phase=phase, completed=False, effects=effects,
                                   blinding=tuple(blinding))
        return CaseObservation(phase=phase, completed=True, effects=effects,
                               blinding=tuple(blinding),
                               reads=int(end.get("reads", 0)),
                               raised=str(end.get("raised", "")))

    if load_end is None:
        return _blind_all(module, function, cases, interpreter, platform, "crash",
                          f"exit {proc.returncode}: no load terminator; "
                          f"{(stderr or '').strip()[-200:]}")

    load_records = phase_events.get("load", [])
    load = CaseObservation(
        phase="load",
        completed=bool(load_end.get("completed")),
        effects=tuple((r["class"], r["detail"]) for r in load_records if r.get("kind") == "effect"),
        blinding=tuple((r["class"], r["detail"]) for r in load_records if r.get("kind") == "blinding"),
        reads=int(load_end.get("reads", 0)),
        raised=str(load_end.get("error", "") if not load_end.get("completed") else ""),
    )
    if channel_corrupt:
        load = CaseObservation(
            phase="load", completed=load.completed, effects=load.effects,
            blinding=load.blinding + (("observer_tampering", "channel corruption"),),
            reads=load.reads, raised=load.raised)
    observed = tuple(_case(i) for i in range(len(cases)))
    if not terminated:
        # No valid final terminator: the run ended mid-stream (os._exit,
        # kill, channel write). Nothing after the last closed case can be
        # trusted; phases already blinded stay blinded, and the absence is
        # itself reported on the load phase when nothing else saw it.
        if all(not c.blinded for c in observed) and not load.blinded:
            load = CaseObservation(
                phase="load", completed=load.completed, effects=load.effects,
                blinding=load.blinding + (("crash", "missing run terminator"),),
                reads=load.reads, raised=load.raised)
    return Observation(module, function, "python_audit_hook", interpreter, platform, load, observed)
