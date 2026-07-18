# REMORA Agent Control Plane

Cloudflare Worker acting as a secure control plane between Claude and private infrastructure.

Claude invokes tools via HTTP → this Worker enforces egress policy, injects API secrets, and writes an immutable audit trail to D1.

```
Claude Desktop / Claude API
  │  (MCP tool calls via servers/mcp_remora.py)
  ▼
[remora-agent-control Worker]
  │  Egress policy — only approved upstream hosts allowed
  │  Secret injection — Claude never sees raw API keys
  │  D1 audit trail — append-only, SHA-256 hashed
  ├──► REMORA Worker        multi-oracle consensus
  ├──► RAG Oracle Worker    legal / knowledge retrieval
  ├──► Law Search Worker    DCE / Norwegian statute database
  ├──► EOS API              Luftfiber building data
  └──► R2 / D1              artifacts, audit log
```

## Tools Exposed to Claude

| Tool | Description | Requires approval |
|------|-------------|-------------------|
| `remora_verify_claim` | Multi-oracle consensus verification | No |
| `dce_search_law` | Search Norwegian statutes (DCE) | No |
| `eos_query_building` | Read EOS building data (read-only) | No |
| `eos_execute_action` | Execute an EOS action | **Yes** |
| `store_artifact` | Write a file to R2 | **Yes** |
| `audit_decision` | Record a human approval decision | No |

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
wrangler secret put CONTROL_SECRET   # Bearer token used by Claude clients
wrangler secret put REMORA_SECRET    # Token for the REMORA Worker
wrangler secret put EOS_API_KEY      # Luftfiber EOS API key
```

### 3. Initialise D1 tables

```bash
npm run db:init:remote
```

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

## Security Principles

- **Egress allowlist**: The Worker only forwards requests to a pre-approved set of upstream domains.
- **Secret injection**: API keys live in Worker Secrets, never in Claude's context.
- **Human-in-the-loop**: Destructive actions (`eos_execute_action`, R2 writes) are held in `PENDING_APPROVAL` until a human approves via `audit_decision`.
- **Audit trail**: Every tool call is written to D1 with a SHA-256 hash of the input/output pair.
- **Bearer token**: All write endpoints require `Authorization: Bearer <secret>`.

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
