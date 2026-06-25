"""Tests for query_opa_policy() in remora.policy.opa_adapter."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from remora.policy.opa_adapter import query_opa_policy


class TestQueryOpaPolicyReturnValues:
    def test_returns_allow_string(self) -> None:
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"result": {"allow": True}}).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            result = query_opa_policy(0.9, "ordered", "read_document")
        assert result == "ALLOW"

    def test_returns_deny_when_allow_false(self) -> None:
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"result": {"allow": False}}).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            result = query_opa_policy(0.1, "disordered", "delete_data")
        assert result == "DENY"

    def test_returns_deny_when_action_deny(self) -> None:
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"result": {"action": "deny"}}).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            result = query_opa_policy(0.3, "critical", "write_record")
        assert result == "DENY"

    def test_fails_closed_when_unreachable(self) -> None:
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = query_opa_policy(0.5, "ordered", "read_document")
        assert result == "DENY"

    def test_fails_closed_on_os_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = query_opa_policy(0.5, "ordered", "read_document")
        assert result == "DENY"

    def test_custom_opa_url_used(self) -> None:
        captured = {}
        with patch("urllib.request.Request") as mock_req:
            with patch("urllib.request.urlopen", side_effect=OSError):
                query_opa_policy(0.8, "ordered", "read", opa_url="http://custom-opa:8181")
            captured["url"] = mock_req.call_args[0][0]
        assert "custom-opa:8181" in captured["url"]

    def test_custom_policy_path(self) -> None:
        captured = {}
        with patch("urllib.request.Request") as mock_req:
            with patch("urllib.request.urlopen", side_effect=OSError):
                query_opa_policy(0.8, "ordered", "read", policy_path="/v1/data/custom/policy")
            captured["url"] = mock_req.call_args[0][0]
        assert "/v1/data/custom/policy" in captured["url"]

    def test_input_document_contains_all_fields(self) -> None:
        captured = {}
        with patch("urllib.request.Request") as mock_req:
            with patch("urllib.request.urlopen", side_effect=OSError):
                query_opa_policy(0.75, "critical", "audit_write")
            body = json.loads(mock_req.call_args[1]["data"])
            captured["input"] = body["input"]
        assert captured["input"]["trust_score"] == 0.75
        assert captured["input"]["phase"] == "critical"
        assert captured["input"]["intent"] == "audit_write"
