# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.calibration.domain_optimizer — per-domain coverage threshold."""
from __future__ import annotations

import pytest

from remora.calibration.domain_optimizer import DomainCoverageOptimizer, _precision_at_threshold


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

class TestPrecisionAtThreshold:
    def test_all_accepted_all_correct(self):
        prec, cov = _precision_at_threshold([0.8, 0.9], [True, True], 0.7)
        assert prec == 1.0
        assert cov == 1.0

    def test_all_rejected(self):
        prec, cov = _precision_at_threshold([0.3, 0.4], [True, False], 0.9)
        assert prec == 0.0
        assert cov == 0.0

    def test_partial_acceptance(self):
        prec, cov = _precision_at_threshold([0.9, 0.8, 0.3], [True, False, True], 0.75)
        # Accepts first two (0.9 and 0.8), 1 of 2 correct
        assert abs(prec - 0.5) < 1e-9
        assert abs(cov - 2 / 3) < 1e-9

    def test_threshold_boundary_is_inclusive(self):
        prec, cov = _precision_at_threshold([0.5], [True], 0.5)
        assert cov == 1.0


# ---------------------------------------------------------------------------
# DomainCoverageOptimizer
# ---------------------------------------------------------------------------

class TestDomainCoverageOptimizer:
    def _make_data(self, n: int = 30, seed: int = 0):
        """Generate synthetic (scores, labels, domains) with domain-specific optima."""
        import random
        rng = random.Random(seed)
        scores, labels, domains = [], [], []
        domain_opts = {"science": 0.7, "general": 0.5, "specialised": 0.8}
        for d, t_opt in domain_opts.items():
            for _ in range(n):
                s = rng.random()
                # P(correct | s) is higher for s > t_opt
                y = rng.random() < (0.9 if s >= t_opt else 0.3)
                scores.append(s)
                labels.append(y)
                domains.append(d)
        return scores, labels, domains

    def test_fit_returns_self(self):
        opt = DomainCoverageOptimizer()
        scores, labels, domains = self._make_data()
        assert opt.fit(scores, labels, domains) is opt

    def test_is_fitted_after_fit(self):
        opt = DomainCoverageOptimizer()
        scores, labels, domains = self._make_data()
        opt.fit(scores, labels, domains)
        assert opt.is_fitted()

    def test_length_mismatch_raises(self):
        opt = DomainCoverageOptimizer()
        with pytest.raises(ValueError):
            opt.fit([0.5, 0.6], [True], ["science", "science"])

    def test_threshold_in_unit_interval(self):
        opt = DomainCoverageOptimizer()
        scores, labels, domains = self._make_data()
        opt.fit(scores, labels, domains)
        for domain in ["science", "general", "specialised"]:
            t = opt.threshold(domain)
            assert 0.0 <= t <= 1.0, f"threshold({domain}) = {t} out of [0,1]"

    def test_unknown_domain_returns_fallback(self):
        opt = DomainCoverageOptimizer(fallback_threshold=0.60)
        opt.fit([0.5, 0.6], [True, False], ["science", "science"])
        assert opt.threshold("unknown_domain") == 0.60

    def test_small_domain_uses_fallback(self):
        """Domains with < min_fit_samples items use global fallback."""
        opt = DomainCoverageOptimizer(min_fit_samples=20)
        scores = [0.7, 0.8, 0.9]
        labels = [True, True, False]
        domains = ["tiny_domain"] * 3
        opt.fit(scores, labels, domains)
        report = opt.precision_report()
        assert report["tiny_domain"]["method"] == "global_fallback"

    def test_loo_domain_uses_loo_method(self):
        opt = DomainCoverageOptimizer(min_fit_samples=5)
        scores, labels, domains = self._make_data(n=10)
        opt.fit(scores, labels, domains)
        report = opt.precision_report()
        for domain_stat in report.values():
            if domain_stat["n"] >= 5:
                assert domain_stat["method"] == "loo_cv"

    def test_precision_report_contains_domains(self):
        opt = DomainCoverageOptimizer()
        scores, labels, domains = self._make_data()
        opt.fit(scores, labels, domains)
        report = opt.precision_report()
        for domain in ["science", "general", "specialised"]:
            assert domain in report

    def test_different_domains_have_different_thresholds(self):
        """Domains with different difficulty levels should get different thresholds."""
        import random
        rng = random.Random(42)
        scores, labels, domains = [], [], []
        # Science: high threshold optimal (only confident items are correct)
        for _ in range(30):
            s = rng.random()
            scores.append(s)
            labels.append(s > 0.8)  # Only very high trust is correct
            domains.append("science")
        # General: low threshold optimal (most items are correct)
        for _ in range(30):
            s = rng.random()
            scores.append(s)
            labels.append(True)  # Always correct — low threshold optimal
            domains.append("general")

        opt = DomainCoverageOptimizer(min_fit_samples=10, min_coverage=0.05)
        opt.fit(scores, labels, domains)
        t_sci = opt.threshold("science")
        t_gen = opt.threshold("general")
        # Science threshold should be higher than general
        assert t_sci > t_gen, f"Expected t_sci={t_sci:.3f} > t_gen={t_gen:.3f}"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_round_trip(self):
        opt = DomainCoverageOptimizer(min_coverage=0.15)
        scores, labels, domains = TestDomainCoverageOptimizer()._make_data()
        opt.fit(scores, labels, domains)
        d_dict = opt.to_dict()
        opt2 = DomainCoverageOptimizer.from_dict(d_dict)
        assert opt2.is_fitted()
        assert abs(opt2.fallback_threshold - opt.fallback_threshold) < 1e-9
        for domain in ["science", "general", "specialised"]:
            assert abs(opt2.threshold(domain) - opt.threshold(domain)) < 1e-9

    def test_from_dict_defaults(self):
        opt = DomainCoverageOptimizer.from_dict({})
        assert not opt.is_fitted()
        assert opt.fallback_threshold == 0.65
