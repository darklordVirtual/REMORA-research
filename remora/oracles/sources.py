# Author: Stian Skogbrott
# License: Apache-2.0
"""Source primitives for evidence-anchored answering.

Domain reliability is a coarse, transparent heuristic — extend via
SourceCorpus subclassing or by passing a domain_score map. The aim is a
deterministic, dependency-free baseline that downstream evidence policies
can layer over.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
from urllib.parse import urlparse


_DOMAIN_TIER = {
    # Tier 1: government, intergovernmental, accredited reference works.
    "gov": 0.95, "gov.uk": 0.95, "europa.eu": 0.95, "who.int": 0.95,
    "nih.gov": 0.95, "nasa.gov": 0.90, "nist.gov": 0.95,
    # Tier 2: peer-reviewed scientific publishers + academic.
    "nature.com": 0.85, "science.org": 0.85, "arxiv.org": 0.65,
    "edu": 0.80,
    # Tier 3: encyclopedic / reference.
    "wikipedia.org": 0.55, "britannica.com": 0.65,
    # Tier 4: general press (variable).
    "reuters.com": 0.70, "apnews.com": 0.70, "bbc.co.uk": 0.65, "bbc.com": 0.65,
}


@dataclass(frozen=True)
class Source:
    url: str
    text: str
    title: str | None = None
    published: str | None = None

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("Source.url must be non-empty")
        if not self.text:
            raise ValueError("Source.text must be non-empty")

    def domain(self) -> str:
        host = urlparse(self.url).hostname or ""
        return host.lower()


def _domain_score(domain: str) -> float:
    if not domain:
        return 0.30
    for suffix, score in _DOMAIN_TIER.items():
        if domain == suffix or domain.endswith("." + suffix):
            return score
    return 0.35


def score_reliability(source: Source) -> float:
    """Return a reliability score in [0, 1] from domain tier + text length."""
    dom = source.domain()
    base = _domain_score(dom)
    text_factor = min(1.0, len(source.text) / 400.0)
    return max(0.0, min(1.0, 0.7 * base + 0.3 * text_factor))


@dataclass(frozen=True)
class SourceCorpus:
    sources: Sequence[Source] = field(default_factory=tuple)

    def filter_by_min_reliability(self, threshold: float) -> "SourceCorpus":
        kept = tuple(s for s in self.sources if score_reliability(s) >= threshold)
        return SourceCorpus(sources=kept)
