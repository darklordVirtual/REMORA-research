# Cloudflare Productivity Layer

This guide explains the fastest way to use REMORA with Cloudflare while still
keeping the repository fully usable without Cloudflare.

The design goals are:

- minimize token use,
- keep code navigation fast,
- preserve a local fallback for contributors without Cloudflare,
- make Claude Code use codegraph before broad file reads.

---

## Mode Overview

### Cloudflare-accelerated mode

Use this when you want the fastest repo context narrowing and the lowest token
usage.

Components:

- `GET /codegraph` on the agent-control worker for repo scope and entrypoints.
- `GET /search` on the agent-control worker for repo search and snippets.
- `remora_codegraph_scope` MCP tool for scope narrowing.
- `remora_repo_search` MCP tool for second-pass file and snippet search.

### Portable mode

Use this when Cloudflare is not available.

Behavior:

- `remora_codegraph_scope` falls back to local `codegraph.yaml` and
  `.codegraphignore`.
- `remora_repo_search` falls back to git-tracked text-file search in the repo.
- Claude Code still works against the local Python MCP server.

---

## Reproducible Setup

### 1. Validate the local repo tools

```bash
cd /workspaces/REMORA
python -m py_compile servers/mcp_remora.py
cd workers/agent-control
./node_modules/.bin/tsc --noEmit
```

### 2. Start the MCP server in Claude Code

```bash
claude mcp add remora python /workspaces/REMORA/servers/mcp_remora.py
```

If you use another machine, replace the path with the local clone path.

### 3. Optional Cloudflare variables

Set these only if the worker is deployed:

```bash
export AGENT_CONTROL_URL="https://remora-agent-control.example.workers.dev"
export CODEGRAPH_URL="$AGENT_CONTROL_URL/codegraph"
export REPO_SEARCH_URL="$AGENT_CONTROL_URL/search"
```

If these are unset, the MCP server uses portable fallback behavior.

### 4. Run the workflow in Claude Code

1. Call `remora_codegraph_scope` first.
2. Call `remora_repo_search` for file snippets and second-pass lookup.
3. Open full files only after the scope has been narrowed.

Example:

```text
Use remora_codegraph_scope for "Claude Code setup".
Then use remora_repo_search for "codegraph Claude Code".
Only after that, read the relevant files.
```

---

## Why This Works

- `codegraph` reduces the file universe before any expensive reads.
- `search` returns snippets instead of whole files.
- Cloudflare can accelerate the same API surface later without changing the
  Claude Code workflow.
- Local fallback keeps the repo useful for people who do not run Cloudflare.

---

## Deployment Notes

The current worker already exposes `/codegraph` and `/search` through the same
repo-aware payload structure. That makes the Cloudflare side cheap to evolve:

- keep the API stable,
- swap the backend implementation later,
- keep MCP clients unchanged.

For now, the worker uses the repo's codegraph catalog as the backing index.
That is enough to keep context low and the workflow reproducible.