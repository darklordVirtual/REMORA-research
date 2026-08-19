# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Lifecycle/effect read projections over the audit chain (issue #241, slice 5).

Moved from servers/execution_api.py with the chain/outbox singletons turned
into explicit parameters. Projections are DERIVED, never stored: a stored
copy could drift from the chain it describes. No HTTP knowledge here.
"""
from __future__ import annotations

from typing import Any


def proposal_events(chain: Any, tenant: str, proposal_id: str) -> list[dict[str, Any]]:
    """Every chain entry belonging to one proposal, in chain order.

    A projection over the tenant audit chain — the store of record — not a
    second copy of it. Ordering is the chain's own sequence, so the trail
    cannot disagree with what was actually appended.
    """
    out: list[dict[str, Any]] = []
    for entry in chain.entries(tenant):
        payload = entry.payload
        if payload.get("proposal_id") != proposal_id:
            continue
        out.append({
            "sequence_no": entry.sequence_no,
            "entry_hash": entry.entry_hash,
            "event": payload.get("event"),
            "actor": payload.get("actor"),
            "payload": payload,
        })
    return out


def dispatch_projection(outbox: Any, tenant: str, proposal_id: str) -> dict[str, Any] | None:
    """The outbox's verdict for this proposal, if a dispatch was intended."""
    rows = outbox.rows_for_proposal(tenant, proposal_id)
    if not rows:
        return None
    row = rows[-1]
    return {
        "outbox_id": row.outbox_id,
        "state": row.state.value,
        "attempt_no": row.attempt_no,
        "worker_id": row.worker_id,
        "detail": row.detail,
        "terminal": row.is_terminal,
    }


def record_effect_verification(chain: Any, tenant: str, verification: Any, *,
                               submitted_by: str = "") -> dict[str, Any]:
    """Append one effect verification to the tenant audit chain.

    Appends; never edits the execution record it verifies. A verifier that
    could rewrite what it verifies produces no evidence, only a claim —
    so a later observation adds a record rather than correcting an
    earlier one, and the trail keeps the uncertainty that genuinely
    happened.

    Deployment-facing: the reader lives with the deployment (it holds the
    credentials), so runtime hands the resulting record back here rather
    than reaching out to a third party from inside governance.
    """
    record = verification.to_dict()
    entry = chain.append(tenant, {
        "event": "effect_verified",
        # Who OBSERVED is the verifier identity inside the record; this is
        # who submitted it. Keeping them separate matters when a record
        # arrives over the API: an auditor needs both.
        "actor": submitted_by or "effect_verifier",
        **record,
    })
    return {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}


#: EffectStatus -> lifecycle state. UNOBSERVABLE and VERIFIER_FAILED both
#: mean "we do not know", which is EFFECT_UNKNOWN and never a mismatch.
#: UNSUPPORTED is absent on purpose: a tool that declares no postcondition
#: was never observed, so it stays at its dispatch state. Mapping it to
#: EFFECT_VERIFIED would record "we did not look" as "we checked".
EFFECT_STATE = {
    "EFFECT_VERIFIED": "EFFECT_VERIFIED",
    "EFFECT_MISMATCH": "EFFECT_MISMATCH",
    "EFFECT_UNOBSERVABLE": "EFFECT_UNKNOWN",
    "EFFECT_VERIFIER_FAILED": "EFFECT_UNKNOWN",
}


def effect_projection(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The verification history for one proposal, latest verdict first.

    Always returns a section, even with nothing in it: a reader who finds
    no key cannot tell "not verified" from "this export predates the
    feature", and that ambiguity is exactly what the UNSUPPORTED status
    exists to remove.
    """
    history = [e["payload"] for e in events
               if e.get("event") == "effect_verified"]
    latest = history[-1] if history else None
    return {
        "status": latest["status"] if latest else None,
        "reason_code": latest["reason_code"] if latest else None,
        "verified_at": latest["verified_at"] if latest else None,
        "verifier_identity": latest["verifier_identity"] if latest else None,
        "expected_sha256": latest["expected_sha256"] if latest else None,
        "observed_sha256": latest["observed_sha256"] if latest else None,
        "history": history,
    }


def current_state(events: list[dict[str, Any]],
                  dispatch: dict[str, Any] | None) -> str:
    """Where the proposal stands, in lifecycle-model vocabulary.

    Derived, never stored: a stored copy could drift from the chain it is
    supposed to describe. The latest fact wins, which is why an effect
    verification outranks the dispatch verdict: "the dispatcher returned
    without raising" and "the approved change is present" are different
    claims, and only the second is about the world.
    """
    effect = effect_projection(events)
    if effect["status"] in EFFECT_STATE:
        return EFFECT_STATE[str(effect["status"])]
    if dispatch is not None and dispatch["terminal"]:
        return str(dispatch["state"])
    names = [str(e.get("event")) for e in events]
    if any(n.startswith("execution_") and n != "execution_authorized"
           for n in names):
        return "REFUSED"
    if "execution_authorized" in names:
        return "DISPATCHING"
    if "rejected" in names:
        return "REFUSED"
    if "approved" in names:
        return "AUTHORIZED"
    if "review_enqueued" in names or any(
        e["payload"].get("review_item_id") for e in events
    ):
        return "REVIEW_PENDING"
    if "assessed" in names:
        return "ASSESSED"
    return "PROPOSED"
