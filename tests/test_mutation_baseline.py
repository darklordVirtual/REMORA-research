# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The mutation-baseline gate: new survivors fail, progress never does.

The scheduled job's value is exactly the asymmetry these tests pin: a NEW
survivor is a test-strength regression and fails loudly; a killed baseline
entry is progress reported as a ratchet hint; a renamed function is
baseline maintenance, not a regression — mutant ids embed function names,
so one rename moves every id at once and must not read as twenty new
survivors plus twenty fixes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_mutation_baseline.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("mutation_baseline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _results(*pairs: tuple[str, str]) -> str:
    return "\n".join(f"    {mid}: {status}" for mid, status in pairs) + "\n"


@pytest.fixture()
def baselined(gate, tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.txt"
    monkeypatch.setattr(gate, "BASELINE", baseline)

    def write(*ids: str) -> None:
        baseline.write_text("\n".join(sorted(ids)) + "\n", encoding="utf-8")

    return write


def _run(gate, tmp_path, text: str, *argv: str) -> int:
    f = tmp_path / "results.txt"
    f.write_text(text, encoding="utf-8")
    return gate.main(["check", *argv, str(f)])


def test_a_new_survivor_fails(gate, tmp_path, baselined, capsys) -> None:
    baselined("m.f__mutmut_1")
    rc = _run(gate, tmp_path, _results(
        ("m.f__mutmut_1", "survived"),
        ("m.f__mutmut_2", "survived"),
    ))
    assert rc == 1
    assert "m.f__mutmut_2" in capsys.readouterr().err


def test_the_exact_baseline_passes(gate, tmp_path, baselined) -> None:
    baselined("m.f__mutmut_1", "m.f__mutmut_2")
    rc = _run(gate, tmp_path, _results(
        ("m.f__mutmut_1", "survived"),
        ("m.f__mutmut_2", "survived"),
        ("m.f__mutmut_3", "killed"),
    ))
    assert rc == 0


def test_progress_is_a_hint_never_a_failure(gate, tmp_path, baselined, capsys) -> None:
    """Killing a baseline survivor must not break the job — otherwise
    improving the tests punishes the improver."""
    baselined("m.f__mutmut_1", "m.f__mutmut_2")
    rc = _run(gate, tmp_path, _results(
        ("m.f__mutmut_1", "survived"),
        ("m.f__mutmut_2", "killed"),
    ))
    assert rc == 0
    assert "ratchet down" in capsys.readouterr().out


def test_a_renamed_function_is_maintenance_not_regression(
    gate, tmp_path, baselined, capsys
) -> None:
    """The whole id-set of the old function vanished: every result mutant
    belongs to other functions, so the stale entries are classified as
    maintenance rather than counted as fixes."""
    baselined("m.old_name__mutmut_1", "m.old_name__mutmut_2")
    rc = _run(gate, tmp_path, _results(
        ("m.new_name__mutmut_1", "killed"),
    ))
    assert rc == 0
    out = capsys.readouterr().out
    assert "rename or removal" in out


def test_an_empty_sweep_never_passes_as_clean(gate, tmp_path, baselined) -> None:
    """A results file with no parseable mutants means the sweep did not run;
    passing it would make an infrastructure failure look like perfection."""
    baselined("m.f__mutmut_1")
    rc = _run(gate, tmp_path, "no mutants here\n")
    assert rc == 1


def test_update_writes_the_sorted_survivor_set(gate, tmp_path, baselined) -> None:
    rc = _run(gate, tmp_path, _results(
        ("m.b__mutmut_2", "survived"),
        ("m.a__mutmut_1", "survived"),
        ("m.c__mutmut_3", "killed"),
    ), "--update")
    assert rc == 0
    assert gate.BASELINE.read_text(encoding="utf-8") == (
        "m.a__mutmut_1\nm.b__mutmut_2\n"
    )


def test_the_committed_baseline_exists_and_is_sorted() -> None:
    baseline = ROOT / "docs" / "assurance" / "mutation_baseline_v1.txt"
    assert baseline.exists(), "the scheduled job requires the baseline file"
    lines = [ln for ln in baseline.read_text(encoding="utf-8").splitlines() if ln]
    assert lines == sorted(lines)
    assert all("__mutmut_" in ln for ln in lines)
