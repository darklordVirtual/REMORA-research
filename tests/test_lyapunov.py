# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.lyapunov — V function and abort controller."""
from remora.lyapunov import (
    LyapunovController,
    LyapunovParams,
    LyapunovState,
    compute_entropy,
    lyapunov_value,
    summarize_v_trajectories,
)


def _make_state(t: int, V: float, H: float = 0.5, D: float = 0.5) -> LyapunovState:
    return LyapunovState(t=t, H=H, D=D, cost=0.0, V=V, consensus_fp="fp")


def test_entropy_uniform_distribution():
    dist = {"a": 0.5, "b": 0.5}
    H = compute_entropy(dist)
    assert abs(H - 1.0) < 1e-9


def test_entropy_certain():
    H = compute_entropy({"a": 1.0})
    assert H == 0.0


def test_lyapunov_value_monotone_decreasing():
    dist1 = {"a": 0.5, "b": 0.5}  # high entropy
    dist2 = {"a": 0.9, "b": 0.1}  # lower entropy
    V1, _, _ = lyapunov_value(dist1, 0.0, LyapunovParams())
    V2, _, _ = lyapunov_value(dist2, 0.0, LyapunovParams())
    assert V2 < V1


def test_lyapunov_empty_distribution():
    V, H, D = lyapunov_value({}, 0.0, LyapunovParams())
    assert V == float("inf")


def test_abort_warming_up():
    ctrl = LyapunovController.init(LyapunovParams(min_window=2))
    ctrl.push(_make_state(1, V=1.0))
    abort, reason = ctrl.should_abort()
    assert not abort
    assert reason == "warming_up"


def test_abort_triggered_on_increase():
    params = LyapunovParams(epsilon_tolerance=0.01, min_window=2)
    ctrl = LyapunovController.init(params)
    ctrl.push(_make_state(1, V=1.0))
    ctrl.push(_make_state(2, V=2.0))  # large increase
    abort, reason = ctrl.should_abort()
    assert abort
    assert "V_increased" in reason


def test_no_abort_on_decrease():
    params = LyapunovParams(epsilon_tolerance=0.05, min_window=2)
    ctrl = LyapunovController.init(params)
    ctrl.push(_make_state(1, V=2.0))
    ctrl.push(_make_state(2, V=1.5))
    abort, _ = ctrl.should_abort()
    assert not abort


def test_is_converging_monotone():
    ctrl = LyapunovController.init(LyapunovParams())
    for i, v in enumerate([3.0, 2.0, 1.0]):
        ctrl.push(_make_state(i+1, V=v))
    assert ctrl.is_converging(last_k=3)


def test_is_not_converging():
    ctrl = LyapunovController.init(LyapunovParams())
    for i, v in enumerate([1.0, 2.0, 1.5]):
        ctrl.push(_make_state(i+1, V=v))
    assert not ctrl.is_converging(last_k=3)


def test_total_reduction():
    ctrl = LyapunovController.init(LyapunovParams())
    ctrl.push(_make_state(1, V=3.0))
    ctrl.push(_make_state(2, V=1.0))
    assert abs(ctrl.total_reduction() - 2.0) < 1e-9


def test_summarize_v_trajectories_reports_aggregate_stability():
    summary = summarize_v_trajectories(
        [
            [1.5, 1.2, 1.0],
            [1.0, 1.1, 0.9],
            [2.0, 1.8, 1.6],
        ],
        epsilon_tolerance=0.0,
    )
    assert summary["n_trajectories"] == 3
    assert summary["n_steps"] == 6
    assert summary["fraction_monotone_nonincreasing"] == 2 / 3
    assert summary["divergent_fraction"] == 1 / 3
    assert summary["mean_total_reduction"] > 0
