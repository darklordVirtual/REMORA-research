# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Resubmit-until-accept probing has to be visible in the audit trail.

The architect review made this binding: ABSTAIN immutability needs
enforcement, and ``superseded_proposal_id`` lineage so that
"resubmit-until-accept" probing is visible in audit and *can* trigger
ESCALATE.

The load-bearing design decision is that lineage is **derived, never
declared**. A client-supplied "this supersedes proposal X" field would be
defeated by the one caller it exists to catch: a prober simply omits it.
So the chain is the only input, and the caller cannot influence the
result by what it sends.

The second decision is that the escalation verdict is **recorded, not
acted on**. The key can only be as precise as the deployment's
declarations allow, so a legitimate agent calling one tool repeatedly can
look like a prober. Routing on a signal whose false-positive rate nobody
has measured would be the mistake this whole layer exists to avoid; it
ships as shadow eligibility first, exactly as the ESCALATE→VERIFY routing
change did.
"""
from __future__ import annotations

from remora.governance.proposal_lineage import (
    LineageKey,
    derive_lineage,
    lineage_key_for,
)

WINDOW = 3600
NOW = "2026-08-05T12:00:00+00:00"


def _entry(seq: int, *, decision: str, actor: str = "agent-1",
           tool: str = "create_issue", target: str = "prod",
           resource: str = "", proposal_id: str = "",
           timestamp: str = "2026-08-05T11:59:00+00:00") -> dict:
    """One chain entry as the audit chain stores it."""
    return {
        "sequence_no": seq,
        "timestamp": timestamp,
        "payload": {
            "event": "assessed",
            "proposal_id": proposal_id or f"p-{seq}",
            "actor": actor,
            "tool_name": tool,
            "decision": decision,
            "target_environment": target,
            "lineage_resource": resource,
        },
    }


def _key(**overrides) -> LineageKey:
    fields = {"actor": "agent-1", "tool_name": "create_issue",
              "target_environment": "prod", "resource": "",
              "basis": "tool_only"}
    fields.update(overrides)
    return LineageKey(**fields)


# ── The key ────────────────────────────────────────────────────────────────

def test_a_declared_target_resource_makes_the_key_precise() -> None:
    """When a signed ToolSpec declares which argument is the target, the
    key names it — two proposals about different objects are not the same
    attempt retried."""
    key = lineage_key_for(
        actor="agent-1", tool_name="create_issue",
        target_environment="prod",
        arguments={"repository": "acme/ops", "title": "x"},
        argument_roles={"repository": "target_resource"},
    )
    assert key.resource == "acme/ops"
    assert key.basis == "semantic_target"


def test_without_declared_roles_the_key_says_it_is_coarse() -> None:
    """A reader must be able to tell a precise match from a coarse one:
    the coarse key cannot distinguish repeated legitimate use from
    probing, and a verdict built on it deserves less weight."""
    key = lineage_key_for(
        actor="agent-1", tool_name="create_issue",
        target_environment="prod",
        arguments={"repository": "acme/ops"}, argument_roles={},
    )
    assert key.resource == ""
    assert key.basis == "tool_only"


def test_the_caller_cannot_influence_the_key_with_extra_arguments() -> None:
    """Only the declared role is read. An argument named to look like a
    role does not become one."""
    key = lineage_key_for(
        actor="agent-1", tool_name="create_issue",
        target_environment="prod",
        arguments={"target_resource": "pretend", "repository": "acme/ops"},
        argument_roles={"repository": "target_resource"},
    )
    assert key.resource == "acme/ops"


# ── Deriving the lineage ───────────────────────────────────────────────────

def test_a_first_proposal_has_no_lineage() -> None:
    result = derive_lineage([], _key(), now=NOW, window_seconds=WINDOW)
    assert result.superseded_proposal_id == ""
    assert result.prior_abstain_count == 0
    assert result.probe_sequence_no == 1
    assert result.escalation_eligible is False


def test_a_retry_after_an_abstain_names_what_it_supersedes() -> None:
    entries = [_entry(1, decision="abstain", proposal_id="p-first")]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.superseded_proposal_id == "p-first"
    assert result.prior_abstain_count == 1
    assert result.probe_sequence_no == 2


def test_the_most_recent_abstain_is_the_one_superseded() -> None:
    entries = [
        _entry(1, decision="abstain", proposal_id="p-old"),
        _entry(2, decision="abstain", proposal_id="p-recent"),
    ]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.superseded_proposal_id == "p-recent"
    assert result.prior_abstain_count == 2


def test_repeated_probing_becomes_eligible_for_escalation() -> None:
    entries = [_entry(i, decision="abstain") for i in range(1, 4)]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.probe_sequence_no == 4
    assert result.escalation_eligible is True


def test_eligibility_is_shadow_only_and_says_so() -> None:
    """The record must state that nothing was routed on this, or a reader
    would reasonably assume the escalation happened."""
    entries = [_entry(i, decision="abstain") for i in range(1, 4)]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.shadow_only is True
    assert result.escalation_eligible is True


# ── What must NOT count ────────────────────────────────────────────────────

def test_another_actor_does_not_inherit_lineage() -> None:
    entries = [_entry(1, decision="abstain", actor="agent-2")]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.prior_abstain_count == 0


def test_another_tool_does_not_count() -> None:
    entries = [_entry(1, decision="abstain", tool="delete_issue")]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.prior_abstain_count == 0


def test_another_target_environment_does_not_count() -> None:
    entries = [_entry(1, decision="abstain", target="staging")]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.prior_abstain_count == 0


def test_a_different_declared_resource_does_not_count() -> None:
    """Two issues in two repositories are two actions, not one retried."""
    entries = [_entry(1, decision="abstain", resource="acme/other")]
    result = derive_lineage(
        entries, _key(resource="acme/ops", basis="semantic_target"),
        now=NOW, window_seconds=WINDOW,
    )
    assert result.prior_abstain_count == 0


def test_an_accepted_proposal_is_not_a_probe() -> None:
    """Probing means being refused and trying again. A call that was
    allowed is the system working."""
    entries = [_entry(1, decision="accept"), _entry(2, decision="verify")]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.prior_abstain_count == 0
    assert result.superseded_proposal_id == ""


def test_abstains_outside_the_window_do_not_accumulate() -> None:
    """Otherwise every long-lived tenant eventually looks like a prober,
    and the signal decays into a function of account age."""
    entries = [_entry(1, decision="abstain",
                      timestamp="2026-08-04T12:00:00+00:00")]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.prior_abstain_count == 0
    assert result.superseded_proposal_id == ""


def test_an_unparseable_timestamp_is_excluded_rather_than_trusted() -> None:
    """A record we cannot place in time cannot support a claim about a
    rate. Counting it would let a malformed entry manufacture eligibility."""
    entries = [_entry(1, decision="abstain", timestamp="not-a-timestamp")]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.prior_abstain_count == 0


def test_non_assessment_events_are_ignored() -> None:
    entries = [{"sequence_no": 1, "timestamp": "2026-08-05T11:59:00+00:00",
                "payload": {"event": "effect_verified", "actor": "agent-1",
                            "decision": "abstain"}}]
    result = derive_lineage(entries, _key(), now=NOW, window_seconds=WINDOW)
    assert result.prior_abstain_count == 0


# ── The record ─────────────────────────────────────────────────────────────

def test_the_result_serializes_with_its_basis_and_window() -> None:
    """The verdict travels with the two things needed to judge it: how
    precise the key was, and over what window it was counted."""
    entries = [_entry(1, decision="abstain", proposal_id="p-first")]
    payload = derive_lineage(
        entries, _key(), now=NOW, window_seconds=WINDOW,
    ).to_dict()
    assert payload["superseded_proposal_id"] == "p-first"
    assert payload["lineage_key_basis"] == "tool_only"
    assert payload["window_seconds"] == WINDOW
    assert payload["shadow_only"] is True
