"""Distribution shift detector for conformal guardrail runtime protection.

The Problem
-----------
REMORA's conformal coverage guarantee holds under the *exchangeability*
assumption: calibration and production queries must come from the same
distribution.  If an engineer deploys the agent to a new domain (e.g.,
calibrated on legal queries, now used for medical questions), the guarantee
breaks silently — the model keeps ACCEPTing but the true error rate rises.

This Module
-----------
``PromptDriftDetector`` monitors incoming queries at runtime and raises a
flag when the query distribution has shifted significantly from calibration.
When detected, ``RemoraDecisionEngine.decide()`` routes to VERIFY instead of
CONFORMAL_ACCEPT (wired via ``PolicyObservation.distribution_shift_detected``).

Algorithm
---------
Two fast, dependency-free signals:

1. **Zlib compression density** (Kolmogorov proxy)
   density = len(zlib.compress(prompt)) / len(prompt.encode())
   Highly repetitive/formulaic text compresses well (low density).
   A domain shift often changes the information density of queries.

2. **Log-length** (structural complexity proxy)
   Normalized prompt length log1p(len) / 10.  Extreme lengths (very short
   one-word queries or multi-page documents) indicate out-of-distribution use.

Detection rule (Two-sigma test):
   A query is flagged if *either* signal falls outside the calibration mean
   ± k_sigma standard deviations, where k_sigma defaults to 2.5.
   This gives an approximate 1.2% false-positive rate per signal under
   normality (Chebyshev bound: ≤ 1/k² = 16% for non-normal distributions).

Accumulator mode (recommended):
   To avoid single-query noise, ``detect_population()`` tests a batch of
   recent queries.  The engine should maintain a rolling window of the last
   N queries and call this periodically.

Usage
-----
::

    detector = PromptDriftDetector()
    detector.fit(calibration_prompts)         # offline

    # At runtime, per query:
    obs = PolicyObservation(
        question=prompt,
        distribution_shift_detected=detector.detect(prompt),
        ...
    )
"""
from __future__ import annotations

import math
import warnings
import zlib
from dataclasses import dataclass, field
from typing import Sequence

try:
    from scipy import stats as _scipy_stats
    _SCIPY_AVAILABLE = True
except ImportError:
    _scipy_stats = None  # type: ignore[assignment]
    _SCIPY_AVAILABLE = False


def _ks_2samp_stdlib(a: "Sequence[float]", b: "Sequence[float]") -> tuple[float, float]:
    """Two-sample KS test statistic and asymptotic p-value — stdlib only.

    Uses the asymptotic approximation p ≈ 2·exp(−2·D²·nₑ) where
    nₑ = n₁·n₂ / (n₁+n₂) is the effective sample size.  Accurate for
    n₁, n₂ ≥ 10.
    """
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    # Evaluate ECDFs at every unique observation in both samples
    all_vals = sorted(set(list(a) + list(b)))
    a_s = sorted(a)
    b_s = sorted(b)
    d = 0.0
    for x in all_vals:
        fa = sum(1 for v in a_s if v <= x) / n1
        fb = sum(1 for v in b_s if v <= x) / n2
        d = max(d, abs(fa - fb))
    ne = (n1 * n2) / (n1 + n2)
    t = d * math.sqrt(ne)
    p_val = 2.0 * math.exp(-2.0 * t * t)
    return d, max(0.0, min(1.0, p_val))


@dataclass
class DriftReport:
    """Diagnostic output from a drift detection check."""
    drift_detected: bool
    density: float
    log_length: float
    density_z: float           # (density - cal_mean) / cal_std
    log_length_z: float
    density_flagged: bool
    log_length_flagged: bool
    cal_n: int
    k_sigma: float


@dataclass
class PromptDriftDetector:
    """Detects distribution shift in incoming prompts relative to calibration.

    Parameters
    ----------
    k_sigma:
        Number of standard deviations outside which a query is flagged (2.5).
    min_cal_samples:
        Minimum calibration prompts required before drift detection is active.
        Below this count, ``detect()`` always returns False (fail-open).
    """

    k_sigma: float = 2.5
    min_cal_samples: int = 20

    _cal_density_mean: float = field(default=0.5, init=False, repr=False)
    _cal_density_std: float = field(default=0.25, init=False, repr=False)
    _cal_length_mean: float = field(default=0.5, init=False, repr=False)
    _cal_length_std: float = field(default=0.25, init=False, repr=False)
    _cal_n: int = field(default=0, init=False, repr=False)

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _density(prompt: str) -> float:
        """Zlib compression ratio as information-density proxy."""
        encoded = prompt.encode("utf-8")
        if not encoded:
            return 0.5
        compressed = zlib.compress(encoded, level=6)
        return len(compressed) / len(encoded)

    @staticmethod
    def _log_length(prompt: str) -> float:
        """Normalised log length: log1p(len) / 10, capped at 1.0."""
        return min(math.log1p(len(prompt)) / 10.0, 1.0)

    def _features(self, prompt: str) -> tuple[float, float]:
        return self._density(prompt), self._log_length(prompt)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def fit(self, prompts: Sequence[str]) -> None:
        """Record calibration distribution from a sequence of reference prompts.

        Call this once offline on the same distribution used to calibrate
        ``ConformalPhaseGuardrail``.  The mean and std of Zlib density and
        log-length are stored; no data is retained after fitting.
        """
        if not prompts:
            raise ValueError("Cannot fit on empty prompt sequence")

        densities = [self._density(p) for p in prompts]
        lengths = [self._log_length(p) for p in prompts]
        n = len(densities)

        def _mean(xs: list[float]) -> float:
            return sum(xs) / n

        def _std(xs: list[float], mean: float) -> float:
            if n < 2:
                return 0.25  # uninformative prior
            var = sum((x - mean) ** 2 for x in xs) / (n - 1)
            return max(math.sqrt(var), 1e-6)

        dm = _mean(densities)
        lm = _mean(lengths)
        self._cal_density_mean = dm
        self._cal_density_std = _std(densities, dm)
        self._cal_length_mean = lm
        self._cal_length_std = _std(lengths, lm)
        self._cal_n = n

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(self, prompt: str) -> bool:
        """Return True if the prompt appears out-of-distribution.

        Fail-open: returns False if not enough calibration data exists yet.
        """
        if self._cal_n < self.min_cal_samples:
            return False

        report = self.report(prompt)
        return report.drift_detected

    def report(self, prompt: str) -> DriftReport:
        """Full diagnostic report for a single prompt."""
        density, log_len = self._features(prompt)

        if self._cal_density_std > 0:
            density_z = (density - self._cal_density_mean) / self._cal_density_std
        else:
            density_z = 0.0

        if self._cal_length_std > 0:
            length_z = (log_len - self._cal_length_mean) / self._cal_length_std
        else:
            length_z = 0.0

        density_flagged = abs(density_z) > self.k_sigma
        length_flagged = abs(length_z) > self.k_sigma
        detected = (density_flagged or length_flagged) and self._cal_n >= self.min_cal_samples

        return DriftReport(
            drift_detected=detected,
            density=density,
            log_length=log_len,
            density_z=density_z,
            log_length_z=length_z,
            density_flagged=density_flagged,
            log_length_flagged=length_flagged,
            cal_n=self._cal_n,
            k_sigma=self.k_sigma,
        )

    def detect_population(self, prompts: Sequence[str]) -> bool:
        """Return True if a significant fraction of a batch is flagged.

        Uses a majority vote: batch drift is declared if > 50% of queries
        are individually flagged.  More robust to single-query noise than
        per-query detection.
        """
        if not prompts:
            return False
        flagged = sum(1 for p in prompts if self.detect(p))
        return flagged > len(prompts) / 2


# ---------------------------------------------------------------------------
# KS-test trust score drift detector
# ---------------------------------------------------------------------------

class DistributionDriftWarning(UserWarning):
    """Issued when runtime trust scores drift from the calibration distribution.

    When raised, the conformal coverage guarantee may no longer hold — the
    calibration set and the production traffic come from different distributions,
    violating the exchangeability assumption.
    """


class TrustScoreDriftDetector:
    """Detects distribution drift in runtime trust scores using the KS test.

    Maintains a rolling window of the last ``window_size`` runtime trust scores
    and compares against the calibration array using
    ``scipy.stats.ks_2samp``.  If the two-sample KS test p-value falls below
    ``alpha``, a :class:`DistributionDriftWarning` is issued and ``update()``
    returns ``True``.

    Parameters
    ----------
    cal_trust_scores:
        Trust scores collected during offline calibration.
    window_size:
        Rolling window length for runtime scores (default 50).
    alpha:
        Significance threshold for the KS test (default 0.05).

    Notes
    -----
    Fails open when fewer than ``window_size`` runtime scores have been
    collected: ``update()`` returns ``False`` and ``test_drift()`` returns
    ``(False, 1.0)`` until the window is full.  This prevents spurious
    warnings during warm-up.
    """

    def __init__(
        self,
        cal_trust_scores: Sequence[float],
        window_size: int = 50,
        alpha: float = 0.05,
    ) -> None:
        if not cal_trust_scores:
            raise ValueError("cal_trust_scores cannot be empty")
        self._cal: list[float] = list(cal_trust_scores)
        self._window_size = window_size
        self._alpha = alpha
        self._buffer: list[float] = []

    def update(self, trust_score: float) -> bool:
        """Record a new runtime trust score and check for drift.

        Returns
        -------
        bool
            ``True`` if drift was detected (and a :class:`DistributionDriftWarning`
            was issued); ``False`` otherwise or when the window is not yet full.
        """
        self._buffer.append(trust_score)
        if len(self._buffer) > self._window_size:
            self._buffer.pop(0)

        if len(self._buffer) < self._window_size:
            return False

        detected, _ = self.test_drift()
        if detected:
            warnings.warn(
                f"Trust score distribution drift detected (KS p < {self._alpha}). "
                "Conformal coverage guarantees may not hold — "
                "consider recalibrating before continuing.",
                DistributionDriftWarning,
                stacklevel=2,
            )
        return detected

    def test_drift(self) -> tuple[bool, float]:
        """Run the KS test against the calibration distribution.

        Returns
        -------
        (drift_detected, p_value) : tuple[bool, float]
            ``drift_detected`` is ``True`` when ``p_value < alpha``.
            Returns ``(False, 1.0)`` when fewer than ``window_size`` runtime
            scores have been collected or when scipy is not installed.
        """
        if len(self._buffer) < self._window_size:
            return False, 1.0
        if _SCIPY_AVAILABLE:
            result = _scipy_stats.ks_2samp(self._cal, self._buffer)
            p_value = float(result.pvalue)
        else:
            _, p_value = _ks_2samp_stdlib(self._cal, self._buffer)
        detected = p_value < self._alpha
        return detected, p_value
