# Author: Stian Skogbrott
# License: Apache-2.0
"""Reference formulas the AROMER worker mirrors: EMA smoothing + stability v2."""
from __future__ import annotations

import pytest

from remora.aromer.intelligence.score import (
    EMA_ALPHA,
    STABILITY_SIGMA_REF,
    dispersion_stability,
    ema_smooth,
    stability_score_v2,
)

# Live AII series from the worker (2026-06-05 → 2026-06-09, oldest first):
# a static 200-episode system whose raw AII swung 0.40↔0.65 purely from
# sliding-window composition noise.
LIVE_AII = [0.4066, 0.6244, 0.5866, 0.5866, 0.5311, 0.5311, 0.4433, 0.4256,
            0.4256, 0.4256, 0.4257, 0.4527, 0.4596, 0.4404, 0.4404, 0.4262,
            0.4262, 0.4438, 0.5156, 0.5939, 0.5939, 0.5165, 0.6497, 0.5656]


class TestEmaSmooth:
    def test_empty(self):
        assert ema_smooth([]) == []

    def test_single_value_passthrough(self):
        assert ema_smooth([0.7]) == [0.7]

    def test_constant_series_unchanged(self):
        out = ema_smooth([0.5] * 10)
        assert all(abs(v - 0.5) < 1e-12 for v in out)

    def test_length_preserved(self):
        assert len(ema_smooth(LIVE_AII)) == len(LIVE_AII)

    def test_bounded_by_input_range(self):
        out = ema_smooth(LIVE_AII)
        assert min(LIVE_AII) <= min(out)
        assert max(out) <= max(LIVE_AII)

    def test_reduces_volatility_on_live_series(self):
        import statistics
        raw_std = statistics.pstdev(LIVE_AII)
        smoothed_std = statistics.pstdev(ema_smooth(LIVE_AII))
        assert smoothed_std < raw_std * 0.75

    def test_alpha_one_is_identity(self):
        assert ema_smooth(LIVE_AII, alpha=1.0) == [float(v) for v in LIVE_AII]

    def test_invalid_alpha_rejected(self):
        with pytest.raises(ValueError):
            ema_smooth([0.1, 0.2], alpha=0.0)
        with pytest.raises(ValueError):
            ema_smooth([0.1, 0.2], alpha=1.5)

    def test_default_alpha_documented(self):
        assert EMA_ALPHA == 0.35

    def test_responds_to_sustained_change(self):
        # A real regime change must still come through within a few cycles.
        series = [0.4] * 6 + [0.8] * 6
        out = ema_smooth(series)
        assert out[-1] > 0.7


class TestDispersionStability:
    def test_too_few_samples_is_zero(self):
        assert dispersion_stability([]) == 0.0
        assert dispersion_stability([0.5]) == 0.0

    def test_constant_series_fully_stable(self):
        assert dispersion_stability([0.6] * 6) == 1.0

    def test_noise_at_sigma_ref_is_zero(self):
        # Two-point series with std exactly sigma_ref.
        assert dispersion_stability([0.5 - STABILITY_SIGMA_REF,
                                     0.5 + STABILITY_SIGMA_REF]) == 0.0

    def test_bounded(self):
        for series in ([0.0, 1.0], [0.45, 0.55], LIVE_AII):
            assert 0.0 <= dispersion_stability(series) <= 1.0

    def test_monotone_in_noise(self):
        quiet = dispersion_stability([0.50, 0.51, 0.50, 0.51])
        loud = dispersion_stability([0.30, 0.70, 0.25, 0.75])
        assert quiet > loud


class TestStabilityV2:
    def test_perfectly_stable_full_coverage(self):
        assert stability_score_v2([0.5] * 6, [0.5] * 6, 1.0) == 1.0

    def test_no_history_no_coverage_is_zero(self):
        assert stability_score_v2([], [], 0.0) == 0.0

    def test_live_volatile_friction_caps_score(self):
        # Live friction series (volatile) vs constant metajudge:
        friction = [0.0, 0.0623, 0.0418, 0.1969, 0.4843, 0.7047]
        metajudge = [0.42, 0.42, 0.42, 0.42, 0.42, 0.42]
        score = stability_score_v2(friction, metajudge, 0.22)
        # Dispersion of the friction series is near zero stability; metajudge
        # constant is fully stable → dispersion term ≈ 0.5; coverage 0.22.
        assert 0.2 <= score <= 0.5

    def test_coverage_clamped(self):
        assert stability_score_v2([0.5, 0.5], [0.5, 0.5], 5.0) == 1.0
        assert stability_score_v2([0.5, 0.5], [0.5, 0.5], -1.0) == 0.5

    def test_no_self_reference(self):
        # The formula consumes friction/metajudge series only — feeding it the
        # stability output cannot change subsequent inputs. (Documented
        # property; asserted here as an API contract: signature takes only the
        # two component series and coverage.)
        import inspect
        params = list(inspect.signature(stability_score_v2).parameters)
        assert params == ["recent_friction", "recent_metajudge", "high_conf_coverage"]


class TestLoopHealthAnalysis:
    """Offline tests for the loop-health analyser (no network)."""

    def _payload(self, **overrides):
        history = [
            {"aii": v, "n_episodes": 200, "stability_score": 0.11,
             "false_accept_rate": 0.0, "friction_score": 0.4,
             "metajudge_quality": 0.5}
            for v in reversed(LIVE_AII)  # API returns newest first
        ]
        payload = {
            "aii_smoothed": 0.51,
            "trend": "stable",
            "interpretation": "LEARNING",
            "history": history,
            "meta": {"transfer_source": "static_seed_expectation"},
        }
        payload.update(overrides)
        return payload

    def test_analyse_flags_static_transfer(self):
        from experiments.aromer_loop_health import analyse
        report = analyse(self._payload())
        assert report["checks"]["transfer_provenance"]["status"] == "WARN"

    def test_analyse_passes_real_transfer(self):
        from experiments.aromer_loop_health import analyse
        report = analyse(self._payload(
            meta={"transfer_source": "python_replay_arena"}))
        assert report["checks"]["transfer_provenance"]["status"] == "PASS"

    def test_analyse_flags_volatility_and_static_window(self):
        from experiments.aromer_loop_health import analyse
        report = analyse(self._payload())
        assert report["checks"]["aii_volatility"]["status"] == "WARN"
        assert report["checks"]["episode_growth"]["status"] == "WARN"
        assert report["checks"]["stability_liveness"]["status"] == "WARN"

    def test_analyse_safety_fail_on_false_accept(self):
        from experiments.aromer_loop_health import analyse
        payload = self._payload()
        payload["history"][0]["false_accept_rate"] = 0.05
        report = analyse(payload)
        assert report["checks"]["safety"]["status"] == "FAIL"
        assert report["overall"] == "FAIL"

    def test_analyse_smoothed_matches_reference(self):
        from experiments.aromer_loop_health import analyse
        report = analyse(self._payload())
        expected = round(ema_smooth(LIVE_AII)[-1], 4)
        assert report["aii_smoothed_latest"] == expected
