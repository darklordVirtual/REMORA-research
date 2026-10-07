# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Report-specific binding for Federation results (AC-RS-01 to AC-RS-14).

The same claim id evaluated on two reports of one operation can give two
different native results. Rul1an raised this on
aeoess/agent-governance-vocabulary#177 (issuecomment-6047105582) with the
public synthetic fixtures LATE and LATE-CONFLICT. The cases below reproduce
only their semantics, locally and synthetically, with no material copied:

- LATE: the first report comes before any result was delivered (CONTRADICTED),
  the second after (ESTABLISHED);
- LATE-CONFLICT: the first report sees the delivered result (ESTABLISHED), the
  second comes after a conflicting final result was delivered (CONTRADICTED).

A result that does not name its report cannot tell these apart, and every
shortcut (first, last, any established) gets at least one of them wrong.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from remora.crypto import SignatureDomain, SigningKey  # noqa: E402
from remora.federation import (  # noqa: E402
    NativeResult,
    ProjectionMap,
    Report,
    SelectionProfile,
    SelectionRefused,
    SubjectRef,
    TransportCapabilities,
    select_report,
)
from remora.federation.evidence import projection_record, read_projection_record  # noqa: E402
from remora.federation.results import federate_result, verify_result  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KEY = SigningKey.from_text("e5" * 32, [SignatureDomain.FEDERATION_RESULT])
OTHER = SigningKey.from_text("f6" * 32, [SignatureDomain.FEDERATION_RESULT])
CLAIM = "definite_support"

# -- a minimal native model ----------------------------------------------------------------
# An operation's provider deliveries, and client reports made at given instants. The native
# verifier answers definite_support for one report: was the result the report relies on
# delivered by the time of that report, and is it still the latest delivered result?

CASES = {
    "LATE": {"deliveries": [{"at": 2, "result": "succeeded"}],
             "reports": [{"report_id": "report-1", "at": 1}, {"report_id": "report-2", "at": 3}],
             "expected": {"report-1": "CONTRADICTED", "report-2": "ESTABLISHED"}},
    "LATE-CONFLICT": {"deliveries": [{"at": 1, "result": "succeeded"},
                                     {"at": 3, "result": "failed"}],
                      "reports": [{"report_id": "report-1", "at": 2},
                                  {"report_id": "report-2", "at": 4}],
                      "expected": {"report-1": "ESTABLISHED", "report-2": "CONTRADICTED"}},
}


def _reports(case: str) -> list[Report]:
    return [Report(operation_id=f"op-{case}", report_id=r["report_id"], sequence=i + 1,
                   body={"reported_at": r["at"], "relies_on": "succeeded"})
            for i, r in enumerate(CASES[case]["reports"])]


def _native(case: str):
    deliveries = CASES[case]["deliveries"]

    def evaluate(report: Report) -> NativeResult:
        seen = [d for d in deliveries if d["at"] <= report.body["reported_at"]]
        if not seen:
            return NativeResult("CONTRADICTED", "result_not_delivered_at_report_time")
        latest = max(seen, key=lambda d: d["at"])
        if latest["result"] != report.body["relies_on"]:
            return NativeResult("CONTRADICTED", "conflicting_result_delivered")
        return NativeResult("ESTABLISHED", "required_result_delivered")
    return evaluate


def _caps() -> TransportCapabilities:
    return TransportCapabilities.from_dict({
        "schema_version": "remora-federation-transport-capabilities-v1",
        "transport": "synthetic/v1", "capabilities": {"result_binding": True}})


def _map() -> ProjectionMap:
    return ProjectionMap.from_dict({
        "schema_version": "remora-federation-projection-map-v1",
        "projection_map_id": "synthetic", "transport": "synthetic/v1",
        "native_claims": {CLAIM: {"version": "1", "dimensions": {"native_result": ["result_binding"]},
                                  "preserved_claim": "remora.definite_support"}}})


def _record(**kwargs):
    return projection_record(transport="synthetic/v1", adapter_digest="sha256:" + "0" * 64,
                             projection_map_digest=_map().digest, capabilities_digest=_caps().digest,
                             remora_revision="test", transport_revision="test", **kwargs)


def _federate(case: str, **selector):
    projection = _map().project(CLAIM, _caps()).to_dict()
    return federate_result(native_claim=CLAIM, reports=_reports(case), evaluate=_native(case),
                           key=KEY, projection=projection, record=_record, **selector)


# -- AC-RS-01, 02, 09, 10 -------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(CASES))
def test_two_reports_of_one_operation_keep_their_own_native_results(case) -> None:
    for report in _reports(case):
        record, evidence = _federate(case, report_id=report.report_id)
        assert record["subject"] == report.subject().to_dict()
        assert record["evidence_selection"]["selection_rule"] == "explicit_report_id"
        assert record["evidence_selection"]["selected_digest"] == report.digest
        expected = CASES[case]["expected"][report.report_id]
        assert record["native_result"]["status"] == expected
        # Projection strength is a separate dimension: a negative native finding is
        # faithfully PRESERVED.
        assert record["projection"] == "PRESERVED"
        checked = verify_result(evidence, [KEY.verification_key()], native_claim=CLAIM,
                                subject=report.subject(), report=report)
        assert checked.bound and checked.native_result["status"] == expected


def test_the_two_reports_have_distinct_subject_bindings() -> None:
    first, second = _reports("LATE")
    assert first.subject() != second.subject()
    assert first.digest != second.digest


def test_the_native_reason_survives_beside_the_projection() -> None:
    record, _ = _federate("LATE", report_id="report-1")
    assert record["native_result"] == {"status": "CONTRADICTED",
                                       "reason_code": "result_not_delivered_at_report_time",
                                       "vocabulary": "remora-claim-result-v1"}
    assert record["projection"] in ("PRESERVED", "NARROWED", "NOT_ESTABLISHED", "UNSUPPORTED")
    assert "status" not in record["projection"]


def test_a_projection_strength_is_never_a_native_status() -> None:
    with pytest.raises(ValueError):
        NativeResult("PRESERVED", "x")
    with pytest.raises(ValueError):
        NativeResult("ESTABLISHED", "Free text reason with spaces")


# -- AC-RS-06, 07, 08: every shortcut fails at least one expectation ------------------------

def _shortcut(name: str, reports: list[Report], evaluate) -> str:
    results = [evaluate(r).status for r in reports]
    if name == "always-first":
        return results[0]
    if name == "always-last":
        return results[-1]
    return "ESTABLISHED" if "ESTABLISHED" in results else results[0]  # any-established


@pytest.mark.parametrize("shortcut", ["always-first", "always-last", "any-established"])
def test_each_shortcut_gets_at_least_one_expectation_wrong(shortcut) -> None:
    wrong = []
    for case in CASES:
        reports, evaluate = _reports(case), _native(case)
        answer = _shortcut(shortcut, reports, evaluate)  # one answer for the operation
        for report in reports:
            if answer != CASES[case]["expected"][report.report_id]:
                wrong.append((case, report.report_id))
    assert wrong, f"{shortcut} matched every expectation"


def test_report_specific_selection_gets_all_four_right() -> None:
    for case in CASES:
        for report in _reports(case):
            record, _ = _federate(case, report_digest=report.digest)
            assert record["native_result"]["status"] == CASES[case]["expected"][report.report_id]


# -- AC-RS-05: ambiguity fails closed ----------------------------------------------------------

def test_several_eligible_reports_and_no_selector_produce_no_result() -> None:
    with pytest.raises(SelectionRefused) as refused:
        _federate("LATE")
    assert refused.value.reason == "report_selection_ambiguous"


@pytest.mark.parametrize("kwargs, reason", [
    ({"report_id": "report-9"}, "selected_report_absent"),
    ({"report_digest": "sha256:" + "0" * 64}, "selected_report_absent"),
    ({"report_id": "report-1", "report_digest": "sha256:" + "0" * 64}, "selector_overdetermined"),
])
def test_a_selector_that_does_not_name_one_report_refuses(kwargs, reason) -> None:
    with pytest.raises(SelectionRefused) as refused:
        select_report(_reports("LATE"), **kwargs)
    assert refused.value.reason == reason


def test_one_report_id_naming_two_reports_refuses() -> None:
    first, _ = _reports("LATE")
    twin = Report(operation_id=first.operation_id, report_id=first.report_id, sequence=9,
                  body={"reported_at": 7, "relies_on": "succeeded"})
    with pytest.raises(SelectionRefused) as refused:
        select_report([first, twin], report_id=first.report_id)
    assert refused.value.reason == "report_id_not_unique"


def test_reports_for_two_operations_are_not_a_selection() -> None:
    with pytest.raises(SelectionRefused) as refused:
        select_report([_reports("LATE")[0], _reports("LATE-CONFLICT")[0]], report_id="report-1")
    assert refused.value.reason == "reports_for_different_operations"


def test_a_declared_profile_is_a_named_rule_not_an_implicit_one() -> None:
    latest = SelectionProfile("latest-sequence-v1", lambda rs: max(rs, key=lambda r: r.sequence))
    report, selection = select_report(_reports("LATE"), profile=latest)
    assert report.report_id == "report-2"
    assert selection.to_dict()["profile_id"] == "latest-sequence-v1"
    assert selection.selection_rule == "declared_profile"


def test_a_single_report_needs_no_selector() -> None:
    report, selection = select_report(_reports("LATE")[:1])
    assert selection.selection_rule == "single_available" and selection.eligible == 1


# -- AC-RS-03, 04: relabelling breaks the binding ---------------------------------------------

def _signed(case="LATE", report_id="report-2"):
    record, evidence = _federate(case, report_id=report_id)
    report = next(r for r in _reports(case) if r.report_id == report_id)
    return report, evidence


def _resigned_payload(evidence: bytes, change) -> bytes:
    outer = json.loads(evidence)
    document = json.loads(base64.b64decode(outer["result_b64"]))
    change(document)
    outer["result_b64"] = base64.b64encode(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).decode()
    return json.dumps(outer).encode()


@pytest.mark.parametrize("field, value", [
    ("operation_id", "op-other"), ("report_id", "report-1"),
    ("report_digest", "sha256:" + "1" * 64), ("sequence", 1),
])
def test_editing_the_signed_subject_breaks_the_signature(field, value) -> None:
    report, evidence = _signed()
    tampered = _resigned_payload(evidence, lambda d: d["subject"].__setitem__(field, value))
    checked = verify_result(tampered, [KEY.verification_key()], native_claim=CLAIM,
                            subject=report.subject())
    assert checked.binding == "NOT_ESTABLISHED" and checked.reason == "signature_invalid"
    assert checked.native_result is None


def test_an_established_result_for_one_report_does_not_verify_for_another() -> None:
    _, evidence = _signed(report_id="report-2")
    other = _reports("LATE")[0]
    checked = verify_result(evidence, [KEY.verification_key()], native_claim=CLAIM,
                            subject=other.subject())
    assert (checked.binding, checked.reason) == ("NOT_ESTABLISHED", "subject_differs")


@pytest.mark.parametrize("change, reason", [
    (lambda r: Report(r.operation_id, "report-2b", r.body, r.sequence), "report_differs_from_subject"),
    (lambda r: Report(r.operation_id, r.report_id, {**r.body, "reported_at": 99}, r.sequence),
     "report_differs_from_subject"),
    (lambda r: Report(r.operation_id, r.report_id, r.body, 7), "report_differs_from_subject"),
])
def test_report_bytes_that_do_not_hash_to_the_signed_digest_refuse(change, reason) -> None:
    report, evidence = _signed()
    checked = verify_result(evidence, [KEY.verification_key()], native_claim=CLAIM,
                            subject=report.subject(), report=change(report))
    assert (checked.binding, checked.reason) == ("NOT_ESTABLISHED", reason)


def test_another_claim_or_an_untrusted_key_is_not_established() -> None:
    report, evidence = _signed()
    assert verify_result(evidence, [KEY.verification_key()], native_claim="other_claim",
                         subject=report.subject()).reason == "claim_differs"
    assert verify_result(evidence, [OTHER.verification_key()], native_claim=CLAIM,
                         subject=report.subject()).reason == "unknown_kid"


def test_a_report_subject_must_be_integrity_bound() -> None:
    with pytest.raises(ValueError):
        SubjectRef(kind="operation_report", operation_id="op", report_id="r")  # no digest


# -- AC-RS-13: legacy v1 records ------------------------------------------------------------------

def test_a_legacy_v1_record_is_readable_and_never_upgraded() -> None:
    fixtures = json.loads((ROOT / "artifacts/interop/federation-port-v0/fixtures.json")
                          .read_text(encoding="utf-8"))
    record = dict(fixtures["cases"][0]["projection_records"][0])
    legacy = {k: v for k, v in record.items()
              if k not in ("subject", "evidence_selection", "native_result")}
    legacy["schema_version"] = "remora-federation-projection-v1"
    read = read_projection_record(legacy)
    assert read["subject"] is None and read["native_result"] is None
    assert read["report_specific_binding"] == "NOT_ESTABLISHED"
    assert read["report_specific_binding_reason"] == "legacy_v1_record_has_no_subject"


def test_a_v2_record_alone_does_not_establish_its_report_binding() -> None:
    record, _ = _federate("LATE", report_id="report-1")
    read = read_projection_record(record)
    assert read["report_specific_binding"] == "NOT_ESTABLISHED"
    assert read["report_specific_binding_reason"] == "declared_requires_signed_result_verification"
    with pytest.raises(ValueError):
        read_projection_record({**record, "schema_version": "remora-federation-projection-v9"})


def test_v2_records_validate_against_the_published_schema() -> None:
    import jsonschema

    schema = json.loads((ROOT / "schemas/remora-federation-projection-v2.json")
                        .read_text(encoding="utf-8"))
    for case in CASES:
        for report in _reports(case):
            jsonschema.validate(_federate(case, report_id=report.report_id)[0], schema)


# -- section 12: post-dispatch observations stay independently attributable ------------------------

def test_attempt_and_effect_observations_of_one_operation_are_separate_subjects() -> None:
    attempt = Report("op-refund", "attempt-1", {"outcome": "provider_confirmed", "at": 1}, 1,
                     kind="execution_attempt")
    unknown = Report("op-refund", "effect-1", {"observed": None, "at": 2}, 2,
                     kind="effect_observation")
    verified = Report("op-refund", "effect-2", {"observed": {"status": "refunded"}, "at": 3}, 3,
                      kind="effect_observation")
    verdicts = {
        "attempt-1": NativeResult("provider_confirmed", "provider_response_received",
                                  vocabulary="federation-port-v0-outcome"),
        "effect-1": NativeResult("EFFECT_UNOBSERVABLE", "postcondition_read_timeout",
                                 vocabulary="remora-effect-status-v1"),
        "effect-2": NativeResult("EFFECT_VERIFIED", "postcondition_verified",
                                 vocabulary="remora-effect-status-v1"),
    }
    projection = _map().project(CLAIM, _caps()).to_dict()
    reports = [attempt, unknown, verified]
    subjects, statuses = set(), []
    for report in reports:
        record, evidence = federate_result(
            native_claim="effect_observation", reports=reports,
            evaluate=lambda r: verdicts[r.report_id], key=KEY, projection=projection,
            record=_record, report_id=report.report_id)
        subjects.add(json.dumps(record["subject"], sort_keys=True))
        statuses.append(record["native_result"]["status"])
        assert verify_result(evidence, [KEY.verification_key()], native_claim="effect_observation",
                             subject=report.subject(), report=report).bound
    assert len(subjects) == 3
    assert statuses == ["provider_confirmed", "EFFECT_UNOBSERVABLE", "EFFECT_VERIFIED"]
