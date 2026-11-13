# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What a host that embeds REMORA needs from ``remora.sdk`` and could not reach.

Found by driving the governed path from a host that imports ``remora.sdk``
only:

* a verifier could not hand over what it observed, so no write could be settled
  as ``EFFECT_VERIFIED`` with a computed verdict through the SDK, although the
  route accepts ``observed`` and ``arguments``;
* ``resolve_unknown`` sent its default empty ``reason``, which the route always
  refuses.
"""
from __future__ import annotations

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from remora.sdk import (  # noqa: E402
    AsyncRemoraClient,
    EffectVerificationView,
    RemoraClient,
    build_postcondition,
    verify_effect,
)

OBSERVED = {"value": 21.5}
ARGUMENTS = {"tag": "TIC-101", "value": 21.5}


def _verification() -> EffectVerificationView:
    view = verify_effect(
        build_postcondition(tool_id="write_setpoint", target_selector={"tag": "TIC-101"},
                            expected_fields={"value": 21.5}),
        OBSERVED, proposal_id="p-1", execution_id="j-1", toolspec_hash="",
        verifier_identity="effect-verifier")
    return EffectVerificationView.from_payload(
        {**view.to_dict(), "tool_call_hash": "a" * 64, "grant_jti": "j-1"})


def _recording(seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append({"path": request.url.path, "body": body})
        if request.url.path.endswith("/resolve"):
            return httpx.Response(200, json={"operation_id": body["operation_id"],
                                             "status": "resolved", "executed": body["executed"]})
        return httpx.Response(200, json={"status": "EFFECT_VERIFIED",
                                         "verdict_source": "computed"})
    return handler


def _sync(seen: list[dict]) -> RemoraClient:
    http = httpx.Client(transport=httpx.MockTransport(_recording(seen)),
                        base_url="http://remora.test")
    return RemoraClient(base_url="http://remora.test", token="t", http_client=http)


def _async(seen: list[dict]) -> AsyncRemoraClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(_recording(seen)),
                             base_url="http://remora.test")
    return AsyncRemoraClient(base_url="http://remora.test", token="t", http_client=http)


def test_record_effect_hands_over_what_the_verifier_observed():
    seen: list[dict] = []
    recorded = _sync(seen).record_effect("p-1", _verification(),
                                         observed=OBSERVED, arguments=ARGUMENTS)
    body = seen[-1]["body"]
    assert seen[-1]["path"] == "/v1/execution/proposals/p-1/effect"
    assert body["observed"] == OBSERVED and body["arguments"] == ARGUMENTS
    assert recorded.verdict_source == "computed"


def test_record_effect_without_them_sends_what_it_sent_before():
    seen: list[dict] = []
    verification = _verification()
    _sync(seen).record_effect("p-1", verification)
    sent = seen[-1]["body"]
    assert "observed" not in sent and "arguments" not in sent
    assert {k: v for k, v in sent.items() if k not in ("tool_call_hash", "grant_jti")} == {
        k: v for k, v in verification.to_dict().items()
        if k not in ("tool_call_hash", "grant_jti")}


def test_async_record_effect_hands_over_the_same():
    seen: list[dict] = []
    asyncio.run(_async(seen).record_effect("p-1", _verification(),
                                           observed=OBSERVED, arguments=ARGUMENTS))
    assert seen[-1]["body"]["observed"] == OBSERVED
    assert seen[-1]["body"]["arguments"] == ARGUMENTS


@pytest.mark.parametrize("reason", ["", "   "])
def test_resolve_unknown_refuses_an_empty_reason_before_any_request(reason):
    seen: list[dict] = []
    with pytest.raises(ValueError, match="reason"):
        _sync(seen).resolve_unknown("op-1", executed=False, evidence_ref="journal:1",
                                    reason=reason)
    with pytest.raises(ValueError, match="reason"):
        asyncio.run(_async(seen).resolve_unknown("op-1", executed=False,
                                                 evidence_ref="journal:1", reason=reason))
    assert seen == []


def test_resolve_unknown_sends_a_given_reason():
    seen: list[dict] = []
    _sync(seen).resolve_unknown("op-1", executed=True, evidence_ref="journal:1",
                                reason="read back from the controller")
    assert seen[-1]["body"]["reason"] == "read back from the controller"
