# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for GainabilityClassifier."""
from __future__ import annotations

import random

from remora.selective.gainability import (
    GainabilityClassifier,
    extract_features,
)


def test_extract_features_returns_fixed_length_vector():
    item = {
        "trust_score": 0.7,
        "order_parameter": 0.6,
        "susceptibility": 0.2,
        "hallucination_bound": 0.05,
        "dissensus": 0.4,
        "rho_response_agreement": 0.3,
        "phase": "critical",
    }
    feats = extract_features(item)
    assert isinstance(feats, list)
    assert len(feats) >= 6
    assert all(isinstance(x, float) for x in feats)


def test_extract_features_missing_keys_default_to_zero():
    feats = extract_features({})
    assert all(isinstance(x, float) for x in feats)
    assert all(x == 0.0 or x == 1.0 for x in feats)  # phase one-hot may produce 0/1


def test_classifier_overfits_separable_toy_data():
    rng = random.Random(0)
    X: list[list[float]] = []
    y: list[bool] = []
    for _ in range(200):
        is_gainable = rng.random() < 0.3
        # Easy linear separator on first feature.
        f0 = rng.uniform(0.5, 1.0) if is_gainable else rng.uniform(0.0, 0.5)
        feats = [f0] + [rng.random() * 0.01 for _ in range(5)]
        X.append(feats)
        y.append(is_gainable)
    clf = GainabilityClassifier(lr=0.5, epochs=300, l2=1e-4)
    clf.fit(X, y)
    preds = [clf.predict_proba(x) > 0.5 for x in X]
    acc = sum(int(p == t) for p, t in zip(preds, y)) / len(y)
    assert acc > 0.90, f"toy accuracy {acc} too low"


def test_classifier_proba_in_unit_interval():
    clf = GainabilityClassifier()
    clf.fit([[0.0, 0.0], [1.0, 1.0]], [False, True])
    p = clf.predict_proba([0.5, 0.5])
    assert 0.0 <= p <= 1.0
