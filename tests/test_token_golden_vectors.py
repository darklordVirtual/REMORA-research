# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Golden signature vectors for the PolicyDecisionToken wire format.

The mutation pass (docs/assurance/mutation_testing_v1.md, issue #280) found
34 surviving mutants in ``_canonical_payload`` — every one self-consistent:
sign and verify share the mutated function, so a renamed payload key or a
changed separator survives every issue→verify roundtrip test in the suite.
A roundtrip proves internal consistency; only a frozen vector proves the
FORMAT. These vectors pin the canonical bytes and the HMAC-SHA256 hex for a
fixed key at two points of the optional-field lattice, so any drift in key
names, ordering, separators, the included-only-when-set discipline or the
MAC construction breaks a committed literal instead of passing silently.

If one of these assertions fails, the wire format changed: that is a
BREAKING change for every verifier holding tokens in flight, and the right
response is a deliberate format version bump — never an update of the
vector to make the test pass.
"""
from __future__ import annotations

from remora.enforcement.token import _canonical_payload, _compute_signature

KEY = b"golden-vector-key-2026-08-25"

MINIMAL_PAYLOAD = (
    '{"action":"accept","issued_at":"2026-08-25T00:00:00+00:00",'
    '"observation_hash":"' + "a" * 64 + '","request_id":"req-golden-1"}'
).encode()
MINIMAL_SIG = "e827a798dcda79be400776e43dc039f5eae7d01eaa9fe79c32915c1b770a8f6f"

FULL_PAYLOAD = (
    '{"action":"accept","audience":"pep-exec",'
    '"expires_at":"2026-08-25T00:05:00+00:00",'
    '"issued_at":"2026-08-25T00:00:00+00:00","issuer":"remora-pdp",'
    '"jti":"jti-golden-1","kid":"k1",'
    '"observation_hash":"' + "b" * 64 + '","request_id":"req-golden-2"}'
).encode()
FULL_SIG = "fae6309b6eaf490f4298c3a2793c534bf7426911d8f48ef5fc70b0cb92d89504"


def test_minimal_payload_matches_the_golden_bytes() -> None:
    """No optional field set: none may appear, and the four mandatory keys
    appear under exactly these names, sorted, with compact separators."""
    got = _canonical_payload(
        action="accept",
        observation_hash="a" * 64,
        request_id="req-golden-1",
        issued_at="2026-08-25T00:00:00+00:00",
    )
    assert got == MINIMAL_PAYLOAD


def test_full_payload_matches_the_golden_bytes() -> None:
    """Every optional field set: each appears under its exact name. The
    included-only-when-set discipline is what lets pre-lifecycle tokens
    verify unchanged while a set field cannot be stripped unsigned."""
    got = _canonical_payload(
        action="accept",
        observation_hash="b" * 64,
        request_id="req-golden-2",
        issued_at="2026-08-25T00:00:00+00:00",
        expires_at="2026-08-25T00:05:00+00:00",
        jti="jti-golden-1",
        audience="pep-exec",
        kid="k1",
        issuer="remora-pdp",
    )
    assert got == FULL_PAYLOAD


def test_minimal_signature_matches_the_golden_hex() -> None:
    assert _compute_signature(MINIMAL_PAYLOAD, KEY) == MINIMAL_SIG


def test_full_signature_matches_the_golden_hex() -> None:
    assert _compute_signature(FULL_PAYLOAD, KEY) == FULL_SIG


def test_the_two_vectors_disagree() -> None:
    """A degenerate _compute_signature (constant output, key ignored) would
    pass a single vector; two distinct payloads under one key may never
    collide."""
    assert MINIMAL_SIG != FULL_SIG
    assert _compute_signature(MINIMAL_PAYLOAD, b"other-key") != MINIMAL_SIG
