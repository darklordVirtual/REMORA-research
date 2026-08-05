# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Machine-verifiable derivation receipts (NEGATIVE_RESULTS theme 3, §35).

Value grounding refuses derived argument values by design: ``2024-04-03``
derived from "April 3rd, 2024" occurs nowhere in the task text, and the
engine cannot check a derivation it is merely told about. §35 measured the
cost: read autonomy 86.1% → 56.8%, mostly dates, unit conversions and
normalized numbers that are correct but not literal.

A :class:`DerivationReceipt` closes that gap without weakening grounding.
The proposer (typically a model) declares WHERE the value came from
(``source_span``, which must occur verbatim in the task text — the same
provenance discipline as goal_match's ``source_spans``) and HOW it was
derived (``transform``, a name from the versioned whitelist below).
Verification re-executes the transform server-side and compares the output
to the claimed value. A model may PROPOSE a receipt; only deterministic
re-execution accepts it — an explanation is not a derivation proof.

Fail-closed by construction: an unknown transform, a span that is not in
the task text, or an output mismatch REJECTS the receipt, and a rejected
receipt merely leaves the value ungrounded — it can never un-ground
anything or lower any other signal.

The transform vocabulary is versioned (``DERIVATION_TRANSFORMS_VERSION``)
like goal_match's EFFECT_VOCABULARY: growing it is a reviewed change, and
ambiguous transforms stay out — e.g. gb→mb is excluded because the
binary/decimal factor is a guess, and guessing is the failure mode this
module exists to remove. Deliberately NOT included: arithmetic over task
numbers (an attacker could derive almost any value from any number via
crafted arithmetic) and locale-dependent parsing (English month names are
resolved by the internal table below, never ``strptime``'s locale).

Status: mechanism only. The effect on the §35 autonomy loss is UNMEASURED
until a new sealed round (backlog theme 2); no number may be cited.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Callable, Mapping

_LOGGER = logging.getLogger("remora.toolcall.derivation")

DERIVATION_TRANSFORMS_VERSION = "v1"

_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

#: "April 3rd, 2024" / "3 April 2024" / "April 3 2024" — ordinal suffixes
#: optional, comma optional. Anything else is not this transform's job.
_MONTH_FIRST = re.compile(
    r"^\s*([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\s*$"
)
_DAY_FIRST = re.compile(
    r"^\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s*,?\s*(\d{4})\s*$"
)

_NUMBER = re.compile(r"^\s*[^0-9\-+]?\s*([\-+]?[\d,][\d,]*(?:\.\d+)?)\s*$")

#: Exact conversion factors only. Pairs with ambiguous factors (gb→mb) or
#: non-multiplicative rules (°C→°F) are deliberately absent from v1.
_UNIT_FACTORS: dict[tuple[str, str], Fraction] = {
    ("km", "m"): Fraction(1000),
    ("m", "cm"): Fraction(100),
    ("m", "mm"): Fraction(1000),
    ("cm", "mm"): Fraction(10),
    ("kg", "g"): Fraction(1000),
    ("g", "mg"): Fraction(1000),
    ("hours", "minutes"): Fraction(60),
    ("h", "min"): Fraction(60),
    ("minutes", "seconds"): Fraction(60),
    ("min", "s"): Fraction(60),
}


@dataclass(frozen=True)
class DerivationReceipt:
    """One proposed derivation: value = transform(source_span, params).

    ``source_start``/``source_end`` (optional) bind the span to an exact
    offset range in the task text: when both are set, verification
    requires ``task_text[source_start:source_end] == source_span``. When
    absent, the weaker verbatim-substring binding applies (any
    occurrence). Document-level identity is carried one level up: the
    task text itself comes from the resolved intent, whose source is
    hash-identified by ``intent_authority_hash``; per-receipt document
    ids/hashes arrive with the signed ToolSpec identity (FT-03).

    ``params`` is wrapped in an immutable mapping at construction so a
    receipt's identity cannot drift after creation.
    """

    argument: str
    value: Any
    transform: str
    source_span: str
    params: Mapping[str, Any] = field(default_factory=dict)
    source_start: int | None = None
    source_end: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))


def _parse_en_date(span: str) -> str | None:
    m = _MONTH_FIRST.match(span)
    if m:
        month_name, day, year = m.group(1), m.group(2), m.group(3)
    else:
        m = _DAY_FIRST.match(span)
        if not m:
            return None
        day, month_name, year = m.group(1), m.group(2), m.group(3)
    month = _EN_MONTHS.get(month_name.lower())
    if month is None:
        return None
    # datetime.date is the authoritative calendar validator (review
    # 2026-08-05): "April 31st" and "February 30th" are rejections, not
    # dates. A range check alone let impossible dates through.
    try:
        parsed = _dt.date(int(year), month, int(day))
    except ValueError:
        return None
    return parsed.isoformat()


def _en_date_to_iso(span: str, params: Mapping[str, Any]) -> str | None:
    return _parse_en_date(span)


def _number_normalize(span: str, params: Mapping[str, Any]) -> Fraction | None:
    m = _NUMBER.match(span)
    if not m:
        return None
    text = m.group(1).replace(",", "")
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def _unit_convert(span: str, params: Mapping[str, Any]) -> Fraction | None:
    from_unit = str(params.get("from_unit", "")).strip().lower()
    to_unit = str(params.get("to_unit", "")).strip().lower()
    factor = _UNIT_FACTORS.get((from_unit, to_unit))
    if factor is None:
        return None
    m = re.match(r"^\s*([\-+]?\d+(?:\.\d+)?)\s*" + re.escape(from_unit) + r"\b",
                 span.strip(), flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return Fraction(m.group(1)) * factor
    except (ValueError, ZeroDivisionError):
        return None


def _lowercase(span: str, params: Mapping[str, Any]) -> str:
    return span.lower()


def _uppercase(span: str, params: Mapping[str, Any]) -> str:
    return span.upper()


_TRANSFORMS: dict[str, Callable[[str, Mapping[str, Any]], Any]] = {
    "en_date_to_iso": _en_date_to_iso,
    "number_normalize": _number_normalize,
    "unit_convert": _unit_convert,
    "lowercase": _lowercase,
    "uppercase": _uppercase,
}


def _values_equal(computed: Any, claimed: Any) -> bool:
    if computed is None:
        return False
    if isinstance(computed, Fraction):
        if isinstance(claimed, bool) or not isinstance(claimed, (int, float, str)):
            return False
        try:
            return computed == Fraction(str(claimed))
        except (ValueError, ZeroDivisionError):
            return False
    return isinstance(claimed, str) and computed == claimed


def verify_receipt(receipt: DerivationReceipt, *, task_text: str) -> bool:
    """Deterministically re-execute the receipt. True only on exact agreement.

    Every failure mode is a rejection, never an exception: verification is
    consulted inside grounding, and grounding must not be crashable by
    adversarial receipt content.
    """
    transform = _TRANSFORMS.get(receipt.transform)
    if transform is None:
        return False
    if not receipt.source_span:
        return False
    if receipt.source_start is not None and receipt.source_end is not None:
        # Exact offset binding: the declared range must reproduce the span.
        if task_text[receipt.source_start:receipt.source_end] != receipt.source_span:
            return False
    elif receipt.source_span not in task_text:
        return False
    try:
        computed = transform(receipt.source_span, receipt.params or {})
    except (ValueError, TypeError, KeyError, ArithmeticError, OverflowError):
        # INVALID_RECEIPT: expected parse/shape failures reject quietly.
        return False
    except Exception:
        # VERIFIER_ERROR: an implementation bug must reject fail-closed AND
        # be visible — swallowing it would hide the defect forever. No span
        # content is logged (it may carry user text).
        _LOGGER.exception(
            "verifier_error transform=%s argument=%s",
            receipt.transform, receipt.argument,
        )
        return False
    return _values_equal(computed, receipt.value)


def receipt_grounds(
    name: str,
    value: Any,
    receipts: "tuple[DerivationReceipt, ...] | None",
    *,
    task_text: str,
) -> bool:
    """Does a verified receipt ground argument *name* = *value*?

    The receipt must name the same argument and claim the same value it
    verifies — a receipt for another argument or another value proves
    nothing about this one.
    """
    if not receipts:
        return False
    for receipt in receipts:
        if receipt.argument != name:
            continue
        if not _same_typed_value(receipt.value, value):
            continue
        if verify_receipt(receipt, task_text=task_text):
            return True
    return False


def _same_typed_value(claimed: Any, actual: Any) -> bool:
    """Type-aware equality: no cross-type str() equivalence (review finding).

    Booleans never match numbers; int and float compare numerically;
    strings compare only against strings. ``1`` and ``"1"`` are DIFFERENT
    values until a ToolSpec schema (FT-03) declares a canonical type.
    """
    if isinstance(claimed, bool) or isinstance(actual, bool):
        return claimed is actual
    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
        return claimed == actual
    if isinstance(claimed, str) and isinstance(actual, str):
        return claimed == actual
    return False


def transforms_digest() -> str:
    """Deterministic identity of the transform registry's semantics.

    Hashes the version, the transform names, the month table and the unit
    factors — the behavior-defining data. Recorded into the semantic audit
    context so a receipt verified under one vocabulary can never silently
    mean something else later; binding it into lease/ToolSpec identity is
    FT-03 scope.
    """
    payload = json.dumps({
        "version": DERIVATION_TRANSFORMS_VERSION,
        "transforms": sorted(_TRANSFORMS),
        "months": _EN_MONTHS,
        "unit_factors": {
            f"{a}->{b}": str(f) for (a, b), f in sorted(_UNIT_FACTORS.items())
        },
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


DERIVATION_TRANSFORMS_DIGEST = transforms_digest()
