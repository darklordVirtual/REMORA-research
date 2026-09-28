# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""effective_n counts harmful template clusters, not domains.

The tool-call scorers derived clusters by stripping the last ``_`` segment of
the task id. Task ids are ``<domain>2_<seq>`` (``sh2_0001``), so that yielded
one "cluster" per domain: every v1, v2 and blind v3 result recorded
``effective_n: 7``, while the significance analysis correctly used 70 template
clusters. A cluster is one template: (domain, scenario_family) where the task
carries a family, else (domain, tool, arguments without the variant counter).
"""
from __future__ import annotations

from remora.toolcall.benchmark import generate_benchmark
from remora.toolcall.benchmark_v2 import generate_benchmark_v2
from remora.toolcall.scoring import template_cluster_key


def _harmful_clusters(tasks) -> int:
    return len({template_cluster_key(t) for t in tasks if t.is_unsafe_if_executed})


def test_v2_has_56_harmful_clusters_of_70():
    tasks = generate_benchmark_v2()
    assert len({template_cluster_key(t) for t in tasks}) == 70
    assert _harmful_clusters(tasks) == 56


def test_v1_clusters_ignore_the_variant_counter():
    tasks = generate_benchmark()
    assert len({template_cluster_key(t) for t in tasks}) == 42
    assert _harmful_clusters(tasks) == 21


def test_a_cluster_is_never_just_the_domain():
    tasks = generate_benchmark_v2()
    domains = {t.domain for t in tasks}
    assert _harmful_clusters(tasks) > len(domains)


def test_aggregate_metrics_reports_harmful_clusters():
    from remora.toolcall.scoring import aggregate_metrics
    from remora.toolcall.schema import ToolCallDecision, ToolCallOutcome

    tasks = generate_benchmark_v2()
    outcomes = [
        ToolCallOutcome(
            task_id=t.task_id,
            decision=ToolCallDecision(action="ESCALATE"),
            correct_action=False, unsafe_execution=False, false_accept=False,
            false_block=False, correct_abstention=False,
            critical_error_intercepted=False, utility_score=0.0,
        )
        for t in tasks
    ]
    assert aggregate_metrics(tasks, outcomes)["effective_n"] == 56


def test_blind_v3_reports_harmful_clusters():
    from remora.toolcall.benchmark_blind_v3 import (
        load_candidate_actions_v3,
        load_evaluation_truths_v3,
        score_blinded_v3,
    )

    tasks = load_candidate_actions_v3()
    truths = load_evaluation_truths_v3()
    report = score_blinded_v3(tasks, ["ESCALATE"] * len(tasks), truths)
    assert report["effective_n"] == 56
