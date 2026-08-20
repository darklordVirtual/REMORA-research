# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The coverage gate must fail on a regression and explain its own blind spot.

A floor that only ever prints OK is decoration. These tests drive the checker
with synthetic reports so the refusal path is exercised, and pin the two
properties the gate exists to provide: per-file floors for the enforcement
files (so a package average cannot absorb a regression in the two files that
enforce), and an explicit statement that the Postgres adapters are not measured
by this run (so the package number is not read as "the untested fraction").
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_coverage_thresholds.py"


def _load():
    spec = importlib.util.spec_from_file_location("cov_thresholds", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load()


def _report(files: dict[str, float], overall: float = 99.0) -> dict:
    """A coverage report where each named file has the given percentage."""
    return {
        "totals": {"percent_covered": overall},
        "files": {
            path: {
                "summary": {
                    "covered_lines": int(pct),
                    "num_statements": 100,
                    "covered_branches": 0,
                    "num_branches": 0,
                },
                "missing_lines": [],
            }
            for path, pct in files.items()
        },
    }


def _run(gate, tmp_path: Path, report: dict) -> int:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return gate.main(["check_coverage_thresholds.py", str(path)])


def _all_at(gate, pct: float) -> dict[str, float]:
    """Every configured package and file sitting at the same percentage."""
    files = {f"{prefix}/_m.py": pct for prefix in gate.THRESHOLDS if "." not in Path(prefix).name}
    files.update({prefix: pct for prefix in gate.THRESHOLDS if prefix.endswith(".py")})
    files.update({path: pct for path in gate.FILE_THRESHOLDS})
    return files


def test_every_enforcement_source_file_has_a_floor(gate) -> None:
    """No file in the package may sit outside the per-file gate unnoticed."""
    on_disk = {
        f"remora/enforcement/{p.name}"
        for p in (ROOT / "remora" / "enforcement").glob("*.py")
        if p.name != "__init__.py"
    }
    assert on_disk == set(gate.FILE_THRESHOLDS), (
        "add or remove a FILE_THRESHOLDS entry when an enforcement module is "
        "added or deleted"
    )


def test_file_floors_do_not_exceed_the_package_floor_silently(gate) -> None:
    """The two Postgres-carrying files are the reason the package floor is low."""
    assert gate.FILE_THRESHOLDS["remora/enforcement/gate.py"] < gate.THRESHOLDS["remora/enforcement"]
    assert gate.FILE_THRESHOLDS["remora/enforcement/outbox.py"] < gate.THRESHOLDS["remora/enforcement"]
    # The fully in-process modules are held to a higher bar than the package.
    for path in ("lease.py", "token.py"):
        assert gate.FILE_THRESHOLDS[f"remora/enforcement/{path}"] > gate.THRESHOLDS["remora/enforcement"]


def test_a_report_meeting_every_floor_passes(gate, tmp_path) -> None:
    assert _run(gate, tmp_path, _report(_all_at(gate, 99.0))) == 0


def test_a_single_file_regression_fails_even_when_the_package_would_pass(
    gate, tmp_path, capsys
) -> None:
    """The point of the per-file floor: averages must not absorb a drop."""
    files = _all_at(gate, 99.0)
    files["remora/enforcement/lease.py"] = 10.0
    # The package still averages well above its floor across five files.
    assert _run(gate, tmp_path, _report(files)) == 1
    assert "lease.py" in capsys.readouterr().err


def test_a_package_regression_fails(gate, tmp_path, capsys) -> None:
    files = _all_at(gate, 99.0)
    for path in list(files):
        if path.startswith("remora/policy"):
            files[path] = 1.0
    assert _run(gate, tmp_path, _report(files)) == 1
    assert "remora/policy" in capsys.readouterr().err


def test_a_global_regression_fails(gate, tmp_path, capsys) -> None:
    assert _run(gate, tmp_path, _report(_all_at(gate, 99.0), overall=1.0)) == 1
    assert "TOTAL" in capsys.readouterr().err


def test_an_unmeasured_file_is_a_failure_not_a_pass(gate, tmp_path, capsys) -> None:
    """Deleting a file from the source list must not read as full coverage."""
    files = _all_at(gate, 99.0)
    del files["remora/enforcement/outbox.py"]
    assert _run(gate, tmp_path, _report(files)) == 1
    assert "nothing measured" in capsys.readouterr().err


def test_the_run_states_what_it_does_not_measure(gate, tmp_path, capsys) -> None:
    """83% must not be readable as '17% of the enforcement path is untested'."""
    _run(gate, tmp_path, _report(_all_at(gate, 99.0)))
    out = capsys.readouterr().out
    assert "Postgres" in out
    assert "separate job" in out


def test_the_docstring_records_where_the_postgres_paths_are_covered(gate) -> None:
    assert "Postgres" in (gate.__doc__ or "") or "Postgres" in SCRIPT.read_text(encoding="utf-8")
