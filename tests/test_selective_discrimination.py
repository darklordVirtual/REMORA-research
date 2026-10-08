# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""remora.selective.discrimination: discrimination measured apart from a blocking floor."""
from __future__ import annotations

import math
import random

import pytest

from remora.selective.discrimination import (
    auroc,
    operating_point_at_fbr,
    partial_auroc,
    roc_points,
    twin_concordance,
    twin_decomposition,
    wilson_interval,
)

HARM = [0.9, 0.8, 0.7, 0.2]
BEN = [0.1, 0.3, 0.75, 0.05]


def test_auroc_extremes_and_ties() -> None:
    assert auroc([2, 3], [0, 1]).auroc == 1.0
    assert auroc([0, 1], [2, 3]).auroc == 0.0
    assert auroc([1, 1], [1, 1]).auroc == 0.5
    # 13 of 16 pairs ordered correctly
    assert auroc(HARM, BEN).auroc == pytest.approx(13 / 16)


def test_delong_standard_error_agrees_with_a_bootstrap() -> None:
    rng = random.Random(7)
    h = [rng.gauss(1.0, 1.0) for _ in range(60)]
    b = [rng.gauss(0.0, 1.0) for _ in range(80)]
    r = auroc(h, b)
    boots = []
    for _ in range(1500):
        hs = [rng.choice(h) for _ in h]
        bs = [rng.choice(b) for _ in b]
        boots.append(auroc(hs, bs).auroc)
    mu = sum(boots) / len(boots)
    sd = math.sqrt(sum((x - mu) ** 2 for x in boots) / (len(boots) - 1))
    assert r.standard_error == pytest.approx(sd, rel=0.15)
    assert r.ci_low < r.auroc < r.ci_high


def test_the_interval_is_clipped_and_degenerate_inputs_refused() -> None:
    r = auroc([5, 6, 7], [1, 2, 3])
    assert (r.ci_low, r.ci_high) == (1.0, 1.0)
    for bad in ([], [float("nan")], [True]):
        with pytest.raises(ValueError):
            auroc(bad, [0.1])


def test_roc_runs_from_blocking_nothing_to_blocking_everything() -> None:
    pts = roc_points(HARM, BEN)
    assert pts[0] == (math.inf, 0.0, 0.0)
    assert pts[-1][1:] == (1.0, 1.0)
    assert all(a[1] <= b[1] and a[2] <= b[2] for a, b in zip(pts, pts[1:]))


def test_partial_auroc_standardization() -> None:
    rng = random.Random(3)
    h = [rng.random() + 0.3 for _ in range(50)]
    b = [rng.random() for _ in range(50)]
    # Over the whole range McClish's standardization is the AUROC itself.
    assert partial_auroc(h, b, max_fbr=1.0) == pytest.approx(auroc(h, b).auroc)
    assert partial_auroc([2, 3], [0, 1], max_fbr=0.1) == pytest.approx(1.0)
    same = [0.1, 0.2, 0.3, 0.4]
    assert partial_auroc(same, same, max_fbr=0.2) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        partial_auroc(h, b, max_fbr=0)


def test_operating_point_blocks_the_most_harm_the_budget_allows() -> None:
    strict = operating_point_at_fbr(HARM, BEN, fbr_budget=0.0)
    assert (strict.threshold, strict.harmful_passed, strict.benign_blocked) == (0.8, 2, 0)
    loose = operating_point_at_fbr(HARM, BEN, fbr_budget=0.25)
    assert (loose.threshold, loose.far, loose.fbr) == (0.7, 0.25, 0.25)
    assert loose.far_ci[0] <= loose.far <= loose.far_ci[1]


def test_operating_point_blocks_nothing_when_the_top_score_breaks_the_budget() -> None:
    op = operating_point_at_fbr([0.5, 0.5], [0.5, 0.5], fbr_budget=0.1)
    assert math.isinf(op.threshold)
    assert (op.far, op.fbr) == (1.0, 0.0)
    assert op.as_dict()["threshold"] == "inf"


def test_a_floor_has_zero_far_and_zero_discrimination() -> None:
    """The AgentHarm shape: everything blocked. Safe, and blind."""
    floor = twin_decomposition([(True, True)] * 20)
    assert (floor.floor, floor.discriminated, floor.floor_rate) == (20, 0, 1.0)
    assert floor.discrimination_rate == 0.0
    assert floor.mcnemar_p == 1.0


def test_twin_cells_and_exact_mcnemar() -> None:
    pairs = [(True, False)] * 10 + [(True, True)] * 3 + [(False, False)] * 2
    d = twin_decomposition(pairs)
    assert (d.discriminated, d.floor, d.leak, d.inverted) == (10, 3, 2, 0)
    assert d.mcnemar_p == pytest.approx(2 / 1024)
    both_ways = twin_decomposition([(True, False)] * 4 + [(False, True)] * 4)
    assert both_ways.mcnemar_p == 1.0
    with pytest.raises(ValueError):
        twin_decomposition([(1, 0)])  # type: ignore[list-item]


def test_twin_concordance_compares_each_harm_only_with_its_twin() -> None:
    assert twin_concordance([(0.9, 0.1), (0.2, 0.8), (0.5, 0.5)]) == pytest.approx(0.5)
    # Across pairs one harmful item outscores the other pair's benign one, but
    # each harmful item loses to its own twin.
    pairs = [(0.6, 0.7), (0.8, 0.9)]
    assert auroc([0.6, 0.8], [0.7, 0.9]).auroc == 0.25
    assert twin_concordance(pairs) == 0.0


def test_wilson_interval() -> None:
    lo, hi = wilson_interval(0, 208)
    assert lo == 0.0 and hi == pytest.approx(0.0181, abs=5e-4)  # CLAIM-002's 1.81 %
    with pytest.raises(ValueError):
        wilson_interval(3, 2)


def test_the_agentharm_diagnostic_matches_its_artifacts_and_pins_the_diagnosis() -> None:
    """POST-HOC, spent artifacts (NEGATIVE_RESULTS.md §80). Pins what the
    instrument says about them, so a change in either is seen."""
    import importlib.util
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "agentharm_discrimination_diagnostic",
        root / "scripts/agentharm_discrimination_diagnostic.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    built = mod.build()
    committed = json.loads((root / "results/agentharm_discrimination_diagnostic_v1.json")
                           .read_text(encoding="utf-8"))
    assert built == committed

    c = built["claim_002"]
    # FAR = 0 is the floor cell: no twin is told apart by the recorded decisions.
    assert c["decision_as_recorded"]["floor"] == 208
    assert c["decision_as_recorded"]["discriminated"] == 0
    assert c["minimum_effective_p"] > c["worker_escalate_at"]
    # The graded signal separates globally, and not at a low false-block rate.
    assert 0.67 < c["effective_p"]["auroc"]["auroc"] < 0.77
    assert c["effective_p"]["partial_auroc_mcclish"]["fbr<=0.1"] < 0.55
    m1 = built["trimode_n88"]["modes"]["m1_verdict"]["twins_block_is_not_accept"]
    m3 = built["trimode_n88"]["modes"]["m3_verdict"]["twins_block_is_not_accept"]
    # The oracle tells twins apart; REMORA's mode-3 mapping tells none apart.
    assert m1["discriminated"] == 29 and m1["mcnemar_p"] < 1e-6
    assert (m3["discriminated"], m3["floor"]) == (0, 44)
