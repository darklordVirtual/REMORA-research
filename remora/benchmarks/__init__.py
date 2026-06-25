# Author: Stian Skogbrott
# License: Apache-2.0
"""Benchmark datasets for REMORA evaluation."""
from remora.benchmarks.loaders import (
    BenchmarkItem, BenchmarkName, GroundTruthType,
    load_hotpotqa, load_scifact, load_fever, load_dce, load_combined,
)
from remora.benchmarks.extended import load_all_extended
from remora.benchmarks.standard import (
    load_mmlu, load_arc, load_csqa, load_nq, load_gsm8k, load_code,
    load_all_standard, load_by_subject,
    load_false_claims, load_true_claims,
)

__all__ = [
    "BenchmarkItem", "BenchmarkName", "GroundTruthType",
    "load_hotpotqa", "load_scifact", "load_fever", "load_dce",
    "load_combined", "load_all_extended",
    "load_mmlu", "load_arc", "load_csqa", "load_nq", "load_gsm8k", "load_code",
    "load_all_standard", "load_by_subject",
    "load_false_claims", "load_true_claims",
]
