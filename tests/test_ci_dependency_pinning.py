"""Static guards for the two CI install defects that reddened master on 2026-09-21.

Both scheduled workflows failed in their *install* step, not in the work they
exist to do:

* ``Mutation Testing (scheduled)`` uninstalled ``remora`` — a distribution name
  that has not existed since the project was renamed to ``remora-assurance``.
  pip skipped it silently, the installed package kept shadowing the mutated
  sources, and the workflow's own guard correctly aborted the sweep.
* ``NLI backend parity (RF-06)`` could not resolve its install set: the
  constraint lock pinned ``click==8.1.8`` and ``huggingface_hub==1.28.0``,
  and that huggingface-hub release requires ``click>=8.4.2``. Two pins in one
  lock file contradicted each other, so pip reported ResolutionImpossible
  before the NLI run started.

Scope (declared, not exhaustive): these are static checks over the workflow
YAML and the committed lock file, covering the two pins that actually
collided. They do not resolve the dependency graph, so a contradiction
between any other pair of pins is not detected here; the scheduled runs
remain the backstop.
"""

from __future__ import annotations

import re
import json
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
LOCK_FILE = REPO_ROOT / "requirements-lock.txt"

PIN = re.compile(r"^([A-Za-z0-9._-]+)==(.+)$")


def _distribution_name() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["name"])


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in LOCK_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-e")) or "file://" in line:
            continue
        match = PIN.match(line)
        if match:
            pins[_canonical(match.group(1))] = match.group(2)
    return pins


def _run_scripts(workflow_path: Path) -> list[str]:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    scripts: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if isinstance(step.get("run"), str):
                scripts.append(step["run"])
    return scripts


def test_mutation_sweep_uninstalls_the_real_distribution_name() -> None:
    """The sweep is only valid when the package itself is gone from site-packages."""
    distribution = _distribution_name()
    scripts = _run_scripts(WORKFLOWS_DIR / "mutation.yml")
    uninstalls = [
        script
        for script in scripts
        if re.search(
            rf"pip\s+uninstall\b[^\n]*(?<![A-Za-z0-9._-]){re.escape(distribution)}(?![A-Za-z0-9._-])",
            script,
        )
    ]
    assert uninstalls, (
        f"mutation.yml must uninstall the project distribution {distribution!r} before "
        "the sweep; pip silently skips an unknown name and the installed package then "
        "shadows every mutant."
    )


def test_lock_pins_huggingface_hub() -> None:
    """The collision only has two sides while both packages stay pinned."""
    assert "huggingface-hub" in _lock_pins(), (
        "requirements-lock.txt must keep huggingface-hub pinned; unpinned it floats "
        "to whatever floor the latest release declares and the nli extra resolves "
        "differently on every run."
    )


def test_lock_click_pin_satisfies_the_pinned_huggingface_hub_floor() -> None:
    """The two pins that collided must stay mutually satisfiable.

    huggingface_hub 1.28.0 (the pinned release) declares ``click<9.0.0,>=8.4.2``.
    Any later huggingface-hub bump keeps or raises that floor, so 8.4.2 is the
    lower bound this lock has to clear.
    """
    pins = _lock_pins()
    click_version = tuple(int(part) for part in pins["click"].split(".")[:3])
    assert click_version >= (8, 4, 2), (
        f"click is pinned at {pins['click']}, below the >=8.4.2 floor that the pinned "
        "huggingface-hub requires; the nli extra cannot resolve."
    )


@pytest.mark.parametrize(("package", "patched"), [
    ("datasets", "5.0.1"),
    ("fsspec", "2026.6.0"),
    ("s3fs", "2026.6.0"),
    ("langgraph-sdk", "0.4.4"),
    ("mako", "1.4.2"),
    ("multidict", "6.9.1"),
    ("scapy", "2.7.0"),
])
def test_lock_excludes_known_vulnerable_dependency_versions(package, patched) -> None:
    assert Version(_lock_pins()[package]) >= Version(patched)


def test_unlocked_datasets_extra_excludes_the_vulnerable_release() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        extras = tomllib.load(handle)["project"]["optional-dependencies"]
    requirement = next(Requirement(value) for value in extras["datasets"]
                       if Requirement(value).name == "datasets")
    assert Version("5.0.0") not in requirement.specifier
    assert Version("5.0.1") in requirement.specifier


@pytest.mark.parametrize("manifest", [
    "frontend/package-lock.json", "workers/mcp-gateway/package-lock.json",
])
@pytest.mark.parametrize(("package", "patched"), [
    ("source-map-js", "1.2.2"),
    ("shell-quote", "1.11.0"),
    ("sharp", "0.35.5"),
])
def test_npm_locks_exclude_known_vulnerable_dependency_versions(manifest, package, patched) -> None:
    lock = json.loads((REPO_ROOT / manifest).read_text(encoding="utf-8"))
    for path, entry in lock["packages"].items():
        if path.endswith(f"/{package}"):
            assert Version(entry["version"]) >= Version(patched), path
