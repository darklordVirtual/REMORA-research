"""Tests for remora.aromer.intelligence module.

Tests cover IntelligenceScore, AiiComponents, and IntelligenceClient.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from remora.aromer.intelligence.score import (
    AiiComponents,
    IntelligenceScore,
    friction_score,
)
from remora.aromer.intelligence.client import IntelligenceClient


class TestFrictionScore:
    """The friction component must retain a usable gradient at every review rate."""

    def test_strictly_decreasing(self) -> None:
        rates = [0.0, 0.055, 0.15, 0.255, 0.31, 0.53, 0.9]
        scores = [friction_score(r) for r in rates]
        assert all(a > b for a, b in zip(scores, scores[1:])), scores

    def test_no_dead_zone_above_old_baseline(self) -> None:
        # The old metric was exactly 0 here; the new one must still carry signal.
        assert friction_score(0.31) > 0.05
        assert friction_score(0.53) > 0.0

    def test_centred_on_15pct_target(self) -> None:
        assert 0.40 < friction_score(0.15) < 0.55

    def test_clamped_unit_interval(self) -> None:
        assert friction_score(0.0) == 1.0
        assert 0.0 <= friction_score(5.0) <= 1.0


class TestAiiComponentsDefaults:
    """Test AiiComponents dataclass defaults."""

    def test_aii_components_defaults(self) -> None:
        """AiiComponents() has sensible defaults."""
        comp = AiiComponents()
        assert comp.calibration_score == 0.0
        assert comp.friction_score == 0.0
        assert comp.metajudge_quality == 0.0
        assert comp.transfer_score == 0.5
        assert comp.stability_score == 0.0
        assert comp.ece == 0.5
        assert comp.benign_review_rate == 0.27
        assert comp.false_accept_rate == 0.0
        assert comp.world_model_active is False
        assert comp.lora_active is False
        assert comp.n_episodes == 0
        assert comp.n_high_confidence == 0


class TestIntelligenceScoreSummary:
    """Test IntelligenceScore.summary() formatting."""

    def test_intelligence_score_summary_format(self) -> None:
        """summary() includes "AII:", "T1", "T2", "T3", "T4", "T5", "trend="."""
        comp = AiiComponents(
            calibration_score=0.8,
            friction_score=0.75,
            metajudge_quality=0.7,
            transfer_score=0.65,
            stability_score=0.6,
            ece=0.1,
            benign_review_rate=0.05,
            false_accept_rate=0.02,
            world_model_active=False,
            lora_active=False,
            n_episodes=100,
            n_high_confidence=80,
        )
        score = IntelligenceScore(
            aii=0.72,
            components=comp,
            trend="stable",
            interpretation="CAPABLE",
        )
        summary = score.summary()
        assert "AII:" in summary
        assert "T1" in summary
        assert "T2" in summary
        assert "T3" in summary
        assert "T4" in summary
        assert "T5" in summary
        assert "trend=" in summary
        assert "CAPABLE" in summary
        assert "stable" in summary

    def test_summary_shows_world_model_active(self) -> None:
        """When world_model_active=True, summary() contains "active"."""
        comp = AiiComponents(world_model_active=True)
        score = IntelligenceScore(aii=0.5, components=comp)
        summary = score.summary()
        assert "active" in summary

    def test_summary_shows_world_model_shadow(self) -> None:
        """When world_model_active=False, summary() contains "shadow"."""
        comp = AiiComponents(world_model_active=False)
        score = IntelligenceScore(aii=0.5, components=comp)
        summary = score.summary()
        assert "shadow" in summary

    def test_summary_shows_lora_on(self) -> None:
        """When lora_active=True, summary() contains "on"."""
        comp = AiiComponents(lora_active=True)
        score = IntelligenceScore(aii=0.5, components=comp)
        summary = score.summary()
        assert "on" in summary

    def test_summary_shows_lora_off(self) -> None:
        """When lora_active=False, summary() contains "off"."""
        comp = AiiComponents(lora_active=False)
        score = IntelligenceScore(aii=0.5, components=comp)
        summary = score.summary()
        assert "off" in summary


class TestFromApiParsing:
    """Test IntelligenceScore.from_api() parsing."""

    def test_from_api_full_response(self) -> None:
        """from_api() with complete mock response parses all fields correctly."""
        data = {
            "current": {
                "aii": 0.75,
                "calibration_score": 0.8,
                "friction_score": 0.7,
                "metajudge_quality": 0.65,
                "transfer_score": 0.6,
                "stability_score": 0.55,
                "ece": 0.12,
                "benign_review_rate": 0.1,
                "false_accept_rate": 0.05,
                "world_model_active": 1,
                "lora_active": 1,
                "n_episodes": 500,
                "n_high_confidence": 450,
                "timestamp": "2026-06-05T12:00:00Z",
            },
            "trend": "improving",
            "interpretation": "CAPABLE",
        }
        score = IntelligenceScore.from_api(data)
        assert score.aii == 0.75
        assert score.components.calibration_score == 0.8
        assert score.components.friction_score == 0.7
        assert score.components.metajudge_quality == 0.65
        assert score.components.transfer_score == 0.6
        assert score.components.stability_score == 0.55
        assert score.components.ece == 0.12
        assert score.components.benign_review_rate == 0.1
        assert score.components.false_accept_rate == 0.05
        assert score.components.world_model_active is True
        assert score.components.lora_active is True
        assert score.components.n_episodes == 500
        assert score.components.n_high_confidence == 450
        assert score.timestamp == "2026-06-05T12:00:00Z"
        assert score.trend == "improving"
        assert score.interpretation == "CAPABLE"

    def test_from_api_empty_current(self) -> None:
        """from_api() with None current returns AII=0.0, trend="insufficient_data"."""
        data = {
            "current": None,
            "trend": "insufficient_data",
            "interpretation": "WARMUP",
            "history": [],
        }
        score = IntelligenceScore.from_api(data)
        assert score.aii == 0.0
        assert score.trend == "insufficient_data"
        assert score.interpretation == "WARMUP"
        assert score.components.calibration_score == 0.0
        assert score.components.transfer_score == 0.5  # default

    def test_from_api_missing_fields(self) -> None:
        """from_api() with partial response uses defaults."""
        data = {
            "current": {
                "aii": 0.5,
                "calibration_score": 0.4,
            },
            "trend": "stable",
            "interpretation": "LEARNING",
        }
        score = IntelligenceScore.from_api(data)
        assert score.aii == 0.5
        assert score.components.calibration_score == 0.4
        assert score.components.transfer_score == 0.5  # default
        assert score.components.friction_score == 0.0  # default
        assert score.trend == "stable"
        assert score.interpretation == "LEARNING"

    def test_from_api_false_accept_rate(self) -> None:
        """false_accept_rate=0.05 is parsed correctly."""
        data = {
            "current": {
                "aii": 0.6,
                "false_accept_rate": 0.05,
            },
            "trend": "stable",
            "interpretation": "LEARNING",
        }
        score = IntelligenceScore.from_api(data)
        assert score.components.false_accept_rate == 0.05


class TestInterpretationThresholds:
    """Test interpretation mapping by AII value."""

    def test_interpretation_trained(self) -> None:
        """from_api with aii=0.85 → interpretation="TRAINED"."""
        data = {
            "current": {"aii": 0.85},
            "interpretation": "TRAINED",
        }
        score = IntelligenceScore.from_api(data)
        assert score.aii == 0.85
        assert score.interpretation == "TRAINED"

    def test_interpretation_capable(self) -> None:
        """from_api with aii=0.65 → interpretation="CAPABLE"."""
        data = {
            "current": {"aii": 0.65},
            "interpretation": "CAPABLE",
        }
        score = IntelligenceScore.from_api(data)
        assert score.aii == 0.65
        assert score.interpretation == "CAPABLE"

    def test_interpretation_learning(self) -> None:
        """from_api with aii=0.50 → interpretation="LEARNING"."""
        data = {
            "current": {"aii": 0.50},
            "interpretation": "LEARNING",
        }
        score = IntelligenceScore.from_api(data)
        assert score.aii == 0.50
        assert score.interpretation == "LEARNING"

    def test_interpretation_warmup(self) -> None:
        """from_api with aii=0.35 → interpretation="WARMUP"."""
        data = {
            "current": {"aii": 0.35},
            "interpretation": "WARMUP",
        }
        score = IntelligenceScore.from_api(data)
        assert score.aii == 0.35
        assert score.interpretation == "WARMUP"


class TestWeightsAndThresholds:
    """Test WEIGHTS and THRESHOLDS constants."""

    def test_weights_sum_to_one(self) -> None:
        """WEIGHTS values sum to 1.0."""
        total = sum(IntelligenceScore.WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_weights_structure(self) -> None:
        """WEIGHTS has expected keys."""
        assert "calibration" in IntelligenceScore.WEIGHTS
        assert "friction" in IntelligenceScore.WEIGHTS
        assert "metajudge" in IntelligenceScore.WEIGHTS
        assert "transfer" in IntelligenceScore.WEIGHTS
        assert "stability" in IntelligenceScore.WEIGHTS

    def test_thresholds_structure(self) -> None:
        """THRESHOLDS has expected keys and ordered values."""
        assert IntelligenceScore.THRESHOLDS["WARMUP"] == 0.0
        assert IntelligenceScore.THRESHOLDS["LEARNING"] == 0.40
        assert IntelligenceScore.THRESHOLDS["CAPABLE"] == 0.60
        assert IntelligenceScore.THRESHOLDS["TRAINED"] == 0.80


class TestIntelligenceClient:
    """Test IntelligenceClient HTTP and network behavior."""

    def test_intelligence_client_init_default_url(self) -> None:
        """IntelligenceClient() with no args uses AROMER_BASE_URL."""
        client = IntelligenceClient()
        assert client._base is not None
        assert "aromer" in client._base.lower() or "localhost" in client._base.lower()

    def test_intelligence_client_init_custom_url(self) -> None:
        """IntelligenceClient(base_url) uses provided URL."""
        client = IntelligenceClient(base_url="http://localhost:9999")
        assert client._base == "http://localhost:9999"

    def test_intelligence_client_strips_trailing_slash(self) -> None:
        """IntelligenceClient strips trailing slash from base_url."""
        client = IntelligenceClient(base_url="http://localhost:9999/")
        assert client._base == "http://localhost:9999"

    def test_intelligence_client_current_success(self) -> None:
        """IntelligenceClient.current() with successful response."""
        mock_response = {
            "current": {
                "aii": 0.72,
                "calibration_score": 0.8,
                "friction_score": 0.7,
                "metajudge_quality": 0.6,
                "transfer_score": 0.65,
                "stability_score": 0.5,
                "ece": 0.15,
                "benign_review_rate": 0.08,
                "false_accept_rate": 0.02,
                "world_model_active": 1,
                "lora_active": 0,
                "n_episodes": 1000,
                "n_high_confidence": 800,
                "timestamp": "2026-06-05T12:30:00Z",
            },
            "trend": "stable",
            "interpretation": "CAPABLE",
            "history": [],
        }

        client = IntelligenceClient(base_url="http://localhost:9999")
        with patch("urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_response).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = resp

            score = client.current(history_hours=1)

        assert score.aii == 0.72
        assert score.interpretation == "CAPABLE"
        assert score.trend == "stable"
        assert score.components.calibration_score == 0.8

    def test_intelligence_client_network_error(self) -> None:
        """IntelligenceClient.current() raises RuntimeError on network error."""
        import urllib.error

        client = IntelligenceClient(base_url="http://127.0.0.1:1")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            try:
                client.current()
                assert False, "Expected RuntimeError on network error"
            except RuntimeError as e:
                assert "unreachable" in str(e).lower()

    def test_intelligence_client_history(self) -> None:
        """IntelligenceClient.history() returns list of historical records."""
        mock_response = {
            "current": {
                "aii": 0.72,
                "calibration_score": 0.8,
                "friction_score": 0.7,
                "metajudge_quality": 0.6,
                "transfer_score": 0.65,
                "stability_score": 0.5,
                "ece": 0.15,
                "benign_review_rate": 0.08,
                "false_accept_rate": 0.02,
                "world_model_active": 0,
                "lora_active": 0,
                "n_episodes": 1000,
                "n_high_confidence": 800,
                "timestamp": "2026-06-05T12:30:00Z",
            },
            "trend": "stable",
            "interpretation": "CAPABLE",
            "history": [
                {"aii": 0.70, "timestamp": "2026-06-05T12:00:00Z"},
                {"aii": 0.68, "timestamp": "2026-06-05T11:00:00Z"},
                {"aii": 0.65, "timestamp": "2026-06-05T10:00:00Z"},
            ],
        }

        client = IntelligenceClient(base_url="http://localhost:9999")
        with patch("urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_response).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = resp

            history = client.history(hours=24)

        assert len(history) == 3
        assert history[0]["aii"] == 0.70
        assert history[1]["aii"] == 0.68
        assert history[2]["aii"] == 0.65

    def test_intelligence_client_history_empty(self) -> None:
        """IntelligenceClient.history() returns empty list when no history."""
        mock_response = {
            "current": {"aii": 0.5},
            "trend": "insufficient_data",
            "interpretation": "WARMUP",
            "history": [],
        }

        client = IntelligenceClient(base_url="http://localhost:9999")
        with patch("urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_response).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = resp

            history = client.history(hours=24)

        assert history == []


class TestComponentsBooleanCoercion:
    """Test that boolean values are coerced from API integers."""

    def test_world_model_active_coerced_from_int(self) -> None:
        """world_model_active coerced from 1 to True."""
        data = {
            "current": {
                "aii": 0.5,
                "world_model_active": 1,
            },
            "interpretation": "LEARNING",
        }
        score = IntelligenceScore.from_api(data)
        assert score.components.world_model_active is True

    def test_lora_active_coerced_from_int(self) -> None:
        """lora_active coerced from 1 to True."""
        data = {
            "current": {
                "aii": 0.5,
                "lora_active": 1,
            },
            "interpretation": "LEARNING",
        }
        score = IntelligenceScore.from_api(data)
        assert score.components.lora_active is True

    def test_world_model_active_coerced_from_zero(self) -> None:
        """world_model_active coerced from 0 to False."""
        data = {
            "current": {
                "aii": 0.5,
                "world_model_active": 0,
            },
            "interpretation": "LEARNING",
        }
        score = IntelligenceScore.from_api(data)
        assert score.components.world_model_active is False
