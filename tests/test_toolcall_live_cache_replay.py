from __future__ import annotations

import json
from pathlib import Path
import pytest

from experiments.evaluate_toolcall_benchmark_v2_live import run
from experiments.evaluate_toolcall_benchmark_v2_live_exec import run as run_live_exec


pytestmark = pytest.mark.live_replay_heavy


def test_live_cache_replay_runs_without_network(tmp_path: Path) -> None:
    cache_path = tmp_path / "toolcall_live_cache.json"
    first = run(mode="replay", cache_path=cache_path)
    second = run(mode="replay", cache_path=cache_path)

    assert first["n_tasks"] >= 500
    assert first["mode"] == "replay"
    assert second["mode"] == "replay"
    assert set(first["baselines"]) == set(second["baselines"])
    assert cache_path.exists()

    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "decisions" in cached
    assert "single_model_gpt" in cached["decisions"]


def test_live_exec_replay_emits_sandbox_execution_metrics(tmp_path: Path) -> None:
    cache_path = tmp_path / "toolcall_live_cache.json"
    result = run_live_exec(mode="replay", cache_path=cache_path, sandbox_root=tmp_path / "sandbox")
    assert result["evaluation"] == "sandbox_live_execution"
    assert result["n_tasks"] >= 500
    remora = result["baselines"]["REMORA_full_policy_gate"]
    assert "execution_sandbox" in remora
    sx = remora["execution_sandbox"]
    assert "unsafe_effect_rate" in sx
    assert "execute_attempt_rate" in sx
