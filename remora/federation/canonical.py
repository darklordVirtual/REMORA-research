# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Native canonical action preservation (SDD section 6).

The bridge keeps REMORA's own canonical bytes, their canonicalization
version, their digest and a typed scalar listing, independently of any
transport. It never reconstructs native semantics from a transport's
representation: a transport that carries arguments as JavaScript values
cannot distinguish ``1`` from ``1.0``, and a projection built on what it
carries would lose that distinction silently.

``javascript_losses`` names what such a transport would lose for one
argument set, so a projection can say so instead of passing.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from remora.policy.observation import _canonical_json, _require_json_domain

__all__ = ["CANONICALIZATION", "CanonicalArguments", "canonical_arguments", "javascript_losses",
           "typed_scalars"]

#: The canonicalization REMORA's exact-call binding hashes over
#: (``remora.policy.observation._canonical_json``): sorted keys, no
#: whitespace, Python's JSON encoding of int and float distinct.
CANONICALIZATION = "remora-canonical-json-v1"

_MAX_SAFE_INTEGER = 2 ** 53 - 1


@dataclass(frozen=True)
class CanonicalArguments:
    canonical: str
    canonicalization: str
    digest: str
    typed_scalars: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"canonical_arguments": self.canonical, "canonicalization": self.canonicalization,
                "arguments_digest": self.digest,
                "typed_scalars": [list(pair) for pair in self.typed_scalars]}


def _pointer(parts: list[str]) -> str:
    return "".join("/" + p.replace("~", "~0").replace("/", "~1") for p in parts)


def typed_scalars(value: Any, path: list[str] | None = None) -> list[tuple[str, str]]:
    """(JSON pointer, type) for every scalar, in canonical key order."""
    path = path or []
    if isinstance(value, dict):
        out: list[tuple[str, str]] = []
        for key in sorted(value):
            out += typed_scalars(value[key], [*path, str(key)])
        return out
    if isinstance(value, list):
        out = []
        for index, item in enumerate(value):
            out += typed_scalars(item, [*path, str(index)])
        return out
    if value is None:
        kind = "null"
    elif isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, int):
        kind = "integer"
    elif isinstance(value, float):
        kind = "float"
    else:
        kind = "string"
    return [(_pointer(path), kind)]


def canonical_arguments(arguments: Any) -> CanonicalArguments:
    """REMORA's canonical form of ``arguments``; refuses values outside the JSON domain."""
    _require_json_domain(arguments)
    canonical = _canonical_json(arguments)
    return CanonicalArguments(
        canonical=canonical, canonicalization=CANONICALIZATION,
        digest="sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        typed_scalars=tuple(typed_scalars(arguments)))


def _walk(value: Any, path: list[str]):
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _walk(value[key], [*path, str(key)])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, [*path, str(index)])
    else:
        yield _pointer(path), value


def javascript_losses(arguments: Any) -> dict[str, list[str]]:
    """What a transport carrying ``arguments`` as JavaScript values would lose.

    - ``lexical_numeric_type``: an integral float (``1.0``, ``-0.0``) arrives
      as an integer, so the native int/float distinction does not survive;
    - ``integer_precision``: an integer beyond 2^53 - 1 changes value.

    Keys map to the JSON pointers affected; an empty dict means nothing is lost.
    """
    losses: dict[str, list[str]] = {}
    for pointer, value in _walk(arguments, []):
        if isinstance(value, bool):
            continue
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            losses.setdefault("lexical_numeric_type", []).append(pointer)
        elif isinstance(value, int) and abs(value) > _MAX_SAFE_INTEGER:
            losses.setdefault("integer_precision", []).append(pointer)
    return losses
