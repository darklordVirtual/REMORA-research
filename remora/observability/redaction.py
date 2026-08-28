# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Value-level redaction for structured log fields (RMR-003).

``events.py`` screens field NAMES against a deny-list, which is a rule a
reviewer can check by reading a call site. It does not look at values, and for
most fields that is the right trade: a heuristic over values either misses real
secrets or mangles legitimate hashes.

One field defeats that reasoning. Several dispatch call sites pass
``detail=str(exc)``, and an exception raised by a downstream library carries
whatever that library chose to put in its message: a bearer token from an
authorization header, an internal hostname, a filesystem path, a connection
string. The field name is innocent, so the name-level screen passes it, and the
value lands in the governance log. The comment at one of those call sites says
as much: the text is kept away from the caller because it can name key
material, and is then written to a log the module's own first constraint says
must never contain a secret.

This module closes that at the emitter rather than at the call sites. A future
call site cannot reintroduce the leak by passing a differently named free-text
field, because every string value is screened on the way out.

What redaction is and is not: it is a net under free text that should not have
been free text. It is not a licence to log secrets deliberately. Structured
identifiers, digests and enum values remain the right thing to pass.
"""

from __future__ import annotations

import re

#: Replacement marker. Distinct and greppable, so an operator reading a log can
#: tell redaction happened rather than wondering where the text went.
MARKER = "[redacted]"

#: Ordered longest-context-first: a bearer token inside a URL should be caught
#: by the credential rule before the URL rule rewrites the host.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Authorization headers and bearer/basic tokens, with or without a header name.
    ("bearer", re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._\-+/=]{8,}")),
    # JWTs: three base64url segments separated by dots.
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")),
    # key=value and key: value forms for anything credential-shaped.
    (
        "assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token|credential|"
            r"private[_-]?key|signing[_-]?key|access[_-]?key|auth)\b"
            r"\s*[:=]\s*[^\s,;)\]}]+"
        ),
    ),
    # Connection strings: scheme://user:password@host
    ("dsn", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s/@]+:[^\s/@]+@[^\s]+")),
    # Any remaining URL, which carries host and often a path.
    ("url", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s\"'<>]+")),
    # Absolute POSIX paths, and Windows drive paths.
    ("path", re.compile(r"(?<![\w.])/(?:[\w.\-]+/){1,}[\w.\-]*")),
    ("winpath", re.compile(r"\b[A-Za-z]:\\(?:[^\\\s\"']+\\)*[^\\\s\"']*")),
    # Long hex runs: raw keys, nonces and private material.
    ("hex", re.compile(r"\b[0-9a-fA-F]{32,}\b")),
    # Internal-looking hostnames. Deliberately narrow: only dotted names with a
    # non-public-looking final label, so ordinary prose survives.
    (
        "host",
        re.compile(
            r"(?<![\w.@/])(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+"
            r"(?:local|internal|lan|intranet|corp|svc|cluster)\b"
        ),
    ),
)


def redact_text(value: str) -> str:
    """Replace credential-shaped and location-shaped runs with :data:`MARKER`.

    Deliberately conservative in one direction only: a false positive costs an
    operator some context in a log line, and a false negative costs a
    credential. When the two trade against each other, redact.
    """

    if not value:
        return value
    out = value
    for _name, pattern in _PATTERNS:
        out = pattern.sub(MARKER, out)
    return out


def redact_field(name: str, value: object) -> object:
    """Redact one structured field value, leaving non-text values untouched.

    Hashes and identifiers are passed through by name so that a digest field
    keeps its digest: ``*_hash``, ``*_id``, ``jti`` and ``nonce`` are the
    values an audit trail exists to carry, and a long hex rule would otherwise
    eat exactly those.
    """

    if not isinstance(value, str):
        return value
    lowered = name.lower()
    if (
        lowered.endswith("_hash")
        or lowered.endswith("_id")
        or lowered.endswith("_sha")
        or lowered in {"jti", "nonce", "kid", "digest", "sha", "commit"}
    ):
        return value
    return redact_text(value)


__all__ = ["MARKER", "redact_field", "redact_text"]
