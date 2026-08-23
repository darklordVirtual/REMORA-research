# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Which tool sets a gateway deployment serves, and what it declares.

The property worth pinning: a set is only offered when it can actually work.
An agent cannot tell "refused" from "broken", and it should never have to.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GITHUB_VARS = {"REMORA_GITHUB_TOKEN": "t",
               "REMORA_GITHUB_REPOS": "owner/repo"}
GRAPH_VARS = {"REMORA_KG_TENANT": "acme"}
ALL_VARS = {**GITHUB_VARS, **GRAPH_VARS}


def _load(monkeypatch, env: dict[str, str]):
    for name in (*ALL_VARS, "REMORA_GATEWAY_TOOL_SETS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    from deploy.gateway import bundle, registry
    return importlib.reload(registry), importlib.reload(bundle)


def test_a_set_is_offered_only_when_it_can_work(monkeypatch):
    registry, _ = _load(monkeypatch, GITHUB_VARS)
    assert registry.enabled_sets() == ("github",)
    assert not any(n.startswith("kg_") for n in registry.tool_names())


def test_both_sets_when_both_are_configured(monkeypatch):
    registry, _ = _load(monkeypatch, ALL_VARS)
    assert set(registry.enabled_sets()) == {"github", "graph"}
    names = registry.tool_names()
    assert any(n.startswith("gh_") for n in names)
    assert any(n.startswith("kg_") for n in names)


def test_nothing_is_offered_without_configuration(monkeypatch):
    registry, _ = _load(monkeypatch, {})
    assert registry.enabled_sets() == ()
    assert registry.tool_names() == ()


def test_an_explicit_selection_overrides_detection(monkeypatch):
    registry, _ = _load(monkeypatch, {**ALL_VARS,
                                      "REMORA_GATEWAY_TOOL_SETS": "github"})
    assert registry.enabled_sets() == ("github",)


def test_a_misspelled_set_is_a_startup_failure(monkeypatch):
    """Fewer tools than the operator thinks is worse than a loud failure."""
    registry, _ = _load(monkeypatch, {**ALL_VARS,
                                      "REMORA_GATEWAY_TOOL_SETS": "githbu"})
    with pytest.raises(RuntimeError) as exc:
        registry.enabled_sets()
    assert "githbu" in str(exc.value)


def test_every_offered_tool_is_declared(monkeypatch):
    """A callable with no declaration would be assessed on nothing."""
    registry, bundle = _load(monkeypatch, ALL_VARS)
    declared = bundle.build_semantic_bundle().registry.signatures
    for name in registry.tool_names():
        assert name in declared, f"{name} is offered but not declared"


def test_nothing_is_declared_that_is_not_offered(monkeypatch):
    """The reverse: a declaration with no callable is a phantom tool."""
    registry, bundle = _load(monkeypatch, GITHUB_VARS)
    declared = set(bundle.build_semantic_bundle().registry.signatures)
    assert declared == set(registry.tool_names())


def test_graph_writes_are_declared_mutating(monkeypatch):
    _, bundle = _load(monkeypatch, ALL_VARS)
    contracts = bundle.build_semantic_bundle().contracts.contracts
    assert contracts["kg_assert_fact"].mutation is True
    assert contracts["kg_retract_fact"].mutation is True
    assert contracts["kg_query_facts"].mutation is False


def test_asserting_a_fact_is_a_create_not_an_update(monkeypatch):
    """The fact did not exist before, and readers downstream inherit it."""
    _, bundle = _load(monkeypatch, ALL_VARS)
    contracts = bundle.build_semantic_bundle().contracts.contracts
    assert contracts["kg_assert_fact"].effect == "create"


def test_a_github_reference_resolves_through_github(monkeypatch):
    _, bundle = _load(monkeypatch, ALL_VARS)
    from deploy.gateway import gh_bundle, kg_intent

    seen: list[str] = []
    monkeypatch.setattr(gh_bundle, "resolve_intent",
                        lambda r: seen.append(("gh", r)) or "GH")
    monkeypatch.setattr(kg_intent, "resolve_intent",
                        lambda r: seen.append(("kg", r)) or "KG")

    assert bundle.resolve_intent("owner/repo#7") == "GH"
    assert seen == [("gh", "owner/repo#7")]


def test_a_task_subject_falls_through_to_the_graph(monkeypatch):
    """GitHub is tried first, so the caller need not know which resolver runs."""
    _, bundle = _load(monkeypatch, ALL_VARS)
    from deploy.gateway import gh_bundle, kg_intent

    monkeypatch.setattr(gh_bundle, "resolve_intent", lambda r: None)
    monkeypatch.setattr(kg_intent, "resolve_intent", lambda r: "KG")

    assert bundle.resolve_intent("task:onboard-acme") == "KG"


def test_a_graph_only_deployment_never_calls_github(monkeypatch):
    _, bundle = _load(monkeypatch, GRAPH_VARS)
    from deploy.gateway import gh_bundle, kg_intent

    def explode(_r):  # pragma: no cover - reached only on failure
        raise AssertionError("GitHub was consulted without the set being live")

    monkeypatch.setattr(gh_bundle, "resolve_intent", explode)
    monkeypatch.setattr(kg_intent, "resolve_intent", lambda r: "KG")
    assert bundle.resolve_intent("task:x") == "KG"


def test_no_sets_means_no_authority(monkeypatch):
    """Unresolvable authority is UNKNOWN, which is review, not permission."""
    _, bundle = _load(monkeypatch, {})
    assert bundle.resolve_intent("anything") is None


def test_an_under_specified_intent_is_recorded_not_hidden(monkeypatch, caplog):
    """A task with no spans cannot contradict anything.

    Measured against the deployed gateway on 2026-08-23: a task carrying only
    task_text, operation and resource_type produced identical decisions for
    the right task, the wrong task and no task at all. Adding source_spans and
    action_spans made a write under a read-only task come back as ESCALATE
    with expected_effect_contradicted.

    It is a warning rather than a refusal: an under-specified task is weaker,
    not invalid, and refusing it would remove the human review it still gets.
    """
    import logging

    from deploy.gateway import kg_intent, kg_registry

    monkeypatch.setattr(kg_registry, "read_intent", lambda s: {
        "task_text": "Do the thing.", "operation": "read",
    })
    with caplog.at_level(logging.WARNING):
        resolved = kg_intent.resolve_intent("task:thin")
    assert resolved is not None, "a thin task still resolves"
    assert any("cannot contradict" in r.message for r in caplog.records)


def test_a_task_with_spans_is_not_warned_about(monkeypatch, caplog):
    import logging

    from deploy.gateway import kg_intent, kg_registry

    monkeypatch.setattr(kg_registry, "read_intent", lambda s: {
        "task_text": "Read the business graph.", "operation": "read",
        "source_spans": ["business graph"], "action_spans": ["read"],
    })
    with caplog.at_level(logging.WARNING):
        kg_intent.resolve_intent("task:rich")
    assert not [r for r in caplog.records if "cannot contradict" in r.message]
