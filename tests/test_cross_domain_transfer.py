# Author: Stian Skogbrott
# License: Apache-2.0
"""Cross-domain transfer (§16): the abstract prior generalises across domains,
and the leave-one-domain-out harness measures it honestly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.aromer.evals.cross_domain_transfer import (
    TransferEpisode,
    run_cross_domain_transfer,
)
from remora.aromer.world_model.domain_prior import DomainHarmPrior

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Abstract prior (the transfer mechanism)
# ---------------------------------------------------------------------------

def _prior() -> DomainHarmPrior:
    p = DomainHarmPrior(path="/tmp/does-not-persist-test")
    p._priors = {}
    return p


def test_abstract_prior_is_domain_agnostic() -> None:
    p = _prior()
    # Learn "destructive_write/critical is harmful" from database only.
    for _ in range(20):
        p.update_abstract("destructive_write", "critical", harm_occurred=True)
    # An UNSEEN domain inherits the abstract structure via backoff.
    assert p.p_harm_backoff("medical", "destructive_write", "critical") > 0.8
    # A seen domain-specific prior still wins over the abstract one.
    for _ in range(20):
        p.update("medical", "destructive_write", "critical", harm_occurred=False)
    assert p.p_harm_backoff("medical", "destructive_write", "critical") < 0.2


def test_abstract_domain_excluded_from_all_stats() -> None:
    p = _prior()
    p.update_abstract("write", "high", harm_occurred=True)
    p.update("database", "write", "high", harm_occurred=True)
    domains = {s.domain for s in p.all_stats()}
    assert "__abstract__" not in domains
    assert "database" in domains


def test_backoff_uses_domain_specific_when_observed() -> None:
    p = _prior()
    p.update_abstract("read", "low", harm_occurred=True)   # abstract says harmful
    for _ in range(10):
        p.update("git", "read", "low", harm_occurred=False)  # git says benign
    # Domain-specific evidence overrides the abstract prior.
    assert p.p_harm_backoff("git", "read", "low") < 0.5


# ---------------------------------------------------------------------------
# Leave-one-domain-out harness
# ---------------------------------------------------------------------------

def _episodes() -> list[TransferEpisode]:
    """Two domains sharing the same abstract harm structure."""
    eps: list[TransferEpisode] = []
    for domain in ("database", "medical"):
        eps += [TransferEpisode(domain, "destructive_write", "critical", True)] * 6
        eps += [TransferEpisode(domain, "read", "low", False)] * 6
    return eps


def test_transfer_measures_held_out_domain() -> None:
    report = run_cross_domain_transfer(_episodes())
    # Both domains share structure → transfer should be near-perfect.
    assert report.overall_accuracy >= 0.9
    assert report.n_target_domains == 2
    assert {f.target_domain for f in report.folds} == {"database", "medical"}


def test_target_domain_never_seen_during_its_fold() -> None:
    """Structural guarantee: a fold's source updates exclude the target."""
    eps = _episodes()
    report = run_cross_domain_transfer(eps)
    for f in report.folds:
        target_count = sum(1 for e in eps if e.domain == f.target_domain)
        # source updates = all episodes minus this domain's.
        assert f.n_source_updates == len(eps) - target_count


def test_requires_two_domains() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        run_cross_domain_transfer(
            [TransferEpisode("only", "read", "low", False)] * 5
        )


def test_worker_report_shape_has_cases_keys() -> None:
    report = run_cross_domain_transfer(_episodes())
    cdt = report.to_worker_report()["cross_domain_transfer"]
    # The live worker sums keys ending in "_cases".
    assert any(k.endswith("_cases") for k in cdt)
    assert cdt["measured"] is True
    total_cases = sum(v for k, v in cdt.items() if k.endswith("_cases"))
    assert total_cases == report.n_target_cases


# ---------------------------------------------------------------------------
# Committed artifact is reproducible
# ---------------------------------------------------------------------------

def test_committed_artifact_matches_regeneration() -> None:
    artifact = ROOT / "results" / "aromer_cross_domain_transfer_v1.json"
    if not artifact.exists():
        pytest.skip("artifact not generated; run scripts/run_cross_domain_transfer.py")
    committed = json.loads(artifact.read_text(encoding="utf-8"))
    assert committed["schema_version"] == "aromer_cross_domain_transfer_v1"
    # Deterministic: regenerating from the same templates gives the same headline.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rcdt", ROOT / "scripts" / "run_cross_domain_transfer.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    regen = run_cross_domain_transfer(mod._episodes())
    assert round(regen.overall_accuracy, 4) == committed["overall_accuracy"]
