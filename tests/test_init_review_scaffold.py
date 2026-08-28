# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""`remora init-review` must produce a configuration the invariants accept.

The scaffold exists to automate ceremony, so the only meaningful test is
whether what it writes satisfies the real prerequisites, unmodified: the
strict-profile validator, the custody guard for each half, the ToolSpec
verifier, the registry contract and the intent resolver. Nothing here
mocks those checks.
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from remora.scaffold import ScaffoldExists, init_review


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("export "):
            key, _, raw = line[len("export "):].partition("=")
            env[key] = shlex.split(raw)[0]
    return env


@pytest.fixture
def scaffold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    summary = init_review(tmp_path / ".remora")
    return tmp_path / ".remora", summary


def _apply(monkeypatch, env: dict[str, str]) -> None:
    # One name per line: a generic secret scanner reads `"X", "Y_KEY"` on one
    # line as an assignment of a secret. These are variable names.
    for name in (
        "REMORA_PG_DSN",
        "REMORA_CHAIN_DB",
        "REMORA_LEASE_SIGNING_KEY",
        "REMORA_PDP_SIGNING_KEY",
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
        "REMORA_TOOLSPEC_SIGNING_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(env["PYTHONPATH"])


def test_authority_env_satisfies_the_strict_prerequisites(scaffold, monkeypatch) -> None:
    from remora.enforcement.custody import assert_custody_split
    from remora.toolcall.runtime_profile import validate_runtime_profile_prerequisites

    root, _ = scaffold
    env = _load_env(root / "authority.env")
    _apply(monkeypatch, env)
    assert validate_runtime_profile_prerequisites() == "review"
    assert assert_custody_split() == "authority"


def test_executor_env_satisfies_the_strict_prerequisites(scaffold, monkeypatch) -> None:
    pytest.importorskip("cryptography", reason="executor env needs the Ed25519 public key")
    from remora.enforcement.custody import assert_custody_split
    from remora.toolcall.runtime_profile import validate_runtime_profile_prerequisites

    root, _ = scaffold
    env = _load_env(root / "executor.env")
    _apply(monkeypatch, env)
    assert validate_runtime_profile_prerequisites() == "review"
    assert assert_custody_split() == "executor"


def test_the_two_halves_never_share_a_secret(scaffold) -> None:
    """The split is the point: no file may hold both kinds of material."""
    root, _ = scaffold
    authority = _load_env(root / "authority.env")
    executor = _load_env(root / "executor.env")
    effect = authority["REMORA_EFFECT_CREDENTIAL_ENV_NAMES"]

    assert effect not in authority
    assert effect in executor
    signing_material = (
        "REMORA_PDP_SIGNING_KEY",
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
        "REMORA_TOOLSPEC_SIGNING_KEY",
        "REMORA_ENVELOPE_SIGNING_KEY",
    )
    for signing in signing_material:
        assert signing in authority
        assert signing not in executor


def test_bundle_verifies_under_the_generated_key_and_identity(scaffold) -> None:
    from remora.toolcall.toolspec import ToolSpecBundle

    root, summary = scaffold
    env = _load_env(root / "authority.env")
    bundle = json.loads((root / "toolspec-bundle.json").read_text(encoding="utf-8"))
    loaded = ToolSpecBundle.load(
        bundle, key=env["REMORA_TOOLSPEC_SIGNING_KEY"],
        trusted_identities=[summary["signing_identity"]],
    )
    assert loaded.get("send_notification").version == 1


def test_bundle_is_refused_under_a_different_key(scaffold) -> None:
    from remora.toolcall.toolspec import ToolSpecBundle, ToolSpecRefused

    root, summary = scaffold
    bundle = json.loads((root / "toolspec-bundle.json").read_text(encoding="utf-8"))
    with pytest.raises(ToolSpecRefused):
        ToolSpecBundle.load(bundle, key="not-the-key",
                            trusted_identities=[summary["signing_identity"]])


def test_registry_module_registers_the_demo_tool(scaffold, monkeypatch) -> None:
    root, summary = scaffold
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("remora_registry", None)
    import importlib

    module = importlib.import_module("remora_registry")
    registered: dict[str, object] = {}
    module.register_tools(lambda name, fn: registered.__setitem__(name, fn))
    assert list(registered) == ["send_notification"]


def test_demo_tool_refuses_without_the_effect_credential(scaffold, monkeypatch) -> None:
    """The demo behaves like a real tool: no credential, no effect."""
    root, _ = scaffold
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.delenv("EFFECT_CREDENTIAL_NAME", raising=False)
    sys.modules.pop("remora_registry", None)
    import importlib

    module = importlib.import_module("remora_registry")
    with pytest.raises(RuntimeError):
        module.send_notification({"to": "ops@example.com"})


def test_intent_source_resolves_through_the_research_bundle(scaffold, monkeypatch) -> None:
    root, _ = scaffold
    env = _load_env(root / "authority.env")
    monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", env["REMORA_INTENT_SOURCE_FILE"])
    from servers.semantic_bundle_research import resolve_intent

    resolved = resolve_intent("wo-demo-1")
    assert resolved is not None
    assert "notification" in resolved.task_text
    assert resolve_intent("wo-unknown") is None


def test_second_run_refuses_to_overwrite_keys(scaffold) -> None:
    root, _ = scaffold
    with pytest.raises(ScaffoldExists):
        init_review(root)
    init_review(root, force=True)


def test_secrets_are_gitignored(scaffold) -> None:
    root, _ = scaffold
    ignored = (root / ".gitignore").read_text(encoding="utf-8").split()
    assert {"keys/", "*.env", "state/"} <= set(ignored)


def test_cli_entry_point(tmp_path, monkeypatch, capsys) -> None:
    from remora.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["init-review", "--dir", str(tmp_path / "cfg")]) == 0
    assert "authority.env" in " ".join(p.name for p in (tmp_path / "cfg").iterdir())
    assert main(["init-review", "--dir", str(tmp_path / "cfg")]) == 2
    assert "refused" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_secrets_are_written_owner_only(scaffold) -> None:
    """Keys and env files must never be readable to other users."""
    import stat

    root, _ = scaffold
    assert stat.S_IMODE((root / "keys").stat().st_mode) == 0o700
    for path in [*(root / "keys").iterdir(), root / "authority.env", root / "executor.env"]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
