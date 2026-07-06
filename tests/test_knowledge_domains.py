# Author: Stian Skogbrott
# License: Apache-2.0
"""Knowledge-domain modules: deterministic logic + artifact agreement.

Per docs/claim_hygiene.md, every number a doc states must be computed here and
match a committed result artifact with status:ok. These tests fail if the code
and the artifact diverge, or an invariant breaks.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.knowledge_domains import (
    cost_routing,
    eval_harness,
    evidence_graph,
    multitenant,
    ontology,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "knowledge_domains"


def _result(name: str) -> dict:
    data = json.loads((RESULTS / f"{name}.json").read_text())
    assert data["status"] == "ok"
    assert data["provenance"]["schema"] == "result_provenance_v1"
    return data["result"]


# ── eval_harness ────────────────────────────────────────────────────────────

def test_eval_harness_matches_artifact():
    scores = eval_harness.evaluate(eval_harness.GOLD, eval_harness.PREDICTIONS)
    assert _result("eval_harness") == scores


def test_eval_harness_perfect_scores_one():
    perfect = tuple(
        eval_harness.Prediction(c.qid, c.gold_ids, c.should_refuse)
        for c in eval_harness.GOLD
    )
    scores = eval_harness.evaluate(eval_harness.GOLD, perfect)
    assert scores["grounding_f1"] == 1.0 and scores["refusal_accuracy"] == 1.0


# ── evidence_graph ──────────────────────────────────────────────────────────

def test_evidence_graph_matches_artifact():
    assert _result("evidence_graph") == evidence_graph.metrics(
        evidence_graph.build_graph(evidence_graph.FIXTURE))


def test_evidence_graph_detects_orphan():
    g = evidence_graph.build_graph(
        ({"id": "X", "artifacts": [], "literature": [], "docs": ["d"]},))
    assert evidence_graph.orphan_claims(g) == ["X"]


# ── multitenant ─────────────────────────────────────────────────────────────

def test_multitenant_matches_artifact():
    assert _result("multitenant") == multitenant.run_isolation_battery().__dict__


def test_cross_tenant_read_refused():
    s = multitenant.TenantStore()
    s.put("a", "k", "secret")
    with pytest.raises(multitenant.CrossTenantError):
        s.get("b", "k")


def test_chains_do_not_interleave():
    s = multitenant.TenantStore()
    s.put("a", "k", "v")
    s.put("b", "k", "v")
    assert s.head("a") != s.head("b")


# ── ontology ────────────────────────────────────────────────────────────────

def test_ontology_matches_artifact():
    assert _result("ontology") == ontology.validate(ontology.FIXTURE)


def test_ontology_flags_unknown_level():
    bad = ({"id": "B", "evidence_level": "vibes", "metrics": {"n_x": 1}},)
    assert ontology.validate(bad)["nonconforming"] == 1


# ── cost_routing ────────────────────────────────────────────────────────────

def test_cost_routing_matches_artifact():
    result = cost_routing.route(cost_routing.MODELS, cost_routing.WORKLOAD)
    art = _result("cost_routing")
    for key in ("n_requests", "savings_ratio", "quality_violations",
                "routed_cost", "baseline_cost"):
        assert art[key] == result[key]


def test_cost_routing_sound_and_cheaper():
    r = cost_routing.route(cost_routing.MODELS, cost_routing.WORKLOAD)
    assert r["quality_violations"] == 0
    assert r["routed_cost"] < r["baseline_cost"]


def test_cost_routing_picks_cheapest_eligible():
    assert cost_routing.cheapest_meeting(cost_routing.MODELS, 0.70).name == "small"
    assert cost_routing.cheapest_meeting(cost_routing.MODELS, 0.99) is None
