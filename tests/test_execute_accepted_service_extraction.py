# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 execute-accepted extraction (slice 9)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_route_delegates_to_extracted_service() -> None:
    import servers.execution_api as api
    from remora.execution import service

    assert api._redeem_accept_token is service.redeem_accept_token


def test_execute_accepted_route_keeps_only_http_concerns() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "servers" / "execution_api.py"
    ).read_text(encoding="utf-8")
    body = src.split("def execute_accepted(", 1)[1].split("\n@router", 1)[0]
    for moved in ("_GATE.check", "_dispatch_under_lease(", "_outbox().claim",
                  "_outbox().settle", "_CHAIN.append",
                  "observation_hash !="):
        assert moved not in body, f"execute_accepted route still contains {moved}"
    for kept in ("PolicyDecisionToken.from_dict", "TokenRefused",
                 "record_execution_execute", "reconcile_stale_dispatches"):
        assert kept in body, f"execute_accepted route lost {kept}"


def test_token_refused_carries_bounded_metric_label() -> None:
    from remora.execution.service import TokenRefused

    exc = TokenRefused("binding refused: mismatch", "binding_refused")
    assert str(exc).startswith("binding refused")
    assert exc.refusal == "binding_refused"
