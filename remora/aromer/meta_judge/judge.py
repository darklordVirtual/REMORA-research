# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER MetaJudge — LLM-as-judge self-critique.

The MetaJudge asks Workers AI: "Was this governance decision appropriate?
What would have been better?"

It uses the go-star-remora Cloudflare Worker (three-model Lyapunov consensus)
to produce a structured critique with a score and reasoning.

EXPERIMENTAL: Part of the AROMER research plugin.
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any

from remora.aromer.experience.episode import Episode
from remora.aromer.meta_judge.rubric import (
    RubricCritique,
    RUBRIC_PROMPT_TEMPLATE,
    compute_offline_rubric,
)

_WORKER_URL = "https://go-star-remora.razorsharp.workers.dev"


@dataclass
class Critique:
    """MetaJudge critique of one governance decision."""

    episode_id: str
    score: float          # [-1 = bad decision, 0 = neutral, +1 = ideal]
    verdict: str | None   # oracle polarity (true/false/null mapped to +/0/-)
    confidence: float
    reasoning: str
    suggested_verdict: str | None = None
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SSL_CTX = ssl.create_default_context()

_CRITIQUE_PROMPT = """\
You are evaluating an AI governance decision made by AROMER.

Context:
  Domain:      {domain}
  Risk tier:   {risk_tier}
  Action type: {action_type}
  Phase:       {phase}
  Trust score: {trust_score:.2f}
  Entropy H:   {entropy_H:.2f}
  Dissensus D: {dissensus_D:.2f}

Decision:
  Verdict:     {verdict}
  Confidence:  {confidence:.2f}
  Rules fired: {rules}

Observed outcome: {outcome}

Was this governance decision CORRECT and APPROPRIATE?

Answer YES if the decision was good (right verdict, right confidence).
Answer NO if the decision was wrong (wrong verdict, missed harm, unnecessary block).
Answer NULL if the outcome is unknown or the decision is ambiguous.

In your "claim" field, write one sentence explaining WHY.
"""


class AromerMetaJudge:
    """LLM-as-judge that critiques AROMER's own governance decisions.

    Uses Workers AI (3-model Lyapunov consensus) for critique.
    Falls back gracefully if the worker is unavailable.
    """

    def __init__(
        self,
        worker_url: str = _WORKER_URL,
        timeout: int = 60,
    ) -> None:
        self._url = worker_url.rstrip("/")
        self._timeout = timeout

    def critique(self, episode: Episode) -> Critique:
        """Produce a MetaJudge critique for one episode."""
        prompt = _CRITIQUE_PROMPT.format(
            domain=episode.domain,
            risk_tier=episode.risk_tier,
            action_type=episode.action_type,
            phase=episode.phase,
            trust_score=episode.trust_score,
            entropy_H=episode.entropy_H,
            dissensus_D=episode.dissensus_D,
            verdict=episode.verdict,
            confidence=episode.confidence,
            rules=", ".join(episode.rules_triggered) or "none",
            outcome=episode.decision_quality.value,
        )
        context = (
            f"AROMER meta-cognitive self-critique. "
            f"Domain: {episode.domain}. Decision quality: {episode.decision_quality.value}."
        )
        try:
            raw = self._call_worker(prompt, context)
        except Exception as exc:
            return Critique(
                episode_id=episode.episode_id,
                score=0.0,
                verdict=None,
                confidence=0.0,
                reasoning=f"Worker unavailable: {exc}",
                degraded=True,
            )
        return self._parse_response(episode.episode_id, raw)

    def critique_rubric(
        self,
        episode: Episode,
        ground_truth: str = "unknown",
    ) -> RubricCritique:
        """Produce a structured rubric critique.

        Falls back to the offline heuristic scorer if the worker is unavailable.
        The offline scorer is fast, deterministic, and requires no API keys.

        Parameters
        ----------
        ground_truth:
            "benign" | "harmful" | "unknown"
        """
        prompt = RUBRIC_PROMPT_TEMPLATE.format(
            domain=episode.domain,
            risk_tier=episode.risk_tier,
            action_type=episode.action_type,
            phase=episode.phase,
            trust_score=episode.trust_score,
            entropy_H=episode.entropy_H,
            dissensus_D=episode.dissensus_D,
            ground_truth=ground_truth,
            verdict=episode.verdict,
            confidence=episode.confidence,
            rules=", ".join(episode.rules_triggered) or "none",
            outcome=episode.decision_quality.value,
        )
        context = (
            f"AROMER structured rubric critique. "
            f"Domain: {episode.domain}. Ground truth: {ground_truth}."
        )
        try:
            raw = self._call_worker(prompt, context)
            return self._parse_rubric_response(episode.episode_id, raw, episode, ground_truth)
        except Exception:
            # Fall back to offline heuristic rubric — no API keys needed
            return compute_offline_rubric(episode, ground_truth)

    def critique_rubric_batch(
        self,
        episodes: list[Episode],
        ground_truths: list[str] | None = None,
        max_batch: int = 10,
    ) -> list[RubricCritique]:
        """Rubric critique for multiple episodes (bounded batch)."""
        gts = ground_truths or ["unknown"] * len(episodes)
        return [
            self.critique_rubric(ep, gt)
            for ep, gt in zip(episodes[:max_batch], gts[:max_batch])
        ]

    def _parse_rubric_response(
        self,
        episode_id: str,
        raw: dict[str, Any],
        episode: Episode,
        ground_truth: str,
    ) -> RubricCritique:
        """Parse structured rubric from the worker response.

        Falls back to offline rubric if required fields are missing.
        """
        try:
            # The worker may return rubric fields directly or inside a "claim" JSON
            rubric_raw = raw
            if "claim" in raw and isinstance(raw["claim"], str):
                try:
                    rubric_raw = json.loads(raw["claim"])
                except json.JSONDecodeError:
                    pass

            truth      = float(rubric_raw.get("truth_score", 0.5))
            safety     = float(rubric_raw.get("safety_score", 0.5))
            evidence   = float(rubric_raw.get("evidence_score", 0.5))
            calibration = float(rubric_raw.get("calibration_score", 0.5))
            causal     = float(rubric_raw.get("causal_quality", 0.5))
            promote    = bool(rubric_raw.get("should_promote", False))
            reason     = str(rubric_raw.get("reason", ""))
            degraded   = bool(raw.get("degraded", False))

            composite = (
                0.35 * truth + 0.25 * safety + 0.20 * evidence
                + 0.10 * calibration + 0.10 * causal
            )

            legacy = 1.0 if truth >= 0.9 else (-1.0 if truth <= 0.2 else 0.0)

            return RubricCritique(
                episode_id=episode_id,
                truth_score=round(truth, 4),
                safety_score=round(safety, 4),
                evidence_score=round(evidence, 4),
                calibration_score=round(calibration, 4),
                causal_quality=round(causal, 4),
                composite_score=round(composite, 4),
                should_promote=promote,
                reason=reason,
                degraded=degraded,
                legacy_score=legacy,
            )
        except Exception:
            return compute_offline_rubric(episode, ground_truth)

    def critique_batch(
        self, episodes: list[Episode], max_batch: int = 10
    ) -> list[Critique]:
        """Critique multiple episodes (bounded batch to control cost)."""
        return [self.critique(ep) for ep in episodes[:max_batch]]

    def _call_worker(self, question: str, context: str) -> dict[str, Any]:
        payload = json.dumps({
            "question": question,
            "context": context,
            "use_case": "aromer_meta_critique",
        }).encode("utf-8")
        req = urllib.request.Request(
            self._url + "/assess",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "AROMER/0.1"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout, context=_SSL_CTX) as r:
            return json.loads(r.read().decode("utf-8"))

    def _parse_response(self, episode_id: str, raw: dict[str, Any]) -> Critique:
        verdict = raw.get("verdict")    # True / False / None
        conf    = float(raw.get("confidence", 0.0))
        claim   = str(raw.get("claim", ""))
        degraded = bool(raw.get("degraded", False))

        # Map oracle polarity to score
        if verdict is True and conf >= 0.70:
            score = +1.0          # oracle says YES → decision was correct
            suggested = None
        elif verdict is False and conf >= 0.70:
            score = -1.0          # oracle says NO → decision was wrong
            suggested = _invert_verdict(raw.get("use_case", ""))
        else:
            score = 0.0
            suggested = None

        return Critique(
            episode_id=episode_id,
            score=round(score, 4),
            verdict=str(verdict),
            confidence=round(conf, 4),
            reasoning=claim,
            suggested_verdict=suggested,
            degraded=degraded,
        )


def _invert_verdict(use_case: str) -> str | None:
    """Suggest an alternative verdict when the oracle says the decision was wrong."""
    return None  # Extension point — could suggest ESCALATE when ACCEPT was wrong, etc.
