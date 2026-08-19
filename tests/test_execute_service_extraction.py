# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 execute-orchestration extraction (slice 8)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_route_delegates_to_extracted_service() -> None:
    import servers.execution_api as api
    from remora.execution import service

    assert api._execute_approved_item is service.execute_approved_item


def test_execute_route_keeps_only_http_concerns() -> None:
    """The execute route body must be thin: no grant mint/consume, no
    dispatch, no outbox claim/settle, no chain writes."""
    src = (
        Path(__file__).resolve().parents[1] / "servers" / "execution_api.py"
    ).read_text(encoding="utf-8")
    body = src.split("def execute(", 1)[1].split("\n@router", 1)[0]
    for moved in ("PolicyDecisionToken.issue", "_GATE.check",
                  "_dispatch_under_lease(", "_outbox().claim",
                  "_outbox().settle", "_CHAIN.append",
                  "record_execution_outcome"):
        assert moved not in body, f"execute route still contains {moved}"
    for kept in ("_require_tenant_capability", "reconcile_stale_dispatches",
                 "record_execution_execute", "ToolSpecChanged",
                 "ReviewNotFound", "ReviewConflict"):
        assert kept in body, f"execute route lost {kept}"


def test_service_execute_has_no_http_knowledge() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "remora" / "execution" / "service.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("fastapi", "HTTPException", "APIRouter", "servers.",
                      "pydantic"):
        assert forbidden not in src, forbidden
