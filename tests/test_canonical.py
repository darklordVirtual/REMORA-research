# Author: Stian Skogbrott
# License: Apache-2.0
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
