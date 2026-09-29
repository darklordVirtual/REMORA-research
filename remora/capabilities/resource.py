# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Resource identities an effect capability is scoped to (NTA-2, phase 1).

``filesystem.read`` means nothing for policy until it says *which* file. A
resource is written ``<scheme>://<authority>/<path>``, for example
``workspace://reports/september.pdf`` or ``database://reporting-eu/monthly``.
The authority names the provider, account or region, so switching provider is
a different resource and is checked as one.

The comparison is the attack surface, so the canonical form refuses rather
than normalises anything that could mean two things: ``.`` and ``..``
segments, empty segments, percent-encoding, backslashes, whitespace, control
characters, user information, queries and fragments. Scheme and authority are
lower-cased; the path keeps its case. A pattern is a canonical resource, or one
followed by ``/*`` for the subtree beneath it, and matching respects segment
boundaries: ``workspace://reports/*`` does not cover ``workspace://reports-x``.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = ["ResourceRefused", "canonical_resource", "canonical_resource_pattern",
           "resource_within"]

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*$")
_AUTHORITY = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?(:[0-9]{1,5})?$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._~!$&'()+,;=:@-]+$")


class ResourceRefused(ValueError):
    """A resource or pattern that has no single canonical meaning."""


def canonical_resource(raw: str) -> str:
    """The canonical form of ``raw``, or ``ResourceRefused``."""
    if not isinstance(raw, str) or not raw:
        raise ResourceRefused("a resource is a non-empty string")
    if any(ch in raw for ch in "%\\?#*") or any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in raw):
        raise ResourceRefused("encoded, escaped, query, fragment, wildcard or control characters")
    scheme, sep, rest = raw.partition("://")
    if not sep:
        raise ResourceRefused("a resource is <scheme>://<authority>/<path>")
    scheme = scheme.lower()
    if not _SCHEME.match(scheme):
        raise ResourceRefused(f"invalid scheme {scheme!r}")
    authority, _, path = rest.partition("/")
    authority = authority.lower()
    if "@" in authority or not _AUTHORITY.match(authority):
        raise ResourceRefused(f"invalid authority {authority!r}")
    segments = path.split("/") if path else []
    if segments and segments[-1] == "":
        segments.pop()  # one trailing slash names the same resource
    for segment in segments:
        if segment in {"", ".", ".."} or not _SEGMENT.match(segment):
            raise ResourceRefused(f"ambiguous path segment {segment!r}")
    return f"{scheme}://{authority}" + "".join(f"/{s}" for s in segments)


def canonical_resource_pattern(raw: str) -> str:
    """A canonical resource, or one followed by ``/*`` for its subtree."""
    if not isinstance(raw, str):
        raise ResourceRefused("a pattern is a string")
    if raw.endswith("/*"):
        base = canonical_resource(raw[:-2])
        if "://" not in base or base.endswith("://"):
            raise ResourceRefused("a subtree pattern needs an authority")
        return base + "/*"
    return canonical_resource(raw)


def resource_within(resource: str, patterns: Iterable[str]) -> bool:
    """Whether ``resource`` is covered by any pattern. An ambiguous resource never is."""
    try:
        canonical = canonical_resource(resource)
    except ResourceRefused:
        return False
    for pattern in patterns:
        if pattern.endswith("/*"):
            if canonical.startswith(pattern[:-1]):
                return True
        elif canonical == pattern:
            return True
    return False
