from __future__ import annotations

import pytest

from remora.oracles.evidence_verifier import (
    LLMEvidenceVerifier,
    NLIEvidenceVerifier,
    LexicalEvidenceVerifier,
)


def test_lexical_verifier_is_deterministic() -> None:
    verifier = LexicalEvidenceVerifier()
    claim = "Aspirin reduces inflammation"
    snippet = "Aspirin reduces inflammation in clinical use"
    assert verifier.classify(claim, snippet) == verifier.classify(claim, snippet)


def test_nli_verifier_uses_custom_classifier() -> None:
    verifier = NLIEvidenceVerifier(nli_fn=lambda c, s: "supports")
    assert verifier.classify("claim", "snippet") == "supports"

    verifier_tuple = NLIEvidenceVerifier(nli_fn=lambda c, s: ("contradicts", 0.99))
    assert verifier_tuple.classify("claim", "snippet") == "contradicts"


def test_nli_verifier_falls_back_to_lexical_when_missing_or_invalid() -> None:
    fallback = LexicalEvidenceVerifier(support_threshold=0.0, contradiction_threshold=1.1)
    verifier = NLIEvidenceVerifier(nli_fn=None, fallback=fallback)
    assert verifier.classify("any claim", "any snippet") == "supports"

    invalid = NLIEvidenceVerifier(nli_fn=lambda c, s: "unknown")
    assert invalid.classify("claim", "snippet") == "insufficient"


def test_llm_verifier_maps_string_and_dict_outputs() -> None:
    v_str = LLMEvidenceVerifier(llm_fn=lambda c, s: "supports")
    assert v_str.classify("claim", "snippet") == "supports"

    v_dict = LLMEvidenceVerifier(llm_fn=lambda c, s: {"verdict": "contradicts", "confidence": 0.8})
    assert v_dict.classify("claim", "snippet") == "contradicts"

    v_invalid = LLMEvidenceVerifier(llm_fn=lambda c, s: {"verdict": "maybe"})
    assert v_invalid.classify("claim", "snippet") == "insufficient"


def test_nli_verifier_with_mocked_local_cross_encoder() -> None:
    # The local-NLI branch softmaxes its logits with numpy, which arrives only
    # with the `analysis` extra (and transitively with the NLI stack). The
    # deterministic CI job installs [dev,causal,api], so numpy is genuinely
    # absent there and this test must skip rather than fail — it covers an
    # optional-dependency path, not a core one.
    pytest.importorskip("numpy")
    from unittest.mock import MagicMock

    mock_encoder = MagicMock()
    mock_encoder.predict.side_effect = lambda pairs: {
        ("snippet supports", "claim"): [[0.0, 10.0, 0.0]],
        ("snippet opposes", "claim"): [[10.0, 0.0, 0.0]],
        ("snippet neutral", "claim"): [[0.0, 0.0, 10.0]],
    }[pairs[0]]

    verifier = NLIEvidenceVerifier(use_local_nli=True)
    verifier._encoder = mock_encoder

    assert verifier.classify("claim", "snippet supports") == "supports"
    assert verifier.classify("claim", "snippet opposes") == "contradicts"
    assert verifier.classify("claim", "snippet neutral") == "insufficient"

