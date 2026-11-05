# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Kill tests for the cumulative-limit survivors of the 2026-11-04 mutation sweep.

``remora/enforcement/cumulative_limits.py`` joined ``[tool.mutmut] only_mutate``
on 2026-10-24 without its tests: ``tests/limits/`` was never in the sweep's
selection, and the selection guard scanned only the top level of ``tests/``.
The first sweep that ran the limits suites reported survivors in the paths the
OT pilot relies on: the after-the-fact accounting of movement the controller
reports, the reviewer's resolution of an unknown outcome, and the dispatcher's
operational record when a reservation cannot be given back.

Each test here pins one of those as a contract, in the form the repository
already uses for the gate and the dispatcher (docs/assurance/mutation_testing_v1.md):
the whole value, the exact literal, and the governance event by name, level
and payload. Every kill was verified by running the test against the mutant
in the sandbox (``MUTANT_UNDER_TEST``).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from remora.enforcement import cumulative_limits as cl
from remora.enforcement.lease import GovernedToolDispatcher, ToolDidNotExecute
from tests.limits.test_limits_unit import (
    LIMITS,
    METERS as METERS_PLAIN,
    PREV_METERS,
    SEEN_LIMIT,
    T0,
    policy,
    prev_guard,
    reserve,
)

LOGGER = "remora.governance"


def _dispatcher(guard):
    d = GovernedToolDispatcher(expected_policy_bundle_hash="b" * 64)
    if guard is not None:
        d.bind_limit_guard(guard)
    return d


def _lease(nonce="n1"):
    return SimpleNamespace(tenant_id="t", actor_identity="p", nonce=nonce, expires_at=None,
                           tool_args_hash="h" * 64, proposal_id="prop")


def _events(caplog, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.name == LOGGER and r.getMessage().startswith(name + " ")]


def _payload(record: logging.LogRecord) -> dict:
    return record.remora  # type: ignore[attr-defined]


def _broken(*_a, **_k):
    raise OSError("disk gone")


# ── the dispatcher's operational record when a reservation stays held ─────────


def test_a_failed_release_is_recorded_as_exactly_this_event(tmp_path, caplog, monkeypatch):
    guard = prev_guard(tmp_path, {"AHU-1": 19.0})
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 19.5}
    assert d._limit_refusal(_lease("n1"), "move_seen", args, args, None) is None
    monkeypatch.setattr(guard, "release", _broken)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert d._limit_release(_lease("n1"), "move_seen") is None
    [record] = _events(caplog, "dispatch.limit_release_failed")
    assert record.levelno == logging.WARNING
    assert _payload(record) == {"tenant_id": "t", "tool_name": "move_seen",
                                "proposal_id": "prop", "error_type": "OSError"}
    # The reservation is kept, so the resource stays pending: the limit errs towards refusing.
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=21.5) == cl.RESOURCE_BUSY


def test_a_release_without_a_guard_is_a_no_op_not_an_error():
    d = _dispatcher(None)
    assert d._limit_release(_lease("n1"), "move_seen") is None
    assert d._limit_did_not_execute(_lease("n1"), "move_seen", "rail") == "none"


def test_a_failed_did_not_execute_holds_the_budget_and_records_the_same_event(
        tmp_path, caplog, monkeypatch):
    guard = prev_guard(tmp_path, {"AHU-1": 19.0})
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 19.5}
    assert d._limit_refusal(_lease("n1"), "move_seen", args, args, None) is None
    monkeypatch.setattr(guard, "did_not_execute", _broken)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert d._limit_did_not_execute(_lease("n1"), "move_seen", "rail") == "held"
    [record] = _events(caplog, "dispatch.limit_release_failed")
    assert record.levelno == logging.WARNING
    assert _payload(record) == {"tenant_id": "t", "tool_name": "move_seen",
                                "proposal_id": "prop", "error_type": "OSError"}


def test_a_failed_settle_is_recorded_as_exactly_this_event(tmp_path, caplog, monkeypatch):
    guard = prev_guard(tmp_path, {"AHU-1": 19.0})
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 19.5}
    assert d._limit_refusal(_lease("n1"), "move_seen", args, args, None) is None
    monkeypatch.setattr(guard, "settle", _broken)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        d._limit_settle(_lease("n1"), "move_seen", ok=True, result={"previous": 19.0})
    [record] = _events(caplog, "dispatch.limit_settle_failed")
    assert record.levelno == logging.ERROR
    assert _payload(record) == {"tenant_id": "t", "tool_name": "move_seen",
                                "proposal_id": "prop", "error_type": "OSError"}


def test_the_after_the_fact_and_not_reached_events_carry_the_plant_values(tmp_path, caplog):
    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 19.5}
    assert d._limit_refusal(_lease("n1"), "move_seen", args, args, None) is None
    plant["AHU-1"] = 19.4   # the plant stopped short, and reports it came from 17.0
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        d._limit_settle(_lease("n1"), "move_seen", ok=True, result={"previous": 17.0})
    [charged] = _events(caplog, "dispatch.limit_charged_after_the_fact")
    assert charged.levelno == logging.ERROR
    assert _payload(charged) == {"tenant_id": "t", "tool_name": "move_seen",
                                 "proposal_id": "prop", "quantity": "seen",
                                 "resource": "AHU-1", "actual_movement": 24,
                                 "charged_after": 19}
    [missed] = _events(caplog, "dispatch.limit_target_not_reached")
    assert missed.levelno == logging.WARNING
    assert _payload(missed) == {"tenant_id": "t", "tool_name": "move_seen",
                                "proposal_id": "prop", "quantity": "seen",
                                "resource": "AHU-1", "target": 195, "observed": 194}


# ── ToolDidNotExecute carries its evidence in its message ─────────────────────


def test_tool_did_not_execute_reads_as_source_and_detail():
    exc = ToolDidNotExecute("rail", "refused: insufficient funds")
    assert (exc.source, exc.detail) == ("rail", "refused: insufficient funds")
    assert str(exc) == "rail: refused: insufficient funds"


@pytest.mark.parametrize("source, detail", [("", "refused"), ("rail", ""), ("", "")])
def test_tool_did_not_execute_names_what_it_needs(source, detail):
    with pytest.raises(ValueError,
                       match="^ToolDidNotExecute needs the source and what it observed$"):
        raise ToolDidNotExecute(source, detail)  # the constructor refuses before anything is raised


# ── after-the-fact accounting: the controller's report, not the target ────────


def test_the_charge_after_the_fact_alone_can_exhaust_the_limit(tmp_path):
    """Limit 2.0 degC. Reserved 0.5; the controller reports it moved from 17.0,
    so 2.5 happened and 2.0 is charged after the fact. The next 0.1 must
    refuse because of that charge, and for no other reason."""
    plant = {"AHU-1": 19.0}
    limits = [*LIMITS, dict(SEEN_LIMIT, limit_id="seen hourly", max=30)]   # a space is legal
    guard = cl.LimitGuard(policy(meters=PREV_METERS, limits=limits),
                          cl.LimitLedger(tmp_path / "after.db"),
                          observer=lambda t, q, r: plant[r])
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None   # 5
    plant["AHU-1"] = 19.5
    [record] = guard.settle("1", ok=True, result={"previous": 17.0}, now=T0)
    assert (record["actual_movement"], record["charged_after"]) == (25, 20)
    assert [(k.split(cl._SEP)[0], a) for k, a in guard.ledger.charges("1#after")] == [
        ("seen hourly", 20)]
    # 5 reserved + 20 charged after = 25 of 30: 0.6 more (6) would be 31.
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=20.1) == cl.EXCEEDED
    # Without the after-the-fact charge, 5 + 6 = 11 of 30 would have run.
    assert reserve(guard, "move_seen", "3", unit="AHU-1", value=20.0) is None    # 5
    # An unknown outcome names its counter by the whole limit id.
    guard.settle("3", ok=False)
    assert guard.unresolved("t")[0]["charges"] == [{"counter": "seen hourly", "amount": 5}]


def test_movement_is_measured_to_where_the_plant_ended_not_the_target(tmp_path):
    """Target 19.5, plant read back at 19.4, controller reports 17.0: the
    movement that happened is 2.4, not the 2.5 the target would say."""
    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    plant["AHU-1"] = 19.4
    [record] = guard.settle("1", ok=True, result={"previous": 17.0}, now=T0)
    assert record["observed"] == 194 and record["target"] == 195
    assert (record["actual_movement"], record["charged_after"]) == (24, 19)


def test_a_record_without_a_controller_report_does_not_stop_the_accounting(tmp_path):
    """Two observed quantities in one write. The first has no previous_field,
    the second does: the second is still accounted."""
    plant = {"AHU-1": 19.0, "V-1": 40.0}
    meters = {"move_seen": [
        {"quantity": "seen", "kind": "change", "argument": "value", "scale": 10,
         "unit": "degC", "resource_argument": "unit", "observed": True},
        {"quantity": "travel", "kind": "change", "argument": "pct", "scale": 1,
         "unit": "pct", "resource_argument": "valve", "observed": True,
         "previous_field": "old_pct"},
    ]}
    limits = [*LIMITS, SEEN_LIMIT,
              {"limit_id": "travel", "tenant": "t", "quantity": "travel", "unit": "pct",
               "max": 60, "window_seconds": 3600, "principal": "*", "resource": "*"}]
    guard = cl.LimitGuard(policy(meters=meters, limits=limits, baselines=[]),
                          cl.LimitLedger(tmp_path / "two.db"),
                          observer=lambda t, q, r: plant[r])
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5, valve="V-1",
                   pct=45) is None
    plant.update({"AHU-1": 19.5, "V-1": 45.0})
    records = guard.settle("1", ok=True, result={"old_pct": 10}, now=T0)
    by_quantity = {r["quantity"]: r for r in records}
    assert "actual_movement" not in by_quantity["seen"]
    assert (by_quantity["travel"]["actual_movement"],
            by_quantity["travel"]["charged_after"]) == (35, 30)
    assert [(k.split(cl._SEP)[0], a) for k, a in guard.ledger.charges("1#after")] == [
        ("travel", 30)]


# ── the reviewer's resolution is the ledger's record ─────────────────────────


def _unknown_payment(tmp_path, checker):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "ledger.db"), evidence=checker)
    assert reserve(guard, "pay", "A", amount=7000, cur="JPY") is None
    guard.settle("A", ok=False)
    return guard


def test_a_resolution_as_executed_is_recorded_in_these_words(tmp_path):
    guard = _unknown_payment(tmp_path, lambda t, op, ref: {"executed": True})
    assert guard.resolve(tenant="t", operation_id="A", executed=True, resolved_by="reviewer-1",
                         reason="the rail settled it", evidence_ref="stmt-9") is None
    [row] = guard.unrecorded_resolutions("t")
    assert row["resolution"] == "executed (stmt-9 checked): the rail settled it"
    assert (row["resolved_by"], row["evidence_ref"], row["reason"], row["state"]) == (
        "reviewer-1", "stmt-9", "the rail settled it", "settled")


def test_a_resolution_without_evidence_or_reason_is_recorded_bare(tmp_path):
    asked = []

    def checker(tenant, operation, evidence_ref):
        asked.append(evidence_ref)
        return {"executed": False}

    guard = _unknown_payment(tmp_path, checker)
    assert guard.resolve(tenant="t", operation_id="A", executed=False,
                         resolved_by="reviewer-1") is None
    assert asked == [""]
    [row] = guard.unrecorded_resolutions("t")
    assert row["resolution"] == "not_executed"
    assert (row["evidence_ref"], row["reason"], row["state"]) == ("", "", "released")


def test_the_principal_cannot_resolve_and_the_source_is_not_even_asked(tmp_path):
    asked = []

    def checker(tenant, operation, evidence_ref):
        asked.append(evidence_ref)
        return {"executed": False}

    guard = _unknown_payment(tmp_path, checker)
    assert guard.resolve(tenant="t", operation_id="A", executed=False, resolved_by="p",
                         evidence_ref="stmt-1") == cl.RESOLVER_IS_PRINCIPAL
    assert asked == []
    assert guard.unresolved("t")[0]["operation_id"] == "A"


# ── the observer is asked about this tenant and resource, including names with spaces ──


def _recording_observer(plant, asked):
    def observe(tenant, quantity, resource):
        asked.append((tenant, quantity, resource))
        return plant[resource]
    return observe


def test_the_observer_is_asked_about_the_tenant_and_resource_of_the_call(tmp_path):
    plant = {"Pump 2": 19.0}
    asked = []
    guard = cl.LimitGuard(policy(meters=PREV_METERS, limits=[*LIMITS, dict(SEEN_LIMIT, max=60)]),
                          cl.LimitLedger(tmp_path / "space.db"),
                          observer=_recording_observer(plant, asked))
    assert reserve(guard, "move_seen", "1", unit="Pump 2", value=19.5) is None
    assert guard.fence("1") is None
    assert guard.begin("1") is None
    plant["Pump 2"] = 19.4
    [record] = guard.settle("1", ok=True, result={"previous": 17.0}, now=T0)
    assert (record["resource"], record["observed"], record["reached"]) == ("Pump 2", 194, False)
    assert (record["actual_movement"], record["charged_after"]) == (24, 19)
    assert asked == [("t", "seen", "Pump 2")] * 3
    assert [(k.split(cl._SEP), a) for k, a in guard.ledger.charges("1#after")] == [
        (["seen", "*", "Pump 2"], 19)]
    # An unknown outcome on the same resource lists the counter by its limit id.
    assert reserve(guard, "move_seen", "2", unit="Pump 2", value=19.0) is None
    guard.settle("2", ok=False)
    [unresolved] = guard.unresolved("t")
    assert unresolved["operation_id"] == "2" and unresolved["principal"] == "p"
    assert unresolved["tool"] == "move_seen"
    assert unresolved["charges"] == [{"counter": "seen", "amount": 4}]


def test_a_tracked_meter_before_an_observed_one_does_not_hide_it(tmp_path):
    """One write moves a tracked value and an observed one. The tracked row is
    skipped; the observed row is still fenced, read back and accounted."""
    plant = {"V-1": 40.0}
    asked = []
    meters = {"move_both": [
        {"quantity": "movement", "kind": "change", "argument": "value", "scale": 10,
         "unit": "degC", "resource_argument": "unit"},
        {"quantity": "travel", "kind": "change", "argument": "pct", "scale": 1,
         "unit": "pct", "resource_argument": "valve", "observed": True,
         "previous_field": "old_pct"},
    ]}
    limits = [*LIMITS,
              {"limit_id": "travel", "tenant": "t", "quantity": "travel", "unit": "pct",
               "max": 60, "window_seconds": 3600, "principal": "*", "resource": "*"}]
    guard = cl.LimitGuard(policy(meters=meters, limits=limits),
                          cl.LimitLedger(tmp_path / "both.db"),
                          observer=_recording_observer(plant, asked))
    assert reserve(guard, "move_both", "1", unit="AHU-1", value=19.5, valve="V-1",
                   pct=45) is None
    plant["V-1"] = 41.0                       # an operator moved it after the reservation
    assert guard.fence("1") == cl.STATE_CHANGED
    plant["V-1"] = 40.0
    assert guard.fence("1") is None
    plant["V-1"] = 45.0
    records = guard.settle("1", ok=True, result={"old_pct": 10}, now=T0)
    assert [r["quantity"] for r in records] == ["travel"]
    assert (records[0]["actual_movement"], records[0]["charged_after"]) == (35, 30)
    assert asked == [("t", "travel", "V-1")] * 4


# ── a preview reserves nothing and reads the clock it is given ────────────────


def test_a_preview_reads_the_clock_it_is_given_and_reserves_nothing(tmp_path):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "preview.db"))
    assert reserve(guard, "start", "1", now=T0, unit="AHU-1") is None
    assert reserve(guard, "start", "2", now=T0 + 1, unit="AHU-1") is None
    args = {"unit": "AHU-1"}
    assert guard.preview(tenant="t", principal="p", tool_name="start", arguments=args,
                         now=T0 + 2) == cl.EXCEEDED
    assert guard.preview(tenant="t", principal="p", tool_name="start", arguments=args,
                         now=T0 + 3601) is None                   # the window slid
    assert guard.preview(tenant="t", principal="p", tool_name="start", arguments=args,
                         now=T0 + 3601) is None                   # and nothing was reserved
    assert reserve(guard, "start", "3", now=T0 + 3601, unit="AHU-1") is None


# ── a reservation lives until its lease expires, not until the clock is read ──


def test_a_reservation_whose_lease_has_not_expired_is_not_released(tmp_path):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "expiry.db"))
    assert guard.reserve(tenant="t", principal="p", tool_name="start",
                         arguments={"unit": "AHU-1"}, operation_id="A", request_hash="h-A",
                         now=T0, expires_at=T0 + 300) is None
    assert reserve(guard, "start", "B", now=T0 + 10, unit="AHU-1") is None
    assert guard.begin("A") is None
    assert guard.reserve(tenant="t", principal="p", tool_name="start",
                         arguments={"unit": "AHU-1"}, operation_id="C", request_hash="h-C",
                         now=T0 + 20, expires_at=T0 + 300) == cl.EXCEEDED


# ── the operation key is a frozen canonical form ──────────────────────────────


def _keyed_guard(tmp_path):
    return cl.LimitGuard(policy(idempotency={"pay": {"key_arguments": ["payee", "amount",
                                                                        "cur", "reference"]}}),
                         cl.LimitLedger(tmp_path / "keyed.db"))


def test_the_operation_key_is_the_sha256_of_its_canonical_json(tmp_path):
    import hashlib

    guard = _keyed_guard(tmp_path)
    args = {"payee": "Ørsted Hafslund", "amount": 7000, "cur": "JPY", "reference": "INV-1"}
    body = '["t","pay",["payee","amount","cur","reference"],["Ørsted Hafslund",7000,"JPY","INV-1"]]'
    assert guard.operation_key("t", "pay", args) == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert guard.operation_key("t", "pay", args) == (
        "%s" % hashlib.sha256(body.encode()).hexdigest())
    assert guard.operation_key("t", "start", {"unit": "AHU-1"}) is None


def test_the_same_payment_in_two_tenants_is_two_operations(tmp_path):
    guard = _keyed_guard(tmp_path)
    args = dict(payee="acme", amount=7000, cur="JPY", reference="INV-1")
    assert reserve(guard, "pay", "A", **args) is None
    assert reserve(guard, "pay", "A2", **args) == cl.DUPLICATE_IN_FLIGHT
    assert guard.reserve(tenant="u", principal="p", tool_name="pay", arguments=args,
                         operation_id="B", request_hash="h-B", now=T0) == cl.UNDECLARED
    other = cl.LimitGuard(policy(limits=[*LIMITS, dict(LIMITS[0], limit_id="spend-u", tenant="u")],
                                 idempotency={"pay": {"key_arguments": ["payee", "amount",
                                                                        "cur", "reference"]}}),
                          guard.ledger)
    assert other.reserve(tenant="u", principal="p", tool_name="pay", arguments=args,
                         operation_id="B", request_hash="h-B", now=T0) is None


def test_a_call_whose_arguments_are_not_an_object_has_no_key_and_is_refused(tmp_path):
    """A keyed tool that reads no arguments for its meter still cannot be
    identified from an argument list: refused as unidentifiable, not as a
    ledger failure."""
    meters = {**METERS_PLAIN, "ping": [{"quantity": "pings", "kind": "count", "unit": "pings"}]}
    limits = [*LIMITS, {"limit_id": "pings", "tenant": "t", "quantity": "pings",
                        "unit": "pings", "max": 5, "principal": "*"}]
    guard = cl.LimitGuard(policy(meters=meters, limits=limits,
                                 idempotency={"ping": {"key_arguments": ["ref"]}}),
                          cl.LimitLedger(tmp_path / "ping.db"))
    assert reserve(guard, "ping", "A", ref="r-1") is None
    assert guard.reserve(tenant="t", principal="p", tool_name="ping", arguments=["r-2"],
                         operation_id="B", request_hash="h-B", now=T0) == cl.IDEMPOTENCY_KEY_INVALID


# ── a signed policy: the envelope, the bytes and the pilot's own file ──────────


def test_a_signed_envelope_carries_signed_at_as_metadata():
    from remora.crypto import SignatureDomain, SigningKey

    key = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    body = {"schema": cl.SCHEMA, "meters": METERS_PLAIN, "limits": LIMITS}
    document = cl.sign_policy(body, key, "2026-10-23T00:00:00Z")
    assert set(document) == {"schema", "policy", "signed_at", "signature"}
    assert document["signed_at"] == "2026-10-23T00:00:00Z"
    assert cl.canonical_policy_bytes({"b": "Ø", "a": 1}) == b'{"a":1,"b":"\xc3\x98"}'


@pytest.mark.parametrize("document, message", [
    ("x", "limit policy is not a signed 'remora-cumulative-limits-signed/v1' envelope"),
    ([], "limit policy is not a signed 'remora-cumulative-limits-signed/v1' envelope"),
    ({"schema": cl.SCHEMA},
     "limit policy is not a signed 'remora-cumulative-limits-signed/v1' envelope"),
    ({"schema": cl.SIGNED_SCHEMA, "policy": "x", "signature": {}},
     "signed limit policy needs a policy and a signature"),
    ({"schema": cl.SIGNED_SCHEMA, "policy": {}, "signature": "x"},
     "signed limit policy needs a policy and a signature"),
])
def test_an_unsigned_or_malformed_envelope_is_refused_and_says_why(document, message):
    with pytest.raises(cl.LimitPolicyError) as caught:
        cl.verify_signed_policy(document, [])
    assert str(caught.value) == message


def test_the_pilots_committed_limits_verify_under_the_pilots_trusted_key():
    import json
    from pathlib import Path

    from remora.crypto import SignatureDomain, VerificationKey

    pilot = Path(__file__).resolve().parents[2] / "deploy" / "ot-pilot"
    document = json.loads((pilot / "limits.json").read_text(encoding="utf-8"))
    compose = (pilot / "docker-compose.yml").read_text(encoding="utf-8")
    [raw_key] = [line.split(":", 1)[1].strip() for line in compose.splitlines()
                 if line.strip().startswith("REMORA_LIMITS_TRUSTED_KEYS:")]
    key = VerificationKey.from_text(raw_key, {SignatureDomain.LIMIT_POLICY})
    policy_out, kid = cl.verify_signed_policy(document, [key])
    assert kid == key.kid == document["signature"]["kid"]
    assert policy_out == document["policy"] and policy_out["coverage"] == "all_writes"
    # Any edit to the signed body is refused: the budget cannot be widened in place.
    widened = json.loads(json.dumps(document))
    widened["policy"]["limits"][0]["max"] += 1
    with pytest.raises(cl.LimitPolicyError, match="limit policy signature refused"):
        cl.verify_signed_policy(widened, [key])


# ── messages an operator reads at startup ─────────────────────────────────────


def test_an_in_memory_ledger_is_refused_by_name():
    with pytest.raises(ValueError, match="^cumulative limit ledger: ':memory:' is an in-memory"):
        cl.LimitLedger(":memory:")


def test_observed_meters_without_an_observer_are_refused_by_name(tmp_path):
    with pytest.raises(cl.LimitPolicyError, match="^observed change meters need an observer$"):
        cl.LimitGuard(policy(meters=PREV_METERS, limits=[*LIMITS, SEEN_LIMIT]),
                      cl.LimitLedger(tmp_path / "x.db"))


def test_the_topology_problem_is_stated_in_full():
    problem = cl.ledger_topology_problem("/var/lib/remora/limits.db",
                                         authority_dsn="postgresql://a/b", scope="")
    assert problem == (
        "REMORA_LIMITS_LEDGER is a host-local SQLite file while REMORA_PG_DSN holds the "
        "authority state, so a second executor host would keep its own budget and could "
        "spend the whole limit. Use a PostgreSQL DSN for REMORA_LIMITS_LEDGER, or set "
        "REMORA_LIMITS_LEDGER_SCOPE=single_host to declare that exactly one host runs executors")
    assert cl.ledger_topology_problem("/x.db", authority_dsn="postgresql://a/b",
                                      scope="cluster") == (
        "REMORA_LIMITS_LEDGER_SCOPE='cluster' is not 'single_host'; leave it unset for a "
        "PostgreSQL ledger")


# ── the dispatcher hands the guard the lease's clock, expiry and principal ─────

ISO_T0 = "2027-01-15T10:00:00+00:00"
ISO_T0_PLUS_100 = "2027-01-15T10:01:40+00:00"


def test_the_after_the_fact_charge_is_dated_by_the_dispatch_clock(tmp_path):
    """The charge the controller's report adds sits in the window of the
    dispatch's own clock, not the wall clock, so the next call within that
    window meets it."""
    plant = {"AHU-1": 19.0}
    guard = cl.LimitGuard(policy(meters=PREV_METERS, limits=[*LIMITS, dict(SEEN_LIMIT, max=30)]),
                          cl.LimitLedger(tmp_path / "clock.db"), observer=lambda t, q, r: plant[r])
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 19.5}
    assert d._limit_refusal(_lease("n1"), "move_seen", args, args, ISO_T0) is None    # 5
    plant["AHU-1"] = 19.5
    d._limit_settle(_lease("n1"), "move_seen", ok=True, result={"previous": 17.0}, now=ISO_T0)
    # 5 + 20 after the fact = 25; 0.6 more (6) is 31 of 30 inside the window.
    later = {"unit": "AHU-1", "value": 20.1}
    assert d._limit_refusal(_lease("n2"), "move_seen", later, later,
                            ISO_T0_PLUS_100) == cl.EXCEEDED


def test_a_reservation_is_released_when_its_own_lease_expires(tmp_path):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "lease-expiry.db"))
    d = _dispatcher(guard)
    short = SimpleNamespace(tenant_id="t", actor_identity="p", nonce="n1",
                            expires_at="2027-01-15T10:00:05+00:00",
                            tool_args_hash="h" * 64, proposal_id="prop")
    args = {"unit": "AHU-1"}
    assert d._limit_refusal(short, "start", args, args, ISO_T0) is None
    assert d._limit_refusal(_lease("n2"), "start", args, args, ISO_T0_PLUS_100) is None
    assert d._limit_begin(short, "start") == cl.RESERVATION_RELEASED
    # The released start no longer counts: a third start fits the limit of two.
    assert d._limit_refusal(_lease("n3"), "start", args, args, ISO_T0_PLUS_100) is None


def test_a_lease_without_a_principal_reserves_nothing(tmp_path):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "principal.db"))
    d = _dispatcher(guard)
    anonymous = SimpleNamespace(tenant_id="t", actor_identity=None, nonce="n1", expires_at=None,
                                tool_args_hash="h" * 64, proposal_id="prop")
    args = {"unit": "AHU-1"}
    assert d._limit_refusal(anonymous, "start", args, args, ISO_T0) == cl.PRINCIPAL_MISSING
    assert guard.ledger.charges("lease:n1") == []


# ── through dispatch: the refusal, its event and the dispatch clock ────────────


def test_a_dispatch_past_the_limit_is_refused_with_its_event_at_the_dispatch_clock(
        tmp_path, caplog, monkeypatch):
    from remora.enforcement.lease import ExecutionLease

    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "limits-dispatch-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "dispatch.db"))
    d = GovernedToolDispatcher(expected_policy_bundle_hash="b1")
    d.register("start", lambda arguments: "started")
    d.bind_limit_guard(guard)
    args = {"unit": "AHU-1"}

    def lease(tag, now):
        from datetime import datetime, timedelta

        issued = datetime.fromisoformat(now)
        return ExecutionLease.issue(
            decision="accept", tenant_id="t", actor_identity="p", tool_name="start",
            arguments=args, target_environment="prod", policy_bundle_hash="b1",
            issued_at=now, expires_at=(issued + timedelta(minutes=30)).isoformat(),
            proposal_id=f"prop-{tag}", grant_jti=f"jti-{tag}")

    def dispatch(tag, now):
        return d.dispatch(lease(tag, now), "start", args, tenant_id="t",
                          target_environment="prod", actor_identity="p", now=now)

    assert dispatch("a", ISO_T0).executed is True
    assert dispatch("b", ISO_T0_PLUS_100).executed is True
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        third = dispatch("c", ISO_T0_PLUS_100)
    assert (third.executed, third.refusal_reason, third.proposal_id) == (
        False, cl.EXCEEDED, "prop-c")
    [event] = _events(caplog, "dispatch.refused")
    assert event.levelno == logging.WARNING
    assert _payload(event) == {"reason": "limit_exceeded", "tenant_id": "t",
                               "tool_name": "start", "proposal_id": "prop-c",
                               "grant_jti": "jti-c"}
    # The window is the dispatch clock's: an hour later the first start has left it.
    assert dispatch("d", "2027-01-15T11:00:01+00:00").executed is True


# ── through dispatch, with the independent recorder: the fence, the adapter's word, the clock ──


class _Recorder:
    def __init__(self):
        self.entries = []

    def append(self, kind, payload):
        self.entries.append((kind, dict(payload)))
        return SimpleNamespace(seq=len(self.entries) - 1)


@pytest.fixture()
def signing(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "limits-dispatch-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _real_lease(tool, args, *, now=ISO_T0, ttl_seconds=1800, tag="x"):
    from datetime import datetime, timedelta

    from remora.enforcement.lease import ExecutionLease

    issued = datetime.fromisoformat(now)
    return ExecutionLease.issue(
        decision="accept", tenant_id="t", actor_identity="p", tool_name=tool, arguments=args,
        target_environment="prod", policy_bundle_hash="b1", issued_at=now,
        expires_at=(issued + timedelta(seconds=ttl_seconds)).isoformat(),
        proposal_id=f"prop-{tag}", grant_jti=f"jti-{tag}")


def _recorded(lease, tool, **detail):
    return ("dispatch", {"phase": "intent", "tenant_id": "t", "tool_name": tool,
                         "proposal_id": lease.proposal_id, "grant_jti": lease.grant_jti,
                         "tool_args_hash": lease.tool_args_hash, "nonce": lease.nonce, **detail})


def _outcome(lease, tool, outcome):
    kind, payload = _recorded(lease, tool)
    return (kind, {**payload, "phase": "outcome", "intent_seq": 0, "outcome": outcome})


def test_a_plant_that_moved_before_the_write_refuses_at_the_fence_and_records_it(
        tmp_path, caplog, signing):
    readings = [19.0, 17.0]                # at the reservation, then at the fence
    asked = []

    def observe(tenant, quantity, resource):
        asked.append((tenant, quantity, resource))
        return readings.pop(0) if len(readings) > 1 else readings[0]

    guard = cl.LimitGuard(policy(meters=PREV_METERS, limits=[*LIMITS, SEEN_LIMIT]),
                          cl.LimitLedger(tmp_path / "fence.db"), observer=observe)
    ran = []
    d = GovernedToolDispatcher(expected_policy_bundle_hash="b1")
    d.register("move_seen", lambda arguments: ran.append(arguments) or {"previous": 19.0})
    d.bind_limit_guard(guard)
    recorder = _Recorder()
    d.bind_recorder(recorder, lambda tool: True)
    args = {"unit": "AHU-1", "value": 19.5}
    lease = _real_lease("move_seen", args, tag="fence")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = d.dispatch(lease, "move_seen", args, tenant_id="t", target_environment="prod",
                            actor_identity="p", now=ISO_T0)
    assert ran == []
    assert (result.executed, result.refusal_reason, result.proposal_id,
            result.recorder_seq, result.dispatch_began) == (
        False, cl.STATE_CHANGED, "prop-fence", 0, False)
    [event] = _events(caplog, "dispatch.refused")
    assert event.levelno == logging.WARNING
    assert _payload(event) == {"reason": "limit_state_changed", "tenant_id": "t",
                               "tool_name": "move_seen", "proposal_id": "prop-fence",
                               "grant_jti": "jti-fence"}
    assert recorder.entries == [_recorded(lease, "move_seen"), _outcome(lease, "move_seen", "refused")]
    assert asked == [("t", "seen", "AHU-1")] * 2
    # Nothing was written, so the reservation is given back and the resource is free.
    assert guard.ledger.charges(f"lease:{lease.nonce}") == []
    assert reserve(guard, "move_seen", "next", unit="AHU-1", value=19.0) is None


@pytest.mark.parametrize("source, reservation", [("rail", "released"), ("someone", "held")])
def test_the_adapters_word_that_nothing_ran_is_recorded_and_believed_only_from_a_trusted_source(
        tmp_path, caplog, signing, source, reservation):
    guard = cl.LimitGuard(policy(non_execution={"pay": {"trusted_sources": ["rail"]}}),
                          cl.LimitLedger(tmp_path / "rail.db"))

    def pay(arguments):
        raise ToolDidNotExecute(source, "refused: insufficient funds")

    d = GovernedToolDispatcher(expected_policy_bundle_hash="b1")
    d.register("pay", pay)
    d.bind_limit_guard(guard)
    recorder = _Recorder()
    d.bind_recorder(recorder, lambda tool: True)
    args = {"amount": 20000, "cur": "JPY"}
    lease = _real_lease("pay", args, tag="rail")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = d.dispatch(lease, "pay", args, tenant_id="t", target_environment="prod",
                            actor_identity="p", now=ISO_T0)
    assert (result.executed, result.refusal_reason, result.proposal_id, result.dispatch_began,
            result.recorder_seq, result.pre_effect) == (
        False, "tool_did_not_execute", "prop-rail", True, 0,
        (source, "refused: insufficient funds"))
    [event] = _events(caplog, "dispatch.refused")
    assert event.levelno == logging.WARNING
    assert _payload(event) == {"reason": "tool_did_not_execute", "tenant_id": "t",
                               "tool_name": "pay", "proposal_id": "prop-rail",
                               "grant_jti": "jti-rail",
                               "detail": f"{source}: refused: insufficient funds",
                               "limit_reservation": reservation}
    assert recorder.entries == [_recorded(lease, "pay"), _outcome(lease, "pay", "refused")]
    # The whole budget comes back only on the trusted source's word.
    assert reserve(guard, "pay", "again", amount=20000, cur="JPY") == (
        None if reservation == "released" else cl.EXCEEDED)


def test_a_reservation_whose_tool_is_running_is_never_released_by_time(tmp_path, signing):
    """The lease may expire while the tool runs. Marked started before the
    tool is invoked, its reservation stays until the call settles; a reserve
    made meanwhile, past the expiry, still meets it."""
    guard = cl.LimitGuard(policy(limits=[*LIMITS[:2], dict(LIMITS[2], max=1)]),
                          cl.LimitLedger(tmp_path / "running.db"))
    inner = []

    def start(arguments):
        from datetime import datetime

        past_expiry = datetime.fromisoformat(ISO_T0).timestamp() + 120
        inner.append(reserve(guard, "start", "inner", now=past_expiry, unit="AHU-1"))
        return "started"

    d = GovernedToolDispatcher(expected_policy_bundle_hash="b1")
    d.register("start", start)
    d.bind_limit_guard(guard)
    args = {"unit": "AHU-1"}
    lease = _real_lease("start", args, ttl_seconds=60, tag="running")
    result = d.dispatch(lease, "start", args, tenant_id="t", target_environment="prod",
                        actor_identity="p", now=ISO_T0)
    assert result.executed is True, result.refusal_reason
    assert inner == [cl.EXCEEDED]


def test_the_charge_after_the_fact_through_dispatch_is_dated_by_the_dispatch_clock(
        tmp_path, signing):
    plant = {"AHU-1": 19.0}
    guard = cl.LimitGuard(policy(meters=PREV_METERS, limits=[*LIMITS, dict(SEEN_LIMIT, max=30)]),
                          cl.LimitLedger(tmp_path / "after-dispatch.db"),
                          observer=lambda t, q, r: plant[r])

    def move(arguments):
        plant["AHU-1"] = arguments["value"]
        return {"previous": 17.0}        # the controller says it came from 17.0

    d = GovernedToolDispatcher(expected_policy_bundle_hash="b1")
    d.register("move_seen", move)
    d.bind_limit_guard(guard)
    args = {"unit": "AHU-1", "value": 19.5}
    lease = _real_lease("move_seen", args, tag="after")
    result = d.dispatch(lease, "move_seen", args, tenant_id="t", target_environment="prod",
                        actor_identity="p", now=ISO_T0)
    assert result.executed is True, result.refusal_reason
    later = {"unit": "AHU-1", "value": 20.1}
    assert d._limit_refusal(_lease("n2"), "move_seen", later, later,
                            ISO_T0_PLUS_100) == cl.EXCEEDED


# ── a call's unit and resource are bounded like the policy's strings ──────────


def test_a_calls_unit_and_resource_are_strings_of_at_most_200_characters(tmp_path):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "bounds.db"))
    assert reserve(guard, "start", "1", unit="u" * 200) is None
    assert reserve(guard, "start", "2", unit="u" * 201) == cl.RESOURCE_INVALID
    assert reserve(guard, "start", "3", unit="") == cl.RESOURCE_INVALID
    assert reserve(guard, "start", "4", unit=5) == cl.RESOURCE_INVALID
    assert reserve(guard, "start", "5", unit="a\x1fb") == cl.RESOURCE_INVALID
    assert reserve(guard, "start", "6") == cl.RESOURCE_INVALID
    assert guard.reserve(tenant="t", principal="p", tool_name="pay",
                         arguments={"amount": 1, "cur": "c" * 200}, operation_id="7",
                         request_hash="h", now=T0) == cl.UNDECLARED        # read, then no limit
    for cur in ("c" * 201, "", 5, "J\x1fPY", None):
        assert guard.reserve(tenant="t", principal="p", tool_name="pay",
                             arguments={"amount": 1, "cur": cur}, operation_id="8",
                             request_hash="h", now=T0) == cl.UNIT_INVALID


# ── a released operation is not reserved again under its own id ───────────────


def test_a_released_operation_cannot_be_reserved_again_under_its_own_id(tmp_path):
    """After a fence refusal the value row still names the operation while its
    reservations are gone. Reserving under the same id again must refuse as
    changed, and never record a charge of -1 (which would widen the budget)."""
    plant = {"AHU-1": 19.0}
    guard = cl.LimitGuard(policy(meters=PREV_METERS, limits=[*LIMITS, SEEN_LIMIT]),
                          cl.LimitLedger(tmp_path / "released.db"),
                          observer=lambda t, q, r: plant[r])
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    guard.release("1")
    assert guard.ledger.charges("1") == []
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) == cl.RESERVATION_RELEASED
    assert guard.ledger.charges("1") == []
    # Another operation on the resource starts from the value the reservation was measured from.
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=21.0) is None
    assert guard.ledger.charges("2") == [(cl._SEP.join(("seen", "*", "AHU-1")), 20)]


# ── the persisted counter keys: a reopened ledger sees what was reserved ───────
#
# Review of PR #1171: a mutant that changes the serialized counter key is not
# equivalent across a restart or an upgrade, because the ledger on disk was
# written under the old key. These tests pin the key format as it is persisted
# and show a reopened ledger still enforcing earlier consumption.

PERSISTED_KEYS = {
    # a per-principal limit with no resource: the principal, and "*" for all resources
    ("spend", "p", None): "spend\x1fp\x1f*",
    # a shared, per-resource limit: "*" for every principal, the resource itself
    ("move", "p", "AHU-1"): "move\x1f*\x1fAHU-1",
    ("starts", "q", "Pump 2"): "starts\x1f*\x1fPump 2",
}


def test_the_counter_key_format_is_frozen():
    by_id = {lim.limit_id: lim for lim in policy().limits}
    for (limit_id, principal, resource), key in PERSISTED_KEYS.items():
        assert by_id[limit_id].counter_key(principal, resource) == key
    fixed = policy(limits=[*LIMITS, dict(LIMITS[1], limit_id="ahu1", resource="AHU-1")]).limits[-1]
    assert fixed.counter_key("p", "AHU-1") == "ahu1\x1f*\x1fAHU-1"
    own = policy(limits=[*LIMITS, dict(LIMITS[1], limit_id="own", principal="p",
                                       resource=None)]).limits[-1]
    assert own.counter_key("p", "AHU-1") == "own\x1fp\x1f*"


def test_a_reopened_ledger_enforces_what_an_earlier_process_reserved(tmp_path):
    """Two payments of 7000 under one process, then the ledger file is opened by
    a new LimitLedger and LimitGuard, as a restarted executor would. The third
    payment must still refuse, and the rows must carry the frozen keys."""
    import sqlite3

    path = tmp_path / "persisted.db"
    first = cl.LimitGuard(policy(), cl.LimitLedger(path))
    assert reserve(first, "pay", "A", amount=7000, cur="JPY") is None
    assert reserve(first, "pay", "B", amount=7000, cur="JPY") is None
    assert reserve(first, "move", "M1", unit="AHU-1", value=19.5) is None
    first.settle("M1", ok=True)
    assert reserve(first, "start", "S1", principal="q", unit="Pump 2") is None
    del first

    reopened = cl.LimitGuard(policy(), cl.LimitLedger(path))
    assert reserve(reopened, "pay", "C", amount=7000, cur="JPY") == cl.EXCEEDED
    assert reserve(reopened, "move", "M2", unit="AHU-1", value=21.5) == cl.EXCEEDED  # 0.5 + 2.0 of 2.0
    assert reserve(reopened, "start", "S2", principal="r", unit="Pump 2") is None
    assert reserve(reopened, "start", "S3", principal="s", unit="Pump 2") == cl.EXCEEDED
    with sqlite3.connect(path) as conn:
        keys = {row[0] for row in conn.execute("SELECT counter_key FROM limit_counter")}
    assert keys == set(PERSISTED_KEYS.values())


def test_a_limit_redefined_under_the_same_id_fails_closed_on_the_old_ledger(tmp_path):
    """The persisted counter carries the limit's binding. A limit whose
    definition changed (here the maximum) meets its old rows and refuses as
    changed rather than counting from zero."""
    path = tmp_path / "rebound.db"
    old = cl.LimitGuard(policy(), cl.LimitLedger(path))
    assert reserve(old, "pay", "A", amount=7000, cur="JPY") is None
    widened = cl.LimitGuard(policy(limits=[dict(LIMITS[0], max=40000), *LIMITS[1:]]),
                            cl.LimitLedger(path))
    assert reserve(widened, "pay", "B", amount=7000, cur="JPY") == cl.CHANGED
