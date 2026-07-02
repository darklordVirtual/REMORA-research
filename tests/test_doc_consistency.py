# Author: Stian Skogbrott
# License: Apache-2.0
"""Documentation-consistency guard (external-review readiness).

An external technical review flagged architecture-narrative drift: the root
ARCHITECTURE.md carried a stale "fact-verification system" framing (SciFact /
FEVER / HotpotQA benchmark loaders, converged_threshold=0.72) that contradicted
the current "governance overlay for agent actions" story. This test locks the
canonical framing so the drift cannot silently return, and pins doc-stated
hyperparameters to the code they claim to describe.

Deliberately strict: a claim-hygiene repo must not let its canonical
architecture doc and its code point in two different directions.
"""
from __future__ import annotations

from pathlib import Path

from remora.genome import Genome

_ROOT = Path(__file__).resolve().parents[1]
_ARCH = _ROOT / "ARCHITECTURE.md"


def _arch_text() -> str:
    return _ARCH.read_text(encoding="utf-8")


def test_architecture_doc_exists() -> None:
    assert _ARCH.exists(), "ARCHITECTURE.md must exist as the canonical architecture reference"


def test_architecture_uses_current_governance_framing() -> None:
    text = _arch_text().lower()
    assert "governance overlay" in text, "ARCHITECTURE.md must frame REMORA as a governance overlay"
    assert "hard-block policy invariants" in text, (
        "ARCHITECTURE.md must describe the Stage-1 hard-block policy layer"
    )
    # The four canonical outcomes.
    for outcome in ("ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"):
        assert outcome in _arch_text(), f"ARCHITECTURE.md must document the {outcome} outcome"


def test_architecture_doc_has_no_fact_verification_primary_framing() -> None:
    """The stale fact-verification benchmark-loader narrative must not return.

    (An honest one-line 'Evolution' note about the project's claim-verification
    origins is fine — it does not name these benchmark loaders.)
    """
    text = _arch_text()
    for stale in ("SciFact", "FEVER", "HotpotQA"):
        assert stale not in text, (
            f"stale fact-verification framing '{stale}' returned to ARCHITECTURE.md — "
            "REMORA governs agent actions, it is not a fact-checker"
        )


def test_architecture_converged_threshold_matches_code() -> None:
    """Every doc mention of converged_threshold must state the genome value."""
    expected = Genome().converged_threshold  # 0.75
    hits = [ln for ln in _arch_text().splitlines() if "converged_threshold" in ln]
    assert hits, "ARCHITECTURE.md should document converged_threshold"
    for line in hits:
        assert str(expected) in line, (
            f"converged_threshold in ARCHITECTURE.md is out of sync with genome.py "
            f"(expected {expected}): {line.strip()!r}"
        )
        assert "0.72" not in line, (
            f"stale converged_threshold=0.72 present in ARCHITECTURE.md: {line.strip()!r}"
        )


def test_architecture_declares_shadow_only_scope() -> None:
    """External-review readiness: the doc must state the honest maturity scope."""
    text = _arch_text()
    assert "SHADOW_ONLY" in text, "ARCHITECTURE.md must state deployment status SHADOW_ONLY"
    assert "tamper-evident" in text.lower(), (
        "ARCHITECTURE.md must describe the audit chain as tamper-evident (not tamper-proof)"
    )


def test_pyproject_urls_point_to_this_repo() -> None:
    """Metadata-drift guard: this repo's package URLs must point to
    REMORA-research, not the private main REMORA repo (external-review finding)."""
    import tomllib

    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    urls = pyproject.get("project", {}).get("urls", {})
    repo = urls.get("Repository", "")
    assert repo.endswith("REMORA-research"), (
        f"pyproject Repository URL should point to REMORA-research, got {repo!r}"
    )
