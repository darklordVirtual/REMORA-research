# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The three execution-boundary interop fixtures describe REMORA.

For each of ``exact-call-binding-v1``, ``fresh-authority-v1`` and
``effect-evidence-v1``, and the v1.1 successors of the first and third: the manifest pins the committed bytes; the
zero-dependency reference verifier reproduces every expected outcome; and,
separately, REMORA's real primitives reproduce every expected outcome through
``remora.interop.boundary_fixtures``. The two agree case by case. Negative
controls make sure the agreement is not vacuous: a fixture edited to expect
the wrong thing is CONTRADICTED by REMORA, and a refusal reason REMORA has no
class for surfaces as a mismatch rather than being absorbed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from remora.interop import boundary_fixtures as bf

ROOT = Path(__file__).resolve().parents[1]
INTEROP = ROOT / "artifacts" / "interop"
PACKAGES = ("exact-call-binding-v1", "fresh-authority-v1", "effect-evidence-v1",
            "exact-call-binding-v1.1", "effect-evidence-v1.1")


@pytest.fixture(autouse=True)
def _signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "boundary-fixture-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")


def _fixtures(package: str) -> dict[str, Any]:
    return json.loads((INTEROP / package / "fixtures.json").read_text(encoding="utf-8"))


def _reference_run(package: str) -> dict[str, Any]:
    out = subprocess.run([sys.executable, str(INTEROP / package / "reference_verifier.py")], cwd=ROOT,
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr or out.stdout
    return json.loads(out.stdout)


@pytest.mark.parametrize("package", PACKAGES)
def test_manifest_pins_committed_bytes(package: str) -> None:
    manifest = json.loads((INTEROP / package / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["package_files"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"], entry["path"]


@pytest.mark.parametrize("package", PACKAGES)
def test_reference_verifier_reproduces_every_expected_outcome(package: str) -> None:
    payload = _reference_run(package)
    assert payload["failures"] == []
    assert len(payload["results"]) == len(_fixtures(package)["cases"])


@pytest.mark.parametrize("package", PACKAGES)
def test_remora_primitives_reproduce_every_expected_outcome(package: str) -> None:
    records = bf.evaluate_package(_fixtures(package))
    contradicted = [(r["case_id"], r["expected"], r["observed"]) for r in records if r["result"] == "CONTRADICTED"]
    assert contradicted == []
    # Every case reports the claim result the fixture declares, including the
    # NOT_ESTABLISHED ceiling on the unverifiable-authorization cases.
    fixtures = _fixtures(package)
    assert [r["result"] for r in records] == [c["expected"]["claim_result"] for c in fixtures["cases"]]
    assert {r["claim_id"] for r in records} == set(fixtures["claims"])


@pytest.mark.parametrize("package", PACKAGES)
def test_reference_verifier_and_remora_agree_case_by_case(package: str) -> None:
    reference = {r["id"]: r["actual"] for r in _reference_run(package)["results"]}
    remora = {r["case_id"]: r["observed"]["value"] for r in bf.evaluate_package(_fixtures(package))}
    assert reference == remora


def test_every_fixture_case_carries_a_ceiling_on_its_result() -> None:
    for package in PACKAGES:
        fixtures = _fixtures(package)
        assert fixtures["result_vocabulary"] == ["ESTABLISHED", "CONTRADICTED", "NOT_ESTABLISHED"]
        assert fixtures["claim_ceiling"].startswith("ESTABLISHED means only that")
        assert "does not establish" in fixtures["claim_ceiling"]
        for case in fixtures["cases"]:
            assert case["expected"]["claim_result"] in fixtures["result_vocabulary"], case["id"]
            assert case["claim_id"] in fixtures["claims"], case["id"]


# ── Negative controls: the agreement is not vacuous ────────────────────────


def test_a_fixture_that_expects_dispatch_of_a_mutated_call_is_contradicted() -> None:
    fixtures = copy.deepcopy(_fixtures("exact-call-binding-v1"))
    (case,) = [c for c in fixtures["cases"] if c["id"] == "argument_value_changed"]
    case["expected"]["outcomes"] = [{"outcome": "DISPATCHED", "refusal_class": None}]
    (record,) = [r for r in bf.evaluate_package(fixtures) if r["case_id"] == "argument_value_changed"]
    assert record["result"] == "CONTRADICTED"
    assert record["observed"]["value"] == [{"outcome": "REFUSED", "refusal_class": "call_mismatch"}]


def test_a_fixture_that_expects_a_stale_lease_to_dispatch_is_contradicted() -> None:
    fixtures = copy.deepcopy(_fixtures("fresh-authority-v1"))
    (case,) = [c for c in fixtures["cases"] if c["id"] == "toolspec_changed"]
    case["expected"]["outcomes"] = [{"outcome": "DISPATCHED", "refusal_class": None}]
    (record,) = [r for r in bf.evaluate_package(fixtures) if r["case_id"] == "toolspec_changed"]
    assert record["result"] == "CONTRADICTED"


def test_a_fixture_that_promotes_an_unobservable_effect_is_contradicted() -> None:
    fixtures = copy.deepcopy(_fixtures("effect-evidence-v1"))
    (case,) = [c for c in fixtures["cases"] if c["id"] == "reader_returns_nothing"]
    case["expected"]["highest_established_state"] = "EFFECT_VERIFIED"
    (record,) = [r for r in bf.evaluate_package(fixtures) if r["case_id"] == "reader_returns_nothing"]
    assert record["result"] == "CONTRADICTED"
    assert record["observed"]["value"]["effect_status"] == "EFFECT_UNOBSERVABLE"


def test_unmapped_refusal_reasons_surface_rather_than_being_absorbed() -> None:
    assert bf._refusal_class("some_new_refusal") == "unmapped:some_new_refusal"
    assert bf._refusal_class("token_verification_failed:kid_revoked") == "authority_revoked"
    assert bf._refusal_class("decision_escalate_not_accept") == "decision_not_accept"
    for reason, cls in bf.REFUSAL_CLASS_BY_REASON.items():
        assert bf._refusal_class(reason) == cls


def test_an_unsigned_process_cannot_report_a_binding_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a signing key REMORA issues unsigned leases; every case would
    refuse as unverifiable and a careless evaluator would report that as a
    finding. The evaluator refuses to run instead."""
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
    fixtures = _fixtures("exact-call-binding-v1")
    (case,) = [c for c in fixtures["cases"] if c["id"] == "same_call_dispatches"]
    with pytest.raises(bf.FixtureEnvironmentError):
        bf.evaluate_exact_call_binding(case)


# ── v1.1 successors ────────────────────────────────────────────────────────


def test_v1_1_packages_carry_every_v1_case_unchanged() -> None:
    for package in ("exact-call-binding", "effect-evidence"):
        v1 = _fixtures(f"{package}-v1")["cases"]
        v11 = _fixtures(f"{package}-v1.1")["cases"]
        assert v11[: len(v1)] == v1
        assert all(case.get("added_in") == "v1.1" for case in v11[len(v1):])


def test_a_fixture_that_expects_an_integral_float_to_dispatch_is_contradicted() -> None:
    fixtures = copy.deepcopy(_fixtures("exact-call-binding-v1.1"))
    (case,) = [c for c in fixtures["cases"] if c["id"] == "argument_integer_became_integral_float"]
    case["expected"]["outcomes"] = [{"outcome": "DISPATCHED", "refusal_class": None}]
    (record,) = [r for r in bf.evaluate_package(fixtures) if r["case_id"] == case["id"]]
    assert record["result"] == "CONTRADICTED"
    assert record["observed"]["value"] == [{"outcome": "REFUSED", "refusal_class": "call_mismatch"}]


def test_a_fixture_that_verifies_a_missing_field_as_null_is_contradicted() -> None:
    fixtures = copy.deepcopy(_fixtures("effect-evidence-v1.1"))
    (case,) = [c for c in fixtures["cases"] if c["id"] == "exact_null_field_missing"]
    case["expected"]["effect_status"] = "EFFECT_VERIFIED"
    case["expected"]["highest_established_state"] = "EFFECT_VERIFIED"
    (record,) = [r for r in bf.evaluate_package(fixtures) if r["case_id"] == case["id"]]
    assert record["result"] == "CONTRADICTED"
    assert record["observed"]["value"]["effect_status"] == "EFFECT_MISMATCH"


def test_contract_rejected_maps_only_the_rule_map_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """CONTRACT_REJECTED is the fixture name for validate_comparison_rules
    refusing; any other ValueError is a failure of the run, not an outcome."""
    (case,) = [c for c in _fixtures("effect-evidence-v1.1")["cases"] if c["id"] == "unknown_comparison_rule"]
    assert bf.evaluate_effect_evidence_v1_1(case) == {
        "effect_status": "CONTRACT_REJECTED", "highest_established_state": "EXECUTION_REPORTED_SUCCESS"}

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("something_else")

    monkeypatch.setattr(bf, "verify_declared_delta", _boom)
    (ok_case,) = [c for c in _fixtures("effect-evidence-v1.1")["cases"] if c["id"] == "verified_declared_delta"]
    with pytest.raises(ValueError, match="something_else"):
        bf.evaluate_effect_evidence_v1_1(ok_case)
