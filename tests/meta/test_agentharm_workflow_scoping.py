# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Static guards for .github/workflows/agentharm-experiment.yml (SR-12, SEC-18).

The job that runs third-party eval code must hold a read-only token and no
workflow-level secrets; secrets are step-scoped; results reach the repository
only through a separate job that runs no experiment code and opens a pull
request. The interpreter must match the one the hashed lock was compiled for.
Scope: these read the workflow text; they do not run the workflow.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "agentharm-experiment.yml"
LOCK = ROOT / "requirements-agentharm.lock"
LOCK_IN = ROOT / "requirements-agentharm.in"


def _wf() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


def test_no_workflow_level_env_secrets() -> None:
    wf = _wf()
    assert "secrets." not in yaml.safe_dump(wf.get("env") or {})
    for job in wf["jobs"].values():
        assert "secrets." not in yaml.safe_dump(job.get("env") or {})


def test_eval_job_is_read_only_and_does_not_open_pull_requests() -> None:
    job = _wf()["jobs"]["agentharm"]
    assert job["permissions"] == {"contents": "read"}
    assert not any("create-pull-request" in s.get("uses", "") for s in job["steps"])
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


def test_secrets_are_step_scoped() -> None:
    job = _wf()["jobs"]["agentharm"]
    for step in job["steps"]:
        text = yaml.safe_dump(step)
        if step.get("name") in ("Verify HF dataset access", "Run experiment arms"):
            continue
        assert "secrets." not in text, step.get("name")
    assert _step(job, "Verify HF dataset access")["env"]["HF_TOKEN"] == "${{ secrets.HF_TOKEN }}"
    # The eval step downloads the gated dataset, so it needs the token too.
    assert _step(job, "Run experiment arms")["env"]["HF_TOKEN"] == "${{ secrets.HF_TOKEN }}"


def test_propose_job_runs_no_experiment_code() -> None:
    wf = _wf()
    job = wf["jobs"]["propose-results"]
    assert job["needs"] == "agentharm"
    assert job["if"] == "inputs.limit == '0'"
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    text = yaml.safe_dump(job)
    assert "secrets." not in text
    for step in job["steps"]:
        run = step.get("run", "")
        assert not re.search(r"\b(pip|python|inspect)\b", run), run
    assert any(s.get("uses", "").startswith("peter-evans/create-pull-request@") for s in job["steps"])
    assert any(s.get("uses", "").startswith("actions/download-artifact@") for s in job["steps"])


def test_python_version_matches_the_lock() -> None:
    job = _wf()["jobs"]["agentharm"]
    setup = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-python@"))
    assert str(setup["with"]["python-version"]) == "3.12"
    assert "--python-version 3.12" in LOCK.read_text(encoding="utf-8").splitlines()[1]


def test_install_is_hash_locked_and_lock_excludes_vulnerable_fsspec() -> None:
    job = _wf()["jobs"]["agentharm"]
    run = _step(job, "Install REMORA + experiment deps")["run"]
    assert "pip install --require-hashes -r requirements-agentharm.lock" in run
    pins = dict(re.findall(r"^([a-z0-9][a-z0-9._-]*)(?:\[[^\]]*\])?==(\S+)", LOCK.read_text(encoding="utf-8"), re.M))
    # PYSEC-2026-4217 / CVE-2026-104851, fixed in fsspec 2026.6.0.
    assert tuple(int(p) for p in pins["fsspec"].split(".")) >= (2026, 6, 0)
    declared = dict(re.findall(r"^([a-z0-9][a-z0-9._-]*)==(\S+)", LOCK_IN.read_text(encoding="utf-8"), re.M))
    for name, version in declared.items():
        assert pins[name] == version, name
