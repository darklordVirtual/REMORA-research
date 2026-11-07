# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Does an authorization survive delegation through several agents as it was given?

Four questions, asked of both REMORA paths: the A2A reference envelope
(``remora/governance/a2a_envelope.py``, CAP-006) and the execution API
(``/v1/execution/*``).

1. An intermediary widens the scope it was delegated.
2. A legitimate intermediary changes what the original authority allowed,
   here a payment of 250 into one of 25000, holding whatever symmetric key the
   envelope is signed with.
3. A used authorization is presented again after a restart, or to another
   verifier process.
4. A correctly signed chain is used for an action outside the task it was
   delegated for.

Before 2026-11-07, the A2A path stopped (1) only. It accepted (2) in three
forms: no link carried the authority's parameters, any registered key could
start a chain of its own, and one symmetric key registered for several
principals let any of them sign as another. It accepted (3) whenever the
caller's replay guard forgot, and (4) whenever the verifier did not ask
(``artifacts/assurance/delegated-authority-2026-11-07/baseline.json``). The
cases below pin each of those to a refusal, and show what an honest chain
still passes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.governance.a2a_envelope import (
    A2AGovernanceEnvelope,
    AgentIdentity,
    DeclaredOperation,
    DelegationLink,
    RegisteredKey,
    durable_replay_guard,
    sign_delegation_link,
)
from remora.governance.task_identity import TaskIdentity
from remora.policy.observation import canonical_tool_call_hash

ENVELOPE_KEY = b"envelope-key-every-hop-holds-0000000"
ORIGIN_KEY = b"origin-link-key-000000000000000000000"
MID_KEY = b"intermediary-link-key-00000000000000"
AUDIENCE = "payment-service"
ROOTS = {"origin"}
INVOICE_TASK = TaskIdentity(context_id="case-77", task_id="invoice-250")
OTHER_TASK = TaskIdentity(context_id="case-77", task_id="add-vendor")
REGISTRY = {"k-origin": RegisteredKey(ORIGIN_KEY, "origin"),
            "k-mid": RegisteredKey(MID_KEY, "mid")}


def _iso() -> str:
    return datetime.now(UTC).isoformat()


def _link(delegator, delegatee, scope, *, key=None, kid=None, signing_key=None, parent=None,
          **extra):
    return sign_delegation_link(DelegationLink(delegator, delegatee, tuple(scope), _iso(), **extra),
                                key=key, kid=kid, signing_key=signing_key, parent=parent)


def _origin(scope=("payment:release",), **extra):
    return _link("origin", "mid", scope, key=ORIGIN_KEY, kid="k-origin", **extra)


def _mid(scope=("payment:release",), **extra):
    return _link("mid", "worker", scope, key=MID_KEY, kid="k-mid", **extra)


def _chain(origin, scope=("payment:release",), **mid):
    """The origin's link and the intermediary's, bound to it."""
    return [origin, _mid(scope, parent=origin, **mid)]


def _envelope(chain, scope=("payment:release",), amount=250, task=None, declared=None):
    arguments = {"account": "A-1", "amount": amount}
    call_hash = canonical_tool_call_hash(name="release_payment", arguments=arguments, target="prod")
    envelope = A2AGovernanceEnvelope.issue(
        identity=AgentIdentity("worker", "1", "org", "org"), delegation_chain=tuple(chain),
        requested_scope=tuple(scope), policy_version="p1", audience=AUDIENCE,
        tool_call_hash=call_hash, signing_key=ENVELOPE_KEY, task_identity=task,
        declared_operation=declared)
    return envelope, call_hash, arguments


def _verify(envelope, call_hash, arguments, *, registry=REGISTRY, guard=None, **extra):
    extra.setdefault("expected_task_identity", None)
    return envelope.verify(
        signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE, expected_tool_call_hash=call_hash,
        link_keys=registry, replay_guard=guard or (lambda nonce: False),
        expected_roots=ROOTS, actual_arguments=arguments, **extra)


AMOUNT_250 = ({"lte": 250, "argument": "amount"},)


# ── 0. an honest chain passes ────────────────────────────────────────────────


def test_an_honest_two_hop_chain_with_a_bounded_amount_verifies():
    result = _verify(*_envelope(_chain(_origin(conditions=AMOUNT_250))))
    assert result.valid, result.failures


# ── 1. an intermediary widens the scope ─────────────────────────────────────


def test_1_a_widened_scope_at_the_intermediary_is_refused():
    chain = _chain(_origin(), ("payment:release", "vendor:add"))
    result = _verify(*_envelope(chain, scope=("payment:release",)))
    assert "scope_widened_at_link:1:vendor:add" in result.failures


def test_1_a_scope_the_chain_never_granted_is_refused():
    result = _verify(*_envelope(_chain(_origin()), scope=("vendor:add",)))
    assert "scope_exceeds_delegation:vendor:add" in result.failures


# ── 2. an intermediary changes what the authority allowed ───────────────────


def test_2_an_amount_past_the_origins_condition_is_refused_though_the_envelope_is_valid():
    """The intermediary holds the envelope key and issues a valid envelope for
    25000. The origin's condition sits in the origin's signed link."""
    result = _verify(*_envelope(_chain(_origin(conditions=AMOUNT_250)), amount=25000))
    assert result.failures == ("argument_outside_delegation:0:amount",)


def test_2_the_intermediary_cannot_loosen_the_origins_condition():
    origin = _origin(conditions=AMOUNT_250)
    loosened = DelegationLink(**{**origin.__dict__,
                                 "conditions": ({"lte": 50000, "argument": "amount"},)})
    result = _verify(*_envelope([loosened, _mid(parent=origin)], amount=25000))
    assert "link_signature_mismatch:0" in result.failures


def test_2_a_later_link_can_only_add_a_condition():
    chain = _chain(_origin(conditions=AMOUNT_250), conditions=({"lte": 100, "argument": "amount"},))
    assert _verify(*_envelope(chain, amount=100)).valid
    assert _verify(*_envelope(chain, amount=250)).failures == (
        "argument_outside_delegation:1:amount",)


def test_2_a_chain_re_rooted_at_the_intermediary_is_refused():
    """Drop the origin's link and start the chain at the intermediary's own key."""
    chain = [_link("mid", "worker", ("payment:release", "vendor:add"), key=MID_KEY, kid="k-mid")]
    result = _verify(*_envelope(chain, scope=("vendor:add",), amount=25000))
    assert result.failures == ("untrusted_delegation_root:mid",)


def test_2_one_symmetric_key_for_every_principal_lets_none_of_them_sign():
    shared = b"one-key-every-agent-holds-0000000000"
    registry = {"k-o": RegisteredKey(shared, "origin"), "k-m": RegisteredKey(shared, "mid")}
    forged = _link("origin", "mid", ("payment:release", "vendor:add"), key=shared, kid="k-o")
    hop = _link("mid", "worker", ("vendor:add",), key=shared, kid="k-m", parent=forged)
    result = _verify(*_envelope([forged, hop], scope=("vendor:add",), amount=25000),
                     registry=registry)
    assert set(result.failures) == {"shared_link_key_at_link:0:k-o",
                                    "shared_link_key_at_link:1:k-m"}


def test_2_conditions_with_no_arguments_to_check_them_against_never_pass():
    envelope, call_hash, _ = _envelope(_chain(_origin(conditions=AMOUNT_250)), amount=25000)
    result = envelope.verify(signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE,
                             expected_tool_call_hash=call_hash, link_keys=REGISTRY,
                             replay_guard=lambda n: False, expected_roots=ROOTS)
    assert result.failures == ("link_conditions_unchecked",)
    lax = envelope.verify(signing_key=ENVELOPE_KEY, strict=False)
    assert "link_conditions_unchecked" in lax.failures


def test_2_a_condition_that_reads_state_is_malformed_in_a_link():
    chain = _chain(_origin(conditions=({"equals_state": "account.owner", "argument": "account"},)))
    assert "malformed_link_condition:0" in _verify(*_envelope(chain)).failures


@pytest.fixture()
def origin_ed25519():
    from remora.crypto import SignatureDomain, SigningKey

    return SigningKey.generate({SignatureDomain.A2A_DELEGATION_LINK})


def test_2_an_ed25519_origin_link_verifies_against_its_public_key_only(origin_ed25519):
    vk = origin_ed25519.verification_key()
    registry = {vk.kid: RegisteredKey(b"", "origin", verification_key=vk),
                "k-mid": RegisteredKey(MID_KEY, "mid")}
    origin = _link("origin", "mid", ("payment:release",), signing_key=origin_ed25519,
                   conditions=AMOUNT_250)
    assert _verify(*_envelope(_chain(origin)), registry=registry).valid
    # A verifier holding the registry holds no material that signs as the
    # origin: an HMAC signature, under any bytes, does not pass the public key.
    forged = _link("origin", "mid", ("payment:release",), key=b"anything", kid=vk.kid)
    assert "link_signature_mismatch:0" in _verify(
        *_envelope(_chain(forged), amount=25000), registry=registry).failures
    # Nor does an Ed25519 signature pass an HMAC entry.
    hmac_registry = {vk.kid: RegisteredKey(ORIGIN_KEY, "origin"),
                     "k-mid": RegisteredKey(MID_KEY, "mid")}
    assert "link_signature_mismatch:0" in _verify(
        *_envelope(_chain(origin)), registry=hmac_registry).failures


def test_2_a_registry_entry_with_both_or_neither_key_is_malformed(origin_ed25519):
    vk = origin_ed25519.verification_key()
    origin = _link("origin", "mid", ("payment:release",), signing_key=origin_ed25519)
    for entry in (RegisteredKey(ORIGIN_KEY, "origin", verification_key=vk),
                  RegisteredKey(b"", "origin")):
        registry = {vk.kid: entry, "k-mid": RegisteredKey(MID_KEY, "mid")}
        assert f"malformed_registry_entry_at_link:0:{vk.kid}" in _verify(
            *_envelope(_chain(origin)), registry=registry).failures


# ── 3. replay after a restart, or at another verifier process ───────────────


def test_3_a_durable_guard_refuses_a_replay_after_a_restart_and_at_a_second_process(tmp_path):
    from remora.enforcement.nonce_store import DurableNonceStore

    db = str(tmp_path / "a2a-nonces.db")
    envelope, call_hash, arguments = _envelope(_chain(_origin()))
    first = durable_replay_guard(DurableNonceStore(db_path=db), verifier=AUDIENCE)
    assert _verify(envelope, call_hash, arguments, guard=first).valid
    assert _verify(envelope, call_hash, arguments, guard=first).failures == ("replay_detected",)
    restarted = durable_replay_guard(DurableNonceStore(db_path=db), verifier=AUDIENCE)
    assert _verify(envelope, call_hash, arguments, guard=restarted).failures == (
        "replay_detected",)
    second_process = durable_replay_guard(DurableNonceStore(db_path=db), verifier=AUDIENCE)
    assert _verify(envelope, call_hash, arguments, guard=second_process).failures == (
        "replay_detected",)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT tenant_id FROM lease_nonce_consumed").fetchall() == [
            (f"a2a:{AUDIENCE}",)]


def test_3_a_tampered_envelope_consumes_no_nonce(tmp_path):
    from remora.enforcement.nonce_store import DurableNonceStore

    db = str(tmp_path / "a2a-nonces.db")
    guard = durable_replay_guard(DurableNonceStore(db_path=db), verifier=AUDIENCE)
    envelope, call_hash, arguments = _envelope(_chain(_origin()))
    assert not _verify(envelope, "f" * 64, arguments, guard=guard).valid
    assert _verify(envelope, call_hash, arguments, guard=guard).valid


def test_3_another_verifier_identity_is_refused_by_audience():
    envelope, call_hash, arguments = _envelope(_chain(_origin()))
    result = envelope.verify(signing_key=ENVELOPE_KEY, expected_audience="ledger-service",
                             expected_tool_call_hash=call_hash, link_keys=REGISTRY,
                             replay_guard=lambda n: False, expected_roots=ROOTS,
                             actual_arguments=arguments)
    assert result.failures == ("audience_mismatch",)


def test_3_the_guard_names_its_verifier():
    with pytest.raises(ValueError):
        durable_replay_guard(object(), verifier="")


# ── 4. a correctly signed chain used for another task ───────────────────────


def _task_links(task=INVOICE_TASK):
    return _chain(_origin(context_id=task.context_id, task_id=task.task_id))


def test_4_an_envelope_for_another_task_than_the_origin_delegated_is_refused():
    result = _verify(*_envelope(_task_links(), task=OTHER_TASK),
                     expected_task_identity=OTHER_TASK)
    assert result.failures == ("task_outside_delegation",)


def test_4_the_delegated_task_passes_when_the_verifier_checks_it():
    assert _verify(*_envelope(_task_links(), task=INVOICE_TASK),
                   expected_task_identity=INVOICE_TASK).valid


def test_4_a_bound_task_the_verifier_does_not_check_fails_in_strict_mode():
    result = _verify(*_envelope(_task_links(), task=INVOICE_TASK))
    assert result.failures == ("strict_unchecked_task_binding",)


def test_4_an_intermediary_cannot_move_the_chain_to_another_task():
    chain = _chain(_origin(context_id="case-77", task_id="invoice-250"),
                   context_id="case-77", task_id="add-vendor")
    result = _verify(*_envelope(chain, task=OTHER_TASK), expected_task_identity=OTHER_TASK)
    assert "task_changed_at_link:1" in result.failures


def test_4_a_declared_operation_the_verifier_does_not_check_fails_in_strict_mode():
    declared = DeclaredOperation("payment:release", ("A-1",))
    result = _verify(*_envelope(_chain(_origin()), declared=declared))
    assert result.failures == ("strict_unchecked_declared_operation",)
    checked = _verify(*_envelope(_chain(_origin()), declared=declared),
                      actual_operation=("payment:release", "A-2"))
    assert checked.failures == ("actual_operation_exceeds_declaration",)


# ── adversarial review 2026-11-07 ───────────────────────────────────────────


def test_review_a_looser_parent_cannot_be_put_in_front_of_a_bound_link():
    """The origin issued the intermediary two links: one bounded to 250 for
    the invoice, one unbounded for another task. The intermediary delegated
    under the first. Swapping in the second would drop the bound and the task;
    the intermediary's link signed the first one's digest."""
    bounded = _origin(conditions=AMOUNT_250, context_id="case-77", task_id="invoice-250")
    loose = _origin()
    _, hop = _chain(bounded)
    result = _verify(*_envelope([loose, hop], amount=25000))
    assert result.failures == ("parent_mismatch_at_link:1",)


def test_review_strict_mode_requires_every_link_after_the_first_to_bind_its_parent():
    unbound = [_origin(conditions=AMOUNT_250), _mid()]
    assert _verify(*_envelope(unbound)).failures == ("strict_unbound_parent_at_link:1",)
    assert _verify(*_envelope(unbound), strict=False).valid


def test_review_a_root_link_names_no_parent():
    other = _origin()
    root = _link("origin", "mid", ("payment:release",), key=ORIGIN_KEY, kid="k-origin",
                 parent=other)
    result = _verify(*_envelope(_chain(root)))
    assert "parent_digest_on_root_link" in result.failures


def test_review_a_parent_is_bound_once_it_is_signed():
    with pytest.raises(ValueError):
        _mid(parent=DelegationLink("origin", "mid", ("payment:release",), _iso()))


def test_review_a_link_key_equal_to_the_envelope_key_is_refused():
    """Whoever holds the envelope key could then write the origin's link too."""
    registry = {"k-origin": RegisteredKey(ENVELOPE_KEY, "origin"),
                "k-mid": RegisteredKey(MID_KEY, "mid")}
    origin = _link("origin", "mid", ("payment:release",), key=ENVELOPE_KEY, kid="k-origin")
    result = _verify(*_envelope(_chain(origin)), registry=registry)
    assert result.failures == ("link_key_is_envelope_key_at_link:0:k-origin",)


def _twins():
    """Pairs of different bytes HMAC-SHA256 treats as one key (RFC 2104)."""
    long_key = b"L" * 100
    return [(ORIGIN_KEY, ORIGIN_KEY + b"\0\0"),                  # zero padding
            (long_key, hashlib.sha256(long_key).digest())]       # a long key and its hash


@pytest.mark.parametrize(("one", "twin"), _twins())
def test_review_keys_hmac_treats_as_equal_are_one_shared_key(one, twin):
    assert one != twin
    assert hmac.new(one, b"m", "sha256").digest() == hmac.new(twin, b"m", "sha256").digest()
    registry = {"k-o": RegisteredKey(one, "origin"), "k-m": RegisteredKey(twin, "mid")}
    origin = _link("origin", "mid", ("payment:release",), key=one, kid="k-o")
    hop = _link("mid", "worker", ("payment:release",), key=twin, kid="k-m", parent=origin)
    result = _verify(*_envelope([origin, hop]), registry=registry)
    assert set(result.failures) == {"shared_link_key_at_link:0:k-o",
                                    "shared_link_key_at_link:1:k-m"}


def test_review_a_padded_envelope_key_is_the_envelope_key():
    padded = ENVELOPE_KEY + b"\0"
    registry = {"k-o": RegisteredKey(padded, "origin"), "k-mid": RegisteredKey(MID_KEY, "mid")}
    origin = _link("origin", "mid", ("payment:release",), key=padded, kid="k-o")
    assert _verify(*_envelope(_chain(origin)), registry=registry).failures == (
        "link_key_is_envelope_key_at_link:0:k-o",)


_SECOND_PROCESS = """
import sys
from remora.enforcement.nonce_store import DurableNonceStore
from remora.governance.a2a_envelope import durable_replay_guard
seen = durable_replay_guard(DurableNonceStore(db_path=sys.argv[1]), verifier=sys.argv[2])
print("seen" if seen(sys.argv[3]) else "fresh")
"""


def test_review_a_replay_is_refused_by_a_separate_os_process(tmp_path):
    from remora.enforcement.nonce_store import DurableNonceStore

    db = str(tmp_path / "a2a-nonces.db")
    envelope, call_hash, arguments = _envelope(_chain(_origin()))
    guard = durable_replay_guard(DurableNonceStore(db_path=db), verifier=AUDIENCE)
    assert _verify(envelope, call_hash, arguments, guard=guard).valid
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", _SECOND_PROCESS, db, AUDIENCE, envelope.nonce],
                         capture_output=True, text=True, cwd=root, check=True, timeout=60)
    assert out.stdout.strip() == "seen"
    fresh = subprocess.run([sys.executable, "-c", _SECOND_PROCESS, db, "ledger-service",
                            envelope.nonce], capture_output=True, text=True, cwd=root,
                           check=True, timeout=60)
    assert fresh.stdout.strip() == "fresh"   # nonces are kept per verifier


@pytest.mark.parametrize("argument", [["amount"], 7, ""])
def test_review_a_condition_on_a_non_string_argument_fails_and_does_not_raise(argument):
    chain = _chain(_origin(conditions=({"lte": 250, "argument": argument},)))
    assert "malformed_link_condition:0" in _verify(*_envelope(chain)).failures


@pytest.mark.parametrize("amount", [float("inf"), float("-inf"), float("nan")])
def test_review_a_bound_is_never_met_by_a_non_finite_number(amount):
    gte = ({"gte": 1, "argument": "amount"},)
    for conditions in (AMOUNT_250, gte):
        envelope, call_hash, arguments = _envelope(_chain(_origin(conditions=conditions)))
        arguments = {**arguments, "amount": amount}
        assert "argument_outside_delegation:0:amount" in _verify(
            envelope, call_hash, arguments).failures


def test_review_a_bool_is_not_the_number_it_compares_equal_to():
    for conditions, value in ((({"eq": 1, "argument": "amount"},), True),
                              (({"in": [0, 250], "argument": "amount"},), False)):
        envelope, call_hash, arguments = _envelope(_chain(_origin(conditions=conditions)))
        assert "argument_outside_delegation:0:amount" in _verify(
            envelope, call_hash, {**arguments, "amount": value}).failures


def test_review_expected_roots_as_a_bare_string_raises():
    envelope, call_hash, arguments = _envelope(_chain(_origin()))
    with pytest.raises(TypeError):
        envelope.verify(signing_key=ENVELOPE_KEY, expected_roots="origin")


def test_review_a_registry_key_is_bytes():
    with pytest.raises(TypeError):
        RegisteredKey("origin-key", "origin")  # type: ignore[arg-type]


def test_review_the_parent_binding_round_trips_through_json():
    envelope, call_hash, arguments = _envelope(_chain(_origin(conditions=AMOUNT_250)))
    again = A2AGovernanceEnvelope.from_json(envelope.to_json())
    assert again.delegation_chain[1].parent_digest == envelope.delegation_chain[1].parent_digest
    assert _verify(again, call_hash, arguments).valid


# ── second review 2026-11-07 ────────────────────────────────────────────────

HUGE = json.loads("1" + "0" * 400)   # strict JSON admits it; float() overflows


def test_review2_a_huge_integer_is_refused_by_a_bound_and_never_raises():
    from remora.capabilities.constraints import (
        CapabilityRefusal,
        Condition,
        ToolConstraint,
        evaluate_constraint,
    )
    from remora.toolcall.intent_scope import IntentScope

    bound = ToolConstraint(conditions=(Condition.from_dict({"lte": 250, "argument": "amount"}),))
    assert evaluate_constraint(bound, {"amount": HUGE}) is CapabilityRefusal.ARGUMENT_MISMATCH
    floor = ToolConstraint(conditions=(Condition.from_dict({"gte": 1, "argument": "amount"}),))
    assert evaluate_constraint(floor, {"amount": HUGE}) is None    # an int is finite
    envelope, call_hash, arguments = _envelope(_chain(_origin(conditions=AMOUNT_250)))
    assert "argument_outside_delegation:0:amount" in _verify(
        envelope, call_hash, {**arguments, "amount": HUGE}).failures
    scope = IntentScope.from_dict({"tools": ["release_payment"], "effects": ["update"],
                                   "arguments": [{"lte": 250, "argument": "amount"}]})
    assert scope.check("release_payment", {"amount": HUGE}, effect="update",
                       target_arguments=[]).status == \
        "out_of_scope"


@pytest.mark.parametrize(("condition", "value"), [
    ({"ne": 0, "argument": "dry_run"}, False),
    ({"ne": 1, "argument": "force"}, True),
    ({"not_in": [1], "argument": "force"}, True),
    ({"not_in": [0, 2], "argument": "dry_run"}, False),
])
def test_review2_a_deny_list_still_refuses_the_bool_a_tool_reads_as_its_number(condition, value):
    from remora.capabilities.constraints import Condition, ToolConstraint, evaluate_constraint

    constraint = ToolConstraint(conditions=(Condition.from_dict(condition),))
    assert evaluate_constraint(constraint, {condition["argument"]: value}) is not None


@pytest.mark.parametrize(("condition", "value"), [
    ({"eq": [1], "argument": "x"}, [True]),
    ({"in": [[0]], "argument": "x"}, [False]),
    ({"eq": {"a": 1}, "argument": "x"}, {"a": True}),
    ({"eq": [1], "argument": "x"}, (1,)),
])
def test_review2_equality_keeps_bools_apart_at_every_depth(condition, value):
    from remora.capabilities.constraints import Condition, ToolConstraint, evaluate_constraint

    constraint = ToolConstraint(conditions=(Condition.from_dict(condition),))
    assert evaluate_constraint(constraint, {"x": value}) is not None
    assert evaluate_constraint(constraint, {"x": json.loads(json.dumps(condition.get(
        "eq", (condition.get("in") or [None])[0])))}) is None


def test_review2_equals_state_keeps_a_bool_apart_from_a_number():
    from remora.capabilities.constraints import Condition, ToolConstraint, evaluate_constraint

    constraint = ToolConstraint(conditions=(
        Condition.from_dict({"equals_state": "flag", "argument": "x"}),))
    assert evaluate_constraint(constraint, {"x": 1}, reader=lambda src, args: True) is not None
    assert evaluate_constraint(constraint, {"x": True}, reader=lambda src, args: True) is None


def test_review2_an_ed25519_signature_has_one_spelling(origin_ed25519):
    """Unused low bits of the last base64 character changed the link's digest
    without breaking its signature."""
    import base64

    vk = origin_ed25519.verification_key()
    registry = {vk.kid: RegisteredKey(b"", "origin", verification_key=vk),
                "k-mid": RegisteredKey(MID_KEY, "mid")}
    origin = _link("origin", "mid", ("payment:release",), signing_key=origin_ed25519)
    encoded = origin.signature.removeprefix("ed25519:")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    stem, last = encoded.rstrip("="), encoded.rstrip("=")[-1]
    variant = alphabet[alphabet.index(last) ^ 1]
    respelled = stem[:-1] + variant + "=" * (len(encoded) - len(stem))
    assert base64.b64decode(respelled) == base64.b64decode(encoded)
    twin = DelegationLink(**{**origin.__dict__, "signature": "ed25519:" + respelled})
    assert _verify(*_envelope(_chain(origin)), registry=registry).valid
    assert "link_signature_mismatch:0" in _verify(
        *_envelope(_chain(twin)), registry=registry).failures


def test_review2_an_empty_envelope_key_neither_signs_nor_verifies():
    envelope, call_hash, arguments = _envelope(_chain(_origin()))
    with pytest.raises(ValueError):
        A2AGovernanceEnvelope.issue(
            identity=AgentIdentity("worker", "1", "org", "org"),
            delegation_chain=envelope.delegation_chain, requested_scope=("payment:release",),
            policy_version="p1", audience=AUDIENCE, signing_key=b"")
    assert "no_verification_key" in envelope.verify(signing_key=b"", strict=False).failures


# ── compatibility ────────────────────────────────────────────────────────────


def test_a_link_without_the_new_fields_signs_the_bytes_it_signed_before():
    link = DelegationLink("origin", "mid", ("payment:release",), "2026-11-07T00:00:00+00:00",
                          kid="k-origin")
    # The payload at dea40402, byte for byte.
    assert link.signable_payload() == (
        b'{"delegatee":"mid","delegator":"origin","expires_at":null,'
        b'"issued_at":"2026-11-07T00:00:00+00:00","kid":"k-origin","scope":["payment:release"]}')


def test_the_new_fields_round_trip_through_json():
    envelope, call_hash, arguments = _envelope(
        _chain(_origin(conditions=AMOUNT_250, context_id="case-77", task_id="invoice-250")),
        task=INVOICE_TASK)
    again = A2AGovernanceEnvelope.from_json(envelope.to_json())
    assert again.delegation_chain[0].conditions == AMOUNT_250
    assert _verify(again, call_hash, arguments, expected_task_identity=INVOICE_TASK).valid


# ── the execution API: the same four questions ──────────────────────────────


def test_execution_1_a_delegated_capability_set_cannot_widen():
    from remora.capabilities import (
        CapabilityPolicy,
        CapabilityResolver,
        DelegationDenied,
        delegate,
    )

    now = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    policy = CapabilityPolicy.from_dict({
        "policy_version": "p1", "registry_version": "r1",
        "registry": {"release_payment": ["prod"], "add_vendor": ["prod"]},
        "principals": {"agent-1": ["release_payment"]}, "tasks": {"payments": ["release_payment"]},
        "tenants": {"acme": ["release_payment", "add_vendor"]},
        "environments": {"prod": ["release_payment", "add_vendor"]},
        "constraints": {"release_payment": {"conditions": [{"lte": 250, "argument": "amount"}]}}})
    parent = CapabilityResolver(policy).resolve(principal_id="agent-1", tenant_id="acme",
                                                environment="prod", task_type="payments", now=now)
    with pytest.raises(DelegationDenied):
        delegate(parent, delegatee="agent-2", tools=["add_vendor"], purpose="x", now=now)
    child = delegate(parent, delegatee="agent-2", tools=["release_payment"], purpose="payment",
                     now=now)
    # The parent's amount bound is inherited, and can only be narrowed.
    assert [dict(c) for c in child.constraints["release_payment"]["conditions"]] == [
        {"lte": 250, "argument": "amount"}]


def test_execution_2_a_work_order_for_250_does_not_cover_25000():
    from remora.toolcall.intent_scope import IntentScope

    scope = IntentScope.from_dict({"tools": ["release_payment"], "effects": ["update"],
                                   "targets": {"account": ["A-1"]},
                                   "arguments": [{"lte": 250, "argument": "amount"}]})
    check = lambda amount: scope.check(  # noqa: E731
        "release_payment", {"account": "A-1", "amount": amount}, effect="update",
        target_arguments=["account"])
    assert check(250).status == "in_scope"
    assert (check(25000).status, check(25000).violations) == ("out_of_scope", ("argument:amount",))
    assert check("250").status == "out_of_scope"  # a numeric bound is never met by a string


@pytest.mark.parametrize("bad", [
    [{"lte": 250}],                                          # no argument
    [{"equals_state": "account.owner", "argument": "account"}],  # reads state
    [{"lte": "250", "argument": "amount"}],                  # non-numeric bound
    [{"lte": 250, "argument": ["amount"]}],                  # non-string argument
    "lte 250",
])
def test_execution_2_a_malformed_argument_bound_is_refused_at_parse(bad):
    from remora.toolcall.intent_scope import IntentScope

    with pytest.raises(ValueError):
        IntentScope.from_dict({"tools": ["t"], "effects": ["update"], "arguments": bad})


PILOT = Path(__file__).resolve().parents[1] / "deploy" / "ot-pilot"


def test_execution_2_through_the_api_a_bounded_work_order_refuses_the_larger_move(
        monkeypatch, tmp_path):
    """The pilot's WO-1201, given a bound on the setpoint value, refuses a
    move past it at assess with no review item: an approver cannot lift it."""
    pytest.importorskip("fastapi")
    from tests.limits.test_limits_ot_pilot import payload
    from tests.test_toolspec_execution_wiring import _client

    monkeypatch.syspath_prepend(str(PILOT))
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    orders = json.loads((PILOT / "work_orders.json").read_text(encoding="utf-8"))
    orders["WO-1201"]["scope"]["arguments"] = [{"lte": 4.5, "argument": "value"}]
    path = tmp_path / "work_orders.json"
    path.write_text(json.dumps(orders), encoding="utf-8")
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("ot-pilot", "reviewer"))
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "ot_registry")
    monkeypatch.setenv("REMORA_SEMANTIC_BUNDLE_MODULE", "ot_bundle")
    monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", str(path))
    for var in ("REMORA_LIMITS_FILE", "REMORA_REQUIRE_LIMITS"):
        monkeypatch.delenv(var, raising=False)
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    try:
        inside = client.post("/v1/execution/assess", json=payload(
            "adjust_setpoint", "WO-1201", loop="PIC-101", value=4.3)).json()
        assert inside["decision"] == "verify"
        outside = client.post("/v1/execution/assess", json=payload(
            "adjust_setpoint", "WO-1201", loop="PIC-101", value=5.9)).json()
        assert outside["decision"] == "abstain" and "review_item_id" not in outside
        assert "intent_scope_mismatch" in outside["reasons"]
    finally:
        sys.modules.pop("ot_registry", None)
        sys.modules.pop("ot_bundle", None)
