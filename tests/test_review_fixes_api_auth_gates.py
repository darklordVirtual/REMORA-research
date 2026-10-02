# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Non-ASCII bearer must be a 401, and audit gates must not pass vacuously."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from remora.audit_gates.api import Violation, run_caveat_gate, run_claim_audit


class _Req:
    def __init__(self, headers):
        self.headers = headers


@pytest.mark.parametrize("table", [False, True])
def test_non_ascii_bearer_is_401_not_500(monkeypatch, table):
    import servers.api as api

    monkeypatch.setattr(api, "_TOKEN_TABLE", {"secret-tok": ("t1", "operator")} if table else {})
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "" if table else "secret-tok")
    with pytest.raises(HTTPException) as exc:
        api._authenticate(_Req({"Authorization": "Bearer té"}))
    assert exc.value.status_code == 401


def test_missing_claim_register_is_not_a_pass(tmp_path):
    result = run_claim_audit(tmp_path)
    assert result.passed is False
    assert result.has(Violation.MISSING_ARTIFACT, "claim_register")


def test_caveat_gate_stub_does_not_report_pass(tmp_path):
    result = run_caveat_gate(tmp_path)
    assert result.passed is False
    assert result.has(Violation.GATE_NOT_IMPLEMENTED)
