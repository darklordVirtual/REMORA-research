import pytest
np = pytest.importorskip("numpy")
from remora.future_concept.auto_formalization import Lean4Compiler, FormalProof
from remora.future_concept.weight_grafting import NeuralSplicer, GraftedModel
from remora.future_concept.kv_intercept import SubTokenInterceptor

def test_auto_formalization():
    compiler = Lean4Compiler()
    proof = compiler.formalize_consensus("A and B implies A", {})
    assert isinstance(proof, FormalProof)
    assert not proof.is_verified
    assert proof.theorem_statement == "A and B implies A"

    is_valid = compiler.verify_proof(proof)
    assert not is_valid

def test_weight_grafting():
    splicer = NeuralSplicer()
    base = {"layer.1.weight": np.array([1, 2, 3]), "layer.2.weight": np.array([4, 5, 6])}
    donor = {"layer.1.weight": np.array([7, 8, 9])}

    model = splicer.splice_layers(base, donor, ["layer.1.weight"])
    assert isinstance(model, GraftedModel)
    assert "layer.1.weight" in model.grafted_layers
    assert (base["layer.1.weight"] == np.array([7, 8, 9])).all()

    stability = splicer.evaluate_graft_stability(model)
    assert stability == 0.95

def test_kv_intercept():
    interceptor = SubTokenInterceptor(alpha=0.1)

    # Stable state (no betti hole)
    res_stable = interceptor.monitor_kv_cache([10.0, 5.0], [0.1, 0.2, 0.1])
    assert not res_stable.betti_hole_detected
    assert res_stable.original_logit == res_stable.modified_logit

    # Dissonant state (betti hole)
    res_dissonant = interceptor.monitor_kv_cache([10.0, 5.0], [5.0, 6.0, 5.0]) # high values for higher score
    assert res_dissonant.betti_hole_detected
    assert res_dissonant.modified_logit < res_dissonant.original_logit
