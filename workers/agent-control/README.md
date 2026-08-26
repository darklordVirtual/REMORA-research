# REMORA Agent Control Plane

Cloudflare Worker acting as a secure control plane between Claude and private infrastructure.

Claude invokes tools via HTTP; this Worker injects API secrets and writes a hash-stamped audit trail to D1.

```
Claude Desktop / Claude API
  │  (MCP tool calls via servers/mcp_remora.py)
  ▼
[remora-agent-control Worker]
  │  Bounded egress — statically-bound service workers only
  │  Secret injection — Claude never sees raw API keys
  │  D1 audit trail — SHA-256 input/output hashes; approvals recorded via UPDATE
  ├──► REMORA Worker        multi-oracle consensus
  ├──► RAG Oracle Worker    legal / knowledge retrieval
  ├──► Law Search Worker    DCE / Norwegian statute database
  └──► R2 / D1              artifacts, audit log
```

## Tools Exposed to Claude

These are the tools actually in `TOOL_CATALOG` (`src/index.ts`):

| Tool | Description | Requires approval |
|------|-------------|-------------------|
| `remora_verify_claim` | Multi-oracle consensus verification | No |
| `dce_search_law` | Search Norwegian statutes (DCE) | No |
| `store_artifact` | Write a file to R2 | **Yes** |

`audit_decision` was **removed** (2026-08-19): it let the same shared bearer
that proposes an action record its own approval, with `approved_by` as
caller-supplied text. Approvals are now first-class records granted only by an
authenticated, independent human reviewer via `POST /approvals`, see below.

## Deploy

### 1. Create Cloudflare resources

```bash
# D1 audit database
wrangler d1 create remora-audit
# Copy the database_id into wrangler.toml

# R2 artifact bucket
wrangler r2 bucket create remora-artifacts

# KV session store
wrangler kv namespace create remora-sessions
# Copy the id into wrangler.toml
```

### 2. Set secrets

```bash
wrangler secret put CONTROL_SECRET        # Bearer token required on every request
wrangler secret put ENVELOPE_SIGNING_KEY  # optional; HMAC over the envelope chain
```

(Only these two secrets are read by the code. Upstream service workers are
reached via Cloudflare service bindings, not secret-authenticated fetches.)

`ENVELOPE_SIGNING_KEY` is optional but changes what the audit trail proves.
Without it the chain detects an edited envelope, because the stored hash no
longer matches the stored payload. With it the chain also detects an attacker
who has D1 write access and rewrites whole rows including their hashes, since
they cannot forge the HMAC. `GET /envelopes/verify` states which of the two
guarantees is in force rather than leaving the reader to assume the stronger one.

### 3. Initialise D1 tables

```bash
npm run db:init:remote
```

`schema.sql` is idempotent, so re-running this against an existing deployment
adds the `decision_envelopes` and `envelope_chain_head` tables without
touching existing `audit_log` rows. Envelopes start at sequence 0 from that
point; calls made before the upgrade have no envelope and must not be
presented as though they did.

### 4. Deploy

```bash
npm run deploy
```

### 5. Connect to Claude Desktop

Add to `claude_desktop_config.json`:

```json
"mcpServers": {
  "remora": {
    "command": "python",
    "args": ["C:\\Users\\Stian\\REMORA\\servers\\mcp_remora.py"],
    "env": {
      "AGENT_CONTROL_URL": "https://remora-agent-control.<your-subdomain>.workers.dev",
      "AGENT_CONTROL_SECRET": "<CONTROL_SECRET>"
    }
  }
}
```

## Approvals (`POST /approvals`)

```
1. Agent proposes:   POST /execute {tool: store_artifact, input: {...}}   → 402 APPROVAL_REQUIRED + audit_id
2. Human reviews:    POST /approvals {audit_id, approved: true}
                     (Cloudflare Access identity; workload bearer refused)
3. Agent re-submits: POST /execute {tool, input: {..., audit_id}}
                     → the approval is consumed (single-use) after re-checking
                       tenant, exact input hash, ToolSpec hash, policy hash, expiry
```

Refusal reason codes: `REVIEWER_IDENTITY_REQUIRED`, `SELF_APPROVAL_FORBIDDEN`,
`TENANT_MISMATCH`, `PAYLOAD_CHANGED_AFTER_APPROVAL`,
`TOOLSPEC_CHANGED_AFTER_APPROVAL`, `POLICY_CHANGED_AFTER_APPROVAL`,
`APPROVAL_EXPIRED`, `APPROVAL_ALREADY_CONSUMED`, `APPROVAL_REJECTED`.

## Security Principles

- Bounded egress: outbound calls go only to the statically-bound service
  workers and fixed upstreams declared in `wrangler.toml`; there is no
  dynamic, request-controlled destination. (A configurable `EGRESS_ALLOWLIST`
  is roadmap, not implemented; earlier README wording overstated it; issue #55.)
- Secret injection: API keys live in Worker Secrets, never in Claude's context.
- Human-in-the-loop, no self-approval: destructive actions (R2 writes via
  `store_artifact`) are held until an independent human reviewer approves via
  `POST /approvals`. Reviewer identity comes only from a verified Cloudflare
  Access JWT (`src/auth.ts`; `ACCESS_TEAM_DOMAIN` + `ACCESS_AUD` +
  `REVIEWER_EMAILS`); the workload bearer is explicitly refused on that
  endpoint, and a reviewer whose identity equals the requester is refused
  (`SELF_APPROVAL_FORBIDDEN`). Each approval (`src/approval.ts`) is immutable,
  single-use, expires (`APPROVAL_TTL_SECONDS`, default 900), and is bound to
  the exact tool-call hash, ToolSpec identity and policy identity; any of
  those changing after approval refuses execution. Regression suite:
  `tests/test_agent_control_approvals.py` runs the real TS modules.
- Audit trail: Every tool call is written to D1 with a SHA-256 hash of the input/output pair.
- Governance record: Every `/execute` also writes a hash-chained
  `DecisionEnvelope` v2 (`src/envelope.ts`), including the calls that were
  *refused*; a held or rejected action is the evidence that the gate worked.
  A failed envelope write returns 500 rather than a clean 200, so an ungoverned
  action never reports success.
- Bearer token: All write endpoints require `Authorization: Bearer <secret>`.

## DecisionEnvelope Audit Trail

`audit_log` records that a call happened. The envelope chain records what was
decided, and links each decision to the one before it, so a deleted or edited
record is detectable instead of merely absent.

**Numeric payload contract.** The chain is written in TypeScript and verified
in Python, and the two languages serialize four numeric shapes differently:
integral-valued floats (`1.0` vs `1`), negative zero, `1e20` (positional in
ECMAScript), and integers beyond 2^53 (JavaScript precision loss). Payloads
on the envelope path must stay inside the agreed domain (plain integers up
to 2^53−1, non-integral floats, strings, booleans, null) or carry such
values as strings. The agreement domain and the pinned divergences are frozen
in `tests/golden/canonical_json_vectors_v1.json`
(`tests/test_canonical_json_golden_vectors.py` runs both languages against
them); changing a vector is a hash-contract change requiring an explicit
migration.

```
GET /envelopes?session_id=<id>&limit=50   List stored envelopes (admin)
GET /envelopes/<request_id>               Fetch one envelope (admin)
GET /envelopes/verify                     Recompute the tenant chain (admin)
```

Chain contract, identical to `remora.governance.tenant_chain` (REM-034):

```
entry_hash = SHA256( previous_hash ␟ canonical(envelope) ␟ tenant_id
                     ␟ sequence_no ␟ timestamp )        (␟ = 0x1f)
```

The exact canonical string that was hashed is stored verbatim in
`envelope_canonical`, so verifiers hash those bytes rather than
re-serialising; no cross-language JSON difference can turn an intact chain
into a reported break.

Fork-freedom without `SELECT ... FOR UPDATE`: `UNIQUE (tenant_id,
sequence_no)` means two writers that read the same head compute the same
sequence number and the loser's whole batch rolls back, after which it
retries against the new head.

Verify independently, without trusting this Worker's own endpoint:

```bash
curl -sH "Authorization: Bearer $CONTROL_SECRET" \
  "https://<worker>/envelopes?limit=200" > chain.json
python scripts/verify_envelope_chain.py --worker-export chain.json
```

**Scope: do not overclaim.** `gate.outcome` here records what this control
plane did: whether it required human approval and whether the call ran. It is
not a REMORA policy-engine verdict, and `audit.policy_version` says so
(`agent-control-gate/v1`). Putting the full decision engine in front of tool
dispatch is REM-024/REM-030.

## MCP Tools in Claude Desktop

After deployment, Claude Desktop can call:

```
agent_start_session    → Create a session, receive a session_id
agent_execute_tool     → Invoke a control plane tool
agent_audit_log        → Retrieve the agent's action history
```

## MicroVM Extension (future)

The Cloudflare Sandbox SDK (Workers Paid / Enterprise) provides a MicroVM runtime for heavier workloads:

```toml
# wrangler.toml — add when on Workers Paid plan
[sandbox]
enabled = true
```

This is not required for MVP: the control plane Worker logic runs fully on the free Workers plan.
