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
import tomllib
from pathlib import Path

import yaml

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
