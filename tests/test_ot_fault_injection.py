# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's fault-injection runner and its plant evidence checker.

The runner itself drives a live Docker stack and is exercised by running it
(``artifacts/pilot-pack/runs/fault-injection-*``). What is tested here is
what decides the evidence without a stack: the configuration fingerprint,
the measurements, and ``ot_registry.check_limit_evidence``, which a reviewer's
resolution of an unknown outcome is checked against.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parents[1] / "deploy" / "ot-pilot"


def _load(name: str):
    sys.path.insert(0, str(PILOT))
    try:
        spec = importlib.util.spec_from_file_location(f"pilot_{name}", PILOT / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(PILOT))


runner = _load("run_fault_injection")
registry = _load("ot_registry")


# ── Frozen configuration ────────────────────────────────────────────────────

def test_every_config_file_exists_and_is_digested():
    root = Path(__file__).resolve().parents[1]
    digests = runner.file_digests(root)
    assert set(digests) == set(runner.CONFIG_FILES)
    assert all(isinstance(d, str) and len(d) == 64 for d in digests.values()), digests


def test_a_missing_file_is_recorded_as_none(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    assert runner.file_digests(tmp_path, ("a.txt", "b.txt"))["b.txt"] is None


def test_the_fingerprint_moves_with_the_deployment_and_not_with_the_commit():
    base = {"files": {"a": "1"}, "api_image_id": "sha256:i", "policy_hash": "p",
            "manifest_digest": None, "commit_sha": "c1"}
    same = dict(base, commit_sha="c2")
    assert runner.fingerprint_digest(base) == runner.fingerprint_digest(same)
    for key, value in (("files", {"a": "2"}), ("api_image_id", "sha256:j"),
                       ("policy_hash", "q"), ("manifest_digest", "m")):
        assert runner.fingerprint_digest(dict(base, **{key: value})) != runner.fingerprint_digest(base)


# ── Measurement ─────────────────────────────────────────────────────────────

def test_percentile_is_nearest_rank():
    values = [float(v) for v in range(1, 101)]
    assert runner.percentile(values, 50) == 50.0
    assert runner.percentile(values, 95) == 95.0
    assert runner.percentile([7.0], 95) == 7.0
    assert runner.percentile([], 50) is None


def test_operations_summary_counts_false_refusals_and_human_steps():
    results = [{"intended_writes": 1, "completed_writes": 1},
               {"intended_writes": 2, "completed_writes": 1},
               {"intended_writes": 0, "completed_writes": 0},
               {"intended_writes": 1}]
    summary = runner.operations_summary(results, ["approve by a", "approve by a", "stop"])
    assert summary["intended_writes"] == 4
    assert summary["completed_writes"] == 2
    assert summary["false_refusals"] == 2
    assert summary["completion_rate"] == 0.5
    assert summary["human_steps"] == 3
    assert summary["human_steps_by_kind"] == {"approve by a": 2, "stop": 1}


def test_an_extra_write_does_not_raise_the_completion_rate():
    summary = runner.operations_summary([{"intended_writes": 1, "completed_writes": 3}], [])
    assert (summary["completed_writes"], summary["completion_rate"]) == (1, 1.0)


def test_latency_summary_groups_by_route():
    summary = runner.latency_summary({"POST /v1/execution/execute": [10.0, 20.0, 30.0], "GET /x": []})
    assert list(summary) == ["POST /v1/execution/execute"]
    assert summary["POST /v1/execution/execute"]["calls"] == 3
    assert summary["POST /v1/execution/execute"]["max_ms"] == 30.0


def test_every_fault_states_what_it_expects():
    names = [f.name for f in runner.FAULTS]
    assert len(names) == len(set(names)) == 9
    assert all(f.expect for f in runner.FAULTS)
    # Revocation leaves the approver revoked, so it must run last.
    assert runner.FAULTS[-1].run is runner.f_approver_revoked_after_approval


# ── The plant evidence checker ──────────────────────────────────────────────

@pytest.fixture()
def plant(monkeypatch):
    monkeypatch.setattr(registry, "PLANT", {**registry.PLANT, "log": []})
    monkeypatch.setattr(registry, "PLANT_STARTED_AT", time.time() - 60)
    return registry.PLANT


def _operation(tool: str = "close_work_order", seconds_ago: float = 10.0) -> dict:
    return {"tool": tool, "at": time.time() - seconds_ago, "principal": "ot-agent"}


def _logged(plant, tool: str, seconds_ago: float, **fields) -> None:
    at = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    plant["log"].append({"at": at.isoformat(), "tool": tool, **fields})


def test_an_operation_the_plant_never_logged_did_not_execute(plant):
    verdict = registry.check_limit_evidence("ot-pilot", _operation(), "plant-log:close_work_order:WO-9999")
    assert verdict == {"executed": False, "source": "ot-plant-log"}


def test_a_logged_effect_after_the_reservation_executed(plant):
    _logged(plant, "close_work_order", seconds_ago=5, wo_id="WO-1201")
    verdict = registry.check_limit_evidence("ot-pilot", _operation(), "plant-log:close_work_order:WO-1201")
    assert verdict["executed"] is True


def test_an_effect_logged_before_the_reservation_is_not_this_operation(plant):
    _logged(plant, "close_work_order", seconds_ago=30, wo_id="WO-1201")
    verdict = registry.check_limit_evidence("ot-pilot", _operation(), "plant-log:close_work_order:WO-1201")
    assert verdict["executed"] is False


def test_another_resource_is_not_this_operation(plant):
    _logged(plant, "close_work_order", seconds_ago=5, wo_id="WO-1202")
    verdict = registry.check_limit_evidence("ot-pilot", _operation(), "plant-log:close_work_order:WO-1201")
    assert verdict["executed"] is False


@pytest.mark.parametrize("ref", ["WO-1201", "plant-log:close_work_order", "rail:close_work_order:WO-1",
                                 "plant-log:create_work_order:WO-1201"])
def test_a_reference_that_does_not_name_this_operation_raises(plant, ref):
    with pytest.raises(ValueError):
        registry.check_limit_evidence("ot-pilot", _operation(), ref)


def test_an_operation_older_than_the_plant_cannot_be_told(plant):
    with pytest.raises(LookupError):
        registry.check_limit_evidence("ot-pilot", _operation(seconds_ago=120),
                                      "plant-log:close_work_order:WO-9999")
