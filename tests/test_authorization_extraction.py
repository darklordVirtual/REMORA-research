# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 authorization extraction (slice 3)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_authorization_module_has_no_http_knowledge() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "remora" / "execution" / "authorization.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("fastapi", "HTTPException", "APIRouter", "servers."):
        assert forbidden not in src, forbidden


def test_no_bundle_reports_enforced_false() -> None:
    from remora.execution.authorization import resolve_toolspec

    identity = resolve_toolspec(None, "any_tool", {}, "prod")
    assert identity == {"enforced": False, "tool_id": "any_tool",
                        "version": 0, "hash": "", "bundle_digest": ""}


def test_route_layer_converts_refusal_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    import servers.execution_api as api
    from fastapi import HTTPException
    from remora.toolcall.toolspec import ToolSpecRefused

    class _RefusingBundle:
        def get(self, name):
            raise ToolSpecRefused("unknown_tool: " + name)

    monkeypatch.setattr(api, "_toolspec_bundle", lambda: _RefusingBundle())
    with pytest.raises(HTTPException) as exc:
        api._resolve_toolspec("nope", {}, "prod")
    assert exc.value.status_code == 409
    assert str(exc.value.detail).startswith("unknown_tool")


def test_assessed_record_reads_chain_not_request() -> None:
    from remora.execution.authorization import assessed_record

    class _Entry:
        def __init__(self, payload):
            self.payload = payload

    class _Chain:
        def entries(self, tenant):
            assert tenant == "t1"
            return [
                _Entry({"event": "assessed", "review_item_id": "item-1",
                        "toolspec_hash": "h1", "proposal_id": "p1"}),
            ]

    assert assessed_record(_Chain(), "t1", "item-1") == ("h1", "p1")
    assert assessed_record(_Chain(), "t1", "") == ("", "")
    assert assessed_record(_Chain(), "t1", "missing") == ("", "")
