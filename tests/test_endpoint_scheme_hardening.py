# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Configured endpoints on the authority path accept http(s) only (REM-037, ruff S310).

A file: or custom scheme lets local content stand in for a remote answer.
For the OPA query that could turn a misconfiguration into an ALLOW; for the
custody hop it would let a local file impersonate the executor. Both now
fail closed on any scheme but http and https.
"""
from __future__ import annotations

import json

import pytest

import remora.execution.remote_dispatch as rd
from remora.policy.opa_adapter import query_opa_policy


@pytest.mark.parametrize("endpoint", ["file:///etc/passwd", "ftp://executor/x", "gopher://h"])
def test_custody_hop_refuses_a_non_http_endpoint(monkeypatch, endpoint):
    called = []
    monkeypatch.setenv(rd.ENDPOINT_ENV, endpoint)
    monkeypatch.setattr(rd, "_post", lambda *a, **k: called.append(a) or {})
    with pytest.raises(rd.RemoteDispatchUnavailable, match="http"):
        rd.remote_dispatch(lease=object(), tenant="t", principal="p", tool_call=object())
    assert called == []


def test_opa_query_denies_on_a_file_url_even_if_the_file_says_allow(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"result": {"allow": True, "action": "allow"}}), encoding="utf-8")
    decision = query_opa_policy(trust_score=0.9, phase="ordered", intent="read",
                                opa_url=f"file://{tmp_path}", policy_path="/allow.json")
    assert decision == "DENY"


def test_mcp_helpers_refuse_non_http_endpoints():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers"))
    import mcp_remora as m
    assert m._post("file:///etc/passwd", {})["error"].startswith("endpoint must be")
    assert m._get("file:///etc/passwd")["error"].startswith("endpoint must be")


def test_audit_log_query_is_encoded(monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers"))
    import mcp_remora as m
    seen = []

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    monkeypatch.setattr(m, "AGENT_CONTROL", "https://control.example")
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda req, **k: (seen.append(req.full_url), _Resp())[1])
    m.handle_agent_audit_log({"session_id": "s1&tenant=other", "limit": 5})
    assert seen and "tenant=other" not in seen[0].split("?", 1)[1].split("&")
    assert "session_id=s1%26tenant%3Dother" in seen[0]
