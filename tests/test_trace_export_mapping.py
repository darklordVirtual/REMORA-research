# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA -> AgenTrust TRACE mapping (REMORA-SDD-TRACE-001, milestone M1).

The mapping is an ``external-evidence-source`` output, not a TRACE Trust
Record. These tests pin that position against the TRACE schema vendored at
the commit in ``integrations/agentrust-trace/upstream-lock.json``:

- every field the mapping emits validates against the pinned schema;
- the required fields it leaves out are exactly the ones named, each with a
  reason, and the full schema refuses the record on exactly those;
- no value REMORA holds but cannot justify (runtime identity hash, build
  digest, principal, data scope) leaks into a TRACE field;
- the native result is carried, never upgraded.

Expected outcomes are written out here by hand rather than read back from
the generated fixtures, so a generator and mapper that drift together still
fail.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
jsonschema = pytest.importorskip("jsonschema")

from remora.interop.jcs import canonicalise  # noqa: E402
from remora.interop.trace import TRACE_REQUIRED  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "integrations" / "agentrust-trace"
LOCK = json.loads((PKG / "upstream-lock.json").read_text(encoding="utf-8"))
SCHEMA_PATH = PKG / LOCK["trace_spec"]["vendored_as"]
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

_spec = importlib.util.spec_from_file_location("trace_fixture_generate",
                                               PKG / "fixtures" / "generate.py")
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)
CASES = gen.build_cases()

ABSENT_WITH_CONTEXT = {"subject", "runtime", "policy", "data_class", "build_provenance", "cnf"}
ABSENT_WITHOUT_CONTEXT = ABSENT_WITH_CONTEXT | {"model"}

EXPECTED = {
    "01-established-with-context": ("ESTABLISHED", ABSENT_WITH_CONTEXT, True),
    "02-contradicted-preserved": ("CONTRADICTED", ABSENT_WITH_CONTEXT, True),
    "03-no-context-no-resolver": ("ESTABLISHED", ABSENT_WITHOUT_CONTEXT, False),
    "04-wrong-tenant": ("BINDING_MISMATCH", "tenant_differs"),
    "05-wrong-principal": ("BINDING_MISMATCH", "principal_differs"),
    "06-context-replaced": ("BINDING_MISMATCH", "execution_context_digest_differs"),
    "07-context-not-bound": ("BINDING_MISMATCH", "execution_context_not_bound_to_report"),
    "08-untrusted-signer": ("NATIVE_EVIDENCE_INVALID", "unknown_kid"),
    "09-result-rebound-to-other-report": ("NATIVE_EVIDENCE_INVALID", "subject_differs"),
    "10-tampered-envelope": ("NATIVE_EVIDENCE_INVALID", "signature_invalid"),
    "11-subject-not-report-specific": ("AMBIGUOUS_SUBJECT", "subject_not_report_specific"),
    "12-report-not-held": ("AMBIGUOUS_SUBJECT", "selected_report_absent"),
}


def _mapping(name: str) -> dict:
    return CASES[name]["expected"]["mapping"]


def _validator(required: set[str]):
    schema = copy.deepcopy(SCHEMA)
    schema["required"] = sorted(required)
    return jsonschema.Draft202012Validator(schema,
                                           format_checker=jsonschema.FormatChecker())


# -- upstream pin -----------------------------------------------------------------------------

def test_vendored_schema_matches_the_lock():
    digest = "sha256:" + hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    assert digest == LOCK["trace_spec"]["schema_sha256"]
    assert tuple(SCHEMA["required"]) == TRACE_REQUIRED
    assert SCHEMA["properties"]["eat_profile"]["const"] == LOCK["trace_spec"]["eat_profile"]


# -- the fixtures -----------------------------------------------------------------------------

def test_every_case_has_a_hand_written_expectation():
    assert set(CASES) == set(EXPECTED)


def test_committed_fixtures_match_the_generator():
    assert gen.main(["--check"]) == 0


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_case_outcome(name):
    outcome = CASES[name]["expected"]
    expected = EXPECTED[name]
    if isinstance(expected[1], str):
        assert outcome == {"refused": {"code": expected[0], "reason": expected[1]}}
        return
    status, absent, referenced = expected
    mapping = outcome["mapping"]
    assert mapping["remora"]["native_result"]["status"] == status
    assert set(mapping["absent_required"]) == absent
    assert all(mapping["absent_required"].values())
    assert ("references" in mapping["trace"]) is referenced
    assert mapping["remora"]["reference_emitted"] is referenced


# -- schema position --------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(n for n, e in EXPECTED.items() if not isinstance(e[1], str)))
def test_emitted_fields_validate_and_absent_fields_are_exactly_the_failures(name):
    mapping = _mapping(name)
    trace = mapping["trace"]
    absent = set(mapping["absent_required"])
    assert not absent & set(trace)
    assert set(TRACE_REQUIRED) - set(trace) == absent

    # Every emitted field is valid TRACE v0.2 at the pinned commit.
    errors = list(_validator(set(TRACE_REQUIRED) - absent).iter_errors(trace))
    assert errors == []

    # Under the full schema the record is refused, and only for the absent fields.
    missing = set()
    for error in _validator(set(TRACE_REQUIRED)).iter_errors(trace):
        assert error.validator == "required", error.message
        missing |= {f for f in absent if f"'{f}'" in error.message}
    assert missing == absent


def test_the_mapping_never_says_it_is_a_trust_record():
    for name in ("01-established-with-context", "03-no-context-no-resolver"):
        mapping = _mapping(name)
        assert mapping["is_trust_record"] is False
        assert mapping["trace_conformance_level"] is None
        assert mapping["trace_role"] == "external-evidence-source"
        assert "signature" not in mapping["trace"]
        assert "not_a_trace_trust_record" in mapping["remora"]["non_claims"]
        assert "independent_verification_not_established" in mapping["remora"]["non_claims"]


# -- no promotion ------------------------------------------------------------------------------

def test_native_negative_result_is_carried_verbatim():
    native = _mapping("02-contradicted-preserved")["remora"]["native_result"]
    assert native == {"status": "CONTRADICTED", "reason_code": "arguments_differ_from_lease",
                      "vocabulary": "remora-claim-result-v1"}


def test_appraisal_is_none_and_origin_is_not_self():
    trace = _mapping("01-established-with-context")["trace"]
    assert trace["appraisal"]["status"] == "none"
    assert trace["origin"]["kind"] == "third-party-control-plane"
    assert "runtime" not in trace  # no software-only record with an invented measurement


def test_values_remora_holds_but_cannot_justify_stay_out_of_trace_fields():
    mapping = _mapping("01-established-with-context")
    blob = json.dumps(mapping["trace"])
    unmapped = mapping["remora"]["available_unmapped"]
    for name in ("runtime_identity_hash", "build_provenance_digest"):
        value = unmapped[name]["value"]
        assert value.removeprefix("sha256:") not in blob, name
        assert unmapped[name]["why_not_mapped"]
    # The principal is the actor of the action, not the TRACE workload subject.
    principal = mapping["remora"]["execution_context"]["principal_id"]
    assert principal.startswith("spiffe://")
    assert principal not in blob
    assert "internal" not in blob  # the data scope classification is not a data_class


def test_model_comes_only_from_a_bound_context():
    assert _mapping("01-established-with-context")["trace"]["model"] == {
        "provider": "example-provider", "model_id": "example-model-1"}
    assert "model" not in _mapping("03-no-context-no-resolver")["trace"]


def test_reference_is_a_digest_pinned_pointer_to_the_signed_result():
    case = CASES["01-established-with-context"]
    evidence = base64.b64decode(case["input"]["evidence_b64"])
    digest = "sha256:" + hashlib.sha256(evidence).hexdigest()
    (reference,) = case["expected"]["mapping"]["trace"]["references"]
    assert reference == {"rel": "remora-native-claim-result", "id": digest,
                         "resolver": "deploy.example.test", "digest": digest,
                         "retention": "P1Y"}


def test_trace_digest_is_over_jcs_of_the_trace_object():
    mapping = _mapping("01-established-with-context")
    expected = "sha256:" + hashlib.sha256(canonicalise(mapping["trace"])).hexdigest()
    assert mapping["trace_digest"] == expected


def test_mapping_is_deterministic():
    again = gen.build_cases()
    for name in EXPECTED:
        assert again[name]["expected"] == CASES[name]["expected"]


# -- request validation -----------------------------------------------------------------------

def _with_request(**changes) -> dict:
    case_input = copy.deepcopy(CASES["01-established-with-context"]["input"])
    case_input["request"].update(changes)
    return gen.evaluate(case_input)


@pytest.mark.parametrize("changes, reason", [
    ({"issued_at": 1}, "issued_at_out_of_range"),
    ({"issued_at": True}, "issued_at_out_of_range"),
    ({"ingested_at": gen.ISSUED_AT + 1}, "ingested_after_issued"),
    ({"producer": " "}, "producer_empty"),
    ({"resolver": ""}, "resolver_empty"),
    ({"resolver": None}, "retention_without_resolver"),
    ({"retention": "one year"}, "retention_not_iso8601_duration"),
])
def test_invalid_requests_are_refused(changes, reason):
    assert _with_request(**changes) == {"refused": {"code": "INVALID_INPUT", "reason": reason}}


def test_a_different_claim_id_does_not_reuse_the_signed_result():
    assert _with_request(native_claim="remora.fresh_authority") == {
        "refused": {"code": "NATIVE_EVIDENCE_INVALID", "reason": "claim_differs"}}


def test_a_noncanonical_context_is_refused():
    case_input = copy.deepcopy(CASES["01-established-with-context"]["input"])
    case_input["execution_context"] = json.dumps(json.loads(case_input["execution_context"]),
                                                 indent=1)
    assert gen.evaluate(case_input) == {"refused": {
        "code": "INVALID_INPUT", "reason": "execution_context_history_noncanonical"}}


def test_a_refusal_code_outside_the_declared_vocabulary_is_a_programming_error() -> None:
    from remora.interop.trace.mapping import REFUSAL_CODES, TraceExportRefused

    for code in REFUSAL_CODES:
        assert TraceExportRefused(code, "reason").code == code
    with pytest.raises(ValueError, match="unknown TRACE refusal code"):
        TraceExportRefused("INVALID_IMPUT", "typo")
