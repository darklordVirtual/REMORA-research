# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression pins for external review 2026-07-29 findings F-06 and F-08.

F-06: the deterministic-round orchestrator declared a provenance input path
(artifacts/...) that differed from the file the experiment actually reads
(benchmarks/...), so the documented fail-hard reproduction round aborted in
the provenance step on a clean HEAD.

F-08: compare_runs() called load_seeds(..., shadow=False) against a
keyword-only ``shadow_mode`` parameter; the TypeError was swallowed by a
broad except and the "seeded" arm silently ran unseeded — a misleading A/B.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_orchestrator():
    spec = importlib.util.spec_from_file_location(
        "run_deterministic_round_2026_07",
        ROOT / "scripts" / "run_deterministic_round_2026_07.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_deterministic_round_2026_07"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_declared_provenance_inputs_exist_on_disk():
    """F-06: every declared sidecar input must be a real file at HEAD."""
    mod = _load_orchestrator()
    missing = {
        artifact: str(path)
        for artifact, (_script, inputs, _codes) in mod.SIDECARS.items()
        for name, path in inputs.items()
        if not Path(path).is_file()
    }
    assert not missing, f"declared provenance inputs missing: {missing}"


class _FakeSIS:
    sis = 0.5
    safety_preservation = 1.0


class _FakeReport:
    overall_accuracy = 0.5
    false_accept_rate = 0.0
    false_block_rate = 0.0
    sis = _FakeSIS()

    def to_dict(self):
        return {}


def test_compare_runs_actually_loads_seeds(monkeypatch, tmp_path):
    """F-08: the seeded arm must call the seeds loader with valid kwargs."""
    from remora.aromer.evals import replay_runner
    from remora.aromer.seeds import load_aromer_seeds

    calls: dict = {}

    def spy(seed_dir, **kwargs):
        calls["seed_dir"] = seed_dir
        calls["kwargs"] = kwargs

    monkeypatch.setattr(load_aromer_seeds, "load_seeds", spy)
    monkeypatch.setattr(replay_runner, "run_arena", lambda *a, **k: _FakeReport())

    out = replay_runner.compare_runs(
        arena_dir=tmp_path, seeds_dir=tmp_path, load_seeds=True)
    assert calls, "seeds loader was never called on the seeded arm"
    assert calls["kwargs"] == {"dry_run": False, "shadow_mode": False}
    assert set(out) == {"cold", "seeded", "delta"}


def test_compare_runs_does_not_swallow_programming_errors(monkeypatch, tmp_path):
    """F-08: a TypeError in the loader must propagate, not become a warning."""
    from remora.aromer.evals import replay_runner
    from remora.aromer.seeds import load_aromer_seeds

    def bad(seed_dir, **kwargs):
        raise TypeError("unexpected keyword argument")

    monkeypatch.setattr(load_aromer_seeds, "load_seeds", bad)
    monkeypatch.setattr(replay_runner, "run_arena", lambda *a, **k: _FakeReport())

    with pytest.raises(TypeError):
        replay_runner.compare_runs(
            arena_dir=tmp_path, seeds_dir=tmp_path, load_seeds=True)
