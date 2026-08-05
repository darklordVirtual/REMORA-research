# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Synchronous REMORA client for third-party integrators.

``RemoraClient`` is the remote-mode entry point: the application sends
proposals over HTTPS; policy evaluation, human review, token/lease
binding, enforcement and the audit chain stay inside the REMORA control
plane. The SDK provides no bypass operation; actual non-bypassability
depends on deploying REMORA as the exclusive credential-holding
execution path (the agent holds no tool credentials and no direct
route to the governed side effects).

Requires the ``sdk`` extra (``pip install "remora[sdk]"``) for httpx.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

try:
    import httpx
except ImportError as exc:  # pragma: no cover - exercised only without extra
    raise ImportError(
        'RemoraClient requires httpx; install with pip install "remora[sdk]"'
    ) from exc

from remora.sdk.errors import (
    ApprovalExpiredError,
    AuthenticationError,
    AuthorizationError,
    BindingRefusedError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    RemoraError,
    RemoraUnavailableError,
    ReplayRefusedError,
    ServerError,
)
from remora.sdk.effects import EffectVerificationView
from remora.sdk.models import (
    ApprovalResult,
    AssessmentResult,
    AuditVerification,
    ExecutionResult,
    LifecycleTrail,
    ProposalView,
    RejectionResult,
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
        used for in-process testing against an ASGI app. An injected
        client is OWNED BY THE CALLER: :meth:`close` never closes it, so
        shared transports and connection pools survive (review
        2026-08-05). Only a client this constructor created itself is
        closed.
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
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            base_url=base_url, timeout=timeout,
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the transport this client created; never an injected one."""
        if self._owns_http:
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

    def reject(self, review_item_id: str, *, reason: str) -> RejectionResult:
        """Refuse a pending review item, terminally.

        The counterpart to :meth:`approve`. ``reason`` is mandatory: an
        unexplained refusal cannot be reviewed after the fact. A rejected
        item can never be approved or executed afterwards.
        """
        payload = self._request("POST", "/v1/execution/reject", json={
            "item_id": review_item_id, "reason": reason,
        })
        return RejectionResult.from_payload(payload)

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

    def execute_accepted(
        self, execution_token: Mapping[str, Any], tool_call: ToolCall
    ) -> ExecutionResult:
        """Redeem an ACCEPT token and dispatch the call it authorizes.

        The direct-ACCEPT counterpart of :meth:`execute`: no review item is
        involved, because the token itself is the authorization. Pass the
        ``execution_token`` from :class:`AssessmentResult` together with the
        SAME ``tool_call`` that was assessed — the server re-hashes the
        payload and refuses a mismatch (:class:`BindingRefusedError`)
        before anything runs.

        Raises :class:`ReplayRefusedError` if the grant was already
        consumed, :class:`ApprovalExpiredError` if the token is past its
        TTL, and :class:`BindingRefusedError` on payload drift.
        """
        payload = self._request("POST", "/v1/execution/execute-accepted", json={
            "execution_token": dict(execution_token),
            "tool_call": tool_call.to_payload(),
        })
        return ExecutionResult.from_payload(payload)

    def record_effect(self, proposal_id: str,
                      verification: "EffectVerificationView") -> "EffectVerificationView":
        """Hand a verification you performed back to REMORA for recording.

        Verification runs in YOUR process because the reader holds the
        credentials; REMORA never reaches into your system of record. The
        chain therefore stores this as an attestation by the verifier
        named in the record, and only its hashes cross the boundary — the
        observed values stay with you.

        Recorded exactly as reported, mismatches included.
        """
        payload = self._request(
            "POST", f"/v1/execution/proposals/{proposal_id}/effect",
            json=verification.to_dict(),
        )
        return EffectVerificationView.from_payload(
            {**verification.to_dict(), **payload}
        )

    def get_proposal(self, proposal_id: str) -> ProposalView:
        """The decision and current state of one proposal."""
        payload = self._request(
            "GET", f"/v1/execution/proposals/{proposal_id}",
        )
        return ProposalView.from_payload(payload)

    def get_lifecycle(self, proposal_id: str) -> LifecycleTrail:
        """The ordered event trail for one proposal."""
        payload = self._request(
            "GET", f"/v1/execution/proposals/{proposal_id}/lifecycle",
        )
        return LifecycleTrail.from_payload(payload)

    def export_evidence(self, proposal_id: str) -> "dict[str, Any]":
        """The evidence bundle: every recorded section plus a hashed manifest.

        Returned as the raw mapping on purpose — the manifest's hashes are
        computed over the exact JSON sections, so re-shaping them into
        typed models here would break independent verification.
        """
        return self._request(
            "GET", f"/v1/execution/proposals/{proposal_id}/evidence",
        )

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
        return error_for_response(response)


def error_for_response(response: "httpx.Response") -> RemoraError:
    """Map an HTTP error response to the typed hierarchy.

    Shared by the sync and async clients so the two can never drift on
    error semantics.
    """
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
    if response.status_code == 409:
        # The server says 409 for every "authorization cannot be honoured";
        # the detail names WHICH one, and integrators must not have to
        # parse prose to tell a replay from a payload mismatch.
        lowered = detail.lower()
        if "binding refused" in lowered:
            return BindingRefusedError(detail)
        if "consumed" in lowered or "replay" in lowered:
            return ReplayRefusedError(detail)
        if "expired" in lowered or "too old" in lowered:
            return ApprovalExpiredError(detail)
    exc_type = _STATUS_ERRORS.get(response.status_code, RemoraError)
    return exc_type(detail)
