# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the SAP v3 round's pure analysis machinery (no network)."""
from __future__ import annotations

import pytest

from experiments.sap_v3_round import (
    pav_fit,
    pav_predict,
    signals_for,
    three_way_split,
)


def test_pav_is_monotone_and_pools_violators() -> None:
    grid, vals = pav_fit([0.1, 0.2, 0.3, 0.4], [1.0, 0.0, 1.0, 1.0])
    assert vals == sorted(vals)  # non-decreasing by construction
    # The 1,0 violator pair pools to 0.5.
    assert pav_predict(grid, vals, 0.15) == pytest.approx(0.5)
    assert pav_predict(grid, vals, 0.9) == pytest.approx(1.0)


def test_pav_perfect_separation() -> None:
    grid, vals = pav_fit([0.1, 0.2, 0.8, 0.9], [0.0, 0.0, 1.0, 1.0])
    assert pav_predict(grid, vals, 0.05) == pytest.approx(0.0)
    assert pav_predict(grid, vals, 0.95) == pytest.approx(1.0)


def test_pav_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        pav_fit([0.1], [0.0, 1.0])
    with pytest.raises(ValueError):
        pav_fit([], [])


def _rows(n: int = 200) -> list[dict]:
    rows = []
    for i in range(n):
        h = f"{i:08x}"
        rows.append({
            "item_id": f"boolq_{i:04d}_{h}",
            "benchmark": "boolq" if i % 3 else "truthfulqa",
            "ground_truth": bool(i % 2),
            "votes": ["true", "true", "false"],
            "confidences": [0.9, 0.8, 0.6],
            "correct_per_oracle": [bool(i % 2), True, False],
            "majority_prediction": "true",
            "majority_correct": bool(i % 2),
            "temperature": 0.1 + (i % 10) * 0.05,
        })
    return rows


def test_three_way_split_sizes_and_disjointness() -> None:
    rows = _rows(300)
    dev, riskcal, test = three_way_split(rows)
    assert len(dev) + len(riskcal) + len(test) == 300
    # SAP v3: 40/30/30 within group-rounding tolerance.
    assert abs(len(dev) - 120) <= 12
    assert abs(len(riskcal) - 90) <= 12
    assert abs(len(test) - 90) <= 12
    ids = [r["item_id"] for r in dev + riskcal + test]
    assert len(ids) == len(set(ids))


def test_three_way_split_is_deterministic() -> None:
    rows = _rows(150)
    a = tuple(tuple(sorted(r["item_id"] for r in part)) for part in three_way_split(rows))
    b = tuple(tuple(sorted(r["item_id"] for r in part)) for part in three_way_split(rows))
    assert a == b


def test_signals_use_calibrated_confidence() -> None:
    row = _rows(1)[0]
    # Identity-ish calibration: perfect separation on the dev fit.
    grid, vals = pav_fit([0.0, 1.0], [0.0, 1.0])
    calib = {"grids": [grid] * 3, "vals": [vals] * 3}
    sig = signals_for(row, calib)
    assert sig["neg_temperature"] == pytest.approx(-row["temperature"])
    assert 0.0 <= sig["calibrated_mean_confidence"] <= 1.0
    # margin is 2-1 = 1 plus the bounded calibrated mean.
    assert 1.0 <= sig["margin_plus_calibrated_confidence"] <= 2.0
