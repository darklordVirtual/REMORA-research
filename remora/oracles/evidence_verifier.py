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
    """Pluggable NLI-style verifier.

    If no custom nli_fn is provided, this class falls back to lexical behavior.
    This is a structural interface upgrade; semantic performance must be
    demonstrated separately.
    """

    def __init__(
        self,
        nli_fn: NLIClassifierFn | None = None,
        fallback: EvidenceVerifierProtocol | None = None,
    ) -> None:
        self.nli_fn = nli_fn
        self.fallback = fallback or LexicalEvidenceVerifier()

    def classify(self, claim: str, snippet: str) -> EvidenceRelation:
        if self.nli_fn is None:
            return self.fallback.classify(claim, snippet)
        out = self.nli_fn(claim, snippet)
        if isinstance(out, tuple):
            label = out[0]
        else:
            label = out
        if label in {"supports", "contradicts", "insufficient"}:
            return label
        return "insufficient"


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
            return label
        return "insufficient"
