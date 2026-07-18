# Author: Stian Skogbrott
# License: Apache-2.0
"""Cross-domain transfer evaluation for the AROMER world model (§16).

The `transfer_unmeasured` interpretation ceiling exists because AROMER's
T4=1.0 came from *in-domain* replay — the arena never proved that harm
structure learned in one domain predicts harm in a **held-out domain it
never trained on**. That is the difference between memorising per-domain
priors and learning transferable structure.

This harness measures it honestly, by construction:

1. Split the labelled episode set into disjoint SOURCE and TARGET domains.
2. Train the **abstract** prior (``update_abstract``, keyed only on
   ``action_type × risk_tier``) on SOURCE-domain episodes only.
3. Predict harm on TARGET-domain episodes using ONLY the abstract prior —
   the target domains were never seen, so the domain-specific prior is empty
   and ``p_harm_backoff`` falls back to the abstract structure.
4. Report transfer accuracy plus the leave-one-domain-out breakdown, in the
   ``*_cases`` shape the live worker reads for ``cross_domain_transfer``.

A high transfer accuracy is evidence the world model learned *structure*
(action-type/risk-tier harm regularities) that generalises across domains,
not just per-domain lookups. It is deterministic given the input episodes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from remora.aromer.world_model.domain_prior import _HARM_THRESHOLD, DomainHarmPrior


@dataclass(frozen=True)
class TransferEpisode:
    """One labelled episode for transfer evaluation."""

    domain: str
    action_type: str
    risk_tier: str
    harmful: bool          # ground-truth harm label
    weight: float = 1.0    # 1.0 strong signal, 0.25 partial (VERIFY/benign_review)


@dataclass
class FoldResult:
    target_domain: str
    n_target: int
    correct: int
    accuracy: float
    n_source_updates: int


@dataclass
class TransferReport:
    """Cross-domain transfer result — mirrors the worker's expected shape."""

    overall_accuracy: float
    n_target_cases: int
    n_correct: int
    n_source_domains: int
    n_target_domains: int
    threshold: float
    folds: list[FoldResult] = field(default_factory=list)

    def to_worker_report(self) -> dict[str, Any]:
        """Shape the live worker consumes: ``cross_domain_transfer`` with
        per-target ``*_cases`` keys plus a transfer_success scalar."""
        cdt: dict[str, Any] = {
            "transfer_success": round(self.overall_accuracy, 4),
            "threshold": self.threshold,
            "measured": True,
        }
        for f in self.folds:
            cdt[f"{f.target_domain}_cases"] = f.n_target
            cdt[f"{f.target_domain}_accuracy"] = round(f.accuracy, 4)
        return {"cross_domain_transfer": cdt}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "aromer_cross_domain_transfer_v1",
            "overall_accuracy": round(self.overall_accuracy, 4),
            "n_target_cases": self.n_target_cases,
            "n_correct": self.n_correct,
            "n_source_domains": self.n_source_domains,
            "n_target_domains": self.n_target_domains,
            "threshold": self.threshold,
            "protocol": (
                "Leave-one-domain-out: abstract (action_type × risk_tier) prior "
                "trained on all OTHER domains predicts harm on the held-out "
                "domain via p_harm_backoff. No target-domain episode is ever "
                "seen during that fold's training."
            ),
            "folds": [
                {
                    "target_domain": f.target_domain,
                    "n_target_cases": f.n_target,
                    "correct": f.correct,
                    "accuracy": round(f.accuracy, 4),
                    "n_source_updates": f.n_source_updates,
                }
                for f in self.folds
            ],
            **self.to_worker_report(),
        }


def _evaluate_fold(
    target: str,
    episodes: list[TransferEpisode],
    threshold: float,
) -> FoldResult:
    """Train the abstract prior on every domain except ``target``; predict
    ``target``'s episodes from the resulting domain-agnostic structure."""
    prior = DomainHarmPrior(path="/dev/null-not-persisted")
    prior._priors = {}  # fresh in-memory model; never touch disk
    n_source_updates = 0
    for ep in episodes:
        if ep.domain == target:
            continue
        prior.update_abstract(ep.action_type, ep.risk_tier,
                              harm_occurred=ep.harmful, weight=ep.weight)
        n_source_updates += 1

    target_eps = [e for e in episodes if e.domain == target]
    correct = 0
    for ep in target_eps:
        # Domain-specific prior is empty for the held-out target → backoff.
        predicted_harm = prior.p_harm_backoff(
            target, ep.action_type, ep.risk_tier
        ) >= threshold
        if predicted_harm == ep.harmful:
            correct += 1
    n = len(target_eps)
    return FoldResult(
        target_domain=target,
        n_target=n,
        correct=correct,
        accuracy=(correct / n) if n else 0.0,
        n_source_updates=n_source_updates,
    )


def run_cross_domain_transfer(
    episodes: Iterable[TransferEpisode],
    threshold: float = _HARM_THRESHOLD,
) -> TransferReport:
    """Leave-one-domain-out cross-domain transfer over labelled episodes.

    Requires ≥ 2 distinct domains. Each domain is held out once; the abstract
    prior trained on the remaining domains must predict the held-out domain's
    harm labels from action-type/risk-tier structure alone.
    """
    eps = list(episodes)
    by_domain: dict[str, int] = defaultdict(int)
    for e in eps:
        by_domain[e.domain] += 1
    domains = sorted(by_domain)
    if len(domains) < 2:
        raise ValueError(
            f"cross-domain transfer needs >= 2 distinct domains, got {len(domains)}"
        )

    folds = [_evaluate_fold(d, eps, threshold) for d in domains]
    total = sum(f.n_target for f in folds)
    correct = sum(f.correct for f in folds)
    return TransferReport(
        overall_accuracy=(correct / total) if total else 0.0,
        n_target_cases=total,
        n_correct=correct,
        n_source_domains=len(domains),   # each fold trains on all-but-one
        n_target_domains=len(domains),
        threshold=threshold,
        folds=folds,
    )
