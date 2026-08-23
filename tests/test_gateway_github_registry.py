# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The governed GitHub tool set for the MCP gateway.

These pin the deployment-owned half of the boundary: which repositories are
reachable at all, what each tool is declared to be, and how a GitHub issue
becomes the authority a call claims to act under.

The network is never touched. What is under test is the gateway's own
reasoning, not GitHub's behaviour.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.gateway import gh_bundle, gh_registry  # noqa: E402

REPO = "darklordVirtual/REMORA-research"


@pytest.fixture(autouse=True)
def _scope(monkeypatch):
    monkeypatch.setenv("REMORA_GITHUB_REPOS", REPO)
    monkeypatch.setenv("REMORA_GITHUB_TOKEN", "test-token")


# ── the repository allowlist ────────────────────────────────────────────────

def test_an_unlisted_repository_is_refused(monkeypatch):
    """The token may have wider access than the deployment should use."""
    with pytest.raises(gh_registry.GitHubUnavailable) as exc:
        gh_registry._check_repo("someone-else/private-thing")
    assert "allowlist" in str(exc.value)


def test_an_empty_allowlist_reaches_nothing(monkeypatch):
    """Unscoped is not a governed deployment, so it is refused outright."""
    monkeypatch.setenv("REMORA_GITHUB_REPOS", "")
    with pytest.raises(gh_registry.GitHubUnavailable) as exc:
        gh_registry._check_repo(REPO)
    assert "no repository is reachable" in str(exc.value)


def test_the_listed_repository_passes():
    assert gh_registry._check_repo(REPO) == REPO


def test_a_missing_credential_is_a_clear_refusal(monkeypatch):
    monkeypatch.delenv("REMORA_GITHUB_TOKEN", raising=False)
    with pytest.raises(gh_registry.GitHubUnavailable) as exc:
        gh_registry._token()
    assert "REMORA_GITHUB_TOKEN" in str(exc.value)


def test_every_tool_checks_the_repository_before_the_network(monkeypatch):
    """A refused repository must never reach an HTTP request."""
    def explode(*a, **k):  # pragma: no cover - reached only on failure
        raise AssertionError("the network was touched for an unlisted repo")

    monkeypatch.setattr(gh_registry, "_request", explode)
    for name, fn in gh_registry.TOOLS:
        with pytest.raises(gh_registry.GitHubUnavailable):
            fn({"repo": "outside/allowlist", "number": 1, "title": "x",
                "body": "x", "label": "x"})


# ── declared semantics ──────────────────────────────────────────────────────

def test_the_bundle_builds_without_a_credential(monkeypatch):
    """Building the policy view must not require reaching GitHub."""
    monkeypatch.delenv("REMORA_GITHUB_TOKEN", raising=False)
    assert gh_bundle.build_semantic_bundle() is not None


def test_read_tools_are_declared_read_and_writes_are_declared_write():
    sigs = gh_bundle.build_semantic_bundle().registry.signatures
    assert sigs["gh_read_issue"].effect == "read"
    assert sigs["gh_list_issues"].effect == "read"
    for mutating in ("gh_create_issue", "gh_comment_issue",
                     "gh_close_issue", "gh_add_label"):
        assert sigs[mutating].effect == "write", mutating


def test_every_registered_tool_has_a_declared_signature():
    """A callable with no declaration would be assessed on nothing."""
    sigs = gh_bundle.build_semantic_bundle().registry.signatures
    for name, _ in gh_registry.TOOLS:
        assert name in sigs, f"{name} is registered but not declared"


# ── the issue as authority ──────────────────────────────────────────────────

def test_a_malformed_reference_resolves_to_nothing():
    for bad in ("", "nonsense", "owner/repo", "#12", "owner/repo#abc"):
        assert gh_bundle.resolve_intent(bad) is None, bad


def test_an_issue_outside_the_allowlist_does_not_grant_authority(monkeypatch):
    def explode(*a, **k):  # pragma: no cover - reached only on failure
        raise AssertionError("an unlisted repo was read")

    monkeypatch.setattr(gh_registry, "gh_read_issue", explode)
    assert gh_bundle.resolve_intent("someone-else/thing#1") is None


def test_an_unreadable_issue_resolves_to_unknown_not_permitted(monkeypatch):
    """Failure to establish authority is not the same as having it."""
    def unavailable(_):
        raise gh_registry.GitHubUnavailable("404")

    monkeypatch.setattr(gh_registry, "gh_read_issue", unavailable)
    assert gh_bundle.resolve_intent(f"{REPO}#1") is None


def test_the_issue_text_becomes_the_authority(monkeypatch):
    monkeypatch.setattr(gh_registry, "gh_read_issue", lambda _: {
        "title": "Close the stale tracking issue",
        "body": "It was resolved by the fix that landed last week.",
    })
    resolved = gh_bundle.resolve_intent(f"{REPO}#42")
    assert resolved is not None
    assert "stale tracking issue" in resolved.task_text
    assert resolved.authority.startswith(f"github_issue:{REPO}#42:")


def test_editing_the_issue_changes_the_authority(monkeypatch):
    """An issue edited after approval must not authorise the same call.

    The digest is over the text as read, so a rewritten issue produces a
    different authority rather than silently standing in for the one a human
    actually approved.
    """
    monkeypatch.setattr(gh_registry, "gh_read_issue", lambda _: {
        "title": "Add a label", "body": "tracking",
    })
    before = gh_bundle.resolve_intent(f"{REPO}#42").authority

    monkeypatch.setattr(gh_registry, "gh_read_issue", lambda _: {
        "title": "Add a label", "body": "tracking, and also close it",
    })
    after = gh_bundle.resolve_intent(f"{REPO}#42").authority

    assert before != after


def test_an_empty_issue_carries_no_authority(monkeypatch):
    monkeypatch.setattr(gh_registry, "gh_read_issue",
                        lambda _: {"title": "", "body": ""})
    assert gh_bundle.resolve_intent(f"{REPO}#42") is None


@pytest.mark.parametrize("text,expected", [
    ("Please close this once the fix lands", "close"),
    ("Open a new issue for the follow-up", "create"),
    ("Add a label to track this", "update"),
    ("Review the failing job", "read"),
    ("Resolve the duplicate", "close"),
])
def test_the_effect_an_issue_asks_for(text, expected):
    assert gh_bundle._effect_from_text(text) == expected


def test_a_mutating_reading_wins_over_a_read_one():
    """"Review and close" is asking for a close, not a read."""
    assert gh_bundle._effect_from_text("Review this and close it") == "close"


def test_text_that_asks_for_nothing_recognisable_yields_no_effect():
    """The extractor is frozen, so silence is the honest answer.

    An issue phrased outside the vocabulary resolves to no effect, which sends
    the call to review rather than accepting it on a guess. That is the known
    weakness of a deterministic extractor and it fails in the safe direction.
    """
    assert gh_bundle._effect_from_text("Thoughts on the architecture?") == ""
