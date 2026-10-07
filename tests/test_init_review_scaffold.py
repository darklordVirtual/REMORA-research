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


def test_effect_env_satisfies_the_strict_prerequisites(scaffold, monkeypatch) -> None:
    pytest.importorskip("cryptography", reason="effect env needs the Ed25519 public key")
    from remora.enforcement.custody import assert_custody_split
    from remora.toolcall.runtime_profile import validate_runtime_profile_prerequisites

    root, _ = scaffold
    env = _load_env(root / "effect.env")
    _apply(monkeypatch, env)
    assert validate_runtime_profile_prerequisites() == "review"
    assert assert_custody_split() == "effect"


def test_the_three_domains_never_share_a_secret(scaffold) -> None:
    """The split is the point: no file may hold two kinds of material."""
    root, _ = scaffold
    authority = _load_env(root / "authority.env")
    executor = _load_env(root / "executor.env")
    effect_domain = _load_env(root / "effect.env")
    effect = authority["REMORA_EFFECT_CREDENTIAL_ENV_NAMES"]

    # CR-005: only the effect domain holds the effect credential. Tool code
    # runs in the executor, which reaches effects only through the mediator.
    assert effect not in authority
    assert effect not in executor
    assert effect in effect_domain
    credential = effect_domain[effect]
    assert credential not in "".join(authority.values())
    assert credential not in "".join(executor.values())
    assert executor["REMORA_EFFECT_ENDPOINT"]
    signing_material = (
        "REMORA_PDP_SIGNING_KEY",
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
        "REMORA_ENVELOPE_SIGNING_KEY",
    )
    for signing in signing_material:
        assert signing in authority
        assert signing not in executor
        assert signing not in effect_domain


def test_the_demo_tool_is_signed_mediated(scaffold) -> None:
    """CR-005: the signed spec says MEDIATED, never leaves it to inference."""
    from remora.execution.effect_policy import effect_policy_refusal
    from remora.toolcall.toolspec import ToolSpecBundle

    root, _ = scaffold
    env = _load_env(root / "authority.env")
    bundle = json.loads((root / "toolspec-bundle.json").read_text(encoding="utf-8"))
    spec = ToolSpecBundle.load(bundle, verification_keys=_verify_keys(env),
                               accept_hmac=False).get("send_notification")
    assert spec.effect_mode == "MEDIATED"
    assert spec.direct_effect_credentials == "FORBIDDEN"
    assert effect_policy_refusal(spec, mediated=True) is None
    assert effect_policy_refusal(spec, mediated=False) == "effect_mediation_not_registered"


def test_no_runtime_half_can_author_a_toolspec_bundle(scaffold) -> None:
    """RMR-CR-001: every domain verifies bundles; none holds signing material."""
    root, summary = scaffold
    for half in ("authority.env", "executor.env", "effect.env"):
        env = _load_env(root / half)
        assert "REMORA_TOOLSPEC_SIGNING_KEY" not in env, half
        assert env["REMORA_TOOLSPEC_PINNED_DIGEST"] == summary["toolspec_bundle_digest"]
        seed = (root / "keys" / "toolspec_ed25519_seed").read_text(encoding="utf-8").strip()
        assert seed not in "".join(env.values()), half


def _verify_keys(env: dict[str, str]):
    from remora.crypto import SignatureDomain, VerificationKey

    return [VerificationKey.from_text(k, [SignatureDomain.TOOLSPEC_BUNDLE])
            for k in env["REMORA_TOOLSPEC_VERIFY_KEYS"].split(",")]


def test_bundle_verifies_under_the_generated_key_and_identity(scaffold) -> None:
    from remora.toolcall.toolspec import ToolSpecBundle

    root, summary = scaffold
    env = _load_env(root / "authority.env")
    bundle = json.loads((root / "toolspec-bundle.json").read_text(encoding="utf-8"))
    loaded = ToolSpecBundle.load(
        bundle, verification_keys=_verify_keys(env), accept_hmac=False,
        pinned_bundle_digest=env["REMORA_TOOLSPEC_PINNED_DIGEST"],
        require_pinned_digest=True,
    )
    assert loaded.get("send_notification").version == 1
    assert loaded.signing_algorithm == "Ed25519"
    assert loaded.signing_identity == summary["signing_identity"]


def test_bundle_is_refused_under_a_different_key(scaffold) -> None:
    from remora.crypto import SignatureDomain, SigningKey
    from remora.toolcall.toolspec import ToolSpecBundle, ToolSpecRefused

    root, _ = scaffold
    bundle = json.loads((root / "toolspec-bundle.json").read_text(encoding="utf-8"))
    stranger = SigningKey.generate([SignatureDomain.TOOLSPEC_BUNDLE]).verification_key()
    with pytest.raises(ToolSpecRefused) as exc:
        ToolSpecBundle.load(bundle, verification_keys=[stranger], accept_hmac=False)
    assert exc.value.reason_code == "toolspec_signing_identity_unknown"


def test_registry_module_registers_the_demo_tool(scaffold, monkeypatch) -> None:
    root, summary = scaffold
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("remora_registry", None)
    import importlib

    module = importlib.import_module("remora_registry")
    registered: dict[str, bool] = {}
    module.register_tools(
        lambda name, fn, mediated=False: registered.__setitem__(name, mediated))
    assert registered == {"send_notification": True}
    executors: dict[str, object] = {}
    module.register_effect_executors(executors.update)
    assert list(executors) == ["notification.send"]


def test_demo_effect_refuses_without_the_effect_credential(scaffold, monkeypatch) -> None:
    """The demo primitive behaves like a real one: no credential, no effect."""
    root, _ = scaffold
    monkeypatch.syspath_prepend(str(root))
    credential_name = "ACME_NOTIFY_API_KEY"  # a variable name, not a secret
    monkeypatch.setenv("REMORA_EFFECT_CREDENTIAL_ENV_NAMES", credential_name)
    monkeypatch.delenv(credential_name, raising=False)
    sys.modules.pop("remora_registry", None)
    import importlib

    module = importlib.import_module("remora_registry")
    with pytest.raises(RuntimeError):
        module.deliver_notification("notification://outbox", {"to": "ops@example.com"})


def test_demo_tool_reaches_its_effect_only_through_the_mediator(scaffold, monkeypatch) -> None:
    """The tool asks for notification.send on the outbox and nothing else."""
    root, _ = scaffold
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("remora_registry", None)
    import importlib

    module = importlib.import_module("remora_registry")
    asked: list[tuple[str, str, dict]] = []

    class _State:
        value = "EXECUTED"

    class _Mediator:
        def invoke(self, capability, resource, arguments):
            asked.append((capability, resource, dict(arguments)))
            return type("Effect", (), {"state": _State, "refusal": None})()

    result = module.send_notification({"to": "ops@example.com"}, _Mediator())
    assert asked == [("notification.send", "notification://outbox",
                      {"to": "ops@example.com", "subject": ""})]
    assert result["status"] == "EXECUTED"


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
    for path in [*(root / "keys").iterdir(), root / "authority.env", root / "executor.env",
                 root / "effect.env"]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
