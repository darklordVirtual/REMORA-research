# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
import logging
from typing import Any

from remora.observability.events import governance_event

from remora.enforcement.token import PolicyDecisionToken, TokenVerificationResult


@dataclass(frozen=True)
class EnforcementResult:
    """Result of an enforcement gate check."""
    allowed: bool
    action: str
    token_verified: bool
    reason: str
    strict_mode: bool



def _scalar(row: "tuple[Any, ...] | None", default: Any) -> Any:
    """First column of a single-row result, or *default* when there is none.

    COUNT(*) always returns a row, but the type checker cannot know that,
    and an unguarded subscript here is the same latent defect fixed in
    tenant_chain.py: an opaque 'NoneType' failure instead of a usable one.
    """
    return default if row is None else row[0]


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
    # Reject tokens whose issued_at is unreasonably old even if the signed
    # expiry is still in the future (defence in depth against long-TTL issuance).
    MAX_TOKEN_AGE_SECONDS = 3600

    def __init__(self, strict: bool = True, audience: str = "", dsn: str = "",
                 db_path: str = "", state_endpoint: str = "") -> None:
        self.strict = strict
        self.audience = audience
        self._dsn = dsn
        self._db_path = db_path
        # Durable ledger over the Worker's D1 binding, for a container with no
        # writable disk and no database credential. Found via decision-os-min's
        # HB-1 write-up: this gate knew REMORA_PG_DSN and REMORA_CHAIN_DB but
        # not the state endpoint, so the Cloudflare deployment silently fell to
        # the in-memory set — the exact replay-after-restart class the durable
        # ledger exists to close, reintroduced by a backend the guard accepted
        # but the gate never learned to use.
        self._state_endpoint = state_endpoint
        # One-time consumption: jti values this PEP has already executed on.
        import threading
        self._consumed: set[str] = set()
        self._consume_lock = threading.Lock()
        self._ensure_table()

    def _ensure_table(self) -> None:
        if self._dsn:
            import psycopg  # type: ignore
            with psycopg.connect(self._dsn) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pep_consumed (jti TEXT PRIMARY KEY, consumed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pep_ledger_watermark (id INTEGER PRIMARY KEY, issued_count BIGINT NOT NULL DEFAULT 0, last_reset_at TIMESTAMP WITH TIME ZONE, last_reset_reason TEXT)"
                )
                conn.commit()
        elif self._db_path:
            import sqlite3
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pep_consumed (jti TEXT PRIMARY KEY, consumed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pep_ledger_watermark (id INTEGER PRIMARY KEY, issued_count INTEGER NOT NULL DEFAULT 0, last_reset_at TIMESTAMP, last_reset_reason TEXT)"
                )
                conn.commit()
        elif self._state_endpoint:
            from remora.persistence.d1_connection import connect
            with connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pep_consumed (jti TEXT PRIMARY KEY, consumed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pep_ledger_watermark (id INTEGER PRIMARY KEY, issued_count INTEGER NOT NULL DEFAULT 0, last_reset_at TIMESTAMP, last_reset_reason TEXT)"
                )
                conn.commit()

    # -- ledger integrity (architect review 2026-08-05) --------------------
    #
    # The consumed-grant ledger is what makes a one-time grant one-time. A
    # deleted row does not fail anything — it silently re-authorizes an
    # execution that was already spent, which is the quietest failure in
    # the enforcement path. The audit chain is tamper-evident; moving the
    # tamper target to the ledger without giving it the same property just
    # relocates the problem.
    #
    # This does not prevent deletion (a database owner always can). It
    # makes deletion EVIDENT: a durable high-water mark counts grants ever
    # consumed, and a ledger holding fewer rows than that has lost some.
    # Legitimate pruning stays possible through an explicit reset, so the
    # discipline is "operator-authorized", not "impossible".

    def _bump_watermark(self, conn: Any) -> None:
        """Count one more consumed grant, in the caller's transaction.

        Same statement on both backends: no parameters, so no placeholder
        dialect difference to carry.
        """
        conn.execute(
            "INSERT INTO pep_ledger_watermark (id, issued_count) "
            "VALUES (1, 1) ON CONFLICT (id) DO UPDATE SET "
            "issued_count = pep_ledger_watermark.issued_count + 1"
        )

    def verify_ledger(self) -> dict[str, Any]:
        """Report whether the consumed-grant ledger still holds every grant.

        ``intact`` is ``True`` when the row count matches the high-water
        mark, ``False`` when rows are missing, and ``None`` when there is
        no durable ledger to verify — ``None`` means *unknown*, never
        *fine*, because an in-process ledger loses everything on restart
        and reporting it as intact would be a false comfort.
        """
        if self._dsn:
            import psycopg  # type: ignore

            with psycopg.connect(self._dsn) as conn:
                rows = _scalar(
                    conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone(), 0
                )
                mark = conn.execute(
                    "SELECT issued_count, last_reset_reason FROM "
                    "pep_ledger_watermark WHERE id = 1"
                ).fetchone()
        elif self._db_path:
            import sqlite3

            with sqlite3.connect(self._db_path) as conn:
                rows = _scalar(
                    conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone(), 0
                )
                mark = conn.execute(
                    "SELECT issued_count, last_reset_reason FROM "
                    "pep_ledger_watermark WHERE id = 1"
                ).fetchone()
        elif self._state_endpoint:
            from remora.persistence.d1_connection import connect
            with connect() as conn:
                rows = _scalar(
                    conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone(), 0
                )
                mark = conn.execute(
                    "SELECT issued_count, last_reset_reason "
                    "FROM pep_ledger_watermark WHERE id = 1"
                ).fetchone()
        else:
            return {
                "durable": False,
                "intact": None,
                "consumed_rows": len(self._consumed),
                "high_water_mark": None,
                "last_reset_reason": None,
                "problems": [
                    "in-process ledger: consumed grants are lost on restart, "
                    "so integrity cannot be verified. Set REMORA_PG_DSN or "
                    "REMORA_CHAIN_DB."
                ],
            }

        issued = int(mark[0]) if mark else 0
        reason = mark[1] if mark else None
        problems: list[str] = []
        if rows < issued:
            problems.append(
                f"ledger holds {rows} consumed grants but {issued} were "
                f"consumed: {issued - rows} missing. A deleted grant is "
                "replayable — investigate before trusting one-time "
                "authorization, and reset the watermark only if the removal "
                "was a deliberate, authorized prune."
            )
        return {
            "durable": True,
            "intact": not problems,
            "consumed_rows": int(rows),
            "high_water_mark": issued,
            "last_reset_reason": reason,
            "problems": problems,
        }

    def reset_ledger_watermark(self, *, reason: str) -> None:
        """Re-baseline the mark after an authorized prune. Reason required.

        Deliberately explicit: an unexplained reset is indistinguishable
        from covering up a deletion, so the reason is stored alongside the
        new mark and surfaced by :meth:`verify_ledger`.
        """
        if not reason or not reason.strip():
            raise ValueError("resetting the ledger watermark requires a reason")
        if self._dsn:
            import psycopg  # type: ignore

            with psycopg.connect(self._dsn) as conn:
                count = _scalar(
                    conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone(), 0
                )
                conn.execute(
                    "INSERT INTO pep_ledger_watermark "
                    "(id, issued_count, last_reset_at, last_reset_reason) "
                    "VALUES (1, %s, CURRENT_TIMESTAMP, %s) "
                    "ON CONFLICT (id) DO UPDATE SET issued_count = EXCLUDED.issued_count, "
                    "last_reset_at = EXCLUDED.last_reset_at, "
                    "last_reset_reason = EXCLUDED.last_reset_reason",
                    (count, reason),
                )
                conn.commit()
        elif self._db_path:
            import sqlite3

            with sqlite3.connect(self._db_path) as conn:
                count = _scalar(
                    conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone(), 0
                )
                conn.execute(
                    "INSERT INTO pep_ledger_watermark "
                    "(id, issued_count, last_reset_at, last_reset_reason) "
                    "VALUES (1, ?, CURRENT_TIMESTAMP, ?) "
                    "ON CONFLICT (id) DO UPDATE SET issued_count = excluded.issued_count, "
                    "last_reset_at = excluded.last_reset_at, "
                    "last_reset_reason = excluded.last_reset_reason",
                    (count, reason),
                )
                conn.commit()
        else:
            raise RuntimeError(
                "no durable ledger to re-baseline; the in-process ledger has "
                "no watermark"
            )

    def check(
        self,
        token: PolicyDecisionToken,
        expected_observation_hash: str | None = None,
        consume: bool = False,
        now: str | None = None,
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
        vr: TokenVerificationResult = token.verify(expected_observation_hash, now=now)

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

        # Audience binding: a gate configured with an audience only honours
        # tokens addressed to it.
        if self.audience and token.audience != self.audience:
            return EnforcementResult(
                allowed=False,
                action=token.action,
                token_verified=True,
                reason="audience_mismatch",
                strict_mode=self.strict,
            )

        # Maximum token age from issued_at (independent of the signed expiry).
        # Malformed or ambiguous timestamps fail CLOSED with a machine-readable
        # reason — check() must never raise an uncaught naive/aware TypeError
        # (a naive issued_at parsed fine but exploded on subtraction against
        # the aware clock; coerce both sides to UTC like token.verify does).
        from datetime import datetime
        try:
            issued = datetime.fromisoformat(token.issued_at.replace("Z", "+00:00"))
            current = (
                datetime.fromisoformat(now.replace("Z", "+00:00"))
                if now is not None else datetime.now(UTC)
            )
            if issued.tzinfo is None:
                issued = issued.replace(tzinfo=UTC)
            if current.tzinfo is None:
                current = current.replace(tzinfo=UTC)
            age_seconds = (current - issued).total_seconds()
        except (ValueError, TypeError):
            return EnforcementResult(
                allowed=False,
                action=token.action,
                token_verified=True,
                reason="issued_at_unparseable",
                strict_mode=self.strict,
            )
        if age_seconds < 0:
            # Future issued_at: clock-skewed or malicious issuer input. Same
            # fail-closed posture as token.verify's current < issued check,
            # enforced here too because non-strict unsigned flows can reach
            # this point without a verified expiry window.
            return EnforcementResult(
                allowed=False,
                action=token.action,
                token_verified=True,
                reason="token_issued_in_future",
                strict_mode=self.strict,
            )
        if age_seconds > self.MAX_TOKEN_AGE_SECONDS:
            return EnforcementResult(
                allowed=False,
                action=token.action,
                token_verified=True,
                reason="token_too_old",
                strict_mode=self.strict,
            )

        allowed = token.action in self.ACCEPT_ACTIONS
        reason = "accept" if allowed else f"decision_{token.action}_not_accept"

        # One-time consumption (atomic check-and-consume under the lock):
        # a jti this gate has executed on can never authorise again.
        if token.jti:
            if self._dsn:
                import psycopg  # type: ignore
                try:
                    with psycopg.connect(self._dsn) as conn:
                        if allowed and consume:
                            with conn.transaction():
                                conn.execute("INSERT INTO pep_consumed (jti) VALUES (%s)", (token.jti,))
                                self._bump_watermark(conn)
                        else:
                            row = conn.execute("SELECT 1 FROM pep_consumed WHERE jti = %s", (token.jti,)).fetchone()
                            if row:
                                raise psycopg.IntegrityError()
                except psycopg.IntegrityError:
                    return EnforcementResult(
                        allowed=False,
                        action=token.action,
                        token_verified=True,
                        reason="token_already_consumed",
                        strict_mode=self.strict,
                    )
            elif self._db_path:
                import sqlite3
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        if allowed and consume:
                            conn.execute("INSERT INTO pep_consumed (jti) VALUES (?)", (token.jti,))
                            self._bump_watermark(conn)
                            conn.commit()
                        else:
                            row = conn.execute("SELECT 1 FROM pep_consumed WHERE jti = ?", (token.jti,)).fetchone()
                            if row:
                                raise sqlite3.IntegrityError()
                except sqlite3.IntegrityError:
                    return EnforcementResult(
                        allowed=False,
                        action=token.action,
                        token_verified=True,
                        reason="token_already_consumed",
                        strict_mode=self.strict,
                    )
            elif self._state_endpoint:
                from remora.persistence.d1_connection import (
                    D1Unavailable,
                    connect,
                )
                try:
                    with connect() as conn:
                        if allowed and consume:
                            # INSERT + watermark commit as ONE atomic batch:
                            # the PRIMARY KEY is the compare-and-set, so of
                            # two racers exactly one commit succeeds and the
                            # other surfaces the UNIQUE violation below.
                            conn.execute(
                                "INSERT INTO pep_consumed (jti) VALUES (?)",
                                (token.jti,))
                            self._bump_watermark(conn)
                        else:
                            row = conn.execute(
                                "SELECT 1 FROM pep_consumed WHERE jti = ?",
                                (token.jti,)).fetchone()
                            if row:
                                return EnforcementResult(
                                    allowed=False,
                                    action=token.action,
                                    token_verified=True,
                                    reason="token_already_consumed",
                                    strict_mode=self.strict,
                                )
                except D1Unavailable as exc:
                    if "UNIQUE" in str(exc):
                        return EnforcementResult(
                            allowed=False,
                            action=token.action,
                            token_verified=True,
                            reason="token_already_consumed",
                            strict_mode=self.strict,
                        )
                    # The store the one-time property lives in cannot be
                    # reached. Assuming unspent is exactly the double-spend
                    # the ledger exists to prevent, so this fails closed.
                    return EnforcementResult(
                        allowed=False,
                        action=token.action,
                        token_verified=True,
                        reason="consumed_ledger_unavailable",
                        strict_mode=self.strict,
                    )
            else:
                with self._consume_lock:
                    if token.jti in self._consumed:
                        return EnforcementResult(
                            allowed=False,
                            action=token.action,
                            token_verified=True,
                            reason="token_already_consumed",
                            strict_mode=self.strict,
                        )
                    if allowed and consume:
                        self._consumed.add(token.jti)

        result = EnforcementResult(
            allowed=allowed,
            action=token.action,
            token_verified=vr.verified or (not token.is_signed and not self.strict),
            reason=reason,
            strict_mode=self.strict,
        )
        # The PEP decision is the single most operationally interesting event
        # in the system: it is where an authorization is spent or refused.
        governance_event(
            "grant.checked",
            level=logging.INFO if result.allowed else logging.WARNING,
            allowed=result.allowed,
            action=result.action,
            reason=result.reason,
            token_jti=token.jti,
            consumed=bool(consume and result.allowed),
            strict_mode=self.strict,
            token_verified=result.token_verified,
        )
        return result

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
        # The execution path always consumes: one grant, one execution.
        result = self.check(token, expected_observation_hash, consume=True)
        if not result.allowed:
            raise PermissionError(
                f"EnforcementGate: execution blocked. "
                f"action={token.action!r}, reason={result.reason!r}, "
                f"strict={self.strict}"
            )
        return action_fn()
