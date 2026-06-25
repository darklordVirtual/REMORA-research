"""Tests for remora.selective.feature_join."""
from __future__ import annotations


from remora.selective.feature_join import (
    build_gainability_features,
    feature_coverage_report,
    gainability_label,
    load_joined_items,
)


# ---------------------------------------------------------------------------
# load_joined_items
# ---------------------------------------------------------------------------

def test_load_joined_items_returns_list():
    result = load_joined_items()
    assert isinstance(result, list)


def test_load_joined_items_ablation_fields_present():
    items = load_joined_items()
    assert len(items) > 0
    for item in items:
        # Every item must have the core ablation classification field.
        assert "majority_correct" in item, f"missing majority_correct in {item.keys()}"
        assert "item_id" in item


def test_load_joined_items_thermo_match_has_trust_score():
    items = load_joined_items()
    # Items that joined successfully should have non-None trust_score.
    matched = [it for it in items if it.get("trust_score") is not None]
    assert len(matched) > 0, "Expected at least some items to have thermo data joined"


def test_load_joined_items_no_match_has_none_trust_score():
    """Items that failed to join should have trust_score as None (not a crash)."""
    from pathlib import Path
    import json
    import tempfile
    import os

    # Create a minimal ablation artifact with a fake item_id that won't join.
    fake_ablation = {
        "conditions": {
            "B_majority": {
                "items": [
                    {
                        "item_id": "fake_item_no_thermo_9999",
                        "benchmark": "test",
                        "domain": "test",
                        "correct": False,
                        "is_adversarial": False,
                        "difficulty": "medium",
                    }
                ]
            }
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(fake_ablation, fh)
        tmp_path = fh.name

    try:
        items = load_joined_items(ablation_path=Path(tmp_path))
        assert len(items) == 1
        assert items[0]["trust_score"] is None
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# build_gainability_features
# ---------------------------------------------------------------------------

def test_build_gainability_features_length_11():
    items = load_joined_items()
    assert len(items) > 0
    feats = build_gainability_features(items[0])
    assert len(feats) == 11


def test_build_gainability_features_empty_item_no_crash():
    feats = build_gainability_features({})
    assert len(feats) == 11
    # All should be numeric floats.
    for v in feats:
        assert isinstance(v, float)


def test_build_gainability_features_all_floats():
    items = load_joined_items()
    for item in items[:20]:
        feats = build_gainability_features(item)
        assert all(isinstance(v, float) for v in feats)


# ---------------------------------------------------------------------------
# gainability_label
# ---------------------------------------------------------------------------

def test_gainability_label_true_when_majority_wrong_d2_right():
    assert gainability_label({"majority_correct": False, "d2_correct": True}) is True


def test_gainability_label_false_when_majority_correct():
    assert gainability_label({"majority_correct": True, "d2_correct": True}) is False


def test_gainability_label_false_when_both_wrong():
    assert gainability_label({"majority_correct": False, "d2_correct": False}) is False


def test_gainability_label_false_empty_defaults():
    # majority_correct defaults to True, so label should be False.
    assert gainability_label({}) is False


# ---------------------------------------------------------------------------
# feature_coverage_report
# ---------------------------------------------------------------------------

def test_feature_coverage_report_empty_item_zero_coverage():
    report = feature_coverage_report([{}])
    assert isinstance(report, dict)
    # An empty dict has no keys, so the report should be empty.
    assert report == {}


def test_feature_coverage_report_with_none_values_zero_coverage():
    report = feature_coverage_report([{"trust_score": None, "phase": None}])
    assert isinstance(report, dict)
    assert "trust_score" in report
    assert report["trust_score"]["count"] == 0
    assert report["trust_score"]["coverage_pct"] == 0.0


def test_feature_coverage_report_full_item_100_pct():
    full_item = {
        "trust_score": 0.5,
        "phase": "ordered",
        "majority_correct": True,
    }
    report = feature_coverage_report([full_item])
    for key in ("trust_score", "phase", "majority_correct"):
        assert report[key]["count"] == 1
        assert report[key]["coverage_pct"] == 100.0


def test_feature_coverage_report_returns_dict_with_known_keys():
    items = load_joined_items()
    report = feature_coverage_report(items)
    assert isinstance(report, dict)
    # These keys must appear in the report (all ablation items have them).
    for key in ("majority_correct", "item_id"):
        assert key in report
        assert report[key]["coverage_pct"] == 100.0
