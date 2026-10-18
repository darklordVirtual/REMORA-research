# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What effect-evidence-v1 cannot tell apart (invocation axes, issue #918).

Probity's invocation_axes corpus handed 22 execution bundles to the frozen v1
reference verifier. On three it returned EFFECT_VERIFIED where Probity's reader
did not, and each turns on a fact the v1 input has no field for: the call a
bundle is bound to, who observed, and the decision captured for the request.

These tests pin that limit rather than repair it. Bundles that differ only in
one of those facts project to identical v1 input and get identical verdicts,
so a v1 EFFECT_VERIFIED cannot be read as a claim about any of them. The
projection is the one the reproduction job uses (observation.fields becomes
observed; everything else outside the v1 input is dropped). The verifier is
the frozen file, checked against its manifest pin first.

The last section runs the same variants through effect-evidence-v2, which
carries the three facts: each changes the v2 verdict while the v1 verdict
stays EFFECT_VERIFIED. v1 keeps its bytes; the limit stays a property of v1.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "artifacts" / "interop" / "effect-evidence-v1"


@pytest.fixture(scope="module")
def frozen() -> Any:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    pins = {Path(f["path"]).name: f["sha256"] for f in manifest["package_files"]}
    source = PACKAGE / "reference_verifier.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == pins["reference_verifier.py"]
    spec = importlib.util.spec_from_file_location("effect_evidence_v1_reference", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: A bundle in the shape Probity's corpus uses, with the facts v1 cannot carry.
BUNDLE = {
    "call_binding": "sha256:" + "a" * 64,
    "dispatch": {"outcome": "DISPATCHED"},
    "execution_report": {"status": "success", "message": "ticket closed"},
    "postcondition": {"tool_id": "update_ticket", "expected_fields": {"status": "closed"}},
    "observation": {"source": "independent_reader", "fields": {"status": "closed"}},
}


def project(bundle: dict[str, Any]) -> dict[str, Any]:
    """The v1 input a bundle becomes: the reproduction job's mapping."""
    post = dict(bundle.get("postcondition") or {})
    post.setdefault("comparison_rules", {})
    obs = bundle.get("observation")
    return {
        "dispatch": bundle["dispatch"],
        "execution_report": bundle.get("execution_report"),
        "postcondition": post,
        "observed": None if obs is None else obs.get("fields"),
    }


def _variant(**changes: Any) -> dict[str, Any]:
    bundle = copy.deepcopy(BUNDLE)
    for path, value in changes.items():
        target = bundle
        *parents, leaf = path.split("__")
        for name in parents:
            target = target[name]
        target[leaf] = value
    return bundle


def test_the_base_bundle_is_verified(frozen):
    assert frozen.evaluate(project(BUNDLE))["highest_established_state"] == "EFFECT_VERIFIED"


@pytest.mark.parametrize("name, variant", [
    ("bundle_for_other_call", _variant(call_binding="sha256:" + "b" * 64)),
    ("observation_from_the_tool", _variant(observation__source="tool")),
])
def test_a_bundle_fact_v1_cannot_carry_does_not_change_the_verdict(frozen, name, variant):
    assert project(variant) == project(BUNDLE), name
    assert frozen.evaluate(project(variant)) == frozen.evaluate(project(BUNDLE))


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_a_captured_decision_does_not_change_the_verdict(frozen, decision):
    """dispatched_after_deny: the decision lives in the capture, not the bundle.
    The projection has no place for it, and a v1 input that carries it anyway
    is read without it, so a dispatch after a deny verifies like one after an
    allow."""
    v1_input = project(BUNDLE)
    assert set(v1_input) == {"dispatch", "execution_report", "postcondition", "observed"}
    carried = {**v1_input, "captured_decision": {"decision": decision}}
    assert frozen.evaluate(carried) == frozen.evaluate(v1_input)
    assert frozen.evaluate(carried)["highest_established_state"] == "EFFECT_VERIFIED"


def test_two_of_the_three_limits_are_stated_non_claims_and_one_is_not():
    """The decision limit is stated in docs/interop/FEDERATION.md, not in the
    frozen claim packet, whose bytes do not change."""
    packet = json.loads((PACKAGE / "claim-packet.json").read_text(encoding="utf-8"))
    non_claims = packet["explicit_non_claims"]
    assert "that the reader is independent of the tool that acted" in non_claims
    assert "that the observed object is the one the call targeted" in non_claims
    assert not any("decision" in n for n in non_claims)
    federation = (PACKAGE.parents[2] / "docs" / "interop" / "FEDERATION.md").read_text(
        encoding="utf-8")
    assert "dispatched_after_deny" in federation
    assert "decision correspondence" in federation.replace("\n", " ")


# ── effect-evidence-v2 carries the three facts ─────────────────────────────

V2_PACKAGE = PACKAGE.parent / "effect-evidence-v2"


@pytest.fixture(scope="module")
def v2() -> Any:
    manifest = json.loads((V2_PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    pins = {Path(f["path"]).name: f["sha256"] for f in manifest["package_files"]}
    source = V2_PACKAGE / "reference_verifier.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == pins["reference_verifier.py"]
    spec = importlib.util.spec_from_file_location("effect_evidence_v2_reference", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project_v2(bundle: dict[str, Any], decision: str = "allow") -> dict[str, Any]:
    """The v2 input a bundle becomes: the reproduction job's v2 mapping."""
    source = (bundle.get("observation") or {}).get("source")
    observer = ({"id": "independent-reader", "control_domain": "reader-domain", "read_only": True}
                if source == "independent_reader"
                else {"id": "tool", "control_domain": "executor-domain", "read_only": False})
    return {
        **project(bundle),
        "invocation": BUNDLE["call_binding"],
        "decision": {"call": BUNDLE["call_binding"],
                     "verdict": {"allow": "accept"}.get(decision, decision), "approved": False},
        "bundle_call": bundle["call_binding"],
        "executor": {"proposed_by": "agent", "executed_by": "tool", "control_domain": "executor-domain"},
        "observer": observer,
    }


def test_v2_verifies_the_base_bundle(v2):
    assert v2.evaluate(project_v2(BUNDLE))["highest_established_state"] == "EFFECT_VERIFIED"


@pytest.mark.parametrize("name, variant, decision, lineage", [
    ("bundle_for_other_call", _variant(call_binding="sha256:" + "b" * 64), "allow", "tool_call_hash_mismatch"),
    ("observation_from_the_tool", _variant(observation__source="tool"), "allow", "BOUND"),
    ("dispatched_after_deny", BUNDLE, "deny", "dispatched_after_deny"),
])
def test_v2_tells_apart_what_v1_cannot(v2, frozen, name, variant, decision, lineage):
    """Each fact v1 drops changes the v2 verdict, and none reaches
    EFFECT_VERIFIED, while the frozen v1 verdict stays the same."""
    assert frozen.evaluate(project(variant))["highest_established_state"] == "EFFECT_VERIFIED"
    verdict = v2.evaluate(project_v2(variant, decision))
    assert verdict["lineage_status"] == lineage, name
    assert verdict["highest_established_state"] != "EFFECT_VERIFIED", name
