# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER Orchestrator — the closed-loop meta-cognitive core.

AromerOrchestrator wraps RemoraDecisionEngine with:
  1. World-model trust adjustment  (DomainHarmPrior)
  2. Adapter-bridge strategy       (ThermodynamicAdapter + AdaptiveThresholdEngine + OracleBandit)
  3. Persistent episodic memory    (EpisodicStore)
  4. Async MetaJudge critique      (Workers AI LLM-as-judge)
  5. Continuous learning loop      (adapt() called by CF Worker cron or manually)

EXPERIMENTAL: This is a research prototype exploring meta-cognitive AI governance.
Claims are limited to what is backed by artifacts and tests. AROMER is not AGI.

Usage
-----
    from remora.aromer import AromerOrchestrator, OutcomeType

    aromer = AromerOrchestrator()

    # Govern an agent action
    report, episode_id = aromer.decide(obs)

    # Later: record what actually happened
    aromer.record_outcome(episode_id, OutcomeType.CORRECT_ACCEPT)

    # Run one learning cycle (also runs automatically every hour via CF Worker)
    aromer.adapt()

    # Inspect what AROMER has learned
    print(aromer.summary())
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from remora.aromer.experience.episode import Episode, GroundTruth, OutcomeType
from remora.aromer.experience.store import EpisodicStore
from remora.aromer.integration.bridge import AromerAdapterBridge
from remora.aromer.meta_judge.judge import AromerMetaJudge
from remora.aromer.world_model.domain_prior import DomainHarmPrior
from remora.aromer.evals.replay_runner import run_arena
from remora.policy import RemoraDecisionEngine, PolicyObservation
from remora.policy.report import DecisionReport

_VERSION = "0.2.0-experimental"
_WORLD_MODEL_MAX_ECE = 0.10
_WORLD_MODEL_MIN_OBSERVATIONS = 10


@dataclass
class AromerDecision:
    """Result of one AROMER governance decision."""

    episode_id: str
    report: DecisionReport
    world_model_adjustment: float  # how much trust_score was adjusted
    adapted_lambda: float
    oracle_ranking: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "verdict": self.report.action.value,
            "human_review_required": self.report.human_review_required,
            "world_model_adjustment": round(self.world_model_adjustment, 4),
            "adapted_lambda": round(self.adapted_lambda, 6),
            "oracle_ranking": self.oracle_ranking,
        }


class AromerOrchestrator:
    """AROMER — Autonomous REMORA Orchestrator, Meta-Emergent Reasoner.

    The closed-loop meta-cognitive governance layer that learns from every
    decision and continuously improves its governance strategy.

    Parameters
    ----------
    store_path:      Path for persistent episodic memory JSONL.
    world_model_path: Path for world model Bayesian priors JSON.
    bridge_state_path: Path for adapter bridge state JSON.
    run_meta_judge:  If True, critique recent episodes asynchronously on adapt().
    meta_judge_batch: Max episodes per meta-judge cycle (controls cost).
    """

    VERSION = _VERSION

    def __init__(
        self,
        store_path: str | None = None,
        world_model_path: str | None = None,
        bridge_state_path: str | None = None,
        *,
        run_meta_judge: bool = True,
        meta_judge_batch: int = 5,
        world_model_shadow_mode: bool = True,
        world_model_activation_ece: float = _WORLD_MODEL_MAX_ECE,
        world_model_activation_min_observations: int = _WORLD_MODEL_MIN_OBSERVATIONS,
        run_replay_arena: bool = True,
    ) -> None:
        self._engine   = RemoraDecisionEngine()
        self._store    = EpisodicStore(store_path)
        self._world    = DomainHarmPrior(
            world_model_path,
            shadow_mode=world_model_shadow_mode,
        )
        self._bridge   = AromerAdapterBridge(bridge_state_path)
        self._judge    = AromerMetaJudge() if run_meta_judge else None
        self._run_judge = run_meta_judge
        self._judge_batch = meta_judge_batch
        self._adapt_count = 0
        self._world_model_activation_ece = world_model_activation_ece
        self._world_model_activation_min_observations = (
            world_model_activation_min_observations
        )
        self._run_replay_arena = run_replay_arena

    # ------------------------------------------------------------------
    # Core governance API
    # ------------------------------------------------------------------

    def decide(self, obs: PolicyObservation) -> tuple[DecisionReport, str]:
        """Govern an agent action through the AROMER closed loop.

        Returns
        -------
        (DecisionReport, episode_id)
        The episode_id can be used later to record the observed outcome.
        """
        # 1. World-model trust adjustment
        original_trust = obs.trust_score
        adjusted_trust = self._world.adjust_trust(
            obs.trust_score,
            domain=obs.domain or "unknown",
            action_type=obs.action_type or "execution",
            risk_tier=obs.risk_tier or "medium",
        )
        # No trust signal to adjust (obs.trust_score is None) → no adjustment.
        world_adjustment = (
            (adjusted_trust - original_trust)
            if (adjusted_trust is not None and original_trust is not None)
            else 0.0
        )

        # Build adjusted observation
        adjusted_obs = _replace_trust(obs, adjusted_trust)

        # 2. Inject conformal trust threshold once the world model is calibrated.
        # When shadow_mode=False (ECE < 0.10 and n_obs >= 10), the world model
        # has enough data to trust its adjustments. At that point, activating the
        # conformal ACCEPT path reduces unnecessary VERIFY on benign actions.
        # The threshold uses the bridge's adapted trust_critical_min + a safety
        # offset of +0.27 so ACCEPT only fires well above the ESCALATE floor.
        if not self._world.shadow_mode:
            raw_min = self._bridge.get_threshold("trust_critical_min")
            self._engine.conformal_trust_threshold = min(
                0.85, raw_min + 0.27
            )
        else:
            self._engine.conformal_trust_threshold = None

        # 2. Governance decision through REMORA
        report = self._engine.decide(adjusted_obs)

        # 3. Build and persist episode
        episode = Episode(
            domain=obs.domain or "unknown",
            risk_tier=obs.risk_tier or "medium",
            action_type=obs.action_type or "execution",
            phase=_phase_from_H(obs.final_H),
            trust_score=adjusted_trust,
            entropy_H=obs.final_H,
            dissensus_D=obs.final_D,
            verdict=report.action.value,
            confidence=_confidence_from_report(report),
            rules_triggered=_rules_from_report(report),
            meta={
                "original_trust": original_trust,
                "world_adjustment": world_adjustment,
                "world_model_shadow_mode": self._world.shadow_mode,
                "oracle_ranking": self._bridge.select_oracles(3),
                "adapted_lambda": self._bridge.adapted_lambda(),
            },
        )
        episode_id = self._store.record(episode)

        return report, episode_id

    def record_outcome(
        self,
        episode_id: str,
        outcome: OutcomeType,
        severity: float = 0.0,
    ) -> bool:
        """Record the observed outcome for a past episode.

        This is the primary feedback entry point.  Call this after the
        governed action has been observed to succeed or fail.

        Parameters
        ----------
        episode_id: returned by decide()
        outcome:    one of OutcomeType.*
        severity:   -1.0 (serious harm) … +1.0 (major benefit)

        Returns True if the episode was found and updated.
        """
        updated = self._store.update_outcome(episode_id, outcome, severity)
        if updated:
            episode = self._store.get(episode_id)
            if episode:
                # Propagate to all adapters
                self._bridge.record_outcome(episode)
                # Bayesian world-model update
                if episode.decision_quality is not None:
                    weight = self._world.update_from_quality(
                        domain=episode.domain,
                        action_type=episode.action_type,
                        risk_tier=episode.risk_tier,
                        decision_quality=episode.decision_quality,
                    )
                    episode.meta["world_model_update_weight"] = weight
        return updated

    def record_ground_truth(
        self,
        episode_id: str,
        ground_truth: GroundTruth,
        severity: float = 0.0,
    ) -> bool:
        """Record harmful/benign truth and derive decision quality internally."""
        updated = self._store.update_ground_truth(episode_id, ground_truth, severity)
        if updated:
            episode = self._store.get(episode_id)
            if episode:
                self._bridge.record_outcome(episode)
                if episode.decision_quality is not None:
                    weight = self._world.update_from_quality(
                        domain=episode.domain,
                        action_type=episode.action_type,
                        risk_tier=episode.risk_tier,
                        decision_quality=episode.decision_quality,
                    )
                    episode.meta["world_model_update_weight"] = weight
        return updated

    # ------------------------------------------------------------------
    # Learning cycle
    # ------------------------------------------------------------------

    def adapt(self, domain: str | None = None) -> dict[str, Any]:
        """Run one full learning cycle.

        Steps:
        1. Run MetaJudge critique on recent episodes with known outcomes
        2. Propagate pending outcomes to adapters
        3. Run threshold adaptation cycle
        4. Return adaptation report

        This is called by the CF Worker cron every hour.
        """
        self._adapt_count += 1
        # TTL-resolve stale pending episodes first so freshly presumed-benign
        # episodes participate in this cycle's statistics (mirrors the worker).
        pending_resolution = self._store.resolve_stale_pending(
            world_model=self._world,
        )
        report: dict[str, Any] = {
            "cycle": self._adapt_count,
            "store_size": self._store.size,
            "pending_resolution": pending_resolution,
            "pending_outcomes": len(self._store.pending_outcomes()),
        }

        # Meta-judge critique on recent labelled episodes
        if self._run_judge and self._judge:
            recent_labelled = [
                e for e in self._store.recent(50, with_outcome_only=True)
                if e.critique_score is None
            ][: self._judge_batch]

            critiques = self._judge.critique_batch(recent_labelled)
            for critique in critiques:
                self._store.update_critique(
                    critique.episode_id,
                    critique.score,
                    critique.reasoning,
                )
            report["meta_judge_critiques"] = len(critiques)
            if critiques:
                report["mean_critique_score"] = round(
                    sum(c.score for c in critiques) / len(critiques), 4
                )

        # Adapter adaptation cycle
        bridge_report = self._bridge.adapt(domain=domain)
        report["adaptation"] = bridge_report

        # Experience statistics
        summary = self._store.summary()
        report["experience"] = {
            "total_episodes":   summary.total,
            "n_harmful":        summary.n_harmful,
            "n_benign":         summary.n_benign,
            "n_unknown":        summary.n_unknown,
            "false_accept_rate": summary.false_accept_rate,
            "hard_fpr":          summary.hard_fpr,
            "review_friction":   summary.review_friction,
            "correct_intercept_rate": summary.correct_intercept_rate,
            "false_block_rate":  summary.false_block_rate,
            "safety_violations": summary.safety_violations,
            "mean_critique_score": summary.mean_critique_score,
        }

        # World model highlights
        report["world_model"] = self._world.summary()
        report["world_model_activation"] = self._update_world_model_activation(
            summary.false_accept_rate
        )
        if self._run_replay_arena:
            replay_report = run_arena(engine=RemoraDecisionEngine())
            report["replay_arena"] = {
                "total_episodes": replay_report.total_episodes,
                "overall_accuracy": replay_report.overall_accuracy,
                "replay_score": replay_report.sis.sis,
                "transfer_score": replay_report.sis.transfer_success,
                "false_accept_rate": replay_report.false_accept_rate,
                "cross_domain_transfer": _cross_domain_transfer(replay_report),
            }

        return report

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a snapshot of AROMER's current learned state."""
        bridge_s = self._bridge.summary()
        store_s  = self._store.summary()
        return {
            "version":        self.VERSION,
            "adapt_cycles":   self._adapt_count,
            "store_size":     self._store.size,
            "experience":     store_s.to_dict(),
            "bridge":         bridge_s,
            "world_model":    self._world.summary(),
            "world_model_activation": self._world_model_activation_state(),
        }

    def status(self) -> dict[str, Any]:
        """Lightweight health check."""
        return {
            "version":      self.VERSION,
            "store_size":   self._store.size,
            "adapt_cycles": self._adapt_count,
            "bridge_lambda": round(self._bridge.adapted_lambda(), 6),
            "world_model_active": not self._world.shadow_mode,
        }

    def _update_world_model_activation(
        self,
        false_accept_rate: float | None,
    ) -> dict[str, Any]:
        """Activate calibrated world-model trust adjustment; revert on safety drift."""
        if false_accept_rate is not None and false_accept_rate > 0:
            self._world.shadow_mode = True
            return self._world_model_activation_state(
                reason="reverted_false_accept_rate"
            )

        ece = _world_model_ece(self._store.recent(self._store.size), self._world)
        summary = self._store.summary()
        n_observations = summary.n_harmful + summary.n_benign
        if (
            self._world.shadow_mode
            and ece < self._world_model_activation_ece
            and n_observations >= self._world_model_activation_min_observations
        ):
            self._world.shadow_mode = False
            return self._world_model_activation_state(reason="activated")

        return self._world_model_activation_state(reason="unchanged")

    def _world_model_activation_state(self, reason: str = "") -> dict[str, Any]:
        summary = self._store.summary()
        labelled = summary.n_harmful + summary.n_benign
        ece = _world_model_ece(self._store.recent(self._store.size), self._world)
        return {
            "active": not self._world.shadow_mode,
            "shadow_mode": self._world.shadow_mode,
            "ece": round(ece, 4),
            "n_observations": labelled,
            "max_ece": self._world_model_activation_ece,
            "min_observations": self._world_model_activation_min_observations,
            "reason": reason,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _replace_trust(obs: PolicyObservation, new_trust: float) -> PolicyObservation:
    """Return a copy of PolicyObservation with a new trust_score."""
    # PolicyObservation is a dataclass — use dataclasses.replace
    from dataclasses import replace
    return replace(obs, trust_score=new_trust)


def _phase_from_H(entropy_H: float | None) -> str:
    # No thermodynamic state → conservative "critical", matching the
    # PolicyObservation contract (missing phase is treated as critical).
    # Minimal observations (no final_H) must not crash the primary path.
    if entropy_H is None:
        return "critical"
    if entropy_H < 0.45:
        return "ordered"
    if entropy_H < 0.75:
        return "critical"
    return "disordered"


def _confidence_from_report(report: DecisionReport) -> float:
    try:
        return float(getattr(report, "confidence", 0.5))
    except Exception:
        return 0.5


def _rules_from_report(report: DecisionReport) -> list[str]:
    try:
        reasons = getattr(report, "reasons", None)
        if reasons:
            return [str(r) for r in reasons]
        reason = getattr(report, "reason", None)
        if reason:
            return [str(reason)]
    except Exception:
        pass
    return []


def _world_model_ece(episodes: list[Episode], world: DomainHarmPrior) -> float:
    """Expected calibration error for labelled episodes against world priors."""
    labelled = [e for e in episodes if e.ground_truth != GroundTruth.UNKNOWN]
    if not labelled:
        return 0.5

    buckets: dict[float, list[tuple[Episode, float]]] = {}
    for episode in labelled:
        p_harm = world.p_harm(
            episode.domain,
            episode.action_type,
            episode.risk_tier,
        )
        bucket = round(p_harm, 1)
        buckets.setdefault(bucket, []).append((episode, p_harm))

    ece = 0.0
    for bucket_items in buckets.values():
        observed = sum(
            1 for episode, _p_harm in bucket_items
            if episode.ground_truth == GroundTruth.HARMFUL
        ) / len(bucket_items)
        predicted = sum(p_harm for _episode, p_harm in bucket_items) / len(bucket_items)
        ece += (len(bucket_items) / len(labelled)) * abs(predicted - observed)
    return ece


def _cross_domain_transfer(replay_report: Any) -> dict[str, Any]:
    """Summarise whether database safety patterns transfer to financial cases."""
    transfer_cases = [
        result for result in replay_report.results
        if result.category == "transfer"
    ]
    database_to_financial = [
        result for result in transfer_cases
        if result.domain == "financial"
        and "database_to_financial" in result.tags
    ]
    n = len(database_to_financial)
    correct = sum(1 for result in database_to_financial if result.match)
    return {
        "database_to_financial_accuracy": round(correct / n, 4) if n else 0.0,
        "database_to_financial_cases": n,
        "database_to_financial_correct": correct,
    }
