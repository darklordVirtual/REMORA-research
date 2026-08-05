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

from remora.sdk.client import error_for_response
from remora.sdk.errors import RemoraUnavailableError
from remora.sdk.models import (
    ApprovalResult,
    AssessmentResult,
    AuditVerification,
    ExecutionResult,
    ToolCall,
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

    async def execute(
        self, review_item_id: str, tool_call: ToolCall
    ) -> ExecutionResult:
        """Async :meth:`RemoraClient.execute`; same exact-call re-binding."""
        payload = await self._request("POST", "/v1/execution/execute", json={
            "item_id": review_item_id,
            "tool_call": tool_call.to_payload(),
        })
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

    async def verify_audit_chain(self) -> AuditVerification:
        """Async :meth:`RemoraClient.verify_audit_chain`."""
        payload = await self._request("GET", "/v1/execution/audit/verify")
        return AuditVerification.from_payload(payload)

    # -- transport ---------------------------------------------------------

    async def _request(self, method: str, path: str,
                       json: Any = None) -> dict[str, Any]:
        json_body = json
        try:
            response = await self._http.request(
                method, path, json=json_body, headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise RemoraUnavailableError(
                f"REMORA control plane unreachable: {exc}",
            ) from exc
        if response.status_code >= 400:
            raise error_for_response(response)
        return response.json()
