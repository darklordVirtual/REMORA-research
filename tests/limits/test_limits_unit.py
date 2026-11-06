# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""LimitPolicy validation, LimitGuard reservation and the dispatcher hooks."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from remora.enforcement import cumulative_limits as cl

T0 = 1_800_000_000.0
METERS = {
    "pay": [{"quantity": "spend", "kind": "sum", "argument": "amount", "unit_argument": "cur"}],
    "move": [{"quantity": "movement", "kind": "change", "argument": "value", "scale": 10,
              "unit": "degC", "resource_argument": "unit"}],
    "start": [{"quantity": "starts", "kind": "count", "unit": "starts",
               "resource_argument": "unit"}],
}
LIMITS = [
    {"limit_id": "spend", "tenant": "t", "quantity": "spend", "unit": "JPY", "max": 20000,
     "principal": "p"},
    {"limit_id": "move", "tenant": "t", "quantity": "movement", "unit": "degC", "max": 20,
     "window_seconds": 3600, "principal": "*", "resource": "*"},
    {"limit_id": "starts", "tenant": "t", "quantity": "starts", "unit": "starts", "max": 2,
     "window_seconds": 3600, "principal": "*", "resource": "*"},
]
BASELINES = [{"tenant": "t", "quantity": "movement", "resource": "AHU-1", "value": 19.0,
              "seed_id": "s1"}]


def policy(**changes):
    data = {"schema": cl.SCHEMA, "meters": METERS, "limits": LIMITS, "baselines": BASELINES}
    data.update(changes)
    return cl.LimitPolicy.from_dict(data)


@pytest.fixture()
def guard(tmp_path):
    return cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "ledger.db"))


def reserve(guard, tool, op, now=T0, principal="p", **arguments):
    return guard.reserve(tenant="t", principal=principal, tool_name=tool, arguments=arguments,
                         operation_id=op, request_hash=f"h-{op}", now=now)


def settle(guard, op, ok=True):
    guard.settle(op, ok)


import re

MAX = cl.MAX_UNITS
MALFORMED = [
    ({"schema": "other"}, "limit policy schema must be 'remora-cumulative-limits/v1'"),
    ({"coverage": "some"}, f"coverage must be one of {re.escape(str(cl.COVERAGES))}"),
    ({"meters": {}}, "a limit policy meters at least one tool"),
    ({"meters": "x"}, "a limit policy meters at least one tool"),
    ({"meters": {"pay": []}}, "tool 'pay': a non-empty list of meters"),
    ({"meters": {"pay": "x"}}, "tool 'pay': a non-empty list of meters"),
    ({"meters": {"pay": ["x"]}}, "tool 'pay': each meter is an object"),
    ({"meters": {"": METERS["pay"]}}, "tool name must be a non-empty string of at most 200 characters"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "avg", "argument": "a", "unit": "u"}]}},
     f"tool 'pay': kind must be one of {re.escape(str(cl.KINDS))}"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "unit": "u"}]}},
     "tool 'pay' argument must be a non-empty string of at most 200 characters"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "count", "argument": "a", "unit": "u"}]}},
     "tool 'pay': a count meter reads no argument"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a"}]}},
     "tool 'pay': declare exactly one of unit, unit_argument"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a", "unit": "u",
                          "unit_argument": "c"}]}},
     "tool 'pay': declare exactly one of unit, unit_argument"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "change", "argument": "a", "unit": "u"}]}},
     "tool 'pay': a change meter needs resource_argument"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a", "unit": "u",
                          "observed": "yes"}]}},
     "tool 'pay': observed is a boolean, on change meters only"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a", "unit": "u",
                          "observed": True}]}},
     "tool 'pay': observed is a boolean, on change meters only"),
    ({"meters": {"move": [dict(METERS["move"][0], previous_field="old")]}},
     "tool 'move': previous_field needs an observed meter"),
    ({"meters": {"move": [dict(METERS["move"][0], observed="yes")]}},
     "tool 'move': observed is a boolean, on change meters only"),
    ({"meters": {"pay": [{"quantity": "", "kind": "sum", "argument": "a", "unit": "u"}]}},
     "tool 'pay' quantity must be a non-empty string of at most 200 characters"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a", "unit": ""}]}},
     "unit must be a non-empty string of at most 200 characters"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a",
                          "unit_argument": ""}]}},
     "unit_argument must be a non-empty string of at most 200 characters"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a", "unit": "u",
                          "resource_argument": ""}]}},
     "resource_argument must be a non-empty string of at most 200 characters"),
    ({"meters": {"move": [dict(METERS["move"][0], observed=True, previous_field="")]}},
     "previous_field must be a non-empty string of at most 200 characters"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a", "unit": "u"},
                         {"quantity": "q", "kind": "count", "unit": "u"}]}},
     "tool 'pay': one meter per quantity"),
    ({"meters": {"a": [{"quantity": "q", "kind": "sum", "argument": "x", "unit": "u"}],
                 "b": [{"quantity": "q", "kind": "sum", "argument": "x", "unit": "u",
                        "scale": 10}]}},
     "quantity 'q' has two scales"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "sum", "argument": "a", "unit": "u",
                          "scale": 0}]}},
     f"scale must be an integer in \\[1, {MAX}\\]"),
    ({"meters": {"pay": [{"quantity": "q", "kind": "count", "unit": "u", "per_call": 0}]}},
     f"per_call must be an integer in \\[1, {MAX}\\]"),
    ({"limits": ["x"]}, "each limit is an object"),
    ({"limits": [dict(LIMITS[0], limit_id=None)]}, "limit_id must be a non-empty string of at most 200 characters"),
    ({"limits": [dict(LIMITS[0], tenant="")]}, "tenant must be a non-empty string of at most 200 characters"),
    ({"limits": [dict(LIMITS[0], quantity=" ")]}, "quantity must be a non-empty string of at most 200 characters"),
    ({"limits": [dict(LIMITS[0], unit=1)]}, "unit must be a non-empty string of at most 200 characters"),
    ({"limits": [dict(LIMITS[0], principal="")]}, "principal must be a non-empty string of at most 200 characters"),
    ({"limits": [dict(LIMITS[0], resource="")]}, "resource must be a non-empty string of at most 200 characters"),
    ({"limits": [dict(LIMITS[0], max=-1)]}, f"max must be an integer in \\[0, {MAX}\\]"),
    ({"limits": [dict(LIMITS[0], max=1.5)]}, f"max must be an integer in \\[0, {MAX}\\]"),
    ({"limits": [dict(LIMITS[0], max=MAX + 1)]}, f"max must be an integer in \\[0, {MAX}\\]"),
    ({"limits": [dict(LIMITS[0], window_seconds=0)]},
     f"window_seconds must be an integer in \\[1, {MAX}\\]"),
    ({"limits": [LIMITS[0], LIMITS[0]]}, "limit_id values must be unique"),
    ({"baselines": ["x"]}, "each baseline is an object"),
    ({"baselines": [dict(BASELINES[0], quantity="spend2")]},
     "baseline for unmetered quantity 'spend2'"),
    ({"baselines": [dict(BASELINES[0], quantity="")]},
     "baseline quantity must be a non-empty string of at most 200 characters"),
    ({"baselines": [dict(BASELINES[0], value=19.05)]},
     "baseline value for 'movement' is not exact at scale 10"),
    ({"baselines": [dict(BASELINES[0], tenant="")]}, "tenant must be a non-empty string of at most 200 characters"),
    ({"baselines": [dict(BASELINES[0], resource="")]}, "resource must be a non-empty string of at most 200 characters"),
    ({"baselines": [dict(BASELINES[0], seed_id="")]}, "seed_id must be a non-empty string of at most 200 characters"),
    ({"baselines": [BASELINES[0], dict(BASELINES[0], seed_id="s2")]},
     "two baselines for one resource"),
    ({"idempotency": "x"}, "idempotency is an object keyed by tool"),
    ({"idempotency": {"read": {"key_arguments": ["a"]}}},
     "idempotency for unmetered tool 'read'"),
    ({"idempotency": {"pay": {"key_arguments": []}}},
     "tool 'pay': key_arguments is a non-empty list of distinct argument names"),
    ({"idempotency": {"pay": {"key_arguments": ["a", "a"]}}},
     "tool 'pay': key_arguments is a non-empty list of distinct argument names"),
    ({"idempotency": {"pay": {"key_arguments": [""]}}},
     "tool 'pay' key argument must be a non-empty string of at most 200 characters"),
    ({"non_execution": "x"}, "non_execution is an object keyed by tool"),
    ({"non_execution": {"read": {"trusted_sources": ["rail"]}}},
     "non_execution for unmetered tool 'read'"),
    ({"non_execution": {"pay": {"trusted_sources": []}}},
     "tool 'pay': trusted_sources is a non-empty list of distinct source names"),
    ({"non_execution": {"pay": {"trusted_sources": [""]}}},
     "tool 'pay' trusted source must be a non-empty string of at most 200 characters"),
]


@pytest.mark.parametrize("changes, message", MALFORMED, ids=[m for _, m in MALFORMED])
def test_a_malformed_policy_refuses_and_says_why(changes, message):
    """The operator reads this message when a signed limits.json is wrong and
    the deployment refuses to start. The words are the contract: the whole
    message, anchored, so a wrapped or extended message does not pass."""
    with pytest.raises(cl.LimitPolicyError) as caught:
        policy(**changes)
    assert re.fullmatch(message, str(caught.value)), str(caught.value)


def test_the_validation_bounds_are_inclusive():
    long = "x" * 200
    p = policy(limits=[dict(LIMITS[0], max=0, window_seconds=1),
                       dict(LIMITS[0], limit_id="big", tenant=long, max=MAX)])
    assert (p.limits[0].max, p.limits[0].window_seconds) == (0, 1)
    assert (p.limits[1].max, p.limits[1].tenant) == (MAX, long)
    with pytest.raises(cl.LimitPolicyError, match="tenant must be a non-empty string of at most 200 characters"):
        policy(limits=[dict(LIMITS[0], tenant="x" * 201)])
    assert cl._scaled(MAX, 1) == MAX and cl._scaled(MAX + 1, 1) is None
    assert cl._scaled(MAX / 100, 100) == MAX


def test_a_zero_limit_refuses_every_metered_call(tmp_path):
    guard = cl.LimitGuard(policy(limits=[dict(LIMITS[0], max=0)]),
                          cl.LimitLedger(tmp_path / "zero.db"))
    assert reserve(guard, "pay", "A", amount=1, cur="JPY") == cl.EXCEEDED


def test_three_times_7000_against_20000(guard):
    assert [reserve(guard, "pay", op, amount=7000, cur="JPY") for op in "ABC"] == \
        [None, None, cl.EXCEEDED]


def test_a_window_slides(guard):
    assert reserve(guard, "start", "1", now=T0, unit="AHU-1") is None
    assert reserve(guard, "start", "2", now=T0 + 1000, unit="AHU-1") is None
    assert reserve(guard, "start", "3", now=T0 + 3599, unit="AHU-1") == cl.EXCEEDED
    assert reserve(guard, "start", "4", now=T0 + 3601, unit="AHU-1") is None  # "1" left
    assert reserve(guard, "start", "5", now=T0 + 3700, unit="AHU-1") == cl.EXCEEDED


def test_an_iso_clock_is_read(guard):
    assert reserve(guard, "start", "1", now="2027-01-15T10:00:00+00:00", unit="AHU-1") is None
    assert reserve(guard, "start", "2", now="2027-01-15T10:30:00+00:00", unit="AHU-1") is None
    assert reserve(guard, "start", "3", now="2027-01-15T10:59:00+00:00",
                   unit="AHU-1") == cl.EXCEEDED


def test_without_a_clock_the_wall_clock_is_used(tmp_path):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "wall.db"))
    assert [reserve(guard, "start", op, now=None, unit="AHU-1") for op in "123"] == \
        [None, None, cl.EXCEEDED]


def test_a_limit_added_after_a_reservation_refuses_its_retry(tmp_path):
    ledger = cl.LimitLedger(tmp_path / "l.db")
    first = cl.LimitGuard(policy(), ledger)
    assert reserve(first, "pay", "A", amount=7000, cur="JPY") is None
    extra = dict(LIMITS[0], limit_id="spend-shared", principal="*")
    second = cl.LimitGuard(policy(limits=[*LIMITS, extra]), ledger)
    assert reserve(second, "pay", "A", amount=7000, cur="JPY") == cl.CHANGED


@pytest.mark.parametrize("answer", ["moved", "raises"])
def test_a_guard_whose_policy_is_no_longer_in_force_refuses(tmp_path, answer):
    state = {"in_force": True}

    def in_force():
        if not state["in_force"] and answer == "raises":
            raise OSError("policy file unreadable")
        return state["in_force"]

    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "l.db"), in_force=in_force)
    assert reserve(guard, "pay", "A", amount=7000, cur="JPY") is None
    state["in_force"] = False
    assert guard.governs("unmetered")
    assert reserve(guard, "pay", "B", amount=1, cur="JPY") == cl.POLICY_CHANGED
    assert guard.preview(tenant="t", principal="p", tool_name="pay",
                         arguments={"amount": 1, "cur": "JPY"}) == cl.POLICY_CHANGED
    assert guard.fence("A") == cl.POLICY_CHANGED
    assert guard.compare("pay", {"amount": 1, "cur": "JPY"},
                         {"amount": 1, "cur": "JPY"}) == cl.POLICY_CHANGED
    guard.release("A")           # what was reserved is still released, not stranded
    state["in_force"] = True
    assert reserve(guard, "pay", "C", amount=20000, cur="JPY") is None


def test_movement_is_measured_from_the_last_value(guard):
    assert reserve(guard, "move", "1", unit="AHU-1", value=20.0) is None
    settle(guard, "1")
    assert reserve(guard, "move", "2", unit="AHU-1", value=19.5) is None  # 1.0 + 0.5
    settle(guard, "2")
    assert reserve(guard, "move", "3", unit="AHU-1", value=20.5) == cl.EXCEEDED
    assert reserve(guard, "move", "4", unit="AHU-1", value=20.0) is None  # exactly 2.0


def test_a_pending_move_makes_the_unit_busy(guard):
    assert reserve(guard, "move", "1", unit="AHU-1", value=19.5) is None
    assert reserve(guard, "move", "2", unit="AHU-1", value=19.5) == cl.RESOURCE_BUSY
    settle(guard, "1")
    assert reserve(guard, "move", "2", unit="AHU-1", value=19.5) is None  # no movement


def test_a_failed_move_needs_a_new_seed(guard, tmp_path):
    assert reserve(guard, "move", "1", unit="AHU-1", value=19.5) is None
    settle(guard, "1", ok=False)
    assert reserve(guard, "move", "2", unit="AHU-1", value=19.5) == cl.BASELINE_UNKNOWN
    reseeded = cl.LimitGuard(policy(baselines=[dict(BASELINES[0], value=19.5, seed_id="s2")]),
                             guard.ledger)
    assert reserve(reseeded, "move", "2", unit="AHU-1", value=19.5) is None


def test_a_retry_of_one_operation_is_not_charged_twice(guard):
    assert reserve(guard, "pay", "A", amount=7000, cur="JPY") is None
    assert reserve(guard, "pay", "A", amount=7000, cur="JPY") is None
    assert reserve(guard, "move", "M", unit="AHU-1", value=20.0) is None
    assert reserve(guard, "move", "M", unit="AHU-1", value=20.0) is None  # still pending
    settle(guard, "M")
    assert reserve(guard, "move", "M", unit="AHU-1", value=20.0) is None  # after it ran
    assert reserve(guard, "pay", "B", amount=7000, cur="JPY") is None
    assert reserve(guard, "pay", "C", amount=6000, cur="JPY") is None
    assert reserve(guard, "pay", "D", amount=1, cur="JPY") == cl.EXCEEDED


def test_a_reused_operation_with_another_request_is_refused(guard):
    assert reserve(guard, "pay", "A", amount=7000, cur="JPY") is None
    assert reserve(guard, "pay", "A", amount=1, cur="JPY") == cl.CHANGED


def test_preview_reserves_nothing(guard):
    for _ in range(5):
        assert guard.preview(tenant="t", principal="p", tool_name="pay",
                             arguments={"amount": 7000, "cur": "JPY"}, now=T0) is None
    assert reserve(guard, "pay", "A", amount=20000, cur="JPY") is None


@pytest.mark.parametrize("tool, arguments, reason", [
    ("pay", {"amount": 7000}, cl.UNIT_INVALID),
    ("pay", {"amount": 7000, "cur": ""}, cl.UNIT_INVALID),
    ("pay", {"amount": 10 ** 13, "cur": "JPY"}, cl.AMOUNT_INVALID),
    ("pay", {"amount": float("nan"), "cur": "JPY"}, cl.AMOUNT_INVALID),
    ("pay", {"amount": float("inf"), "cur": "JPY"}, cl.AMOUNT_INVALID),
    ("pay", "not-a-mapping", cl.UNIT_INVALID),
    ("move", {"value": 20.0}, cl.RESOURCE_INVALID),
    ("move", {"unit": "AHU-1", "value": 20.04}, cl.AMOUNT_INVALID),
    ("move", {"unit": "AHU-1"}, cl.AMOUNT_INVALID),
])
def test_an_unreadable_call_is_refused_before_the_ledger(guard, tool, arguments, reason):
    assert guard.reserve(tenant="t", principal="p", tool_name=tool, arguments=arguments,
                         operation_id="op", request_hash="h", now=T0) == reason


def test_a_call_without_a_principal_is_refused(guard):
    assert reserve(guard, "pay", "A", principal="", amount=7000, cur="JPY") == \
        cl.PRINCIPAL_MISSING


def test_unmetered_tools_under_each_coverage(tmp_path):
    ledger = cl.LimitLedger(tmp_path / "l.db")
    listed = cl.LimitGuard(policy(), ledger)
    assert not listed.governs("reset") and listed.preview(
        tenant="t", principal="p", tool_name="reset", arguments={}) is None
    writes = {"reset": True, "read": False}
    strict = cl.LimitGuard(policy(coverage="all_writes"), ledger,
                           is_write=lambda name: writes.get(name))
    assert strict.governs("reset")
    assert reserve(strict, "reset", "1") == cl.TOOL_UNMETERED
    assert reserve(strict, "read", "2") is None
    assert reserve(strict, "unknown", "3") == cl.COVERAGE_UNKNOWN
    assert reserve(cl.LimitGuard(policy(coverage="all_writes"), ledger), "read", "4") == \
        cl.COVERAGE_UNKNOWN

    def broken(name):
        raise RuntimeError("bundle unreadable")
    assert reserve(cl.LimitGuard(policy(coverage="all_writes"), ledger, is_write=broken),
                   "read", "5") == cl.COVERAGE_UNKNOWN


def test_compare_refuses_a_resolved_invocation_that_meters_differently(guard):
    wire = {"amount": 7000, "cur": "JPY"}
    assert guard.compare("pay", wire, dict(wire)) is None
    assert guard.compare("pay", wire, {"amount": 19000, "cur": "JPY"}) == cl.INVOCATION_DIFFERS
    assert guard.compare("pay", wire, {"amount": "x", "cur": "JPY"}) == cl.AMOUNT_INVALID
    assert guard.compare("other", wire, {}) is None


def test_an_unreadable_ledger_refuses(guard, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(guard.ledger, "transaction", broken)
    assert reserve(guard, "pay", "A", amount=7000, cur="JPY") == cl.LEDGER_UNAVAILABLE


def test_the_ledger_refuses_an_in_memory_database():
    with pytest.raises(Exception):
        cl.LimitLedger(":memory:")


def _dispatcher(guard):
    from remora.enforcement.lease import GovernedToolDispatcher

    d = GovernedToolDispatcher(expected_policy_bundle_hash="b" * 64)
    d.bind_limit_guard(guard)
    return d


def _lease(nonce="n1"):
    return SimpleNamespace(tenant_id="t", actor_identity="p", nonce=nonce, expires_at=None,
                           tool_args_hash="h" * 64, proposal_id="prop")


def test_the_dispatcher_ignores_tools_without_a_meter(guard):
    d = _dispatcher(guard)
    assert d._limit_refusal(_lease(), "read", {"amount": 10 ** 9}, {}, None) is None
    d._limit_settle(_lease(), "read", ok=True)  # nothing to settle


def test_the_dispatcher_refuses_a_resolved_amount_the_wire_form_does_not_name(guard):
    d = _dispatcher(guard)
    wire = {"amount": 7000, "cur": "JPY"}
    assert d._limit_refusal(_lease(), "pay", wire, {"amount": 19000, "cur": "JPY"},
                            None) == cl.INVOCATION_DIFFERS


def test_the_dispatcher_keys_the_reservation_by_lease_and_settles_it(guard):
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 20.0}
    assert d._limit_refusal(_lease("n1"), "move", args, args, None) is None
    assert d._limit_refusal(_lease("n1"), "move", args, args, None) is None  # same lease
    assert d._limit_refusal(_lease("n2"), "move", args, args, None) == cl.RESOURCE_BUSY
    d._limit_settle(_lease("n1"), "move", ok=True)
    assert d._limit_refusal(_lease("n2"), "move", args, args, None) is None


def test_a_settle_that_fails_leaves_the_unit_closed(guard, monkeypatch):
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 20.0}
    assert d._limit_refusal(_lease("n1"), "move", args, args, None) is None

    def broken(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(guard, "settle", broken)
    d._limit_settle(_lease("n1"), "move", ok=True)
    monkeypatch.undo()
    assert d._limit_refusal(_lease("n2"), "move", args, args, None) == cl.RESOURCE_BUSY


OBSERVED_METERS = {**METERS, "move_seen": [{"quantity": "seen", "kind": "change",
                                            "argument": "value", "scale": 10, "unit": "degC",
                                            "resource_argument": "unit", "observed": True}]}
SEEN_LIMIT = {"limit_id": "seen", "tenant": "t", "quantity": "seen", "unit": "degC",
              "max": 20, "window_seconds": 3600, "principal": "*", "resource": "*"}


def observed_guard(tmp_path, plant):
    def observe(tenant, quantity, resource):
        value = plant[resource]
        if isinstance(value, Exception):
            raise value
        return value
    return cl.LimitGuard(policy(meters=OBSERVED_METERS, limits=[*LIMITS, SEEN_LIMIT]),
                         cl.LimitLedger(tmp_path / "seen.db"), observer=observe)


@pytest.mark.parametrize("meter", [
    {"quantity": "q", "kind": "count", "unit": "u", "observed": True},
    {"quantity": "q", "kind": "change", "argument": "a", "unit": "u",
     "resource_argument": "r", "observed": "yes"},
])
def test_observed_is_a_boolean_on_change_meters_only(meter):
    with pytest.raises(cl.LimitPolicyError):
        policy(meters={"x": [meter]})


def test_an_observed_meter_needs_an_observer(tmp_path):
    with pytest.raises(cl.LimitPolicyError, match="need an observer"):
        cl.LimitGuard(policy(meters=OBSERVED_METERS), cl.LimitLedger(tmp_path / "l.db"))


def test_movement_is_measured_from_the_observed_value_and_rounded_up(tmp_path):
    plant = {"AHU-1": 19.03}
    guard = observed_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=20.0) is None  # 9.7 -> 10
    assert guard.settle("1", ok=True) == [{"tenant": "t", "quantity": "seen", "resource": "AHU-1",
                                           "target": 200, "observed": 190, "reached": False}]
    plant["AHU-1"] = 20.0
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=21.0) is None  # 10; 20 in all
    guard.settle("2", ok=True)
    plant["AHU-1"] = 21.0
    assert reserve(guard, "move_seen", "3", unit="AHU-1", value=21.1) == cl.EXCEEDED


@pytest.mark.parametrize("reading", [None, "19", True, float("nan"), float("inf"),
                                     ConnectionError("down")])
def test_an_unreadable_observation_refuses(tmp_path, reading):
    guard = observed_guard(tmp_path, {"AHU-1": reading})
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) == \
        cl.OBSERVATION_UNAVAILABLE


def test_observed_moves_are_still_serial_and_retries_are_charged_once(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = observed_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=20.0) is None
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=20.0) == cl.RESOURCE_BUSY
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=20.0) is None  # the retry
    plant["AHU-1"] = 20.0
    assert guard.settle("1", ok=True)[0]["reached"] is True
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=21.0) is None
    assert reserve(guard, "move_seen", "3", unit="AHU-2", value=1.0) == \
        cl.OBSERVATION_UNAVAILABLE  # KeyError at the observer


def test_after_a_failure_the_plant_is_read_instead_of_a_baseline(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = observed_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=20.0) is None
    assert guard.settle("1", ok=False)[0]["observed"] == 190
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=20.0) is None


def test_a_settle_whose_read_back_fails_keeps_the_target(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = observed_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=20.0) is None
    plant["AHU-1"] = ConnectionError("down")
    assert guard.settle("1", ok=True) == [{"tenant": "t", "quantity": "seen", "resource": "AHU-1",
                                           "target": 200, "observed": None, "reached": None}]


def test_settle_reads_back_observed_meters_only(tmp_path):
    guard = observed_guard(tmp_path, {"AHU-1": 19.0})
    assert reserve(guard, "move", "1", unit="AHU-1", value=19.5) is None  # a tracked meter
    assert guard.settle("1", ok=True) == []
    plain = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "plain.db"))
    assert reserve(plain, "move", "1", unit="AHU-1", value=19.5) is None
    assert plain.settle("1", ok=True) == []


def test_the_dispatcher_records_a_target_the_plant_did_not_reach(tmp_path, caplog):
    import logging

    plant = {"AHU-1": 19.0}
    d = _dispatcher(observed_guard(tmp_path, plant))
    args = {"unit": "AHU-1", "value": 20.0}
    assert d._limit_refusal(_lease("n1"), "move_seen", args, args, None) is None
    with caplog.at_level(logging.WARNING):
        d._limit_settle(_lease("n1"), "move_seen", ok=True)
    assert "dispatch.limit_target_not_reached" in caplog.text


def test_a_guard_without_an_observer_observes_nothing(guard):
    assert guard._observe("t", "movement", "AHU-1", 10) is None


PREV_METERS = {**METERS, "move_seen": [dict(OBSERVED_METERS["move_seen"][0],
                                            previous_field="previous")]}


def prev_guard(tmp_path, plant):
    def observe(tenant, quantity, resource):
        value = plant[resource]
        if isinstance(value, Exception):
            raise value
        return value
    return cl.LimitGuard(policy(meters=PREV_METERS, limits=[*LIMITS, SEEN_LIMIT]),
                         cl.LimitLedger(tmp_path / "prev.db"), observer=observe)


def test_previous_field_needs_an_observed_meter():
    with pytest.raises(cl.LimitPolicyError, match="previous_field"):
        policy(meters={"x": [{"quantity": "q", "kind": "change", "argument": "a", "unit": "u",
                              "resource_argument": "r", "previous_field": "old"}]})


def test_the_fence_sees_a_plant_that_moved_or_cannot_be_read(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    assert guard.fence("none") is None                   # nothing observed for it
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    assert guard.fence("1") is None
    plant["AHU-1"] = 17.0
    assert guard.fence("1") == cl.STATE_CHANGED
    plant["AHU-1"] = ConnectionError("down")
    assert guard.fence("1") == cl.OBSERVATION_UNAVAILABLE


def test_release_gives_back_what_an_unrun_call_reserved(tmp_path):
    guard = prev_guard(tmp_path, {"AHU-1": 19.0})
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=21.0) is None   # 2.0
    guard.settle("1", ok=False)
    guard.release("1")
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=21.0) is None   # 2.0 again


def test_movement_the_controller_reports_beyond_the_reservation_is_charged(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None   # 0.5
    plant["AHU-1"] = 19.5
    records = guard.settle("1", ok=True, result={"previous": 17.0}, now=T0)
    assert records[0]["actual_movement"] == 25 and records[0]["charged_after"] == 20
    assert reserve(guard, "move_seen", "2", unit="AHU-1", value=19.6) == cl.EXCEEDED


@pytest.mark.parametrize("result", [None, "text", {}, {"previous": True}, {"previous": "17"}])
def test_no_usable_controller_report_charges_nothing_more(tmp_path, result):
    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    plant["AHU-1"] = 19.5
    assert "charged_after" not in guard.settle("1", ok=True, result=result)[0]


def test_a_report_matching_the_reservation_charges_nothing_more(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    plant["AHU-1"] = ConnectionError("down")             # read-back fails: the target is used
    record = guard.settle("1", ok=True, result={"previous": 19.0})[0]
    assert record["actual_movement"] == 5 and "charged_after" not in record


def test_a_failed_call_is_not_accounted_from_its_result(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    assert "actual_movement" not in guard.settle("1", ok=False, result={"previous": 10.0})[0]


def test_the_dispatcher_fence_release_and_after_the_fact_logging(tmp_path, caplog, monkeypatch):
    import logging

    plant = {"AHU-1": 19.0}
    guard = prev_guard(tmp_path, plant)
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 19.5}
    assert d._limit_fence(_lease("n0"), "read") is None          # ungoverned tool
    assert d._limit_refusal(_lease("n1"), "move_seen", args, args, None) is None
    assert d._limit_fence(_lease("n1"), "move_seen") is None
    plant["AHU-1"] = 19.5
    with caplog.at_level(logging.ERROR):
        d._limit_settle(_lease("n1"), "move_seen", ok=True, result={"previous": 17.0})
    assert "dispatch.limit_charged_after_the_fact" in caplog.text

    def broken(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(guard, "fence", broken)
    assert d._limit_fence(_lease("n1"), "move_seen") == cl.OBSERVATION_UNAVAILABLE
    monkeypatch.setattr(guard, "release", broken)
    with caplog.at_level(logging.WARNING):
        d._limit_release(_lease("n1"), "move_seen")
    assert "dispatch.limit_release_failed" in caplog.text
    d._limit_release(_lease("n1"), "read")                       # ungoverned tool: nothing


def test_after_the_fact_charges_only_the_moved_quantity(tmp_path):
    """A write that is both a move and an actuation: only movement is re-charged."""
    plant = {"AHU-1": 19.0}
    meters = {"move_seen": [PREV_METERS["move_seen"][0],
                            {"quantity": "starts", "kind": "count", "unit": "starts",
                             "resource_argument": "unit"}]}

    def observe(tenant, quantity, resource):
        return plant[resource]
    guard = cl.LimitGuard(policy(meters=meters, limits=[*LIMITS, SEEN_LIMIT], baselines=[]),
                          cl.LimitLedger(tmp_path / "two.db"), observer=observe)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    plant["AHU-1"] = 19.5
    guard.settle("1", ok=True, result={"previous": 17.0})
    after = [(k.split("\x1f")[0], a) for k, a in guard.ledger.charges("1#after")]
    assert after == [("seen", 20)]


def test_a_signed_policy_verifies_only_as_signed():
    from remora.crypto import SignatureDomain, SigningKey

    key = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    body = {"schema": cl.SCHEMA, "meters": METERS, "limits": LIMITS}
    document = cl.sign_policy(body, key, "2026-10-23T00:00:00Z")
    policy_out, kid = cl.verify_signed_policy(document, [key.verification_key()])
    assert policy_out == body and kid == key.kid
    other = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    with pytest.raises(cl.LimitPolicyError, match="unknown_kid"):
        cl.verify_signed_policy(document, [other.verification_key()])
    for broken in (body, {"schema": cl.SIGNED_SCHEMA},
                   {"schema": cl.SIGNED_SCHEMA, "policy": body, "signature": {"x": 1}},
                   dict(document, policy=dict(body, coverage="all_writes"))):
        with pytest.raises(cl.LimitPolicyError):
            cl.verify_signed_policy(broken, [key.verification_key()])


# ── 2026-10-24 audit: fence refusal, naive clock, key separator ───────────────


def test_a_fence_refusal_that_wrote_nothing_does_not_poison_the_resource(tmp_path):
    """The only fence refusal a tracked meter can get is a moved policy. The
    write never happened, so after release the next change starts from the
    value the reservation was measured from, without a new seed."""
    in_force = {"ok": True}
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "fence.db"),
                          in_force=lambda: in_force["ok"])
    assert reserve(guard, "move", "lease:n1", unit="AHU-1", value=20.0) is None  # 1.0
    in_force["ok"] = False
    assert guard.fence("lease:n1") == cl.POLICY_CHANGED
    guard.release("lease:n1")
    in_force["ok"] = True
    assert reserve(guard, "move", "lease:n2", unit="AHU-1", value=20.0) is None  # 1.0 from 19.0
    guard.settle("lease:n2", ok=True)
    assert reserve(guard, "move", "lease:n3", unit="AHU-1", value=21.5) == cl.EXCEEDED  # 2.5


def test_release_after_a_settle_still_restores_the_value(tmp_path):
    guard = cl.LimitGuard(policy(), cl.LimitLedger(tmp_path / "order.db"))
    assert reserve(guard, "move", "lease:n1", unit="AHU-1", value=20.0) is None
    guard.settle("lease:n1", ok=False)
    guard.release("lease:n1")
    assert reserve(guard, "move", "lease:n2", unit="AHU-1", value=19.5) is None


def test_a_naive_iso_timestamp_is_read_as_utc(monkeypatch):
    import time as _time

    monkeypatch.setenv("TZ", "America/New_York")
    _time.tzset()
    try:
        assert cl._epoch("2027-01-15T10:00:00") == cl._epoch("2027-01-15T10:00:00+00:00")
    finally:
        monkeypatch.delenv("TZ")
        _time.tzset()


def test_the_key_separator_is_refused_in_every_part(guard):
    sep = "\x1f"
    assert guard.reserve(tenant="t", principal="p", tool_name="move",
                         arguments={"unit": f"AHU{sep}1", "value": 19.5},
                         operation_id="op", request_hash="h") == cl.RESOURCE_INVALID
    assert guard.reserve(tenant="t", principal="p", tool_name="pay",
                         arguments={"amount": 1, "cur": f"J{sep}PY"},
                         operation_id="op", request_hash="h") == cl.UNIT_INVALID
    assert reserve(guard, "pay", "A", principal=f"p{sep}x", amount=1, cur="JPY") == \
        cl.PRINCIPAL_INVALID
    assert guard.fence("op") is None  # nothing was recorded for a refused call
