# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The effect domain: where mediated effects run in a strict deployment (NTA-2 phase 3).

The effect domain holds the effect credentials and trusts nothing the tool
worker says beyond the lease it presents. It verifies the lease itself, checks
that the lease was actually dispatched, derives the effect authority from the
lease-bound capability set and its own copy of the tool's ceiling, and keeps
the per-execution budget and closure. A worker can therefore ask for anything
and receive only what the lease's authority allows.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from remora.capabilities import CapabilityRefusal, StaticEpochSource
from remora.enforcement.capability_mediator import CapabilityMediator, EffectState
from remora.enforcement.effect_capability import derive_effect_authority
from remora.enforcement.effect_client import RemoteEffectClient
from remora.enforcement.effect_domain import EffectDomain
from remora.enforcement.execution_context import ExecutionContext
from remora.enforcement.lease import ExecutionLease
from tests.capabilities.test_capability_mediation import CEILING, _parent


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "effect-domain-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _lease(capability_set, *, issued=None):
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-42",
        tool_name="report.generate", arguments={"month": "2026-09"},
        target_environment="prod", policy_bundle_hash="b1",
        issued_at=(issued or datetime.now(UTC)).isoformat(), capability_set=capability_set)


class World:
    def __init__(self, *, started=True, epochs=None, clock=None):
        self.calls: list[tuple[str, str]] = []
        self.dispatched: set[str] = set()
        self.started = started
        self.domain = EffectDomain(
            ceilings=lambda tool: CEILING if tool == CEILING.tool else None,
            executors={
                "database.read": lambda r, a: self.calls.append(("database.read", r)) or [1],
                "filesystem.read": lambda r, a: self.calls.append(("filesystem.read", r)) or "t",
            },
            execution_started=self._started, epochs=epochs,
            clock=clock or (lambda: datetime.now(UTC)))

    def _started(self, lease):
        if self.started == "raise":
            raise OSError("nonce store down")
        return self.started and lease.nonce in self.dispatched

    def open(self, capability_set=None):
        capability_set = capability_set or _parent()
        lease = _lease(capability_set)
        self.dispatched.add(lease.nonce)
        return lease, capability_set


def _request(lease, capability_set, capability, resource, arguments=None, **extra):
    return {"lease": lease.to_dict(), "capability_set": capability_set.to_dict(),
            "capability": capability, "resource": resource,
            "arguments": arguments or {}, **extra}


def test_an_effect_of_a_dispatched_lease_runs_on_the_canonical_resource():
    w = World()
    lease, cs = w.open()
    answer = w.domain.serve(_request(lease, cs, "database.read", "Database://Reporting-EU/m"))
    assert answer["state"] == "EXECUTED" and answer["result"] == [1]
    assert w.calls == [("database.read", "database://reporting-eu/m")]


def test_a_lease_that_was_never_dispatched_serves_nothing():
    w = World()
    cs = _parent()
    lease = _lease(cs)  # minted, never consumed
    answer = w.domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
    assert answer["refusal"] == "execution_not_started" and w.calls == []


def test_an_unanswerable_dispatch_check_refuses():
    w = World(started="raise")
    lease, cs = w.open()
    answer = w.domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
    assert answer["refusal"] == "execution_state_unverifiable" and w.calls == []


def test_a_tampered_lease_is_refused():
    w = World()
    lease, cs = w.open()
    wire = lease.to_dict()
    wire["tool_name"] = "email.send"
    answer = w.domain.serve({**_request(lease, cs, "database.read", "database://reporting-eu/m"),
                             "lease": wire})
    assert answer["refusal"] == "signature_invalid" and w.calls == []


def test_a_capability_set_other_than_the_leases_is_refused():
    w = World()
    lease, _ = w.open()
    answer = w.domain.serve(_request(lease, _parent(), "database.read", "database://reporting-eu/m"))
    assert answer["refusal"] == CapabilityRefusal.DIGEST_MISMATCH.value and w.calls == []


def test_the_worker_cannot_widen_the_ceiling():
    w = World()
    lease, cs = w.open()
    answer = w.domain.serve(_request(
        lease, cs, "filesystem.read", "secrets://production/key",
        ceiling=[{"capability": "filesystem.read", "resources": ["secrets://*"],
                  "purpose": "the worker's own idea"}]))
    assert answer["refusal"] == CapabilityRefusal.RESOURCE_NOT_AUTHORIZED.value and w.calls == []


def test_close_ends_the_execution_for_good():
    w = World()
    lease, cs = w.open()
    w.domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
    closed = w.domain.close({"lease": lease.to_dict()})
    assert closed["closed"] is True and closed["effects"] == 1
    again = w.domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
    assert again["refusal"] == CapabilityRefusal.CONTEXT_MISSING.value
    assert len(w.calls) == 1


def test_revoking_the_caller_set_revokes_the_effects():
    cs = _parent()
    w = World(epochs=StaticEpochSource(revoked_sets=frozenset({cs.capability_set_id})))
    lease, _ = w.open(cs)
    answer = w.domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
    assert answer["refusal"] == CapabilityRefusal.REVOKED.value and w.calls == []


def test_an_execution_ends_with_its_effect_authority_and_cannot_start_late():
    now = [datetime.now(UTC)]
    w = World(clock=lambda: now[0])
    lease, cs = w.open()
    now[0] = datetime.now(UTC)  # after the lease was issued
    first = w.domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
    assert first["state"] == "EXECUTED"
    now[0] += timedelta(seconds=61)  # past the effect authority's 60 s default
    later = w.domain.serve(_request(lease, cs, "filesystem.read", "workspace://reports/a.pdf"))
    assert later["refusal"] in {CapabilityRefusal.EXPIRED.value,
                                CapabilityRefusal.CONTEXT_MISSING.value}
    late_lease, late_cs = w.open()
    now[0] = datetime.fromisoformat(late_lease.expires_at) + timedelta(seconds=1)
    refused = w.domain.serve(_request(late_lease, late_cs, "database.read",
                                      "database://reporting-eu/m"))
    assert refused["refusal"] == "lease_expired"
    assert len(w.calls) == 1


@pytest.mark.parametrize("request_", [{}, {"lease": "x"}, {"lease": {}, "capability": 1}])
def test_a_malformed_request_is_refused(request_):
    assert World().domain.serve(request_)["refusal"] == "request_malformed"


class TestTheClient:
    def _worker_mediator(self, w, lease, cs, post=None):
        client = RemoteEffectClient(post=post or (lambda path, body: (
            w.domain.serve(body) if path == "/v1/execution/effects" else w.domain.close(body))))
        authority = derive_effect_authority(cs, tool_name="report.generate", ceiling=CEILING,
                                            now=datetime.now(UTC))
        context = ExecutionContext.for_dispatch(
            tool_name="report.generate", capability_set=cs, proposal_id="p",
            policy_bundle_hash="b1", toolspec_hash="", lease_digest=lease.digest())
        executors = client.executors_for(lease, cs, [c.capability for c in CEILING.capabilities])
        return CapabilityMediator(context, authority, executors=executors), client

    def test_a_round_trip_executes_in_the_effect_domain(self):
        w = World()
        lease, cs = w.open()
        mediator, _ = self._worker_mediator(w, lease, cs)
        effect = mediator.invoke("database.read", "database://reporting-eu/m")
        assert effect.executed and effect.result == [1]
        assert w.calls == [("database.read", "database://reporting-eu/m")]

    def test_a_domain_refusal_is_a_refusal_in_the_worker(self):
        w = World()
        cs = _parent()
        lease = _lease(cs)  # not dispatched
        mediator, _ = self._worker_mediator(w, lease, cs)
        effect = mediator.invoke("database.read", "database://reporting-eu/m")
        assert effect.state is EffectState.REFUSED and effect.refusal == "execution_not_started"

    def test_a_lost_transport_leaves_the_effect_unknown(self):
        w = World()
        lease, cs = w.open()

        def down(path, body):
            raise ConnectionError("effect domain unreachable")

        mediator, _ = self._worker_mediator(w, lease, cs, post=down)
        effect = mediator.invoke("database.read", "database://reporting-eu/m")
        assert effect.state is EffectState.UNKNOWN

    def test_close_reaches_the_domain(self):
        w = World()
        lease, cs = w.open()
        _, client = self._worker_mediator(w, lease, cs)
        client.close(lease)
        again = w.domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
        assert again["refusal"] == CapabilityRefusal.CONTEXT_MISSING.value


class TestDurability:
    """Closure and budget survive a restart of the effect domain."""

    def _domain(self, ledger, calls, max_effects=64):
        from remora.enforcement.effect_domain import EffectDomain

        return EffectDomain(
            ceilings=lambda tool: CEILING if tool == CEILING.tool else None,
            executors={"database.read": lambda r, a: calls.append(r) or [1]},
            execution_started=lambda lease: True, ledger=ledger, max_effects=max_effects)

    def test_a_closed_execution_stays_closed_after_a_restart(self):
        from remora.enforcement.nonce_store import InMemoryNonceStore

        ledger, calls = InMemoryNonceStore(), []
        cs = _parent()
        lease = _lease(cs)
        first = self._domain(ledger, calls)
        first.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
        first.close({"lease": lease.to_dict()})
        restarted = self._domain(ledger, calls)
        answer = restarted.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
        assert answer["refusal"] == CapabilityRefusal.CONTEXT_MISSING.value
        assert len(calls) == 1

    def test_the_budget_continues_across_a_restart(self):
        from remora.enforcement.nonce_store import InMemoryNonceStore

        ledger, calls = InMemoryNonceStore(), []
        cs = _parent()
        lease = _lease(cs)
        self._domain(ledger, calls, max_effects=2).serve(
            _request(lease, cs, "database.read", "database://reporting-eu/a"))
        restarted = self._domain(ledger, calls, max_effects=2)
        ok = restarted.serve(_request(lease, cs, "database.read", "database://reporting-eu/b"))
        over = restarted.serve(_request(lease, cs, "database.read", "database://reporting-eu/c"))
        assert ok["state"] == "EXECUTED"
        assert over["refusal"] == CapabilityRefusal.EFFECT_BUDGET_EXHAUSTED.value
        assert calls == ["database://reporting-eu/a", "database://reporting-eu/b"]

    def test_an_unavailable_ledger_refuses_rather_than_running(self):
        class Down:
            def try_consume(self, nonce, *, tenant_id):
                raise OSError("down")

            def consumed(self, nonce, *, tenant_id):
                raise OSError("down")

        calls: list = []
        cs = _parent()
        lease = _lease(cs)
        answer = self._domain(Down(), calls).serve(
            _request(lease, cs, "database.read", "database://reporting-eu/m"))
        assert answer["refusal"] == "execution_state_unverifiable" and calls == []


class TestRefusalPaths:
    def test_a_malformed_capability_set_is_refused(self):
        w = World()
        lease, cs = w.open()
        body = {**_request(lease, cs, "database.read", "database://reporting-eu/m"),
                "capability_set": {"nonsense": True}}
        assert w.domain.serve(body)["refusal"] == CapabilityRefusal.DIGEST_MISMATCH.value

    def test_an_unreadable_ceiling_refuses(self):
        from remora.enforcement.effect_domain import EffectDomain

        def broken(tool):
            raise OSError("bundle gone")

        domain = EffectDomain(ceilings=broken, executors={}, execution_started=lambda _lease: True)
        cs = _parent()
        lease = _lease(cs)
        answer = domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
        assert answer["refusal"] == "downstream_ceiling_unavailable"

    def test_an_undeclared_tool_gets_no_effect(self):
        from remora.enforcement.effect_domain import EffectDomain

        domain = EffectDomain(ceilings=lambda tool: None, executors={
            "database.read": lambda r, a: 1}, execution_started=lambda _lease: True)
        cs = _parent()
        lease = _lease(cs)
        answer = domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
        assert answer["refusal"] == CapabilityRefusal.NOT_ALLOWED.value

    def test_a_parent_at_the_depth_cap_derives_nothing(self):
        from remora.capabilities import delegate
        from remora.capabilities.delegation import MAX_DELEGATION_DEPTH

        chain = _parent()
        now = datetime.now(UTC)
        for n in range(MAX_DELEGATION_DEPTH):
            chain = delegate(chain, delegatee="agent-42", tools=["report.generate"],
                             purpose="relay", now=now, transitive=True)
        w = World()
        lease = _lease(chain)
        w.dispatched.add(lease.nonce)
        answer = w.domain.serve(_request(lease, chain, "database.read",
                                         "database://reporting-eu/m"))
        assert answer["refusal"] == CapabilityRefusal.DELEGATION_DENIED.value

    def test_a_ledger_that_fails_mid_execution_refuses_the_effect(self):
        from remora.enforcement.effect_domain import EffectDomain

        class Flaky:
            def consumed(self, nonce, *, tenant_id):
                return False

            def try_consume(self, nonce, *, tenant_id):
                raise OSError("down")

        calls: list = []
        domain = EffectDomain(ceilings=lambda t: CEILING, executors={
            "database.read": lambda r, a: calls.append(r)},
            execution_started=lambda _lease: True, ledger=Flaky())
        cs = _parent()
        lease = _lease(cs)
        answer = domain.serve(_request(lease, cs, "database.read", "database://reporting-eu/m"))
        assert answer["refusal"] == "execution_state_unverifiable" and calls == []
        closed = domain.close({"lease": lease.to_dict()})
        # The ledger fails before an execution opens: recording the session
        # deadline is its first write (code review of 898758f, finding 2), so
        # no mediator exists and no effect record was made.
        assert closed == {"closed": True, "durable": False, "effects": 0}

    def test_close_refuses_a_malformed_or_forged_lease(self):
        w = World()
        malformed = w.domain.close({})
        assert malformed["refusal"] == "request_malformed"
        lease, _ = w.open()
        wire = lease.to_dict()
        wire["tool_name"] = "email.send"
        forged = w.domain.close({"lease": wire})
        assert forged["refusal"] == "lease_not_authentic"


class TestHttpTransport:
    def _server(self, handler_body):
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers["Content-Length"])
                body = _json.loads(self.rfile.read(length))
                seen.append((self.path, self.headers.get("Authorization"), body))
                payload = _json.dumps(handler_body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        seen: list = []
        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, seen

    def test_the_http_post_round_trips_with_its_bearer(self):
        from remora.enforcement.effect_client import http_post

        server, seen = self._server({"state": "EXECUTED", "result": [3]})
        try:
            post = http_post(f"http://127.0.0.1:{server.server_port}", token="t-1")
            assert post("/v1/execution/effects", {"x": 1}) == {"state": "EXECUTED", "result": [3]}
            assert seen == [("/v1/execution/effects", "Bearer t-1", {"x": 1})]
        finally:
            server.shutdown()

    def test_an_unreachable_domain_is_unavailable_not_refused(self):
        from remora.enforcement.effect_client import EffectDomainUnavailable, http_post

        post = http_post("http://127.0.0.1:9", timeout=0.5)
        with pytest.raises(EffectDomainUnavailable):
            post("/v1/execution/effects", {})

    def test_a_non_http_endpoint_is_refused(self):
        from remora.enforcement.effect_client import http_post

        with pytest.raises(ValueError):
            http_post("file:///etc/passwd")

    def test_the_env_configured_post(self, monkeypatch):
        from remora.enforcement.effect_client import http_post_from_env

        server, seen = self._server({"state": "REFUSED", "refusal": "x"})
        try:
            monkeypatch.setenv("REMORA_EFFECT_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
            monkeypatch.setenv("REMORA_EFFECT_TOKEN", "env-token")
            http_post_from_env()("/v1/execution/effects", {})
            assert seen[0][1] == "Bearer env-token"
        finally:
            server.shutdown()

    def test_an_unexpected_state_is_unknown(self):
        from remora.enforcement.effect_client import EffectDomainUnavailable, RemoteEffectClient

        cs = _parent()
        run = RemoteEffectClient(post=lambda p, b: {"state": "MAYBE"}).executors_for(
            _lease(cs), cs, ["database.read"])["database.read"]
        with pytest.raises(EffectDomainUnavailable):
            run("database://reporting-eu/m", {})


def test_a_well_formed_lease_with_a_malformed_capability_is_refused():
    w = World()
    lease, cs = w.open()
    body = {**_request(lease, cs, "database.read", "database://reporting-eu/m"), "capability": 7}
    assert w.domain.serve(body)["refusal"] == "request_malformed" and w.calls == []


# ── code review of 898758f: closure and expiry across workers ────────────────

def _durable(db, clock, calls, dispatched):
    from remora.enforcement.nonce_store import DurableNonceStore

    return EffectDomain(
        ceilings=lambda tool: CEILING if tool == CEILING.tool else None,
        executors={"database.read": lambda r, a: calls.append(r) or [1]},
        execution_started=lambda lease: lease.nonce in dispatched,
        ledger=DurableNonceStore(db_path=db), clock=lambda: clock[0])


class TestCloseAndExpiryAcrossWorkers:
    """Finding 1: a close on one worker stops a second worker that already has
    the execution open. Finding 2: expiry is terminal, for one worker, a second
    worker and after a restart; a cache miss never grants a fresh lifetime."""

    def _world(self, tmp_path):
        clock = [datetime.now(UTC)]
        cs = _parent(now=clock[0])
        lease = _lease(cs, issued=clock[0])
        calls: list[str] = []
        dispatched = {lease.nonce}
        db = str(tmp_path / "effects.db")
        request = _request(lease, cs, "database.read", "database://reporting-eu/m")
        return clock, lease, request, calls, lambda: _durable(db, clock, calls, dispatched)

    def test_close_on_one_worker_stops_an_already_open_second_worker(self, tmp_path):
        clock, lease, request, calls, worker = self._world(tmp_path)
        a, b = worker(), worker()
        assert a.serve(request)["state"] == "EXECUTED"
        assert b.serve(request)["state"] == "EXECUTED"
        assert a.close({"lease": lease.to_dict()})["durable"] is True
        assert a.serve(request)["state"] == "REFUSED"
        after = b.serve(request)
        assert after["state"] == "REFUSED"
        assert after["refusal"] == CapabilityRefusal.CONTEXT_MISSING.value
        assert len(calls) == 2

    def test_expiry_is_terminal_on_the_same_worker(self, tmp_path):
        clock, _lease_, request, calls, worker = self._world(tmp_path)
        d = worker()
        assert d.serve(request)["state"] == "EXECUTED"
        clock[0] += timedelta(seconds=61)
        assert d.serve(request)["state"] == "REFUSED"
        clock[0] += timedelta(seconds=1)
        assert d.serve(request)["state"] == "REFUSED"
        assert len(calls) == 1

    def test_expiry_is_terminal_after_a_restart(self, tmp_path):
        clock, _lease_, request, calls, worker = self._world(tmp_path)
        assert worker().serve(request)["state"] == "EXECUTED"
        clock[0] += timedelta(seconds=62)
        assert worker().serve(request)["state"] == "REFUSED"  # a fresh process, a cache miss
        assert len(calls) == 1

    def test_a_worker_that_joins_later_inherits_the_deadline(self, tmp_path):
        clock, _lease_, request, calls, worker = self._world(tmp_path)
        assert worker().serve(request)["state"] == "EXECUTED"
        clock[0] += timedelta(seconds=30)
        late = worker()
        assert late.serve(request)["state"] == "EXECUTED"
        clock[0] += timedelta(seconds=31)  # 61 s after the first effect, 31 s after the join
        assert late.serve(request)["state"] == "REFUSED"

    def test_the_recorded_deadline_is_never_later_than_the_derived_one(self, tmp_path):
        clock, _lease_, request, calls, worker = self._world(tmp_path)
        d = worker()
        assert d.serve(request)["state"] == "EXECUTED"
        mediator = next(iter(d._open.values()))
        expires = datetime.fromisoformat(mediator.authority.expires_at)
        assert expires <= clock[0] + timedelta(seconds=60)
        assert expires > clock[0] + timedelta(seconds=54)  # rounded down to a 5 s grid at most


def test_without_a_ledger_expiry_is_terminal_until_the_lease_ends():
    clock = [datetime.now(UTC)]
    w = World(clock=lambda: clock[0])
    cs = _parent(now=clock[0])
    lease = _lease(cs, issued=clock[0])
    w.dispatched.add(lease.nonce)
    request = _request(lease, cs, "database.read", "database://reporting-eu/m")
    assert w.domain.serve(request)["state"] == "EXECUTED"
    clock[0] += timedelta(seconds=61)
    assert w.domain.serve(request)["state"] == "REFUSED"
    clock[0] += timedelta(seconds=1)
    assert w.domain.serve(request)["state"] == "REFUSED"
    assert len(w.calls) == 1
