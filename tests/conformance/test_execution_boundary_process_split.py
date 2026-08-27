# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Property E across real process boundaries, with a real credential (L5).

The single-process suite in ``test_execution_boundary.py`` recorded two
bypasses that succeed, and concluded that REMORA's execution boundary is a
process boundary rather than a call boundary. That conclusion was an
argument. This module tests it.

Three processes, three different sets of secrets:

* **effect service** (``_effect_service.py``) holds nothing, and refuses
  ``POST /send`` without the bearer token. ``GET /mailbox`` is the
  authoritative read-back used for property G.
* **execution domain** (``_executor.py``) holds the effect credential and the
  Ed25519 *public* key. It can verify a lease and cannot mint one; it exits
  rather than start if handed the private seed.
* **authority and agent** is this pytest process. It holds the Ed25519
  private seed and mints leases. It never holds the effect credential, which
  the fixture asserts rather than assumes.

The chain under test, end to end:

    intent -> authority -> exact call -> exclusive execution path -> effect proof

Every refusal below is confirmed against the mailbox, not against the
dispatch response. A dispatcher reporting a refusal while the effect
happened anyway is exactly the failure property G exists to catch, so the
response is never the evidence.

Case identifiers used in the conformance assessment:

    P1  the agent process does not hold the effect credential
    P2  the agent reaches the effect service directly and is refused
    P3  an authorised call executes, and the world confirms it
    P4  argument substitution under a valid lease is refused
    P5  replay of a spent lease is refused
    P6  the execution domain cannot mint its own authority
    P7  a lease spent on one executor is refused by another, over a shared durable store
    P8  a lease spent before an executor restart is refused after it
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from remora.enforcement.lease import ExecutionLease

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

BUNDLE = "c" * 64
EFFECT_TOKEN = "effect-credential-that-only-the-executor-holds"
APPROVED = "approved@example.com"
ATTACKER = "attacker@example.com"

# Deterministic Ed25519 seed and its public key, generated once below. Test
# material only: it never leaves this process except as a public key.
_SEED = bytes(range(32)).hex()


def _public_key_hex() -> str:
    ed25519 = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        reason="Ed25519 lease material requires the 'cryptography' extra",
    )
    from cryptography.hazmat.primitives import serialization

    private = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_SEED))
    raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw.hex()


def _start(script: str, env: dict[str, str]) -> tuple[subprocess.Popen, int]:
    """Launch a helper process and read the ephemeral port it prints."""
    child_env = {**os.environ, **env}
    child_env["PYTHONPATH"] = str(REPO)
    child_env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(HERE / script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
    )
    line = proc.stdout.readline().strip() if proc.stdout else ""
    if not line.isdigit():
        proc.kill()
        stderr = proc.stderr.read() if proc.stderr else ""
        pytest.fail(f"{script} did not start: {line!r} {stderr!r}")
    return proc, int(line)


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def _post(url: str, body: dict, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


@pytest.fixture(scope="module")
def split():
    """The three-process fixture, with the secrets deliberately separated."""
    public_key = _public_key_hex()

    effect_proc, effect_port = _start(
        "_effect_service.py", {"CONFORMANCE_EFFECT_TOKEN": EFFECT_TOKEN}
    )
    effect_url = f"http://127.0.0.1:{effect_port}"

    executor_env = {
        "CONFORMANCE_EFFECT_TOKEN": EFFECT_TOKEN,
        "CONFORMANCE_EFFECT_URL": effect_url,
        "CONFORMANCE_POLICY_BUNDLE_HASH": BUNDLE,
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC": public_key,
        # Explicitly cleared: the execution domain must not be able to sign.
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE": "",
        "REMORA_LEASE_SIGNING_KEY": "",
        "REMORA_PDP_SIGNING_KEY": "",
    }
    try:
        executor_proc, executor_port = _start("_executor.py", executor_env)
    except BaseException:
        effect_proc.kill()
        raise

    # The authority half runs here. This process signs and never delivers.
    previous = {
        key: os.environ.get(key)
        for key in (
            "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
            "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
            "CONFORMANCE_EFFECT_TOKEN",
        )
    }
    os.environ["REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE"] = _SEED
    os.environ["REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"] = public_key
    os.environ.pop("CONFORMANCE_EFFECT_TOKEN", None)

    try:
        yield {
            "effect_url": effect_url,
            "executor_url": f"http://127.0.0.1:{executor_port}",
        }
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for proc in (executor_proc, effect_proc):
            proc.kill()
            proc.wait(timeout=10)


def _mailbox(split) -> list[dict]:
    return _get(split["effect_url"] + "/mailbox")["delivered"]


def _issue(tool_name: str, arguments: dict) -> dict:
    lease = ExecutionLease.issue(
        decision="accept",
        tenant_id="t1",
        actor_identity="agent-1",
        tool_name=tool_name,
        arguments=arguments,
        target_environment="prod",
        policy_bundle_hash=BUNDLE,
        issued_at=datetime.now(timezone.utc).isoformat(),
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(),
    )
    return lease.to_dict()


def _dispatch(split, lease: dict, arguments: dict) -> dict:
    return _post(
        split["executor_url"] + "/dispatch",
        {
            "lease": lease,
            "tool_name": "send_mail",
            "arguments": arguments,
            "tenant_id": "t1",
            "target_environment": "prod",
            "actor_identity": "agent-1",
        },
    )


# --------------------------------------------------------------------------


def test_p1_agent_process_does_not_hold_the_effect_credential(split) -> None:
    """The premise of the whole fixture, asserted instead of assumed."""
    assert os.environ.get("CONFORMANCE_EFFECT_TOKEN") is None
    whoami = _get(split["executor_url"] + "/whoami")
    assert whoami["holds_effect_credential"] is True
    assert whoami["holds_lease_private_key"] is False
    assert whoami["holds_lease_public_key"] is True


def test_p2_agent_cannot_reach_the_effect_directly(split) -> None:
    """No alternative credential path: the exclusivity claim in E."""
    before = len(_mailbox(split))
    with pytest.raises(urllib.error.HTTPError) as caught:
        _post(split["effect_url"] + "/send", {"to": ATTACKER})
    assert caught.value.code == 401
    assert len(_mailbox(split)) == before, "unauthorised call still delivered"


def test_p3_authorised_call_executes_and_the_world_confirms_it(split) -> None:
    """The full chain, with the effect proved by read-back rather than by 200."""
    before = len(_mailbox(split))
    arguments = {"to": APPROVED}
    result = _dispatch(split, _issue("send_mail", arguments), arguments)
    assert result["executed"] is True, result

    delivered = _mailbox(split)
    assert len(delivered) == before + 1
    assert delivered[-1]["to"] == APPROVED


def test_p4_argument_substitution_is_refused_and_nothing_is_delivered(
    split,
) -> None:
    """Exact-call binding held at the boundary, checked against the world."""
    before = _mailbox(split)
    lease = _issue("send_mail", {"to": APPROVED})
    result = _dispatch(split, lease, {"to": ATTACKER})
    assert result["executed"] is False
    # Pinned: a refusal for a serialisation or routing reason would make this
    # test pass without the binding ever being checked.
    assert result["refusal_reason"] == "tool_args_hash_mismatch"

    after = _mailbox(split)
    assert after == before
    assert all(entry["to"] != ATTACKER for entry in after)


def test_p5_replay_of_a_spent_lease_is_refused(split) -> None:
    """Single use, observed at the effect rather than at the ledger.

    Scoped to one execution process: the dispatcher here uses the default
    in-process nonce ledger. P7 is the widening, with two executor
    processes over a shared durable store.
    """
    arguments = {"to": APPROVED}
    lease = _issue("send_mail", arguments)

    first = _dispatch(split, lease, arguments)
    assert first["executed"] is True, first
    after_first = _mailbox(split)

    second = _dispatch(split, lease, arguments)
    assert second["executed"] is False
    assert second["refusal_reason"] == "nonce_already_consumed"
    assert _mailbox(split) == after_first, "replay produced a second effect"


def test_p6_execution_domain_cannot_mint_its_own_authority(split) -> None:
    """The custody split, tested by trying to break it.

    An execution domain handed the private seed exits rather than serve. If
    it ever starts, the split has become decorative and every lease it
    verifies is a lease it could have written.
    """
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "_executor.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO),
            "CONFORMANCE_EFFECT_TOKEN": EFFECT_TOKEN,
            "CONFORMANCE_EFFECT_URL": split["effect_url"],
            "CONFORMANCE_POLICY_BUNDLE_HASH": BUNDLE,
            "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE": _SEED,
        },
    )
    try:
        _stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("executor served while holding the lease signing key")
    assert proc.returncode == 2
    assert "refuses to hold the lease signing key" in stderr


# --------------------------------------------------------------------------
# P7 — distributed single use across executor processes
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_executors(split, tmp_path_factory):
    """Two execution domains sharing one durable nonce store.

    P5 scoped itself to a single executor because the default ledger is
    in-process. This fixture is the widening it named: a SQLite store on
    disk, read through REMORA_CHAIN_DB exactly as the real server reads it,
    shared by two independent executor processes.
    """
    db = tmp_path_factory.mktemp("nonce") / "lease_nonce.db"
    env = {
        "CONFORMANCE_EFFECT_TOKEN": EFFECT_TOKEN,
        "CONFORMANCE_EFFECT_URL": split["effect_url"],
        "CONFORMANCE_POLICY_BUNDLE_HASH": BUNDLE,
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC": _public_key_hex(),
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE": "",
        "REMORA_LEASE_SIGNING_KEY": "",
        "REMORA_PDP_SIGNING_KEY": "",
        "REMORA_CHAIN_DB": str(db),
    }
    procs, urls = [], []
    try:
        for _ in range(2):
            proc, port = _start("_executor.py", env)
            procs.append(proc)
            urls.append(f"http://127.0.0.1:{port}")
        yield urls
    finally:
        for proc in procs:
            proc.kill()
            proc.wait(timeout=10)


def _dispatch_to(url: str, lease: dict, arguments: dict) -> dict:
    return _post(
        url + "/dispatch",
        {
            "lease": lease,
            "tool_name": "send_mail",
            "arguments": arguments,
            "tenant_id": "t1",
            "target_environment": "prod",
            "actor_identity": "agent-1",
        },
    )


def test_p7_both_executors_report_a_durable_store(two_executors) -> None:
    for url in two_executors:
        assert _get(url + "/whoami")["nonce_store"] == "durable"


@pytest.mark.parametrize("first, second", [(0, 1), (1, 0)])
def test_p7_a_lease_spent_on_one_executor_is_refused_by_the_other(
    split, two_executors, first: int, second: int
) -> None:
    """Single use holds across processes, observed at the effect.

    Both orderings run, so the result cannot depend on which process
    created the table or which one happened to start first.
    """
    arguments = {"to": APPROVED}
    lease = _issue("send_mail", arguments)

    won = _dispatch_to(two_executors[first], lease, arguments)
    assert won["executed"] is True, won
    after_first = _mailbox(split)

    replay = _dispatch_to(two_executors[second], lease, arguments)
    assert replay["executed"] is False
    assert replay["refusal_reason"] == "nonce_already_consumed"
    assert _mailbox(split) == after_first, "cross-executor replay produced an effect"


def test_p8_a_lease_spent_before_a_restart_is_refused_after_it(
    split, two_executors, tmp_path_factory
) -> None:
    """The A-row remainder: single use survives the consumer being gone.

    The executor that spent the nonce is killed, and a fresh executor over
    the same store refuses the replay. The in-process ledger cannot do this
    by construction; the durable store must, or a restart is a free replay.
    """
    db = tmp_path_factory.mktemp("restart") / "lease_nonce.db"
    env = {
        "CONFORMANCE_EFFECT_TOKEN": EFFECT_TOKEN,
        "CONFORMANCE_EFFECT_URL": split["effect_url"],
        "CONFORMANCE_POLICY_BUNDLE_HASH": BUNDLE,
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC": _public_key_hex(),
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE": "",
        "REMORA_LEASE_SIGNING_KEY": "",
        "REMORA_PDP_SIGNING_KEY": "",
        "REMORA_CHAIN_DB": str(db),
    }
    arguments = {"to": APPROVED}
    lease = _issue("send_mail", arguments)

    first, port = _start("_executor.py", env)
    try:
        won = _dispatch_to(f"http://127.0.0.1:{port}", lease, arguments)
        assert won["executed"] is True, won
        after = _mailbox(split)
    finally:
        first.kill()
        first.wait(timeout=10)

    second, port2 = _start("_executor.py", env)
    try:
        replay = _dispatch_to(f"http://127.0.0.1:{port2}", lease, arguments)
        assert replay["executed"] is False
        assert replay["refusal_reason"] == "nonce_already_consumed"
        assert _mailbox(split) == after, "replay after restart produced an effect"
    finally:
        second.kill()
        second.wait(timeout=10)


# --------------------------------------------------------------------------
# P7 over a real Postgres server (runs in the Postgres CI jobs)
# --------------------------------------------------------------------------

pg_dsn = pytest.mark.skipif(
    not os.environ.get("REMORA_PG_DSN", "").strip(),
    reason="REMORA_PG_DSN not set (cross-executor single use needs a real Postgres)",
)


@pytest.fixture(scope="module")
def two_executors_postgres(split):
    """Two executors over the Postgres nonce store the deployment path uses."""
    env = {
        "CONFORMANCE_EFFECT_TOKEN": EFFECT_TOKEN,
        "CONFORMANCE_EFFECT_URL": split["effect_url"],
        "CONFORMANCE_POLICY_BUNDLE_HASH": BUNDLE,
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC": _public_key_hex(),
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE": "",
        "REMORA_LEASE_SIGNING_KEY": "",
        "REMORA_PDP_SIGNING_KEY": "",
        "REMORA_CHAIN_DB": "",
        "REMORA_PG_DSN": os.environ.get("REMORA_PG_DSN", ""),
    }
    procs, urls = [], []
    try:
        for _ in range(2):
            proc, port = _start("_executor.py", env)
            procs.append(proc)
            urls.append(f"http://127.0.0.1:{port}")
        yield urls
    finally:
        for proc in procs:
            proc.kill()
            proc.wait(timeout=10)


@pg_dsn
@pytest.mark.parametrize("first, second", [(0, 1), (1, 0)])
def test_p7_postgres_a_lease_spent_on_one_executor_is_refused_by_the_other(
    split, two_executors_postgres, first: int, second: int
) -> None:
    """P7 against a real database server rather than a file on one disk.

    Same assertion as the SQLite case. The store is the one
    servers/execution_api.py builds from REMORA_PG_DSN, so this is the
    deployment path, exercised across two processes.
    """
    for url in two_executors_postgres:
        assert _get(url + "/whoami")["nonce_store"] == "durable"

    arguments = {"to": APPROVED}
    lease = _issue("send_mail", arguments)

    won = _dispatch_to(two_executors_postgres[first], lease, arguments)
    assert won["executed"] is True, won
    after_first = _mailbox(split)

    replay = _dispatch_to(two_executors_postgres[second], lease, arguments)
    assert replay["executed"] is False
    assert replay["refusal_reason"] == "nonce_already_consumed"
    assert _mailbox(split) == after_first
