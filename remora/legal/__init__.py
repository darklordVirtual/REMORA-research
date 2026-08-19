# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Legal verification primitives.

Existence of a legal citation is an authoritative-registry fact, never a
model-consensus outcome. See citation_existence.py.
"""
from remora.legal.citation_existence import (
    CitationAssessment,
    CitationExistence,
    resolve_citation_existence,
)

__all__ = [
    "CitationAssessment",
    "CitationExistence",
    "resolve_citation_existence",
]
