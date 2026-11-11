# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Why the OT pilot cannot run WS1 in enforce mode today (NEGATIVE_RESULTS §105).

These tests pin a state, not a goal. When one fails because the state
improved, update §105 and docs/assurance/ws1_utility_test_plan_v1.md with it.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import re
from pathlib import Path

import pytest

from remora.verification.execution_gate import ENFORCE_DEPENDENCIES, Ws1Gate

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "deploy" / "ot-pilot"
STATUS = ROOT / "docs" / "design" / "derived-information-flow-control-v1-status.md"


def _pilot_deployment():
    spec = importlib.util.spec_from_file_location("ot_ws1_under_test", PILOT / "ot_ws1.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.build_ws1_deployment()


def test_the_pilot_deployment_builds_a_shadow_gate():
    assert Ws1Gate("shadow", _pilot_deployment(), flow_control=False).mode == "shadow"


def test_the_pilot_deployment_cannot_build_an_enforce_gate():
    deployment = _pilot_deployment()
    assert dict(deployment.enforce_dependencies) == {}
    with pytest.raises(ValueError, match="REMORA_FLOW_CONTROL"):
        Ws1Gate("enforce", deployment, flow_control=False)
    with pytest.raises(ValueError) as refused:
        Ws1Gate("enforce", deployment, flow_control=True)
    assert all(dep in str(refused.value) for dep in ENFORCE_DEPENDENCIES)


def test_the_pilot_compose_file_runs_ws1_in_shadow_without_flow_control():
    compose = (PILOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "REMORA_WS1_MODE: shadow" in compose
    assert not re.search(r"^\s*REMORA_FLOW_CONTROL:", compose, flags=re.MULTILINE)


def _status_of(work_package: str) -> set[str]:
    """The status cells of the rows whose work-package column names it.

    Columns are phase, work package, priority, status. A row that cites the
    package in its evidence text is another package's row and is not read.
    """
    found = set()
    for line in STATUS.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) > 5 and re.search(rf"\b{re.escape(work_package)}\b", cells[2]):
            found.add(cells[4].split(" ")[0])
    assert found and found <= {"DONE", "IN_PROGRESS", "NOT_STARTED"}, (work_package, found)
    return found


def test_four_of_the_five_prerequisites_are_not_done_in_the_status_record():
    """IFC-04b is the result-labelling half of IFC-04. Only IFC-11 is done."""
    assert _status_of("IFC-04") == {"IN_PROGRESS"}
    assert _status_of("IFC-06") == {"IN_PROGRESS"}
    assert _status_of("IFC-11") == {"DONE"}
    assert _status_of("IFC-12") == {"IN_PROGRESS"}
    assert "NOT_STARTED" in _status_of("IFC-13")


def test_the_pilots_toolspec_bundle_declares_no_flow_block():
    import sys

    sys.path.insert(0, str(PILOT))
    try:
        import build_toolspec
        bundle = build_toolspec.unsigned_bundle()
    finally:
        sys.path.remove(str(PILOT))
    assert '"flow"' not in __import__("json").dumps(bundle)


def test_limit_the_enforce_check_accepts_any_non_empty_string_as_evidence():
    """The gate cannot tell evidence from a placeholder: a deployment that
    writes one word per work package gets an enforce gate. The Study C harness
    and two test fixtures do, each labelled as not evidence (§105)."""
    placeholder = dataclasses.replace(
        _pilot_deployment(), enforce_dependencies=dict.fromkeys(ENFORCE_DEPENDENCIES, "x"))
    assert Ws1Gate("enforce", placeholder, flow_control=True).mode == "enforce"
    blank = dataclasses.replace(
        _pilot_deployment(), enforce_dependencies=dict.fromkeys(ENFORCE_DEPENDENCIES, "  "))
    with pytest.raises(ValueError):
        Ws1Gate("enforce", blank, flow_control=True)
