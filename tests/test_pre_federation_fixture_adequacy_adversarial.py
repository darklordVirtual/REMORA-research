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
    verifier = _load_reference("effect-evidence-v1.1")
    postcondition = {
        "tool_id": "update_ticket",
        "expected_fields": {"deleted_at": None},
        "comparison_rules": {"deleted_at": "exact"},
    }
    assert verifier.effect_status(postcondition, {}) == "EFFECT_MISMATCH"
    assert verifier.effect_status(
        postcondition, {"deleted_at": None}) == "EFFECT_VERIFIED"


def test_effect_fixture_corpus_contains_missing_vs_null_discriminator():
    path = ROOT / "artifacts/interop/effect-evidence-v1.1/fixtures.json"
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
    verifier = _load_reference("effect-evidence-v1.1")
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
        ROOT / "artifacts/interop/exact-call-binding-v1.1/README.md"
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


def test_exact_call_fixture_corpus_contains_integral_float_type_change():
    """Scalar-type significance needs a discriminator portable verifiers can fail.

    JSON's textual 1 and 1.0 parse to different Python scalar kinds but collapse
    to one JavaScript Number.  A verifier can pass the current string-vs-int
    case while still being unable to implement the published contract here.
    """
    path = ROOT / "artifacts/interop/exact-call-binding-v1.1/fixtures.json"
    doc = json.loads(path.read_text(encoding="utf-8"))

    found = False
    for case in doc["cases"]:
        auth = case.get("authorization", {}).get("arguments", {})
        for presented in case.get("dispatches", []):
            args = presented.get("arguments", {})
            for key, before in auth.items():
                if key not in args:
                    continue
                after = args[key]
                if (
                    type(before) is int and type(after) is float
                    and float(before) == after
                ) or (
                    type(before) is float and type(after) is int
                    and before == float(after)
                ):
                    found = True
                    assert case["expected"]["outcomes"][0]["outcome"] == "REFUSED"
    assert found, (
        "exact-call-binding-v1 says scalar types are significant but has no "
        "integer-vs-integral-float discriminator"
    )


# ── Preserved negative result: the frozen v1 packages keep their blind spots ──
#
# exact-call-binding-v1 and effect-evidence-v1 are frozen and external runs
# pin their digests, so the probes above were answered by v1.1 successors
# rather than by rewriting v1. These tests pin the v1 blind spots as they are.
# If one starts failing, the v1 bytes changed, which a frozen package must not.


def test_v1_effect_reference_verifier_still_reads_missing_as_null():
    verifier = _load_reference("effect-evidence-v1")
    postcondition = {
        "tool_id": "update_ticket",
        "expected_fields": {"deleted_at": None},
        "comparison_rules": {"deleted_at": "exact"},
    }
    assert verifier.effect_status(postcondition, {}) == "EFFECT_VERIFIED"


def test_v1_effect_reference_verifier_still_falls_back_to_exact_for_unknown_rule():
    verifier = _load_reference("effect-evidence-v1")
    postcondition = {
        "tool_id": "update_ticket",
        "expected_fields": {"status": "closed"},
        "comparison_rules": {"status": "excat"},
    }
    assert verifier.effect_status(postcondition, {"status": "closed"}) == "EFFECT_VERIFIED"


def test_v1_corpora_still_lack_the_discriminators():
    effect = json.loads((ROOT / "artifacts/interop/effect-evidence-v1/fixtures.json").read_text(encoding="utf-8"))
    for case in effect["cases"]:
        expected = (case.get("postcondition") or {}).get("expected_fields") or {}
        observed = case.get("observed")
        assert observed is None or not any(
            wanted is None and name not in observed for name, wanted in expected.items())
    call = json.loads((ROOT / "artifacts/interop/exact-call-binding-v1/fixtures.json").read_text(encoding="utf-8"))
    for case in call["cases"]:
        auth = case["authorization"]["arguments"]
        for presented in case["dispatches"]:
            for key, before in auth.items():
                after = presented["arguments"].get(key)
                assert {type(before), type(after)} != {int, float}, case["id"]
    readme = (ROOT / "artifacts/interop/exact-call-binding-v1/README.md").read_text(encoding="utf-8").lower()
    for term in ("post-verification mutation", "verify-then-mutate", "mutable argument", "toctou"):
        assert term not in readme


def test_v1_effect_reference_verifier_fails_exactly_the_v1_1_repair_cases():
    """The v1.1 additions discriminate: the v1 verifier is wrong on the cases
    that target its blind spots and right on every carried-over v1 case."""
    v1 = _load_reference("effect-evidence-v1")
    doc = json.loads((ROOT / "artifacts/interop/effect-evidence-v1.1/fixtures.json").read_text(encoding="utf-8"))
    wrong = set()
    for case in doc["cases"]:
        expected = {k: case["expected"][k] for k in ("effect_status", "highest_established_state")}
        if v1.evaluate(case) != expected:
            wrong.add(case["id"])
    assert wrong == {
        "exact_null_field_missing",
        "hash_rule_field_missing",
        "unknown_comparison_rule",
        "unknown_rule_with_unobservable_object",
        "rule_for_undeclared_field",
        "integer_is_not_integral_float",
        "nested_bool_is_not_int",
        "version_as_string",
        "version_as_bool",
        "version_as_integral_float",
        "declared_version_as_string",
    }
    assert all(case.get("added_in") == "v1.1" for case in doc["cases"] if case["id"] in wrong)
