# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for remora.semantic_entropy — SE clustering and entropy computation.

Most tests use the TokenFingerprintBackend (no external model required) and
verify mathematical properties of Semantic Entropy as defined in
Kuhn, Gal & Farquhar (ICLR 2023).

TestNLIExecution additionally executes the real NLISemanticBackend (RF-06).
Those tests skip with an explicit reason where the ``nli`` extra (or the
torch DLL) is unavailable — UNLESS REMORA_REQUIRE_NLI=1, in which case
unavailability is a hard failure (the no-silent-skip rule for the
nli-parity.yml CI job, where NLI execution is the point).
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path

import pytest

from remora.semantic_entropy import (
    SemanticCluster,
    TokenFingerprintBackend,
    _UnionFind,
    compute_semantic_entropy,
    make_backend,
    se_to_temperature,
    semantic_entropy_from_weighted_dist,
)


# ---------------------------------------------------------------------------
# UnionFind
# ---------------------------------------------------------------------------


def test_union_find_initial_state():
    uf = _UnionFind(5)
    for i in range(5):
        assert uf.find(i) == i


def test_union_find_merge():
    uf = _UnionFind(4)
    uf.union(0, 1)
    uf.union(2, 3)
    assert uf.find(0) == uf.find(1)
    assert uf.find(2) == uf.find(3)
    assert uf.find(0) != uf.find(2)


def test_union_find_transitive():
    uf = _UnionFind(3)
    uf.union(0, 1)
    uf.union(1, 2)
    assert uf.find(0) == uf.find(2)


# ---------------------------------------------------------------------------
# TokenFingerprintBackend
# ---------------------------------------------------------------------------


def test_fingerprint_backend_identical_strings():
    b = TokenFingerprintBackend()
    assert b.predict("yes", "yes") == 1.0


def test_fingerprint_backend_different_strings():
    b = TokenFingerprintBackend()
    score = b.predict("yes", "no")
    assert score == 0.0


def test_fingerprint_backend_name():
    b = TokenFingerprintBackend()
    assert b.name == "token_fingerprint"


# ---------------------------------------------------------------------------
# compute_semantic_entropy — boundary cases
# ---------------------------------------------------------------------------


def test_empty_responses():
    result = compute_semantic_entropy([])
    assert result.entropy == 0.0
    assert result.n_responses == 0
    assert result.n_clusters == 0
    assert result.clusters == ()


def test_single_response():
    result = compute_semantic_entropy(["yes"])
    assert result.entropy == 0.0
    assert result.n_responses == 1
    assert result.n_clusters == 1
    assert result.clusters[0].mass == 1.0


def test_all_identical_responses():
    """SE = 0 when all responses are semantically identical."""
    result = compute_semantic_entropy(["yes", "yes", "yes"])
    assert result.entropy == pytest.approx(0.0, abs=1e-10)
    assert result.n_clusters == 1
    assert result.clusters[0].mass == pytest.approx(1.0)


def test_all_distinct_responses():
    """SE = log(N) when all responses are maximally distinct."""
    responses = ["alpha", "beta", "gamma"]
    result = compute_semantic_entropy(responses)
    expected_entropy = math.log(3)
    assert result.n_clusters == 3
    assert result.entropy == pytest.approx(expected_entropy, rel=0.01)


def test_two_equal_one_different():
    """Two identical + one different: 2 clusters, masses 2/3 and 1/3."""
    result = compute_semantic_entropy(["yes", "yes", "no"])
    assert result.n_clusters == 2
    dominant = result.clusters[0]
    minority = result.clusters[1]
    assert dominant.mass == pytest.approx(2 / 3, abs=1e-9)
    assert minority.mass == pytest.approx(1 / 3, abs=1e-9)
    expected = -(2 / 3) * math.log(2 / 3) - (1 / 3) * math.log(1 / 3)
    assert result.entropy == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# SemanticEntropyResult properties
# ---------------------------------------------------------------------------


def test_normalised_entropy_unanimous():
    result = compute_semantic_entropy(["yes", "yes", "yes"])
    assert result.normalised_entropy == pytest.approx(0.0, abs=1e-10)


def test_normalised_entropy_maximal():
    # Use multi-word strings so the token fingerprint backend can distinguish them
    responses = ["Paris is correct", "Berlin is correct", "Rome is correct", "Madrid is correct"]
    result = compute_semantic_entropy(responses)
    assert result.normalised_entropy == pytest.approx(1.0, abs=1e-9)


def test_normalised_entropy_single_response():
    result = compute_semantic_entropy(["yes"])
    assert result.normalised_entropy == 0.0


def test_dominant_cluster_mass():
    result = compute_semantic_entropy(["yes", "yes", "no"])
    assert result.dominant_cluster_mass == pytest.approx(2 / 3, abs=1e-9)


def test_entropy_bounded_by_log_n():
    """SE must always be ≤ log(N)."""
    for responses in [
        ["a"],
        ["a", "a"],
        ["a", "b"],
        ["a", "a", "b"],
        ["a", "b", "c"],
        ["a", "b", "b", "c"],
    ]:
        result = compute_semantic_entropy(responses)
        max_entropy = math.log(len(responses)) if len(responses) > 1 else 0.0
        assert result.entropy <= max_entropy + 1e-9


def test_entropy_non_negative():
    for responses in [["yes"], ["yes", "yes"], ["yes", "no"], ["a", "b", "c"]]:
        result = compute_semantic_entropy(responses)
        assert result.entropy >= 0.0


def test_cluster_members_cover_all_responses():
    """Union of cluster members must equal the input."""
    responses = ["yes", "yes", "no", "unknown"]
    result = compute_semantic_entropy(responses)
    all_members = []
    for cluster in result.clusters:
        all_members.extend(cluster.members)
    assert sorted(all_members) == sorted(responses)


def test_cluster_masses_sum_to_one():
    responses = ["yes", "no", "yes", "unknown"]
    result = compute_semantic_entropy(responses)
    total_mass = sum(c.mass for c in result.clusters)
    assert total_mass == pytest.approx(1.0, abs=1e-9)


def test_backend_name_in_result():
    result = compute_semantic_entropy(["yes"], backend=TokenFingerprintBackend())
    assert result.backend_name == "token_fingerprint"


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------


def test_duplicate_strings_always_cluster():
    """Identical strings must cluster regardless of backend or threshold."""
    result = compute_semantic_entropy(["Paris", "Paris", "Berlin"])
    assert result.n_clusters == 2
    paris_cluster = next(c for c in result.clusters if "Paris" in c.members)
    assert len(paris_cluster) == 2


# ---------------------------------------------------------------------------
# Custom backend via entailment_threshold
# ---------------------------------------------------------------------------


class _AlwaysEntailsBackend:
    """Mock backend that always returns entailment=1.0."""
    name = "always_entails"

    def predict(self, premise: str, hypothesis: str) -> float:
        return 1.0


class _NeverEntailsBackend:
    """Mock backend that always returns entailment=0.0."""
    name = "never_entails"

    def predict(self, premise: str, hypothesis: str) -> float:
        return 0.0


def test_always_entails_backend_one_cluster():
    result = compute_semantic_entropy(
        ["Paris", "France capital", "Berlin"],
        backend=_AlwaysEntailsBackend(),
    )
    assert result.n_clusters == 1
    assert result.entropy == pytest.approx(0.0, abs=1e-10)


def test_never_entails_backend_all_distinct():
    responses = ["a", "b", "c"]
    result = compute_semantic_entropy(responses, backend=_NeverEntailsBackend())
    assert result.n_clusters == 3
    assert result.entropy == pytest.approx(math.log(3), rel=0.01)


def test_threshold_zero_treats_any_as_equivalent():
    """Threshold=0 means any non-negative score clusters responses."""
    result = compute_semantic_entropy(
        ["yes", "no"],
        backend=_AlwaysEntailsBackend(),
        entailment_threshold=0.0,
    )
    assert result.n_clusters == 1


# ---------------------------------------------------------------------------
# semantic_entropy_from_weighted_dist
# ---------------------------------------------------------------------------


def test_weighted_dist_uniform():
    dist = {"a": 0.5, "b": 0.5}
    se = semantic_entropy_from_weighted_dist(dist)
    assert se == pytest.approx(math.log(2), abs=1e-9)


def test_weighted_dist_point_mass():
    dist = {"a": 1.0}
    se = semantic_entropy_from_weighted_dist(dist)
    assert se == pytest.approx(0.0, abs=1e-10)


def test_weighted_dist_skips_zero_mass():
    dist = {"a": 0.9, "b": 0.1, "c": 0.0}
    se = semantic_entropy_from_weighted_dist(dist)
    assert se == pytest.approx(-(0.9 * math.log(0.9) + 0.1 * math.log(0.1)), abs=1e-9)


# ---------------------------------------------------------------------------
# se_to_temperature
# ---------------------------------------------------------------------------


def test_se_to_temperature_unanimous():
    """Unanimous (SE=0) → low temperature."""
    result = compute_semantic_entropy(["yes", "yes", "yes"])
    t = se_to_temperature(result, n_oracles=3)
    assert t < 0.2  # should be near the epsilon floor


def test_se_to_temperature_maximal_disagreement():
    """Maximal disagreement → high temperature."""
    result = compute_semantic_entropy(["Paris capital", "Berlin capital", "Rome capital"])
    t = se_to_temperature(result, n_oracles=3)
    assert t > 0.5


def test_se_to_temperature_bounded():
    """Temperature must always be in [0.05, 2.0]."""
    for responses in [
        ["yes"],
        ["yes", "yes", "yes"],
        ["a", "b", "c"],
        ["a", "b", "c", "d", "e"],
    ]:
        result = compute_semantic_entropy(responses)
        t = se_to_temperature(result, n_oracles=len(responses))
        assert 0.05 <= t <= 2.0


def test_se_to_temperature_ordering():
    """More disagreement → higher temperature."""
    unanimous = compute_semantic_entropy(["yes", "yes", "yes"])
    split = compute_semantic_entropy(["yes", "yes", "no"])
    all_diff = compute_semantic_entropy(["Paris capital", "Berlin capital", "Rome capital"])

    t_unanimous = se_to_temperature(unanimous, n_oracles=3)
    t_split = se_to_temperature(split, n_oracles=3)
    t_all_diff = se_to_temperature(all_diff, n_oracles=3)

    assert t_unanimous < t_split < t_all_diff


# ---------------------------------------------------------------------------
# make_backend
# ---------------------------------------------------------------------------


def test_make_backend_default_returns_token_fingerprint():
    b = make_backend(prefer_nli=False)
    assert isinstance(b, TokenFingerprintBackend)


def test_make_backend_nli_unavailable_falls_back(monkeypatch):
    """If sentence-transformers is not installed, fall back gracefully."""
    import sys
    # Force ImportError by temporarily hiding sentence_transformers
    original = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = None  # type: ignore[assignment]
    try:
        b = make_backend(prefer_nli=True)
        assert isinstance(b, TokenFingerprintBackend)
    finally:
        if original is None:
            del sys.modules["sentence_transformers"]
        else:
            sys.modules["sentence_transformers"] = original


# ---------------------------------------------------------------------------
# Integration: SE as drop-in for thermodynamic entropy
# ---------------------------------------------------------------------------


def test_se_lower_than_token_entropy_for_synonyms():
    """SE should be lower than token-hash entropy when responses are synonymous.

    With the token fingerprint backend, this can't be proven (both use the
    same fingerprint logic), but we can verify the mathematical bound holds:
    SE(2 clusters, 2 responses each from 4) < SE(4 singleton clusters).
    """
    # 2 pairs of identical responses: 2 clusters
    paired = compute_semantic_entropy(["yes", "yes", "no", "no"])
    # 4 distinct multi-word responses: 4 clusters
    # (single-char strings are filtered to "empty" by the token fingerprint backend)
    distinct = compute_semantic_entropy([
        "Paris capital France", "Berlin capital Germany",
        "Rome capital Italy", "Madrid capital Spain",
    ])

    assert paired.n_clusters == 2
    assert distinct.n_clusters == 4
    assert paired.entropy < distinct.entropy


def test_se_result_is_hashable_compat():
    """SemanticCluster and SemanticEntropyResult should be usable in sets/dicts."""
    result = compute_semantic_entropy(["yes", "no"])
    cluster = result.clusters[0]
    assert isinstance(cluster, SemanticCluster)
    # Frozen dataclass — should be hashable
    _ = {cluster}


# ---------------------------------------------------------------------------
# NLI-executed path (RF-06) — runs wherever the nli extra actually loads
# ---------------------------------------------------------------------------

# Cached (backend, failure_reason) so the cross-encoder model is constructed
# at most once per test session, not per test.
_NLI_LOAD_RESULT: tuple[object, str | None] | None = None


def _nli_backend_or_handle():
    """Return a real NLISemanticBackend, or skip/fail per REMORA_REQUIRE_NLI.

    Unavailability manifests as ImportError without the ``nli`` extra, but as
    OSError (WinError 4551) under the documented Windows application-control
    block on torch's shm.dll — hence the deliberately broad except. Called
    from test bodies (not a fixture) so REMORA_REQUIRE_NLI=1 produces a
    FAILED test, not a fixture ERROR.
    """
    global _NLI_LOAD_RESULT
    if _NLI_LOAD_RESULT is None:
        try:
            from remora.semantic_entropy import NLISemanticBackend
            _NLI_LOAD_RESULT = (NLISemanticBackend(), None)
        except Exception as exc:
            _NLI_LOAD_RESULT = (None, f"{type(exc).__name__}: {exc}")
    backend, reason = _NLI_LOAD_RESULT
    if backend is None:
        if os.environ.get("REMORA_REQUIRE_NLI") == "1":
            pytest.fail(
                f"REMORA_REQUIRE_NLI=1 but the NLI backend is unavailable: {reason}"
            )
        pytest.skip(f"NLI backend unavailable: {reason}")
    return backend


class TestNLIExecution:
    """Execute the real NLI backend — the path no reported context has run."""

    def test_lexically_disjoint_paraphrases_cluster_under_nli(self):
        """Paraphrases with zero shared content tokens must co-cluster under
        NLI while the fingerprint backend keeps them apart — the divergence
        RF-06 exists to expose."""
        backend = _nli_backend_or_handle()
        responses = ["The request was approved.", "Permission has been granted."]
        nli_result = compute_semantic_entropy(responses, backend=backend)
        fp_result = compute_semantic_entropy(
            responses, backend=TokenFingerprintBackend()
        )
        assert nli_result.n_clusters == 1
        assert fp_result.n_clusters == 2

    def test_contradiction_pair_clusters_apart_under_nli(self):
        backend = _nli_backend_or_handle()
        responses = ["The system passed every test.", "The system failed every test."]
        nli_result = compute_semantic_entropy(responses, backend=backend)
        assert nli_result.n_clusters == 2

    def test_entropy_finite_under_both_backends(self):
        backend = _nli_backend_or_handle()
        responses = [
            "The request was approved.",
            "Permission has been granted.",
            "The request was denied.",
        ]
        h_nli = compute_semantic_entropy(responses, backend=backend).entropy
        h_fp = compute_semantic_entropy(
            responses, backend=TokenFingerprintBackend()
        ).entropy
        assert isinstance(h_nli, float) and math.isfinite(h_nli)
        assert isinstance(h_fp, float) and math.isfinite(h_fp)


# ---------------------------------------------------------------------------
# Parity smoke script (scripts/se_backend_parity_smoke.py) — offline path
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
_SMOKE_SCRIPT = _ROOT / "scripts" / "se_backend_parity_smoke.py"
_CORPUS_PATH = _ROOT / "data" / "se_parity" / "paraphrase_corpus_v1.json"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "se_backend_parity_smoke", _SMOKE_SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestParitySmokeOffline:
    """Fingerprint-side structure and determinism — runs everywhere.

    The NLI path is forced unavailable via monkeypatch so the default suite
    never loads (or downloads) the cross-encoder model; real NLI execution is
    covered by TestNLIExecution and the nli-parity.yml smoke step.
    """

    def test_corpus_structure(self):
        corpus = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
        assert corpus["schema"] == "se_parity_corpus_v1"
        assert corpus["n_items"] == len(corpus["items"]) == 24
        ids = [item["id"] for item in corpus["items"]]
        assert len(ids) == len(set(ids)), "item ids must be unique"
        classes = {item["class"] for item in corpus["items"]}
        assert classes == {"paraphrase_disjoint", "contradiction_lexical", "identical"}
        for item in corpus["items"]:
            assert 3 <= len(item["responses"]) <= 5
            assert all(isinstance(r, str) and r for r in item["responses"])

    def test_smoke_script_fingerprint_only_structure_and_determinism(
        self, tmp_path, monkeypatch
    ):
        mod = _load_smoke_module()
        monkeypatch.setattr(
            mod, "try_load_nli_backend",
            lambda: (None, "forced unavailable (offline test)"),
        )
        out1 = tmp_path / "run1.json"
        out2 = tmp_path / "run2.json"
        assert mod.main(["--output", str(out1)]) == 0
        assert mod.main(["--output", str(out2)]) == 0

        payload = json.loads(out1.read_text(encoding="utf-8"))
        assert payload["status"] in {"skipped", "ok"}
        # NLI is forced unavailable here, so the skip must be explicit.
        assert payload["status"] == "skipped"
        assert payload["reason"] == "nli_backend_unavailable"
        assert payload["schema"] == "se_backend_parity_smoke_v1"
        assert payload["n_items"] == len(payload["items"]) == 24
        assert payload["fingerprint_backend"] == "token_fingerprint"
        for row in payload["items"]:
            assert set(row) == {"id", "class", "n_responses", "fingerprint"}
            stats = row["fingerprint"]
            assert stats["n_clusters"] >= 1
            assert math.isfinite(stats["entropy"]) and stats["entropy"] >= 0.0
        # Byte-identical across runs (same forced-skip status both times).
        assert out1.read_bytes() == out2.read_bytes()

    def test_smoke_script_require_nli_fails_hard_when_unavailable(
        self, tmp_path, monkeypatch
    ):
        mod = _load_smoke_module()
        monkeypatch.setattr(
            mod, "try_load_nli_backend",
            lambda: (None, "forced unavailable (offline test)"),
        )
        out = tmp_path / "out.json"
        rc = mod.main(["--require-nli", "--output", str(out)])
        assert rc != 0
        # The skip artifact is still written explicitly, never silently.
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] == "skipped"
        assert payload["reason"] == "nli_backend_unavailable"
