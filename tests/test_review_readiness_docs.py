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
        ROOT / "enterprise" / "executive-brief.md",
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
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "implemented research heuristic" in text
    assert "candidate hallucination-bound proxy" in text
    assert "controlled safety simulation, not production evidence" in text
    assert "This is not a heuristic" not in text
    assert "not a tuned hyperparameter" not in text
    assert "formal_guarantee" not in text


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


def test_commercial_license_boundary_is_documented() -> None:
    """Keep the open-core and enterprise licensing boundary visible."""
    required_files = [
        ROOT / "NOTICE",
        ROOT / "TRADEMARKS.md",
        ROOT / "enterprise" / "ENTERPRISE_LICENSE.md",
    ]
    for path in required_files:
        assert path.exists(), path

    joined = "\n".join(path.read_text(encoding="utf-8") for path in required_files)
    for required in [
        "Stian Skogbrott",
        "Luftfiber AS",
        "Apache-2.0",
        "AROMER",
        "hosted",
        "managed",
        "separate written enterprise agreement",
        "brand",
        "support",
        "certification",
        "compliance",
        "pro layer",
        "GO-STAR",
        "law search",
        "DCE",
        "proprietary",
    ]:
        assert required in joined


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
