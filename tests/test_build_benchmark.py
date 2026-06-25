# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for scripts.build_benchmark."""
import json

from scripts.build_benchmark import PRESETS, BenchmarkEntry, write_benchmark_snapshot


def _entry(item_id: str, benchmark: str, domain: str) -> BenchmarkEntry:
    return BenchmarkEntry(
        item_id=item_id,
        question=f"Question for {item_id}?",
        ground_truth=True,
        domain=domain,
        benchmark=benchmark,
        difficulty="medium",
        context=None,
        best_answer=None,
        source_confidence=0.95,
        is_adversarial=False,
        notes=None,
    )


def test_n500_preset_is_explicit_and_reproducible():
    assert PRESETS["n500"] == {
        "truthfulqa_per_domain": 100,
        "boolq_per_domain": 160,
    }


def test_write_benchmark_snapshot_writes_locked_schema(tmp_path):
    snapshot_path = tmp_path / "benchmark_n500_locked.json"
    entries = [
        _entry("tqa_0001", "truthfulqa", "general"),
        _entry("boolq_0001", "boolq", "science"),
    ]

    write_benchmark_snapshot(entries, snapshot_path)

    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert data["meta"]["n_items"] == 2
    assert data["meta"]["sources"] == ["boolq", "truthfulqa"]
    assert data["meta"]["domains"] == ["general", "science"]
    assert len(data["items"]) == 2
    assert set(data["items"][0]) == {
        "item_id",
        "question",
        "ground_truth",
        "domain",
        "benchmark",
        "difficulty",
        "context",
        "best_answer",
        "source_confidence",
        "is_adversarial",
        "notes",
    }
