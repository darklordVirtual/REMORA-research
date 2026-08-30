# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Principal revocation survives a restart, a second worker, and an outage.

Found by the AGNTCY crosswalk review: ``ReviewQueue`` held revoked
principals in a dict on the instance, and the server builds one queue per
tenant per process. The chain recorded ``principal_revoked`` either way, so
the audit trail of an affected deployment reads correct while enforcement
had already forgotten.

The control in every durability test here is the in-memory store: it is the
thing whose restart behaviour must differ from the durable one.
"""
from __future__ import annotations

import pytest

from remora.governance.revocation_store import (
    DurableRevocationStore,
    InMemoryRevocationStore,
    RevocationStore,
    RevocationStoreUnavailable,
)


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "revocations.sqlite3")


class TestDurability:
    """The defect, stated as a test that fails against a process-local dict."""

    def test_a_revocation_survives_a_restart(self, db_path):
        DurableRevocationStore(db_path=db_path).revoke("alice", tenant_id="acme")

        # A new instance is what a restarted process, or a replacement
        # container, gets. It shares nothing with the one above but the file.
        restarted = DurableRevocationStore(db_path=db_path)
        assert restarted.is_revoked("alice", tenant_id="acme") is True

    def test_a_second_worker_sees_the_revocation(self, db_path):
        worker_one = DurableRevocationStore(db_path=db_path)
        worker_two = DurableRevocationStore(db_path=db_path)

        worker_one.revoke("alice", tenant_id="acme", reason="left the org")

        assert worker_two.is_revoked("alice", tenant_id="acme") is True

    def test_the_in_memory_store_is_the_control(self):
        """Pins what was wrong, so a regression to it is visible."""

        first = InMemoryRevocationStore()
        first.revoke("alice", tenant_id="acme")

        second = InMemoryRevocationStore()
        assert second.is_revoked("alice", tenant_id="acme") is False

    def test_revoking_twice_is_not_an_error(self, db_path):
        store = DurableRevocationStore(db_path=db_path)
        store.revoke("alice", tenant_id="acme", reason="first")
        store.revoke("alice", tenant_id="acme", reason="second")

        assert store.is_revoked("alice", tenant_id="acme") is True


class TestTenantScope:
    def test_revoking_in_one_tenant_does_not_revoke_in_another(self, db_path):
        store = DurableRevocationStore(db_path=db_path)
        store.revoke("alice", tenant_id="acme")

        assert store.is_revoked("alice", tenant_id="acme") is True
        assert store.is_revoked("alice", tenant_id="globex") is False

    @pytest.mark.parametrize("store", [
        InMemoryRevocationStore(),
        DurableRevocationStore(db_path="ignored-by-the-value-check"),
    ])
    @pytest.mark.parametrize("principal,tenant", [
        ("", "acme"), ("   ", "acme"), ("alice", ""), ("alice", "   "),
    ])
    def test_an_unscoped_revocation_is_refused(self, store, principal, tenant):
        with pytest.raises(ValueError):
            store.revoke(principal, tenant_id=tenant)
        with pytest.raises(ValueError):
            store.is_revoked(principal, tenant_id=tenant)


class TestFailClosed:
    """An unreachable store is neither answer. It raises."""

    @pytest.fixture()
    def unreachable(self, tmp_path):
        # A path inside a file, so sqlite cannot open it. Not a mock: the
        # point is that a real backend failure produces the raise.
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        return DurableRevocationStore(db_path=str(blocker / "db.sqlite3"))

    def test_reading_an_unreachable_store_raises(self, unreachable):
        with pytest.raises(RevocationStoreUnavailable):
            unreachable.is_revoked("alice", tenant_id="acme")

    def test_writing_to_an_unreachable_store_raises(self, unreachable):
        with pytest.raises(RevocationStoreUnavailable):
            unreachable.revoke("alice", tenant_id="acme")

    def test_unavailable_is_never_reported_as_not_revoked(self, unreachable):
        """The whole point: an outage must not become a way around revocation.

        A store that returned False here would let a withdrawn approver keep
        executing for as long as the backend was down.
        """
        try:
            answer = unreachable.is_revoked("alice", tenant_id="acme")
        except RevocationStoreUnavailable:
            return
        pytest.fail(f"unavailable store answered {answer!r} instead of raising")


class TestProtocolConformance:
    @pytest.mark.parametrize("store", [
        InMemoryRevocationStore(),
        DurableRevocationStore(db_path="some/path.sqlite3"),
    ])
    def test_both_stores_satisfy_the_protocol(self, store):
        assert isinstance(store, RevocationStore)

    def test_a_durable_store_with_no_backend_is_refused(self):
        """An unconfigured durable store would be memory wearing the name."""

        with pytest.raises(ValueError, match="needs one of"):
            DurableRevocationStore()

    def test_an_in_memory_sqlite_path_is_refused(self):
        """``:memory:`` is per-connection, so it is not durable at all."""

        with pytest.raises(Exception):
            DurableRevocationStore(db_path=":memory:")


# --------------------------------------------------------------------------
# The re-gate. The store above is only worth having if the gate reads it.
# --------------------------------------------------------------------------


def _queue_and_item(**kwargs):
    from datetime import timedelta

    from remora.governance.review_queue import ReviewQueue
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionAction

    q = ReviewQueue(tenant_id="acme", **kwargs)
    obs = PolicyObservation(
        question="update_work_order(order=WO-1)",
        risk_tier="high",
        action_type="production_write",
        tool_call_hash="h" * 64,
    )
    item = q.enqueue(obs, DecisionAction.VERIFY, queue_ttl=timedelta(hours=1))
    return q, item.item_id, obs


class TestTheReGateReadsTheStore:
    def test_a_revocation_from_another_worker_stops_execution(self, db_path):
        """The defect, end to end.

        Worker one revokes. Worker two holds the approval and has never
        heard of the revocation except through the shared store. Before this
        change worker two executed.
        """
        from datetime import timedelta

        from remora.governance.review_queue import ExecutionDecision

        shared = DurableRevocationStore(db_path=db_path)
        worker_two, item_id, obs = _queue_and_item(revocation_store=shared)
        worker_two.approve(
            item_id, approver="alice", approval_ttl=timedelta(minutes=5)
        )

        DurableRevocationStore(db_path=db_path).revoke("alice", tenant_id="acme")

        outcome = worker_two.execute(item_id, obs)
        assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED

    def test_another_tenant_revocation_does_not_stop_execution(self, db_path):
        from datetime import timedelta

        from remora.governance.review_queue import ExecutionDecision

        shared = DurableRevocationStore(db_path=db_path)
        q, item_id, obs = _queue_and_item(revocation_store=shared)
        q.approve(item_id, approver="alice", approval_ttl=timedelta(minutes=5))

        shared.revoke("alice", tenant_id="globex")

        assert q.execute(item_id, obs).decision is ExecutionDecision.EXECUTE

    def test_an_unreachable_store_refuses_rather_than_executing(self, tmp_path):
        """Fail closed at the gate, and without destroying the approval.

        Raising leaves the approval intact for a retry. Voiding it would
        turn a transient outage into a permanently dead authorization, the
        same error as burning an unspent nonce.
        """
        from datetime import timedelta

        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        broken = DurableRevocationStore(db_path=str(blocker / "db.sqlite3"))

        # Approve through a working store, then lose the backend.
        q, item_id, obs = _queue_and_item(
            revocation_store=InMemoryRevocationStore()
        )
        q.approve(item_id, approver="alice", approval_ttl=timedelta(minutes=5))
        q._revocations = broken

        with pytest.raises(RevocationStoreUnavailable):
            q.execute(item_id, obs)

    def test_the_chain_does_not_record_a_revocation_the_store_refused(
        self, tmp_path
    ):
        """Ordering: store first, chain second.

        The defect this replaces was an audit entry for a revocation that
        enforcement had forgotten. Writing the chain when the store failed
        would recreate exactly that.
        """
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        broken = DurableRevocationStore(db_path=str(blocker / "db.sqlite3"))

        q, _item_id, _obs = _queue_and_item(revocation_store=broken)

        with pytest.raises(RevocationStoreUnavailable):
            q.revoke_principal("alice", reason="left the org")

        assert not any(e.kind == "principal_revoked" for e in q.events)


class TestJoiningAnAmbientTransaction:
    """The re-gate reads this store from inside the review-state transaction.

    Opening a second connection to the same SQLite file blocks on the writer
    already holding it, which surfaced as ``database is locked`` against the
    durability suite. The store therefore joins the caller's transaction when
    there is one.
    """

    def test_a_second_connection_would_have_deadlocked(self, db_path):
        """Pins the mechanism, so the provider is not removed as ceremony."""
        import sqlite3

        holder = sqlite3.connect(db_path, timeout=0.2)
        holder.execute("CREATE TABLE t (x INTEGER)")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO t VALUES (1)")

        unaware = DurableRevocationStore(db_path=db_path)
        with pytest.raises(RevocationStoreUnavailable, match="locked"):
            unaware.revoke("alice", tenant_id="acme")

        joined = DurableRevocationStore(
            db_path=db_path, connection_provider=lambda: holder
        )
        joined.revoke("alice", tenant_id="acme")
        assert joined.is_revoked("alice", tenant_id="acme") is True
        holder.commit()
        holder.close()

    def test_the_store_does_not_commit_the_callers_transaction(self, db_path):
        """A commit here would publish half of the caller's work."""
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO t VALUES (1)")

        store = DurableRevocationStore(
            db_path=db_path, connection_provider=lambda: conn
        )
        store.revoke("alice", tenant_id="acme")

        conn.rollback()
        conn.close()

        # The caller rolled back, so neither their row nor the revocation
        # survives. The store must not have made that decision for them.
        after = sqlite3.connect(db_path)
        assert after.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
        after.close()

    def test_a_provider_returning_none_falls_back_to_its_own_connection(
        self, db_path
    ):
        store = DurableRevocationStore(
            db_path=db_path, connection_provider=lambda: None
        )
        store.revoke("alice", tenant_id="acme")
        assert DurableRevocationStore(db_path=db_path).is_revoked(
            "alice", tenant_id="acme"
        ) is True
