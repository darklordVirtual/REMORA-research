# Governed MCP gateway

How an MCP client — Claude Code, Claude Desktop, ChatGPT — calls tools that
REMORA governs, and what happens between the model asking and anything
actually changing.

Design and measurements: [DOC-319](../design/cloudflare-mcp-gateway-v1.md).
Code: `workers/mcp-gateway/`.

## What it is

The agent sees ordinary MCP tools. It calls `set_valve_position` the way it
would call any tool. It does not know, and does not need to know, that the
call is being assessed.

What the agent does *not* have is a credential for the valve. Only the
`GovernedToolDispatcher` inside the container holds that. This is the whole
point of the arrangement: an agent that dislikes a refusal has no second route
to the same effect, because the route it would need does not exist in the
process it runs in.

```
Claude Code / Claude Desktop / ChatGPT
        │  MCP over Streamable HTTP
        ▼
  MCP gateway (Worker)          protocol, session, proposal store
        │
        ▼
  REMORA container              assess → approve → execute
        │
        ▼
  durable execution state       audit chain, review queue, grant ledger
        │
        ▼
  the actual tool               reached only with a redeemed grant
```

## The four decisions

Every tool call is assessed before anything happens. There are four possible
answers, and only one of them executes immediately.

| Decision | What the agent gets back | Side effect |
| --- | --- | --- |
| `accept` | `status: executed` with the result | yes, immediately |
| `verify` | `status: pending_approval` with a `proposal_id` and an `approval_reference` | none |
| `escalate` | `status: refused` with reasons | none |
| `abstain` | `status: refused` with reasons | none |

A refusal is **not** returned as a tool error. Flagging it as an error would
invite the model to treat governance as a fault to be routed around, which is
precisely the behaviour the system exists to prevent. The refusal text says so
in as many words: do not retry, and do not look for another way to the same
effect.

### VERIFY is the normal path, not the edge case

Of the 15 cases in the OT battery, 13 resolve to `verify` and 2 to
`escalate`. Not one reaches `accept` unattended. Any design that treats
approval as an exception would therefore be designing for the case that almost
never happens.

MCP has no native "wait for a human" semantics, and blocking the call until
someone answers would time out in both Claude and ChatGPT. So the tool returns
immediately:

```json
{
  "decision": "verify",
  "reasons": ["evidence_insufficient"],
  "status": "pending_approval",
  "proposal_id": "fc3407ba-a0b4-4c91-97c9-f0842cf25c6f",
  "approval_reference": "27f6e1dc-b3d3-471e-8620-45f58dd37622",
  "explanation": "Nothing has been executed. A human must approve this call first. ..."
}
```

The agent gives the `approval_reference` to the user, then polls
`remora_proposal_status` with the `proposal_id`. While the call is still
unapproved the poll reports `pending_approval` again — not an error, because
waiting is not a failure.

Once a human with the approver role has approved it, the same poll executes
the call and returns the result.

### The arguments cannot drift between approval and execution

The gateway stores the original tool call and re-presents it in full at
execution time. The agent never gets to supply the arguments again. This is
not a convenience: REMORA re-gates the full payload against what was approved,
so an agent that approved a valve at 35% and executed at 100% would be refused
— and with this design it cannot even attempt it.

A redeemed proposal is deleted. Polling it again reports `unknown_proposal`,
and the attempt never reaches REMORA.

## Roles

The gateway holds an **operator** token. It can propose and it can execute an
approved call. It cannot approve.

That separation is enforced server-side, not by the gateway being polite about
it. Measured against the running system: the operator token attempting to
approve its own proposal gets **403**. A compromised gateway therefore cannot
self-approve a mutating call — it can only ask, the same as before.

## Verified behaviour

End to end against the real execution API with durable Postgres, 2026-08-23:

```
1. agent proposes        -> verify / pending_approval
   approval_reference    -> 27f6e1dc-b3d3-471e-8620-45f58dd37622
2. operator self-approve -> 403   (role separation holds)
3. approver approves     -> 200
4. agent polls           -> executed
   side effect           -> PIC-101 setpoint 4 -> 3.8
5. replay same proposal  -> unknown_proposal
6. audit chain           -> valid (postgres, durable)
```

And the case that matters most — a mutating call under a read-only intent:

```
set_valve_position(valve=V-12, position_pct=100, intent_ref=MON-ROUND)
  -> escalate / refused
  -> reasons: schema_unverified_verify, tool_does_not_match_goal
```

`MON-ROUND` is a monitoring round. It does not authorise moving a valve, and
the call is refused for that reason rather than for looking suspicious.

## Running it locally

Two processes: REMORA with its database, and the gateway.

```sh
# 1. REMORA in production mode against real Postgres
docker compose -f deploy/ot-pilot/docker-compose.yml up -d postgres api

# 2. the gateway
cd workers/mcp-gateway
npm install
npx wrangler dev --config wrangler.dev.toml --port 8791
```

`wrangler.dev.toml` has no container binding, so an edit-reload cycle does not
rebuild a 338 MB image. `REMORA_API_URL` changes the transport only: every
decision is still made by the REMORA execution API that compose brings up, in
production mode, against real Postgres. There is no code path in the gateway
that reaches a tool without one.

Check it is up:

```sh
curl http://127.0.0.1:8791/health
# {"status":"ok","service":"remora-mcp-gateway","transport":"direct (development)"}
```

### Connecting Claude Code

```sh
claude mcp add --scope local --transport http remora-gateway http://127.0.0.1:8791/mcp
claude mcp list
# remora-gateway: http://127.0.0.1:8791/mcp (HTTP) - ✔ Connected
```

The seven tools then appear in the session: the six governed OT tools, plus
`remora_proposal_status`.

To approve something the agent has proposed, use the approver token against
the execution API:

```sh
export REMORA_APPROVER_TOKEN=...   # the approver role; docker-compose.yml carries the local value
curl -X POST http://127.0.0.1:8080/v1/execution/approve \
  -H "Authorization: Bearer ${REMORA_APPROVER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"item_id": "<approval_reference>", "approval_ttl_seconds": 900}'
```

An approval console is a later slice. Until then, approving is a curl command,
and the tokens in `docker-compose.yml` are local pilot values — a real
deployment puts an identity provider there instead.

## Deploying to Cloudflare

`wrangler.toml` is the production config: the container binding, `basic`
instance, always on.

It needs a Postgres reachable over TLS, supplied as a Worker secret. Container
egress was measured on 2026-08-23 and raw TCP works — psycopg completes a full
wire-protocol session — so no HTTP-shaped persistence backend is involved.

```sh
cd workers/mcp-gateway
wrangler secret put REMORA_PG_DSN
wrangler secret put REMORA_AGENT_TOKEN
wrangler secret put REMORA_API_TOKENS
wrangler secret put REMORA_PDP_SIGNING_KEY
wrangler secret put REMORA_LEASE_SIGNING_KEY
wrangler secret put REMORA_AUDIT_SIGNING_KEY
wrangler secret put REMORA_ENVELOPE_SIGNING_KEY
wrangler deploy
```

Every one of those is required. `REMORA_ENV=production` makes the check
binding: without durable execution state or the signing keys, the container
refuses to start. That refusal is the feature. A gateway that came up without
a durable one-time-grant ledger would accept a replayed grant after any
restart, and the audit chain would be tamper-evident in name only.

### European jurisdiction

The execution state this container writes is not operational telemetry. It is
the tenant audit chain, the one-time-grant ledger and the DecisionEnvelope
store: a record of who authorised which action against which system.

`wrangler.toml` therefore pins the container to a compliance boundary rather
than to a region list:

```toml
[containers.constraints]
jurisdiction = "eu"
```

`eu` maps to EEUR and WEUR. The proposal store is pinned the same way — a
pending proposal holds the exact arguments of a call awaiting approval, which
is the same class of record — via `PROPOSAL_JURISDICTION` and
`DurableObjectNamespace.jurisdiction()`. A Durable Object's jurisdiction is
fixed when the object is created and cannot be changed afterwards, which is
the property that makes it worth setting.

**Placement is not a GDPR guarantee.** It constrains where the container runs
and where the proposal store lives. It says nothing about the database, which
must be in the same jurisdiction and is a separate decision — see the
"Database" section below.

### Access

The gateway is machine-to-machine. Claude Code and ChatGPT can send headers;
they cannot complete an interactive browser sign-in. So the Access policy uses
**service tokens**, not SSO.

```sh
# 1. a service token for this client
wrangler access service-token create --name "remora-mcp-claude-code"
# records CF-Access-Client-Id and CF-Access-Client-Secret; the secret is
# shown once

# 2. an Access application over the MCP endpoint, with a policy that admits
#    that service token and nothing else
```

Then the client sends the pair as headers:

```sh
claude mcp add --transport http remora-gateway https://<host>/mcp   --header "CF-Access-Client-Id: <id>"   --header "CF-Access-Client-Secret: <secret>"
```

Two independent checks then stand between a model and a side effect: Access
decides whether this client may reach the gateway at all, and REMORA decides
whether this call may happen. The first is authentication, the second is
authority. Neither substitutes for the other — a valid service token still
gets `escalate` on a valve change under a monitoring round.

A service token identifies a *client*, not a person. It is the right primitive
for an agent, and the wrong one for approval: approving stays with a human
holding the approver role, and the gateway's own token cannot approve at all.

### Database

The container connects directly to Postgres over TLS. Measured 2026-08-23:
raw TCP egress works and psycopg completes a full wire-protocol session, so
Hyperdrive is not in this path and no HTTP-shaped persistence backend is
involved.

For a European deployment the database must sit in the same jurisdiction as
the container. The provider is a cost and data-processing decision rather than
a technical one; every option speaks the same protocol.

### What this deployment is not

It runs `REMORA_ENV=production` under the **default research profile**, not
`controlled_pilot`.

`controlled_pilot` additionally requires a signed ToolSpec bundle, a signing
key and a trusted-identity allowlist, and there is no signed bundle for the OT
registry yet. Setting `REMORA_RUNTIME_PROFILE=controlled_pilot` without one
would make the container refuse to start — correctly.

This is a named gap, not a hidden one. Until the bundle exists, `assess` takes
risk tier and action type from the deployment-owned registry module rather
than from signed authority. Set `REMORA_RUNTIME_PROFILE` once the bundle is
there; `remora/toolcall/runtime_profile.py` will verify the claim rather than
take it on trust.

## Adding a governed tool

Two places, and the split is the important part:

1. `deploy/ot-pilot/ot_registry.py` — the callable and its authoritative
   metadata. This is where risk tier, action type and everything else that
   decides an outcome lives. It is deployment-owned and server-side.
2. `workers/mcp-gateway/src/tools.ts` — the MCP schema: name, description,
   argument shape.

A field added in `tools.ts` can never widen authority. It only changes what
the agent is able to propose; what that proposal is *worth* is decided from
the registry. A caller cannot assert its way to an ACCEPT — see
`ToolCallRequest` in `servers/execution_contracts.py`, where the only inbound
safety influence permitted is a downgrade.

Every governed tool requires an `intent_ref`: the work order the call claims
to act under. A call with no resolvable intent has no authority behind it, and
a test pins that every tool demands one.

## Tests

```sh
cd workers/mcp-gateway
npm test          # 16 protocol and governance tests
npm run type-check
```

The REMORA client is faked in those tests, so they pin the gateway's own
behaviour rather than REMORA's: that a refusal executes nothing, that a
pending proposal executes nothing, that stored arguments are used at
redemption rather than supplied ones, and that a redeemed proposal cannot be
replayed.

The end-to-end contract is `deploy/ot-pilot/run_ot_battery.py`, which runs
against the execution API directly. A tamper case that passes is a failed
deployment.
