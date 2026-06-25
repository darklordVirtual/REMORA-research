# Author: Stian Skogbrott
# License: Apache-2.0
"""Domain-specific coverage-curve optimiser for REMORA trust routing.

Problem
-------
The current selective evaluation uses a *global* trust threshold (18 % in-sample
optimum on N=544).  This has two weaknesses:

1. **In-sample bias**: the threshold is selected and evaluated on the same items.
2. **Domain mismatch**: a threshold that is precision-optimal for TruthfulQA
   "Misconceptions" items may be far too loose for Norwegian debt-law items.

Solution
--------
:class:`DomainCoverageOptimizer` learns a per-domain accept threshold via
leave-one-out cross-validation on a small labelled set.  At inference time it
returns the domain-specific threshold instead of the global one.

Mathematical basis
------------------
For a domain d, define the precision-coverage tradeoff:

    precision(t, d) = P(correct | trust ≥ t, domain = d)
    coverage(t, d)  = P(trust ≥ t | domain = d)

We want:
    t*(d) = argmax_t  precision(t, d)
            subject to coverage(t, d) ≥ min_coverage

The LOO estimator ensures t* is not selected on the held-out item:

    t_loo(i, d) = argmax_t  precision_LOO(t, d; excluding item i)
    threshold(d) = mean(t_loo(i, d) for all i in domain d)

For domains with < min_fit_samples items, fall back to the global threshold.

Typical usage
-------------
    opt = DomainCoverageOptimizer(min_coverage=0.15)
    opt.fit(trust_scores, labels, domains)

    t_law   = opt.threshold("specialised")   # e.g., 0.78
    t_fact  = opt.threshold("general")       # e.g., 0.55
    t_sci   = opt.threshold("science")       # e.g., 0.63
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _precision_at_threshold(
    scores: list[float],
    labels: list[bool],
    threshold: float,
) -> tuple[float, float]:
    """Return (precision, coverage) for a given threshold."""
    accepted = [(s, y) for s, y in zip(scores, labels) if s >= threshold]
    if not accepted:
        return 0.0, 0.0
    n_correct = sum(1 for _, y in accepted if y)
    precision = n_correct / len(accepted)
    coverage = len(accepted) / len(scores) if scores else 0.0
    return precision, coverage


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

@dataclass
class DomainCoverageOptimizer:
    """Per-domain precision-optimal coverage threshold via LOO cross-validation.

    Parameters
    ----------
    min_coverage:
        Minimum required coverage fraction for a threshold to be considered.
        Prevents the optimizer from selecting an extremely high threshold that
        only accepts 1–2 items.
    min_fit_samples:
        Minimum items in a domain to fit a domain-specific threshold.
        Domains below this count fall back to the global threshold.
    t_grid_steps:
        Number of candidate thresholds to evaluate (uniform grid over [0, 1]).
    fallback_threshold:
        Global threshold used when domain-specific fitting is not possible.
    """

    min_coverage: float = 0.10
    min_fit_samples: int = 10
    t_grid_steps: int = 100
    fallback_threshold: float = 0.65

    _thresholds: dict[str, float] = field(default_factory=dict)
    _domain_stats: dict[str, dict] = field(default_factory=dict)
    _global_threshold: float = 0.65
    _fitted: bool = False

    def fit(
        self,
        trust_scores: list[float],
        labels: list[bool],
        domains: list[str],
    ) -> "DomainCoverageOptimizer":
        """Fit per-domain thresholds.

        Parameters
        ----------
        trust_scores:
            Raw trust scores in [0, 1], one per benchmark item.
        labels:
            Ground-truth correctness (True = accepted verdict was correct).
        domains:
            Domain label for each item (e.g., "science", "specialised", "general").
        """
        if not (len(trust_scores) == len(labels) == len(domains)):
            raise ValueError("trust_scores, labels, and domains must have the same length")

        # Group by domain
        by_domain: dict[str, list[tuple[float, bool]]] = {}
        for s, y, d in zip(trust_scores, labels, domains):
            by_domain.setdefault(d, []).append((s, y))

        # Compute global threshold used for small-sample domains.
        # The user-specified fallback_threshold is preserved for unknown domains
        # not seen during fitting.
        all_scores = list(trust_scores)
        all_labels = list(labels)
        global_t = self._find_threshold(all_scores, all_labels)
        self._global_threshold = global_t

        # Per-domain LOO thresholds
        self._thresholds = {}
        self._domain_stats = {}

        for domain, items in by_domain.items():
            scores_d = [s for s, _ in items]
            labels_d = [y for _, y in items]

            if len(items) < self.min_fit_samples:
                self._thresholds[domain] = global_t
                self._domain_stats[domain] = {
                    "n": len(items),
                    "threshold": round(global_t, 4),
                    "method": "global_fallback",
                }
                continue

            # Leave-one-out threshold estimation
            loo_thresholds: list[float] = []
            for i in range(len(items)):
                scores_loo = scores_d[:i] + scores_d[i + 1:]
                labels_loo = labels_d[:i] + labels_d[i + 1:]
                t_loo = self._find_threshold(scores_loo, labels_loo)
                loo_thresholds.append(t_loo)

            domain_t = sum(loo_thresholds) / len(loo_thresholds)

            # Sanity check: verify precision at the LOO threshold on full domain data
            prec, cov = _precision_at_threshold(scores_d, labels_d, domain_t)

            self._thresholds[domain] = domain_t
            self._domain_stats[domain] = {
                "n": len(items),
                "threshold": round(domain_t, 4),
                "precision_at_threshold": round(prec, 4),
                "coverage_at_threshold": round(cov, 4),
                "method": "loo_cv",
            }

        self._fitted = True
        return self

    def _find_threshold(
        self,
        scores: list[float],
        labels: list[bool],
    ) -> float:
        """Grid-search the threshold maximising precision subject to min_coverage."""
        if not scores:
            return self.fallback_threshold

        best_t = self.fallback_threshold
        best_prec = 0.0

        # Evaluate at percentile grid points + boundary of data
        candidates = sorted(set(scores))
        # Add uniform grid for smoother search
        for i in range(self.t_grid_steps + 1):
            candidates.append(i / self.t_grid_steps)
        candidates = sorted(set(max(0.0, min(1.0, c)) for c in candidates))

        for t in candidates:
            prec, cov = _precision_at_threshold(scores, labels, t)
            if cov >= self.min_coverage and prec > best_prec:
                best_prec = prec
                best_t = t

        return best_t

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def threshold(self, domain: str) -> float:
        """Return the optimal accept threshold for *domain*.

        Falls back to the global threshold for unknown domains.
        """
        return self._thresholds.get(domain, self.fallback_threshold)

    def precision_report(self) -> dict[str, dict]:
        """Return per-domain fitting statistics."""
        return dict(self._domain_stats)

    def is_fitted(self) -> bool:
        return self._fitted

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "min_coverage": self.min_coverage,
            "fallback_threshold": self.fallback_threshold,
            "thresholds": dict(self._thresholds),
            "domain_stats": dict(self._domain_stats),
            "fitted": self._fitted,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DomainCoverageOptimizer":
        opt = cls(
            min_coverage=float(d.get("min_coverage", 0.10)),
            fallback_threshold=float(d.get("fallback_threshold", 0.65)),
        )
        opt._thresholds = dict(d.get("thresholds", {}))
        opt._domain_stats = dict(d.get("domain_stats", {}))
        opt._fitted = bool(d.get("fitted", False))
        return opt
