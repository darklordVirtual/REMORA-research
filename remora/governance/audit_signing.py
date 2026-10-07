# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signatures on tenant audit chain entries: v1 frozen, v2 domain-separated (CR-011).

v1 signs ``HMAC-SHA256(key, entry_hash)`` with no statement of what the bytes
are. It is frozen with its vector in ``vectors/v1/audit_chain.json``, and a v1
entry is never re-signed: re-signing history would replace the evidence of
what was signed with a claim about it made later.

v2 signs ``"v2:" + HMAC-SHA256(key, REMORA/AUDIT/v2 || 0x00 || entry_hash)``.
A chain enters v2 exactly once, through an ``AUDIT_VERSION_TRANSITION`` record
whose payload names the final v1 head and the new domain::

    v1 entries ... -> AUDIT_VERSION_TRANSITION {from, to, previous_chain_head,
                      new_domain} -> v2 entries ...

The transition record is itself the first v2 entry, and a chain never goes
back. The era of each entry is read from the chain's structure (before or
after its transition), never from what the entry's signature claims, so:

- a v1 signature after the transition is a finding, and a ``v2:`` signature
  before any transition is one, and both are checkable without the key;
- with the key, every signature is checked in the era it belongs to.

An unsigned chain (no ``REMORA_AUDIT_SIGNING_KEY``) has no signature format,
and gets no transition record.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["TRANSITION_EVENT", "V2_PREFIX", "chain_signature_format", "entry_signature",
           "is_transition", "signature_problems", "transition_payload"]

TRANSITION_EVENT = "AUDIT_VERSION_TRANSITION"
V2_PREFIX = "v2:"

def _v2_domain() -> str:
    from remora.crypto import SignatureDomain

    return SignatureDomain.AUDIT.value


def entry_signature(entry_hash: str, key: bytes, *, v2: bool) -> str:
    """The signature an entry carries in its era."""
    if not v2:
        return hmac.new(key, entry_hash.encode(), hashlib.sha256).hexdigest()
    from remora.crypto import SignatureDomain, preimage

    return V2_PREFIX + hmac.new(
        key, preimage(SignatureDomain.AUDIT, entry_hash.encode()), hashlib.sha256).hexdigest()


def transition_payload(previous_chain_head: str, *, first: bool) -> dict[str, Any]:
    """The AUDIT_VERSION_TRANSITION record. ``first``: the chain had no entries."""
    return {
        "event": TRANSITION_EVENT,
        "from": "none" if first else "v1",
        "to": "v2",
        "previous_chain_head": previous_chain_head,
        "new_domain": _v2_domain(),
    }


def is_transition(payload: Mapping[str, Any]) -> bool:
    return payload.get("event") == TRANSITION_EVENT


def signature_problems(entries: Sequence[Any], key: bytes) -> list[str]:
    """Era and signature findings for one chain, in order.

    ``key`` empty: only the structural (era) checks run, which need none.
    """
    problems: list[str] = []
    v2 = False
    for i, entry in enumerate(entries):
        payload = entry.payload if isinstance(entry.payload, Mapping) else {}
        if is_transition(payload):
            if v2:
                problems.append(f"audit_transition_repeated_at:{i}")
            if payload != transition_payload(entry.previous_hash, first=(i == 0)):
                problems.append(f"audit_transition_malformed_at:{i}")
            v2 = True
        signature = entry.signature or ""
        if signature:
            if v2 and not signature.startswith(V2_PREFIX):
                problems.append(f"audit_v1_after_transition_at:{i}")
            elif not v2 and signature.startswith(V2_PREFIX):
                problems.append(f"audit_v2_before_transition_at:{i}")
        if key and signature:
            if not hmac.compare_digest(entry_signature(entry.entry_hash, key, v2=v2), signature):
                problems.append(f"signature_mismatch_at:{i}")
        elif key and not signature:
            problems.append(f"signature_missing_at:{i}")
    return problems


def chain_signature_format(entries: Sequence[Any]) -> str:
    """``none``, ``v1``, ``v2`` or ``v1+v2``: what the chain's signatures are."""
    seen = {("v2" if (e.signature or "").startswith(V2_PREFIX) else "v1")
            for e in entries if e.signature}
    if not seen:
        return "none"
    return "+".join(sorted(seen))

