# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Typed error hierarchy for the REMORA SDK.

SDK users handle governance failures as typed exceptions, never by
interpreting HTTP statuses or detail strings. Every SDK error carries a
stable ``code`` (an SDK-side taxonomy — the REST API does not yet emit
machine error codes), an optional ``request_id`` for correlation (the
server's ``correlation_id`` on 5xx responses), and a ``retryable`` flag
that a caller can act on directly (fail closed when ``False``).
"""
from __future__ import annotations

__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "ConflictError",
    "InvalidRequestError",
    "NotFoundError",
    "RateLimitedError",
    "RemoraError",
    "RemoraUnavailableError",
    "ServerError",
]


class RemoraError(Exception):
    """Base class for every error raised by the REMORA SDK."""

    code: str = "remora_error"
    retryable: bool = False

    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


class AuthenticationError(RemoraError):
    """The bearer token is missing or invalid (HTTP 401)."""

    code = "authentication_failed"


class AuthorizationError(RemoraError):
    """The authenticated principal lacks the required capability (HTTP 403)."""

    code = "authorization_denied"


class NotFoundError(RemoraError):
    """The referenced resource does not exist for this tenant (HTTP 404)."""

    code = "not_found"


class ConflictError(RemoraError):
    """The resource is not in a state that permits the operation (HTTP 409)."""

    code = "conflict"


class InvalidRequestError(RemoraError):
    """The request payload failed server-side validation (HTTP 422)."""

    code = "invalid_request"


class RateLimitedError(RemoraError):
    """The tenant rate limit was hit (HTTP 429); retry after ``retry_after``."""

    code = "rate_limited"
    retryable = True

    def __init__(self, message: str, *, request_id: str | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message, request_id=request_id)
        self.retry_after = retry_after


class ServerError(RemoraError):
    """The server failed (HTTP 5xx); ``request_id`` is its correlation id."""

    code = "server_error"


class RemoraUnavailableError(RemoraError):
    """The control plane could not be reached at the transport level."""

    code = "unavailable"
    retryable = True


# ── Execution-refusal errors (AAE §12) ─────────────────────────────────────
#
# The server answers every one of these with HTTP 409, because they are all
# "your request was well-formed but this authorization cannot be honoured".
# Collapsing them into one ConflictError would force integrators to parse
# detail strings to tell a replay from a payload mismatch — exactly what a
# typed hierarchy exists to prevent. They are subclasses of ConflictError so
# existing `except ConflictError` handlers keep working.


class BindingRefusedError(ConflictError):
    """The presented tool call is not the one the authorization covers.

    Not retryable by re-sending: the authorization is bound to an exact
    payload, so a different payload needs its own assessment.
    """

    code = "binding_refused"


class ReplayRefusedError(ConflictError):
    """The execution grant was already consumed.

    The side effect may well have happened on the first redemption — this
    is a refusal to run it twice, not evidence that nothing ran.
    """

    code = "replay_refused"


class ApprovalExpiredError(ConflictError):
    """The approval or execution token is no longer valid in time.

    Retryable only through a fresh decision: re-approving the same stale
    grant would defeat the TTL it exists to enforce.
    """

    code = "approval_expired"
    retryable = True


class UnknownExecutionStateError(RemoraError):
    """The outcome of an execution is undeterminable.

    Deliberately NOT retryable: the side effect may already have happened,
    and re-running is the one move the execution layer must never make.
    Resolution is an operator decision.
    """

    code = "unknown_execution_state"
