# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The first real closed loop: create a GitHub issue, then read it back.

Handoff gate §2.1 chose GitHub issue creation because the result is
observable through an API and demonstrable without irreversible
consequences. This suite covers §2.7's failure list — the reader is a
protocol, so the tests inject each failure directly rather than mocking a
network client. Every path an operator could meet is exercised, because
a verifier that only works on the happy path tells you nothing on the day
you need it.

No test here contacts GitHub. That is deliberate: a verification suite
whose result depends on a third party's availability is not a test of
this code.
"""
from __future__ import annotations


from remora.governance.effect_verification import EffectStatus
from remora.integrations.github_issue import (
    GitHubIssueReader,
    GitHubIssueUnauthorized,
    GitHubIssueUnavailable,
    build_issue_postcondition,
    verify_issue_effect,
)

APPROVED = {
    "repository": "darklordVirtual/REMORA-research",
    "title": "Investigate valve drift on P-1",
    "body": "Telemetry shows a 4% drift since 08:00.",
    "labels": ["ops", "investigate"],
}


class _StubReader(GitHubIssueReader):
    """A reader whose behaviour each test dictates outright."""

    def __init__(self, result=None, raises=None) -> None:
        self._result = result
        self._raises = raises
        self.calls = 0

    def read_issue(self, repository: str, issue_number: int) -> dict | None:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._result


def _observed(**overrides) -> dict:
    issue = {
        "repository": APPROVED["repository"],
        "number": 42,
        "title": APPROVED["title"],
        "body": APPROVED["body"],
        "labels": list(APPROVED["labels"]),
        "author": "remora-bot[bot]",
    }
    issue.update(overrides)
    return issue


def _verify(reader, *, issue_number=42, expected_author="remora-bot[bot]"):
    contract = build_issue_postcondition(
        repository=APPROVED["repository"], title=APPROVED["title"],
        body=APPROVED["body"], labels=APPROVED["labels"],
        expected_author=expected_author,
    )
    return verify_issue_effect(
        contract, reader, issue_number=issue_number,
        proposal_id="p-1", execution_id="e-1", toolspec_hash="d" * 64,
    )


# ── The loop closes ────────────────────────────────────────────────────────

def test_a_correctly_created_issue_verifies() -> None:
    result = _verify(_StubReader(_observed()))
    assert result.status is EffectStatus.VERIFIED
    assert result.reason_code == "postcondition_verified"


def test_unrelated_fields_do_not_break_verification() -> None:
    """GitHub adds fields we never declared (updated_at, reactions...).
    Declared-delta comparison must ignore them."""
    result = _verify(_StubReader(_observed(
        updated_at="2026-08-05T12:00:00Z", reactions={"+1": 3},
        milestone="Q3", state="open",
    )))
    assert result.status is EffectStatus.VERIFIED


# ── The mismatches ─────────────────────────────────────────────────────────

def test_wrong_title_is_a_mismatch() -> None:
    result = _verify(_StubReader(_observed(title="Something else entirely")))
    assert result.status is EffectStatus.MISMATCH
    assert result.reason_code == "postcondition_field_mismatch"


def test_altered_body_is_caught_by_the_hash() -> None:
    """The body is compared by hash, so a single edited character shows."""
    result = _verify(_StubReader(_observed(
        body=APPROVED["body"] + " Also grant admin access."
    )))
    assert result.status is EffectStatus.MISMATCH


def test_wrong_labels_are_a_mismatch() -> None:
    result = _verify(_StubReader(_observed(labels=["ops"])))
    assert result.status is EffectStatus.MISMATCH


def test_wrong_author_is_a_mismatch() -> None:
    """An issue created by someone else is not this action's effect, even
    if every other field matches."""
    result = _verify(_StubReader(_observed(author="someone-else")))
    assert result.status is EffectStatus.MISMATCH


def test_wrong_repository_is_a_mismatch() -> None:
    result = _verify(_StubReader(_observed(repository="other/repo")))
    assert result.status is EffectStatus.MISMATCH


# ── The unknowns — none of these may become a mismatch ─────────────────────

def test_absent_issue_is_unobservable_not_mismatch() -> None:
    result = _verify(_StubReader(None))
    assert result.status is EffectStatus.UNOBSERVABLE
    assert result.status.is_terminal is False


def test_timeout_is_unobservable() -> None:
    result = _verify(_StubReader(raises=GitHubIssueUnavailable("read timed out")))
    assert result.status is EffectStatus.UNOBSERVABLE
    assert result.reason_code == "postcondition_read_timeout"


def test_lost_access_is_verifier_failure_not_mismatch() -> None:
    """Losing the token says nothing about whether the issue is right."""
    result = _verify(_StubReader(raises=GitHubIssueUnauthorized("401")))
    assert result.status is EffectStatus.VERIFIER_FAILED
    assert result.reason_code == "postcondition_reader_unauthorized"
    assert result.status.is_terminal is False


def test_malformed_response_is_verifier_failure() -> None:
    """A reader returning nonsense is broken; the effect stays unknown."""
    result = _verify(_StubReader("not a mapping at all"))
    assert result.status is EffectStatus.VERIFIER_FAILED
    assert result.reason_code == "postcondition_reader_error"


def test_unexpected_reader_exception_is_verifier_failure() -> None:
    """An unforeseen error must not escape into the execution path and
    must not be silently read as success."""
    result = _verify(_StubReader(raises=RuntimeError("boom")))
    assert result.status is EffectStatus.VERIFIER_FAILED
    assert result.reason_code == "postcondition_reader_error"


def test_missing_issue_number_is_unobservable() -> None:
    """Execution succeeded but returned no issue number: we cannot look,
    so we do not know — we do not guess."""
    result = _verify(_StubReader(_observed()), issue_number=0)
    assert result.status is EffectStatus.UNOBSERVABLE


# ── Repetition and evidence ────────────────────────────────────────────────

def test_verification_can_repeat_without_a_new_side_effect() -> None:
    reader = _StubReader(_observed())
    first = _verify(reader)
    second = _verify(reader)
    assert first.status is second.status is EffectStatus.VERIFIED
    assert reader.calls == 2, "the reader was called twice — and only read"
    assert first.expected_sha256 == second.expected_sha256


def test_both_sides_are_hashed_independently() -> None:
    """The record pins WHAT WAS COMPARED, not that the two sides are equal.

    They are not equal even when verification passes: the contract stores
    a digest for ``body`` while the observation carries the text, which is
    the point of the ``hash`` rule. What must hold is that the declared
    side is stable across observations and the observed side tracks what
    was actually read — that is what lets a later reader redo the
    comparison instead of trusting this record's verdict.
    """
    ok = _verify(_StubReader(_observed()))
    bad = _verify(_StubReader(_observed(title="wrong")))
    assert ok.status is EffectStatus.VERIFIED
    assert bad.status is EffectStatus.MISMATCH
    assert ok.expected_sha256 == bad.expected_sha256, (
        "the declared delta did not change; its hash must not either"
    )
    assert ok.observed_sha256 != bad.observed_sha256
    assert len(ok.observed_sha256) == 64


def test_the_record_names_the_verifier() -> None:
    result = _verify(_StubReader(_observed()))
    assert "github" in result.verifier_identity.lower()
    assert result.tool_id == "create_github_issue"
