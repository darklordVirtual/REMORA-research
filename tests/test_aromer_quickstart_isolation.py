# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #424 (RMR-CR-009): the AROMER quickstart never touches home.

The external deep review found the documented quickstart redirecting only
the episodic store while the world-model and adapter-bridge defaults fell
back to ``~/.aromer`` — a crash on any read-only home despite F-10
describing the problem as fixed. This test runs the quickstart in a
subprocess with HOME pointed at a fresh directory and asserts NOTHING was
written there: the whole loop lives in the quickstart's own temp root.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = ROOT / "examples" / "aromer_quickstart.py"


def test_quickstart_writes_nothing_under_home(tmp_path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = dict(os.environ)
    env.pop("REMORA_AROMER_HOME", None)
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)  # Windows expanduser

    proc = subprocess.run(
        [sys.executable, str(QUICKSTART)],
        capture_output=True, text=True, timeout=300, env=env, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]

    written = [p for p in fake_home.rglob("*")]
    assert written == [], (
        "the quickstart leaked state into home: "
        f"{[str(p.relative_to(fake_home)) for p in written]}"
    )


def test_an_explicit_aromer_home_override_is_respected(tmp_path) -> None:
    override = tmp_path / "explicit-home"
    env = dict(os.environ)
    env["REMORA_AROMER_HOME"] = str(override)
    env["HOME"] = str(tmp_path / "untouched")
    env["USERPROFILE"] = str(tmp_path / "untouched")

    proc = subprocess.run(
        [sys.executable, str(QUICKSTART)],
        capture_output=True, text=True, timeout=300, env=env, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert not (tmp_path / "untouched").exists() or \
        list((tmp_path / "untouched").rglob("*")) == []
