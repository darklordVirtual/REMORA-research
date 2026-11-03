# SPDX-License-Identifier: BUSL-1.1
"""RMR-SEC-0001 (WP2): production refuses signing keys anyone can know.

The OT pilot compose shipped ``REMORA_LEASE_SIGNING_KEY:
pilot-lease-key-change-me``, and production startup accepted it. The
2026-11-02 review signed a lease with that literal and closed a valve. The
pilot now generates its keys (deploy/ot-pilot/init_tokens.py), and
production refuses a placeholder-shaped or short symmetric key.
"""
from __future__ import annotations

import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from servers.api import weak_symmetric_signing_keys  # noqa: E402

STRONG = secrets.token_hex(32)


@pytest.mark.parametrize("value", [
    "pilot-lease-key-change-me",
    "pilot-pdp-key-change-me-but-padded-past-thirty-two-bytes",
    "short",
    "x" * 31,
    "REPLACE-ME-with-a-real-key-of-at-least-32-bytes",
])
def test_placeholder_and_short_keys_are_weak(value: str) -> None:
    assert weak_symmetric_signing_keys({"REMORA_LEASE_SIGNING_KEY": value}) == [
        "REMORA_LEASE_SIGNING_KEY"]


def test_a_random_key_is_not_weak_and_unset_keys_are_not_reported() -> None:
    env = {name: secrets.token_hex(32) for name in (
        "REMORA_PDP_SIGNING_KEY", "REMORA_LEASE_SIGNING_KEY",
        "REMORA_AUDIT_SIGNING_KEY", "REMORA_ENVELOPE_SIGNING_KEY")}
    assert weak_symmetric_signing_keys(env) == []
    assert weak_symmetric_signing_keys({}) == []


def _production_env(monkeypatch, tmp_path) -> None:
    import servers.api as api

    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "tok")
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://localhost/remora")
    monkeypatch.setattr(api, "filesystem_type_for", lambda _path: "ext4")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "groq")
    monkeypatch.setenv("REMORA_API_TOKENS", '{"t":{"tenant":"t","role":"operator"}}')
    for name in ("REMORA_ENVELOPE_SIGNING_KEY", "REMORA_PDP_SIGNING_KEY",
                 "REMORA_LEASE_SIGNING_KEY", "REMORA_AUDIT_SIGNING_KEY"):
        monkeypatch.setenv(name, secrets.token_hex(32))


@pytest.mark.parametrize("name", ["REMORA_LEASE_SIGNING_KEY", "REMORA_PDP_SIGNING_KEY",
                                  "REMORA_AUDIT_SIGNING_KEY", "REMORA_ENVELOPE_SIGNING_KEY"])
def test_production_startup_refuses_the_committed_pilot_literals(
    monkeypatch, tmp_path, name: str
) -> None:
    import servers.api as api

    _production_env(monkeypatch, tmp_path)
    literal = {"REMORA_LEASE_SIGNING_KEY": "pilot-lease-key-change-me",
               "REMORA_PDP_SIGNING_KEY": "pilot-pdp-key-change-me",
               "REMORA_AUDIT_SIGNING_KEY": "pilot-audit-key-change-me",
               "REMORA_ENVELOPE_SIGNING_KEY": "pilot-envelope-key-change-me"}[name]
    monkeypatch.setenv(name, literal)
    with pytest.raises(RuntimeError, match=name):
        api._validate_production_prerequisites()


def test_production_startup_accepts_generated_keys(monkeypatch, tmp_path) -> None:
    import servers.api as api

    _production_env(monkeypatch, tmp_path)
    api._validate_production_prerequisites()


def test_no_signing_key_literal_is_committed_in_deploy() -> None:
    """Every REMORA_*_SIGNING_KEY in a compose file comes from the environment."""
    offenders = []
    for path in (ROOT / "deploy").rglob("*.y*ml"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"\s*(REMORA_\w*SIGNING_KEY)\s*:\s*(\S+)", line)
            if match and not match.group(2).startswith("${"):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []


def test_init_tokens_generates_strong_keys(tmp_path) -> None:
    script = (ROOT / "deploy" / "ot-pilot" / "init_tokens.py").read_text(encoding="utf-8")
    target = tmp_path / "init_tokens.py"
    target.write_text(script, encoding="utf-8")
    subprocess.run([sys.executable, str(target)], check=True, capture_output=True)
    env = dict(line.split("=", 1) for line in (tmp_path / ".env").read_text(
        encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
    mapped = {f"REMORA_{name[3:]}": value for name, value in env.items()
              if name.startswith("OT_") and name.endswith("_SIGNING_KEY")}
    assert set(mapped) == {"REMORA_PDP_SIGNING_KEY", "REMORA_LEASE_SIGNING_KEY",
                           "REMORA_AUDIT_SIGNING_KEY", "REMORA_ENVELOPE_SIGNING_KEY"}
    assert weak_symmetric_signing_keys(mapped) == []
    assert len(set(mapped.values())) == 4, "each authority gets its own key"
