# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Governed GitHub tools for the MCP gateway.

Deployment-owned: this module is what a deployment writes itself, and it is
where the authoritative metadata for each tool lives. The MCP schema in
``workers/mcp-gateway/src/tools.ts`` only describes what an agent may
*propose*; what a proposal is worth is decided from here, server-side.

The credential lives in this process and nowhere else. The agent never holds
it, which is what makes a refusal final rather than advisory — there is no
second route to the same effect from where the agent is standing.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

API = "https://api.github.com"
_TIMEOUT = 20


class GitHubUnavailable(RuntimeError):
    """The call could not be completed. Says nothing about whether it applied."""


def _token() -> str:
    token = os.getenv("REMORA_GITHUB_TOKEN", "").strip()
    if not token:
        raise GitHubUnavailable(
            "REMORA_GITHUB_TOKEN is not set. The governed tools hold the "
            "credential; without it there is nothing to govern."
        )
    return token


def _allowed_repos() -> frozenset[str]:
    """Repositories this deployment may touch at all.

    A closed list rather than an open credential scope: the token may well
    have wider access, and the deployment narrows it. An unlisted repository
    is refused here, before any policy decision, because a tool that can reach
    anything cannot be reasoned about.
    """
    raw = os.getenv("REMORA_GITHUB_REPOS", "").strip()
    return frozenset(r.strip() for r in raw.split(",") if r.strip())


def _check_repo(repo: str) -> str:
    allowed = _allowed_repos()
    if not allowed:
        raise GitHubUnavailable(
            "REMORA_GITHUB_REPOS is empty, so no repository is reachable. "
            "This is deliberate: an unscoped deployment is not a governed one."
        )
    if repo not in allowed:
        raise GitHubUnavailable(
            f"repository {repo!r} is not in this deployment's allowlist"
        )
    return repo


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "remora-governed-gateway")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GitHubUnavailable(f"GitHub returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubUnavailable(f"GitHub unreachable: {exc.reason}") from exc


# ── the governed callables ──────────────────────────────────────────────────
#
# Each returns the declared delta rather than GitHub's whole response body, so
# what the postcondition reader compares against is small and explicit.

def gh_read_issue(a: dict[str, Any]) -> dict[str, Any]:
    repo = _check_repo(str(a.get("repo", "")))
    number = int(a.get("number", 0))
    issue = _request("GET", f"/repos/{repo}/issues/{number}")
    return {
        "repo": repo,
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "body": (issue.get("body") or "")[:4000],
        "labels": [x.get("name") for x in issue.get("labels", [])],
    }


def gh_list_issues(a: dict[str, Any]) -> dict[str, Any]:
    repo = _check_repo(str(a.get("repo", "")))
    state = str(a.get("state", "open"))
    query = urllib.parse.urlencode({"state": state, "per_page": 30})
    issues = _request("GET", f"/repos/{repo}/issues?{query}")
    return {
        "repo": repo,
        "state": state,
        "issues": [
            {"number": i.get("number"), "title": i.get("title"),
             "state": i.get("state")}
            for i in issues if "pull_request" not in i
        ],
    }


def gh_create_issue(a: dict[str, Any]) -> dict[str, Any]:
    repo = _check_repo(str(a.get("repo", "")))
    created = _request("POST", f"/repos/{repo}/issues", {
        "title": str(a.get("title", "")),
        "body": str(a.get("body", "")),
    })
    return {
        "repo": repo,
        "number": created.get("number"),
        "title": created.get("title"),
        "state": created.get("state"),
        "url": created.get("html_url"),
    }


def gh_comment_issue(a: dict[str, Any]) -> dict[str, Any]:
    repo = _check_repo(str(a.get("repo", "")))
    number = int(a.get("number", 0))
    posted = _request("POST", f"/repos/{repo}/issues/{number}/comments",
                      {"body": str(a.get("body", ""))})
    return {
        "repo": repo, "number": number,
        "comment_id": posted.get("id"),
        "url": posted.get("html_url"),
    }


def gh_close_issue(a: dict[str, Any]) -> dict[str, Any]:
    repo = _check_repo(str(a.get("repo", "")))
    number = int(a.get("number", 0))
    updated = _request("PATCH", f"/repos/{repo}/issues/{number}",
                       {"state": "closed"})
    return {
        "repo": repo, "number": number,
        "state": updated.get("state"),
        "url": updated.get("html_url"),
    }


def gh_add_label(a: dict[str, Any]) -> dict[str, Any]:
    repo = _check_repo(str(a.get("repo", "")))
    number = int(a.get("number", 0))
    label = str(a.get("label", ""))
    _request("POST", f"/repos/{repo}/issues/{number}/labels", {"labels": [label]})
    issue = _request("GET", f"/repos/{repo}/issues/{number}")
    return {
        "repo": repo, "number": number,
        "labels": [x.get("name") for x in issue.get("labels", [])],
    }


TOOLS: tuple[tuple[str, Callable[[dict[str, Any]], Any]], ...] = (
    ("gh_read_issue", gh_read_issue),
    ("gh_list_issues", gh_list_issues),
    ("gh_create_issue", gh_create_issue),
    ("gh_comment_issue", gh_comment_issue),
    ("gh_close_issue", gh_close_issue),
    ("gh_add_label", gh_add_label),
)


def register_tools(register: Callable[[str, Callable[[Any], Any]], None]) -> None:
    for name, fn in TOOLS:
        register(name, fn)
