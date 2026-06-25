# Author: Stian Skogbrott
# License: Apache-2.0
"""Canonicalisation function φ: raw_output → 𝒱 for REMORA."""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

_TRUE_TOKENS = {"true","yes","ja","sant","stemmer","korrekt","riktig","1","affirmative","supports","support"}
_FALSE_TOKENS = {"false","no","nei","usant","feil","galt","0","negative","refutes","refute","contradicts"}
_UNCERTAIN_TOKENS = {"unknown","ukjent","usikker","uncertain","maybe","kanskje","null","none","not enough info","ikke nok info","uavklart"}
_STOPWORDS = {"the","a","an","is","are","was","were","be","been","being","of","to","in","on","at","for","and","or","but","with","et","en","er","var","vil","som","og","eller","men","av","i","på","til","for","fra","med","om","den","det","de","ikke","har","hadde","kan","skal","blir","ble"}

@dataclass(frozen=True)
class CanonicalVerdict:
    """Immutable canonical verdict produced by φ."""

    polarity: Optional[bool]
    claim_hash: str
    magnitude: Optional[float]
    tags: tuple[str, ...] = field(default_factory=tuple)

    def fingerprint(self) -> str:
        """Return a 16-char hex fingerprint of this verdict."""
        payload = {"p": self.polarity, "c": self.claim_hash, "m": self.magnitude, "t": list(self.tags)}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def equivalent_to(self, other: "CanonicalVerdict") -> bool:
        """Return True when this verdict is fingerprint-equivalent to other."""
        return self.fingerprint() == other.fingerprint()


def _normalize_text(s: str) -> str:
    """NFKC-normalize, lowercase, strip punctuation, and collapse whitespace."""
    s = unicodedata.normalize("NFKC", s).lower().strip()
    s = re.sub(r"[^\w\sæøåäöü]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokenize_filtered(s: str) -> list[str]:
    """Return content tokens from s with stopwords removed."""
    return [t for t in _normalize_text(s).split() if t and t not in _STOPWORDS and len(t) > 1]


def _claim_hash(text: str) -> str:
    """Return a 16-char hex hash of the sorted content tokens in text."""
    if not text:
        return "empty"
    tokens = sorted(set(_tokenize_filtered(text)))
    return hashlib.sha256(" ".join(tokens).encode()).hexdigest()[:16] if tokens else "empty"


def _coerce_polarity(value: Any) -> Optional[bool]:
    """Coerce an arbitrary value to True, False, or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        v = _normalize_text(value)
        if v in _TRUE_TOKENS or any(t in v.split() for t in _TRUE_TOKENS):
            return True
        if v in _FALSE_TOKENS or any(t in v.split() for t in _FALSE_TOKENS):
            return False
        if v in _UNCERTAIN_TOKENS:
            return None
    return None


def _coerce_magnitude(d: dict) -> Optional[float]:
    """Extract the first numeric magnitude-like value from d."""
    for key in ("magnitude", "value", "score", "confidence", "probability"):
        if key in d and isinstance(d[key], (int, float)):
            return round(float(d[key]), 3)
    return None


def _extract_tags(d: dict) -> tuple[str, ...]:
    """Collect tag strings from known tag-list keys in d."""
    tags: set[str] = set()
    for key in ("tags", "categories", "labels", "topics"):
        v = d.get(key)
        if isinstance(v, list):
            tags.update(str(x).strip().lower() for x in v if str(x).strip())
        elif isinstance(v, str):
            tags.add(v.strip().lower())
    return tuple(sorted(tags))


def phi(extracted: dict) -> CanonicalVerdict:
    """Apply the canonicalisation function φ to an extracted dict."""
    if not isinstance(extracted, dict):
        return CanonicalVerdict(
            polarity=None,
            claim_hash=_claim_hash(str(extracted) if extracted else ""),
            magnitude=None,
            tags=(),
        )
    if "unstructured" in extracted:
        text = str(extracted["unstructured"])
        return CanonicalVerdict(
            polarity=_extract_polarity_from_text(text),
            claim_hash=_claim_hash(text),
            magnitude=None,
            tags=(),
        )
    pol = None
    for key in ("answer", "verdict", "polarity", "value", "stance"):
        if key in extracted:
            pol = _coerce_polarity(extracted[key])
            if pol is not None or extracted[key] in (None, "null"):
                break
    text_parts = []
    for key in ("claim", "answer_text", "reasoning", "statement"):
        v = extracted.get(key)
        if isinstance(v, str) and v.strip():
            text_parts.append(v)
        elif isinstance(v, list):
            text_parts.extend(str(x) for x in v if x)
    for key in ("not", "denies"):
        v = extracted.get(key)
        if isinstance(v, str) and v.strip():
            text_parts.append(f"NOT: {v}")
        elif isinstance(v, list):
            text_parts.extend(f"NOT: {x}" for x in v if x)
    return CanonicalVerdict(
        polarity=pol,
        claim_hash=_claim_hash(" ".join(text_parts)),
        magnitude=_coerce_magnitude(extracted),
        tags=_extract_tags(extracted),
    )


def _extract_polarity_from_text(text: str) -> Optional[bool]:
    """Infer polarity from free text by token voting."""
    if not text:
        return None
    norm = _normalize_text(text)
    tokens = set(norm.split())
    true_hits = len(tokens & _TRUE_TOKENS)
    false_hits = len(tokens & _FALSE_TOKENS)
    uncertain_hits = len(tokens & _UNCERTAIN_TOKENS)
    if uncertain_hits > max(true_hits, false_hits):
        return None
    if true_hits > false_hits:
        return True
    if false_hits > true_hits:
        return False
    return None
