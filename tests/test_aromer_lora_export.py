from __future__ import annotations

import json

from scripts.benchmark_lora_metajudge import parse_response, score_prediction
from scripts.export_lora_training_data import (
    build_examples,
    completion_for,
    write_split,
)


def _episode(**overrides):
    data = {
        "id": "ep-1",
        "domain": "database",
        "risk_tier": "critical",
        "action_type": "destructive_write",
        "phase": "ordered",
        "trust_score": 0.2,
        "entropy_h": 0.1,
        "dissensus_d": 0.1,
        "verdict": "ESCALATE",
        "ground_truth": "harmful",
        "decision_quality": "correct_block",
        "outcome": "correct_block",
    }
    data.update(overrides)
    return data


def test_completion_for_false_accept_scores_safety_low():
    completion = completion_for(
        _episode(verdict="ACCEPT", decision_quality="false_accept", trust_score=0.9)
    )

    assert completion["safety_score"] == 0.0
    assert completion["truth_score"] == 0.0
    assert completion["calibration_score"] == 0.0
    assert completion["promote_memory"] is False


def test_build_examples_skips_unknown_ground_truth():
    rows = [
        (_episode(id="known"), "test"),
        (_episode(id="unknown", ground_truth="unknown", decision_quality=None), "test"),
    ]

    examples = build_examples(rows)

    assert [example.episode_id for example in examples] == ["known"]
    assert "Respond with ONLY valid JSON" in examples[0].prompt


def test_write_split_writes_prompt_completion_jsonl(tmp_path):
    examples = build_examples([(_episode(id=f"ep-{i}"), "test") for i in range(5)])

    manifest = write_split(examples, tmp_path, heldout_ratio=0.2, seed=1)

    assert manifest["n_total"] == 5
    assert manifest["n_train"] == 4
    assert manifest["n_heldout"] == 1
    train_row = json.loads((tmp_path / "train.jsonl").read_text().splitlines()[0])
    assert set(train_row) == {"prompt", "completion"}
    assert isinstance(json.loads(train_row["completion"]), dict)


def test_parse_response_extracts_json_from_text():
    parsed = parse_response('prefix {"safety_score": 1, "truth_score": 0.9} suffix')

    assert parsed["safety_score"] == 1
    assert parsed["truth_score"] == 0.9


def test_score_prediction_requires_close_rubric_scores():
    expected = {"safety_score": 1.0, "truth_score": 1.0, "calibration_score": 0.8}
    close = {"safety_score": 0.95, "truth_score": 1.0, "calibration_score": 0.75}
    far = {"safety_score": 0.2, "truth_score": 0.1, "calibration_score": 0.1}

    assert score_prediction(close, expected) >= 0.90
    assert score_prediction(far, expected) < 0.90
