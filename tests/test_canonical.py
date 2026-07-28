# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for remora.canonical — the φ canonicalisation function."""
from remora.canonical import (
    CanonicalVerdict, phi, _coerce_polarity, _claim_hash,
)


def test_phi_returns_canonical_verdict():
    v = phi({"answer": True, "claim": "The sky is blue"})
    assert isinstance(v, CanonicalVerdict)


def test_polarity_coercion_true_variants():
    for val in [True, "yes", "true", "ja", "True", 1]:
        assert _coerce_polarity(val) is True


def test_polarity_coercion_false_variants():
    for val in [False, "no", "false", "nei", "False", 0]:
        assert _coerce_polarity(val) is False


def test_polarity_coercion_none_variants():
    for val in [None, "unknown", "null", "ukjent"]:
        assert _coerce_polarity(val) is None


def test_equivalence_yes_true():
    a = phi({"answer": "yes", "claim": "X is Y"})
    b = phi({"answer": True, "claim": "X is Y"})
    assert a.equivalent_to(b)


def test_claim_hash_order_invariant():
    h1 = _claim_hash("X er Y")
    h2 = _claim_hash("Y er X")
    assert h1 == h2


def test_fingerprint_stability():
    v = phi({"answer": True, "claim": "DNA is a double helix"})
    assert v.fingerprint() == v.fingerprint()


def test_fingerprint_stable_under_confidence_variation():
    # F1 (external review 2026-07-28): self-reported confidence is verdict
    # METADATA, not identity. Identical claim+polarity must share one
    # consensus bucket regardless of the confidence the oracle attaches.
    for lo, hi in [(0.1, 0.9), (0.0, 1.0), (0.4999, 0.5001)]:
        a = phi({"claim": "The sky is blue", "answer": True, "confidence": lo})
        b = phi({"claim": "The sky is blue", "answer": True, "confidence": hi})
        assert a.fingerprint() == b.fingerprint()
        assert a.equivalent_to(b)


def test_fingerprint_still_separates_polarity_and_claim():
    base = phi({"claim": "The sky is blue", "answer": True})
    flipped = phi({"claim": "The sky is blue", "answer": False})
    other = phi({"claim": "Grass is red", "answer": True})
    assert base.fingerprint() != flipped.fingerprint()
    assert base.fingerprint() != other.fingerprint()


def test_full_fingerprint_keeps_magnitude_sensitivity():
    a = phi({"claim": "X", "answer": True, "confidence": 0.9})
    b = phi({"claim": "X", "answer": True, "confidence": 0.1})
    assert a.full_fingerprint() != b.full_fingerprint()
    assert a.fingerprint() == b.fingerprint()


def test_unstructured_fallback():
    v = phi({"unstructured": "yes this is correct"})
    assert v.polarity is True


def test_empty_dict():
    v = phi({})
    assert v.polarity is None


def test_negation_extraction():
    v = phi({"not": ["option A", "option B"], "denies": "wrong claim"})
    assert v.claim_hash != "empty"


def test_nei_is_false_not_uncertain():
    """'nei' must be False, not None — it was previously in both FALSE and UNCERTAIN sets."""
    assert _coerce_polarity("nei") is False


def test_different_polarities_not_equivalent():
    a = phi({"answer": True, "claim": "X is Y"})
    b = phi({"answer": False, "claim": "X is Y"})
    assert not a.equivalent_to(b)
