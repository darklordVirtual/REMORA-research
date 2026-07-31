# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import re
from typing import Any, Callable, Literal, Protocol

EvidenceRelation = Literal["supports", "contradicts", "insufficient"]

_NEG_TOKENS = frozenset({
    "not", "no", "never", "neither", "without", "doesn't", "isn't",
    "wasn't", "weren't", "cannot", "can't",
})


class EvidenceVerifierProtocol(Protocol):
    def classify(self, claim: str, snippet: str) -> EvidenceRelation:
        ...


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(t) >= 2}


def lexical_score(claim: str, snippet: str) -> float:
    claim_toks = tokens(claim)
    snippet_toks = tokens(snippet)
    if not claim_toks or not snippet_toks:
        return 0.0
    return len(claim_toks & snippet_toks) / len(claim_toks | snippet_toks)


def has_negation(text: str) -> bool:
    return bool(tokens(text) & _NEG_TOKENS)


class LexicalEvidenceVerifier:
    def __init__(self, support_threshold: float = 0.15, contradiction_threshold: float = 0.30) -> None:
        self.support_threshold = support_threshold
        self.contradiction_threshold = contradiction_threshold

    def classify(self, claim: str, snippet: str) -> EvidenceRelation:
        score = lexical_score(claim, snippet)
        if score >= self.contradiction_threshold and has_negation(claim) != has_negation(snippet):
            return "contradicts"
        if score >= self.support_threshold:
            return "supports"
        return "insufficient"


NLIClassifierFn = Callable[[str, str], EvidenceRelation | tuple[EvidenceRelation, float]]
LLMClassifierFn = Callable[[str, str], Any]


class NLIEvidenceVerifier:
    """Pluggable NLI-style verifier with optional local semantic Cross-Encoder.

    Parameters
    ----------
    nli_fn:
        Optional custom NLI classifier callable.
    fallback:
        Verifier fallback. Defaults to LexicalEvidenceVerifier.
    use_local_nli:
        If True, attempts to load a sentence-transformers cross-encoder
        (default "cross-encoder/nli-deberta-v3-small") to perform true
        semantic NLI evaluation rather than falling back to lexical checks.
    nli_model_name:
        Model name to use when use_local_nli is True.
    support_threshold:
        Threshold probability for "supports" classification. Default 0.5.
    contradiction_threshold:
        Threshold probability for "contradicts" classification. Default 0.5.
    """

    def __init__(
        self,
        nli_fn: NLIClassifierFn | None = None,
        fallback: EvidenceVerifierProtocol | None = None,
        use_local_nli: bool = False,
        nli_model_name: str = "cross-encoder/nli-deberta-v3-small",
        support_threshold: float = 0.5,
        contradiction_threshold: float = 0.5,
    ) -> None:
        self.nli_fn = nli_fn
        self.fallback = fallback or LexicalEvidenceVerifier()
        self.use_local_nli = use_local_nli
        self.nli_model_name = nli_model_name
        self.support_threshold = support_threshold
        self.contradiction_threshold = contradiction_threshold
        self._encoder = None

        if self.use_local_nli and self.nli_fn is None:
            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import]
                self._encoder = CrossEncoder(self.nli_model_name)
            except ImportError:
                import warnings
                warnings.warn(
                    "sentence-transformers is not installed. NLIEvidenceVerifier "
                    "falling back to LexicalEvidenceVerifier."
                )

    def classify(self, claim: str, snippet: str) -> EvidenceRelation:
        if self.nli_fn is not None:
            out = self.nli_fn(claim, snippet)
            if isinstance(out, tuple):
                label = out[0]
            else:
                label = out
            if label in {"supports", "contradicts", "insufficient"}:
                return label  # type: ignore[return-value]
            return "insufficient"

        if self.use_local_nli and self._encoder is not None:
            import numpy as np  # type: ignore[import]
            # Use snippet as premise and claim as hypothesis
            scores = self._encoder.predict([(snippet, claim)])
            logits = scores[0]
            exp_logits = np.exp(logits - np.max(logits))
            probs = exp_logits / exp_logits.sum()
            contradiction_prob = float(probs[0])
            entailment_prob = float(probs[1])

            if entailment_prob >= self.support_threshold:
                return "supports"
            if contradiction_prob >= self.contradiction_threshold:
                return "contradicts"
            return "insufficient"

        return self.fallback.classify(claim, snippet)


class LLMJudgeVerifier:
    """Full LLM-judge backed verifier implementing EvidenceVerifierProtocol.

    Uses remora.verifier.LLMJudge (oracle-based) to classify claim vs snippet.
    This is the production-quality replacement for LexicalEvidenceVerifier.

    Map from JudgeOutcome → EvidenceRelation:
      supported  → supports
      refuted    → contradicts
      challenged → insufficient
      parse_error → insufficient (fallback to lexical)
    """

    def __init__(self, oracle, fallback: EvidenceVerifierProtocol | None = None) -> None:
        from remora.verifier.llm_judge import LLMJudge, JudgeOutcome
        self._judge = LLMJudge(oracle)
        self._JudgeOutcome = JudgeOutcome
        self.fallback = fallback or LexicalEvidenceVerifier()

    def classify(self, claim: str, snippet: str) -> EvidenceRelation:
        JudgeOutcome = self._JudgeOutcome
        try:
            verdict = self._judge.evaluate(
                question=claim,
                answer=claim,
                evidence=[snippet],
            )
            if verdict.outcome == JudgeOutcome.SUPPORTED:
                return "supports"
            if verdict.outcome == JudgeOutcome.REFUTED:
                return "contradicts"
            if verdict.outcome == JudgeOutcome.PARSE_ERROR:
                return self.fallback.classify(claim, snippet)
            return "insufficient"
        except Exception:
            return self.fallback.classify(claim, snippet)


class LLMEvidenceVerifier:
    """LLM-backed verifier adapter with strict schema mapping.

    Expected classifier output can be one of:
    - EvidenceRelation string
    - {"verdict": "<supports|contradicts|insufficient>", "confidence": float}
    """

    def __init__(
        self,
        llm_fn: LLMClassifierFn | None = None,
        fallback: EvidenceVerifierProtocol | None = None,
    ) -> None:
        self.llm_fn = llm_fn
        self.fallback = fallback or LexicalEvidenceVerifier()

    def classify(self, claim: str, snippet: str) -> EvidenceRelation:
        if self.llm_fn is None:
            return self.fallback.classify(claim, snippet)
        out = self.llm_fn(claim, snippet)
        if isinstance(out, str):
            label = out
        elif isinstance(out, dict):
            label = out.get("verdict", "insufficient")
        else:
            label = "insufficient"
        if label in {"supports", "contradicts", "insufficient"}:
            return label  # type: ignore[return-value]
        return "insufficient"
