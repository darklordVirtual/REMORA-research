# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RFC 8785 (JCS) canonicalisation, for wire interoperability only.

This module exists because of the 2026-08-28 REMORA x APS conformance feedback,
which identified four classes of divergence between Python's
``json.dumps(sort_keys=True)`` and RFC 8785. All four reproduce against
``remora.policy.observation._canonical_json``:

======= ======================================== ==============================
class   REMORA today                             RFC 8785 requires
======= ======================================== ==============================
1       ``{"v":1e-06}`` / ``{"v":1e-07}``        ``0.000001`` / ``1e-7``
2       ``{"v":"caf\\u00e9"}``                    raw UTF-8
3       keys sorted by code point                 sorted by UTF-16 code unit
4       ``9223372036854775809`` exactly           IEEE 754 binary64
======= ======================================== ==============================

**This module does not replace the existing canonicalisation, and must not.**
``_canonical_json`` feeds ``canonical_tool_call_hash``, which is bound into
every execution token, every lease, every receipt and every audit-chain entry
this deployment has ever written. Changing those bytes would not merely alter
future hashes; it would make the historical record unverifiable against the
code that verifies it. The signing format is versioned instead, and old bytes
are never rewritten. That was the first recommendation in the feedback and it
is the load-bearing one.

**Classes 1 to 3 are closed here.** They are formatting, they change no
meaning, and a conforming verifier and this module agree byte for byte.

**Class 4 is not adopted, and the reason is a security property rather than a
preference.** RFC 8785 serialises every number as binary64. Above 2^53-1
distinct integers share a binary64 value, so under the JCS number model
``{"n": 9007199254740993}`` and ``{"n": 9007199254740992}`` produce identical
canonical bytes and therefore identical hashes. In a system whose entire
premise is that an approval cannot be reused for different arguments, adopting
a number model that aliases two different arguments onto one hash is an
argument-substitution hole.

So this module does not round. It serialises integers exactly where binary64
can represent them exactly, which is byte-identical to JCS across that whole
range, and it *refuses* a number outside it rather than emitting bytes that
alias. Refusing is the fail-closed direction: a caller learns that its payload
cannot be canonicalised for the wire, instead of receiving a hash that silently
collides with a different payload.

The feedback allows exactly this: classes "closed or explicitly declined". This
is class 4 declined, with the collision as the reason.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

#: The format identifier that travels with anything signed under these rules.
#: Bytes produced under a different identifier are never re-derived under this
#: one: see the module docstring.
CANONICAL_FORMAT = "remora/jcs-rfc8785-v0"

#: The identifier of the pre-existing format, recorded so that a verifier can
#: tell which rules a historical signature was produced under.
LEGACY_CANONICAL_FORMAT = "remora/json-sorted-v1"

#: Largest integer binary64 represents exactly. Above this, RFC 8785's number
#: model maps distinct integers onto identical bytes.
MAX_EXACT_INTEGER = 2**53 - 1

#: Escapes RFC 8785 requires. Everything else printable, including astral
#: characters, is emitted as raw UTF-8.
_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


class NotCanonicalisable(ValueError):
    """The value cannot be represented under these rules without losing meaning."""


def es_number(value: float | int) -> str:
    """Format a number as ECMAScript ``Number.prototype.toString`` would.

    This is the whole of class 1. Python's ``repr`` gives the same shortest
    round-trip digits, and then differs on where it puts the decimal point and
    how it pads the exponent: ``1e-06`` where ECMAScript writes ``0.000001``,
    and ``1e-07`` where it writes ``1e-7``.

    The algorithm is the one in the ECMAScript specification: take the shortest
    digit string ``s`` and the position ``n`` of the decimal point, then choose
    fixed or exponential notation by where ``n`` falls.
    """

    if isinstance(value, bool):
        raise NotCanonicalisable("a boolean is not a number in JSON")

    if isinstance(value, int):
        if abs(value) > MAX_EXACT_INTEGER:
            raise NotCanonicalisable(
                f"integer {value} exceeds the exactly representable range "
                f"(|v| <= {MAX_EXACT_INTEGER}). RFC 8785 would serialise it as "
                f"binary64, where it shares canonical bytes with a different "
                f"integer. Refusing rather than emitting an aliasing hash."
            )
        return str(value)

    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise NotCanonicalisable(f"{value!r} has no JSON representation")
    if number == 0:
        return "0"  # also normalises -0.0, as ECMAScript does
    if number < 0:
        return "-" + es_number(-number)

    digits_tuple = Decimal(repr(number)).as_tuple()
    digits = "".join(str(d) for d in digits_tuple.digits)
    exponent = int(digits_tuple.exponent)
    while len(digits) > 1 and digits.endswith("0"):
        digits = digits[:-1]
        exponent += 1

    k = len(digits)
    n = exponent + k

    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits

    power = n - 1
    sign = "+" if power >= 0 else "-"
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{mantissa}e{sign}{abs(power)}"


def _string(value: str) -> str:
    """Escape only what RFC 8785 requires; emit everything else as UTF-8.

    This is class 2. Python escapes every non-ASCII character by default, so
    ``café`` becomes ``caf\\u00e9`` where a conforming serialiser writes the
    character itself.
    """

    out = ['"']
    for char in value:
        escape = _ESCAPES.get(char)
        if escape is not None:
            out.append(escape)
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _sort_key(key: str) -> bytes:
    """Order object members by UTF-16 code unit, not by code point.

    This is class 3, and it is only visible above the basic multilingual plane.
    An astral character is one surrogate pair in UTF-16, and its leading
    surrogate (0xD800-0xDBFF) sorts *below* BMP characters above 0xE000. Sorting
    by code point puts it after them instead.
    """

    return key.encode("utf-16-be")


def _serialise(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return es_number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_serialise(item) for item in value) + "]"
    if isinstance(value, dict):
        # Type-check every member name BEFORE sorting: the sort key encodes to
        # UTF-16 and would raise an AttributeError on a non-string first,
        # which tells the caller nothing about what is wrong with its payload.
        for key in value:
            if not isinstance(key, str):
                raise NotCanonicalisable(
                    f"object member name {key!r} is not a string; JSON has no "
                    f"canonical form for it"
                )
        members = []
        for key in sorted(value, key=_sort_key):
            members.append(_string(key) + ":" + _serialise(value[key]))
        return "{" + ",".join(members) + "}"
    raise NotCanonicalisable(
        f"{type(value).__name__} has no JSON representation; convert it at the "
        f"call site rather than letting a default coercion decide"
    )


def canonicalise(value: Any) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes for *value*.

    Byte-identical to a conforming implementation for every value it accepts.
    Where RFC 8785 would lose information, it raises
    :class:`NotCanonicalisable` rather than producing bytes: see the module
    docstring on class 4.
    """

    return _serialise(value).encode("utf-8")


__all__ = [
    "CANONICAL_FORMAT",
    "LEGACY_CANONICAL_FORMAT",
    "MAX_EXACT_INTEGER",
    "NotCanonicalisable",
    "canonicalise",
    "es_number",
]
