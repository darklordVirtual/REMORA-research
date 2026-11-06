# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The sweep-measured gate: a sweep that ran no mutant fails by name.

The scheduled sweep of 2026-11-02 failed at collection and measured nothing;
``mutmut run`` exited non-zero, which is necessary and not sufficient, because
nothing named the missing module and nothing told "measured nothing" apart from
"found new survivors". These tests pin what the gate reads from the sweep log
and the sandbox it leaves behind.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_mutation_sweep_measured.py"

PROGRESS = "⠹ 6077/6077  🎉 5888 🫥 0  ⏰ 5  🤔 0  🙁 184  🔇 0  🧙 0\n"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("sweep_measured", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sandbox(tmp_path: Path, *, stats: bool = True) -> Path:
    sandbox = tmp_path / "mutants"
    sandbox.mkdir()
    if stats:
        (sandbox / "mutmut-stats.json").write_text("{}", encoding="utf-8")
    return sandbox


def test_a_sweep_that_ran_to_the_end_passes(gate, tmp_path, capsys) -> None:
    log = tmp_path / "run.log"
    log.write_text("Running mutation testing\n" + PROGRESS + "3.99 mutations/second\n")
    assert gate.main([str(log), "--sandbox", str(_sandbox(tmp_path))]) == 0
    assert "executed 6077 mutants" in capsys.readouterr().out


def test_a_collection_error_names_the_module_the_sandbox_could_not_collect(
        gate, tmp_path, capsys) -> None:
    log = tmp_path / "run.log"
    log.write_text(
        "⠧ Running stats\n"
        "==================================== ERRORS ====================================\n"
        "__________ ERROR collecting tests/test_invocation_evidence_export.py ___________\n"
        "FileNotFoundError: [Errno 2] No such file or directory: "
        "'.../mutants/integrations/invocation-evidence/fixtures/jsonrpc-id-vectors.json'\n"
        "1 error in 13.23s\n"
        "failed to collect stats. runner returned 1\n")
    assert gate.main([str(log), "--sandbox", str(_sandbox(tmp_path, stats=False))]) == 1
    err = capsys.readouterr().err
    assert "could not collect tests/test_invocation_evidence_export.py" in err
    assert "also_copy" in err
    assert "the stats phase failed" in err
    assert "no mutant was executed" in err


def test_a_clean_test_failure_is_measured_nothing(gate, tmp_path, capsys) -> None:
    log = tmp_path / "run.log"
    log.write_text("⠸ Running clean tests\nFAILED tests/x.py::test_y\n"
                   "1 failed, 2138 passed in 85.37s\nFailed to run clean test\n")
    assert gate.main([str(log), "--sandbox", str(_sandbox(tmp_path))]) == 1
    assert "clean-test phase failed" in capsys.readouterr().err


def test_a_missing_stats_file_fails_even_with_a_quiet_log(gate, tmp_path, capsys) -> None:
    log = tmp_path / "run.log"
    log.write_text("Running mutation testing\n" + PROGRESS)
    assert gate.main([str(log), "--sandbox", str(_sandbox(tmp_path, stats=False))]) == 1
    assert "mutmut-stats.json is missing" in capsys.readouterr().err


def test_a_sweep_that_executed_no_mutant_fails(gate, tmp_path, capsys) -> None:
    log = tmp_path / "run.log"
    log.write_text("Running mutation testing\n⠹ 0/6077  🎉 0 🫥 0  ⏰ 0  🤔 0  🙁 0  🔇 0  🧙 0\n")
    assert gate.main([str(log), "--sandbox", str(_sandbox(tmp_path))]) == 1
    assert "no mutant was executed" in capsys.readouterr().err


def test_a_missing_log_is_a_sweep_that_did_not_run(gate, tmp_path, capsys) -> None:
    assert gate.main([str(tmp_path / "absent.log")]) == 1
    assert "did not run" in capsys.readouterr().err


def test_the_workflow_runs_the_gate_and_keeps_the_log() -> None:
    workflow = (ROOT / ".github" / "workflows" / "mutation.yml").read_text(encoding="utf-8")
    assert "mutmut run 2>&1 | tee mutation-run.log" in workflow
    assert "scripts/check_mutation_sweep_measured.py mutation-run.log" in workflow
    assert "mutation-run.log" in workflow.split("Upload results", 1)[1]
    assert "issues: write" in workflow
