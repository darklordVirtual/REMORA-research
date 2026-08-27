from __future__ import annotations

import pytest

from pathlib import Path

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate


ROOT = Path(__file__).resolve().parents[1]


def test_agent_hook_docs_do_not_cite_canonical_v_value() -> None:
    text = (ROOT / "docs" / "integrations" / "agent_tool_hook.md").read_text(encoding="utf-8")
    assert "not a canonical benchmark score" in text
    assert "Do not cite a single `V(t)` value" in text
    assert "1.3941" not in text


def test_scaling_docs_match_current_k_star_formula() -> None:
    text = (ROOT / "remora" / "research_attic" / "theory" / "scaling_analysis.py").read_text(encoding="utf-8")
    assert "decreases as 1/log T" in text
    assert "grows sub-logarithmically" not in text


def test_claim_register_separates_evidence_levels() -> None:
    text = (ROOT / "docs" / "claim_register.md").read_text(encoding="utf-8")
    for required in [
        "Strong Numeric Support",
        "Theoretical Derivations",
        "Internal Empirical Observations",
        "Requires External Replication",
        "Citation Discipline",
    ]:
        assert required in text


def test_public_docs_do_not_pin_stale_test_counts() -> None:
    docs = [
        ROOT / "README.md",
        ROOT / "Makefile",
        ROOT / "paper" / "remora_paper.md",
        ROOT / "docs" / "deployment" / "onprem-airgapped.md",
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in docs)
    stale_phrases = [
        "694 passing",
        "694 tests",
        "683 tests",
        "683 selected tests",
        "650 selected tests",
    ]
    for phrase in stale_phrases:
        assert phrase not in joined


def test_readme_uses_research_candidate_language() -> None:
    # The README was rewritten from marketing language to research-accurate language.
    # This test verifies that the README contains appropriate research-candidate framing
    # that is actually present in the new README, not the old marketing copy.
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Wilson" in text, "README should include Wilson CI statistical framing"
    assert "bounded by documented assumptions" in text, "README should state result bounds"
    assert "deterministic simulator" in text, "README should distinguish simulator from production"
    assert "External replication is pending" in text, "README should state external replication status"
    assert "formal_guarantee" not in text
    assert "production-certified" not in text


def test_evidence_of_capability_states_limits() -> None:
    text = (ROOT / "docs" / "EVIDENCE_OF_CAPABILITY.md").read_text(encoding="utf-8")
    for required in [
        "What REMORA Proves",
        "What Is Implemented",
        "What Is Tested",
        "What Is Not Claimed",
        "How To Reproduce",
        "Why This Matters For Enterprise AI",
        "controlled deterministic safety simulation",
        "not as a finished production product",
    ]:
        assert required in text


def test_project_license_references_are_busl_not_mit() -> None:
    """Project-authored license surfaces must not drift back to MIT.

    REMORA's project license is BUSL-1.1 (2026-07-25). This guard catches MIT
    drift; Apache-header drift is enforced separately by
    ``scripts/check_license_policy.py``, which correctly allowlists third-party
    notices, product names (e.g. "Apache Jena"), and CVE dataset content that
    this simple scanner would false-positive on.

    This deliberately does not scan package lockfiles or upstream benchmark
    notices: dependency licenses and source dataset licenses are not REMORA's
    project license.
    """
    scanned_roots = [
        ROOT / "README.md",
        ROOT / "EVALUATOR_START_HERE.md",
        ROOT / "CITATION.cff",
        ROOT / "pyproject.toml",
        ROOT / "deploy",
        ROOT / "docs",
        ROOT / "scripts",
        ROOT / "datasets",
        ROOT / "experiments",
        ROOT / "redteam",
        ROOT / "servers",
        ROOT / "remora",
        ROOT / "tests",
        ROOT / "artifacts" / "governance-benchmark-pack",
    ]
    forbidden = [
        "MIT License",
        "MIT licensed",
        "MIT-licensed",
        "MIT license",
        "License-MIT",
        "https://opensource.org/licenses/MIT",
        "license: MIT",
        'license = { text = "MIT" }',
        "License :: OSI Approved :: MIT License",
        "License: MIT",
        '__license__ = "MIT"',
    ]
    allowed_substrings = (
        "MITRE",
        "Licence: MIT",
        "MIT for upstream",
    )
    offenders: list[str] = []
    for root in scanned_roots:
        paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in paths:
            if path == Path(__file__).resolve():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix.lower() in {
                ".pdf",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".zip",
                ".pyc",
                ".pyo",
                ".pyd",
            }:
                continue
            if path.name == "package-lock.json":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for phrase in forbidden:
                if phrase in text and not any(allowed in text for allowed in allowed_substrings):
                    offenders.append(f"{path.relative_to(ROOT)}: {phrase}")
    assert offenders == []


def test_licensing_is_bsl_with_commercial_boundary_docs() -> None:
    """Licensing surface is BUSL-1.1 plus a REMORA Commercial License boundary.

    History: the former open-core boundary docs were removed 2026-07-20 as
    overreach for a permissively-licensed research repository. On 2026-07-25 the owner
    reversed that posture: the project moved to Business Source License 1.1
    with commercial licensing (Licensor: Stian Skogbrott), which REQUIRES the
    boundary documents. This test enforces the new surface; the enforcement
    direction of its predecessor test was deliberately inverted.
    """
    required_files = [
        ROOT / "LICENSE",
        ROOT / "legal" / "LICENSING.md",
        ROOT / "legal" / "COMMERCIAL_LICENSE.md",
        ROOT / "legal" / "COPYRIGHT.md",
        ROOT / "legal" / "TRADEMARKS.md",
        ROOT / "legal" / "THIRD_PARTY_NOTICES.md",
    ]
    for path in required_files:
        assert path.exists(), f"{path.name} is required by the BSL licensing model"

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Business Source License 1.1" in license_text
    assert "Stian Skogbrott" in license_text
    assert "Additional Use Grant" in license_text
    assert "Apache" not in license_text

    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Business Source License 1.1" in notice
    assert "Stian Skogbrott" in notice
    assert "permitted without a commercial license from the Licensor" in notice

    # The informational commercial overview must never read as a grant.
    commercial = (ROOT / "legal" / "COMMERCIAL_LICENSE.md").read_text(encoding="utf-8")
    assert "not itself a commercial software" in commercial


def test_decision_envelope_audit_hash_semantics_are_documented() -> None:
    text = (ROOT / "docs" / "evidence" / "decision_envelope_audit.md").read_text(encoding="utf-8")
    for required in [
        "Compact safety hash",
        "Full replay hash-chain",
        "DecisionEnvelope.envelope_hash()",
        "verify_envelope_hash_chain()",
        "not a full forensic hash",
        "does not yet provide cryptographic signing",
        "explicit envelope schema version",
    ]:
        assert required in text
