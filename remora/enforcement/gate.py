# Author: Stian Skogbrott
# License: Apache-2.0
"""EnforcementGate — Policy Enforcement Point (PEP) for REMORA.

Implements intern_forbedring.txt §5.A-B (REM-013): the PEP layer verifies
a signed PolicyDecisionToken from the PDP before allowing action execution.

Without a valid token, the gate fails closed (refuses to execute).

ARCHITECTURAL BOUNDARY (REM-013): The PEP must never call the PDP directly.
It receives a signed token from outside (via the API or orchestrator) and
verifies it before enforcement. This separation ensures the enforcement layer
cannot be bypassed by re-using a stale token or forging a decision.

Enforcement levels:
    strict=True  — reject unsigned tokens (production mode)
    strict=False — allow unsigned tokens with warning (development mode)
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Callable

from remora.enforcement.token import PolicyDecisionToken, TokenVerificationResult


@dataclass(frozen=True)
class EnforcementResult:
    """Result of an enforcement gate check."""
    allowed: bool
    action: str
    token_verified: bool
    reason: str
    strict_mode: bool


class EnforcementGate:
    """Policy Enforcement Point — verifies signed PDP tokens before execution.

    In strict mode (production), unsigned tokens are rejected.
    In non-strict mode (development), unsigned tokens are allowed with a warning.

    Usage::

        gate = EnforcementGate(strict=True)
        result = gate.check(token)
        if result.allowed:
            execute_tool(...)
        else:
            raise RuntimeError(f"Enforcement gate blocked: {result.reason}")
    """

    ACCEPT_ACTIONS = frozenset({"accept"})

    def __init__(self, strict: bool = True) -> None:
        self.strict = strict

    def check(
        self,
        token: PolicyDecisionToken,
        expected_observation_hash: str | None = None,
    ) -> EnforcementResult:
        """Check whether the token authorizes execution.

        Args:
            token: PolicyDecisionToken from the PDP layer.
            expected_observation_hash: If provided, verify the token's observation
                hash matches (prevents token reuse for a different observation).

        Returns:
            EnforcementResult with allowed=True only if the token is valid and
            the decision is ACCEPT.
        """
        # Verify signature
        vr: TokenVerificationResult = token.verify(expected_observation_hash)

        if not vr.verified:
            if not token.is_signed and not self.strict:
                # Development mode: allow unsigned tokens with warning
                warnings.warn(
                    f"EnforcementGate: unsigned token accepted in non-strict mode "
                    f"(reason: {vr.reason}). Set REMORA_PDP_SIGNING_KEY for production.",
                    stacklevel=2,
                )
            elif not vr.verified:
                return EnforcementResult(
                    allowed=False,
                    action=token.action,
                    token_verified=False,
                    reason=f"token_verification_failed:{vr.reason}",
                    strict_mode=self.strict,
                )

        allowed = token.action in self.ACCEPT_ACTIONS
        reason = "accept" if allowed else f"decision_{token.action}_not_accept"

        return EnforcementResult(
            allowed=allowed,
            action=token.action,
            token_verified=vr.verified or (not token.is_signed and not self.strict),
            reason=reason,
            strict_mode=self.strict,
        )

    def enforce(
        self,
        token: PolicyDecisionToken,
        action_fn: Callable[[], Any],
        expected_observation_hash: str | None = None,
    ) -> Any:
        """Execute action_fn only if the token authorizes it.

        Raises:
            PermissionError: if the token is invalid or the decision is not ACCEPT.
        """
        result = self.check(token, expected_observation_hash)
        if not result.allowed:
            raise PermissionError(
                f"EnforcementGate: execution blocked. "
                f"action={token.action!r}, reason={result.reason!r}, "
                f"strict={self.strict}"
            )
        return action_fn()
