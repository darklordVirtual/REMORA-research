# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Does REMORA stop the third 7000 payment against a 20000 budget?

The Horizon Shield #51 set-2 sequence (cases A, B and C: three payments of
7000 JPY-testnet under one 20000 budget) replayed through REMORA's execution
API: ``/v1/execution/assess``, ``/approve`` and ``/execute``, the governed
dispatcher and a sandboxed payment tool that records every call reaching it.

Without a declared limit REMORA executes all three (21000; NEGATIVE_RESULTS.md
section 97). With one, the third is refused before it reaches the tool, on
every path that leads there.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")

from tests.limits.harness import (  # noqa: E402
    PRINCIPAL,
    approve_and_execute,
    assess,
    call,
    make_client,
    ran,
    refused_at_dispatch,
    run,
)

UNIT = "JPY-testnet"


def policy(max_=20000, limit_id="hs51-set2", principal=PRINCIPAL):
    return {"schema": "remora-cumulative-limits/v1",
            "meters": {"transfer_payment": [{"quantity": "spend", "kind": "sum",
                                             "argument": "amount", "unit_argument": "unit"}]},
            "limits": [{"limit_id": limit_id, "tenant": "acme", "quantity": "spend",
                        "unit": UNIT, "max": max_, "principal": principal}]}


def pay(case, amount=7000, unit=UNIT, task_id="task-set2"):
    return call("transfer_payment", task_id=task_id, payee="responder-1", amount=amount,
                unit=unit, reference=f"hs51-musubi-2-{case}")


def paid(tmp_path):
    return sum(r["amount"] for r in ran(tmp_path))


def test_baseline_remora_as_shipped_pays_all_three(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, None)
    assert [run(client, pay(case))["executed"] for case in "ABC"] == [True, True, True]
    assert paid(tmp_path) == 21000


def test_with_a_declared_limit_c_is_refused_before_review(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    a, b, c = (run(client, pay(case)) for case in "ABC")
    assert a["executed"] and b["executed"]
    assert c == {"stage": "assess", "status": 409, "detail": "limit_exceeded"}
    assert [r["reference"] for r in ran(tmp_path)] == ["hs51-musubi-2-A", "hs51-musubi-2-B"]
    import servers.execution_api as exec_mod

    events = [e.payload for e in exec_mod._CHAIN.entries("acme")
              if e.payload.get("event") == "limit_refused"]
    assert [e["detail"] for e in events] == ["limit_exceeded"]


def test_c_approved_before_a_and_b_ran_is_refused_at_dispatch(monkeypatch, tmp_path):
    """The assess check is advisory; the reservation at dispatch holds."""
    client = make_client(monkeypatch, tmp_path, policy())
    items = {case: assess(client, pay(case)).json()["review_item_id"] for case in "ABC"}
    results = {case: approve_and_execute(client, items[case], pay(case)).json()
               for case in "ABC"}
    assert results["A"]["tool_execution"]["executed"] is True
    assert results["B"]["tool_execution"]["executed"] is True
    assert results["C"]["tool_execution"]["refusal_reason"] == "limit_exceeded"
    assert results["C"]["tool_execution"]["executed"] is False
    assert paid(tmp_path) == 14000


def test_concurrent_execution_never_passes_the_limit(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    pending = [(assess(client, pay(f"P{i}")).json()["review_item_id"], pay(f"P{i}"))
               for i in range(6)]
    for item_id, _ in pending:
        client.post("/v1/execution/approve", json={"item_id": item_id,
                                                    "approval_ttl_seconds": 600})
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda p: client.post("/v1/execution/execute",
                                            json={"item_id": p[0], "tool_call": p[1]}),
                      pending))
    assert len(ran(tmp_path)) == 2 and paid(tmp_path) == 14000


def test_the_spend_survives_a_restart(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    run(client, pay("A"))
    run(client, pay("B"))
    client = make_client(monkeypatch, tmp_path, policy())  # new guard, same ledger
    assert run(client, pay("C"))["detail"] == "limit_exceeded"


def test_a_new_task_does_not_reset_the_limit(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    run(client, pay("A", task_id="task-1"))
    run(client, pay("B", task_id="task-2"))
    assert run(client, pay("C", task_id="task-3"))["detail"] == "limit_exceeded"


def test_a_principal_without_a_limit_cannot_spend(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy(principal="someone-else"))
    assert run(client, pay("A"))["detail"] == "limit_undeclared"
    assert ran(tmp_path) == []


@pytest.mark.parametrize(("amount", "reason"), [
    # Not an integer at all: the signed contract (amount: integer) refuses it
    # before the limit preview runs.
    ("7000", "toolspec_arguments_schema_invalid"),
    (7000.5, "toolspec_arguments_schema_invalid"),
    (True, "toolspec_arguments_schema_invalid"),
    # An integer the contract admits but the meter cannot charge.
    (-7000, "limit_amount_invalid"),
    (0, "limit_amount_invalid"),
])
def test_an_amount_that_is_not_a_positive_integer_is_refused(monkeypatch, tmp_path, amount,
                                                              reason):
    client = make_client(monkeypatch, tmp_path, policy())
    r = assess(client, pay("A", amount=amount))
    assert (r.status_code, r.json()["detail"]) == (409, reason)


def test_another_unit_has_no_limit(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    assert run(client, pay("A", unit="JPY"))["detail"] == "limit_undeclared"


def test_a_limit_raised_in_place_is_refused(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    run(client, pay("A"))
    client = make_client(monkeypatch, tmp_path, policy(max_=10 ** 6))
    assert run(client, pay("B"))["detail"] == "limit_changed"
    client = make_client(monkeypatch, tmp_path, policy(max_=10 ** 6, limit_id="raised"))
    assert run(client, pay("B"))["executed"] is True  # a new limit is a new id


def test_dispatch_refuses_even_when_assess_did_not_see_it(monkeypatch, tmp_path):
    """Refusal at dispatch on its own: the assess check is skipped."""
    import servers.execution_api as exec_mod

    client = make_client(monkeypatch, tmp_path, policy())
    monkeypatch.setattr(exec_mod, "_limits_or_refuse", lambda *a: None)
    run(client, pay("A"))
    run(client, pay("B"))
    assert refused_at_dispatch(run(client, pay("C")), "limit_exceeded")


def test_half_a_configuration_refuses(monkeypatch, tmp_path):
    import servers.execution_api as exec_mod

    monkeypatch.setenv("REMORA_LIMITS_FILE", str(tmp_path / "limits.json"))
    monkeypatch.delenv("REMORA_LIMITS_LEDGER", raising=False)
    exec_mod._reset_tool_dispatcher()
    with pytest.raises(ValueError, match="set together"):
        exec_mod._limit_guard()
