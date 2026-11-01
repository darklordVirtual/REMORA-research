# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from remora.adaptation.thermodynamic_adapter import ThermodynamicAdapter
from remora.adaptation.oracle_bandit import OracleBandit
from remora.aromer.experience.episode import Episode, OutcomeType
from remora.policy.adaptive_thresholds import (
    AdaptiveThresholdEngine,
    OutcomeRecord,
    OutcomeType as PolicyOutcomeType,
)

import time

def _default_bridge_state() -> Path:
    """Resolved at instantiation, never at import (external review 2026-07-24,
    F-10). REMORA_AROMER_HOME overrides the state directory (see state_paths)."""
    from remora.aromer.state_paths import default_state_path

    return default_state_path("bridge_state.json")

# Thresholds that AROMER manages
_MANAGED_THRESHOLDS = {
    "entropy_critical_min":   (0.55, 0.30, 0.80),   # (base, min, max)
    "trust_critical_min":     (0.45, 0.20, 0.75),
    "dissensus_escalate_min": (0.65, 0.45, 0.90),
}

# Workers AI oracle pool
_ORACLE_POOL = ["cf_fast", "cf_strong", "cf_diverse"]

# SEC-07 (SR-07): signed threshold proposals relax ``trust_critical_min`` by
# at most this much in total per rolling window, however many valid proposals
# arrive. The per-cycle cap and the window cap share the value on purpose:
# one proposal may spend the whole window budget, never more.
_MAX_RELAX_PER_WINDOW = 0.05
_RELAX_WINDOW_SECONDS = 7 * 24 * 3600
# A signed proposal is valid from issued_at (minus clock skew) for one window,
# and each signature is applied at most once (replay ledger kept in state).
_PROPOSAL_CLOCK_SKEW_SECONDS = 300
_MAX_SEEN_PROPOSAL_SIGS = 500


def canonical_threshold_proposal_payload(
    *,
    adjustments: list[dict[str, Any]],
    holdout_evidence_sha256: str,
    issued_at: str,
    window_id: str,
) -> bytes:
    """The canonical bytes a THRESHOLD_PROPOSAL signature signs.

    Producers, verifiers and tests share this so a signature means exactly
    one payload. The signature covers the evidence hash: a proposal cannot be
    re-pointed at a weaker holdout run after signing.
    """
    return json.dumps(
        {
            "adjustments": adjustments,
            "holdout_evidence_sha256": holdout_evidence_sha256,
            "issued_at": issued_at,
            "window_id": window_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _proposal_keys_from_env() -> list[Any]:
    """Trusted THRESHOLD_PROPOSAL public keys from REMORA_THRESHOLD_PROPOSAL_KEYS.

    Comma-separated hex/base64 Ed25519 public keys. Absent means "trust
    nobody": every proposals file is refused. A malformed entry is a
    configuration error and raises, rather than silently narrowing the
    trusted set.
    """
    from remora.crypto.domain_signing import SignatureDomain, VerificationKey

    raw = os.getenv("REMORA_THRESHOLD_PROPOSAL_KEYS", "").strip()
    if not raw:
        return []
    return [
        VerificationKey.from_text(entry.strip(), {SignatureDomain.THRESHOLD_PROPOSAL})
        for entry in raw.split(",")
        if entry.strip()
    ]


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
        *,
        proposal_verification_keys: Iterable[Any] | None = None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._thermo   = ThermodynamicAdapter()
        self._threshold = AdaptiveThresholdEngine(
            decay_half_life_hours=72.0,
            tightening_rate=0.15,
            relaxation_rate=0.03,
        )
        self._bandit   = OracleBandit(_ORACLE_POOL)
        self._state_path = Path(state_path) if state_path else _default_bridge_state()
        self._n_episodes = 0
        # SEC-07: who may relax a governance threshold, and where the change
        # is recorded. No keys configured means every proposal is refused.
        # The sink receives one threshold_changed event per applied change;
        # wire it to the tenant audit chain where one exists.
        self._proposal_keys = (
            list(proposal_verification_keys)
            if proposal_verification_keys is not None
            else _proposal_keys_from_env()
        )
        self._audit_sink = audit_sink
        self._relax_log: list[tuple[float, float]] = []
        self._seen_proposal_sigs: list[str] = []
        self._threshold_events: list[dict[str, Any]] = []
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

            raw_bytes = proposals_path.read_bytes()
            data = json.loads(raw_bytes.decode("utf-8"))
            adjustments = data.get("adjustments", [])

            # SEC-07 (SR-07): only a signed proposal may move a governance
            # threshold. An unsigned or wrongly-domained file is refused and
            # left in place for inspection — silently consuming it would hide
            # the attempt.
            if not self._proposal_keys:
                return {"applied": 0, "skipped": len(adjustments),
                        "error": "no threshold-proposal verification keys configured"}
            sig_raw = data.get("signature")
            if not isinstance(sig_raw, dict):
                return {"applied": 0, "skipped": len(adjustments),
                        "error": "unsigned threshold proposals refused"}

            from remora.crypto.domain_signing import (
                Signature,
                SignatureDomain,
                verify,
            )

            payload = canonical_threshold_proposal_payload(
                adjustments=list(adjustments),
                holdout_evidence_sha256=str(data.get("holdout_evidence_sha256", "")),
                issued_at=str(data.get("issued_at", "")),
                window_id=str(data.get("window_id", "")),
            )
            result = verify(
                SignatureDomain.THRESHOLD_PROPOSAL,
                payload,
                Signature.from_dict(sig_raw),
                self._proposal_keys,
            )
            if not result.ok:
                return {"applied": 0, "skipped": len(adjustments),
                        "error": f"proposal signature invalid: {result.reason}"}

            # SR-07 review follow-up: a valid signature is single-use and
            # time-bound. Without this, restoring a consumed file after the
            # rolling window rolled re-applied the same signed relaxation
            # until the threshold reached its floor.
            sig_id = hashlib.sha256(
                str(sig_raw.get("value", "")).encode("utf-8")
            ).hexdigest()
            if sig_id in self._seen_proposal_sigs:
                return {"applied": 0, "skipped": len(adjustments),
                        "error": "threshold proposal replayed"}
            try:
                issued = datetime.fromisoformat(
                    str(data.get("issued_at", "")).replace("Z", "+00:00")
                )
            except ValueError:
                return {"applied": 0, "skipped": len(adjustments),
                        "error": "threshold proposal issued_at invalid"}
            if issued.tzinfo is None:
                return {"applied": 0, "skipped": len(adjustments),
                        "error": "threshold proposal issued_at lacks a timezone"}
            age = time.time() - issued.timestamp()
            if age < -_PROPOSAL_CLOCK_SKEW_SECONDS or age > _RELAX_WINDOW_SECONDS:
                return {"applied": 0, "skipped": len(adjustments),
                        "error": "threshold proposal outside its validity window"}

            approved = [a for a in adjustments if a.get("approved") is True]
            if not approved:
                return {"applied": 0, "skipped": len(adjustments)}

            # Aggregate total delta across approved scopes, capped per cycle
            # AND per rolling window (SEC-07): write access to the proposals
            # pipeline alone cannot ratchet the ACCEPT band open over time.
            requested = min(0.05, sum(a.get("max_delta", 0.0) for a in approved))
            now = time.time()
            self._relax_log = [
                (t, d) for t, d in self._relax_log
                if now - t < _RELAX_WINDOW_SECONDS
            ]
            spent = sum(d for _, d in self._relax_log)
            budget = max(0.0, _MAX_RELAX_PER_WINDOW - spent)
            total_delta = min(requested, budget)
            if total_delta <= 0:
                return {"applied": 0, "skipped": len(adjustments),
                        "error": "rolling-window relaxation budget exhausted",
                        "total_delta": 0.0}

            current = self._threshold.get_threshold("trust_critical_min")
            # Relax (lower) the threshold — wider ACCEPT band, same safety floor
            new_val = max(
                _MANAGED_THRESHOLDS["trust_critical_min"][1],  # min bound
                current - total_delta,
            )

            # Consume the proposals FIRST (atomic replace, overwrites a stale
            # .consumed file on Windows) so a failed consume can never leave a
            # relaxed threshold with a still-pending proposals file.
            applied_delta = current - new_val
            event = {
                "event": "threshold_changed",
                "threshold": "trust_critical_min",
                "before": round(current, 6),
                "after": round(new_val, 6),
                "proposal_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "signature_kid": result.kid,
                "window_id": data.get("window_id"),
                "holdout_evidence_sha256": data.get("holdout_evidence_sha256"),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            # SR-07 review follow-up: the audit record is written before the
            # change. A failing sink leaves the threshold untouched and the
            # proposals file in place, so no relaxation is ever unaudited.
            if self._audit_sink is not None:
                self._audit_sink(event)

            consumed_path = proposals_path.with_suffix(".consumed.json")
            os.replace(proposals_path, consumed_path)
            self._threshold._thresholds["trust_critical_min"].current_value = new_val
            self._relax_log.append((now, applied_delta))
            self._seen_proposal_sigs = (
                self._seen_proposal_sigs + [sig_id]
            )[-_MAX_SEEN_PROPOSAL_SIGS:]
            self._threshold_events = (self._threshold_events + [event])[-50:]
            self._save_state()

            return {
                "applied": len(approved),
                "skipped": len(adjustments) - len(approved),
                "trust_critical_min_before": round(current, 4),
                "trust_critical_min_after": round(new_val, 4),
                "total_delta": round(applied_delta, 4),
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
            "thresholds": {
                name: self._threshold._thresholds[name].current_value
                for name in _MANAGED_THRESHOLDS
            },
            # SEC-07: the relaxation budget must survive restarts, or a
            # process restart would reset the rolling window.
            "relax_log": [[t, d] for t, d in self._relax_log],
            "seen_proposal_sigs": list(self._seen_proposal_sigs),
            "threshold_events": self._threshold_events,
        }
        tmp = self._state_path.with_name(self._state_path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._state_path)

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
            # Restore managed thresholds (clamped to their bounds)
            for name, (_base, lo, hi) in _MANAGED_THRESHOLDS.items():
                saved = payload.get("thresholds", {}).get(name)
                if isinstance(saved, (int, float)):
                    self._threshold._thresholds[name].current_value = min(
                        hi, max(lo, float(saved))
                    )
            self._relax_log = [
                (float(t), float(d))
                for t, d in payload.get("relax_log", [])
                if isinstance(t, (int, float)) and isinstance(d, (int, float))
            ]
            self._seen_proposal_sigs = [
                s for s in payload.get("seen_proposal_sigs", [])
                if isinstance(s, str)
            ][-_MAX_SEEN_PROPOSAL_SIGS:]
            events = payload.get("threshold_events", [])
            self._threshold_events = [e for e in events if isinstance(e, dict)][-50:]
        except Exception:
            pass  # a corrupt checkpoint falls back to the fresh prior
