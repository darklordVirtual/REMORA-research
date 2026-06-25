from __future__ import annotations

import pytest

from remora.toolcall.benchmark import load_benchmark
from remora.toolcall.schema import VALID_ACTIONS, VALID_DOMAINS, VALID_SEVERITIES


@pytest.fixture(scope="module")
def benchmark():
    return load_benchmark()


def test_dataset_has_252_tasks(benchmark):
    assert len(benchmark) == 252


def test_each_domain_has_36_tasks(benchmark):
    for domain in VALID_DOMAINS:
        assert sum(1 for t in benchmark if t.domain == domain) == 36


def test_all_domains_present(benchmark):
    assert {t.domain for t in benchmark} == set(VALID_DOMAINS)


def test_all_four_actions_present(benchmark):
    assert {t.ground_truth_action for t in benchmark} == set(VALID_ACTIONS)


def test_no_duplicate_task_ids(benchmark):
    ids = [t.task_id for t in benchmark]
    assert len(ids) == len(set(ids))


def test_unsafe_cases_present(benchmark):
    assert any(t.is_unsafe_if_executed for t in benchmark)


def test_critical_risk_cases_present(benchmark):
    assert any(t.severity == "critical" for t in benchmark)


def test_escalate_tasks_have_unsafe_true_or_high_risk(benchmark):
    for task in benchmark:
        if task.ground_truth_action == "ESCALATE":
            assert task.is_unsafe_if_executed or task.severity in {"high", "critical"}


def test_adversarial_or_security_tasks_present(benchmark):
    assert sum(1 for t in benchmark if "security" in t.tags or "critical" in t.tags) >= 5


def test_schema_all_fields_present(benchmark):
    required_fields = [
        "task_id",
        "domain",
        "user_request",
        "proposed_tool_name",
        "proposed_tool_args",
        "context",
        "ground_truth_action",
        "is_unsafe_if_executed",
        "is_useful_if_executed",
        "expected_failure_mode",
        "explanation",
        "severity",
        "tags",
    ]
    for task in benchmark:
        for field in required_fields:
            assert hasattr(task, field)


def test_all_required_strings_non_empty(benchmark):
    for task in benchmark:
        assert task.task_id
        assert task.user_request
        assert task.proposed_tool_name
        assert task.explanation


def test_all_risk_levels_valid(benchmark):
    for task in benchmark:
        assert task.severity in VALID_SEVERITIES


def test_all_actions_valid(benchmark):
    for task in benchmark:
        assert task.ground_truth_action in VALID_ACTIONS


def test_all_domains_valid(benchmark):
    for task in benchmark:
        assert task.domain in VALID_DOMAINS


def test_validate_passes_for_all_tasks(benchmark):
    for task in benchmark:
        task.validate()
