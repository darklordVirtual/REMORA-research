# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for TTL-based pending-outcome resolution (learning roadmap step 6).

Episodes recorded without a later outcome call stayed ground_truth=UNKNOWN
forever: excluded from every learning surface while the backlog grew without
bound. Resolution is two-stage and never invents ground truth for blocked
actions:

  Stage 1: ACCEPT episodes older than 72h with no harm reported are weak-
           labelled benign (label_source='ttl_presumed', world-model weight
           0.25 — the VERIFY partial-signal class, not observed-truth 1.0).
  Stage 2: non-ACCEPT episodes older than 7 days are expired unlabelled —
           ground truth stays UNKNOWN.

The worker's resolvePendingEpisodes() mirrors these semantics.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from remora.aromer.experience.episode import Episode, GroundTruth
from remora.aromer.experience.store import (
    PRESUMED_BENIGN_WEIGHT,
    EpisodicStore,
)
from remora.aromer.world_model.domain_prior import DomainHarmPrior

NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def _episode(verdict: str, age_hours: float, **kw) -> Episode:
    ts = (NOW - timedelta(hours=age_hours)).isoformat()
    defaults = dict(
        domain="database", risk_tier="medium", action_type="execution",
        phase="ordered", trust_score=0.7, entropy_H=0.3, dissensus_D=0.1,
        verdict=verdict, confidence=0.8,
    )
    defaults.update(kw)
    ep = Episode(**defaults)
    ep.timestamp = ts
    return ep


def _store(tmp_path) -> EpisodicStore:
    return EpisodicStore(tmp_path / "episodes.jsonl")


class TestPresumedBenign:
    def test_stale_accept_becomes_presumed_benign(self, tmp_path):
        store = _store(tmp_path)
        eid = store.record(_episode("ACCEPT", age_hours=100))
        result = store.resolve_stale_pending(now=NOW)
        assert result == {"presumed_benign": 1, "expired": 0}
        ep = store.get(eid)
        assert ep.ground_truth == GroundTruth.BENIGN
        assert ep.decision_quality is not None
        assert ep.decision_quality.value == "correct_accept"
        # Provenance: a presumed label is always distinguishable from truth.
        assert ep.label_source == "ttl_presumed"
        assert ep.label_confidence < 1.0
        assert ep.meta["label_source"] == "ttl_presumed_benign"

    def test_fresh_accept_untouched(self, tmp_path):
        store = _store(tmp_path)
        eid = store.record(_episode("ACCEPT", age_hours=10))
        result = store.resolve_stale_pending(now=NOW)
        assert result == {"presumed_benign": 0, "expired": 0}
        assert store.get(eid).ground_truth == GroundTruth.UNKNOWN

    def test_world_model_updated_at_weak_weight(self, tmp_path):
        store = _store(tmp_path)
        store.record(_episode("ACCEPT", age_hours=100))
        world = DomainHarmPrior(tmp_path / "world.json")
        before = world.stats("database", "execution", "medium")
        store.resolve_stale_pending(world_model=world, now=NOW)
        after = world.stats("database", "execution", "medium")
        # Benign evidence at the weak weight class — never full 1.0.
        assert after.beta == before.beta + PRESUMED_BENIGN_WEIGHT
        assert after.alpha == before.alpha

    def test_labelled_episodes_ignored(self, tmp_path):
        store = _store(tmp_path)
        ep = _episode("ACCEPT", age_hours=100)
        ep.record_ground_truth(GroundTruth.HARMFUL)
        eid = store.record(ep)
        result = store.resolve_stale_pending(now=NOW)
        assert result == {"presumed_benign": 0, "expired": 0}
        assert store.get(eid).ground_truth == GroundTruth.HARMFUL

    def test_resolution_persists_across_reload(self, tmp_path):
        store = _store(tmp_path)
        eid = store.record(_episode("ACCEPT", age_hours=100))
        store.resolve_stale_pending(now=NOW)
        reloaded = EpisodicStore(tmp_path / "episodes.jsonl")
        assert reloaded.get(eid).ground_truth == GroundTruth.BENIGN


class TestExpiry:
    def test_old_blocked_episode_expires_without_label(self, tmp_path):
        store = _store(tmp_path)
        eid = store.record(_episode("ESCALATE", age_hours=8 * 24))
        result = store.resolve_stale_pending(now=NOW)
        assert result == {"presumed_benign": 0, "expired": 1}
        ep = store.get(eid)
        # Ground truth is never invented for actions that did not run.
        assert ep.ground_truth == GroundTruth.UNKNOWN
        assert ep.meta["label_source"] == "ttl_expired"

    def test_expired_excluded_from_pending_backlog(self, tmp_path):
        store = _store(tmp_path)
        store.record(_episode("VERIFY", age_hours=8 * 24))
        store.record(_episode("VERIFY", age_hours=24))
        store.resolve_stale_pending(now=NOW)
        assert len(store.pending_outcomes()) == 1
        assert len(store.pending_outcomes(include_expired=True)) == 2

    def test_mid_age_verify_stays_pending(self, tmp_path):
        store = _store(tmp_path)
        eid = store.record(_episode("VERIFY", age_hours=100))
        result = store.resolve_stale_pending(now=NOW)
        assert result == {"presumed_benign": 0, "expired": 0}
        assert store.get(eid).ground_truth == GroundTruth.UNKNOWN

    def test_expiry_idempotent(self, tmp_path):
        store = _store(tmp_path)
        store.record(_episode("ESCALATE", age_hours=8 * 24))
        first = store.resolve_stale_pending(now=NOW)
        second = store.resolve_stale_pending(now=NOW)
        assert first["expired"] == 1
        assert second["expired"] == 0


class TestOrchestratorIntegration:
    def test_adapt_reports_pending_resolution(self, tmp_path):
        from remora.aromer.orchestrator import AromerOrchestrator

        aromer = AromerOrchestrator(
            store_path=str(tmp_path / "episodes.jsonl"),
            world_model_path=str(tmp_path / "world.json"),
            bridge_state_path=str(tmp_path / "bridge.json"),
            run_meta_judge=False,
            run_replay_arena=False,
        )
        aromer._store.record(_episode("ACCEPT", age_hours=100))
        report = aromer.adapt()
        assert report["pending_resolution"]["presumed_benign"] == 1
        assert report["pending_outcomes"] == 0
