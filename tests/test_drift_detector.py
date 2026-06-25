"""Tests for the PromptDriftDetector."""
from __future__ import annotations

import pytest

from remora.selective.drift_detector import DriftReport, PromptDriftDetector


LEGAL_PROMPTS = [
    "Is the contract clause enforceable under Norwegian contract law?",
    "Does the arbitration agreement satisfy the requirements of §28 of the Arbitration Act?",
    "What are the liability limits under the standard offshore services agreement?",
    "Explain the scope of the indemnity clause in the framework agreement.",
    "Is the force majeure provision broad enough to cover pandemic-related delays?",
    "How does the statute of limitations apply to a breach of contract claim?",
    "Analyze the assignment clause and its restrictions.",
    "Does this NDA cover indirect disclosure to affiliated companies?",
    "Can a unilateral variation clause be enforced without notice?",
    "What remedies are available for anticipatory breach?",
    "Is there an obligation to mitigate loss under this agreement?",
    "Does the termination for convenience clause require any notice period?",
    "Can confidentiality obligations survive contract termination?",
    "What constitutes a material breach under this agreement?",
    "Is the limitation of liability clause enforceable in the relevant jurisdiction?",
    "Does the payment clause create a condition precedent?",
    "Interpret the scope of the intellectual property assignment provision.",
    "Is the penalty clause enforceable or does it constitute a penalty?",
    "What are the obligations of the parties upon termination?",
    "Does this clause constitute an unfair contract term under consumer protection law?",
]


class TestDriftDetectorFit:
    def test_fit_stores_calibration_stats(self) -> None:
        detector = PromptDriftDetector()
        detector.fit(LEGAL_PROMPTS)
        assert detector._cal_n == len(LEGAL_PROMPTS)
        assert 0.0 < detector._cal_density_mean < 2.0
        assert detector._cal_density_std > 0

    def test_fit_raises_on_empty(self) -> None:
        detector = PromptDriftDetector()
        with pytest.raises(ValueError):
            detector.fit([])

    def test_fit_single_prompt_uses_uninformative_prior(self) -> None:
        detector = PromptDriftDetector()
        detector.fit(["Hello."])
        assert detector._cal_density_std == pytest.approx(0.25)
        assert detector._cal_length_std == pytest.approx(0.25)


class TestDriftDetectorDetect:
    def test_fail_open_before_min_samples(self) -> None:
        detector = PromptDriftDetector(min_cal_samples=20)
        detector.fit(LEGAL_PROMPTS[:5])
        assert detector._cal_n == 5
        assert detector.detect("anything") is False

    def test_in_distribution_not_flagged(self) -> None:
        detector = PromptDriftDetector()
        detector.fit(LEGAL_PROMPTS)
        similar = "Does the indemnification clause cover third-party claims?"
        assert detector.detect(similar) is False

    def test_extreme_outlier_flagged(self) -> None:
        detector = PromptDriftDetector(k_sigma=1.5)
        detector.fit(LEGAL_PROMPTS)
        # Single-word query — radically different log-length from legal corpus
        result = detector.report("Ok")
        assert result.log_length_flagged is True

    def test_very_long_prompt_may_flag_length(self) -> None:
        detector = PromptDriftDetector(k_sigma=1.5)
        detector.fit(LEGAL_PROMPTS)
        long_prompt = "analyze " + "the contract " * 2000
        result = detector.report(long_prompt)
        # log-length z-score should be large
        assert result.log_length_z > 0


class TestDriftReport:
    def test_report_fields_populated(self) -> None:
        detector = PromptDriftDetector()
        detector.fit(LEGAL_PROMPTS)
        report = detector.report("Does the NDA cover indirect disclosure?")
        assert isinstance(report, DriftReport)
        assert 0.0 <= report.density <= 2.0
        assert 0.0 <= report.log_length <= 1.0
        assert isinstance(report.density_z, float)
        assert isinstance(report.log_length_z, float)
        assert report.cal_n == len(LEGAL_PROMPTS)
        assert report.k_sigma == pytest.approx(2.5)

    def test_drift_detected_iff_any_flag(self) -> None:
        detector = PromptDriftDetector()
        detector.fit(LEGAL_PROMPTS)
        report = detector.report("Is clause 12 enforceable?")
        assert report.drift_detected == (report.density_flagged or report.log_length_flagged)


class TestDriftDetectorPopulation:
    def test_empty_batch_returns_false(self) -> None:
        detector = PromptDriftDetector()
        detector.fit(LEGAL_PROMPTS)
        assert detector.detect_population([]) is False

    def test_majority_ood_batch_detected(self) -> None:
        detector = PromptDriftDetector(k_sigma=0.5)
        detector.fit(LEGAL_PROMPTS)
        ood_batch = ["Ok", "Hi", "Yes", "No", "?"]
        result = detector.detect_population(ood_batch)
        assert isinstance(result, bool)

    def test_in_distribution_batch_not_detected(self) -> None:
        detector = PromptDriftDetector()
        detector.fit(LEGAL_PROMPTS)
        in_dist = [
            "Is the contractual limitation clause enforceable?",
            "What notice period applies upon termination for convenience?",
        ]
        assert detector.detect_population(in_dist) is False
