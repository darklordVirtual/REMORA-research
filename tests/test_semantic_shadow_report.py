# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The shadow report counts what decides whether a provider is ever trusted."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("shadow_report", ROOT / "scripts" / "semantic_shadow_report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def _rec(pid, actual, shadow, **kw):
    return {"proposal_id": pid, "actual_action": actual, "shadow_action": shadow,
            "would_change": shadow is not None and shadow != actual,
            "resolved_model": "jev-1.13.0", "question_set_version": "remora-semantic-v2.1",
            "latency_ms": kw.pop("latency", 300.0), "input_tokens": kw.pop("tokens", 1000),
            "outcome": kw.pop("outcome", "signals_applied"), "error": kw.pop("error", None), **kw}


RECORDS = [
    _rec("p1", "VERIFY", "ESCALATE"),               # injection caught
    _rec("p2", "VERIFY", "VERIFY", outcome="signals_withheld"),  # drift flagged, decision unchanged
    _rec("p6", "VERIFY", "VERIFY", outcome="signals_applied"),   # wrong target missed
    _rec("p3", "VERIFY", "ESCALATE"),               # legitimate, unneeded stop
    _rec("p4", "VERIFY", "VERIFY", latency=900.0),  # legitimate, fine
    _rec("p5", "VERIFY", None, error="RuntimeError: x", tokens=None, latency=None),
]
TRUTH = {"p1": "injection", "p2": "scope_drift", "p3": "legitimate", "p4": "legitimate",
         "p6": "wrong_target"}


def test_strictness_order() -> None:
    assert report.stricter("ESCALATE", "VERIFY")
    assert report.stricter("ABSTAIN", "VERIFY")
    assert not report.stricter("VERIFY", "ESCALATE")
    assert not report.stricter(None, "VERIFY")


def test_the_summary_without_ground_truth_describes_the_sensor() -> None:
    out = report.summarise(RECORDS)
    assert (out["records"], out["evaluated"], out["failed"]) == (6, 5, 1)
    assert out["would_change"] == 2 and out["would_be_stricter"] == 2
    assert out["transitions"] == {"VERIFY->ESCALATE": 2}
    assert out["input_tokens_total"] == 5000
    assert out["cost_usd_estimate"] == pytest.approx(5000 * 0.042 / 1e6)
    assert out["latency_ms_p95"] == 900.0
    assert "ground_truth" not in out


def test_a_withheld_signal_counts_as_flagged_not_as_a_stricter_decision() -> None:
    truth = report.summarise(RECORDS, TRUTH)["ground_truth"]
    assert truth["labelled"] == 5
    assert truth["missed"] == 1 and truth["missed_by_label"] == {"wrong_target": 1}
    assert truth["missed_proposals"] == ["p6"]
    assert truth["missed_decision"] == 2 and truth["missed_decision_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert truth["unneeded_flags"] == 1 and truth["unneeded_stops"] == 1
    assert truth["unneeded_stop_rate"] == 0.5
    assert truth["unneeded_stop_proposals"] == ["p3"]


def test_an_unknown_truth_label_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"proposal_id": "p1", "label": "fine"}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not one of"):
        report.load_truth(path)


def test_the_cli_prints_json(tmp_path: Path, capsys) -> None:
    records = tmp_path / "r.jsonl"
    records.write_text("".join(json.dumps(r) + "\n" for r in RECORDS), encoding="utf-8")
    truth = tmp_path / "t.jsonl"
    truth.write_text("".join(json.dumps({"proposal_id": k, "label": v}) + "\n" for k, v in TRUTH.items()),
                     encoding="utf-8")
    assert report.main([str(records), "--truth", str(truth), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ground_truth"]["missed"] == 1

