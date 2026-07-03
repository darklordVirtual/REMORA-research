"""Tests for remora.audit.hash_chain — cryptographic audit integrity."""
from __future__ import annotations

from remora.audit.hash_chain import AuditHashChain, HashChainEntry


def test_genesis_entry_has_no_previous_hash() -> None:
    chain = AuditHashChain()
    entry = chain.append(
        timestamp="2026-05-30T10:00:00",
        question_hash="abc123",
        action="accept",
        trust_score=0.8,
        phase="ordered",
    )
    assert entry.previous_hash is None
    assert entry.entry_hash is not None


def test_second_entry_links_to_first() -> None:
    chain = AuditHashChain()
    e1 = chain.append(
        timestamp="2026-05-30T10:00:00",
        question_hash="abc123",
        action="accept",
        trust_score=0.8,
        phase="ordered",
    )
    e2 = chain.append(
        timestamp="2026-05-30T10:01:00",
        question_hash="def456",
        action="escalate",
        trust_score=0.3,
        phase="critical",
    )
    assert e2.previous_hash == e1.entry_hash
    assert e2.entry_hash != e1.entry_hash


def test_verify_valid_chain() -> None:
    chain = AuditHashChain()
    chain.append(
        timestamp="2026-05-30T10:00:00",
        question_hash="abc123",
        action="accept",
        trust_score=0.8,
        phase="ordered",
    )
    chain.append(
        timestamp="2026-05-30T10:01:00",
        question_hash="def456",
        action="verify",
        trust_score=0.5,
        phase="critical",
    )
    assert chain.verify() is True


def test_tampered_entry_detected() -> None:
    chain = AuditHashChain()
    chain.append(
        timestamp="2026-05-30T10:00:00",
        question_hash="abc123",
        action="accept",
        trust_score=0.8,
        phase="ordered",
    )
    e2 = chain.append(
        timestamp="2026-05-30T10:01:00",
        question_hash="def456",
        action="verify",
        trust_score=0.5,
        phase="critical",
    )
    # Tamper: change the action field
    tampered = HashChainEntry(
        timestamp=e2.timestamp,
        question_hash=e2.question_hash,
        action="accept",  # changed from verify
        trust_score=e2.trust_score,
        phase=e2.phase,
        previous_hash=e2.previous_hash,
        entry_hash=e2.entry_hash,
        metadata=e2.metadata,
    )
    chain._entries[1] = tampered
    assert chain.verify() is False


def test_tampered_link_detected() -> None:
    chain = AuditHashChain()
    chain.append(
        timestamp="2026-05-30T10:00:00",
        question_hash="abc123",
        action="accept",
        trust_score=0.8,
        phase="ordered",
    )
    e2 = chain.append(
        timestamp="2026-05-30T10:01:00",
        question_hash="def456",
        action="verify",
        trust_score=0.5,
        phase="critical",
    )
    # Tamper: break the previous_hash link
    broken = HashChainEntry(
        timestamp=e2.timestamp,
        question_hash=e2.question_hash,
        action=e2.action,
        trust_score=e2.trust_score,
        phase=e2.phase,
        previous_hash="fakehash",  # wrong link
        entry_hash=e2.entry_hash,
        metadata=e2.metadata,
    )
    chain._entries[1] = broken
    assert chain.verify() is False


def test_entry_verify_alone() -> None:
    entry = HashChainEntry(
        timestamp="2026-05-30T10:00:00",
        question_hash="q",
        action="accept",
        trust_score=0.5,
        phase="ordered",
        previous_hash=None,
        entry_hash="fake",
        metadata={},
    )
    assert entry.verify() is False  # hash mismatch


def test_chain_to_dicts_roundtrip() -> None:
    chain = AuditHashChain()
    chain.append(
        timestamp="2026-05-30T10:00:00",
        question_hash="abc",
        action="accept",
        trust_score=0.8,
        phase="ordered",
        metadata={"version": "v1"},
    )
    dicts = chain.to_dicts()
    assert len(dicts) == 1
    assert dicts[0]["question_hash"] == "abc"
    assert dicts[0]["metadata"]["version"] == "v1"


def test_concurrent_appends_do_not_fork_chain():
    """External security audit CLAIM 5: concurrent append() must not fork the
    chain. With the append lock, N threads appending produce one linear chain
    of N entries that verifies end-to-end."""
    import threading
    from remora.audit.hash_chain import AuditHashChain

    chain = AuditHashChain()
    n = 200
    barrier = threading.Barrier(8)

    def worker(i: int) -> None:
        barrier.wait()  # maximize contention
        chain.append(
            timestamp="2026-07-03T00:00:00Z",
            question_hash=f"q{i}",
            action="verify",
            trust_score=0.5,
            phase="ordered",
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entries = chain.entries() if hasattr(chain, "entries") else chain._entries
    assert len(entries) == n
    # Every non-genesis entry must link to its predecessor — no forks.
    for prev, cur in zip(entries, entries[1:]):
        assert cur.previous_hash == prev.entry_hash
    assert chain.verify()
