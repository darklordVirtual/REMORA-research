# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The runnable example runs, offline, for every scenario it declares.

A documented example that has drifted from the code is worse than none: it is
the first thing an integrator copies. This runs it as a subprocess, the way an
integrator would, with no account and no network, and checks the property the
example asserts for itself: the provider informed the decision and authorised
nothing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "jev_decision_provider_demo.py"


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("legitimate", "decision with provider:    VERIFY"),
        ("wrong_target", "favourable signal withheld"),
        ("injection", "raised adversarial_detected"),
    ],
)
def test_the_example_runs_offline_and_holds_its_own_assertion(scenario: str, expected: str) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(EXAMPLE), "--scenario", scenario],
        capture_output=True,
        text=True,
        env={"PYTHONIOENCODING": "utf-8", "PATH": "", "SYSTEMROOT": ""} | {
            k: v for k, v in __import__("os").environ.items()
            if k not in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")
        },
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert expected in completed.stdout, completed.stdout
    assert "authorised nothing" in completed.stdout


def test_live_mode_refuses_without_credentials(monkeypatch) -> None:
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")}
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(EXAMPLE), "--live"],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert completed.returncode != 0
    assert "CLOUDFLARE_ACCOUNT_ID" in completed.stderr
