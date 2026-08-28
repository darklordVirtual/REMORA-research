# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Structured operational logging for the trusted computing base.

Until 2026-08-20 the safety core emitted nothing: `remora/policy`,
`remora/enforcement` and `remora/execution` held zero loggers between them,
so when a grant was refused or a dispatch failed in production there was no
log line — only whatever the tenant audit chain happened to record. The two
answer different questions. The audit chain is the governance record: what
was authorised, under which policy, by whom. This is the operational record:
what the process did, when, and how long it took, so a pilot can be run and
debugged without reading the chain.

Design constraints, in order:

1. **Never log a secret.** Two layers, because one was not enough. Field names
   are screened against a deny-list and the emitter raises rather than logging
   something that looks like a credential. Field VALUES are then redacted for
   credential-shaped and location-shaped runs, because a free-text field like
   ``detail=str(exc)`` carries whatever a downstream library put in its
   exception message, under a field name nothing would object to. A logging
   call must never become the reason a key leaks.
2. **Never change behaviour.** Emission failures are swallowed at the call
   site's level, not propagated: an observability defect must not turn into
   a governance defect. The one thing that is *not* swallowed is a
   secret-shaped field, because that is a bug to fix, not a hiccup.
3. **One event, one line, stable keys.** Machine-readable first; the human
   rendering is a side effect of that, not the other way round.
"""
from __future__ import annotations

import logging
from typing import Any

from remora.observability.redaction import redact_field

#: Substrings that must never appear in a field NAME. This layer is a rule a
#: reviewer can check by reading the call site. Values are handled separately,
#: by redaction rather than refusal: see remora.observability.redaction.
_FORBIDDEN_FIELD_PARTS: tuple[str, ...] = (
    "secret",
    "password",
    "passwd",
    "token",
    "credential",
    "api_key",
    "signing_key",
    "private_key",
    "bearer",
    "authorization",
)

#: Suffixes that mark a field as carrying a *reference to* or a *fact about*
#: a credential rather than the credential itself: an id, a digest, a boolean,
#: a count, a timestamp. ``token_jti`` identifies a grant; ``token_verified``
#: says whether one checked out. Neither can be replayed.
_DERIVED_SUFFIXES: tuple[str, ...] = (
    "_jti", "_id", "_hash", "_verified", "_present", "_required",
    "_count", "_at", "_mode", "_valid", "_signed", "_expired",
)

_LOGGER_NAME = "remora.governance"


class SecretFieldError(ValueError):
    """A log field name looked like a credential."""


def _screen(fields: dict[str, Any]) -> None:
    for name in fields:
        lowered = name.lower()
        if lowered.endswith(_DERIVED_SUFFIXES):
            # A digest, an id or a boolean about a credential — not the
            # credential. Logging these is the whole point of correlation.
            continue
        for part in _FORBIDDEN_FIELD_PARTS:
            if part in lowered:
                raise SecretFieldError(
                    f"refusing to log field {name!r}: the name matches "
                    f"{part!r}. Log an identifier ({name}_id), a digest "
                    f"({name}_hash) or a boolean, never the value."
                )


def governance_event(
    event: str, *, level: int = logging.INFO, **fields: Any
) -> None:
    """Emit one structured governance event.

    ``event`` is a stable dotted name (``decision.made``,
    ``grant.consumed``); ``fields`` are the structured payload. Values
    should be identifiers, hashes, enum values, counts and durations — never
    free-form user content, and never a credential.

    Raises :class:`SecretFieldError` when a field name looks like a
    credential. Everything else that can go wrong during emission is
    swallowed: an observability defect must not become a governance defect.
    """
    _screen(fields)
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.isEnabledFor(level):
        return
    # Name screening is not enough on its own. Several call sites pass
    # detail=str(exc), and a downstream library decides what goes in that
    # string: a bearer token, an internal hostname, a path, a connection
    # string. The field name is innocent, so the screen above passes it. Every
    # string value is therefore redacted here, at the one choke point, rather
    # than at each call site where the next one would forget (RMR-003).
    fields = {k: redact_field(k, v) for k, v in fields.items()}
    try:
        rendered = " ".join(f"{k}={v!r}" for k, v in sorted(fields.items()))
        logger.log(level, "%s %s", event, rendered, extra={"remora": fields})
    except Exception:  # pragma: no cover - defensive
        pass


__all__ = ["governance_event", "SecretFieldError"]
