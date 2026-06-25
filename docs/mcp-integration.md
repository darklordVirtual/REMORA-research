# REMORA MCP Integration

REMORA exposes its consensus and verification capabilities as an
[MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server.
This allows AI assistants such as Claude Desktop and Claude Code to call REMORA
tools directly — grounding AI answers in multi-oracle consensus, authoritative
knowledge bases, and deterministic database lookups.

Cloudflare services are optional accelerators, not hard requirements. The MCP
server still works without Cloudflare by using local repository manifests and
the Python code paths already in this repo.

For a reproducible end-to-end setup, see [Cloudflare Productivity Layer](cloudflare-productivity-layer.md).

---

## Architecture

```
Claude Desktop / Claude Code
        │
        │  JSON-RPC over stdio
        ▼
 servers/mcp_remora.py          ← MCP server (open source, this repo)
        │
        ├── go-star-remora.razorsharp.workers.dev      Consensus engine
        │       3 independent LLMs (Groq LLaMA 8B, LLaMA 70B, Mistral 7B)
        │       Lyapunov stability gate
        │
        ├── remora-rag-oracle.razorsharp.workers.dev   RAG oracle
        │       Knowledge base retrieval + synthesis
        │       Dual-consensus option (8B + 70B)
        │       use_case routing (legal / security / general)
        │
        ├── remora-law-search.razorsharp.workers.dev   Law-search bridge
        │       Connects to DCE extension (see below)
        │       Norwegian statute corpus + legal fragment database
        │
        └── remora-agent-control.razorsharp.workers.dev  Agent control plane
                Policy gating, D1 audit ledger, KV sessions, R2 artifacts
                Bearer-auth (fail-closed)
          Service bindings → go-star-remora + remora-law-search
          Codegraph endpoint → repo scope + relevant file suggestions
```

---

## Setup

### Claude Desktop

Add to `claude_desktop_config.json` (location: `%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "remora": {
      "command": "python",
      "args": ["C:/Users/<you>/REMORA/servers/mcp_remora.py"],
      "env": {}
    }
  }
}
```

Restart Claude Desktop. The REMORA tools will appear in the tool list.

### Claude Code / CLI

```bash
claude mcp add remora python C:/Users/<you>/REMORA/servers/mcp_remora.py
```

### Claude Code with codegraph

Use this when you want Claude Code to narrow repo context before reading large
files or making broad edits:

```bash
claude mcp add remora python /workspaces/REMORA/servers/mcp_remora.py
```

Recommended environment variables when Cloudflare is deployed:

```bash
export AGENT_CONTROL_URL="https://remora-agent-control.example.workers.dev"
export CODEGRAPH_URL="$AGENT_CONTROL_URL/codegraph"
export REPO_SEARCH_URL="$AGENT_CONTROL_URL/search"
```

Portable mode works with no Cloudflare variables set. In that case the MCP
server falls back to `codegraph.yaml`, `.codegraphignore`, and local
git-tracked text-file search.

Recommended Claude Code workflow:

1. Call `remora_codegraph_scope` first to narrow the active file set.
2. Call `remora_repo_search` for file snippets or a second-pass search.
3. Only open full files after the repo has been narrowed.

That order keeps token use low and makes the session easier to reproduce.

---

## MCP Tools

### Decision guide

```
Norwegian document (letter, debt collection notice, contract)?
  → remora_verify_legal_citations  — catches hallucinated court decisions (requires DCE)
  → remora_legal_analysis          — comprehensive legal analysis

Single yes/no factual claim?
  → remora_verify_claim

Regulatory text (GDPR art. X, ISO 27001 ...)?
  → remora_rag_query  (domain=specialised)

Norwegian statute directly (§-reference, law name)?
  → remora_norwegian_law_search  (requires DCE)

General document (non-legal)?
  → remora_analyze_document

GO-STAR security finding?
  → remora_verify_claim  (isolated consensus)

Agentic tool calls through policy gate + D1 audit?
  → 1. agent_start_session   — create session with 24 h TTL and audit trail
  → 2. agent_execute_tool    — execute tool call through egress policy + D1 audit
  → 3. agent_audit_log       — retrieve audit log, approve/reject pending actions

Live Lyapunov V(t) and session stability for running agent?
  → remora_session_status

Repo scope / active codegraph entrypoints?
  → remora_codegraph_scope

Repo file snippets / second-pass search?
  → remora_repo_search

System slow or down?
  → remora_status
```

---

### `remora_status`

Health check across the three inference workers (consensus engine, RAG oracle, law-search bridge).

**Parameters:** none

**Returns:** Oracle availability, active model names, RAG chunk counts by domain.

**Example output:**
```
## REMORA System Status

### Consensus Engine
- Status: ✓ Ready
- Active oracles: 3 / 3
- Models: llama-3.1-8b-instant, llama-3.3-70b-versatile, mistralai/mistral-7b-instruct

### Knowledge Base (RAG Oracle)
- Total documents: 93 chunks

### `remora_codegraph_scope`

Returns the canonical repository codegraph scope plus a compact list of
relevant files. This is the recommended first MCP call before broad repo
questions because it narrows context to the active graph.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Search terms such as `MCP`, `Cloudflare`, `counterfactual`, or `worker` |
| `limit` | integer | No | Maximum number of file suggestions to return (1-25, default 8) |

**Backends:**
- Cloudflare Control Plane endpoint: `GET /codegraph` on `remora-agent-control`
- Local fallback: `codegraph.yaml` and `.codegraphignore`

**Returns:** The include/exclude scope, entrypoints, notes, and matching files.

**Why this matters:** use this first when you want to keep token usage low.
The tool narrows the context window before you open more files, so the model
spends fewer tokens on irrelevant repository material.

**Example:**
```
remora_codegraph_scope({
  "query": "MCP Cloudflare",
  "limit": 5
})
```
  - specialised: 13 chunks (GDPR Art. 4+5, ISO 27001)
  - science: 35 chunks (CRISPR, vaccines, chemistry)
  - general: 45 chunks (REMORA whitepaper, architecture docs, general knowledge)
```

---

### `remora_verify_claim`

Asks three independent AI oracles whether a claim is TRUE or FALSE.
Returns a consensus verdict with calibrated confidence.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `claim` | string | Yes | The claim to verify |
| `domain` | string | No | `legal`, `science`, `general` (default: general) |

**Returns:** TRUE / FALSE / UNCERTAIN, confidence %, trust level (HIGH / MEDIUM / LOW), oracle summary.

**Confidence thresholds:**

| Confidence | Trust | Use |
|------------|-------|-----|
| ≥ 85 % | HIGH | Reliable basis for decision |
| 65–84 % | MEDIUM | Verify against primary source |
| 40–64 % | LOW | Indicative only |
| < 40 % | VERY LOW | Abstain — seek expert |

**Example:**
```
remora_verify_claim({
  "claim": "GDPR Article 17 grants data subjects the right to erasure of personal data",
  "domain": "legal"
})
→ ✓ TRUE  100 %  HIGH — Consensus from 3 independent AI oracles
```

---

### `remora_analyze_document`

Asks three independent oracles a free-form question about a document or text.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | Yes | The document text to analyse |
| `question` | string | Yes | The question to answer about the text |
| `domain` | string | No | `legal`, `science`, `general` |

**Returns:** Verdict, confidence, oracle call count, whether Lyapunov iteration was needed.

**Example:**
```
remora_analyze_document({
  "text": "The clause grants the vendor the right to use customer data for product improvement ...",
  "question": "Is this clause problematic under GDPR?",
  "domain": "legal"
})
→ ✓ YES  100 %  9 oracle calls
```

---

### `remora_legal_analysis`

Combines knowledge base retrieval with multi-oracle consensus for legal documents.
First queries the RAG knowledge base with `use_case=legal` (triggers dual-consensus:
the 8B and 70B models both synthesise, then agree-rate boosts confidence +10 pp or
reduces it 20 % on disagreement). Then sends result to the REMORA consensus engine.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `document_text` | string | Yes | The legal document text |
| `analysis_question` | string | Yes | The legal question to answer |
| `jurisdiction` | string | No | `Norway`, `EU`, etc. |
| `domain` | string | No | `specialised` (default), `legal`, `science` |

**Returns:** Verdict, confidence, RAG synthesis summary, knowledge base sources, oracle consensus.

**Note:** The RAG knowledge base contains GDPR, ISO 27001, and selected Norwegian legal summaries.
For authoritative Norwegian statute text, use `remora_norwegian_law_search` (requires DCE).

---

### `remora_rag_search`

Raw search in the REMORA knowledge base. Returns matching chunks with scores.
Use this to inspect what source documents are available before running a query.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query |
| `domain` | string | No | `specialised`, `science`, `general` |

**Returns:** List of matching chunks with titles, source, and relevance score.

---

### `remora_rag_query`

Queries the knowledge base and synthesises an answer using the RAG oracle.
Supports optional dual-consensus (8B + 70B models run in parallel).

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | The question to answer |
| `domain` | string | No | `specialised`, `science`, `general` |
| `dual_consensus` | boolean | No | Run both 8B and 70B models for higher confidence |
| `use_case` | string | No | `legal` (forces dual_consensus + high complexity), `security` (fast path, 8B) |

**Returns:** Synthesised answer, confidence, source list, model used, whether models agreed.

**Example:**
```
remora_rag_query({
  "query": "GDPR Article 5 principles lawfulness fairness transparency",
  "domain": "specialised"
})
→ YES  100 %  Sources: Wikipedia GDPR, EU law  10 chunks retrieved
```

---

### `remora_norwegian_law_search`

Searches the Norwegian statute corpus for law text matching the query.

> **Requires the DCE extension.** See [Extensions](#extensions) below.

Uses semantic vector search (bge-m3, 1024-dim multilingual embeddings) against
the full Norwegian statute corpus indexed by DCE.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Natural language query in Norwegian or English |
| `top_k` | integer | No | Number of results, max 10 (default 5) |

**Returns:** Ranked list of matching law sections with law name, section reference,
relevance score, and excerpt.

**Example:**
```
remora_norwegian_law_search({
  "query": "oppsigelse arbeidsmiljøloven saklig grunn"
})
→ 1. Arbeidsmiljøloven § 15-7  score=0.636
     "(1) Arbeidstaker kan ikke sies opp uten at det er saklig begrunnet ..."
  2. Arbeidstilsynets veiledning om oppsigelse  score=0.619
  3. Arbeidsmiljøloven § 15-12  score=0.581
```

---

### `remora_verify_legal_citations`

Extracts Norwegian legal citations from a document and verifies each one through
a two-layer pipeline: (1) DCE knowledge base lookup, (2) multi-oracle consensus.
Designed to catch AI-hallucinated court decisions before they enter formal documents.

> **Requires the DCE extension.** See [Extensions](#extensions) below.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `document_text` | string | Yes | The document text containing citations to check |
| `jurisdiction` | string | No | `Norway` (default) |

**Returns:** Per-citation verdicts: FOUND_IN_DATABASE / NOT_FOUND / POSSIBLE_MATCH_VECTOR,
oracle consensus (NEEDS_CONTENT_CHECK / CANNOT_VERIFY / LIKELY_HALLUCINATED),
and a combined conclusion for each citation.

**Verdict matrix:**

| DB result | Oracle result | Conclusion |
|-----------|---------------|------------|
| FOUND_IN_DATABASE | NEEDS_CONTENT_CHECK | Partially verified — check content |
| NOT_FOUND | CANNOT_VERIFY | Likely hallucinated |
| NOT_FOUND | LIKELY_HALLUCINATED | Likely hallucinated |
| FOUND_IN_DATABASE | LIKELY_HALLUCINATED | Exists, but claimed content is wrong |

**Example:**
```
remora_verify_legal_citations({
  "document_text": "Ref. Supreme Court HR-2019-928-A and HR-2022-9999-A ..."
})
→ HR-2019-928-A  FOUND IN DATABASE  NEEDS_CONTENT_CHECK  → PARTIALLY VERIFIED
→ HR-2022-9999-A  NOT FOUND         CANNOT_VERIFY         → LIKELY HALLUCINATED
```

See [use case 06](use-cases/06-public-administration-hallucination.md) for a
full documented real-world example (Asker municipality, May 2026).

---

### `agent_start_session`

Creates an audited agent session in the agent-control worker (D1 + KV + R2).
Returns a session UUID with a 24-hour TTL used by subsequent `agent_execute_tool` calls.

> **Requires the agent-control worker.** Endpoint: `https://remora-agent-control.razorsharp.workers.dev`
> Bearer-auth (CONTROL_SECRET) required for all write operations.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | Identifier for the agent or Claude session |
| `description` | string | No | Human-readable session purpose |

**Returns:** Session UUID, creation timestamp, TTL.

---

### `agent_execute_tool`

Routes a tool call through the agent-control egress policy. The call is logged
to D1 with the policy verdict (VERIFIED / BLOCKED / PENDING), confidence score,
and risk classification before execution.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session UUID from `agent_start_session` |
| `tool_name` | string | Yes | Name of the tool being called |
| `arguments` | object | Yes | Tool arguments to pass through the policy gate |

**Returns:** Verdict (VERIFIED / BLOCKED / PENDING), confidence, risk tier, D1 audit row ID.

---

### `agent_audit_log`

Retrieves the D1 audit log for a session. Returns all recorded tool-call verdicts,
timestamps, confidence scores, and any pending actions awaiting human approval.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session UUID to retrieve |
| `limit` | integer | No | Maximum rows to return (default 50) |

**Returns:** Ordered list of audit rows; each row includes tool name, verdict, confidence, risk tier, and timestamp.

---

### `remora_session_status`

Reports the live Lyapunov stability state for the current Claude Code session
from the local `.remora_session/` directory. No network calls — reads local state only.

**Parameters:** none

**Returns:** V(t), H, D, drift score, consecutive-critical-phase count, autonomy level
(FULL / SUPERVISED / HUMAN_REQUIRED), and formal stability assessment.

**Example output:**
```
## Session Lyapunov Status

V(t): 0.42   H: 0.31   D: 0.12
Drift score: 0.05
Consecutive critical phases: 0
Autonomy level: FULL
Formal guarantee: V(t) non-increasing over last 8 tool calls — session is Lyapunov-stable
```

---

## Extensions

REMORA's core components are open source: the MCP server (`servers/mcp_remora.py`),
the consensus worker (`workers/rag-oracle/`), and the law-search bridge
(`workers/law-search/`).

However, two of the twelve MCP tools depend on **private data extensions**
that connect REMORA to closed-source knowledge bases and infrastructure.

### DCE — Document Compliance Engine (Mine Dokumenter)

DCE is a closed-source Norwegian document intelligence platform. It is not
part of this repository and is not publicly available.

REMORA connects to DCE through the law-search bridge worker, which binds to
two DCE resources hosted in a private Cloudflare account:

| DCE resource | Type | Content | Used by |
|---|---|---|---|
| `norges-lover-law-index` | Cloudflare Vectorize (1024-dim, bge-m3) | All current Norwegian statutes, semantic index | `remora_norwegian_law_search` |
| `norges-lover-legal-intel` | Cloudflare D1 | Legal decisions (Høyesterett, Finansklagenemnda, Datatilsynet), preparatory works, citation fragments | `remora_verify_legal_citations` |

The law-search bridge worker (`workers/law-search/`) is open source and its
source code is in this repository. What it connects to (the Vectorize index and
D1 database) is part of DCE and requires access to the DCE Cloudflare account.

**Without the DCE extension:**
- `remora_norwegian_law_search` returns an error (no index bound)
- `remora_verify_legal_citations` cannot perform D1 citation lookups

**With the DCE extension:** both tools use real Norwegian law data. The law-search
bridge is already deployed at `https://remora-law-search.razorsharp.workers.dev`
with DCE bindings active. If you are running your own deployment and need DCE
access, contact **support@luftfiber.no**.

### GO-STAR — Security Research Platform

GO-STAR is a separate open-source security research platform. It is not part
of this repository, but integrates with REMORA for vulnerability validation.

When GO-STAR produces security findings, REMORA (`remora_verify_claim`) acts as
a false-positive filter: three independent oracles assess each candidate finding
before it enters the human review queue. This reduces false positives from ~92 %
to substantially lower without running any exploit code.

See [use case 05](use-cases/05-security.md) for details.

### Building your own extension

An extension adds new knowledge to REMORA without modifying the core. The
minimum components are:

1. **A data source** — a Cloudflare Vectorize index or D1 database (or any HTTP
   endpoint your knowledge lives behind)
2. **A bridge worker** — a Cloudflare Worker (like `workers/law-search/`) that
   exposes `/search` and optionally `/verify-citation` endpoints
3. **An MCP handler** — a new `handle_remora_<name>` function in
   `servers/mcp_remora.py` that calls your bridge worker

The existing `workers/law-search/src/index.ts` and the handler
`handle_remora_norwegian_law_search` in `servers/mcp_remora.py` are the
reference implementation for this pattern.

---

## Confidence thresholds

| Confidence | Trust level | Recommended action |
|------------|------------|-------------------|
| ≥ 85 % | HIGH | Reliable basis for decision |
| 65–84 % | MEDIUM | Useful — verify against primary source |
| 40–64 % | LOW | Indicative only |
| < 40 % | VERY LOW | Abstain — seek expert advice |

---

## Tested tools (pytest)

```bash
python -m pytest tests/test_mcp_remora.py -v
```

20 unit tests covering: `remora_legal_analysis` bug fixes, output formatting,
`remora_norwegian_law_search`, and `remora_rag_query`. All tests use local mocks —
no live API calls required.
