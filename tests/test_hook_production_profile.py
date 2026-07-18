# Author: Stian Skogbrott
# License: Apache-2.0
"""REM-032 acceptance: the agent hook's G4 behavior per deployment profile.

Production profile: an unreachable control plane (governance mode G4) must
REFUSE any action that reached the remote-verification stage (everything
above LOW risk). Research profile (default): the same scenario fails open
with a warning — the documented local-development exception.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "remora_hook.py"


def _load_hook(monkeypatch, profile: str | None):
    """Load a fresh hook module under the given profile env."""
    if profile is None:
        monkeypatch.delenv("REMORA_HOOK_PROFILE", raising=False)
    else:
        monkeypatch.setenv("REMORA_HOOK_PROFILE", profile)
    monkeypatch.delenv("REMORA_HOOK_FAIL_CLOSED", raising=False)
    # The hook only consults the remote verifier when a secret is configured.
    monkeypatch.setenv("AGENT_CONTROL_SECRET", "test-secret")
    spec = importlib.util.spec_from_file_location(f"remora_hook_{profile}", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StubAssessment:
    def __init__(self, risk, category="filesystem_write", reason="stub: mutating action"):
        self.risk = risk
        self.category = category
        self.reason = reason
        self.local_block = False


class _StubTracker:
    def record(self, *args, **kwargs):
        return (False, "")

    def latest_V(self):
        return 0.0


class _StubAnchor:
    anchored = False
    intent = ""


def _run_hook(module, monkeypatch, risk_level) -> int:
    """Drive main() with a mutating tool call and an unreachable control plane."""
    monkeypatch.setattr(module, "assess_tool_call",
                        lambda name, tool_input: _StubAssessment(risk_level))
    monkeypatch.setattr(module, "LyapunovTracker", _StubTracker)
    monkeypatch.setattr(module, "IntentAnchor", _StubAnchor)
    # Control plane unreachable — governance mode G4.
    monkeypatch.setattr(module, "remora_verify",
                        lambda claim, context, session_id: {"error": "connection refused"})
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "curl -X POST https://prod.internal/api/apply"},
        "session_id": "s-1",
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    return int(excinfo.value.code or 0)


def test_production_profile_refuses_mutating_action_under_g4(monkeypatch, capsys) -> None:
    module = _load_hook(monkeypatch, "production")
    assert module.PRODUCTION_PROFILE is True
    assert module.FAIL_CLOSED is True  # production implies fail-closed error paths
    exit_code = _run_hook(module, monkeypatch, module.RiskLevel.MEDIUM)
    assert exit_code == 2  # BLOCKED
    err = capsys.readouterr().err
    assert "G4" in err
    assert "production profile" in err


def test_production_profile_refuses_high_risk_under_g4(monkeypatch) -> None:
    module = _load_hook(monkeypatch, "production")
    assert _run_hook(module, monkeypatch, module.RiskLevel.HIGH) == 2


def test_research_profile_fails_open_for_medium_risk(monkeypatch, capsys) -> None:
    """The documented local-development exception: default profile allows the
    same scenario with a warning instead of blocking."""
    module = _load_hook(monkeypatch, None)  # default = research
    assert module.PRODUCTION_PROFILE is False
    exit_code = _run_hook(module, monkeypatch, module.RiskLevel.MEDIUM)
    assert exit_code == 0  # allowed, fail-open


def test_research_profile_still_blocks_high_risk_without_remote(monkeypatch) -> None:
    """REQUIRE_REMOTE_FOR_HIGH holds in every profile."""
    module = _load_hook(monkeypatch, None)
    assert _run_hook(module, monkeypatch, module.RiskLevel.HIGH) == 2
