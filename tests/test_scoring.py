# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.scoring — evaluation metrics."""
import pytest
from remora.benchmarks.loaders import BenchmarkItem, GroundTruthType
from remora.scoring import (
    score_one, score_batch, _polarity_match,
)


def _item(item_id: str, ground_truth, truth_type: str = GroundTruthType.POLARITY.value) -> BenchmarkItem:
    return BenchmarkItem(item_id=item_id, benchmark="test",
        question="Test question?", ground_truth=ground_truth, truth_type=truth_type)


def _report(polarity, support: float = 0.8) -> dict:
    claim = f"[abc12345] pol={polarity}"
    return {"top_claims": [[claim, support]], "known_negations": []}


def test_polarity_match_true():
    assert _polarity_match(True, True) is True


def test_polarity_match_false():
    assert _polarity_match(False, False) is True


def test_polarity_mismatch():
    assert _polarity_match(True, False) is False


def test_polarity_match_none():
    assert _polarity_match(None, True) is False


def test_score_one_correct_true():
    result = score_one(_item("i1", True), _report(True))
    assert result.correct is True
    assert result.predicted is True


def test_score_one_correct_false():
    result = score_one(_item("i2", False), _report(False))
    assert result.correct is True


def test_score_one_incorrect():
    result = score_one(_item("i3", True), _report(False))
    assert result.correct is False


def test_score_one_no_claims():
    result = score_one(_item("i4", True), {"top_claims": [], "known_negations": []})
    assert result.correct is False
    assert result.predicted is None


def test_score_batch_accuracy():
    items = [_item(f"i{i}", True) for i in range(5)]
    # 3 correct, 2 incorrect
    reports = [_report(True)] * 3 + [_report(False)] * 2
    result = score_batch(items, reports)
    assert result["overall"]["accuracy"] == pytest.approx(0.6)
    assert result["overall"]["correct"] == 3


def test_score_batch_length_mismatch():
    with pytest.raises(ValueError):
        score_batch([_item("i1", True)], [_report(True), _report(True)])


def test_score_batch_per_benchmark():
    items = [_item("a", True), _item("b", False)]
    reports = [_report(True), _report(False)]
    result = score_batch(items, reports)
    assert "test" in result["per_benchmark"]
    assert result["per_benchmark"]["test"]["accuracy"] == 1.0
