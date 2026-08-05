# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Smoke tests: the README quickstart examples must run clean and offline.

These pin the first-run experience — `examples/quickstart.py` and
`examples/aromer_quickstart.py` are the first code a new user executes, so a
regression here breaks the front door even when the engine suite is green.
Both scripts are zero-API-key by design; no network access is required.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from remora import __version__

ROOT = Path(__file__).resolve().parents[1]


def _run_example(*argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, *argv],
        capture_output=True, text=True, encoding="utf-8",
        cwd=ROOT, env=env, timeout=180,
    )


def test_examples_quickstart_runs_clean():
    r = _run_example("examples/quickstart.py", "--fast", "--no-color")
    assert r.returncode == 0, r.stderr
    # The banner must report the installed package version, never a stale pin.
    assert f"v{__version__}" in r.stdout
    # The demo must show the full outcome spread the README promises.
    assert "ACCEPT" in r.stdout
    assert "ESCALATE" in r.stdout


def test_examples_aromer_quickstart_runs_clean():
    r = _run_example("examples/aromer_quickstart.py")
    assert r.returncode == 0, r.stderr
    assert "false_accept_rate" in r.stdout


def test_examples_sdk_quickstart_runs_clean():
    """FT-13: the external SDK example must run clean and offline.

    Demo mode spins up the real ASGI app in-process (dev no-auth mode,
    research tool registry) and drives the governed loop through
    ``remora.sdk`` only — the outcome spread and the audit verification
    must be visible in the output.
    """
    r = _run_example("examples/sdk_quickstart.py")
    assert r.returncode == 0, r.stderr
    # No server-side evidence in the demo: the read must ABSTAIN, never
    # ACCEPT on client-asserted trust alone.
    assert "decision: ABSTAIN" in r.stdout
    # The prod write goes through the full review loop.
    assert "decision: VERIFY" in r.stdout
    assert "agent approval refused (authorization_denied)" in r.stdout
    assert "execution outcome: execute" in r.stdout
    assert "tool executed: True" in r.stdout
    # The unknown tool never receives an execution token.
    assert "UNEXPECTED" not in r.stdout
    assert "audit chain valid: True" in r.stdout


def test_examples_agent_gate_runs_clean():
    """The three-line integration example must show the full outcome spread."""
    r = _run_example("examples/agent_gate.py")
    assert r.returncode == 0, r.stderr
    assert "ACCEPT" in r.stdout
    assert "ESCALATE" in r.stdout
    assert "executed read_file" in r.stdout          # ACCEPT path actually ran
    assert "executed drop_database" not in r.stdout  # blocked call never runs
