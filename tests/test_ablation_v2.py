# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for experiments.ablation_v2."""

from experiments.ablation_v2 import load_benchmark


def test_load_benchmark_supports_canonical_module():
    items, meta_map, loader_name = load_benchmark("remora.benchmarks.extended_v2")

    assert loader_name == "load_all_extended_v2"
    assert len(items) == 302
    assert len(meta_map) == 302
    assert all(item.item_id in meta_map for item in items)


def test_load_benchmark_supports_n500_module():
    items, meta_map, loader_name = load_benchmark("remora.benchmarks.extended_v2_n500")

    assert loader_name == "load_all_extended_v2"
    assert len(items) >= 500
    assert len(meta_map) == len(items)
    assert all(item.item_id in meta_map for item in items)
