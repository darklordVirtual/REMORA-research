# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A lost claim must not dispatch; the executor must not serve authority routes.

RMR-009 and RMR-013 from the external forensic review. Both are the same shape:
a separation that was written down and not enforced.

RMR-009. Both call sites in ``remora/execution/service.py`` read

    # FT-02: claim the intent before anything can take effect (exclusive).
    if intent is not None:
        outbox().claim(intent.outbox_id, worker_id=worker_id)

and discarded the return value. ``claim`` returns ``None`` when another worker
already holds the row, so a lost race went on to dispatch the same intent and
then settled over the winner's record. The exclusivity the outbox exists to
provide was a comment.

RMR-013. The custody split gave the execution container its own credentials and
only the public verification key, but it kept serving the whole router --
assess, approve, execute, reject, the audit reader. A compromise there could
authorize work as well as perform it, which is the property the split claims to
remove.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement.outbox import OutboxState, SQLiteExecutionOutbox  # noqa: E402
from remora.execution import service  # noqa: E402


class _FakeChain:
    def __init__(self) -> None:
        self.appended: list[dict] = []

    def append(self, tenant, record):
        self.appended.append(record)
        return type("Entry", (), {"sequence_no": len(self.appended),
                                  "entry_hash": "h" * 64})()


def _intent(outbox, proposal="prop-1"):
    return outbox.record_intent(
        proposal_id=proposal, tenant_id="acme", item_id="item-1",
        tool_name="wo_close", tool_call_hash="c" * 64, grant_jti="jti-1")


# -- RMR-009: the claim is exclusive, and the loser does not dispatch --------

def test_the_winner_claims_and_the_loser_is_told_so(tmp_path):
    outbox = SQLiteExecutionOutbox(str(tmp_path / "o.db"))
    row = _intent(outbox)

    assert service._claim_or_none(lambda: outbox, row, worker_id="w1") is True
    assert service._claim_or_none(lambda: outbox, row, worker_id="w2") is False


def test_no_intent_means_nothing_to_claim():
    """The compatibility path: without a durable intent there is no race."""
    assert service._claim_or_none(lambda: None, None, worker_id="w1") is True


def test_a_lost_claim_classifies_as_refused_not_unknown(tmp_path):
    """This worker watched itself not act, which it can assert first-hand.

    REFUSED rather than UNKNOWN is correct here and only here: the dispatch
    never began in THIS process. It says nothing about the winner's effect.
    """
    from remora.execution.outcome import DispatchOutcome, classify_outcome

    outbox = SQLiteExecutionOutbox(str(tmp_path / "o.db"))
    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w1")

    response = service._claim_lost_response(
        {}, chain=_FakeChain(), tenant="acme", principal="p",
        proposal_id="prop-1", item_id="item-1", tool_call_hash="c" * 64,
        grant_jti="jti-1", intent_sequence_no=7)

    outcome = classify_outcome(response["tool_execution"])
    assert outcome is DispatchOutcome.REFUSED
    assert response["tool_execution"]["refusal_reason"] == "outbox_claim_lost"


def test_the_loser_does_not_settle_the_winners_row(tmp_path):
    """The row belongs to whoever claimed it.

    Settling here would overwrite the record of the execution that actually
    happens, and the overwrite would look like a normal terminal.
    """
    outbox = SQLiteExecutionOutbox(str(tmp_path / "o.db"))
    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w1")

    service._claim_lost_response(
        {}, chain=_FakeChain(), tenant="acme", principal="p",
        proposal_id="prop-1", item_id="item-1", tool_call_hash="c" * 64,
        grant_jti="jti-1", intent_sequence_no=7)

    still = outbox.get(row.outbox_id)
    assert still.state is OutboxState.DISPATCHING
    assert still.worker_id == "w1"


def test_the_loss_is_audited_rather_than_silent():
    """A gap in the chain would read as a lost event, not as a refusal."""
    chain = _FakeChain()
    service._claim_lost_response(
        {}, chain=chain, tenant="acme", principal="p", proposal_id="prop-1",
        item_id="item-1", tool_call_hash="c" * 64, grant_jti="jti-1",
        intent_sequence_no=7)

    (record,) = chain.appended
    assert record["event"] == "execution_result"
    assert record["tool_executed"] is False
    assert record["state_unknown"] is False
    assert record["tool_refusal_reason"] == "outbox_claim_lost"
    assert record["intent_sequence_no"] == 7


def test_neither_call_site_discards_the_claim_result():
    """The regression that made this necessary, pinned at the source.

    Both sites called claim() as a statement. If one starts doing that again
    the exclusivity is gone with no other test failing.
    """
    import inspect

    for line in inspect.getsource(service).splitlines():
        stripped = line.strip()
        if stripped.startswith(("outbox().claim(", "outbox_factory().claim(")):
            pytest.fail("claim() result discarded: " + stripped)


# -- RMR-013: the executor serves one path ----------------------------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import servers.api as api_mod
    return TestClient(api_mod.app)


def test_default_is_authority_so_an_unconfigured_deployment_is_unchanged(
        monkeypatch):
    import servers.execution_api as ex

    monkeypatch.delenv("REMORA_EXECUTION_DOMAIN_ROLE", raising=False)
    assert ex._execution_domain() == "authority"
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "")
    assert ex._execution_domain() == "authority"


def test_an_unrecognised_role_is_a_configuration_error(monkeypatch):
    """Guessing which half was meant is the wrong way to resolve a typo."""
    import servers.execution_api as ex

    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "excutor")
    with pytest.raises(RuntimeError, match="neither"):
        ex._execution_domain()


def test_the_executor_refuses_the_authority_routes(client, monkeypatch):
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    for path in ("/v1/execution/assess", "/v1/execution/approve",
                 "/v1/execution/execute", "/v1/execution/execute-accepted",
                 "/v1/execution/reject"):
        assert client.post(path, json={}).status_code == 404, path
    for path in ("/v1/execution/proposals/x", "/v1/execution/audit/verify",
                 "/v1/execution/proposals/x/evidence"):
        assert client.get(path).status_code == 404, path


def test_the_executor_still_serves_dispatch_leased(client, monkeypatch):
    """Refusing everything would be a safe executor and a useless one."""
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    # Unauthenticated and unvalidated, so anything but 404 proves the domain
    # guard let the request through to the route's own checks.
    assert client.post("/v1/execution/dispatch-leased",
                       json={}).status_code != 404


def test_the_allowlist_matches_exactly_not_by_prefix(client, monkeypatch):
    """The unanchored-allowlist defect, not repeated.

    A startswith test here would admit /dispatch-leased-anything, which is how
    the read-only SQL check failed (NEGATIVE_RESULTS section 51).
    """
    import servers.execution_api as ex
    from fastapi import HTTPException

    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")

    # Asked of the guard directly. Going through the client would pass whether
    # the guard is anchored or not, because no route serves these paths -- the
    # 404 would be FastAPI's, not the guard's, and the test would prove
    # nothing.
    ex._enforce_execution_domain(_request("/v1/execution/dispatch-leased"))
    for path in ("/v1/execution/dispatch-leased-anything",
                 "/v1/execution/dispatch-leased/sub",
                 "/prefix/v1/execution/dispatch-leased"):
        with pytest.raises(HTTPException) as raised:
            ex._enforce_execution_domain(_request(path))
        assert raised.value.status_code == 404, path


def _request(path: str):
    """The smallest thing the guard reads: a request with a URL path."""
    from starlette.requests import Request

    return Request({"type": "http", "method": "POST", "path": path,
                    "headers": [], "query_string": b""})


def test_the_authority_serves_everything_it_did_before(client, monkeypatch):
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "authority")
    # 404 would mean the guard fired; any other status is the route's own.
    assert client.post("/v1/execution/assess", json={}).status_code != 404


def test_a_new_route_is_covered_without_being_listed():
    """The guard is attached to the router, not to each route.

    A per-route decorator is a list a new endpoint silently fails to join, and
    that failure mode is an authority route quietly reachable from the
    execution domain.
    """
    import servers.execution_api as ex

    names = [d.dependency.__name__ for d in ex.router.dependencies]
    assert "_enforce_execution_domain" in names
