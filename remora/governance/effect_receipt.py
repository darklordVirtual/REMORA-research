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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Sequence

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


class ReceiptRefused(Exception):
    """The receipt cannot be bound to a dispatch, or contradicts itself.

    Carries a machine-readable ``reason`` because these refusals are routed on,
    not read: a caller must be able to tell "no such dispatch" from "stale
    observation" without matching message text.
    """

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
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def resolve_lineage(events: Sequence[Mapping[str, Any]]) -> DispatchLineage:
    """The dispatch this proposal actually attempted, or a refusal.

    Reads the audit chain rather than trusting the caller. An assessed
    proposal with no dispatch event has no lineage, which is the case that
    produced the original false VERIFIED.
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
    executed = bool(payload.get("tool_executed"))
    state_unknown = bool(payload.get("state_unknown"))
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
) -> tuple[DispatchLineage, EffectStatus]:
    """Bind a receipt to its dispatch and adjudicate the claimed status.

    Returns the resolved lineage and adjudicated status, or raises
    ``ReceiptRefused`` with a specific reason. The order of checks is the order
    of the rule, so the first failure names the first missing conjunct.
    """
    lineage = resolve_lineage(events)

    # ── the receipt must be about THIS dispatch ────────────────────────────
    if proposal_id != lineage.proposal_id:
        raise ReceiptRefused("proposal_mismatch",
                             "the receipt names a different proposal")
    # For a SETTLED verdict the binding fields are mandatory, not optional.
    # Treating an empty field as "no opinion" meant a receipt could skip every
    # comparison by simply omitting what it would have been compared against,
    # which is the opposite of binding.
    settling = claimed_status in (EffectStatus.VERIFIED, EffectStatus.MISMATCH)
    if settling:
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
    if trusted_verifiers and verifier_identity not in trusted_verifiers:
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
    attempted_at = _parse(lineage.attempted_at)
    if observed_at is None:
        raise ReceiptRefused("verified_at_unparseable",
                             "verified_at is not an ISO-8601 timestamp")
    if attempted_at is not None and observed_at < attempted_at:
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
