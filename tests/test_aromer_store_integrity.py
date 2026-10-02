# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for AROMER persistence/label-integrity review findings.

1. EpisodicStore rewrites must never drop episodes that are not held in memory.
2. TTL-presumed benign labels are not observed ground truth and must not
   count towards world-model activation, false-accept rate or ECE.
3. Friction-optimizer proposals are consumed before the threshold mutates.
4. A corrupt promotion ledger is quarantined and fails closed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from remora.aromer.experience.episode import (
    Episode,
    EpisodeSummary,
    GroundTruth,
    OutcomeType,
)
from remora.aromer.experience.store import EpisodicStore


def _ep(verdict: str = "ACCEPT", **kw) -> Episode:
    return Episode(
        domain=kw.pop("domain", "safe"), risk_tier="low", action_type="read",
        phase="ordered", trust_score=0.9, entropy_H=0.2, dissensus_D=0.1,
        verdict=verdict, confidence=0.9, **kw,
    )


def _lines(path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# 1. store truncation
# ---------------------------------------------------------------------------

def test_update_with_small_max_loaded_does_not_truncate_file(tmp_path):
    path = tmp_path / "episodes.jsonl"
    store = EpisodicStore(path, max_loaded=2)
    ids = [store.record(_ep()) for _ in range(5)]
    assert len(_lines(path)) == 5

    assert store.update_ground_truth(ids[0], GroundTruth.BENIGN)

    on_disk = [json.loads(ln)["episode_id"] for ln in _lines(path)]
    assert on_disk == ids


def test_update_of_loaded_episode_preserves_unloaded_lines(tmp_path):
    path = tmp_path / "episodes.jsonl"
    seed = EpisodicStore(path)
    ids = [seed.record(_ep()) for _ in range(5)]
    store = EpisodicStore(path, max_loaded=2)  # keeps the last two in memory
    assert store.update_outcome(ids[-1], OutcomeType.CORRECT_ACCEPT)
    assert len(_lines(path)) == 5
    persisted = {json.loads(ln)["episode_id"]: json.loads(ln) for ln in _lines(path)}
    assert persisted[ids[-1]]["ground_truth"] == "benign"


def test_resolve_stale_pending_does_not_truncate_file(tmp_path):
    path = tmp_path / "episodes.jsonl"
    store = EpisodicStore(path, max_loaded=2)
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    for _ in range(5):
        store.record(_ep(timestamp=old))
    store.resolve_stale_pending()
    assert len(_lines(path)) == 5


def test_rewrite_is_atomic_via_os_replace(tmp_path, monkeypatch):
    path = tmp_path / "episodes.jsonl"
    store = EpisodicStore(path, max_loaded=2)
    ids = [store.record(_ep()) for _ in range(4)]
    before = path.read_text(encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.update_ground_truth(ids[0], GroundTruth.BENIGN)
    assert path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# 2. ttl_presumed must not count as observed truth
# ---------------------------------------------------------------------------

def test_ttl_presumed_labels_are_stored_but_not_observed(tmp_path):
    path = tmp_path / "episodes.jsonl"
    store = EpisodicStore(path)
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    eid = store.record(_ep(timestamp=old))
    store.resolve_stale_pending()
    ep = store.get(eid)
    assert ep.ground_truth == GroundTruth.BENIGN
    assert ep.label_source == "ttl_presumed"
    summary = store.summary()
    assert summary.n_benign == 0
    assert summary.n_harmful == 0


def test_summary_counts_ignore_presumed():
    obs_h = _ep()
    obs_h.record_ground_truth(GroundTruth.HARMFUL)
    pres = _ep()
    pres.record_ground_truth(GroundTruth.BENIGN)
    pres.label_source = "ttl_presumed"
    s = EpisodeSummary.from_episodes([obs_h, pres])
    assert s.n_benign == 0 and s.n_harmful == 1


def test_world_model_not_activated_from_presumed_labels_only(tmp_path):
    from remora.aromer.orchestrator import AromerOrchestrator

    aromer = AromerOrchestrator(
        store_path=str(tmp_path / "episodes.jsonl"),
        world_model_path=str(tmp_path / "world.json"),
        bridge_state_path=str(tmp_path / "bridge.json"),
        run_meta_judge=False,
        run_replay_arena=False,
        strict_shadow=False,
    )
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    for _ in range(60):
        aromer._store.record(_ep(timestamp=old))

    report = aromer.adapt()

    assert report["pending_resolution"]["presumed_benign"] == 60
    assert report["world_model_activation"]["active"] is False
    assert report["world_model_activation"]["n_observations"] == 0
    assert aromer.status()["world_model_active"] is False


# ---------------------------------------------------------------------------
# 3. friction proposals consumption
# ---------------------------------------------------------------------------

def _bridge(tmp_path):
    from remora.aromer.integration.bridge import AromerAdapterBridge

    proposals = tmp_path / "candidate_threshold_adjustments.json"
    proposals.write_text(json.dumps(
        {"adjustments": [{"approved": True, "max_delta": 0.05}]}), encoding="utf-8")
    return AromerAdapterBridge(
        state_path=tmp_path / "bridge_state.json", proposals_path=proposals
    ), proposals


def test_proposals_consumed_once_even_if_consumed_file_exists(tmp_path):
    bridge, proposals = _bridge(tmp_path)
    (tmp_path / "candidate_threshold_adjustments.consumed.json").write_text("{}")
    start = bridge.get_threshold("trust_critical_min")

    bridge._apply_friction_optimizer_proposals()
    after_first = bridge.get_threshold("trust_critical_min")
    bridge._apply_friction_optimizer_proposals()

    assert not proposals.exists()
    assert after_first == pytest.approx(start - 0.05)
    assert bridge.get_threshold("trust_critical_min") == pytest.approx(after_first)


def test_threshold_not_mutated_when_consume_fails(tmp_path, monkeypatch):
    bridge, proposals = _bridge(tmp_path)
    start = bridge.get_threshold("trust_critical_min")

    def boom(*_a, **_k):
        raise OSError("locked")

    monkeypatch.setattr(os, "replace", boom)
    bridge._apply_friction_optimizer_proposals()

    assert proposals.exists()
    assert bridge.get_threshold("trust_critical_min") == pytest.approx(start)


def test_relaxed_threshold_survives_restart(tmp_path):
    from remora.aromer.integration.bridge import AromerAdapterBridge

    bridge, proposals = _bridge(tmp_path)
    bridge.adapt()
    relaxed = bridge.get_threshold("trust_critical_min")
    assert relaxed < 0.45
    again = AromerAdapterBridge(
        state_path=tmp_path / "bridge_state.json", proposals_path=proposals
    )
    assert again.get_threshold("trust_critical_min") == pytest.approx(relaxed)


# ---------------------------------------------------------------------------
# 4. corrupt promotion ledger
# ---------------------------------------------------------------------------

def test_corrupt_ledger_is_quarantined_and_fails_closed(tmp_path):
    from remora.aromer.experience.promotion_gate import MemoryPromotionGate

    ledger = tmp_path / "promotion_ledger.json"
    ledger.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        MemoryPromotionGate(ledger_path=ledger)

    assert not ledger.exists()
    quarantined = list(tmp_path.glob("promotion_ledger.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not json"
