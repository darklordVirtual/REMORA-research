# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The signed spec identity is checked at the final PEP (RMR-004).

``ExecutionLease`` has always carried ``toolspec_hash`` and
``toolspec_version``, and ``ExecutionLease.verify`` has always been able to
compare them. Nothing ever supplied them at dispatch. The identity was
therefore inside the signature -- unforgeable, and never read: the lease proved
which spec was approved, and the dispatcher never compared it to the spec it
was about to run.

The gap is exactly the window the identity exists to cover. Between issuing the
lease and dispatching under it, the bundle can be replaced, and in the custody
split the executor's bundle is a different file on a different container from
the authority's. A spec that moved in that window meant the action about to run
was not the action that was reviewed, and nothing said so.

What this does NOT close is recorded at the bottom: ``verify_callable`` and
``verify_credential_scope`` still have no non-test caller, and the tests pin
that so it cannot change quietly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import UTC, datetime  # noqa: E402

from remora.enforcement.lease import (  # noqa: E402
    ExecutionLease,
    GovernedToolDispatcher,
)

BUNDLE = "b" * 64


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """An unsigned lease is refused before anything else is checked.

    Signing is not what these tests are about, but without it every one of
    them would pass for the wrong reason.
    """
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "toolspec-binding-key")


def _dispatcher(identity=None):
    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    d.register("wo_close", lambda args: {"ok": True})
    if identity is not None:
        d.bind_toolspec_identity(identity)
    return d


def _lease(*, toolspec_hash="spec-hash-1", toolspec_version=3):
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name="wo_close", arguments={"id": 7}, target_environment="prod",
        policy_bundle_hash=BUNDLE,
        issued_at=datetime.now(UTC).isoformat(),
        tool_contract_bundle_hash="t" * 64, intent_authority_hash="i" * 64,
        toolspec_hash=toolspec_hash, toolspec_version=toolspec_version,
        proposal_id="prop-1", grant_jti="jti-1",
    )


def _dispatch(dispatcher, lease):
    return dispatcher.dispatch(
        lease, "wo_close", {"id": 7}, tenant_id="acme",
        target_environment="prod", actor_identity="agent-1")


# -- the binding ------------------------------------------------------------

def test_a_matching_spec_executes():
    result = _dispatch(
        _dispatcher(lambda name: ("spec-hash-1", 3)), _lease())
    assert result.executed is True


def test_a_spec_that_moved_between_approval_and_dispatch_refuses():
    """The headline case. Executed before this change."""
    result = _dispatch(
        _dispatcher(lambda name: ("spec-hash-2", 3)), _lease())
    assert result.executed is False
    assert result.refusal_reason == "toolspec_hash_mismatch"


def test_a_version_bump_alone_refuses():
    """Same content hash claimed, different version: still a different spec.

    Checking only the hash would let a re-versioned bundle through if the
    hashing ever became content-only.
    """
    result = _dispatch(
        _dispatcher(lambda name: ("spec-hash-1", 4)), _lease())
    assert result.executed is False
    assert result.refusal_reason == "toolspec_version_mismatch"


def test_no_bundle_configured_stays_permitted():
    """The unenforced research path. Reported as enforced=False elsewhere.

    Turning an absent bundle into a refusal would break every library and
    research use of the dispatcher, none of which claims spec enforcement.
    """
    assert _dispatch(_dispatcher(lambda name: None), _lease()).executed is True


def test_an_unbound_dispatcher_behaves_as_before():
    """No resolver at all: unchanged. The compatibility path."""
    assert _dispatch(_dispatcher(), _lease()).executed is True


def test_a_failed_lookup_refuses_rather_than_falling_through():
    """"I could not check" must not become "there was nothing to check".

    This is the failure direction the whole enforcement path exists to avoid,
    and the one an absent-bundle return value would quietly produce.
    """
    def raises(_name):
        raise RuntimeError("bundle unreadable")

    result = _dispatch(_dispatcher(raises), _lease())
    assert result.executed is False
    assert result.refusal_reason == "toolspec_unresolvable"


def test_the_refusal_happens_before_the_nonce_is_spent():
    """A refused dispatch must leave the grant usable.

    Burning the nonce on a spec mismatch would convert a recoverable
    configuration error into a permanently dead authorization.
    """
    dispatcher = _dispatcher(lambda name: ("spec-hash-2", 3))
    lease = _lease()
    assert _dispatch(dispatcher, lease).executed is False

    # The same lease, against a dispatcher whose spec now matches.
    dispatcher.bind_toolspec_identity(lambda name: ("spec-hash-1", 3))
    assert _dispatch(dispatcher, lease).executed is True


def test_the_callable_never_runs_on_a_mismatch():
    """Refusal means the side effect did not happen, not that it was undone."""
    calls = []
    dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    dispatcher.register("wo_close", lambda args: calls.append(args))
    dispatcher.bind_toolspec_identity(lambda name: ("other", 3))

    assert _dispatch(dispatcher, _lease()).executed is False
    assert calls == []


def test_the_identity_is_read_at_dispatch_not_at_issue():
    """Resolving at issue time would check the spec against itself.

    The window this closes is between the two, so the resolver must be called
    during dispatch and not before.
    """
    seen = []

    def resolver(name):
        seen.append(name)
        return ("spec-hash-1", 3)

    dispatcher = _dispatcher(resolver)
    lease = _lease()
    assert seen == []
    _dispatch(dispatcher, lease)
    assert seen == ["wo_close"]


# -- what is still not bound, pinned so it cannot change quietly ------------

def test_verify_callable_still_has_no_non_test_caller():
    """Not fixed here, and not approximated.

    ``verify_callable`` compares the registered callable against a digest the
    spec attests. Nothing in this repository PRODUCES such a digest -- every
    bundle fixture carries a placeholder -- so calling it would compare a real
    callable against a constant and refuse or pass for no reason.

    The RMR-003 rule applies unchanged: where the evidence does not exist yet,
    leave the check unreachable rather than approximating it. If this test
    starts failing, a digest producer exists and the claim it supports has to
    be written down with it.
    """
    _assert_no_production_caller("verify_callable")


def test_verify_credential_scope_still_has_no_non_test_caller():
    """Same, for a different missing input.

    The check needs the scope dispatch is about to USE. Nothing tracks that:
    the callables close over their own credentials and do not declare what they
    reach for. Comparing the declaration against itself would be a check that
    cannot fail.
    """
    _assert_no_production_caller("verify_credential_scope")


def _assert_no_production_caller(name: str) -> None:
    import subprocess

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        ["git", "grep", "-l", name, "--", "*.py"],
        cwd=root, capture_output=True, text=True).stdout.split()
    callers = [f for f in out
               if not f.startswith(("tests/", "examples/", "scripts/"))
               and not f.endswith("toolcall/toolspec.py")]
    assert not callers, (
        f"{name} now has a production caller ({callers}); the input it needs "
        "must exist, and the claim it supports must be recorded")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
