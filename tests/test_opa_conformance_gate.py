# Author: Stian Skogbrott
# License: Apache-2.0
"""Pytest wrapper for the OPA/Rego golden conformance check.

Skips explicitly (with reason) when the ``opa`` binary is not installed —
the structural parity contract is still enforced unconditionally by
``tests/test_opa_parity.py``; this gate additionally proves the shipped
Rego example honors the hard-guard floor when OPA is available.
"""
from __future__ import annotations

import shutil

import pytest

from scripts.opa_conformance import main as conformance_main


@pytest.mark.opa_gate
def test_shipped_rego_policy_passes_safety_parity() -> None:
    if shutil.which("opa") is None:
        pytest.skip("opa binary not found on PATH — install from openpolicyagent.org")
    assert conformance_main([]) == 0
