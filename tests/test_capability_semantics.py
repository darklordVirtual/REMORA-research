# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The capability-semantics gate: claimed status vs demonstrable wiring.

Issue #84 residual 2. The gate's value is what it REFUSES: a register
entry may not claim WIRED_API_PATH while citing an implementation the API
surfaces cannot reach, may not claim PERSISTED_ATOMIC over code with no
durable-backend path, may not claim a reference path with no reference
flow, and may not claim anything with no tests. Each refusal is pinned
with a synthetic entry; the committed register must pass end-to-end.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_capability_semantics.py"

#: Reachable from the API surfaces (the decision engine is the API's core).
REACHABLE_IMPL = "remora/policy/decision_engine.py"
#: A real module no server surface imports (research evaluation harness).
UNREACHABLE_IMPL = "remora/aromer/evals/learning_ablation.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("capability_semantics", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cap(status: str, evidence: list[str]) -> dict:
    return {"id": "CAP-TEST", "status": status, "evidence": evidence}


def test_the_fixture_modules_have_the_reachability_they_claim(gate) -> None:
    """The synthetic entries below are only meaningful while these two
    facts hold; if either module moves, this test names the maintenance."""
    assert gate._FILE_TO_MOD[REACHABLE_IMPL] in gate._REACHED
    assert gate._FILE_TO_MOD[UNREACHABLE_IMPL] not in gate._REACHED


def test_a_wired_api_claim_over_unreachable_code_is_an_over_claim(gate) -> None:
    problems = gate.check_capability(_cap("WIRED_API_PATH", [
        UNREACHABLE_IMPL, "servers/api.py", "tests/test_engine.py"]))
    assert any("cannot demonstrate" in p for p in problems)


def test_a_wired_api_claim_without_a_server_module_fails(gate) -> None:
    problems = gate.check_capability(_cap("WIRED_API_PATH", [
        REACHABLE_IMPL, "tests/test_engine.py"]))
    assert any("without any server module" in p for p in problems)


def test_a_demonstrably_wired_api_claim_passes(gate) -> None:
    assert gate.check_capability(_cap("WIRED_API_PATH", [
        REACHABLE_IMPL, "servers/api.py", "tests/test_engine.py"])) == []


def test_persisted_atomic_requires_a_durable_backend_path(gate) -> None:
    problems = gate.check_capability(_cap("PERSISTED_ATOMIC", [
        REACHABLE_IMPL, "servers/api.py", "tests/test_engine.py"]))
    assert any("durable-backend" in p for p in problems)


def test_persisted_atomic_over_durable_code_passes(gate) -> None:
    assert gate.check_capability(_cap("PERSISTED_ATOMIC", [
        "remora/governance/tenant_chain.py", "servers/execution_api.py",
        "tests/test_execution_api.py"])) == []


def test_a_reference_path_claim_needs_a_reference_flow(gate) -> None:
    problems = gate.check_capability(_cap("WIRED_REFERENCE_PATH", [
        UNREACHABLE_IMPL, "tests/test_engine.py"]))
    assert any("reference flow" in p for p in problems)


def test_no_level_is_exempt_from_tests(gate) -> None:
    problems = gate.check_capability(_cap("IMPLEMENTED_LIBRARY", [
        UNREACHABLE_IMPL]))
    assert any("no test evidence" in p for p in problems)


def test_an_unknown_status_is_refused_not_skipped(gate) -> None:
    assert gate.check_capability(_cap("TOTALLY_WIRED", ["tests/t.py"]))


def test_the_committed_register_passes_end_to_end(gate, capsys) -> None:
    assert gate.main() == 0
    assert "[PASS]" in capsys.readouterr().out
