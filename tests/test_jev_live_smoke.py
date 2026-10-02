# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The live smoke generator, run offline with the deterministic provider.

The live round needs a key and the network; its record shape and its
safety check do not. This drives ``run_round`` with each scenario's offline
answers so the artifact layout and the ACCEPT check are pinned without a
call to TypeSafe.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from remora.decision_providers import DeterministicDecisionProvider
from remora.decision_providers.questions import QUESTION_SET_VERSION

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load(ROOT / "experiments" / "jev_live_smoke.py")
demo = _load(ROOT / "examples" / "jev_decision_provider_demo.py")


def _offline(scenario):
    return DeterministicDecisionProvider(
        scenario["offline_answers"], question_set_version=QUESTION_SET_VERSION
    )


def test_every_scenario_is_recorded_once_per_repeat() -> None:
    record = smoke.run_round(_offline, demo.SCENARIOS, demo.THRESHOLDS, repeats=2)
    assert record["summary"]["runs"] == 2 * len(demo.SCENARIOS)
    assert set(record["summary"]["by_scenario"]) == set(demo.SCENARIOS)
    assert record["thresholds_status"].startswith("illustrative")


def test_a_run_carries_answers_with_legend_and_both_decisions() -> None:
    record = smoke.run_round(_offline, demo.SCENARIOS, demo.THRESHOLDS, repeats=1)
    run = next(r for r in record["runs"] if r["scenario"] == "injection")
    assert run["decision_without_provider"] == "VERIFY"
    assert run["decision_with_provider"] == "ESCALATE"
    assert run["answers"]["possible_injection"]["value"] == 0.93
    assert run["state_hash"] and run["response_hash"]


def test_no_offline_run_reaches_accept() -> None:
    record = smoke.run_round(_offline, demo.SCENARIOS, demo.THRESHOLDS, repeats=1)
    assert record["summary"]["accept_reached"] == 0


def test_the_live_round_refuses_without_a_key(monkeypatch, capsys) -> None:
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    try:
        smoke.main(["--repeats", "1"])
    except SystemExit as exc:
        assert "JEV_API_KEY" in str(exc.code)
    else:  # pragma: no cover - the refusal is the point
        raise AssertionError("the live round ran without a key")
