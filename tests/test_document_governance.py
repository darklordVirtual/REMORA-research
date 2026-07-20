# Author: Stian Skogbrott
# License: Apache-2.0
"""Documentation-governance gate tests.

The live repository must pass the gate, and the gate must actually refuse
the failure modes it exists for (drifted profile declarations, duplicate
canonical topics, dangling successors) — a gate that cannot fail is
decoration.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_document_governance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_document_governance", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repository_passes_documentation_governance() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT
    )
    assert proc.returncode == 0, proc.stderr


def test_registers_parse_as_strict_yaml() -> None:
    """The machine-readable registers must actually be machine-readable.

    Regression: the remediation register carried five entries with unquoted
    `notes: M3a: ...` scalars — invalid YAML that no tool had ever parsed
    until this gate's first run (2026-07-20)."""
    import yaml

    for name in (
        "remediation_register.yaml",
        "capability_register_v1.yaml",
        "claim_register_v1.yaml",
        "document_register_v1.yaml",
        "release_profiles_v1.yaml",
    ):
        with open(ROOT / "docs" / "assurance" / name, encoding="utf-8") as f:
            assert yaml.safe_load(f) is not None, name


def test_profile_declaration_cannot_drift(tmp_path: Path) -> None:
    """Declaring a higher profile than the registers support must fail."""
    mod = _load_module()
    inflated = tmp_path / "profiles.yaml"
    original = (ROOT / "docs" / "assurance" / "release_profiles_v1.yaml").read_text(
        encoding="utf-8"
    )
    inflated.write_text(
        original.replace("current_profile: SHADOW_PILOT", "current_profile: PRODUCTION"),
        encoding="utf-8",
    )
    mod.PROFILES = inflated
    errors: list[str] = []
    mod.check_release_profiles(errors)
    assert any("current_profile" in e and "PRODUCTION" in e for e in errors)


def test_duplicate_canonical_topic_is_refused(tmp_path: Path) -> None:
    mod = _load_module()
    reg = tmp_path / "docreg.yaml"
    reg.write_text(
        "documents:\n"
        "  - path: docs/README.md\n"
        "    status: canonical\n"
        "    topic: same-topic\n"
        "  - path: docs/01-architecture.md\n"
        "    status: canonical\n"
        "    topic: same-topic\n",
        encoding="utf-8",
    )
    mod.DOC_REGISTER = reg
    errors: list[str] = []
    mod.check_document_register(errors)
    assert any("same-topic" in e and "claimed by both" in e for e in errors)


def test_superseded_without_successor_is_refused(tmp_path: Path) -> None:
    mod = _load_module()
    reg = tmp_path / "docreg.yaml"
    reg.write_text(
        "documents:\n"
        "  - path: docs/README.md\n"
        "    status: superseded\n"
        "    superseded_by: docs/does_not_exist.md\n",
        encoding="utf-8",
    )
    mod.DOC_REGISTER = reg
    errors: list[str] = []
    mod.check_document_register(errors)
    assert any("superseded_by" in e for e in errors)


def test_declared_current_profile_is_shadow_pilot() -> None:
    """Pin the honest current state: SHADOW_PILOT (= SHADOW_ONLY).

    If this test fails because the computed profile ROSE, update the
    declaration together with the register evidence that raised it. If it
    fails because the profile FELL, a register regression happened — treat
    as an incident, not a test to silence."""
    import yaml

    with open(
        ROOT / "docs" / "assurance" / "release_profiles_v1.yaml", encoding="utf-8"
    ) as f:
        prof = yaml.safe_load(f)
    assert prof["current_profile"] == "SHADOW_PILOT"
    assert prof["deployment_status_equivalent"] == "SHADOW_ONLY"
