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
from typing import Mapping

#: Replacement marker. Distinct and greppable, so an operator reading a log can
#: tell redaction happened rather than wondering where the text went.
MARKER = "[redacted]"

#: Credential-shaped key names, shared by the assignment rule and by the
#: recursive structured-value walk.
_CREDENTIAL_KEYS = (
    r"api[_-]?key|secret|password|passwd|token|credential|"
    r"private[_-]?key|signing[_-]?key|access[_-]?key|auth"
)
_CREDENTIAL_KEY = re.compile(r"(?i)(?:" + _CREDENTIAL_KEYS + r")")

#: Vendor-prefixed secrets: Anthropic/OpenAI-style sk-, GitHub tokens, AWS
#: access key ids and Slack tokens.
_VENDOR = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{10,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"
    r"|\bxox[abposr]-[A-Za-z0-9\-]{10,}"
)

#: A value that is plainly an identifier or digest: no whitespace, no quoting.
_IDENTIFIER_SHAPE = re.compile(r"[A-Za-z0-9._:\-/+=]{0,256}")

#: Ordered longest-context-first: a bearer token inside a URL should be caught
#: by the credential rule before the URL rule rewrites the host.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Authorization headers and bearer/basic tokens, with or without a header name.
    ("bearer", re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._\-+/=]{8,}")),
    # JWTs: three base64url segments separated by dots.
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")),
    # Vendor-prefixed credentials, which are secrets wherever they appear.
    ("vendor", _VENDOR),
    # key=value and key: value forms for anything credential-shaped. The key
    # may be quoted (JSON), and the value may be quoted and contain spaces.
    (
        "assignment",
        re.compile(
            r"(?i)\b(?:" + _CREDENTIAL_KEYS + r")\b[\"']?"
            r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;)\]}\"']+)"
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


_EXEMPT_NAMES = frozenset({"jti", "nonce", "kid", "digest", "sha", "commit"})
_EXEMPT_SUFFIXES = ("_hash", "_id", "_sha")
_JWT = _PATTERNS[1][1]


def _is_exempt_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in _EXEMPT_NAMES or lowered.endswith(_EXEMPT_SUFFIXES)


def redact_field(name: str, value: object) -> object:
    """Redact one structured field value.

    Hashes and identifiers are passed through by name so that a digest field
    keeps its digest: ``*_hash``, ``*_id``, ``jti`` and ``nonce`` are the
    values an audit trail exists to carry, and a long hex rule would otherwise
    eat exactly those. The exemption holds only while the value still LOOKS
    like an identifier: free text or a vendor-prefixed credential under such a
    name is redacted like any other string.

    Mappings, sequences and exceptions are walked, so a structure logged whole
    does not carry a credential past the emitter.
    """

    if isinstance(value, str):
        if (
            _is_exempt_name(name)
            and _IDENTIFIER_SHAPE.fullmatch(value)
            and not _VENDOR.search(value)
            and not _JWT.search(value)
        ):
            return value
        return redact_text(value)
    if isinstance(value, BaseException):
        return redact_text(f"{type(value).__name__}: {value}")
    if isinstance(value, Mapping):
        return {
            key: (
                MARKER
                if isinstance(key, str)
                and _CREDENTIAL_KEY.search(key)
                and value[key] is not None
                and not isinstance(value[key], (Mapping, list, tuple, set, frozenset))
                else redact_field(str(key), value[key])
            )
            for key in value
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact_field(name, item) for item in value)
    if isinstance(value, (set, frozenset)):
        return [redact_field(name, item) for item in value]
    return value


__all__ = ["MARKER", "redact_field", "redact_text"]
