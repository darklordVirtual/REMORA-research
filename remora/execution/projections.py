# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Lifecycle/effect read projections over the audit chain (issue #241, slice 5).

Moved from servers/execution_api.py with the chain/outbox singletons turned
into explicit parameters. Projections are DERIVED, never stored: a stored
copy could drift from the chain it describes. No HTTP knowledge here.
"""
from __future__ import annotations

from remora.errors import RemoraError

from typing import Any


class EffectVerificationReplay(RemoraError, RuntimeError):
    """A settled effect receipt already exists for this dispatch."""

    code = "effect_verification_replay"
    category = "execution"


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
            # The chain's own time, exposed so an effect receipt can be
            # refused for predating the dispatch it claims to observe. The
            # payload has no timestamp of its own and must not grow one: the
            # chain is the store of record for when something happened.
            "timestamp": entry.timestamp,
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
                               submitted_by: str = "",
                               dispatch_id: str = "",
                               settled_dispatch_id: str = "") -> dict[str, Any]:
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
    payload = {
        "event": "effect_verified",
        # Who OBSERVED is the verifier identity inside the record; this is
        # who submitted it. Keeping them separate matters when a record
        # arrives over the API: an auditor needs both.
        "actor": submitted_by or "effect_verifier",
        # The dispatch this receipt attests to, so a second receipt for the
        # same dispatch is detectable as a replay rather than appended as a
        # second opinion.
        "dispatch_id": dispatch_id,
        **record,
    }
    if settled_dispatch_id:
        # Receipt uniqueness and evidence recording must commit together.
        # Reserving a slot in a separate store first creates a crash window:
        # the slot can survive while the audit append fails, after which every
        # retry is refused although no re-checkable observation exists.
        entry = chain.append_once(
            tenant, f"effect-receipt:{settled_dispatch_id}", payload)
        if entry is None:
            raise EffectVerificationReplay(
                "this dispatch already has a settled effect verdict")
    else:
        # Non-terminal observations deliberately remain appendable: UNKNOWN
        # must be resolvable by a later authoritative observation.
        entry = chain.append(tenant, payload)
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


def envelope_projection(
    events: list[dict[str, Any]],
    dispatch: dict[str, Any] | None,
    *,
    proposal_id: str,
    tenant: str,
) -> "DecisionEnvelope":
    """One DecisionEnvelope for one proposal, derived from the chain (#37).

    The envelope is the canonical governance contract, but the execution path
    never built one: it appended lifecycle records and left ``EffectBlock`` at
    its defaults, so the contract described assessments and the chain described
    executions, and nothing joined them.

    This closes that as a **projection**, not a second store. The chain is the
    record; an envelope assembled here is a view of it, so the two cannot
    drift. The alternative — writing an envelope alongside the chain — creates
    exactly the divergence the lifecycle records exist to prevent.

    Nothing is invented. Every field comes from a recorded payload, and a field
    with no record stays at its default: an envelope that guessed at a risk
    tier would be worse than one that admits it does not have it.
    """
    from remora.governance.envelope import (
        AssessmentBlock,
        AuditBlock,
        DecisionEnvelope,
        EffectBlock,
        GateBlock,
        RequestBlock,
    )

    by_event: dict[str, dict[str, Any]] = {}
    for event in events:
        name = str(event.get("event") or "")
        # Latest wins: a proposal may be assessed, refused and re-presented,
        # and the envelope describes where it ended up.
        by_event[name] = event
    assessed = (by_event.get("assessed") or {}).get("payload", {})
    result = (by_event.get("execution_result") or {}).get("payload", {})
    authorized = (by_event.get("execution_authorized") or {}).get("payload", {})

    effect = effect_projection(events)
    state = current_state(events, dispatch)

    executed = bool(result.get("executed"))
    if not executed and dispatch is not None:
        executed = dispatch.get("state") == "SUCCEEDED"

    ledger: dict[str, Any] = {}
    if "execution_result" in by_event:
        ledger = {
            "sequence_no": by_event["execution_result"]["sequence_no"],
            "entry_hash": by_event["execution_result"]["entry_hash"],
        }
    if dispatch is not None:
        ledger["outbox_id"] = dispatch.get("outbox_id")
        ledger["outbox_state"] = dispatch.get("state")
    if authorized.get("grant_jti"):
        ledger["grant_jti"] = authorized["grant_jti"]
    if effect["status"] is not None:
        # Who observed, and what they reported. Carried separately from
        # effect_outcome so a reader can tell a verified effect from an
        # unverified dispatch without re-deriving the mapping.
        ledger["effect_status"] = effect["status"]
        ledger["effect_verifier_identity"] = effect["verifier_identity"]

    return DecisionEnvelope(
        request=RequestBlock(
            request_id=proposal_id,
            domain="",
            risk_tier=str(assessed.get("risk_tier") or ""),
            proposed_action=str(assessed.get("tool_name") or ""),
            action_type=str(assessed.get("action_type") or ""),
            target_environment=str(assessed.get("target_environment") or ""),
        ),
        assessment=AssessmentBlock(
            # The execution surface runs no oracle swarm and no thermodynamic
            # assessment: those belong to /v1/assess. Empty here is the honest
            # value, not a gap to be filled from somewhere else.
            oracle_votes=[],
            thermodynamic={},
            evidence_quality={},
            policy_triggers=list(assessed.get("reasons") or []),
        ),
        gate=GateBlock(outcome=str(assessed.get("decision") or "")),
        effect=EffectBlock(
            executed=executed,
            tool_call_hash=(result.get("tool_call_hash")
                            or assessed.get("tool_call_hash")),
            # The lifecycle state, which already ranks an effect verification
            # above a dispatch verdict: "the dispatcher returned" and "the
            # approved change is present" are different claims.
            effect_outcome=state,
            ledger_entry=ledger,
        ),
        audit=AuditBlock(
            policy_version=str(assessed.get("policy_version") or ""),
            tenant_id=tenant,
            actor_identity=(assessed.get("actor") or None),
            tool_args_hash=(assessed.get("tool_call_hash") or None),
            tool_contract_bundle_hash=(
                assessed.get("tool_contract_bundle_hash") or None),
            intent_authority_hash=(
                assessed.get("intent_authority_hash") or None),
            # The chain entry hash of the last record for this proposal is the
            # integrity anchor a reader can recheck; it is NOT an envelope
            # chain hash, and the two are not comparable (see AuditBlock).
            hash=(events[-1]["entry_hash"] if events else None),
        ),
    )


if False:  # pragma: no cover - typing only, avoids a runtime import cycle
    from remora.governance.envelope import DecisionEnvelope
