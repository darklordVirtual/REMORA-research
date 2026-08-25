# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Semantic bundle for the governed GitHub tools.

Two jobs. It declares what each tool *is* — effect, capability, resource type —
so risk is derived server-side rather than asserted by the caller. And it
resolves an ``intent_ref`` into the authority a call claims to act under.

For the OT pilot that authority is a signed work order. Here it is a **GitHub
issue**, which is a better fit than it first looks: an issue is written by a
person, states what should happen, and exists independently of the agent that
later proposes a call. REMORA then checks the proposed tool call against what
the issue actually asks for — so ``gh_close_issue`` under an issue that asks
for a label gets refused for the reason it deserves, not for looking odd.

The issue text is fetched at resolve time and its digest becomes the
authority, so an issue edited after approval does not silently authorise a
different action.
"""
from __future__ import annotations

import hashlib
import os
import re

from remora.toolcall.routing.compatibility import CoverageScope, StateIndex
from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature
from remora.toolcall.semantic_bundle import (
    IntentResolution,
    ResolvedIntent,
    SemanticBundle,
)

#: intent_ref looks like "owner/repo#123" — the issue that authorises the call.
_INTENT_RE = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)#(?P<number>\d+)$")

#: Words in an issue that indicate the effect it is asking for. Deliberately
#: small and frozen: this is the deterministic side of the boundary, and an
#: extractor that grows to match anything stops discriminating. The known
#: weakness is the opposite one — an issue that phrases the same request
#: differently resolves to UNKNOWN and lands in VERIFY rather than ACCEPT.
_EFFECT_WORDS: dict[str, tuple[str, ...]] = {
    "create": ("create", "open", "file", "add a new", "raise"),
    "update": ("comment", "reply", "label", "tag", "update", "annotate"),
    "close": ("close", "resolve", "fix", "complete", "done"),
    "read": ("read", "check", "look at", "review", "inspect", "list"),
}


def build_semantic_bundle() -> SemanticBundle:
    registry = ToolRegistry(signatures={
        "gh_read_issue": ToolSignature(
            name="gh_read_issue", effect="read",
            required_params=("repo", "number")),
        "gh_list_issues": ToolSignature(
            name="gh_list_issues", effect="read",
            required_params=("repo",)),
        "gh_create_issue": ToolSignature(
            name="gh_create_issue", effect="write",
            required_params=("repo", "title")),
        "gh_comment_issue": ToolSignature(
            name="gh_comment_issue", effect="write",
            required_params=("repo", "number", "body")),
        "gh_close_issue": ToolSignature(
            name="gh_close_issue", effect="write",
            required_params=("repo", "number")),
        "gh_add_label": ToolSignature(
            name="gh_add_label", effect="write",
            required_params=("repo", "number", "label")),
    })

    contracts = ToolContractRegistry([
        ToolContract(tool="gh_read_issue", capability="issue_read",
                     effect="read", resource_type="issue", mutation=False,
                     argument_roles={"repo": "target_resource",
                                     "number": "target_resource"}),
        ToolContract(tool="gh_list_issues", capability="issue_read",
                     effect="read", resource_type="issue", mutation=False,
                     argument_roles={"repo": "target_resource"}),
        ToolContract(tool="gh_create_issue", capability="issue_create",
                     effect="create", resource_type="issue", mutation=True,
                     argument_roles={"repo": "target_resource",
                                     "title": "payload"}),
        ToolContract(tool="gh_comment_issue", capability="issue_annotate",
                     effect="update", resource_type="issue", mutation=True,
                     argument_roles={"repo": "target_resource",
                                     "number": "target_resource",
                                     "body": "payload"}),
        ToolContract(tool="gh_close_issue", capability="issue_lifecycle",
                     effect="close", resource_type="issue", mutation=True,
                     argument_roles={"repo": "target_resource",
                                     "number": "target_resource"}),
        ToolContract(tool="gh_add_label", capability="issue_annotate",
                     effect="update", resource_type="issue", mutation=True,
                     argument_roles={"repo": "target_resource",
                                     "number": "target_resource",
                                     "label": "payload"}),
    ])

    # Closed world over the repositories this deployment may touch. A repo
    # outside the allowlist is not merely refused by the callable — it is not
    # a known entity to the policy engine either.
    repos = {r.strip() for r in
             os.getenv("REMORA_GITHUB_REPOS", "").split(",") if r.strip()}
    state = StateIndex.from_values(
        repos or {"__none__"},
        (CoverageScope("github",
                       frozenset({"repo", "number", "label", "title", "body",
                                  "state"}),
                       closed_world=False),),
    )
    return SemanticBundle.build(registry=registry, contracts=contracts,
                                validators=None, state=state)


def _effect_from_text(text: str) -> str:
    """The effect an issue is asking for, or "" when it does not say plainly.

    Read order matters: an issue that says "review and close" is asking for a
    close, so the mutating readings are checked before the read one.
    """
    lowered = text.lower()
    for effect in ("close", "create", "update", "read"):
        if any(word in lowered for word in _EFFECT_WORDS[effect]):
            return effect
    return ""


def resolve_intent_detailed(intent_ref: str) -> IntentResolution:
    """Resolve ``owner/repo#123`` into the authority that issue carries.

    Returns None when the reference does not parse, the repository is outside
    the allowlist, or the issue cannot be read. None means UNKNOWN rather than
    permitted: a call with no resolvable authority behind it does not get an
    ACCEPT, it gets sent for review.
    """
    match = _INTENT_RE.match((intent_ref or "").strip())
    if not match:
        return IntentResolution(None, "intent_not_authorized")
    repo, number = match.group("repo"), match.group("number")

    allowed = {r.strip() for r in
               os.getenv("REMORA_GITHUB_REPOS", "").split(",") if r.strip()}
    if repo not in allowed:
        return IntentResolution(None, "intent_not_authorized")

    # Imported here so the bundle can be built without a credential present.
    from deploy.gateway.gh_registry import (
        GitHubNotFound,
        GitHubUnavailable,
        gh_read_issue,
    )

    try:
        issue = gh_read_issue({"repo": repo, "number": int(number)})
    except GitHubNotFound:
        return IntentResolution(None, "intent_not_authorized")
    except (GitHubUnavailable, ValueError):
        return IntentResolution(None, "intent_resolution_failed")

    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    task_text = f"{title}\n\n{body}".strip()
    if not task_text:
        return IntentResolution(None, "intent_not_authorized")

    # The digest is over the text as read now. An issue edited after a call
    # was approved therefore stops matching, rather than silently authorising
    # something the approver never saw.
    digest = hashlib.sha256(task_text.encode("utf-8")).hexdigest()
    authority = f"github_issue:{repo}#{number}:{digest}"

    resolved = ResolvedIntent(
        intent=TaskIntent(
            operation=_effect_from_text(task_text) or "read",
            resource_type="issue",
            requested_effect=_effect_from_text(task_text) or "read",
            target_entities=("target_resource",),
            source_spans=(repo,),
            action_spans=tuple(
                w for w in _EFFECT_WORDS.get(_effect_from_text(task_text), ())
                if w in task_text.lower()
            ),
            proposed_by=authority),
        task_text=task_text,
        authority=authority)
    return IntentResolution(resolved, "resolved")


def resolve_intent(intent_ref: str):  # -> ResolvedIntent | None
    """Backward-compatible public resolver."""
    return resolve_intent_detailed(intent_ref).resolved
