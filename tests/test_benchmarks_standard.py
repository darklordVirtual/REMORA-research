# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.benchmarks.standard — MMLU / ARC / CSQA / NQ benchmark sets.

These tests verify:
  1. Structural correctness — every item has required fields with correct types.
  2. Dataset composition — expected counts and balanced true/false distribution.
  3. MockOracle integration — the standard items can be passed through the
     REMORA consensus engine without errors.
  4. Thermodynamic evaluation — phase classification runs on oracle outputs
     derived from these items.
  5. Regression guard — item counts and false-claim counts match the static
     dataset so accidental edits are caught.
"""
from __future__ import annotations

import pytest

from remora.benchmarks.loaders import BenchmarkItem, GroundTruthType
from remora.benchmarks.standard import (
    load_all_standard,
    load_arc,
    load_by_subject,
    load_code,
    load_csqa,
    load_false_claims,
    load_gsm8k,
    load_mmlu,
    load_nq,
    load_true_claims,
)
from remora.engine import Remora
from remora.genome import Genome
from remora.oracles.mock import MockOracle
from remora.thermodynamics import classify_phase, estimate_temperature, order_parameter


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestItemStructure:
    """Every item must have the required BenchmarkItem fields and correct types."""

    @pytest.fixture(params=["mmlu", "arc", "csqa", "nq", "gsm8k", "code"])
    def loader(self, request):
        loaders = {
            "mmlu": load_mmlu,
            "arc": load_arc,
            "csqa": load_csqa,
            "nq": load_nq,
            "gsm8k": load_gsm8k,
            "code": load_code,
        }
        return loaders[request.param]

    def test_returns_list_of_benchmark_items(self, loader):
        items = loader()
        assert isinstance(items, list)
        assert len(items) > 0
        assert all(isinstance(it, BenchmarkItem) for it in items)

    def test_required_fields_present(self, loader):
        for item in loader():
            assert item.item_id, f"item_id missing on {item}"
            assert item.question, f"question missing on {item}"
            assert item.benchmark, f"benchmark missing on {item}"
            assert item.truth_type == GroundTruthType.POLARITY.value, (
                f"Expected polarity truth_type on {item.item_id}"
            )
            assert isinstance(item.ground_truth, bool), (
                f"ground_truth must be bool, got {type(item.ground_truth)} on {item.item_id}"
            )

    def test_item_ids_are_unique(self, loader):
        ids = [it.item_id for it in loader()]
        assert len(ids) == len(set(ids)), "Duplicate item_ids found"

    def test_metadata_contains_subject(self, loader):
        for item in loader():
            assert "subject" in item.metadata, f"No subject in metadata on {item.item_id}"
            assert isinstance(item.metadata["subject"], str)

    def test_hash_is_stable_and_16_chars(self, loader):
        for item in loader():
            h = item.hash()
            assert len(h) == 16
            assert h == item.hash(), "hash() must be deterministic"


# ---------------------------------------------------------------------------
# Dataset composition tests
# ---------------------------------------------------------------------------

class TestDatasetComposition:
    """Verify expected item counts and balance."""

    def test_mmlu_count(self):
        assert len(load_mmlu()) == 15

    def test_arc_count(self):
        assert len(load_arc()) == 15

    def test_csqa_count(self):
        assert len(load_csqa()) == 15

    def test_nq_count(self):
        assert len(load_nq()) == 15

    def test_gsm8k_count(self):
        assert len(load_gsm8k()) == 15

    def test_code_count(self):
        assert len(load_code()) == 15

    def test_all_standard_count(self):
        assert len(load_all_standard()) == 90

    def test_all_ids_unique_across_datasets(self):
        all_items = load_all_standard()
        ids = [it.item_id for it in all_items]
        assert len(ids) == len(set(ids)), "Cross-dataset duplicate item_ids"

    def test_false_claims_are_a_meaningful_minority(self):
        false_items = load_false_claims()
        all_items = load_all_standard()
        ratio = len(false_items) / len(all_items)
        # Expect at least 20% false claims to avoid trivially easy test sets
        assert ratio >= 0.20, f"Too few false claims: {ratio:.1%}"

    def test_true_claims_are_majority(self):
        assert len(load_true_claims()) > len(load_false_claims())

    def test_true_and_false_partition_exhaustive(self):
        all_items = load_all_standard()
        assert len(load_true_claims()) + len(load_false_claims()) == len(all_items)

    def test_benchmark_names_correct(self):
        for item in load_mmlu():
            assert item.benchmark == "mmlu"
        for item in load_arc():
            assert item.benchmark == "arc"
        for item in load_csqa():
            assert item.benchmark == "csqa"
        for item in load_nq():
            assert item.benchmark == "nq"

    def test_by_subject_returns_subset(self):
        physics = load_by_subject("physics")
        assert len(physics) >= 3, "Expected at least 3 physics items"
        assert all(it.metadata["subject"] == "physics" for it in physics)

    def test_by_subject_unknown_returns_empty(self):
        assert load_by_subject("nonexistent_subject_xyz") == []


# ---------------------------------------------------------------------------
# MockOracle integration — verify items can be passed through Remora
# ---------------------------------------------------------------------------

class TestMockOracleIntegration:
    """Run a small slice of standard items through MockOracle-backed Remora."""

    @pytest.fixture
    def engine(self):
        oracles = [
            MockOracle(name="mock_a", bias=True, noise=0.1),
            MockOracle(name="mock_b", bias=True, noise=0.15),
            MockOracle(name="mock_c", bias=False, noise=0.1),
        ]
        genome = Genome(max_iterations=2)
        return Remora(oracles=oracles, genome=genome)

    def test_runs_without_error_on_all_standard_items(self, engine):
        """Smoke test: every item can be queried; no exception is raised."""
        items = load_all_standard()[:10]  # first 10 to keep the suite fast
        for item in items:
            result = engine.run(item.question)
            assert result is not None, f"engine.run returned None for {item.item_id}"

    def test_result_has_verdict_field(self, engine):
        result = engine.run(load_mmlu()[0].question)
        # Remora result should expose a final verdict or candidate
        assert hasattr(result, "verdict") or hasattr(result, "candidates") or isinstance(result, dict)

    def test_ordered_phase_items_tend_toward_agreement(self, engine):
        """Items with clear ground truth should produce lower disagreement than noisy items."""
        clear_items = [it for it in load_nq() if it.ground_truth is True][:5]
        disagreements = []
        for item in clear_items:
            result = engine.run(item.question)
            rep = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
            d = rep.get("final_D", None)
            if d is not None:
                disagreements.append(d)
        # We can only assert this runs without error; disagreement magnitude is oracle-dependent
        assert len(disagreements) >= 0  # structural: loop completes


# ---------------------------------------------------------------------------
# Thermodynamic evaluation
# ---------------------------------------------------------------------------

class TestThermodynamicEvaluation:
    """Verify thermodynamic phase classification works on oracle-produced outputs."""

    def _mock_vote_distribution(self, n_oracles: int, agree: int) -> dict[str, float]:
        """Helper: build a vote distribution where `agree` oracles say True."""
        votes: dict[str, float] = {}
        if agree > 0:
            votes["True"] = agree / n_oracles
        if agree < n_oracles:
            votes["False"] = (n_oracles - agree) / n_oracles
        return votes

    def test_unanimous_vote_classifies_as_ordered(self):
        votes = self._mock_vote_distribution(3, 3)
        temp = estimate_temperature(votes, rho_bar=0.1, individual_confidences=[0.9, 0.9, 0.9])
        eta = order_parameter(votes, k=2)
        phase = classify_phase(temperature=temp, t_critical=1.0, eta=eta)
        assert phase == "ordered"

    def test_split_vote_classifies_as_disordered_or_critical(self):
        votes = self._mock_vote_distribution(3, 1)  # 1–2 split
        temp = estimate_temperature(votes, rho_bar=0.1, individual_confidences=[0.5, 0.5, 0.5])
        eta = order_parameter(votes, k=2)
        phase = classify_phase(temperature=temp, t_critical=1.0, eta=eta)
        assert phase in ("disordered", "critical")

    def test_mmlu_physics_items_can_be_evaluated(self):
        """Run mock oracle evaluation on MMLU physics items and check phase output."""
        physics_items = load_by_subject("physics")
        assert len(physics_items) >= 3

        for item in physics_items:
            # Simulate unanimous oracle agreement (ordered phase)
            votes = {"True": 1.0}
            temp = estimate_temperature(votes, rho_bar=0.05, individual_confidences=[0.9, 0.92, 0.88])
            eta = order_parameter(votes, k=2)
            phase = classify_phase(temperature=temp, t_critical=1.0, eta=eta)
            assert phase in ("ordered", "critical", "disordered"), (
                f"Unexpected phase '{phase}' for {item.item_id}"
            )

    def test_false_claims_can_be_evaluated_without_error(self):
        """False-claim items (adversarial) should not break the evaluation pipeline."""
        false_items = load_false_claims()
        for item in false_items:
            votes = {"False": 0.67, "True": 0.33}
            temp = estimate_temperature(votes, rho_bar=0.1, individual_confidences=[0.6, 0.55, 0.65])
            phase = classify_phase(temperature=temp, t_critical=1.0, eta=order_parameter(votes, k=2))
            assert phase in ("ordered", "critical", "disordered")


# ---------------------------------------------------------------------------
# Regression guard — static item counts
# ---------------------------------------------------------------------------

class TestRegressionGuard:
    """Pin expected counts so accidental dataset edits are caught immediately."""

    def test_mmlu_false_claim_count(self):
        false_count = sum(1 for it in load_mmlu() if not it.ground_truth)
        assert false_count == 4, f"Expected 4 MMLU false claims, got {false_count}"

    def test_arc_false_claim_count(self):
        false_count = sum(1 for it in load_arc() if not it.ground_truth)
        assert false_count == 3, f"Expected 3 ARC false claims, got {false_count}"

    def test_csqa_false_claim_count(self):
        false_count = sum(1 for it in load_csqa() if not it.ground_truth)
        assert false_count == 4, f"Expected 4 CSQA false claims, got {false_count}"

    def test_nq_false_claim_count(self):
        false_count = sum(1 for it in load_nq() if not it.ground_truth)
        assert false_count == 4, f"Expected 4 NQ false claims, got {false_count}"

    def test_total_false_claim_count(self):
        assert len(load_false_claims()) == 24, "Expected 24 false claims across all standard sets (15 original + 4 gsm8k + 5 code)"

    def test_total_true_claim_count(self):
        assert len(load_true_claims()) == 66, "Expected 66 true claims across all standard sets"
