# Author: Stian Skogbrott
# License: Apache-2.0
"""Oracle correlation tracking and diversity-weighted consensus for REMORA."""
from __future__ import annotations
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

    def rho(self, a, b):
        """Return the rolling agreement rate ρ between providers a and b."""
        if a == b:
            return 1.0
        key = self._pair_key(a, b)
        samples = self._samples.get(key)
        return sum(samples) / len(samples) if samples else 0.0

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
