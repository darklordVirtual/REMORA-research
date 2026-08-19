# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 assess-orchestration extraction (slice 7)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_service_module_has_no_http_knowledge() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "remora" / "execution" / "service.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("fastapi", "HTTPException", "APIRouter", "servers.",
                      "pydantic"):
        assert forbidden not in src, forbidden


def test_route_delegates_to_extracted_service() -> None:
    import servers.execution_api as api
    from remora.execution import service

    assert api._assess_proposal is service.assess_proposal


def test_route_keeps_only_http_concerns() -> None:
    """The assess route body must be thin: auth, capability, idempotency,
    reconcile sweep, service call, metrics — no engine/token/lineage logic."""
    src = (
        Path(__file__).resolve().parents[1] / "servers" / "execution_api.py"
    ).read_text(encoding="utf-8")
    body = src.split("def assess(", 1)[1].split("\n@router", 1)[0]
    for moved in ("PolicyDecisionToken.issue", "derive_lineage(",
                  "_ENGINE.decide", "q.enqueue"):
        assert moved not in body, f"assess route still contains {moved}"
    for kept in ("_require_tenant_capability", "_idempotency_get",
                 "reconcile_stale_dispatches", "record_execution_assess"):
        assert kept in body, f"assess route lost {kept}"
