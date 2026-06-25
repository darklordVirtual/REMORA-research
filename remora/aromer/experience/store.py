# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER EpisodicStore — persistent cross-session experience memory.

Episodes are stored in JSONL format on disk (local mode) and optionally
synced to Cloudflare D1 via the AROMER Worker API (production mode).

Retrieval uses a lightweight cosine-similarity match over the numeric
feature vector of each episode — fast, zero external dependencies.

EXPERIMENTAL: Part of the AROMER research plugin.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remora.aromer.experience.episode import (
    Episode,
    EpisodeSummary,
    GroundTruth,
    OutcomeType,
)

_DEFAULT_STORE_PATH = Path.home() / ".aromer" / "episodes.jsonl"

# TTL-based pending resolution (mirrored by the worker's resolvePendingEpisodes).
# Presumed-benign labels use the weak 0.25 weight class — the same class as
# VERIFY partial signals — never the full 1.0 of observed ground truth.
PRESUMED_BENIGN_WEIGHT = 0.25
_PENDING_BENIGN_TTL_HOURS = 72.0
_PENDING_EXPIRE_DAYS = 7.0


def _parse_ts(raw: str) -> datetime | None:
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


class EpisodicStore:
    """Persistent JSONL-backed experience store.

    Parameters
    ----------
    path:       JSONL file path.  Defaults to ~/.aromer/episodes.jsonl.
    max_loaded: Maximum episodes to keep in memory.  Older episodes are
                only in the JSONL file.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_loaded: int = 10_000,
    ) -> None:
        self.path = Path(path) if path is not None else _DEFAULT_STORE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_loaded = max_loaded
        self._episodes: list[Episode] = []
        self._id_index: dict[str, int] = {}  # episode_id → list index
        self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def record(self, episode: Episode) -> str:
        """Persist a new episode and return its episode_id."""
        self._append_to_file(episode)
        if len(self._episodes) < self.max_loaded:
            self._id_index[episode.episode_id] = len(self._episodes)
            self._episodes.append(episode)
        return episode.episode_id

    def update_outcome(
        self,
        episode_id: str,
        outcome: OutcomeType,
        severity: float = 0.0,
    ) -> bool:
        """Record the observed outcome for a past episode.  Returns True if found."""
        idx = self._id_index.get(episode_id)
        if idx is not None:
            self._episodes[idx].record_outcome(outcome, severity)
            self._rewrite_file()
            return True
        # Episode is in file but not in memory — patch the file
        return self._patch_episode(
            episode_id,
            lambda ep: ep.record_outcome(outcome, severity),
        )

    def update_ground_truth(
        self,
        episode_id: str,
        ground_truth: GroundTruth,
        severity: float = 0.0,
    ) -> bool:
        """Record actual harmful/benign truth and derive decision quality."""
        idx = self._id_index.get(episode_id)
        if idx is not None:
            self._episodes[idx].record_ground_truth(ground_truth, severity)
            self._rewrite_file()
            return True
        return self._patch_episode(
            episode_id,
            lambda ep: ep.record_ground_truth(ground_truth, severity),
        )

    def update_critique(self, episode_id: str, score: float, text: str) -> bool:
        """Attach MetaJudge critique to an episode."""
        idx = self._id_index.get(episode_id)
        if idx is not None:
            self._episodes[idx].record_critique(score, text)
            self._rewrite_file()
            return True
        return self._patch_file(episode_id, {"critique_score": round(score, 4),
                                              "critique_text": text})

    def get(self, episode_id: str) -> Episode | None:
        idx = self._id_index.get(episode_id)
        return self._episodes[idx] if idx is not None else None

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve_similar(
        self,
        episode: Episode,
        top_k: int = 5,
        *,
        domain_filter: str | None = None,
    ) -> list[Episode]:
        """Return top-k most similar past episodes by cosine similarity."""
        query = episode.feature_vector()
        candidates = [
            e for e in self._episodes
            if e.episode_id != episode.episode_id
            and (domain_filter is None or e.domain == domain_filter)
        ]
        if not candidates:
            return []
        scored = sorted(
            candidates,
            key=lambda e: _cosine_sim(query, e.feature_vector()),
            reverse=True,
        )
        return scored[:top_k]

    def recent(self, n: int = 50, *, with_outcome_only: bool = False) -> list[Episode]:
        eps = [e for e in self._episodes
               if not with_outcome_only or e.ground_truth != GroundTruth.UNKNOWN]
        return eps[-n:]

    def pending_outcomes(self, *, include_expired: bool = False) -> list[Episode]:
        return [
            e for e in self._episodes
            if e.ground_truth == GroundTruth.UNKNOWN
            and (include_expired or e.meta.get("label_source") != "ttl_expired")
        ]

    def resolve_stale_pending(
        self,
        *,
        benign_ttl_hours: float = _PENDING_BENIGN_TTL_HOURS,
        expire_after_days: float = _PENDING_EXPIRE_DAYS,
        world_model: Any | None = None,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """TTL-resolve stale pending episodes (mirrors worker resolvePendingEpisodes).

        Stage 1: ACCEPT episodes older than ``benign_ttl_hours`` with no harm
        reported are weak-labelled benign. An executed action with no harm report
        after the TTL is evidence of benignity — the same evidence model as the
        auto-label hook — but the label carries ``label_source='ttl_presumed'``,
        reduced ``label_confidence``, and updates the world model at the weak
        ``PRESUMED_BENIGN_WEIGHT`` (0.25), never the full observed-truth weight.

        Stage 2: non-ACCEPT episodes older than ``expire_after_days`` can never
        produce an observed outcome (the action did not run). They are marked
        expired and excluded from the pending backlog, but ground truth stays
        UNKNOWN — no label is invented for blocked actions.
        """
        now = now or datetime.now(timezone.utc)
        presumed = 0
        expired = 0
        for ep in self._episodes:
            if ep.ground_truth != GroundTruth.UNKNOWN:
                continue
            ts = _parse_ts(ep.timestamp)
            if ts is None:
                continue
            age_hours = (now - ts).total_seconds() / 3600.0
            if ep.verdict.upper() == "ACCEPT":
                if age_hours >= benign_ttl_hours:
                    ep.record_ground_truth(GroundTruth.BENIGN, severity=0.0)
                    ep.label_source = "ttl_presumed"
                    ep.label_confidence = 0.6
                    ep.meta["label_source"] = "ttl_presumed_benign"
                    if world_model is not None:
                        world_model.update(
                            ep.domain, ep.action_type, ep.risk_tier,
                            harm_occurred=False,
                            weight=PRESUMED_BENIGN_WEIGHT,
                        )
                    presumed += 1
            elif (
                age_hours >= expire_after_days * 24.0
                and ep.meta.get("label_source") != "ttl_expired"
            ):
                ep.meta["label_source"] = "ttl_expired"
                expired += 1
        if presumed or expired:
            self._rewrite_file()
        return {"presumed_benign": presumed, "expired": expired}

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def summary(self, domain: str | None = None) -> EpisodeSummary:
        eps = self._episodes
        if domain:
            eps = [e for e in eps if e.domain == domain]
        return EpisodeSummary.from_episodes(eps)

    def domain_stats(self) -> dict[str, EpisodeSummary]:
        domains = {e.domain for e in self._episodes}
        return {d: self.summary(domain=d) for d in domains}

    @property
    def size(self) -> int:
        return len(self._episodes)

    # ------------------------------------------------------------------
    # Persistence internals
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        loaded: list[Episode] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    loaded.append(Episode.from_dict(data))
                except Exception:
                    pass
        # Keep only last max_loaded episodes in memory
        self._episodes = loaded[-self.max_loaded:]
        self._id_index = {e.episode_id: i for i, e in enumerate(self._episodes)}

    def _append_to_file(self, episode: Episode) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(episode.to_dict(), separators=(",", ":")) + "\n")

    def _rewrite_file(self) -> None:
        """Rewrite JSONL with current in-memory state (after updates)."""
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            for ep in self._episodes:
                fh.write(json.dumps(ep.to_dict(), separators=(",", ":")) + "\n")
        tmp.replace(self.path)

    def _patch_file(self, episode_id: str, patch: dict[str, Any]) -> bool:
        """Patch a specific episode in the JSONL file without loading all."""
        if not self.path.exists():
            return False
        lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        found = False
        out = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                out.append(line)
                continue
            try:
                data = json.loads(stripped)
                if data.get("episode_id") == episode_id:
                    data.update(patch)
                    out.append(json.dumps(data, separators=(",", ":")) + "\n")
                    found = True
                    continue
            except Exception:
                pass
            out.append(line)
        if found:
            self.path.write_text("".join(out), encoding="utf-8")
        return found

    def _patch_episode(self, episode_id: str, mutate: Any) -> bool:
        """Patch one JSONL episode by reconstructing derived fields."""
        if not self.path.exists():
            return False
        lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        found = False
        out = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                out.append(line)
                continue
            try:
                data = json.loads(stripped)
                if data.get("episode_id") == episode_id:
                    ep = Episode.from_dict(dict(data))
                    mutate(ep)
                    out.append(json.dumps(ep.to_dict(), separators=(",", ":")) + "\n")
                    found = True
                    continue
            except Exception:
                pass
            out.append(line)
        if found:
            self.path.write_text("".join(out), encoding="utf-8")
        return found


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot    = sum(a[k] * b[k] for k in keys)
    norm_a = math.sqrt(sum(v**2 for v in a.values()))
    norm_b = math.sqrt(sum(v**2 for v in b.values()))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)
