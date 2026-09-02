# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-005: a strict preflight must fail the way the server fails.

`remora doctor` graded the server entrypoint as an optional capability, so a
controlled-pilot configuration could report overall ``ok: true`` while
importing ``servers.api`` refused on a missing bearer token, no control plane
or no durable execution state. The operator got a green preflight and then a
server that would not start, with a fix hint pointing at package contents
rather than at the variable that was actually missing.

A strict runtime profile is a promise about how this process will serve. Under
that promise the entrypoint is not optional.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Everything a controlled pilot needs beyond the authority variables. Removing
#: any one of these must turn the preflight red.
REQUIRED_FOR_SERVING = (
    "REMORA_API_BEARER_TOKEN",
    "REMORA_CONTROL_PLANE_DSN",
    "REMORA_CHAIN_DB",
)


def doctor(env: dict[str, str]) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, "-m", "remora", "doctor", "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:  # pragma: no cover - diagnostic path
        pytest.fail(f"doctor did not emit JSON:\n{result.stdout}\n{result.stderr}")
    return result.returncode, payload


def check(payload: dict, name: str) -> dict:
    for entry in payload["checks"]:
        if entry["check"] == name:
            return entry
    raise AssertionError(
        f"doctor emitted no {name!r} check: {[c['check'] for c in payload['checks']]}"
    )


def pilot_env(base: dict[str, str], tmp_path: Path, drop: str | None = None) -> dict[str, str]:
    env = dict(base)
    env.update(
        {
            "REMORA_RUNTIME_PROFILE": "controlled_pilot",
            "REMORA_ENV": "production",
            "REMORA_API_BEARER_TOKEN": "preflight-probe-token",
            "REMORA_CONTROL_PLANE_DSN": f"sqlite:///{tmp_path / 'control.db'}",
            "REMORA_CHAIN_DB": str(tmp_path / "chain.db"),
        }
    )
    if drop:
        env.pop(drop, None)
    return env


@pytest.fixture
def base_env(monkeypatch):
    import os

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("REMORA_") and not k.startswith("AROMER_")
    }
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


@pytest.mark.parametrize("dropped", REQUIRED_FOR_SERVING)
def test_a_missing_serving_prerequisite_turns_the_preflight_red(base_env, tmp_path, dropped):
    """One variable at a time, as the review specified."""

    code, payload = doctor(pilot_env(base_env, tmp_path, drop=dropped))
    assert payload["ok"] is False, (
        f"doctor reported ok with {dropped} missing: "
        f"{[c for c in payload['checks'] if c['ok'] is False]}"
    )
    assert code == 1


def test_the_entrypoint_check_is_hard_under_a_strict_profile(base_env, tmp_path):
    _, payload = doctor(pilot_env(base_env, tmp_path, drop="REMORA_API_BEARER_TOKEN"))
    entry = check(payload, "api extra (remora serve)")
    assert entry["hard"] is True
    assert entry["ok"] is False


def test_the_failure_names_the_reason_not_the_package(base_env, tmp_path):
    """The old hint sent operators hunting a distribution problem they did not have."""

    _, payload = doctor(pilot_env(base_env, tmp_path, drop="REMORA_API_BEARER_TOKEN"))
    entry = check(payload, "api extra (remora serve)")
    assert "entrypoint refused to start" in entry["detail"]
    assert "REMORA_API_BEARER_TOKEN" in entry["detail"]
    assert "distribution" not in (entry["fix"] or "")


def test_research_profile_keeps_the_entrypoint_optional(base_env):
    """A library install with no API extra is a legitimate configuration."""

    _, payload = doctor(base_env)
    entry = check(payload, "api extra (remora serve)")
    assert entry["hard"] is False


def test_an_enabled_governed_surface_makes_it_hard_without_a_strict_profile(base_env, tmp_path):
    env = dict(base_env)
    env["REMORA_ENABLED_SURFACES"] = "execution"
    env["REMORA_ENV"] = "production"
    _, payload = doctor(env)
    entry = check(payload, "api extra (remora serve)")
    assert entry["hard"] is True
