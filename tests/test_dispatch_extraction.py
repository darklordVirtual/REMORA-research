# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 dispatch extraction (slice 4)."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.execution.dispatch import dispatch_under_lease

_SEMANTIC = {"tool_contract_bundle_hash": "", "intent_authority_hash": ""}
_CALL = SimpleNamespace(tool_name="read_sensor",
                        arguments={"sensor_id": "PT-101"},
                        target_environment="prod")


def test_dispatch_module_has_no_http_knowledge() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "remora" / "execution" / "dispatch.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("fastapi", "HTTPException", "APIRouter", "servers."):
        assert forbidden not in src, forbidden


def test_pep_denied_short_circuits_before_dispatcher() -> None:
    result = dispatch_under_lease(
        tenant="t1", principal="p", tool_call=_CALL, semantic=_SEMANTIC,
        now=datetime.now(UTC), dispatcher=object(), policy_bundle_hash="pb",
        gate_allowed=False,
    )
    assert result == {"executed": False, "refusal_reason": "pep_denied"}


def test_missing_dispatcher_refuses_policy_bundle_unavailable() -> None:
    result = dispatch_under_lease(
        tenant="t1", principal="p", tool_call=_CALL, semantic=_SEMANTIC,
        now=datetime.now(UTC), dispatcher=None, policy_bundle_hash="pb",
    )
    assert result["executed"] is False
    assert result["refusal_reason"] == "policy_bundle_unavailable"


def test_tool_exception_burns_nonce_and_reports_unknown_state() -> None:
    class _Dispatcher:
        def dispatch(self, lease, name, args, **kw):
            raise RuntimeError("downstream exploded")

    result = dispatch_under_lease(
        tenant="t1", principal="p", tool_call=_CALL, semantic=_SEMANTIC,
        now=datetime.now(UTC), dispatcher=_Dispatcher(), policy_bundle_hash="pb",
    )
    assert result["executed"] is False
    assert result["refusal_reason"] == "tool_failed_nonce_burned"
    assert "downstream exploded" in result["error"]


def test_api_wrapper_delegates_to_extracted_impl() -> None:
    import servers.execution_api as api
    from remora.execution import dispatch as dispatch_mod

    assert api._dispatch_under_lease_impl is dispatch_mod.dispatch_under_lease
    assert api._record_dispatch_intent_impl is dispatch_mod.record_dispatch_intent
