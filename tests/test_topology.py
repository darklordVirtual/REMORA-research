import pytest

from remora.topology import compute_betti_numbers

def test_compute_betti_numbers():
    # 1. Perfect agreement -> Betti 0 = 1, Betti 1 = 0
    with pytest.warns(DeprecationWarning, match="fingerprint clusters"):
        res = compute_betti_numbers([("o1", "fp_a"), ("o2", "fp_a"), ("o3", "fp_a")])
    assert res["betti_0"] == 1
    assert res["betti_1"] == 0
    assert not res["topological_collapse"]

    # 2. Total disagreement -> Betti 0 = 3, Betti 1 = 0
    with pytest.warns(DeprecationWarning, match="fingerprint clusters"):
        res = compute_betti_numbers([("o1", "fp_a"), ("o2", "fp_b"), ("o3", "fp_c")])
    assert res["betti_0"] == 3
    assert res["betti_1"] == 0

    # 3. Overlapping logic / fuzzy contradiction -> Betti 1 > 0
    # E.g. o1 supports both fp_a and fp_b (maybe via different sub-claims)
    with pytest.warns(DeprecationWarning, match="fingerprint clusters"):
        res = compute_betti_numbers([("o1", "fp_a"), ("o1", "fp_b"), ("o2", "fp_b")])
    assert res["betti_0"] == 2
    assert res["betti_1"] >= 1
    assert res["topological_collapse"]


def test_compute_betti_numbers_emits_deprecation_warning():
    import warnings
    from remora.topology import compute_betti_numbers
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compute_betti_numbers([("o1", "fp1"), ("o2", "fp1")])
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
