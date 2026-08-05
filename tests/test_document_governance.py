# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Documentation-governance gate tests.

The live repository must pass the gate, and the gate's HARD checks must still
refuse the failure modes they exist for (drifted profile declarations,
duplicate canonical topics, dangling successors, gate-table drift).

As of the 2026-07-27 loosening, register coverage and the schema-v2
verification fields are ADVISORY: they surface as warnings and must NOT fail
the build. These tests pin that split so neither side regresses.
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
    """The machine-readable registers must actually be machine-readable."""
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
    """Declaring a higher profile than the registers support must fail (HARD)."""
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
    """Canonical topic uniqueness stays HARD."""
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
    mod.check_document_register(errors, [])
    assert any("same-topic" in e and "claimed by both" in e for e in errors)


def test_superseded_without_successor_is_refused(tmp_path: Path) -> None:
    """Dangling successor stays HARD."""
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
    mod.check_document_register(errors, [])
    assert any("superseded_by" in e for e in errors)


def test_missing_register_coverage_warns_not_fails(tmp_path: Path) -> None:
    """Coverage gaps (tracked file with no entry / entry for a missing file)
    are ADVISORY after the loosening — they warn, they do not fail."""
    mod = _load_module()
    reg = tmp_path / "docreg.yaml"
    reg.write_text(
        "topics: []\n"
        "documents:\n"
        "  - path: docs/does_not_exist.md\n"
        "    status: supporting\n",
        encoding="utf-8",
    )
    mod.DOC_REGISTER = reg
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_document_register(errors, warnings)
    assert errors == []
    assert any(("no entry" in w) or ("missing/untracked" in w) for w in warnings)


def _verif_reg(tmp_path: Path, entry_lines: str):
    reg = tmp_path / "docreg.yaml"
    reg.write_text("documents:\n" + entry_lines, encoding="utf-8")
    return reg


def test_verified_without_review_date_warns(tmp_path: Path) -> None:
    """code_synced=verified with no review date is an advisory nudge, not a
    build failure."""
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/README.md\n    version: v1\n"
        "    status: supporting\n    last_reviewed: null\n"
        "    code_synced: verified\n    verdict: pending\n",
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_document_verification(errors, warnings)
    assert errors == []
    assert any("verified but last_reviewed is null" in w for w in warnings)


def test_current_verdict_without_verified_warns(tmp_path: Path) -> None:
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/README.md\n    version: v1\n"
        "    status: supporting\n    last_reviewed: 2026-07-26\n"
        "    code_synced: unreviewed\n    verdict: current\n",
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_document_verification(errors, warnings)
    assert errors == []
    assert any("verdict=current without code_synced=verified" in w for w in warnings)


def test_historical_current_is_exempt(tmp_path: Path) -> None:
    """A frozen historical snapshot may be verdict=current without
    code_synced=verified — no warning is raised for it."""
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/README.md\n    version: v1\n"
        "    status: historical\n    last_reviewed: 2026-07-26\n"
        "    code_synced: unreviewed\n    verdict: current\n",
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_document_verification(errors, warnings)
    assert not any("without code_synced=verified" in m for m in errors + warnings)


def test_missing_verification_fields_warn(tmp_path: Path) -> None:
    """Missing schema-v2 fields are advisory now — warnings, not errors."""
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - path: docs/README.md\n    status: supporting\n",
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_document_verification(errors, warnings)
    assert errors == []
    assert any("missing/invalid id" in w for w in warnings)
    assert any("missing/invalid version" in w for w in warnings)
    assert any("code_synced" in w for w in warnings)
    assert any("verdict" in w for w in warnings)


def test_duplicate_doc_id_is_refused(tmp_path: Path) -> None:
    """DOC-id uniqueness is the one verification invariant kept HARD."""
    mod = _load_module()
    mod.DOC_REGISTER = _verif_reg(
        tmp_path,
        "  - id: DOC-001\n    path: docs/a.md\n    version: v1\n"
        "    status: supporting\n    last_reviewed: null\n"
        "    code_synced: unreviewed\n    verdict: pending\n"
        "  - id: DOC-001\n    path: docs/b.md\n    version: v1\n"
        "    status: supporting\n    last_reviewed: null\n"
        "    code_synced: unreviewed\n    verdict: pending\n",
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_document_verification(errors, warnings)
    assert any("duplicate DOC id DOC-001" in e for e in errors)


def test_unaudited_documents_warn_not_fail(tmp_path: Path) -> None:
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
    assert any("not yet audited against code" in w for w in warnings)


def test_placeholder_stub_registered_as_live_doc_is_refused(tmp_path: Path) -> None:
    """A registered live document (canonical/supporting/...) whose content is a
    bare placeholder stub must fail HARD. Gutting a doc to `# Placeholder`
    while its register entry still presents it as live documentation is
    exactly the drift this gate exists to stop (regression: a585202 stubbed
    53 registered docs and left them stamped canonical/verified)."""
    mod = _load_module()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "gutted.md").write_text("# Placeholder\n", encoding="utf-8")
    reg = tmp_path / "docreg.yaml"
    reg.write_text(
        "topics:\n- some-topic\n"
        "documents:\n"
        "  - path: docs/gutted.md\n"
        "    status: canonical\n"
        "    topic: some-topic\n",
        encoding="utf-8",
    )
    mod.DOC_REGISTER = reg
    mod.ROOT = tmp_path
    errors: list[str] = []
    mod.check_document_register(errors, [])
    assert any("placeholder" in e.lower() and "docs/gutted.md" in e for e in errors), errors


def test_placeholder_check_ignores_real_content(tmp_path: Path) -> None:
    """A live doc with real content (even short) is not flagged."""
    mod = _load_module()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "real.md").write_text(
        "# Runtime policy\n\nActual documented behavior.\n", encoding="utf-8"
    )
    reg = tmp_path / "docreg.yaml"
    reg.write_text(
        "topics: []\ndocuments:\n  - path: docs/real.md\n    status: supporting\n",
        encoding="utf-8",
    )
    mod.DOC_REGISTER = reg
    mod.ROOT = tmp_path
    errors: list[str] = []
    mod.check_document_register(errors, [])
    assert not any("placeholder" in e.lower() for e in errors), errors


def test_readme_between_soft_and_hard_cap_warns_not_fails(tmp_path: Path) -> None:
    """Between the soft and hard cap the budget is advisory."""
    mod = _load_module()
    mod.ROOT = tmp_path
    mod.README_LINE_SOFT_CAP = 5
    mod.README_LINE_HARD_CAP = 50
    (tmp_path / "README.md").write_text(
        "\n".join(str(i) for i in range(20)), encoding="utf-8"
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_readme_budget(errors, warnings)
    assert not errors
    assert any("README.md" in w and "advisory" in w for w in warnings)


def test_readme_over_hard_cap_fails(tmp_path: Path) -> None:
    """The front page must not regrow into a dossier: the hard cap is a
    HARD violation, so detail has to move into docs/ and be linked."""
    mod = _load_module()
    mod.ROOT = tmp_path
    mod.README_LINE_SOFT_CAP = 5
    mod.README_LINE_HARD_CAP = 10
    (tmp_path / "README.md").write_text(
        "\n".join(str(i) for i in range(20)), encoding="utf-8"
    )
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_readme_budget(errors, warnings)
    assert any("README.md" in e and "hard cap" in e for e in errors)


def test_release_gates_table_drift_is_refused(tmp_path: Path) -> None:
    """A Status cell that contradicts remediation_register.yaml must fail."""
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
    import yaml

    with open(
        ROOT / "docs" / "assurance" / "release_profiles_v1.yaml", encoding="utf-8"
    ) as f:
        prof = yaml.safe_load(f)
    assert prof["current_profile"] == "SHADOW_PILOT"
    assert prof["deployment_status_equivalent"] == "SHADOW_ONLY"


# ---------------------------------------------------------------------------
# Index completeness: docs/README.md calls itself "the single authoritative
# index", and nothing checked the converse until 2026-07-31 — so a registered,
# current document could pass every gate while being invisible to a reader
# working from the index. That is how superseded_claims.md and
# routing_benchmark_v1_design.md came to sit unlinked.
# ---------------------------------------------------------------------------

def test_index_completeness_flags_an_unlinked_live_document(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "docs" / "assurance").mkdir(parents=True)
    (tmp_path / "docs" / "README.md").write_text(
        "# Index\n\n[linked](assurance/linked.md)\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "assurance" / "document_register_v1.yaml").write_text(
        "documents:\n"
        "- id: DOC-901\n  path: docs/assurance/linked.md\n  status: canonical\n"
        "- id: DOC-902\n  path: docs/assurance/orphan.md\n  status: canonical\n",
        encoding="utf-8",
    )
    mod.ROOT = tmp_path
    errors: list[str] = []
    mod.check_index_completeness(errors)
    assert len(errors) == 1, errors
    assert "DOC-902" in errors[0] and "orphan.md" in errors[0]


def test_index_completeness_ignores_non_live_statuses(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "docs" / "assurance").mkdir(parents=True)
    (tmp_path / "docs" / "README.md").write_text("# Index\n", encoding="utf-8")
    (tmp_path / "docs" / "assurance" / "document_register_v1.yaml").write_text(
        "documents:\n"
        "- id: DOC-903\n  path: docs/assurance/old.md\n  status: superseded\n"
        "- id: DOC-904\n  path: docs/assurance/hist.md\n  status: historical\n",
        encoding="utf-8",
    )
    mod.ROOT = tmp_path
    errors: list[str] = []
    mod.check_index_completeness(errors)
    assert errors == [], errors


def test_the_live_index_links_every_live_registered_document() -> None:
    mod = _load_module()
    errors: list[str] = []
    mod.check_index_completeness(errors)
    assert errors == [], errors
