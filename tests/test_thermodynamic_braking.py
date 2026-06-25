import pytest
from remora.lyapunov import LyapunovState
from remora.policy.thermodynamic_braking import ThermodynamicBrakingSystem

def test_braking_requires_at_least_two_steps():
    system = ThermodynamicBrakingSystem()
    trajectory = [LyapunovState(t=0, H=0.1, D=0.1, cost=0.0, V=0.2, consensus_fp="")]
    result = system.calculate_braking(trajectory)

    assert not result.is_braking
    assert result.penalty == 0.0

def test_braking_does_not_engage_on_stable_trajectory():
    system = ThermodynamicBrakingSystem(activation_threshold=0.05)

    # Trajectory is stable (V drops from 0.5 to 0.4)
    trajectory = [
        LyapunovState(t=0, H=0.2, D=0.3, cost=0.0, V=0.5, consensus_fp=""),
        LyapunovState(t=1, H=0.2, D=0.2, cost=0.0, V=0.4, consensus_fp=""),
    ]

    result = system.calculate_braking(trajectory)
    assert not result.is_braking
    assert pytest.approx(result.trajectory_delta) == -0.1
    assert result.penalty == 0.0

def test_braking_engages_on_accelerating_chaos():
    # Set high sensitivity to see a strong penalty
    system = ThermodynamicBrakingSystem(sensitivity=2.0, activation_threshold=0.05, max_penalty=0.50)

    # Trajectory goes chaotic (V spikes from 0.2 to 0.6 => dV = +0.4)
    trajectory = [
        LyapunovState(t=0, H=0.1, D=0.1, cost=0.0, V=0.2, consensus_fp=""),
        LyapunovState(t=1, H=0.3, D=0.3, cost=0.0, V=0.6, consensus_fp=""),
    ]

    result = system.calculate_braking(trajectory)
    assert result.is_braking
    assert pytest.approx(result.trajectory_delta) == 0.4

    # Expected penalty: (0.4 - 0.05) * 2.0 = 0.7. Capped at 0.50.
    assert pytest.approx(result.penalty) == 0.50
    assert "Thermodynamic braking engaged" in result.reason

def test_braking_respects_linear_scaling_before_cap():
    system = ThermodynamicBrakingSystem(sensitivity=1.0, activation_threshold=0.05, max_penalty=0.80)

    # dV = +0.20
    trajectory = [
        LyapunovState(t=0, H=0.1, D=0.1, cost=0.0, V=0.2, consensus_fp=""),
        LyapunovState(t=1, H=0.2, D=0.2, cost=0.0, V=0.4, consensus_fp=""),
    ]

    result = system.calculate_braking(trajectory)
    assert result.is_braking
    assert pytest.approx(result.trajectory_delta) == 0.2

    # Expected penalty: (0.2 - 0.05) * 1.0 = 0.15
    assert pytest.approx(result.penalty) == 0.15
