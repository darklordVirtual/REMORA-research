from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_hook_docs_do_not_cite_canonical_v_value() -> None:
    text = (ROOT / "docs" / "agent_tool_hook.md").read_text(encoding="utf-8")
    assert "not a canonical benchmark score" in text
    assert "Do not cite a single `V(t)` value" in text
    assert "1.3941" not in text


def test_scaling_docs_match_current_k_star_formula() -> None:
    text = (ROOT / "remora" / "theory" / "scaling_analysis.py").read_text(encoding="utf-8")
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
        ROOT / "paper" / "whitepaper.md",
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
    text = (ROOT / "EVIDENCE_OF_CAPABILITY.md").read_text(encoding="utf-8")
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


def test_project_license_references_are_apache_not_mit() -> None:
    """Project-authored license surfaces must not drift back to MIT.

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


def test_licensing_is_plain_apache_without_commercial_boundary_docs() -> None:
    """Licensing surface is a single Apache-2.0 grant plus a minimal NOTICE.

    The former ENTERPRISE_LICENSE.md / TRADEMARKS.md open-core boundary was
    deliberately removed (owner decision, 2026-07-20): the commercial-boundary
    documents overstated the project's posture for a research repository.
    """
    removed_files = [
        ROOT / "TRADEMARKS.md",
        ROOT / "ENTERPRISE_LICENSE.md",
    ]
    for path in removed_files:
        assert not path.exists(), f"{path} was deliberately removed; do not reintroduce"

    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Apache License" in notice
    assert "Stian Skogbrott" in notice
    assert "Luftfiber AS" in notice
    for overreach in ["enterprise agreement", "trademark", "proprietary"]:
        assert overreach not in notice.lower(), f"NOTICE must stay minimal: {overreach!r}"


def test_decision_envelope_audit_hash_semantics_are_documented() -> None:
    text = (ROOT / "docs" / "decision_envelope_audit.md").read_text(encoding="utf-8")
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
