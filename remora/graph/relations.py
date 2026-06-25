# Author: Stian Skogbrott
# License: Apache-2.0
"""Heuristic claim-relation inference.

Returns one of {SUPPORTS, CONTRADICTS, ENTAILS, REFUTES, UNRELATED}. The
inference is intentionally transparent and dependency-free; oracle-assisted
inference can be plugged in by replacing infer_relation in the call site.
"""
from __future__ import annotations

import re
from enum import Enum


_NEG_TOKENS = {"not", "no", "never", "without", "doesn't", "don't",
               "didn't", "isn't", "wasn't", "won't", "cannot", "can't"}


class Relation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    ENTAILS = "entails"
    REFUTES = "refutes"
    UNRELATED = "unrelated"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+", text.lower()))


def _has_negation(text: str) -> bool:
    return bool(_tokens(text) & _NEG_TOKENS)


def infer_relation(a: str, b: str, topic_overlap: float = 0.30) -> Relation:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return Relation.UNRELATED
    overlap = len(ta & tb) / len(ta | tb)
    if overlap < topic_overlap:
        return Relation.UNRELATED
    neg_a, neg_b = _has_negation(a), _has_negation(b)
    if neg_a != neg_b:
        return Relation.CONTRADICTS
    # Subset heuristic: negated subsets refute the positive entailment;
    # positive subsets entail.
    if ta <= tb or tb <= ta:
        if neg_a and neg_b:
            return Relation.REFUTES
        return Relation.ENTAILS
    return Relation.SUPPORTS
