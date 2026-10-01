# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""success_established_v2: nested effects are part of "it happened" (NTA-2).

v1 is unchanged, so a verdict already given under it stays. v2 additionally
requires the execution_result to say every mediated nested effect settled.
"""
from __future__ import annotations

from remora.governance.evidence_coverage import (
    SUCCESS_ESTABLISHED,
    SUCCESS_ESTABLISHED_V2,
    CoverageStatus,
    EvidenceItem,
    assess_coverage,
)


def _items(nested):
    result = {"event": "execution_result", "tool_executed": True}
    if nested is not None:
        result["nested_effects"] = nested
    payloads = [
        {"event": "assessed", "capability": {"allowed": True}},
        {"event": "execution_authorized"},
        result,
        {"event": "effect_verified", "status": "EFFECT_VERIFIED"},
    ]
    return [EvidenceItem(kind=p["event"], payload=p, ref=str(i),
                         sha256=None, authenticity=None) for i, p in enumerate(payloads)]


def _status(contract, nested):
    from remora.governance.evidence_coverage import Authenticity

    return assess_coverage(contract, _items(nested),
                           verify=lambda item: Authenticity.AUTHENTIC).status


def test_settled_nested_effects_complete_v2():
    nested = {"mediated": True, "count": 2, "settled": True}
    assert _status(SUCCESS_ESTABLISHED_V2, nested) is CoverageStatus.COMPLETE


def test_an_unmediated_tool_completes_v2():
    nested = {"mediated": False, "count": 0, "settled": True}
    assert _status(SUCCESS_ESTABLISHED_V2, nested) is CoverageStatus.COMPLETE


def test_an_unknown_child_leaves_v2_incomplete_while_v1_is_complete():
    nested = {"mediated": True, "count": 1, "settled": False}
    assert _status(SUCCESS_ESTABLISHED, nested) is CoverageStatus.COMPLETE
    assert _status(SUCCESS_ESTABLISHED_V2, nested) is CoverageStatus.AUTHENTIC_BUT_INCOMPLETE


def test_a_record_from_before_nested_effects_stays_complete_under_v1_only():
    assert _status(SUCCESS_ESTABLISHED, None) is CoverageStatus.COMPLETE
    assert _status(SUCCESS_ESTABLISHED_V2, None) is CoverageStatus.AUTHENTIC_BUT_INCOMPLETE


def test_v2_names_the_nested_requirement_when_it_is_missing():
    from remora.governance.evidence_coverage import Authenticity

    verdict = assess_coverage(SUCCESS_ESTABLISHED_V2,
                              _items({"mediated": True, "settled": False}),
                              verify=lambda item: Authenticity.AUTHENTIC)
    assert "execution_result[nested_effects.settled=True,tool_executed=True]" in verdict.missing
