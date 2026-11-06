# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A settled effect verdict is accepted only when bound to a real dispatch.

The recorder used to check that a proposal existed and then store whatever
status the caller supplied. A proposal that had been assessed and never
executed could therefore be recorded ``EFFECT_VERIFIED``, and the lifecycle
projection would report it as such. That is a false VERIFIED -- the highest-risk
verifier error in this project's own model, because every other failure mode
tells you something did not happen and this one tells you something did.

The rule, and the shape of this module:

    EFFECT_VERIFIED =
        valid_dispatch_lineage
        AND authoritative_observation
        AND observation_recorded_for_re_checking
        AND freshness_valid
        AND receipt_not_replayed

The third conjunct is deliberately weaker than "the postcondition matches".
REMORA holds the digests of the comparison, not the maps or the comparison
rules, so it cannot re-run the check -- and a module that pretended to would be
making exactly the kind of unearned claim this project keeps finding. What it
enforces is that the verdict carries both sides, so an auditor CAN re-check it.

Each conjunct is a separate check with its own refusal reason, because an
operator reading a refusal needs to know which one failed. Collapsing them into
one "invalid receipt" would make the record unreadable later, which is the same
argument the recorder already makes for keeping the five statuses distinct.

What this module does NOT do
----------------------------
It does not make REMORA the verifier. Verification runs where the credentials
are, which is the deployment's process; what crosses back is an attestation by
a named verifier. This module decides whether that attestation is *about this
dispatch* and whether its own numbers support the verdict it claims. Those are
different questions from "did the effect happen", and only the deployment can
answer the third.

What to call this, precisely
----------------------------
Not "REMORA derives VERIFIED". An earlier revision of this module said that and
it was an overclaim: REMORA cannot evaluate the postcondition rule, so it does
not compute the verdict. What it does is **accept or refuse a lineage-bound
attestation** -- it decides whether a submitted verdict is about a real
dispatch, is fresh, is attributable, is unreplayed, and carries the evidence an
auditor would need. The verdict itself still comes from the deployment's
verifier. Calling that derivation would be the same species of unearned claim
this module exists to stop.

The distinction that motivates it: an attestation asserting VERIFIED is a claim,
and a claim needs provenance. A measurement whose provenance is unverified is
just another claim -- which this project learned by writing a regression report
from a probe that had read the wrong key (NEGATIVE_RESULTS section 49).
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from remora.errors import RemoraError
from remora.governance.effect_verification import EffectStatus

__all__ = [
    "MAX_CLOCK_SKEW",
    "DispatchLineage",
    "ReceiptRefused",
    "adjudicate_status",
    "resolve_lineage",
    "verify_receipt",
]

#: How far ahead of the server an observation may be dated. A verifier's clock
#: can drift; it cannot legitimately be an hour into the future, and a receipt
#: dated forward would otherwise sit permanently "fresher" than any dispatch.
MAX_CLOCK_SKEW = timedelta(minutes=5)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# A receipt needs an actual, timezone-aware instant. datetime.fromisoformat()
# also accepts date-only and naive values, which do not establish ordering.
_RECEIPT_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)

#: Reason codes ``verify_declared_delta`` emits, with the one status each
#: belongs to. Reason codes are otherwise free text from the deployment's
#: verifier; these are refused only when paired with a different status,
#: because a VERIFIED record saying "field mismatch" contradicts itself.
_REASON_STATUS: Mapping[str, EffectStatus] = {
    "postcondition_verified": EffectStatus.VERIFIED,
    "postcondition_field_mismatch": EffectStatus.MISMATCH,
    "postcondition_version_not_advanced": EffectStatus.MISMATCH,
    # Revisions unchanged across the dispatch and the delta absent (server).
    "postcondition_effect_absent": EffectStatus.MISMATCH,
    "postcondition_no_attributable_change": EffectStatus.UNOBSERVABLE,
    "postcondition_object_absent": EffectStatus.UNOBSERVABLE,
    "postcondition_target_mismatch": EffectStatus.UNOBSERVABLE,
    "empty_postcondition": EffectStatus.UNSUPPORTED,
}


class ReceiptRefused(RemoraError):
    """The receipt cannot be bound to a dispatch, or contradicts itself.

    Carries a machine-readable ``reason`` because these refusals are routed on,
    not read: a caller must be able to tell "no such dispatch" from "stale
    observation" without matching message text.
    """

    code = "receipt_refused"
    category = "governance"

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason


@dataclass(frozen=True)
class DispatchLineage:
    """The dispatch a receipt must be about, read from the audit chain.

    Every field here is server-derived. None of it is taken from the receipt:
    the receipt is checked *against* this, which is the whole point.
    """

    proposal_id: str
    tool_call_hash: str
    grant_jti: str
    dispatch_id: str
    executed: bool
    state_unknown: bool
    attempted_at: str
    execution_context_hash: str = ""
    execution_id: str = ""
    #: The principals that proposed or executed the call. Where separation is
    #: required an effect verifier must be none of them (RMR-AUD-004): the
    #: agent that ran a call does not independently observe its effect.
    executors: frozenset[str] = frozenset()

    @property
    def effect_possible(self) -> bool:
        """Whether an effect could have occurred at all.

        True for a successful dispatch, and also for one whose outcome is
        unknown -- a lost response does not mean nothing happened, and
        forbidding a later authoritative check from resolving it would leave
        the operator with no way to close an UNKNOWN honestly.
        """
        return self.executed or self.state_unknown


def _parse(ts: str) -> datetime | None:
    """Parse a full timestamp with an explicit offset, never invent UTC."""
    if not isinstance(ts, str) or not _RECEIPT_INSTANT.fullmatch(ts):
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _payload(event: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if event is None:
        return {}
    return event.get("payload") or event


def _assessment(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for event in events:
        if event.get("event") == "assessed":
            return event
    return None


#: Decisions that may lead to a dispatch, and whether a human approval must
#: stand between the assessment and the dispatch.
_DISPATCHABLE = {"accept": False, "verify": True, "escalate": True}


def _authorization_of(events: Sequence[Mapping[str, Any]],
                      result: Mapping[str, Any]) -> Mapping[str, Any]:
    """The decision path that allowed this dispatch, or a refusal (RMR-AUD-004).

    An ``execution_result`` says a tool ran. It does not say the policy let it.
    Before this check a result in a trail that also held an ABSTAIN or a
    rejection carried an effect to EFFECT_VERIFIED. The chain must now show the
    whole path: an assessment that could dispatch, no rejection, an approval
    where the decision needed one, and an allowed authorization for exactly
    this grant and call.
    """
    decision = str(_payload(_assessment(events)).get("decision") or "").lower()
    if decision in ("abstain", "deny", "reject", "rejected"):
        raise ReceiptRefused(
            "dispatched_after_deny",
            f"the proposal was assessed {decision}: no dispatch was allowed, so "
            "no effect can be attested to")
    if decision not in _DISPATCHABLE:
        raise ReceiptRefused(
            "assessment_decision_unknown",
            "the audit trail has no assessment decision that allows a dispatch")
    if any(e.get("event") == "rejected" for e in events):
        raise ReceiptRefused(
            "dispatched_after_deny",
            "a reviewer rejected this proposal: no dispatch was allowed")
    jti = str(result.get("grant_jti", ""))
    call_hash = str(result.get("tool_call_hash", ""))
    approved_live = False
    for event in events:
        ev_name = event.get("event")
        if ev_name == "approved":
            approved_live = True
        elif ev_name in ("execution_approval_expired", "execution_approval_invalidated"):
            approved_live = False
        if ev_name != "execution_authorized":
            continue
        auth = _payload(event)
        # ``is True``: the string "true" is not an allowed PEP check.
        if (auth.get("pep_allowed") is True and jti
                and str(auth.get("grant_jti", "")) == jti
                and str(auth.get("tool_call_hash", "")) == call_hash):
            if _DISPATCHABLE[decision] and not approved_live:
                raise ReceiptRefused(
                    "dispatched_without_approval",
                    f"a {decision} decision needs an unvoided approval before "
                    "dispatch, and the audit trail has none")
            return auth
    if _DISPATCHABLE[decision] and not approved_live:
        raise ReceiptRefused(
            "dispatched_without_approval",
            f"a {decision} decision needs an approval before dispatch, and the "
            "audit trail has none")
    raise ReceiptRefused(
        "dispatch_not_authorized",
        "no allowed execution_authorized record names this dispatch's grant "
        "and call")


def resolve_lineage(events: Sequence[Mapping[str, Any]], *,
                    require_decision_path: bool = True) -> DispatchLineage:
    """The dispatch this proposal actually attempted, or a refusal.

    Reads the audit chain rather than trusting the caller. An assessed
    proposal with no dispatch event has no lineage, which is the case that
    produced the original false VERIFIED.

    ``require_decision_path`` (default on) also requires the chain to show the
    policy allowed the dispatch (see ``_authorization_of``). Only a runtime
    whose chain has no decision records turns it off: the surface runtime
    gates its dispatch in process on a one-use assessment handle and a lease,
    and records a refused dispatch as not executed.
    """
    result = None
    for event in events:
        if event.get("event") == "execution_result":
            result = event      # last one wins: a retry supersedes
    if result is None:
        raise ReceiptRefused(
            "no_dispatch",
            "this proposal has no execution_result in its audit trail: nothing "
            "was dispatched, so there is no effect to attest to")

    # The projection nests the appended record under "payload" and carries the
    # chain's own timestamp beside it. Both are read from the chain; nothing
    # here comes from the receipt.
    payload = result.get("payload") or result
    authorized = (_authorization_of(events, payload) if require_decision_path
                  else {})
    # A string such as "false" is truthy in Python. Audit metadata must not
    # become positive execution evidence through a bool() coercion. Absent
    # fields default to False; an unknown can only be established explicitly.
    for field in ("tool_executed", "state_unknown"):
        if field in payload and type(payload[field]) is not bool:
            raise ReceiptRefused(
                "dispatch_flags_malformed",
                f"{field} must be a JSON boolean in the recorded dispatch",
            )
    executed = payload.get("tool_executed", False)
    state_unknown = payload.get("state_unknown", False)
    lineage = DispatchLineage(
        proposal_id=str(payload.get("proposal_id", "")),
        tool_call_hash=str(payload.get("tool_call_hash", "")),
        grant_jti=str(payload.get("grant_jti", "")),
        # The grant is minted once per authorization and consumed once, so it
        # is the dispatch's identity. A separate id would be a second thing to
        # keep in step with it.
        dispatch_id=str(payload.get("grant_jti", "")),
        executed=executed,
        state_unknown=state_unknown,
        attempted_at=str(result.get("timestamp") or ""),
        execution_context_hash=str(payload.get("execution_context_hash", "")),
        execution_id=str(payload.get("execution_id", "")),
        executors=frozenset(
            str(who) for who in (
                _payload(_assessment(events)).get("actor"),
                authorized.get("actor"), authorized.get("executed_by"),
                payload.get("actor"), payload.get("executed_by"))
            if who),
    )
    if not lineage.effect_possible:
        raise ReceiptRefused(
            "dispatch_did_not_execute",
            "the dispatch was refused and its outcome is not unknown, so no "
            "effect can be attested to")
    return lineage


def adjudicate_status(
    claimed: EffectStatus,
    *,
    expected_sha256: str,
    observed_sha256: str,
) -> EffectStatus:
    """The status the observation supports, which may not be the one claimed.

    VERIFIED requires that the verifier recorded BOTH sides of the comparison
    it performed. A verdict with nothing recorded is an assertion, not an
    observation, and an auditor cannot re-check it later.

    What this deliberately does NOT do is require the two digests to be equal.
    An earlier version of this function did, and it was wrong. The digests hash
    two different maps -- the expected FIELDS and the observed ROW -- and the
    comparison between them is rule-based
    (``PostconditionContract.comparison_rules``, e.g. ``content: hash``). A
    passing verification routinely produces different digests, so equality
    would have refused every legitimate VERIFIED the SDK produces. Caught by
    ``tests/test_sdk_effect_roundtrip.py``, which was asserting the real
    contract while this module was inventing a different one.

    REMORA therefore does not re-run the comparison, and does not claim to: it
    holds the digests, not the maps or the rules. What it enforces is that the
    verdict is bound to a real dispatch, is fresh, comes from a trusted
    verifier, is not a replay, and carries the evidence an auditor would need
    to re-check it. Those are the parts REMORA can actually establish.

    UNOBSERVABLE, VERIFIER_FAILED and UNSUPPORTED remain unresolved reports.
    MISMATCH is terminal and carries the same evidentiary burden as VERIFIED:
    a negative system claim is still a claim, and an evidence-free mismatch
    could otherwise occupy the terminal slot ahead of a real observation.
    """
    if claimed in (EffectStatus.UNOBSERVABLE, EffectStatus.VERIFIER_FAILED,
                   EffectStatus.UNSUPPORTED):
        # "We do not know" and "there was nothing to check" carry no evidence
        # because there is none to carry. Demanding digests here would push a
        # verifier towards inventing them.
        return claimed

    # VERIFIED and MISMATCH are both SETTLED verdicts, and both are load-bearing:
    # one closes a proposal as done, the other as wrong. An earlier revision
    # required evidence for VERIFIED alone, which let a MISMATCH with no
    # observation behind it take the terminal slot and block a later legitimate
    # verification. Equal burden for positive and negative claims is the rule
    # this project arrived at; applying it to one and not the other was the
    # same asymmetry in miniature.
    for name, value in (("expected_sha256", expected_sha256),
                        ("observed_sha256", observed_sha256)):
        if not value:
            raise ReceiptRefused(
                "settled_without_observation",
                f"{claimed.value} requires {name}: a settled verdict recording "
                "neither side of its own comparison cannot be re-checked, and "
                "an unre-checkable verdict is an assertion")
        if not _SHA256.match(value):
            raise ReceiptRefused(
                "digest_malformed",
                f"{name} is not a lowercase hex SHA-256 digest")
    return claimed


def verify_receipt(
    *,
    events: Sequence[Mapping[str, Any]],
    proposal_id: str,
    claimed_status: EffectStatus,
    tool_call_hash: str,
    grant_jti: str,
    expected_sha256: str,
    observed_sha256: str,
    verified_at: str,
    verifier_identity: str,
    trusted_verifiers: Sequence[str],
    already_recorded: Sequence[Mapping[str, Any]] = (),
    reason_code: str = "",
    require_decision_path: bool = True,
) -> tuple[DispatchLineage, EffectStatus]:
    """Bind a receipt to its dispatch and adjudicate the claimed status.

    Returns the resolved lineage and adjudicated status, or raises
    ``ReceiptRefused`` with a specific reason. The order of checks is the order
    of the rule, so the first failure names the first missing conjunct.

    ``trusted_verifiers`` is an allowlist: empty trusts nobody. A caller that
    has already bound the identity to an authenticated principal passes that
    one identity.
    """
    lineage = resolve_lineage(events, require_decision_path=require_decision_path)

    owner = _REASON_STATUS.get(reason_code)
    if owner is not None and owner is not claimed_status:
        raise ReceiptRefused(
            "reason_status_contradiction",
            f"reason {reason_code!r} belongs to {owner.value}, not "
            f"{claimed_status.value}; a self-contradicting record is not "
            "evidence of either")

    # ── the receipt must be about THIS dispatch ────────────────────────────
    if proposal_id != lineage.proposal_id:
        raise ReceiptRefused("proposal_mismatch",
                             "the receipt names a different proposal")
    # For a SETTLED verdict the binding fields are mandatory, not optional.
    # Treating an empty field as "no opinion" meant a receipt could skip every
    # comparison by simply omitting what it would have been compared against,
    # which is the opposite of binding.
    settling = claimed_status in (EffectStatus.VERIFIED, EffectStatus.MISMATCH)
    # UNSUPPORTED is terminal as well: it takes the one settled slot, so an
    # unbound UNSUPPORTED could close a dispatch it never named and turn the
    # later real observation into a "replay".
    if claimed_status.is_terminal:
        for name, value in (("tool_call_hash", tool_call_hash),
                            ("grant_jti", grant_jti)):
            if not value:
                raise ReceiptRefused(
                    "binding_incomplete",
                    f"{claimed_status.value} requires {name}: a verdict that "
                    "names nothing to be compared against is not bound to "
                    "anything")
    if tool_call_hash and tool_call_hash != lineage.tool_call_hash:
        raise ReceiptRefused(
            "tool_call_hash_mismatch",
            "the receipt attests to a different call than the one dispatched")
    if grant_jti and grant_jti != lineage.grant_jti:
        raise ReceiptRefused(
            "dispatch_mismatch",
            "the receipt carries another dispatch's grant identity")

    # ── who observed it ────────────────────────────────────────────────────
    # An allowlist rather than merely a non-empty name. "Signed by someone" is
    # not the same as "signed by someone this deployment trusts to look".
    # Empty means nobody is trusted. It used to mean "no restriction", which
    # left the safety of this check to every caller remembering to bind first.
    if verifier_identity not in trusted_verifiers:
        raise ReceiptRefused(
            "untrusted_verifier",
            f"{verifier_identity!r} is not a verifier this deployment trusts")

    # ── one SETTLED verdict per dispatch ───────────────────────────────────
    # Advisory only. This read-then-check cannot be atomic against a concurrent
    # submission, so the binding guarantee lives in
    # TenantAuditChain.append_once(), which commits the uniqueness key and the
    # audit entry in one transaction. This is kept because it produces the
    # specific refusal reason before any write is attempted; it must never be
    # the only check.
    # Not "one receipt per dispatch". UNOBSERVABLE and VERIFIER_FAILED mean
    # "we do not know yet", and a later observation resolving one of them is
    # the mechanism by which an unknown gets closed honestly -- forbidding it
    # would leave every timed-out read permanently unresolvable.
    #
    # What is forbidden is re-verifying a dispatch that already has a terminal
    # verdict. Once VERIFIED or MISMATCH is recorded, a second verdict would
    # either overwrite evidence or let a caller keep submitting until one is
    # accepted.
    for prior in already_recorded:
        prior_dispatch = str(prior.get("dispatch_id") or "")
        if lineage.dispatch_id and prior_dispatch != lineage.dispatch_id:
            continue
        try:
            prior_status = EffectStatus(str(prior.get("status", "")))
        except ValueError:
            continue
        if prior_status.is_terminal:
            raise ReceiptRefused(
                "receipt_replayed",
                f"this dispatch already has a settled verdict "
                f"({prior_status.value}); a second would overwrite evidence")

    # ── the observation must postdate the attempt ──────────────────────────
    if settling and not verified_at:
        # Substituting the server's clock for a missing observation time
        # fabricates the freshness it is supposed to check.
        raise ReceiptRefused(
            "observation_time_missing",
            f"{claimed_status.value} requires verified_at: when the verifier "
            "looked is part of what makes the observation evidence")
    observed_at = _parse(verified_at)
    if observed_at is None:
        raise ReceiptRefused(
            "verified_at_unparseable",
            "verified_at must be a timezone-aware ISO-8601 instant",
        )
    attempted_at = _parse(lineage.attempted_at)
    if attempted_at is None:
        # A missing or malformed source timestamp must not silently skip the
        # chronological check and turn an attestation into EFFECT_VERIFIED.
        raise ReceiptRefused(
            "dispatch_time_unparseable",
            "the audit dispatch timestamp is missing or not an aware instant",
        )
    if observed_at < attempted_at:
        # A reading taken before the call cannot be evidence that the call
        # worked, however well-formed it is. This is the check that catches a
        # pre-existing matching state being passed off as a verification.
        raise ReceiptRefused(
            "observation_precedes_dispatch",
            f"the observation is dated {verified_at}, before the dispatch at "
            f"{lineage.attempted_at}")

    # ── and finally, what the numbers actually support ─────────────────────
    if observed_at > datetime.now(UTC) + MAX_CLOCK_SKEW:
        raise ReceiptRefused(
            "observation_in_the_future",
            f"the observation is dated {verified_at}, more than "
            f"{MAX_CLOCK_SKEW} ahead of this server")

    adjudicated = adjudicate_status(claimed_status,
                                    expected_sha256=expected_sha256,
                                    observed_sha256=observed_sha256)
    return lineage, adjudicated
