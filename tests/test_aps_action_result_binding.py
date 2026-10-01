# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Bounded REMORA digest regressions against APS b64cc8df.

These exercise REMORA's existing mapping, without importing an APS SDK.
They do not establish stage/composite validity, authorization, or an effect.
SDK MATCH, draft text, and Replay derivations remain in the upstream vectors.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from remora.interop.aps.mappings import (
    MappingRefused,
    classify_receipt_decision_relation,
    receipt_decision_ref,
)

FIXTURES = Path(__file__).parent / "fixtures/aps-action-result-binding-b64cc8df"
PINS = {
    "chain.json": "93415285378cd2241476ab94114c50dec85b330bb8c0b1f6c75d252274b0432a",
    "vectors.json": "1cbad25150e4779ef067e269329b0954b966898d6ca933a98b2e3949b23d117b",
}


def _load(name: str) -> dict:
    data = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == PINS[name], "upstream fixture drift"
    return json.loads(data)


VECTORS = _load("vectors.json")["cases"]


@pytest.fixture
def chain() -> dict:
    return _load("chain.json")


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["id"])
def test_exact_decision_evidence_and_record_action_ref_match_pin(chain, vector):
    """Catch changes in domain tags, canonicalization, or action_ref selection."""
    record = chain["cases"][vector["case"]]
    evidence = chain["decision_evidence"][vector["decision_evidence"]]
    observed = receipt_decision_ref(record["action_ref"], evidence)
    binding = vector["decision_ref_binding"]
    assert observed == binding["recomputed_from_permit_evidence"]
    assert (observed == record["decision_ref"]) is binding["equals_record_decision_ref"]


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["id"])
def test_evidence_substitution_breaks_pin_with_record_unchanged(chain, vector):
    """Catch cached/ignored evidence even when a rejection code stays the same."""
    record = chain["cases"][vector["case"]]
    before = copy.deepcopy(record)
    binding = vector["decision_ref_binding"]
    assert receipt_decision_ref(
        record["action_ref"], chain["decision_evidence"]["permit"]
    ) == binding["recomputed_from_permit_evidence"]
    swapped = receipt_decision_ref(
        record["action_ref"], chain["decision_evidence"]["deny"]
    )
    assert swapped != binding["recomputed_from_permit_evidence"]
    assert record == before


def test_positive_result_fails_closed_when_only_decision_evidence_is_swapped(chain):
    """Catch removal of the real relation verifier's digest-mismatch gate."""
    record = chain["cases"]["positive"]
    before = copy.deepcopy(record)
    # PASS here is the legacy narrow digest/time relation, not an APS verdict.
    assert classify_receipt_decision_relation(
        receipt=record, evidence=chain["decision_evidence"]["permit"]
    ) == "PASS"
    assert classify_receipt_decision_relation(
        receipt=record, evidence=chain["decision_evidence"]["deny"]
    ) == "DECISION_REF_MISMATCH"
    assert record == before


def test_case_5_same_rejection_does_not_establish_same_evidence(chain):
    """The concrete counterexample to using only an error code as provenance."""
    record = chain["cases"]["action-ref-mismatch"]
    observations = {}
    for name in ("permit", "deny"):
        evidence = chain["decision_evidence"][name]
        assert classify_receipt_decision_relation(
            receipt=record, evidence=evidence
        ) == "DECISION_REF_MISMATCH"
        observations[name] = receipt_decision_ref(record["action_ref"], evidence)
    assert observations["permit"] == (
        "911ece7f7ed1dea3b8f1c8f9932c4caecb479f6612ec3ab87c64754ad6f6e703"
    )
    assert observations["deny"] != observations["permit"]


def test_deny_binding_differs_without_inventing_an_authority_lifecycle(chain):
    """Catch a digest that omits the decision context/output components."""
    permit = chain["decision_evidence"]["permit"]
    deny = chain["decision_evidence"]["deny"]
    assert deny["authority_state"] == permit["authority_state"]
    assert deny["policy_input"] == permit["policy_input"]
    action_ref = chain["cases"]["positive"]["action_ref"]
    assert receipt_decision_ref(action_ref, permit) == chain["decision_refs"]["permit"]
    assert receipt_decision_ref(action_ref, deny) == chain["decision_refs"]["deny"]
    assert chain["decision_refs"]["permit"] != chain["decision_refs"]["deny"]


@pytest.mark.parametrize(
    "missing", ["authority_state", "policy_input", "decision_context", "decision_output"]
)
def test_missing_decision_evidence_component_is_refused(chain, missing):
    """No fallback to empty, cached, or inferred evidence components."""
    evidence = copy.deepcopy(chain["decision_evidence"]["permit"])
    del evidence[missing]
    with pytest.raises(MappingRefused, match="decision evidence is incomplete"):
        receipt_decision_ref(chain["cases"]["positive"]["action_ref"], evidence)
