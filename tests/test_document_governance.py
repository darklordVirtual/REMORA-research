# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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


def _verif_reg(tmp_path: Path, entry_lines: str):
    reg = tmp_path / "docreg.yaml"
    reg.write_text("documents:\n" + entry_lines, encoding="utf-8")
    return reg


def test_verified_without_review_date_is_refused(tmp_path: Path) -> None:
    """A document cannot be marked code_synced=verified with no review date —
    the register must not claim a check that never happened."""
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/README.md\n    version: v1\n"
        "    status: supporting\n    last_reviewed: null\n"
        "    code_synced: verified\n    verdict: pending\n",
    )
    errors: list[str] = []
    mod.check_document_verification(errors, [])
    assert any("verified but last_reviewed is null" in e for e in errors)


def test_current_verdict_requires_verified(tmp_path: Path) -> None:
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/README.md\n    version: v1\n"
        "    status: supporting\n    last_reviewed: 2026-07-26\n"
        "    code_synced: unreviewed\n    verdict: current\n",
    )
    errors: list[str] = []
    mod.check_document_verification(errors, [])
    assert any("verdict=current requires code_synced=verified" in e for e in errors)


def test_historical_current_is_exempt_from_verified_requirement(tmp_path: Path) -> None:
    """A frozen historical snapshot may be verdict=current (correctly archived)
    without code_synced=verified — it is not expected to match live code."""
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/README.md\n    version: v1\n"
        "    status: historical\n    last_reviewed: 2026-07-26\n"
        "    code_synced: unreviewed\n    verdict: current\n",
    )
    errors: list[str] = []
    mod.check_document_verification(errors, [])
    assert not any("requires code_synced=verified" in e for e in errors)


def test_missing_verification_fields_are_refused(tmp_path: Path) -> None:
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - path: docs/README.md\n    status: supporting\n",
    )
    errors: list[str] = []
    mod.check_document_verification(errors, [])
    assert any("missing/invalid id" in e for e in errors)
    assert any("missing/invalid version" in e for e in errors)
    assert any("code_synced" in e for e in errors)
    assert any("verdict" in e for e in errors)


def test_unaudited_document_warns_not_fails(tmp_path: Path) -> None:
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/README.md\n    version: v1\n"
        "    status: supporting\n    last_reviewed: null\n"
        "    code_synced: unreviewed\n    verdict: pending\n",
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_document_verification(errors, warnings)
    assert errors == []
    assert any("never audited against code" in w for w in warnings)


def test_release_gates_table_drift_is_refused(tmp_path: Path) -> None:
    """A Status cell that contradicts remediation_register.yaml must fail.

    REM-021 is NOT_STARTED in the register; a table row claiming it DONE is
    exactly the mirror-drift this gate exists to catch."""
    mod = _load_module()
    gates = tmp_path / "release_gates.md"
    gates.write_text(
        "| ID | Gate | Status | What DONE means |\n"
        "|----|------|--------|-----------------|\n"
        "| REM-021 | Independent human review | **DONE** | ... |\n",
        encoding="utf-8",
    )
    mod.RELEASE_GATES = gates
    errors: list[str] = []
    mod.check_release_gates_table(errors)
    assert any("REM-021" in e and "drifted" in e for e in errors), errors


def test_release_gates_table_accepts_matching_status(tmp_path: Path) -> None:
    """The mirror passes when the cell states the register status, tolerating
    surrounding prose and 'NOT STARTED' vs 'NOT_STARTED' spelling."""
    mod = _load_module()
    gates = tmp_path / "release_gates.md"
    gates.write_text(
        "| ID | Gate | Status | What DONE means |\n"
        "|----|------|--------|-----------------|\n"
        "| REM-021 | Independent human review | **NOT STARTED** | ... |\n"
        "| REM-023 | RBAC follow-through | **IN_PROGRESS** (folded into REM-021) | ... |\n",
        encoding="utf-8",
    )
    mod.RELEASE_GATES = gates
    errors: list[str] = []
    mod.check_release_gates_table(errors)
    assert errors == [], errors


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
