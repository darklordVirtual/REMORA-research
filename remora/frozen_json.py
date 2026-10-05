# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Deep-frozen JSON values for records that carry their own digest.

A frozen dataclass that wraps a caller's dict in ``MappingProxyType(dict(x))``
is read-only one level deep. The nested dicts and lists are still the
caller's objects, so a digest computed at construction can stop describing
the content the record holds a moment later. The pre-Federation probes
(#744) showed this for effect verifications, postcondition contracts and
evidence-admission manifests.

``freeze`` takes a private deep copy and makes every level read-only:
mappings become ``MappingProxyType``, lists and tuples become tuples. It
admits the JSON domain only: ``None``, ``bool``, ``int``, finite ``float``,
``str``, string-keyed mappings and sequences. Anything else raises
``TypeError`` instead of being coerced with ``str()``, because coercion is
how ``1`` and ``"1"`` (or an object and its repr) end up with one digest.

``thaw`` returns the plain JSON form, and ``digest`` hashes it with sorted
keys, no whitespace, ASCII escapes and ``allow_nan=False``: the encoding
``effect_digest`` has always used, so digests of JSON-domain values pinned by
``effect-evidence-v1`` do not move. ``strict_equal`` compares two
values without Python's cross-type equalities (``True == 1``, ``1 == 1.0``,
``(1,) != [1]`` in the other direction).

The capability model has the same discipline in ``remora.capabilities.model``;
it predates this module and coerces keys with ``str()``, which is why it is
not reused here.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

__all__ = ["digest", "freeze", "strict_equal", "thaw"]


def freeze(value: Any) -> Any:
    """A deep, read-only private copy of a JSON value."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("non-finite float is outside the JSON domain")
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"mapping key {key!r} is not a string; refusing to coerce")
            out[key] = freeze(item)
        return MappingProxyType(out)
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    raise TypeError(
        f"{type(value).__name__} is outside the JSON domain; refusing to coerce")


def thaw(value: Any) -> Any:
    """The plain JSON form of a value: dicts and lists, never proxies."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(item) for item in value]
    return value


def digest(value: Any) -> str:
    """SHA-256 over the canonical encoding of a JSON-domain value."""
    canonical = json.dumps(
        thaw(freeze(value)), sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def strict_equal(left: Any, right: Any) -> bool:
    """Equality that keeps bool, int, float and str apart at every depth."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            strict_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, (Mapping, list, tuple)) or isinstance(
            right, (Mapping, list, tuple)):
        return False
    return type(left) is type(right) and left == right
