# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for scripts/check_require_hashes.py (SR-11/SR-23, SEC-19).

The gate must catch a bare third-party install and a lock pin without a hash,
and must accept the legitimate patterns: hashed -r install, -c constraints,
in-repo code installed with --no-deps --no-build-isolation, and an explicit
marker directly above the command.

The bypass cases below each passed the first version of the gate (review of
PR #1116): a `-c` or `--require-hashes` substring anywhere on the line, pip3,
the non-pip installers, a chained command after `-e .`, a bare local path,
markers leaking across steps or from a continuation line, composite actions,
and a hard-coded list of hashed locks.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_require_hashes.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd or ROOT,
    )


_GOOD_LOCK = (
    "pytest==9.1.1 \\\n"
    "    --hash=sha256:" + "a" * 64 + "\n"
)
_BAD_LOCK = "pytest==9.1.1\n"
_LOCKS = {"requirements-ci.lock": _GOOD_LOCK, "requirements-release.lock": _GOOD_LOCK}


def _tree(tmp_path: Path, workflow: str, locks: dict[str, str] | None = None,
          action: str | None = None) -> Path:
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text(workflow, encoding="utf-8")
    if action is not None:
        act_dir = tmp_path / ".github" / "actions" / "setup"
        act_dir.mkdir(parents=True)
        (act_dir / "action.yml").write_text(action, encoding="utf-8")
    for name, content in (_LOCKS if locks is None else locks).items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return tmp_path


def _steps(*runs: str) -> str:
    """A workflow whose steps carry the given `run:` scripts (block style)."""
    out = "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
    for run in runs:
        out += "      - name: step\n        run: |\n"
        out += "".join(f"          {line}\n" for line in run.splitlines())
    return out


def _gate(tmp_path: Path, workflow: str, **kw) -> subprocess.CompletedProcess:
    return _run("--root", str(_tree(tmp_path, workflow, **kw)))


def test_repo_tree_passes() -> None:
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bare_third_party_install_fails(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps("pip install cyclonedx-bom"))
    assert proc.returncode == 1
    assert "without --require-hashes" in proc.stdout


def test_lock_pin_without_hash_fails(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps("echo"), locks={
        "requirements-ci.lock": _BAD_LOCK, "requirements-release.lock": _GOOD_LOCK})
    assert proc.returncode == 1
    assert "no sha256 hash" in proc.stdout


def test_legitimate_patterns_pass(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps(
        "pip install --require-hashes -r requirements-ci.lock",
        "pip install -e \".[dev]\" -c /tmp/constraints.txt",
        "python -m pip install --no-deps --no-build-isolation -e \".[dev]\"",
        "python -m pip install --no-deps --only-binary=:all: \\\n"
        "  --require-hashes -r \"$RUNNER_TEMP/reader.txt\"",
        "# hash-exempt: verbatim README contract\npip install -e \".[dev]\"",
        "# pinned: dispatch-only tooling\npip install inspect-ai==0.3.248",
        "python -m pip check",
    ))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_pinned_but_unmarked_direct_install_fails(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps("pip install pymupdf==1.28.0"))
    assert proc.returncode == 1
    assert "unmarked" in proc.stdout


# --- bypasses of the first version of the gate (review of PR #1116) -----------

@pytest.mark.parametrize("script", [
    # `-c ` / `--require-hashes` as a substring, not as pip's own option
    "pip install evil  # -c not really --require-hashes",
    "pip install evil && python -c 'print(1)'",
    "pip install evil && bash -c 'true'",
    "pip install evil; echo --require-hashes",
    "pip install --require-hashes evil",
    # pip3 / versioned pip / path to pip
    "pip3 install evil",
    "pip3.12 install evil",
    "\"$RUNNER_TEMP/venv/bin/pip\" install evil",
    "python3 -m pip install evil",
    # other installers
    "uv pip install evil",
    "uvx evil",
    "pipx install evil",
    "pipx run evil",
    "uv tool install evil",
    "poetry add evil",
    # a chained install after an in-repo one
    "pip install --no-deps --no-build-isolation -e . && pip install evil",
    "pip install -e . evil -c",
    # an install hidden in a shell -c argument
    "bash -c 'pip install evil'",
    # in-repo code that still resolves from the index
    "pip install ./x",
    "pip install -e .",
    "pip install --no-deps -e .",
    "pip wheel . --no-deps -w dist/",
])
def test_bypass_is_caught(tmp_path: Path, script: str) -> None:
    proc = _gate(tmp_path, _steps(script))
    assert proc.returncode == 1, f"bypass not caught: {script!r}\n{proc.stdout}"


def test_python_c_install_is_caught(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps(
        "python -c \"import subprocess; subprocess.run(['pip','install','evil'])\""))
    assert proc.returncode == 1
    assert "python -c" in proc.stdout


def test_marker_does_not_leak_to_the_next_step(tmp_path: Path) -> None:
    workflow = _steps(
        "# hash-exempt: covers only the first step\npip install -e \".[dev]\"",
        "pip install evil",
    )
    proc = _gate(tmp_path, workflow)
    assert proc.returncode == 1
    assert "[run 2]" in proc.stdout


def test_yaml_comment_above_step_is_not_a_marker(tmp_path: Path) -> None:
    workflow = (
        "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      # hash-exempt: outside the run script\n"
        "      - run: pip install evil\n"
    )
    proc = _gate(tmp_path, workflow)
    assert proc.returncode == 1


def test_marker_does_not_leak_past_another_command(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps(
        "# hash-exempt: covers the next command only\n"
        "pip install -e \".[dev]\"\n"
        "pip install evil"))
    assert proc.returncode == 1


def test_marker_on_a_continuation_line_does_not_count(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps(
        "pip install \\\n  evil  # hash-exempt: trailing comment"))
    assert proc.returncode == 1


def test_marker_does_not_cover_a_chained_second_install(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps(
        "# pinned: covers one install\npip install a==1.0 && pip install evil"))
    assert proc.returncode == 1


def test_pinned_marker_does_not_cover_an_unpinned_install(tmp_path: Path) -> None:
    proc = _gate(tmp_path, _steps("# pinned: not actually pinned\npip install evil"))
    assert proc.returncode == 1


def test_composite_action_is_scanned(tmp_path: Path) -> None:
    action = (
        "name: setup\nruns:\n  using: composite\n  steps:\n"
        "    - shell: bash\n      run: pip install evil\n"
    )
    proc = _gate(tmp_path, _steps("echo"), action=action)
    assert proc.returncode == 1
    assert ".github/actions/setup/action.yml" in proc.stdout


def test_every_requirements_lock_is_checked(tmp_path: Path) -> None:
    locks = dict(_LOCKS)
    locks["requirements-agentharm.lock"] = _BAD_LOCK
    proc = _gate(tmp_path, _steps("echo"), locks=locks)
    assert proc.returncode == 1
    assert "requirements-agentharm.lock" in proc.stdout


def test_extras_pin_with_hash_is_accepted(tmp_path: Path) -> None:
    locks = {"requirements-ci.lock":
             "uvicorn[standard]==0.54.0 \\\n    --hash=sha256:" + "b" * 64 + "\n"}
    proc = _gate(tmp_path, _steps("echo"), locks=locks)
    assert proc.returncode == 0, proc.stdout


def test_lock_line_that_is_not_an_exact_pin_fails(tmp_path: Path) -> None:
    locks = {"requirements-ci.lock": _GOOD_LOCK + "evil>=1.0\n"}
    proc = _gate(tmp_path, _steps("echo"), locks=locks)
    assert proc.returncode == 1
    assert "not an exact pin" in proc.stdout


# --- supply-chain.yml: pip-audit from a separate tooling venv (SR-11) ----------

def _load_audit_gate():
    import importlib.util

    path = ROOT / "scripts" / "check_pip_audit_baseline.py"
    spec = importlib.util.spec_from_file_location("check_pip_audit_baseline", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_from_tooling_venv_targets_the_project_interpreter(monkeypatch) -> None:
    gate = _load_audit_gate()
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else")
    cmd, env = gate.audit_command("/tools/bin/python")
    assert cmd[0] == "/tools/bin/python"
    assert cmd[1:3] == ["-m", "pip_audit"]
    # pip-audit enumerates the packages of THIS interpreter, not the tool venv.
    assert env["PIPAPI_PYTHON_LOCATION"] == sys.executable
    assert "VIRTUAL_ENV" not in env


def test_audit_without_tooling_venv_is_unchanged(monkeypatch) -> None:
    gate = _load_audit_gate()
    monkeypatch.delenv("PIPAPI_PYTHON_LOCATION", raising=False)
    cmd, env = gate.audit_command(None)
    assert cmd[0] == sys.executable
    assert "PIPAPI_PYTHON_LOCATION" not in env


def test_supply_chain_installs_audit_tooling_outside_the_audited_env() -> None:
    import yaml

    wf = yaml.safe_load((ROOT / ".github/workflows/supply-chain.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["pip-audit"]["steps"]
    runs = "\n".join(s.get("run", "") for s in steps)
    assert '"$RUNNER_TEMP/audit-tools/bin/python" -m pip install --require-hashes' in runs
    assert "python -m pip install --require-hashes \"--only-binary=:all:\" -r requirements-release.lock\n" not in runs
    assert '--audit-python "$RUNNER_TEMP/audit-tools/bin/python"' in runs


def test_release_attest_checks_the_manifest_digest_from_the_build_job() -> None:
    import yaml

    wf = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    build, attest = wf["jobs"]["build"], wf["jobs"]["attest"]
    assert "sums_sha256" in build["outputs"]
    assert "id-token" not in build.get("permissions", {})
    steps = attest["steps"]
    verify = next(s for s in steps if "SHA256SUMS.txt" in s.get("run", ""))
    assert verify["env"]["EXPECTED_SUMS_SHA256"] == "${{ needs.build.outputs.sums_sha256 }}"
    run = verify["run"]
    assert run.index('"${EXPECTED_SUMS_SHA256}  SHA256SUMS.txt" | sha256sum -c') < run.index(
        "sha256sum -c --strict SHA256SUMS.txt")
    # Every installing step precedes the identity; attest installs nothing.
    assert not any("pip install" in s.get("run", "") for s in steps)
    # The download-artifact pin is the one the rest of the repository uses.
    dl = [s["uses"] for s in steps if s.get("uses", "").startswith("actions/download-artifact@")]
    assert dl == ["actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"]
