# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Oracle correlation tracking and diversity-weighted consensus for REMORA."""
from __future__ import annotations
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional
from remora.canonical import CanonicalVerdict


@dataclass
class CorrelationMatrix:
    """Rolling pairwise agreement matrix over oracle verdict streams."""

    window_size: int = 200
    _samples: dict[tuple[str, str], deque] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _pair_key(self, a, b):
        """Return a canonical ordered pair key for providers a and b."""
        return (a, b) if a <= b else (b, a)

    def observe(self, verdicts):
        """Record one round of verdicts into the rolling agreement windows.

        Thread-safe: concurrent oracle callbacks may call this simultaneously
        during parallel fan-out via ThreadPoolExecutor.
        """
        with self._lock:
            for i in range(len(verdicts)):
                for j in range(i + 1, len(verdicts)):
                    a_name, a_v = verdicts[i]
                    b_name, b_v = verdicts[j]
                    key = self._pair_key(a_name, b_name)
                    if key not in self._samples:
                        self._samples[key] = deque(maxlen=self.window_size)
                    self._samples[key].append(1 if a_v.equivalent_to(b_v) else 0)

    #: One-sided normal quantile for the Wilson interval used by :meth:`rho`.
    #: 1.6449 is the 95% one-sided critical value. One-sided rather than
    #: two-sided because only one end of the interval is ever read: ρ is a
    #: risk signal, and only its upper end can under-state risk.
    WILSON_Z: float = 1.6449

    def rho(self, a, b):
        """Return the Wilson **upper** bound on agreement ρ between a and b.

        Not the raw rate. ``sum(samples) / len(samples)`` reads 3/3 as 1.0 and
        0/3 as 0.0, and neither is a measurement of the true rate — at n=3 the
        95% interval around 0/3 still reaches past 0.6. Small windows are the
        normal case here, not the exception: a pair is observed only when both
        providers answer the same round.

        **Direction.** Issue #370 proposed a lower bound. That is the wrong end
        for this quantity, and the choice here follows the issue's own
        fail-closed rule rather than its title. ρ measures *agreement*, so a
        high ρ means the oracles are correlated and the swarm is less
        independent than its member count suggests. Every consumer reads it
        that way: :meth:`diversity_weights` divides by ``1 + Σρ``,
        ``engine.Remora._mean_rho`` feeds the swarm-independence signal, and
        ``high_correlation_pairs`` flags pairs above a threshold. Understating
        ρ therefore overstates diversity, which is precisely the flattering
        direction. The upper bound cannot flatter; the lower bound is what
        would.
        **What this does not change.** #370 objects to 3/3 reading as 1.0 as
        well as to 0/3 reading as 0.0. A one-sided bound can only fix one end,
        and this fixes the one that matters: 0/3 rises from 0.0 to ~0.47,
        while 3/3 stays at 1.0 because the upper bound of three-for-three
        agreement genuinely is 1.0. Pulling it down would need the lower
        bound, which is the flattering direction — three identical answers
        would be reported as weaker evidence of correlation than they are. The
        3/3 case is therefore answered by the direction choice rather than
        left open: at that end, uncorrected is already the conservative
        reading.

        Reads a snapshot under the same lock ``observe()`` writes under, so a
        shared matrix cannot yield an inconsistent view mid-mutation
        (external review REM-036).
        """
        if a == b:
            return 1.0
        key = self._pair_key(a, b)
        with self._lock:
            samples = list(self._samples.get(key) or ())
        return self._wilson_upper(sum(samples), len(samples))

    def rho_observed(self, a, b):
        """Return the raw observed agreement rate, unsmoothed.

        For reporting and diagnostics only. Never feed this to a gate: it is
        the estimator :meth:`rho` deliberately replaced. Kept separate so an
        operator reading a dashboard can still see what was actually counted
        alongside the bound the engine acted on.
        """
        if a == b:
            return 1.0
        key = self._pair_key(a, b)
        with self._lock:
            samples = list(self._samples.get(key) or ())
        return sum(samples) / len(samples) if samples else 0.0

    @classmethod
    def _wilson_upper(cls, successes: int, n: int) -> float:
        """Wilson score interval, upper end, at :attr:`WILSON_Z`.

        ``n == 0`` returns 0.0 rather than the mathematically correct 1.0.
        This is a deliberate carve-out, not an oversight. An unobserved pair
        has no evidence in either direction, and 1.0 would declare every
        provider maximally redundant with every other before the swarm has
        answered a single round — which collapses ``diversity_weights`` to a
        uniform distribution by a different route while telling
        ``high_correlation_pairs`` that everything is correlated. The
        consumers already treat the no-data case as neutral (the pair-count
        floor in ``high_correlation_pairs``, uniform weights when no pair has
        samples), so 0.0 preserves that neutrality. The smoothing exists to
        fix small-n overconfidence, and n=0 is absence of data rather than a
        small sample of it.
        """
        if n <= 0:
            return 0.0
        z = cls.WILSON_Z
        p = successes / n
        z2 = z * z
        denom = 1.0 + z2 / n
        centre = p + z2 / (2 * n)
        margin = z * math.sqrt(p * (1.0 - p) / n + z2 / (4 * n * n))
        return min(1.0, (centre + margin) / denom)

    def rho_matrix(self, providers):
        """Return the full ρ matrix as a nested dict."""
        return {a: {b: self.rho(a, b) for b in providers} for a in providers}

    def diversity_weights(self, providers):
        """Return inverse-correlation diversity weights normalised to sum 1."""
        n = len(providers)
        if n == 0:
            return {}
        if n == 1:
            return {providers[0]: 1.0}
        raw = {
            k: (1.0 / n) / (1.0 + sum(self.rho(k, j) for j in providers if j != k))
            for k in providers
        }
        total = sum(raw.values())
        return {k: v / total for k, v in raw.items()} if total else {k: 1.0 / n for k in providers}

    def n_samples(self):
        """Return the maximum number of samples across all pairs."""
        return max(len(d) for d in self._samples.values()) if self._samples else 0

    def to_dict(self):
        """Serialise the matrix to a plain dict."""
        return {
            "window_size": self.window_size,
            "samples": {f"{k[0]}|{k[1]}": list(v) for k, v in self._samples.items()},
        }

    @classmethod
    def from_dict(cls, d):
        """Deserialise a CorrelationMatrix from a plain dict."""
        cm = cls(window_size=d.get("window_size", 200))
        for key_str, vals in d.get("samples", {}).items():
            a, b = key_str.split("|", 1)
            cm._samples[(a, b)] = deque(vals, maxlen=cm.window_size)
        return cm


@dataclass
class WeightedConsensus:
    """Result of a diversity-weighted consensus vote."""

    winning_fingerprint: str
    winning_verdict: Optional[CanonicalVerdict]
    weighted_support: float
    unweighted_support: float
    correlation_correction: float
    weights: dict[str, float]
    is_tie: bool = False
    tied_fingerprints: list = field(default_factory=list)


def weighted_consensus(provider_verdicts, correlation):
    """Compute a WeightedConsensus from a list of (provider, verdict) pairs.

    When two or more verdicts share the maximum weighted support within a
    tolerance of 1e-9, ``is_tie=True`` is set and ``tied_fingerprints``
    lists all tied candidates.  Callers should route tied results to VERIFY
    rather than accepting an arbitrarily broken tie.
    """
    if not provider_verdicts:
        return WeightedConsensus("", None, 0.0, 0.0, 0.0, {})
    providers = [p for p, _ in provider_verdicts]
    weights = correlation.diversity_weights(providers)
    weighted = defaultdict(float)
    unweighted = defaultdict(float)
    verdict_by_fp = {}
    for provider, verdict in provider_verdicts:
        fp = verdict.fingerprint()
        weighted[fp] += weights.get(provider, 1.0 / len(providers))
        unweighted[fp] += 1.0 / len(provider_verdicts)
        verdict_by_fp[fp] = verdict
    winning_fp = max(weighted, key=lambda k: weighted[k])
    max_weight = weighted[winning_fp]
    tied_fps = [fp for fp, w in weighted.items() if abs(w - max_weight) < 1e-9]
    is_tie = len(tied_fps) > 1
    if is_tie:
        import logging
        logging.getLogger(__name__).warning(
            "remora.correlation: weighted consensus tie detected among %s — "
            "caller should route to VERIFY",
            tied_fps,
        )
    return WeightedConsensus(
        winning_fp,
        verdict_by_fp[winning_fp],
        weighted[winning_fp],
        unweighted[winning_fp],
        abs(weighted[winning_fp] - unweighted[winning_fp]),
        weights,
        is_tie=is_tie,
        tied_fingerprints=tied_fps,
    )
