# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the Product Truth Contract and its gate (scripts/check_product_truth.py)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "check_product_truth", ROOT / "scripts" / "check_product_truth.py"
)
cpt = importlib.util.module_from_spec(_spec)
sys.modules["check_product_truth"] = cpt
_spec.loader.exec_module(cpt)


def test_contract_parses_and_is_internally_consistent():
    contract = cpt.load_contract()
    assert cpt.contract_errors(contract) == []


def test_all_required_capabilities_classified():
    contract = cpt.load_contract()
    names = {c["name"] for c in contract["capabilities"]}
    assert cpt.REQUIRED_CAPABILITIES <= names


def test_core_set_is_exactly_the_execution_kernel():
    contract = cpt.load_contract()
    core = {c["name"] for c in contract["capabilities"] if c["class"] == "core"}
    assert core == {
        "RemoraDecisionEngine",
        "PolicyObservation",
        "hard guards",
        "review queue",
        "PolicyDecisionToken",
        "EnforcementGate",
        "ExecutionLease",
        "GovernedToolDispatcher",
        "ExecutionOutbox",
        "effect verification",
        "tenant audit chain",
        "ToolSpec",
    }


def test_research_machinery_is_never_core():
    contract = cpt.load_contract()
    by_name = {c["name"]: c["class"] for c in contract["capabilities"]}
    for name in ("multi-oracle consensus", "thermodynamics", "AROMER", "RAG oracle", "law search"):
        assert by_name[name] == "experimental", name
    assert by_name["frontend simulator"] == "demo"


def test_flow_line_with_noncore_alias_violates():
    line = "Agent proposes → Multi-oracle consensus → Policy gate → outcome"
    assert cpt.line_violates(line, ["multi-oracle"])


def test_mandatory_marker_violates():
    line = "The cascade pipeline is the primary execution path."
    assert cpt.line_violates(line, ["cascade pipeline"])


def test_qualified_mention_does_not_violate():
    line = "The optional cascade pipeline (research) → assess → report"
    assert not cpt.line_violates(line, ["cascade pipeline"])
    assert not cpt.line_violates(
        "Those components are not prerequisites for the execution kernel.",
        ["multi-oracle"],
    )


def test_plain_mention_without_path_assertion_does_not_violate():
    assert not cpt.line_violates(
        "AROMER is documented in section 5.5.", ["AROMER"]
    )


def test_repo_scan_is_currently_clean():
    contract = cpt.load_contract()
    assert cpt.scan_errors(contract) == []
