# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for source primitives."""
from __future__ import annotations

import pytest

from remora.oracles.sources import Source, SourceCorpus, score_reliability


def test_source_requires_url_and_text():
    with pytest.raises(ValueError):
        Source(url="", text="some text")
    with pytest.raises(ValueError):
        Source(url="https://example.com", text="")


def test_score_reliability_favours_known_domains():
    high = score_reliability(Source(url="https://www.gov.uk/x", text="..."))
    low = score_reliability(Source(url="https://random-blog.example/x", text="..."))
    assert high > low


def test_score_reliability_penalises_very_short_text():
    short = score_reliability(Source(url="https://example.edu/x", text="ok"))
    long = score_reliability(Source(url="https://example.edu/x", text="a" * 500))
    assert long > short


def test_corpus_filter_by_min_reliability_returns_subset():
    corpus = SourceCorpus(sources=[
        Source(url="https://www.nih.gov/a", text="a" * 500),
        Source(url="https://blog.example/b", text="b"),
    ])
    filtered = corpus.filter_by_min_reliability(0.5)
    assert all(s.url.endswith("/a") for s in filtered.sources)
