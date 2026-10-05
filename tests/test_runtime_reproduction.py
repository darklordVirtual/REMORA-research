"""An outside operator can inspect a fresh local runtime run without fixture replay."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from remora.toolcall import surface_evaluation
from scripts.reproduce_runtime_surface import run
from scripts.reproduce_runtime_surface import _git_output


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_reproduction_emits_verifiable_bounded_record(tmp_path: Path) -> None:
    output = tmp_path / "run"
    result = subprocess.run(
        [sys.executable, "scripts/reproduce_runtime_surface.py", "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    record = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert record["cases"]["verified"]["property"] == "EFFECT_VERIFIED"
    assert record["cases"]["extra_tool"]["file_written"] is False
    assert record["cases"]["alternate_effect_path"]["verdict"] == "MISMATCH"
    boundary = json.loads((output / "claim-boundary.json").read_text(encoding="utf-8"))
    assert boundary["runtime_capability_surface_completeness"] == "NOT_ESTABLISHED"
    assert boundary["external_reproduction"] is False
    assert (output / "environment.json").exists()
    environment = json.loads((output / "environment.json").read_text(encoding="utf-8"))
    assert isinstance(environment["working_tree_status"], list)
    assert environment["source_sha256"]["scripts/reproduce_runtime_surface.py"]
    assert (output / "inputs.json").exists()
    assert (output / "hashes.json").exists()
    check = subprocess.run(
        [sys.executable, "scripts/reproduce_runtime_surface.py", "--verify", str(output)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert check.returncode == 0, check.stderr or check.stdout


def test_runtime_reproduction_detects_tampered_evidence(tmp_path: Path) -> None:
    output = tmp_path / "run"
    run = subprocess.run(
        [sys.executable, "scripts/reproduce_runtime_surface.py", "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr or run.stdout
    with (output / "results.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    check = subprocess.run(
        [sys.executable, "scripts/reproduce_runtime_surface.py", "--verify", str(output)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert check.returncode != 0


def test_runtime_reproduction_refuses_failed_negative_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_evaluate = surface_evaluation.evaluate_reference

    def broken_evaluate() -> dict:
        result = real_evaluate()
        result["cases"]["extra_tool"]["runtime"] = "SUCCEEDED"
        return result

    monkeypatch.setattr(surface_evaluation, "evaluate_reference", broken_evaluate)
    with pytest.raises(ValueError, match="extra_tool"):
        run(tmp_path / "run")


def test_runtime_reproduction_requires_bound_effect_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_evaluate = surface_evaluation.evaluate_reference

    def broken_evaluate() -> dict:
        result = real_evaluate()
        result["cases"]["verified"]["rechecked"] = False
        return result

    monkeypatch.setattr(surface_evaluation, "evaluate_reference", broken_evaluate)
    with pytest.raises(ValueError, match="verified"):
        run(tmp_path / "run")


def test_git_status_preserves_porcelain_worktree_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["git", "status"], returncode=0, stdout=" M tracked.py\n"
        ),
    )
    assert _git_output("status", "--porcelain=v1") == " M tracked.py"
