# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER AdapterBridge — unifies REMORA's existing adaptation components.

Connects:
  ThermodynamicAdapter   (SGD-based λ coupling update)
  AdaptiveThresholdEngine (exponential-decay threshold tightening/relaxing)
  OracleBandit           (Thompson Sampling oracle selection)

into a single facade that AROMER's orchestrator calls before and after
each governance decision.

EXPERIMENTAL: Part of the AROMER research plugin.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from remora.adaptation.thermodynamic_adapter import ThermodynamicAdapter
from remora.adaptation.oracle_bandit import OracleBandit
from remora.aromer.experience.episode import Episode, OutcomeType
from remora.policy.adaptive_thresholds import (
    AdaptiveThresholdEngine,
    OutcomeRecord,
    OutcomeType as PolicyOutcomeType,
)

import time

_DEFAULT_BRIDGE_STATE = Path.home() / ".aromer" / "bridge_state.json"

# Thresholds that AROMER manages
_MANAGED_THRESHOLDS = {
    "entropy_critical_min":   (0.55, 0.30, 0.80),   # (base, min, max)
    "trust_critical_min":     (0.45, 0.20, 0.75),
    "dissensus_escalate_min": (0.65, 0.45, 0.90),
}

# Workers AI oracle pool
_ORACLE_POOL = ["cf_fast", "cf_strong", "cf_diverse"]


@dataclass
class BridgeState:
    """Serialisable snapshot of adapter state."""

    n_episodes: int
    lambda_coupling: float
    phase_weights: dict[str, float]
    oracle_ranking: list[str]
    threshold_states: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AromerAdapterBridge:
    """Unified facade over REMORA's adaptation components.

    Usage
    -----
    bridge = AromerAdapterBridge()

    # Before decision: get recommended oracle order
    oracles = bridge.select_oracles(n=3)

    # After decision + outcome:
    bridge.record_outcome(episode)

    # Periodically: run one adaptation cycle
    report = bridge.adapt(domain="financial")

    # Retrieve adapted threshold for policy gate
    t = bridge.get_threshold("entropy_critical_min")
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        proposals_path: str | Path | None = None,
    ) -> None:
        self._thermo   = ThermodynamicAdapter()
        self._threshold = AdaptiveThresholdEngine(
            decay_half_life_hours=72.0,
            tightening_rate=0.15,
            relaxation_rate=0.03,
        )
        self._bandit   = OracleBandit(_ORACLE_POOL)
        self._state_path = Path(state_path) if state_path else _DEFAULT_BRIDGE_STATE
        self._n_episodes = 0
        # Friction optimizer proposals file; defaults to repo artifacts/ directory
        if proposals_path is not None:
            self._proposals_path = Path(proposals_path)
        else:
            _repo = Path(__file__).resolve().parents[3]
            self._proposals_path = _repo / "artifacts" / "candidate_threshold_adjustments.json"

        for name, (base, lo, hi) in _MANAGED_THRESHOLDS.items():
            self._threshold.register_threshold(name, base, min_value=lo, max_value=hi)

        self._load_state()

    # ------------------------------------------------------------------
    # Pre-decision: oracle selection
    # ------------------------------------------------------------------

    def select_oracles(self, n: int = 3) -> list[str]:
        """Return top-n oracles ranked by Thompson Sampling."""
        return self._bandit.select(n)

    # ------------------------------------------------------------------
    # Post-decision: outcome propagation
    # ------------------------------------------------------------------

    def record_outcome(self, episode: Episode) -> None:
        """Propagate an episode outcome to all adapters."""
        outcome = episode.outcome
        correct = outcome.to_correct()
        if correct is None:
            return  # Unknown / pending outcomes don't update adapters

        self._n_episodes += 1

        # Thermodynamic adapter. λ is learned from the dissensus/entropy ↔
        # outcome correlation; episodes recorded without thermodynamic state
        # (minimal PolicyObservation, no final_H/final_D) carry no such signal.
        # Skip the λ update rather than fabricate a neutral value that would
        # dilute the learned coupling — threshold and bandit updates below
        # still run, so the episode is not lost to the loop.
        if episode.dissensus_D is not None and episode.entropy_H is not None:
            self._thermo.record_outcome(
                dissensus=episode.dissensus_D,
                entropy=episode.entropy_H,
                phase=episode.phase,  # type: ignore[arg-type]
                verdict=episode.verdict,  # type: ignore[arg-type]
                correct=correct,
            )

        # Threshold engine — map AROMER outcome to policy outcome type
        policy_outcome = (
            PolicyOutcomeType.CORRECT_ACCEPT if outcome == OutcomeType.CORRECT_ACCEPT
            else PolicyOutcomeType.CORRECT_BLOCK if outcome == OutcomeType.CORRECT_BLOCK
            else PolicyOutcomeType.FALSE_ACCEPT if outcome == OutcomeType.FALSE_ACCEPT
            else PolicyOutcomeType.FALSE_BLOCK if outcome == OutcomeType.FALSE_BLOCK
            else PolicyOutcomeType.SAFETY_VIOLATION if outcome == OutcomeType.SAFETY_VIOLATION
            else PolicyOutcomeType.UNKNOWN
        )
        self._threshold.record_outcome(OutcomeRecord(
            timestamp=time.time(),
            outcome=policy_outcome,
            domain=episode.domain,
            risk_tier=episode.risk_tier,
            confidence_at_decision=episode.confidence,
        ))

        # Oracle bandit — credit only the oracle(s) actually consulted.
        # Crediting the whole pool with one shared `correct` signal (the v0.1
        # behaviour) drove every arm to an identical posterior (live state:
        # alpha=19287, beta=1 for all three), so Thompson Sampling degenerated
        # to noise and "oracle accuracy" became meaningless. We now credit the
        # episode's recorded oracles_used; when provenance is unknown we credit
        # only the primary oracle rather than fabricating signal for arms that
        # never ran.
        consulted = [o for o in episode.oracles_used if o in self._bandit._alpha]
        if not consulted:
            consulted = [_ORACLE_POOL[0]]  # primary only; never the whole pool
        for oracle_id in consulted:
            self._bandit.update(oracle_id, correct)

        self._save_state()

    # ------------------------------------------------------------------
    # Adaptation cycle
    # ------------------------------------------------------------------

    def adapt(self, domain: str | None = None) -> dict[str, Any]:
        """Run one adaptation cycle; return report."""
        report = self._threshold.adapt(domain=domain)
        thermo_state = self._thermo.state()
        friction_report = self._apply_friction_optimizer_proposals()
        self._save_state()
        return {
            "n_episodes": self._n_episodes,
            "threshold_report": report.to_dict(),
            "thermodynamic": {
                "lambda": thermo_state.lambda_coupling,
                "converged": thermo_state.converged,
                "v_params": thermo_state.v_params,
            },
            "oracle_ranking": self._bandit.ranking(),
            "friction_optimizer": friction_report,
        }

    def _apply_friction_optimizer_proposals(self) -> dict[str, Any]:
        """Consume approved proposals from the friction optimizer and apply deltas.

        Reads the configured proposals file (default: repo artifacts/).
        For each approved proposal (FA rate == 0 on holdout), relaxes
        ``trust_critical_min`` by the proposal's max_delta, capped at 0.05/cycle.

        The link between "reduce friction for scope X" and the managed thresholds:
        lower ``trust_critical_min`` widens the ACCEPT band so that ordered-phase
        actions with moderate trust scores pass without VERIFY.
        """
        try:
            proposals_path = self._proposals_path
            if not proposals_path.exists():
                return {"applied": 0, "skipped": 0}

            data = json.loads(proposals_path.read_text(encoding="utf-8"))
            adjustments = data.get("adjustments", [])

            approved = [a for a in adjustments if a.get("approved") is True]
            if not approved:
                return {"applied": 0, "skipped": len(adjustments)}

            # Aggregate total delta across approved scopes, cap at 0.05
            total_delta = min(0.05, sum(a.get("max_delta", 0.0) for a in approved))
            if total_delta <= 0:
                return {"applied": 0, "skipped": len(adjustments)}

            current = self._threshold.get_threshold("trust_critical_min")
            # Relax (lower) the threshold — wider ACCEPT band, same safety floor
            new_val = max(
                _MANAGED_THRESHOLDS["trust_critical_min"][1],  # min bound
                current - total_delta,
            )
            self._threshold._thresholds["trust_critical_min"].current_value = new_val

            # Consume the proposals (rename so they're not reapplied next cycle)
            consumed_path = proposals_path.with_suffix(".consumed.json")
            proposals_path.rename(consumed_path)

            return {
                "applied": len(approved),
                "skipped": len(adjustments) - len(approved),
                "trust_critical_min_before": round(current, 4),
                "trust_critical_min_after": round(new_val, 4),
                "total_delta": round(total_delta, 4),
            }
        except Exception:
            return {"applied": 0, "skipped": 0, "error": "proposals file unreadable"}

    # ------------------------------------------------------------------
    # Threshold access
    # ------------------------------------------------------------------

    def get_threshold(self, name: str) -> float:
        """Return current adapted value of a managed threshold."""
        return self._threshold.get_threshold(name)

    def adapted_lambda(self) -> float:
        return self._thermo.adapted_lambda()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def state(self) -> BridgeState:
        return BridgeState(
            n_episodes=self._n_episodes,
            lambda_coupling=round(self._thermo.adapted_lambda(), 6),
            phase_weights={k: round(v, 4) for k, v in
                           self._thermo.adapted_phase_weights().items()},
            oracle_ranking=self._bandit.ranking(),
            threshold_states={
                name: round(self._threshold.get_threshold(name), 4)
                for name in _MANAGED_THRESHOLDS
            },
        )

    def summary(self) -> dict[str, Any]:
        return {
            **self.state().to_dict(),
            "thermo": self._thermo.summary(),
            "oracle_bandit": self._bandit.summary(),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "n_episodes": self._n_episodes,
            "thermo_lambda": self._thermo.adapted_lambda(),
            "oracle_alpha": {k: v for k, v in self._bandit._alpha.items()},
            "oracle_beta":  {k: v for k, v in self._bandit._beta.items()},
        }
        self._state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._n_episodes = payload.get("n_episodes", 0)
            # Restore oracle posteriors
            for oid in _ORACLE_POOL:
                if oid in payload.get("oracle_alpha", {}):
                    self._bandit._alpha[oid] = payload["oracle_alpha"][oid]
                    self._bandit._beta[oid]  = payload["oracle_beta"].get(oid, 1.0)
        except Exception:
            pass
