# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""GitHub issue creation — the first closed postcondition loop (FT-04).

Chosen as the first integration (handoff gate §2.1) because the result is
observable through an API, readable back, and demonstrable without
irreversible consequences. The point is not GitHub; it is that one
integration proves the whole loop end to end, so the next reader has a
worked example instead of an interface.

The reader is a **protocol**, not a client. This module never opens a
socket: a deployment supplies something that can read an issue back, and
governance compares what it returns against the declared delta. That
keeps the verification logic testable without a third party's
availability deciding whether the suite passes — and it keeps credentials
where they belong, with the deployment.

The comparison follows the frozen contract: **declared delta only**.
GitHub attaches fields nobody declared (``updated_at``, ``reactions``,
``state``), and treating their presence as drift would make every issue
look mismatched.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from remora.governance.effect_verification import (
    EffectStatus,
    EffectVerification,
    PostconditionContract,
    _digest,
    verify_declared_delta,
)

__all__ = [
    "GitHubIssueReader",
    "GitHubIssueUnauthorized",
    "GitHubIssueUnavailable",
    "build_issue_postcondition",
    "verify_issue_effect",
]

TOOL_ID = "create_github_issue"
VERIFIER_IDENTITY = "github.issue_reader/v1"


class GitHubIssueUnavailable(Exception):
    """The issue could not be read in time. Says nothing about correctness."""


class GitHubIssueUnauthorized(Exception):
    """The verifier lost the access it needs. Also says nothing about it."""


@runtime_checkable
class GitHubIssueReader(Protocol):
    """Reads an issue back. Deployment-supplied; never created here.

    Returns the issue as a mapping, or ``None`` when it does not exist.
    Raises :class:`GitHubIssueUnavailable` or
    :class:`GitHubIssueUnauthorized` for the two failure modes that must
    NOT be reported as effect mismatches.
    """

    def read_issue(self, repository: str, issue_number: int) -> dict | None:
        ...


def build_issue_postcondition(
    *,
    repository: str,
    title: str,
    body: str,
    labels: list[str] | tuple[str, ...],
    expected_author: str,
) -> PostconditionContract:
    """The delta an approved issue-creation claims it will produce.

    ``body`` is compared by hash rather than by value: issue bodies are
    long, and storing the whole approved text in the contract would put
    user content into every audit record for no verification gain.

    ``author`` is declared because an issue created by someone else is not
    this action's effect, however well every other field matches.
    """
    return PostconditionContract(
        tool_id=TOOL_ID,
        reader="github.read_issue",
        target_selector={"repository": repository},
        expected_fields={
            "repository": repository,
            "title": title,
            "body": _digest(body),
            "labels": sorted(labels),
            "author": expected_author,
        },
        comparison_rules={"body": "hash"},
        observation_deadline_seconds=30,
        repeatable=True,
        evidence_fields=("repository", "number", "title", "labels", "author"),
    )


def _normalize(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Project the observed issue onto the declared fields.

    Labels arrive either as strings or as objects with a ``name``; both
    normalize to sorted names so an ordering difference is not reported as
    drift. Fields nobody declared are dropped here rather than compared —
    the contract's scope is the declaration, not the payload.

    The body is passed through RAW: the ``hash`` comparison rule does the
    hashing. Hashing it here too would compare a digest against a digest
    of that digest, and every body would look changed.
    """
    labels = issue.get("labels") or []
    names = sorted(
        label.get("name", "") if isinstance(label, Mapping) else str(label)
        for label in labels
    )
    return {
        "repository": issue.get("repository"),
        "title": issue.get("title"),
        "body": issue.get("body"),
        "labels": names,
        "author": issue.get("author"),
    }


def verify_issue_effect(
    contract: PostconditionContract,
    reader: GitHubIssueReader,
    *,
    issue_number: int,
    proposal_id: str,
    execution_id: str,
    toolspec_hash: str,
) -> EffectVerification:
    """Read the issue back and compare it against the approved delta.

    Every failure mode maps to a status that is honest about what is
    known: a timeout or an absent issue is UNOBSERVABLE (we could not
    look), a broken or unauthorized reader is VERIFIER_FAILED (our
    instrument failed), and only an issue we actually read and found
    different is MISMATCH. None of them re-runs the action.
    """
    def _fail(status: EffectStatus, reason: str, detail: str) -> EffectVerification:
        return EffectVerification.build(
            proposal_id=proposal_id, execution_id=execution_id,
            tool_id=contract.tool_id, toolspec_hash=toolspec_hash,
            status=status, reason_code=reason,
            verifier_identity=VERIFIER_IDENTITY,
            expected=contract.expected_fields, observed={}, detail=detail,
        )

    if not issue_number:
        # Execution reported success but gave us nothing to look at. We
        # cannot know, so we say so rather than assuming either way.
        return _fail(
            EffectStatus.UNOBSERVABLE, "postcondition_object_absent",
            "execution returned no issue number; nothing to observe",
        )

    repository = str(contract.target_selector.get("repository", ""))
    try:
        issue = reader.read_issue(repository, int(issue_number))
    except GitHubIssueUnavailable as exc:
        return _fail(
            EffectStatus.UNOBSERVABLE, "postcondition_read_timeout",
            f"the issue could not be read in time: {exc}",
        )
    except GitHubIssueUnauthorized as exc:
        return _fail(
            EffectStatus.VERIFIER_FAILED, "postcondition_reader_unauthorized",
            f"the verifier lost access: {exc}; the effect status is unknown",
        )
    except Exception as exc:  # the reader is deployment code; it may do anything
        return _fail(
            EffectStatus.VERIFIER_FAILED, "postcondition_reader_error",
            f"the reader raised {type(exc).__name__}: {exc}",
        )

    if issue is None:
        return _fail(
            EffectStatus.UNOBSERVABLE, "postcondition_object_absent",
            "the issue does not exist; the effect status is unknown, not failed",
        )
    if not isinstance(issue, Mapping):
        return _fail(
            EffectStatus.VERIFIER_FAILED, "postcondition_reader_error",
            f"the reader returned {type(issue).__name__}, not a mapping",
        )

    return verify_declared_delta(
        contract, _normalize(issue),
        proposal_id=proposal_id, execution_id=execution_id,
        toolspec_hash=toolspec_hash, verifier_identity=VERIFIER_IDENTITY,
    )
