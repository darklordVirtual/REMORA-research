# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation corpus-adequacy probes.

Interop agreement is not useful if producer and verifier share the same blind
spot.  These tests target cases that discriminate the safety semantics rather
than merely reproduce the current authored corpus.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_reference(package: str):
    path = ROOT / "artifacts" / "interop" / package / "reference_verifier.py"
    spec = importlib.util.spec_from_file_location(
        "pre_fed_reference_" + package.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_effect_reference_verifier_distinguishes_missing_from_exact_null():
    verifier = _load_reference("effect-evidence-v1")
    postcondition = {
        "tool_id": "update_ticket",
        "expected_fields": {"deleted_at": None},
        "comparison_rules": {"deleted_at": "exact"},
    }
    assert verifier.effect_status(postcondition, {}) == "EFFECT_MISMATCH"
    assert verifier.effect_status(
        postcondition, {"deleted_at": None}) == "EFFECT_VERIFIED"


def test_effect_fixture_corpus_contains_missing_vs_null_discriminator():
    path = ROOT / "artifacts/interop/effect-evidence-v1/fixtures.json"
    doc = json.loads(path.read_text(encoding="utf-8"))

    found = False
    for case in doc["cases"]:
        post = case.get("postcondition") or {}
        expected = post.get("expected_fields") or {}
        observed = case.get("observed")
        if observed is None:
            continue
        for name, wanted in expected.items():
            if wanted is None and name not in observed:
                found = True
                assert case["expected"]["effect_status"] == "EFFECT_MISMATCH"
    assert found, (
        "effect-evidence-v1 has no case separating an absent property from "
        "an explicitly present JSON null"
    )


def test_effect_reference_verifier_rejects_unknown_rule_instead_of_exact_fallback():
    verifier = _load_reference("effect-evidence-v1")
    postcondition = {
        "tool_id": "update_ticket",
        "expected_fields": {"status": "closed"},
        "comparison_rules": {"status": "excat"},
    }
    try:
        status = verifier.effect_status(postcondition, {"status": "closed"})
    except (KeyError, TypeError, ValueError):
        return
    assert status != "EFFECT_VERIFIED", (
        "invalid comparison-rule vocabulary silently became exact"
    )


def test_exact_call_federation_contract_names_temporal_mutation_boundary():
    """The current static call fixtures cannot detect verify-then-mutate TOCTOU.

    The package must either add a discriminating temporal case/harness or state
    explicitly that post-verification mutation of a mutable call object is
    outside the contract ceiling.
    """
    readme = (
        ROOT / "artifacts/interop/exact-call-binding-v1/README.md"
    ).read_text(encoding="utf-8").lower()
    ceiling_terms = (
        "post-verification mutation",
        "verify-then-mutate",
        "mutable argument",
        "toctou",
    )
    assert any(term in readme for term in ceiling_terms), (
        "exact-call-binding-v1 can be externally green while a live dispatcher "
        "executes a call mutated after its binding check; the temporal boundary "
        "is neither tested nor named in the package ceiling"
    )
