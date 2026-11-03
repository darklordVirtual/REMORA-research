# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The read-autonomy replay's summary counts what the rows say; the artifact agrees with itself."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "control_eval" / "dev_reads_replay_v1.json"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_control_eval_reads_replay", ROOT / "scripts" / "run_control_eval_reads_replay.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _row(action, executed, grounded=True, intent=False, **sig):
    base = dict(suite="s", user_task="t", function="f", declared_action_type=action, declared_risk_tier="low",
                argument_count=1, arguments_grounded=grounded, ungrounded_arguments=[] if grounded else ["x"],
                intent_resolved=intent, tool_matches_goal=None, expected_effect_matches=None,
                argument_values_supported=None, argument_values_grounded=None, prior_outputs=0,
                executed=executed)
    base.update(sig)
    return base


def test_summary_counts_reads_writes_grounding_and_arms():
    m = _module()
    calls = [_row("read", {"A_none": True, "E_IFC": True}),
             _row("read", {"A_none": True, "E_IFC": False}, grounded=False),
             _row("read", {"A_none": True, "E_IFC": True}, grounded=None,
                  tool_matches_goal=True, expected_effect_matches=True,
                  argument_values_supported=True, argument_values_grounded=True),
             _row("write", {"A_none": True, "E_IFC": False})]
    tasks = [{"reads_only": True, "reads_only_and_grounded": True, "utility": {"A_none": True, "E_IFC": True}},
             {"reads_only": False, "reads_only_and_grounded": False, "utility": {"A_none": True, "E_IFC": False}}]
    s = m.summarize(calls, tasks)
    assert (s["benign_calls"], s["declared_reads"], s["declared_writes"], s["undeclared_tools"]) == (4, 3, 1, 0)
    assert (s["reads_arguments_grounded"], s["reads_arguments_ungrounded"], s["reads_no_judgeable_argument"]) == (1, 1, 1)
    assert s["reads_all_four_grounding_signals_true"] == 1
    assert s["reads_executed_by_arm"]["E_IFC"] == 2 and s["writes_executed_by_arm"]["E_IFC"] == 0
    assert s["tasks_reads_only"] == 1 and s["tasks_completed_by_arm"]["E_IFC"] == 1
    assert s["reads_ungrounded_argument_names"] == {"x": 1}


def test_committed_artifact_summary_matches_its_rows():
    m = _module()
    d = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert d["model_calls"] == 0 and d["status"] == "development_replay_read_autonomy"
    assert d["holdout_suite"] not in d["dev_user_tasks"]
    recomputed = m.summarize(d["calls"], d["tasks"])
    assert recomputed == d["summary"]
    # the headline this artifact is cited for
    assert d["summary"]["declared_reads"] == 52 and d["summary"]["benign_calls"] == 66
    assert d["summary"]["reads_executed_by_arm"]["E_IFC"] == 50
    assert d["summary"]["reads_all_four_grounding_signals_true"] == 0
