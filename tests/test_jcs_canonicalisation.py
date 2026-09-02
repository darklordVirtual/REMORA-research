# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RFC 8785 canonicalisation, and the one place we decline to follow it.

The 2026-08-28 REMORA x APS conformance feedback named four classes of
divergence between Python's ``json.dumps(sort_keys=True)`` and RFC 8785. Each
class has a test here that fails against the old behaviour and passes against
``remora.interop.jcs``, plus a test that the old behaviour is still what the
internal binding path produces, because changing those bytes would make every
historical signature unverifiable.

Class 4 is declined rather than closed, and the test that matters most in this
file is the one that shows why: under the JCS number model two different
integers produce the same canonical bytes.
"""
from __future__ import annotations

import pytest

from remora.interop.jcs import (
    CANONICAL_FORMAT,
    aliases_another_integer,
    LEGACY_CANONICAL_FORMAT,
    MAX_EXACT_INTEGER,
    NotCanonicalisable,
    canonicalise,
    es_number,
)
from remora.policy.observation import _canonical_json

ASTRAL = "\U0001F600"          # one surrogate pair in UTF-16
BMP_HIGH = "＀"            # above the surrogate range as a code point


class TestClassOneNumbers:
    """ECMAScript Number.prototype.toString, which Python's repr is not."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (1e-6, "0.000001"),
            (1e-7, "1e-7"),
            (1e-10, "1e-10"),
            (1e20, "100000000000000000000"),
            (1e21, "1e+21"),
            (1e22, "1e+22"),
            (0.1, "0.1"),
            (1.5, "1.5"),
            (-1.5, "-1.5"),
            (100.0, "100"),
            (123456789.0, "123456789"),
            (5e-324, "5e-324"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
            (0.0, "0"),
            (-0.0, "0"),
        ],
    )
    def test_the_ecmascript_form(self, value, expected):
        assert es_number(value) == expected

    def test_negative_zero_normalises(self):
        """ECMAScript prints 0 for -0, so a signed zero cannot change a hash."""

        assert canonicalise({"v": -0.0}) == canonicalise({"v": 0.0})

    @pytest.mark.parametrize("value", [1e-6, 1e-7])
    def test_this_is_where_python_diverged(self, value):
        assert _canonical_json({"v": value}) != canonicalise({"v": value}).decode()

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_a_number_json_cannot_express_is_refused(self, value):
        with pytest.raises(NotCanonicalisable):
            canonicalise({"v": value})


class TestClassTwoStrings:
    """Raw UTF-8, not \\uXXXX escapes."""

    def test_non_ascii_is_emitted_as_itself(self):
        assert canonicalise({"v": "café"}).decode() == '{"v":"café"}'

    def test_this_is_where_python_diverged(self):
        assert "\\u00e9" in _canonical_json({"v": "café"})

    def test_astral_characters_are_emitted_as_themselves(self):
        assert canonicalise({"v": ASTRAL}).decode() == f'{{"v":"{ASTRAL}"}}'

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('"', '"\\""'),
            ("\\", '"\\\\"'),
            ("\b", '"\\b"'),
            ("\f", '"\\f"'),
            ("\n", '"\\n"'),
            ("\r", '"\\r"'),
            ("\t", '"\\t"'),
            ("\x00", '"\\u0000"'),
            ("\x1f", '"\\u001f"'),
        ],
    )
    def test_only_the_required_escapes_are_used(self, raw, expected):
        assert canonicalise(raw).decode() == expected

    def test_delete_is_not_escaped(self):
        """0x7f is not a JSON control character, so it stays literal."""

        assert canonicalise("\x7f").decode() == '"\x7f"'


class TestClassThreeKeyOrder:
    """UTF-16 code units, not code points."""

    def test_an_astral_key_sorts_before_a_high_bmp_key(self):
        out = canonicalise({ASTRAL: 1, BMP_HIGH: 2}).decode()
        assert out.startswith(f'{{"{ASTRAL}"')

    def test_this_is_where_python_diverged(self):
        """Code-point order puts the astral key last; UTF-16 order puts it first."""

        assert sorted([ASTRAL, BMP_HIGH]) == [BMP_HIGH, ASTRAL]
        assert _canonical_json({ASTRAL: 1, BMP_HIGH: 2}).startswith('{"\\uff00"')

    def test_ordinary_keys_are_unaffected(self):
        assert canonicalise({"b": 1, "a": 2, "C": 3}).decode() == '{"C":3,"a":2,"b":1}'

    def test_a_non_string_member_name_is_refused(self):
        with pytest.raises(NotCanonicalisable, match="not a string"):
            canonicalise({1: "one"})


class TestClassFourDeclined:
    """The number model we do not adopt, and the reason."""

    def test_a_uniquely_representable_integer_is_serialised_exactly(self):
        assert canonicalise({"n": MAX_EXACT_INTEGER}).decode() == (
            f'{{"n":{MAX_EXACT_INTEGER}}}'
        )

    def test_an_aliasing_integer_is_refused_rather_than_rounded(self):
        with pytest.raises(NotCanonicalisable, match="aliasing"):
            canonicalise({"n": 2**53})

    def test_the_test_is_uniqueness_not_magnitude(self):
        """Found by running the APS vectors: a magnitude bound was too coarse.

        2**53 + 2 sits above the largest all-integers-representable bound and is
        still the only integer that maps to its double. The conformance suite
        serialises it exactly, and refusing it would have been a false positive
        against a vector that has no ambiguity in it.
        """

        assert aliases_another_integer(2**53) is True
        assert aliases_another_integer(2**53 + 1) is True
        assert aliases_another_integer(2**53 + 2) is False
        assert canonicalise({"n": 2**53 + 2}).decode() == '{"n":9007199254740994}'

    def test_powers_of_two_beyond_the_double_grid_alias(self):
        """Exactly representable is not the same as uniquely representable."""

        for value in (2**60, 2**68):
            assert float(value) == value, "the value itself round-trips"
            assert aliases_another_integer(value) is True
            with pytest.raises(NotCanonicalisable):
                canonicalise({"n": value})

    def test_integers_beyond_binary64_range_are_refused_not_overflowed(self):
        """Issue #510: float(10**400) raises OverflowError before any check ran.

        An integer too large for any double is the round-trip failure at its
        limit, so it is refused the same way an aliasing integer is. A caller
        catching NotCanonicalisable to record a refusal must not see a raw
        OverflowError instead.
        """

        for value in (10**400, -(10**400), 2**1024):
            assert aliases_another_integer(value) is True
            with pytest.raises(NotCanonicalisable):
                canonicalise({"value": value})

    def test_the_reason_two_integers_would_share_canonical_bytes(self):
        """Why refusing beats rounding, stated as an executable fact.

        Under the JCS number model both of these become the same binary64
        value, so a governed call carrying one would hash identically to a call
        carrying the other. An approval for one argument would authorise the
        other.
        """

        # Above 2^53 binary64 represents only every second integer, so an
        # odd value collapses onto its even neighbour.
        a, b = 2**53, 2**53 + 1
        assert a != b
        assert float(a) == float(b)

    def test_floats_do_alias_and_this_module_does_not_prevent_it(self):
        """The limit of the guarantee, pinned so nobody reads it as wider.

        Refusing aliasing integers does not make canonical bytes injective over
        payloads. Distinct float literals collapse in ``json.loads`` before this
        module sees them, so two different JSON texts arrive as one value and
        share bytes. The enforced property is about integers only. Raised by the
        APS corpus maintainer in review of the interop record.
        """

        import json as _json

        wide = _json.loads('{"v": 0.1000000000000000055511151231257827}')
        narrow = _json.loads('{"v": 0.1}')
        assert canonicalise(wide) == canonicalise(narrow) == b'{"v":0.1}'
        assert canonicalise({"v": -0.0}) == canonicalise({"v": 0.0})

    def test_a_float_carrying_a_large_integer_value_is_still_formatted(self):
        """The refusal is about integer precision, not about magnitude."""

        assert es_number(1e300) == "1e+300"


class TestTheHistoricalFormatIsUntouched:
    """The load-bearing constraint: old bytes are never rewritten."""

    def test_the_internal_path_still_produces_the_legacy_form(self):
        assert _canonical_json({"v": "café"}) == '{"v":"caf\\u00e9"}'
        assert _canonical_json({"v": 1e-6}) == '{"v":1e-06}'

    def test_the_two_formats_have_distinct_identifiers(self):
        assert CANONICAL_FORMAT != LEGACY_CANONICAL_FORMAT
        assert "v0" in CANONICAL_FORMAT
        assert "v1" in LEGACY_CANONICAL_FORMAT

    def test_a_tool_call_hash_is_unchanged_by_this_module_existing(self):
        """Regression guard: importing the interop path must not alter bindings."""

        from remora.policy.observation import canonical_tool_call_hash

        assert canonical_tool_call_hash(
            name="read_telemetry", arguments={"asset": "P-1"}, tenant="acme"
        ) == canonical_tool_call_hash(
            name="read_telemetry", arguments={"asset": "P-1"}, tenant="acme"
        )


class TestStructure:
    def test_nested_values(self):
        assert canonicalise({"b": [1, 2.5, None, True], "a": "x"}).decode() == (
            '{"a":"x","b":[1,2.5,null,true]}'
        )

    def test_empty_containers(self):
        assert canonicalise({}).decode() == "{}"
        assert canonicalise([]).decode() == "[]"

    def test_a_tuple_serialises_as_an_array(self):
        assert canonicalise((1, 2)).decode() == "[1,2]"

    def test_booleans_are_not_numbers(self):
        assert canonicalise({"v": True}).decode() == '{"v":true}'
        with pytest.raises(NotCanonicalisable, match="boolean"):
            es_number(True)

    def test_an_unrepresentable_type_is_refused_not_coerced(self):
        """The legacy path used default=str, which silently invented bytes."""

        class Thing:
            pass

        with pytest.raises(NotCanonicalisable, match="no JSON representation"):
            canonicalise({"v": Thing()})

    def test_the_output_is_utf8_bytes(self):
        assert isinstance(canonicalise({"v": "café"}), bytes)
        assert canonicalise({"v": "café"}) == '{"v":"café"}'.encode("utf-8")
