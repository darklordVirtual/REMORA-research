from remora.counterfactual import generate_counterfactual, evaluate_causal_response
from remora.core import Oracle

class MockOracle(Oracle):
    def __init__(self, response_text):
        self._resp = response_text

    @property
    def name(self) -> str:
        return "mock"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        # raw response that resembles the expected format
        return (f'{{"counterfactual_question": "{self._resp}"}}', 0.0, 0.0)

def test_generate_counterfactual():
    oracle = MockOracle("If it rained, is the street dry?")
    res = generate_counterfactual("If it rained, is the street wet?", None, oracle)
    assert res == "If it rained, is the street dry?"

def test_evaluate_causal_response():
    # If polarities match, it fails the stress test (returns False)
    assert not evaluate_causal_response(True, True)
    assert not evaluate_causal_response(False, False)

    # If polarities are different, it passes (returns True)
    assert evaluate_causal_response(True, False)
    assert evaluate_causal_response(True, None)
