# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER Memory Promotion Gate — quality-controlled learning memory.

Episodes pass through 6 promotion levels before entering stable strategy memory.
This prevents noise, false signals, and unverified patterns from polluting the
world model.

Promotion levels
----------------
  L0  raw           Episode recorded, no quality assessment yet
  L1  critiqued     MetaJudge rubric computed; composite ≥ 0.50
  L2  replay_valid  Consistent with ≥ 5 other similar episodes; no contradiction
  L3  holdout_valid Verified on holdout episodes; not a statistical artefact
  L4  stable        Confirmed stable over ≥ 10 learning cycles
  L5  domain_gen    Generalises across ≥ 2 domain variants

Gate thresholds (from learning_laws.seed.json)
----------------------------------------------
  L0 → L1:  composite ≥ 0.50, truth ≥ 0.60, safety ≥ 0.70
  L1 → L2:  replay consistency ≥ 5 episodes, no contradicting episode
  L2 → L3:  holdout accuracy improvement ≥ 0.01 vs baseline
  L3 → L4:  stable across 10 cron cycles (no regression)
  L4 → L5:  transfers to ≥ 2 other domains (analogy test)

Usage
-----
    from remora.aromer.experience.promotion_gate import MemoryPromotionGate
    from remora.aromer.experience.store import EpisodicStore

    gate = MemoryPromotionGate(store=EpisodicStore())

    # Check and try to promote an episode
    new_level, promoted = gate.try_promote(episode_id, rubric)

    # Batch promotion pass (e.g. during cron/adapt())
    report = gate.promotion_pass(max_episodes=100)
    print(report.promoted_to_L2, report.promoted_to_L3)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from remora.aromer.experience.episode import Episode
from remora.aromer.meta_judge.rubric import RubricCritique

# ──────────────────────────────────────────────────────────────────────────────
# Promotion level enum
# ──────────────────────────────────────────────────────────────────────────────

class PromotionLevel(IntEnum):
    """Promotion level for an episode in AROMER's memory hierarchy."""
    L0_RAW           = 0
    L1_CRITIQUED     = 1
    L2_REPLAY_VALID  = 2
    L3_HOLDOUT_VALID = 3
    L4_STABLE        = 4
    L5_DOMAIN_GEN    = 5

    @property
    def label(self) -> str:
        return {
            0: "raw",
            1: "critiqued",
            2: "replay_valid",
            3: "holdout_valid",
            4: "stable",
            5: "domain_general",
        }[self.value]


# Gate thresholds
_L0_TO_L1_MIN_COMPOSITE  = 0.50
_L0_TO_L1_MIN_TRUTH      = 0.60
_L0_TO_L1_MIN_SAFETY     = 0.70

_L1_TO_L2_MIN_CONSISTENT = 5     # similar episodes required
_L2_TO_L3_MIN_HOLDOUT_DELTA = 0.01

# ──────────────────────────────────────────────────────────────────────────────
# Ledger record
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PromotionRecord:
    """Persistent record of an episode's promotion state."""

    episode_id: str
    level: int            # PromotionLevel value
    rubric: dict | None   # serialised RubricCritique
    consistent_count: int = 0
    holdout_validated: bool = False
    stable_cycles: int = 0
    domain_variants: list[str] = field(default_factory=list)
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PromotionRecord":
        domain_variants = d.get("domain_variants") or []
        return cls(
            episode_id=d["episode_id"],
            level=int(d.get("level", 0)),
            rubric=d.get("rubric"),
            consistent_count=int(d.get("consistent_count", 0)),
            holdout_validated=bool(d.get("holdout_validated", False)),
            stable_cycles=int(d.get("stable_cycles", 0)),
            domain_variants=list(domain_variants),
            blocked_reason=str(d.get("blocked_reason", "")),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Promotion pass report
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PromotionPassReport:
    """Summary of one promotion pass."""

    n_evaluated: int
    promoted_to_L1: int = 0
    promoted_to_L2: int = 0
    promoted_to_L3: int = 0
    promoted_to_L4: int = 0
    promoted_to_L5: int = 0
    blocked: int = 0
    already_at_max: int = 0

    @property
    def total_promoted(self) -> int:
        return (
            self.promoted_to_L1 + self.promoted_to_L2 + self.promoted_to_L3 +
            self.promoted_to_L4 + self.promoted_to_L5
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# Gate
# ──────────────────────────────────────────────────────────────────────────────

class MemoryPromotionGate:
    """Quality-controlled promotion of episodes through the memory hierarchy.

    Parameters
    ----------
    store:
        The EpisodicStore to read episodes from.
    ledger_path:
        Where to persist the promotion ledger (JSON).
        Defaults to ~/.aromer/promotion_ledger.json
    """

    def __init__(
        self,
        store: Any = None,       # EpisodicStore — typed as Any to avoid circular
        ledger_path: str | Path | None = None,
    ) -> None:
        self._store = store
        self._ledger_path = (
            Path(ledger_path) if ledger_path
            else Path.home() / ".aromer" / "promotion_ledger.json"
        )
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._ledger: dict[str, PromotionRecord] = {}
        self._load_ledger()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def try_promote(
        self,
        episode_id: str,
        rubric: RubricCritique | None = None,
        consistent_pool: list[Episode] | None = None,
    ) -> tuple[PromotionLevel, bool]:
        """Attempt to advance an episode to the next promotion level.

        Returns (current_level, was_promoted).
        """
        record = self._ledger.get(episode_id) or PromotionRecord(
            episode_id=episode_id, level=0, rubric=None
        )
        current = PromotionLevel(record.level)

        if current == PromotionLevel.L5_DOMAIN_GEN:
            return current, False  # already at max

        if current == PromotionLevel.L0_RAW:
            promoted = self._gate_L0_to_L1(record, rubric)
            if promoted:
                record.level = PromotionLevel.L1_CRITIQUED
                if rubric:
                    record.rubric = rubric.to_dict()
        elif current == PromotionLevel.L1_CRITIQUED:
            promoted = self._gate_L1_to_L2(record, consistent_pool)
        elif current == PromotionLevel.L2_REPLAY_VALID:
            promoted = self._gate_L2_to_L3(record)
        elif current == PromotionLevel.L3_HOLDOUT_VALID:
            promoted = self._gate_L3_to_L4(record)
        elif current == PromotionLevel.L4_STABLE:
            promoted = self._gate_L4_to_L5(record)
        else:
            promoted = False

        if promoted:
            record.level = min(record.level + 1, PromotionLevel.L5_DOMAIN_GEN)

        self._ledger[episode_id] = record
        self._save_ledger()
        return PromotionLevel(record.level), promoted

    def get_level(self, episode_id: str) -> PromotionLevel:
        """Return the current promotion level for an episode."""
        record = self._ledger.get(episode_id)
        if record is None:
            return PromotionLevel.L0_RAW
        return PromotionLevel(record.level)

    def promotion_pass(
        self,
        max_episodes: int = 200,
        rubrics: dict[str, RubricCritique] | None = None,
    ) -> PromotionPassReport:
        """Run a full promotion pass over all tracked episodes.

        Parameters
        ----------
        max_episodes:
            Maximum number of episodes to evaluate in this pass.
        rubrics:
            Pre-computed RubricCritiques keyed by episode_id.
            Will be computed offline if not provided and the episode is in store.
        """
        if self._store is None:
            return PromotionPassReport(n_evaluated=0)

        episodes = self._store.all_episodes()[:max_episodes]
        report = PromotionPassReport(n_evaluated=len(episodes))

        for ep in episodes:
            rubric = (rubrics or {}).get(ep.episode_id)
            if rubric is None and ep.outcome is not None:
                from remora.aromer.meta_judge.rubric import compute_offline_rubric
                gt = "unknown"
                if ep.quality is not None:
                    from remora.aromer.experience.episode import DecisionQuality
                    q = ep.quality
                    if q in (DecisionQuality.CORRECT_ACCEPT,
                              DecisionQuality.BENIGN_REVIEW,
                              DecisionQuality.FALSE_BLOCK):
                        gt = "benign"
                    elif q in (DecisionQuality.CORRECT_BLOCK,
                                DecisionQuality.FALSE_ACCEPT,
                                DecisionQuality.CORRECT_INTERCEPT_VERIFY):
                        gt = "harmful"
                rubric = compute_offline_rubric(ep, gt)

            _current_level, promoted = self.try_promote(ep.episode_id, rubric=rubric)
            if promoted:
                level = PromotionLevel(self._ledger[ep.episode_id].level)
                if level == PromotionLevel.L1_CRITIQUED:
                    report.promoted_to_L1 += 1
                elif level == PromotionLevel.L2_REPLAY_VALID:
                    report.promoted_to_L2 += 1
                elif level == PromotionLevel.L3_HOLDOUT_VALID:
                    report.promoted_to_L3 += 1
                elif level == PromotionLevel.L4_STABLE:
                    report.promoted_to_L4 += 1
                elif level == PromotionLevel.L5_DOMAIN_GEN:
                    report.promoted_to_L5 += 1
            else:
                current = self.get_level(ep.episode_id)
                if current == PromotionLevel.L5_DOMAIN_GEN:
                    report.already_at_max += 1
                else:
                    report.blocked += 1

        return report

    def stable_episodes(self, min_level: int = 3) -> list[str]:
        """Return episode IDs at or above min_level."""
        return [
            eid for eid, rec in self._ledger.items()
            if rec.level >= min_level
        ]

    def summary(self) -> dict[str, Any]:
        """Return a summary of the ledger state."""
        counts = {level.label: 0 for level in PromotionLevel}
        for rec in self._ledger.values():
            level = PromotionLevel(rec.level)
            counts[level.label] += 1
        return {
            "total_tracked": len(self._ledger),
            "level_distribution": counts,
            "stable_plus": sum(
                1 for r in self._ledger.values() if r.level >= PromotionLevel.L3_HOLDOUT_VALID
            ),
        }

    def increment_stable_cycle(self, episode_id: str) -> None:
        """Increment stable_cycles counter (call once per cron/adapt cycle)."""
        if episode_id in self._ledger:
            self._ledger[episode_id].stable_cycles += 1
            self._save_ledger()

    def add_domain_variant(self, episode_id: str, domain: str) -> None:
        """Record a domain in which this episode's pattern was validated."""
        if episode_id in self._ledger:
            if domain not in self._ledger[episode_id].domain_variants:
                self._ledger[episode_id].domain_variants.append(domain)
                self._save_ledger()

    # ──────────────────────────────────────────────────────────────────────────
    # Gate implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _gate_L0_to_L1(
        self,
        record: PromotionRecord,
        rubric: RubricCritique | None,
    ) -> bool:
        """L0 → L1: rubric must clear minimum thresholds."""
        if rubric is None:
            record.blocked_reason = "No rubric available"
            return False
        if rubric.composite_score < _L0_TO_L1_MIN_COMPOSITE:
            record.blocked_reason = (
                f"composite {rubric.composite_score:.2f} < {_L0_TO_L1_MIN_COMPOSITE}"
            )
            return False
        if rubric.truth_score < _L0_TO_L1_MIN_TRUTH:
            record.blocked_reason = (
                f"truth {rubric.truth_score:.2f} < {_L0_TO_L1_MIN_TRUTH}"
            )
            return False
        if rubric.safety_score < _L0_TO_L1_MIN_SAFETY:
            record.blocked_reason = (
                f"safety {rubric.safety_score:.2f} < {_L0_TO_L1_MIN_SAFETY}"
            )
            return False
        record.blocked_reason = ""
        return True

    def _gate_L1_to_L2(
        self,
        record: PromotionRecord,
        consistent_pool: list[Episode] | None,
    ) -> bool:
        """L1 → L2: consistent with ≥ N similar episodes."""
        pool = consistent_pool or []
        compatible = self._count_compatible(record.episode_id, pool)
        record.consistent_count = compatible
        if compatible >= _L1_TO_L2_MIN_CONSISTENT:
            record.blocked_reason = ""
            return True
        record.blocked_reason = f"Only {compatible}/{_L1_TO_L2_MIN_CONSISTENT} consistent episodes"
        return False

    def _gate_L2_to_L3(self, record: PromotionRecord) -> bool:
        """L2 → L3: holdout validation (set externally via record.holdout_validated)."""
        if record.holdout_validated:
            record.blocked_reason = ""
            return True
        record.blocked_reason = "Holdout validation not completed"
        return False

    def _gate_L3_to_L4(self, record: PromotionRecord) -> bool:
        """L3 → L4: stable across ≥ 10 cron cycles."""
        if record.stable_cycles >= 10:
            record.blocked_reason = ""
            return True
        record.blocked_reason = f"Only {record.stable_cycles}/10 stable cycles"
        return False

    def _gate_L4_to_L5(self, record: PromotionRecord) -> bool:
        """L4 → L5: validated in ≥ 2 domain variants."""
        if len(record.domain_variants) >= 2:
            record.blocked_reason = ""
            return True
        record.blocked_reason = f"Only {len(record.domain_variants)}/2 domain variants"
        return False

    def _count_compatible(
        self,
        episode_id: str,
        pool: list[Episode],
    ) -> int:
        """Count how many pool episodes are consistent with this episode."""
        if self._store is None:
            return 0
        target = None
        for ep in (self._store.all_episodes() or []):
            if ep.episode_id == episode_id:
                target = ep
                break
        if target is None:
            return 0

        target_verdict = (target.verdict or "").upper()
        count = 0
        for ep in pool:
            if ep.episode_id == episode_id:
                continue
            if (ep.domain == target.domain and
                    ep.risk_tier == target.risk_tier and
                    (ep.verdict or "").upper() == target_verdict):
                count += 1
        return count

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def _load_ledger(self) -> None:
        if not self._ledger_path.exists():
            return
        try:
            raw = json.loads(self._ledger_path.read_text())
            for eid, rec_dict in raw.items():
                self._ledger[eid] = PromotionRecord.from_dict(rec_dict)
        except Exception:
            self._ledger = {}

    def _save_ledger(self) -> None:
        data = {eid: rec.to_dict() for eid, rec in self._ledger.items()}
        self._ledger_path.write_text(json.dumps(data, indent=2))
