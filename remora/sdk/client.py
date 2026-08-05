# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Synchronous REMORA client for third-party integrators.

``RemoraClient`` is the remote-mode entry point: the application sends
proposals over HTTPS; policy evaluation, human review, token/lease
binding, enforcement and the audit chain stay inside the REMORA control
plane. The client owns no tool credentials and cannot bypass a decision.

Requires the ``sdk`` extra (``pip install "remora[sdk]"``) for httpx.
"""
from __future__ import annotations

import json
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover - exercised only without extra
    raise ImportError(
        'RemoraClient requires httpx; install with pip install "remora[sdk]"'
    ) from exc

from remora.sdk.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    RemoraError,
    RemoraUnavailableError,
    ServerError,
)
from remora.sdk.models import (
    ApprovalResult,
    AssessmentResult,
    AuditVerification,
    ExecutionResult,
    ToolCall,
)

__all__ = ["RemoraClient"]

_STATUS_ERRORS: dict[int, type[RemoraError]] = {
    401: AuthenticationError,
    403: AuthorizationError,
    404: NotFoundError,
    409: ConflictError,
    422: InvalidRequestError,
}


class RemoraClient:
    """Talks to a REMORA control plane over its stable REST contract.

    Parameters
    ----------
    base_url:
        Root of the control plane, e.g. ``https://remora.internal``.
    token:
        Bearer token; sent as ``Authorization: Bearer <token>``.
    tenant / role:
        Optional ``X-Remora-Tenant`` / ``X-Remora-Role`` headers for
        single-token deployments (the server ignores the role claim in
        production).
    timeout:
        Per-request timeout in seconds.
    http_client:
        Optional pre-configured ``httpx.Client`` (its ``base_url`` wins);
        used for in-process testing against an ASGI app. The caller-
        provided client is still closed by :meth:`close`.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        tenant: str | None = None,
        role: str | None = None,
        timeout: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._headers: dict[str, str] = {}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        if tenant:
            self._headers["X-Remora-Tenant"] = tenant
        if role:
            self._headers["X-Remora-Role"] = role
        self._http = http_client or httpx.Client(
            base_url=base_url, timeout=timeout,
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> RemoraClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- operations --------------------------------------------------------

    def assess(self, tool_call: ToolCall) -> AssessmentResult:
        """Ask the control plane what should happen to this call.

        Nothing executes here. ACCEPT returns a signed single-use
        execution token; VERIFY/ESCALATE enqueue a human review item
        (``review_item_id``); ABSTAIN returns neither.
        """
        payload = self._request(
            "POST", "/v1/execution/assess", json=tool_call.to_payload(),
        )
        return AssessmentResult.from_payload(payload)

    def approve(
        self,
        review_item_id: str,
        *,
        ttl_seconds: int = 900,
        on_behalf_of: str | None = None,
    ) -> ApprovalResult:
        """Approve a pending review item for at most ``ttl_seconds``.

        The audited approver identity is always the authenticated
        principal of the bearer token; ``on_behalf_of`` is recorded as an
        unverified annotation and can never delegate authority.
        """
        body: dict[str, Any] = {
            "item_id": review_item_id,
            "approval_ttl_seconds": ttl_seconds,
        }
        if on_behalf_of is not None:
            body["on_behalf_of"] = on_behalf_of
        payload = self._request("POST", "/v1/execution/approve", json=body)
        return ApprovalResult.from_payload(payload)

    def execute(self, review_item_id: str, tool_call: ToolCall) -> ExecutionResult:
        """Execute an approved review item by re-presenting the full call.

        The complete payload is sent again so the server can re-bind the
        exact approved arguments; any drift from the assessed call is
        refused (``binding_refused``), as are expired or invalidated
        approvals.
        """
        payload = self._request("POST", "/v1/execution/execute", json={
            "item_id": review_item_id,
            "tool_call": tool_call.to_payload(),
        })
        return ExecutionResult.from_payload(payload)

    def verify_audit_chain(self) -> AuditVerification:
        """Verify the authenticated tenant's audit chain end to end."""
        payload = self._request("GET", "/v1/execution/audit/verify")
        return AuditVerification.from_payload(payload)

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str,
                 json: Any = None) -> dict[str, Any]:
        json_body = json
        try:
            response = self._http.request(
                method, path, json=json_body, headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise RemoraUnavailableError(
                f"REMORA control plane unreachable: {exc}",
            ) from exc
        if response.status_code >= 400:
            raise self._error_for(response)
        return response.json()

    @staticmethod
    def _error_for(response: httpx.Response) -> RemoraError:
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        detail = str(body.get("detail") or f"HTTP {response.status_code}")
        if response.status_code == 429:
            retry_after: float | None = None
            header = response.headers.get("Retry-After")
            if header is not None:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = None
            return RateLimitedError(detail, retry_after=retry_after)
        if response.status_code >= 500:
            return ServerError(detail, request_id=body.get("correlation_id"))
        exc_type = _STATUS_ERRORS.get(response.status_code, RemoraError)
        return exc_type(detail)
