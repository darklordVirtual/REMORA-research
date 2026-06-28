# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for REM-010: LLM-backed toolcall baselines.

Verifies:
1. Artifact file exists and has valid schema.
2. All three baselines are present in the artifact.
3. FAR (false accept rate) metric is non-null and numerically valid.
4. Results cover the expected N tasks.
5. All recorded actions are valid EXECUTE/VERIFY/ABSTAIN/ESCALATE.
6. Live baseline classes raise cleanly when GROQ_API_KEY is absent.
7. Baseline names distinguish from heuristic baselines (_llm suffix).
"""
from __future__ import annotations

import json

import pytest

from remora.toolcall.baselines_llm import (
    MajorityVoteLLMBaseline,
    SelfConsistencyLLMBaseline,
    SingleModelLLMBaseline,
    _RESULTS_PATH,
    _VALID_ACTIONS,
    all_llm_baselines,
    load_llm_baseline_results,
)

_EXPECTED_BASELINES = {"single_model_llm", "majority_vote_llm", "self_consistency_llm"}
_PILOT_N = 100


class TestArtifactExists:
    """Artifact file (results/toolcall_llm_baselines_pilot_n100.json) must exist."""

    def test_artifact_file_exists(self) -> None:
        assert _RESULTS_PATH.exists(), (
            f"LLM baseline artifact not found: {_RESULTS_PATH}. "
            "Run scripts/run_llm_baselines_v3.py to generate it."
        )

    def test_artifact_is_valid_json(self) -> None:
        with open(_RESULTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_artifact_schema_version(self) -> None:
        data = load_llm_baseline_results()
        assert data["schema_version"] == "llm_baselines_v1"

    def test_artifact_model_field(self) -> None:
        data = load_llm_baseline_results()
        assert "model" in data
        assert "llama" in data["model"].lower() or "cf/" in data["model"].lower()

    def test_artifact_benchmark_field(self) -> None:
        data = load_llm_baseline_results()
        assert data["benchmark"] == "toolcall_blind_v3"

    def test_artifact_n_tasks_field(self) -> None:
        data = load_llm_baseline_results()
        assert data["n_tasks"] == _PILOT_N


class TestArtifactBaselines:
    """All three baselines must be present with correct structure."""

    def test_all_three_baselines_present(self) -> None:
        data = load_llm_baseline_results()
        assert set(data["baselines"].keys()) == _EXPECTED_BASELINES

    def test_each_baseline_has_results(self) -> None:
        data = load_llm_baseline_results()
        for name, baseline_data in data["baselines"].items():
            assert "results" in baseline_data, f"{name} missing results"
            assert len(baseline_data["results"]) > 0, f"{name} has empty results"

    def test_each_baseline_has_n_tasks(self) -> None:
        data = load_llm_baseline_results()
        for name, baseline_data in data["baselines"].items():
            n = baseline_data.get("n_tasks", 0)
            assert n == _PILOT_N, f"{name}: expected {_PILOT_N} tasks, got {n}"

    def test_all_actions_are_valid(self) -> None:
        data = load_llm_baseline_results()
        for baseline_name, baseline_data in data["baselines"].items():
            for r in baseline_data["results"]:
                assert r["action"] in _VALID_ACTIONS, (
                    f"{baseline_name}: invalid action '{r['action']}' for task {r.get('task_id')}"
                )

    def test_each_result_has_task_id(self) -> None:
        data = load_llm_baseline_results()
        for baseline_name, baseline_data in data["baselines"].items():
            for r in baseline_data["results"]:
                assert "task_id" in r, f"{baseline_name}: result missing task_id"
                assert isinstance(r["task_id"], str) and r["task_id"], (
                    f"{baseline_name}: empty task_id"
                )

    def test_each_result_has_confidence(self) -> None:
        data = load_llm_baseline_results()
        for baseline_name, baseline_data in data["baselines"].items():
            for r in baseline_data["results"]:
                conf = r.get("confidence")
                assert isinstance(conf, (int, float)), (
                    f"{baseline_name}: confidence must be numeric, got {conf!r}"
                )
                assert 0.0 <= conf <= 1.0, (
                    f"{baseline_name}: confidence {conf} out of [0,1]"
                )


class TestArtifactStats:
    """Statistical metrics must be valid and within plausible ranges."""

    def test_far_is_present(self) -> None:
        data = load_llm_baseline_results()
        for name, baseline_data in data["baselines"].items():
            stats = baseline_data.get("stats", {})
            assert "false_accept_rate" in stats, f"{name} missing FAR in stats"

    def test_far_is_numeric_or_none(self) -> None:
        data = load_llm_baseline_results()
        for name, baseline_data in data["baselines"].items():
            far = baseline_data.get("stats", {}).get("false_accept_rate")
            if far is not None:
                assert isinstance(far, (int, float)), f"{name} FAR must be numeric"
                assert 0.0 <= far <= 1.0, f"{name} FAR {far} out of [0,1]"

    def test_single_model_far_below_one(self) -> None:
        data = load_llm_baseline_results()
        far = data["baselines"]["single_model_llm"]["stats"].get("false_accept_rate")
        if far is not None:
            assert far < 1.0, "FAR >= 1.0 would mean all harmful tasks were accepted"

    def test_action_distribution_covers_pilot(self) -> None:
        data = load_llm_baseline_results()
        for name, baseline_data in data["baselines"].items():
            dist = baseline_data.get("stats", {}).get("action_distribution", {})
            total = sum(dist.values())
            if total > 0:
                assert total == _PILOT_N, (
                    f"{name}: action_distribution totals {total}, expected {_PILOT_N}"
                )


class TestLLMBaselineClasses:
    """LLM baseline classes have correct names and structure."""

    def test_all_llm_baselines_returns_three(self) -> None:
        assert len(all_llm_baselines()) == 3

    def test_baseline_names_have_llm_suffix(self) -> None:
        for b in all_llm_baselines():
            assert b.name.endswith("_llm"), (
                f"LLM baseline {b.__class__.__name__} name '{b.name}' must end with '_llm'"
            )

    def test_baseline_names_distinct_from_heuristics(self) -> None:
        from remora.toolcall.baselines import all_baselines as heuristic_baselines
        heuristic_names = {b.name for b in heuristic_baselines()}
        llm_names = {b.name for b in all_llm_baselines()}
        overlap = heuristic_names & llm_names
        assert not overlap, f"LLM and heuristic baselines share names: {overlap}"

    def test_single_model_baseline_has_correct_name(self) -> None:
        b = SingleModelLLMBaseline()
        assert b.name == "single_model_llm"

    def test_majority_vote_baseline_has_n_samples(self) -> None:
        b = MajorityVoteLLMBaseline()
        assert b.n_samples == 3

    def test_self_consistency_baseline_has_n_samples(self) -> None:
        b = SelfConsistencyLLMBaseline()
        assert b.n_samples == 5

    def test_live_baseline_raises_without_api_key(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.delenv("CF_AIG_TOKEN", raising=False)
        b = SingleModelLLMBaseline()
        from remora.toolcall.benchmark_blind_v3 import load_candidate_actions_v3
        task = load_candidate_actions_v3()[0]
        with pytest.raises(RuntimeError, match="CLOUDFLARE_API_TOKEN"):
            b.decide(task)
