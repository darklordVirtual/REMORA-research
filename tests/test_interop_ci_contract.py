# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CI triggers cover actual runtime imports; admission executes base code only."""
from __future__ import annotations

import fnmatch
import re

import pytest
import yaml

pytestmark = pytest.mark.docgate


def _workflow(repo_root, name):
    return yaml.load((repo_root / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_producer_trigger_covers_runtime_and_guard_dependencies(repo_root):
    workflow = _workflow(repo_root, "federation-interop.yml")
    for event in ("pull_request", "push"):
        patterns = workflow["on"][event]["paths"]
        for path in (
            "remora/enforcement/lease.py", "remora/governance/effect_verification.py",
            "remora/policy/observation.py", "remora/observability/events.py",
            "servers/execution_api.py", "scripts/check_capability_freshness.py",
            "scripts/interop_external_admission.py", "tests/conftest.py",
            "schemas/runtime-self-service-v1.schema.json",
            "docs/assurance/capability_register_v1.yaml",
            "requirements-federation.lock", "requirements-federation-bootstrap.lock",
        ):
            assert any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), (event, path)


def _pins(text):
    pins = {}
    for line in text.replace("\\\n", " ").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z0-9_.-]+)==([a-zA-Z0-9_.-]+)\s", line)
        assert match, f"unlocked requirement: {line}"
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", line), f"missing package hash: {line}"
        assert match[1] not in pins
        pins[match[1]] = match[2]
    assert pins
    return pins


def test_installs_use_hash_locked_bootstrap_and_no_resolution(repo_root):
    assert _pins((repo_root / "requirements-federation-bootstrap.lock").read_text()) == {"pip": "26.2.1"}
    pins = _pins((repo_root / "requirements-federation.lock").read_text())
    assert {"pytest", "pytest-cov", "pyyaml", "jsonschema", "cryptography", "hatchling", "editables"} <= pins.keys()
    for name in ("federation-interop.yml", "external-interop-admission.yml"):
        workflow = _workflow(repo_root, name)
        steps = next(iter(workflow["jobs"].values()))["steps"]
        setup, = [step for step in steps if step.get("uses", "").startswith("actions/setup-python@")]
        assert setup["with"]["python-version"] == "3.12.15"
        installs = "\n".join(step.get("run", "") for step in steps if "pip install" in step.get("run", ""))
        assert "--upgrade pip" not in installs
        assert "--require-hashes -r requirements-federation-bootstrap.lock" in installs
        assert "--require-hashes -r requirements-federation.lock" in installs
        assert "python -m pip install --no-deps --no-build-isolation -e ." in installs
        assert installs.count("--only-binary=:all:") == 2


def test_admission_workflow_is_base_owned_and_read_only(repo_root):
    workflow = _workflow(repo_root, "external-interop-admission.yml")
    assert set(workflow["on"]) == {"pull_request_target"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["validate"]
    assert job["defaults"]["run"]["working-directory"] == "trusted"
    checkouts = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
    assert checkouts[0]["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert checkouts[0]["with"]["path"] == "trusted"
    assert checkouts[1]["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"
    assert checkouts[1]["with"]["path"] == "incoming"
    assert all(step["with"]["persist-credentials"] == "false" for step in checkouts)
    for step in job["steps"]:
        command = step.get("run", "")
        assert "cd ../incoming" not in command
        assert "../incoming/" not in command
        assert "interop_self_service.py" not in command
    validation, = [step for step in job["steps"] if "interop_external_admission.py" in step.get("run", "")]
    assert "--repo ../incoming" in validation["run"]
    assert validation["env"]["TRUST_REVISION"] == "${{ github.event.pull_request.base.sha }}"
