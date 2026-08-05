# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pytest wrapper for the OPA/Rego golden conformance check.

Skips explicitly (with reason) when the ``opa`` binary is not installed —
the structural parity contract is still enforced unconditionally by
``tests/test_opa_parity.py``; this gate additionally proves the shipped
Rego example honors the hard-guard floor when OPA is available.
"""
from __future__ import annotations

import shutil

import pytest

from scripts.opa_conflict_sweep import main as sweep_main
from scripts.opa_conformance import main as conformance_main


@pytest.mark.opa_gate
def test_shipped_rego_policy_passes_safety_parity() -> None:
    if shutil.which("opa") is None:
        pytest.skip("opa binary not found on PATH — install from openpolicyagent.org")
    assert conformance_main([]) == 0


@pytest.mark.opa_gate
def test_shipped_rego_policy_has_no_rule_conflicts() -> None:
    """No input may leave the policy without a verdict.

    Two ``gate := ...`` rules that co-fire with different values raise
    ``eval_conflict_error``: OPA returns no decision, so there is nothing for
    the adapter's hard-guard floor to correct. Seven such inputs existed in
    the shipped policy until 2026-08-04.
    """
    if shutil.which("opa") is None:
        pytest.skip("opa binary not found on PATH — install from openpolicyagent.org")
    assert sweep_main([]) == 0
