# Author: Stian Skogbrott
# License: Apache-2.0
"""Codegraph client for REMORA — token-efficient repository navigation.

Two backends:
  local   Reads codegraph.paths.ts + CODEGRAPH.md from the repo.
          Zero network, zero API keys. Works offline.
  remote  Queries the agent-control /codegraph endpoint (requires secret).
          Falls back to local automatically.

Usage
-----
    from remora.codegraph import search, get_file_summary

    # Find files relevant to a query
    results = search("aromer orchestrator world model")
    for r in results:
        print(r["path"], "-", r["summary"])

    # Direct lookup
    summary = get_file_summary("remora/aromer/orchestrator.py")
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PATHS_TS  = _REPO_ROOT / "workers" / "agent-control" / "src" / "codegraph.paths.ts"
_CODEGRAPH_MD = _REPO_ROOT / "CODEGRAPH.md"
_AGENT_CONTROL_URL = "https://remora-agent-control.razorsharp.workers.dev"
_SSL = ssl.create_default_context()

# ── Secret loading (mirrors remora_hook.py) ───────────────────────────────────

def _load_secret() -> str:
    if os.environ.get("AGENT_CONTROL_SECRET"):
        return os.environ["AGENT_CONTROL_SECRET"]
    config_paths = [
        os.path.expandvars(r"%APPDATA%\Claude\claude_desktop_config.json"),
        os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json"),
        os.path.expanduser("~/.config/claude/claude_desktop_config.json"),
        str(_REPO_ROOT / ".remora_session" / "hook_config.json"),
    ]
    for path in config_paths:
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            secret = (cfg.get("mcpServers", {}).get("remora", {})
                      .get("env", {}).get("AGENT_CONTROL_SECRET", ""))
            if not secret:
                secret = cfg.get("AGENT_CONTROL_SECRET", "")
            if secret:
                return str(secret)
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return ""


# ── Local backend ─────────────────────────────────────────────────────────────

def _parse_paths_ts() -> list[str]:
    """Extract file paths from codegraph.paths.ts."""
    if not _PATHS_TS.exists():
        return []
    content = _PATHS_TS.read_text(encoding="utf-8")
    # TS file uses single-quoted strings: '.claude/settings.json',
    return re.findall(r"'([^']+\.[a-zA-Z0-9]+)'", content)


def _parse_codegraph_md() -> dict[str, str]:
    """Parse CODEGRAPH.md for path→summary mappings."""
    summaries: dict[str, str] = {}
    if not _CODEGRAPH_MD.exists():
        return summaries
    for line in _CODEGRAPH_MD.read_text(encoding="utf-8").splitlines():
        # Lines like: | `path/to/file.py` | Summary text |
        m = re.match(r"\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|", line)
        if m:
            summaries[m.group(1).strip()] = m.group(2).strip()
    return summaries


_STOPWORDS = frozenset([
    "a", "an", "and", "as", "at", "be", "by", "do", "for", "from",
    "in", "is", "it", "of", "on", "or", "the", "to", "up", "vs",
])


def _score(query_tokens: set[str], path: str, summary: str) -> float:
    text = (path + " " + summary).lower()
    path_tokens = set(re.split(r"[^a-z0-9]+", path.lower())) - _STOPWORDS
    summary_tokens = set(re.split(r"[^a-z0-9]+", summary.lower())) - _STOPWORDS
    hits_path    = len(query_tokens & path_tokens)
    hits_summary = len(query_tokens & summary_tokens)
    # Exact substring bonus
    exact = sum(1 for t in query_tokens if t in text)
    return hits_path * 2.0 + hits_summary * 1.5 + exact * 0.5


def _local_search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    paths    = _parse_paths_ts()
    summaries = _parse_codegraph_md()
    query_tokens = set(re.split(r"[^a-z0-9]+", query.lower())) - _STOPWORDS

    results = []
    for path in paths:
        summary = summaries.get(path, _humanize(path))
        score   = _score(query_tokens, path, summary)
        if score > 0:
            results.append({"path": path, "summary": summary, "score": score, "backend": "local"})

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def _humanize(path: str) -> str:
    stem = Path(path).stem.replace("_", " ").replace("-", " ")
    return stem.title()


# ── Remote backend ────────────────────────────────────────────────────────────

def _remote_search(query: str, limit: int = 8, secret: str = "") -> list[dict[str, Any]] | None:
    if not secret:
        return None
    try:
        url = f"{_AGENT_CONTROL_URL}/codegraph?q={urllib.parse.quote(query)}&limit={limit}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {secret}",
            "User-Agent": "remora-codegraph/1.0",
        })
        with urllib.request.urlopen(req, timeout=8, context=_SSL) as r:
            data = json.loads(r.read().decode("utf-8"))
        # agent-control returns: {matches: [{path, summary, kind, tags}], total_files, ...}
        files = data.get("matches", data.get("files", data.get("results", [])))
        return [
            {
                "path": f.get("path", f) if isinstance(f, dict) else str(f),
                "summary": f.get("summary", "") if isinstance(f, dict) else "",
                "score": float(f.get("score", 1.0)) if isinstance(f, dict) else 1.0,
                "kind": f.get("kind", "") if isinstance(f, dict) else "",
                "backend": "remote",
            }
            for f in files
        ]
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def search(query: str, limit: int = 8, prefer_remote: bool = True) -> list[dict[str, Any]]:
    """Return ranked file results for query.  Falls back local→remote automatically."""
    if prefer_remote:
        secret = _load_secret()
        remote = _remote_search(query, limit, secret)
        if remote is not None:
            return remote
    return _local_search(query, limit)


def get_file_summary(path: str) -> str:
    """Return a one-line summary for a repo file."""
    summaries = _parse_codegraph_md()
    if path in summaries:
        return summaries[path]
    return _humanize(path)


def scope() -> dict[str, Any]:
    """Return the codegraph scope (include/exclude/entrypoints)."""
    paths = _parse_paths_ts()
    return {
        "total_indexed": len(paths),
        "backend": "local",
        "paths_ts": str(_PATHS_TS),
        "codegraph_md": str(_CODEGRAPH_MD),
        "remote_url": _AGENT_CONTROL_URL,
    }


