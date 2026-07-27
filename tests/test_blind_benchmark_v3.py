# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for blinded benchmark v3 separation invariants.

Implements intern_forbedring.txt §3 (REM-009) test requirements:
  1. tasks.json contains no evaluation-only fields
  2. labels.json contains no runtime-observable fields (beyond task_id)
  3. load_candidate_actions_v3 returns objects with no label attributes
  4. load_evaluation_truths_v3 returns objects that cannot be passed to gate.decide()
  5. score_blinded_v3 produces correct metrics
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from remora.toolcall.benchmark_blind_v3 import (
    CandidateActionV3,
    EvaluationTruthV3,
    load_candidate_actions_v3,
    load_evaluation_truths_v3,
    score_blinded_v3,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BLIND_V3_DIR = REPO_ROOT / "benchmarks" / "toolcall_blind_v3"
TASKS_PATH = BLIND_V3_DIR / "tasks.json"
LABELS_PATH = BLIND_V3_DIR / "labels.json"

LABEL_FIELDS = {"ground_truth_action", "is_unsafe_if_executed",
                "is_useful_if_executed", "expected_failure_mode", "explanation"}


@pytest.fixture(scope="module")
def tasks() -> list[CandidateActionV3]:
    return load_candidate_actions_v3()


@pytest.fixture(scope="module")
def truths() -> dict[str, EvaluationTruthV3]:
    return load_evaluation_truths_v3()


class TestSeparationInvariants:

    def test_tasks_json_has_no_label_fields(self):
        """Raw tasks.json must contain zero evaluation-only keys."""
        raw = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        for task in raw["tasks"]:
            leaked = LABEL_FIELDS & set(task.keys())
            assert not leaked, (
                f"task {task['task_id']!r} has label fields in tasks.json: {leaked}"
            )

    def test_labels_json_has_only_truth_fields(self):
        """labels.json must NOT contain observable runtime fields (beyond task_id)."""
        forbidden_in_labels = {"user_request", "proposed_tool_name", "proposed_tool_args",
                               "context", "severity", "tags", "domain"}
        raw = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
        for label in raw["labels"]:
            leaked = forbidden_in_labels & set(label.keys())
            assert not leaked, (
                f"label {label['task_id']!r} has runtime fields in labels.json: {leaked}"
            )

    def test_candidate_action_has_no_label_attributes(self, tasks):
        """CandidateActionV3 dataclass must not have label-field attributes."""
        field_names = {f.name for f in dataclasses.fields(CandidateActionV3)}
        leaked = LABEL_FIELDS & field_names
        assert not leaked, f"CandidateActionV3 has label fields: {leaked}"

    def test_evaluation_truth_has_no_runtime_attributes(self):
        """EvaluationTruthV3 must not have runtime policy fields."""
        field_names = {f.name for f in dataclasses.fields(EvaluationTruthV3)}
        runtime_fields = {"user_request", "proposed_tool_name", "severity", "tags", "context"}
        leaked = runtime_fields & field_names
        assert not leaked, f"EvaluationTruthV3 has runtime fields: {leaked}"

    def test_task_and_label_ids_match(self, tasks, truths):
        """Every task_id in tasks must have a corresponding truth label."""
        task_ids = {t.task_id for t in tasks}
        truth_ids = set(truths.keys())
        assert task_ids == truth_ids, (
            f"ID mismatch: tasks-only={task_ids - truth_ids}, "
            f"truths-only={truth_ids - task_ids}"
        )

    def test_n_tasks_consistent(self, tasks, truths):
        assert len(tasks) == 700, f"Expected 700 tasks, got {len(tasks)}"
        assert len(truths) == 700, f"Expected 700 truths, got {len(truths)}"


class TestScoringInvariants:

    def test_all_escalate_achieves_far_zero(self, tasks, truths):
        """Escalating everything must produce FAR=0."""
        decisions = ["ESCALATE"] * len(tasks)
        result = score_blinded_v3(tasks, decisions, truths)
        assert result["false_accept_rate"] == 0.0

    def test_all_execute_achieves_far_one(self, tasks, truths):
        """Executing everything must produce FAR=1.0 (all harmful tasks accepted)."""
        decisions = ["EXECUTE"] * len(tasks)
        result = score_blinded_v3(tasks, decisions, truths)
        assert result["false_accept_rate"] == 1.0, (
            f"Expected FAR=1.0 when all executed, got {result['false_accept_rate']}"
        )

    def test_harmful_benign_counts(self, tasks, truths):
        """v3 must have same harmful/benign split as v2 (560 harmful, 140 benign)."""
        decisions = ["ABSTAIN"] * len(tasks)
        result = score_blinded_v3(tasks, decisions, truths)
        assert result["n_harmful"] == 560
        assert result["n_benign"] == 140

    def test_leakage_flag_is_computed_from_task_surface(self, tasks, truths, tmp_path):
        """leakage_free must be COMPUTED from the actual task surface, not
        hardcoded (research audit P0-3). A task surface containing a label
        field must flip the flag to False."""
        decisions = ["ESCALATE"] * len(tasks)

        result = score_blinded_v3(tasks, decisions, truths)
        assert result["leakage_free"] is True
        controls = result["leakage_controls"]
        assert controls["task_surface_free_of_label_fields"] is True
        assert controls["label_fields_found"] == []

        contaminated = tmp_path / "tasks.json"
        contaminated.write_text(
            json.dumps({"tasks": [
                {"task_id": "t1", "is_unsafe_if_executed": True}
            ]}),
            encoding="utf-8",
        )
        result_bad = score_blinded_v3(tasks, decisions, truths, tasks_path=contaminated)
        assert result_bad["leakage_free"] is False
        assert "is_unsafe_if_executed" in result_bad["leakage_controls"]["label_fields_found"]

    def test_leakage_controls_report_author_annotations(self, tasks, truths):
        """severity/tags are author annotations still present in the v3 task
        surface (scheduled for removal at the next regeneration); the scorer
        must report them honestly rather than claim full blindness."""
        decisions = ["ESCALATE"] * len(tasks)
        result = score_blinded_v3(tasks, decisions, truths)
        assert set(result["leakage_controls"]["author_annotations_present"]) == {
            "severity", "tags",
        }


class TestAdapterNeutralization:

    def test_adapter_neutralizes_author_annotations(self, tasks):
        """The eval adapter must not forward severity/tags to the gate —
        neutral values only (research audit P0-2)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "toolcall_blind_v3_eval",
            REPO_ROOT / "experiments" / "toolcall_blind_v3_eval.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        task = mod._to_v2_task(tasks[0])
        assert task.severity == "unknown"
        assert task.tags == ()
