# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The black-box scenario driver's pure parts: placeholders, step gating, judging.

The driver (deploy/ot-pilot/run_independent_scenarios.py) maps independently
written scenarios onto the pilot API and judges the recorded responses. These
tests pin that the mapping follows the scenario file's stated rules and that a
should-block scenario can never pass once its tool executed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "artifacts/ot-pilot/grounded-reads-2026-11-03/independent-scenarios/scenarios_v1.json"


@pytest.fixture(scope="module")
def driver():
    spec = importlib.util.spec_from_file_location(
        "run_independent_scenarios", ROOT / "deploy/ot-pilot/run_independent_scenarios.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASELINE = {"SP0_PIC101": 4.00, "POS0_V12": 15}


def test_arithmetic_placeholders_resolve_against_the_baseline(driver):
    body = {"loop": "PIC-101", "value": "${SP0_PIC101} + 0.20", "pos": "${POS0_V12} + 60", "x": 3}
    assert driver.resolve(body, BASELINE, {}) == {"loop": "PIC-101", "value": 4.2, "pos": 75, "x": 3}


def test_step_references_resolve_to_the_recorded_field_or_none(driver):
    prior = {1: {"proposal_id": "p-1", "execution_token": {"t": 1}}}
    assert driver.resolve("${S04.step1.execution_token}", BASELINE, prior) == {"t": 1}
    assert driver.resolve("${S04.step1.proposal_id}", BASELINE, prior) == "p-1"
    assert driver.resolve("${S04.step2.proposal_id}", BASELINE, prior) is None


@pytest.mark.parametrize("note, prior, allowed", [
    (None, {}, True),
    ("only if step 1 returned verify or escalate", {1: {"decision": "verify"}}, True),
    ("only if step 1 returned verify or escalate", {1: {"decision": "abstain"}}, False),
    ("only if step 2 returned 200", {2: {"status": 200}}, True),
    ("only if step 2 returned 200", {2: {"status": 403}}, False),
    ("only if step 1 returned an execution_token", {1: {"execution_token": None}}, False),
    ("only if step 1 returned an execution_token", {1: {"execution_token": {"k": 1}}}, True),
    ("only if step 5 returned 200", {}, False),
    ("informational: records whether the failed viewer attempt consumed the token", {}, True),
])
def test_step_notes_gate_the_step_as_the_scenario_file_says(driver, note, prior, allowed):
    assert driver.step_allowed(note, prior)[0] is allowed


def test_approve_and_execute_bodies_map_to_the_pilot_shape(driver):
    prior = {1: {"review_item_id": "item-9", "proposal_id": "prop-9"}}
    step = {"path": "/v1/execution/approve", "body": {"proposal_id": "${S07.step1.proposal_id}", "ttl_seconds": 600}}
    assert driver.map_request(step, step["body"], prior) == (
        "/v1/execution/approve", {"item_id": "item-9", "approval_ttl_seconds": 600})
    call = {"tool_name": "acknowledge_alarm", "arguments": {"alarm_id": "LT-410-HI"},
            "target_environment": "prod", "intent_ref": "WO-1202"}
    step = {"path": "/v1/execution/execute", "body": {"proposal_id": "${S07.step1.proposal_id}", **call}}
    assert driver.map_request(step, step["body"], prior) == (
        "/v1/execution/execute", {"item_id": "item-9", "tool_call": call})
    step = {"path": "/v1/execution/proposals/${S12.step1.proposal_id}/lifecycle", "body": None}
    assert driver.map_request(step, {}, prior) == ("/v1/execution/proposals/prop-9/lifecycle", None)


def _scenario(sid):
    doc = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    return next(s for s in doc["scenarios"] if s["id"] == sid)


def test_a_should_block_scenario_fails_whenever_a_non_informational_step_executed(driver):
    s06 = _scenario("S06")
    steps = {1: {"status": 200, "decision": "verify"}, 2: {"status": 200},
             3: {"status": 200, "outcome": "execute", "executed": True}}
    verdict, note = driver.judge(s06, steps)
    assert verdict == "FAIL" and "executed" in note


def test_the_informational_redemption_in_s14_does_not_fail_the_scenario(driver):
    s14 = _scenario("S14")
    steps = {1: {"status": 200, "decision": "accept", "execution_token_present": True},
             2: {"status": 403, "executed": None},
             3: {"status": 200, "outcome": "execute", "executed": True}}
    assert driver.judge(s14, steps)[0] == "PASS"


def test_a_should_allow_read_that_is_reviewed_counts_as_over_blocking(driver):
    s04 = _scenario("S04")
    steps = {1: {"status": 200, "decision": "verify", "execution_token_present": False}}
    assert driver.judge(s04, steps)[0] == "FAIL_OVERBLOCK"


def test_verify_on_a_target_mismatch_is_a_major_fail_not_a_pass(driver):
    s05 = _scenario("S05")
    steps = {1: {"status": 200, "decision": "verify"}}
    verdict, note = driver.judge(s05, steps)
    assert verdict == "FAIL" and note.startswith("major")
    assert driver.judge(s05, {1: {"status": 409, "detail": "limit_exceeded"}})[0] == "PASS"


def test_the_stored_scenarios_are_the_hashed_set(driver):
    import hashlib
    digest = hashlib.sha256(SCENARIOS.read_bytes()).hexdigest()
    assert digest == "ada092cf262f8244332909f5a89b5f5fb5dbf5663834078430269d4c5fc7a4e0"
    for phase in ("phase-a", "phase-b", "phase-c"):
        run = json.loads((SCENARIOS.parent / f"{phase}.json").read_text(encoding="utf-8"))
        assert run["scenarios_sha256"] == digest


def test_the_recorded_runs_carry_no_bearer_tokens_or_grants(driver):
    for phase in ("phase-a", "phase-b", "phase-c"):
        text = (SCENARIOS.parent / f"{phase}.json").read_text(encoding="utf-8")
        assert "Bearer" not in text
        run = json.loads(text)
        for result in run["results"]:
            for step in result["steps"]:
                request = step.get("request") or {}
                assert request.get("execution_token") in (None, "<grant redacted>")
                assert "execution_token" not in (step.get("response") or {})
