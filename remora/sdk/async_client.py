# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Asynchronous REMORA client for third-party integrators.

``AsyncRemoraClient`` mirrors :class:`remora.sdk.client.RemoraClient`
operation for operation over ``httpx.AsyncClient``: same paths, same
headers, same request bodies, same result models, and the SAME
status→error mapping (shared ``error_for_response``, so the two clients
cannot drift on error semantics). The SDK provides no bypass operation;
actual non-bypassability depends on deploying REMORA as the exclusive
credential-holding execution path.

Requires the ``sdk`` extra (``pip install "remora[sdk]"``) for httpx.
"""
from __future__ import annotations

from typing import Any, Mapping

try:
    import httpx
except ImportError as exc:  # pragma: no cover - exercised only without extra
    raise ImportError(
        'AsyncRemoraClient requires httpx; install with pip install "remora[sdk]"'
    ) from exc

from remora.sdk.client import (
    bind_verification,
    dispatch_binding,
    error_for_response,
    success_body,
    transport_error_for,
)
from remora.sdk.effects import EffectVerificationView
from remora.sdk.models import (
    ApprovalResult,
    AssessmentResult,
    AuditVerification,
    ExecutionResult,
    LifecycleTrail,
    LimitResolution,
    PendingExecution,
    ProposalView,
    RejectionResult,
    ReviewPacketView,
    ToolCall,
    UnresolvedOperation,
)

__all__ = ["AsyncRemoraClient"]


class AsyncRemoraClient:
    """Async twin of :class:`~remora.sdk.client.RemoraClient`.

    Constructor parameters are identical to the sync client; the
    ``http_client`` override takes an ``httpx.AsyncClient`` (e.g. wrapping
    ``httpx.ASGITransport`` for in-process testing). An injected client is
    owned by the caller — :meth:`aclose` never closes it.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        tenant: str | None = None,
        role: str | None = None,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._headers: dict[str, str] = {}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        if tenant:
            self._headers["X-Remora-Tenant"] = tenant
        if role:
            self._headers["X-Remora-Role"] = role
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=base_url, timeout=timeout,
        )

    # -- lifecycle ---------------------------------------------------------

    async def aclose(self) -> None:
        """Close the transport this client created; never an injected one."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncRemoraClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- operations --------------------------------------------------------

    async def assess(self, tool_call: ToolCall) -> AssessmentResult:
        """Async :meth:`RemoraClient.assess` — nothing executes here."""
        payload = await self._request(
            "POST", "/v1/execution/assess", json=tool_call.to_payload(),
        )
        return AssessmentResult.from_payload(payload)

    async def approve(
        self,
        review_item_id: str,
        *,
        ttl_seconds: int = 900,
        on_behalf_of: str | None = None,
    ) -> ApprovalResult:
        """Async :meth:`RemoraClient.approve`; same identity rules."""
        body: dict[str, Any] = {
            "item_id": review_item_id,
            "approval_ttl_seconds": ttl_seconds,
        }
        if on_behalf_of is not None:
            body["on_behalf_of"] = on_behalf_of
        payload = await self._request("POST", "/v1/execution/approve", json=body)
        return ApprovalResult.from_payload(payload)

    async def reject(self, review_item_id: str, *, reason: str) -> RejectionResult:
        """Async :meth:`RemoraClient.reject`; same mandatory reason."""
        payload = await self._request("POST", "/v1/execution/reject", json={
            "item_id": review_item_id, "reason": reason,
        })
        return RejectionResult.from_payload(payload)

    async def execute(
        self, review_item_id: str, tool_call: ToolCall
    ) -> "ExecutionResult | PendingExecution":
        """Async :meth:`RemoraClient.execute`; same exact-call re-binding
        and the same async-dispatch union (issue #419): a 202 returns
        :class:`PendingExecution` — poll the proposal for the outcome."""
        payload = await self._request("POST", "/v1/execution/execute", json={
            "item_id": review_item_id,
            "tool_call": tool_call.to_payload(),
        })
        if payload.get("dispatch") == "pending":
            return PendingExecution.from_payload(payload)
        return ExecutionResult.from_payload(payload)

    async def execute_accepted(
        self, execution_token: Mapping[str, Any], tool_call: ToolCall
    ) -> ExecutionResult:
        """Async :meth:`RemoraClient.execute_accepted`; same refusals."""
        payload = await self._request(
            "POST", "/v1/execution/execute-accepted", json={
                "execution_token": dict(execution_token),
                "tool_call": tool_call.to_payload(),
            },
        )
        return ExecutionResult.from_payload(payload)

    async def record_effect(self, proposal_id: str,
                            verification: "EffectVerificationView", *,
                            observed: "Mapping[str, Any] | None" = None,
                            arguments: "Mapping[str, Any] | None" = None,
                            ) -> "EffectVerificationView":
        """Hand a verification you performed back to REMORA for recording.

        Verification runs in YOUR process because the reader holds the
        credentials; REMORA never reaches into your system of record. The
        chain therefore stores this as an attestation by the verifier
        named in the record, and only its hashes cross the boundary — the
        observed values stay with you.

        Recorded exactly as reported, mismatches included. A settled verdict
        names the dispatch it observed, read from the proposal's lifecycle
        as :meth:`RemoraClient.record_effect` does.
        """
        body = verification.to_dict()
        if not body.get("tool_call_hash") or not body.get("grant_jti"):
            trail = await self._request(
                "GET", f"/v1/execution/proposals/{proposal_id}/lifecycle")
            body = bind_verification(body, dispatch_binding(trail))
        # What the verifier read and the approved arguments. With both, the
        # server instantiates the signed postcondition and computes the verdict
        # itself; without them the record stays the verifier's claim.
        if observed is not None:
            body["observed"] = dict(observed)
        if arguments is not None:
            body["arguments"] = dict(arguments)
        payload = await self._request(
            "POST", f"/v1/execution/proposals/{proposal_id}/effect",
            json=body,
        )
        return EffectVerificationView.from_payload(
            {**verification.to_dict(), **payload}
        )

    async def get_proposal(self, proposal_id: str) -> ProposalView:
        """Async :meth:`RemoraClient.get_proposal`."""
        payload = await self._request(
            "GET", f"/v1/execution/proposals/{proposal_id}",
        )
        return ProposalView.from_payload(payload)

    async def get_lifecycle(self, proposal_id: str) -> LifecycleTrail:
        """Async :meth:`RemoraClient.get_lifecycle`."""
        payload = await self._request(
            "GET", f"/v1/execution/proposals/{proposal_id}/lifecycle",
        )
        return LifecycleTrail.from_payload(payload)

    async def get_review_packet(self, proposal_id: str) -> ReviewPacketView:
        """Async :meth:`RemoraClient.get_review_packet`."""
        payload = await self._request(
            "GET", f"/v1/execution/proposals/{proposal_id}/review-packet",
        )
        return ReviewPacketView.from_payload(payload)

    async def export_evidence(self, proposal_id: str) -> "dict[str, Any]":
        """Async :meth:`RemoraClient.export_evidence`; raw by design."""
        return await self._request(
            "GET", f"/v1/execution/proposals/{proposal_id}/evidence",
        )

    async def verify_audit_chain(self) -> AuditVerification:
        """Async :meth:`RemoraClient.verify_audit_chain`."""
        payload = await self._request("GET", "/v1/execution/audit/verify")
        return AuditVerification.from_payload(payload)

    async def list_unresolved(self) -> tuple[UnresolvedOperation, ...]:
        """Async :meth:`RemoraClient.list_unresolved`."""
        payload = await self._request("GET", "/v1/execution/limits/unresolved")
        return tuple(UnresolvedOperation.from_payload(op)
                     for op in payload.get("operations", []))

    async def resolve_unknown(self, operation_id: str, *, executed: bool,
                              evidence_ref: str, reason: str = "") -> LimitResolution:
        """Async :meth:`RemoraClient.resolve_unknown`."""
        if not reason.strip():
            raise ValueError("resolve_unknown needs a reason: the route refuses an empty one")
        payload = await self._request("POST", "/v1/execution/limits/resolve", json={
            "operation_id": operation_id, "executed": executed,
            "evidence_ref": evidence_ref, "reason": reason,
        })
        return LimitResolution.from_payload(payload)

    # -- transport ---------------------------------------------------------

    async def _request(self, method: str, path: str,
                       json: Any = None) -> dict[str, Any]:
        json_body = json
        try:
            response = await self._http.request(
                method, path, json=json_body, headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise transport_error_for(exc, path, method) from exc
        if response.status_code >= 400:
            raise error_for_response(response)
        return success_body(response, path)
