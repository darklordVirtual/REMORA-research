# Governed MCP gateway

How an MCP client (Claude Code, Claude Desktop, ChatGPT) calls tools that
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

Every tool call is assessed before anything happens. Only one of the four
executes without a person.

| Decision | Means | What the agent gets | Side effect |
| --- | --- | --- | --- |
| `accept` | run it | the result, plus the reasons that allowed it | yes |
| `verify` | a person must decide | `proposal_id` and `approval_reference` | none yet |
| `escalate` | **a person must decide**, and the call did not resolve under the intent it claimed | the same, with why | none yet |
| `abstain` | nothing to decide on | refused | none |

**`escalate` is not a refusal.** `servers/execution_api.py` is explicit:
"VERIFY/ESCALATE enqueue a review item for a human; ABSTAIN returns
[nothing]". This gateway treated escalate as refused for most of its life,
which threw away the one route a person had to say yes; and escalate is the
case where a person is *most* needed, because something about the call did not
line up. It now goes to approval with the mismatch stated, so whoever looks at
it knows they are not rubber-stamping a routine call.

`abstain` is the refusal. There is nothing for a person to approve, so no
proposal is created.

An `accept` carries its reasons and its grounding signals. It is the one
outcome where nobody looked, so it is the one that must never be unexplained.

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
unapproved the poll reports `pending_approval` again; not an error, because
waiting is not a failure.

Once a human with the approver role has approved it, the same poll executes
the call and returns the result.

### The arguments cannot drift between approval and execution

The gateway stores the original tool call and re-presents it in full at
execution time. The agent never gets to supply the arguments again. This is
not a convenience: REMORA re-gates the full payload against what was approved,
so an agent that approved a valve at 35% and executed at 100% would be refused
and with this design it cannot even attempt it.

A redeemed proposal is deleted. Polling it again reports `unknown_proposal`,
and the attempt never reaches REMORA.

## Roles

The gateway holds an **operator** token. It can propose and it can execute an
approved call. It cannot approve.

That separation is enforced server-side, not by the gateway being polite about
it. Measured against the running system: the operator token attempting to
approve its own proposal gets **403**. A compromised gateway therefore cannot
self-approve a mutating call; it can only ask, the same as before.

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

And the case that matters most; a mutating call under a read-only intent:

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
and the tokens in `docker-compose.yml` are local pilot values; a real
deployment puts an identity provider there instead.

On a deployed gateway the container is reachable only through the Worker, so
approvals go to `POST /approve` on the gateway itself. The Worker forwards the
caller's own `Authorization` header untouched and never uses its operator token
for that route: REMORA decides whether the presented identity holds the approver
role, exactly as it would for a direct caller. The route relays authority; it
does not confer any.

Measured against the deployed gateway: the gateway's own operator token gets
**403** there, a viewer gets **403**, and a request with no credential gets
**401**.

## Deploying to Cloudflare

`wrangler.toml` is the production config: the container binding, `basic`
instance, always on.

It needs a Postgres reachable over TLS, supplied as a Worker secret. Container
egress was measured on 2026-08-23 and raw TCP works (psycopg completes a full
wire-protocol session), so no HTTP-shaped persistence backend is involved.

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

`eu` maps to EEUR and WEUR. The proposal store is pinned the same way; a
pending proposal holds the exact arguments of a call awaiting approval, which
is the same class of record; via `PROPOSAL_JURISDICTION` and
`DurableObjectNamespace.jurisdiction()`. A Durable Object's jurisdiction is
fixed when the object is created and cannot be changed afterwards, which is
the property that makes it worth setting.

**Placement is not a GDPR guarantee.** It constrains where the container runs
and where the proposal store lives. It says nothing about the database, which
must be in the same jurisdiction and is a separate decision; see the
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
authority. Neither substitutes for the other; a valid service token still
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

### Deployed, and what it proved

Live at `remora-mcp-gateway.razorsharp.workers.dev`, container placed in
`txl01` (Berlin) under the `eu` jurisdiction constraint. Full chain against the
deployed gateway, 2026-08-23:

| Step | Result |
| --- | --- |
| agent proposes a setpoint change | `verify` / `pending_approval` |
| gateway's own operator token approves | **403** |
| viewer approves | **403** |
| no credential at all | **401** |
| approver approves | 200 |
| agent polls | `executed` — PIC-101 setpoint 4 → 3.8 |
| replay the same proposal | `unknown_proposal` |
| valve change under a read-only intent | `escalate`, `tool_does_not_match_goal` |

Access refuses an unauthenticated request with 403 and admits the service
token. Claude Code connects to the deployed URL and reports the seven tools.

Deploying surfaced two things the local run could not.

**There was no way to approve.** The container is reachable only through the
Worker, so before `/approve` existed every mutating call would have waited
forever. Fail-closed, but not usable; a governance system that can only ever
refuse has not been tested against the case that matters.

**The durability guard could not see ephemeral disk.** Fixed; see below.

Formerly: `REMORA_ENV=production`
requires `REMORA_PG_DSN` or `REMORA_CHAIN_DB`, and accepts a `REMORA_CHAIN_DB`
path on the container's own filesystem. On Cloudflare that filesystem is
ephemeral: the file is gone the next time the instance starts, so the tenant
audit chain and the one-time-grant ledger do not survive a restart and a
consumed grant becomes replayable. The check passes while providing none of
the guarantee it exists to provide.

That is a real weakness in the guard rather than a deployment mistake, and it
is why `/health` reports `execution_state` and refuses to describe this
deployment as anything other than what it is:

```json
{
  "execution_state": "EPHEMERAL (container disk)",
  "warning": "… a consumed grant becomes replayable. This deployment exercises the path; it is not a pilot. Set REMORA_PG_DSN to fix it."
}
```

Setting `REMORA_PG_DSN` to a Postgres inside the same jurisdiction is the one
remaining step, and it is a single secret plus a redeploy.

### Capability test, 2026-08-23

Run against the deployed gateway. Every case declares what *should* happen; a
legitimate call that gets blocked counts as a failure exactly like an attack
that gets through, because a gateway that refuses everything is perfectly safe
and useless.

**Held.** Nothing reaches a side effect without a human: seven proposals
including mutating ones all stopped at `pending_approval` with no approval.
The gateway's own operator token gets 403 on approval, a viewer gets 403, a
request with no credential gets 401. A redeemed proposal cannot be replayed,
and an approval issued for one call does not redeem another. Cloudflare Access
refuses an unauthenticated request before REMORA is reached.

The data boundary held under attack rather than merely erroring: a query
naming another tenant came back with the tenant rewritten to ours and zero
rows; a subject containing `'; DROP TABLE knowledge_facts; --` matched
nothing and the table was still there afterwards. Writing to the intent graph
was refused, as was a fact with no source, a confidence outside 0..1 and an
unrecognised object kind.

**The finding.** The intent was decorative. Correct task, invented task and no
task at all produced *identical* decisions and identical reasons; every call
reached VERIFY with `evidence_insufficient`. The authority mechanism was
running and influencing nothing.

The cause was under-specified tasks, not a broken mechanism. The seeded tasks
carried `task_text`, `operation` and `resource_type` but no `source_spans` or
`action_spans`, so the goal matcher had nothing to match on and
`tool_does_not_match_goal` could never fire. Adding the spans produced
discrimination immediately:

| Call | Decision | Reason |
| --- | --- | --- |
| write under the write task | `verify` | `evidence_insufficient` |
| write under a **read-only** task | **`escalate`** | **`expected_effect_contradicted`** |
| write under an invented task | `verify` | `evidence_insufficient` |

Three distinct outcomes where there had been one: the task forbids this
effect, no authority was established, and authorised but still wanting a
human. `kg_intent.DISCRIMINATING_PREDICATES` records the requirement and the
resolver warns when a task lacks them; a warning rather than a refusal,
because an under-specified task is weaker, not invalid, and refusing it would
remove the review it still gets.

**Not measured.** Reads do not discriminate: correct and invented read tasks
both reach `verify` with the same reason. And nothing in this deployment ever
reaches `accept`, so autonomy is zero; every call, however well-authorised,
waits for a person. That is the same shape as the repository's own §39 result
and is a property of the configuration, not a fault.

### Durable state, and effect verification

Both were missing when the capability test ran, and both are now in place.

**Durable execution state without a credential.** The container has no
writable disk worth the name, and no database token. It posts to
`state.internal`; the Worker answers from a D1 binding
(`remora-execution-state`, EEUR). `REMORA_STATE_ENDPOINT` is treated as
durable by the guard for the same reason a DSN is; the storage behind it is
not this container's filesystem.

D1 over HTTP has no interactive transaction, so writes are buffered and sent
as one atomic batch at commit, and a rollback is simply never sending them.
That gives all-or-nothing for the write set. It does **not** give isolation
from a concurrent writer between load and commit, which is safe here only
because the deployment runs a single container instance and the container
serialises. It would not be safe with more than one, and
`remora/persistence/d1_connection.py` says so at the top rather than leaving
it to be discovered.

Proven by destroying the container:

```
item consumed before the container was destroyed
  b047d228-4707-42c6-b93d-d71f86f2a2b7

in D1 after the restart      status = executed
queue reloaded by the NEW container (empty disk)   38 items
that item in the reloaded queue                    executed
```

The queue REMORA refuses a re-execution from was read off D1 by a container
whose disk was empty.

**Effect verification.** The dispatcher returning cleanly says the request was
accepted, not that the row is there. After a write executes, the Worker reads
the fact back through its own binding and compares it against the delta the
tool declared, then files the result on the proposal's trail as an attestation
by a named verifier. REMORA records it as reported, mismatches included.

Only the declared fields are compared: a field the delta does not name is out
of scope by construction, because a concurrent legitimate write elsewhere in
the row is not this action's problem.

| Case | Reported |
| --- | --- |
| write, read-back matches | `EFFECT_VERIFIED` / `delta_matches` |
| write, a declared field differs | `EFFECT_MISMATCH`, naming every field |
| write, fact not readable | `EFFECT_UNOBSERVABLE` — never mismatch |
| reader itself broke | `EFFECT_VERIFIER_FAILED` |
| a read | `EFFECT_UNSUPPORTED`, not a vacuous success |

Not knowing and knowing it is wrong are different facts, and only one of them
justifies compensating.

The verifier is TypeScript and the writer is Python, so the canonical digest
is implemented twice. A test pins the TypeScript output against hardcoded
values from `remora.governance.effect_verification.effect_digest`, without
it the two could drift and every verification would silently become a
mismatch.

### Why autonomy is zero, and what that cost to find out

The gateway declares risk metadata for its own tools
(`deploy/gateway/tool_metadata.json`) and grounds argument values in the graph
itself, which is the system of record. Both were missing, and both are needed
before `ACCEPT` is reachable at all: without them every tool falls to the
fail-closed `critical`/`unknown` default and every value looks like it came
from nowhere.

`REMORA_GROUNDED_READ_ACCEPT` is enabled. The path is real and it fires:

| Target | Risk | Outcome |
| --- | --- | --- |
| non-production | low | **`accept`** — `grounded_read_accept` |
| production | low | `abstain` |
| production | medium | `abstain` |
| production | high | `verify` |

**This gateway reads production, so it never reaches the first row.**
`_is_grounded_read` requires a non-production target because no read-only
guarantee covers the disclosure blast radius of live data. That refusal is the
active decision here, not a missing piece, and `tests/test_gateway_grounded_read.py`
pins it; including that it stays refused however well grounded the call is.

**Two things were learned the hard way and are recorded rather than smoothed
over.**

The reads were first declared `low`. Measured effect: every read fell through
to `abstain`. The VERIFY routes are driven by risk tier, both ACCEPT paths
exclude production, and nothing else caught them; so an honest-looking
downgrade made the gateway strictly *less* usable than the fail-closed
default. They are now `high`, and the recorded reason is disclosure: REMORA's
own `_is_low_consequence` refuses to call a production read low-consequence
for exactly that reason, so `low` had contradicted the engine's own reasoning.
A classification must not be chosen for the routing it produces, which is why
the reason is written down next to it.

The `CoverageScope` domain must equal the domain the tool metadata declares. A
scope named something else is never consulted, every value returns `UNKNOWN`,
and every call is ungrounded; silently. It was named `gateway` while the
tools declared `knowledge_graph`, and nothing said so.

### A gap in the decision engine

A correctly declared low- or medium-risk read of production data has **no
route to human approval**. It abstains. Only declaring it `high` or `critical`
produces a `verify` where a person can decide.

The incentive that creates points the wrong way: an accurate low-risk
declaration is less usable than an inaccurate high-risk one. The missing piece
is a path that converts a fall-through into `verify` when an authority
resolved and the grounding signals hold, rather than to `abstain`.

Not changed here. It is a loosening of a default on the security-critical
path, and that is not something to do at the end of a session; but it is
worth doing deliberately.

### External review: what decision-os-min surfaced

`decision-os-min` is a compact capability-security kernel. Read as an external
audit of this architecture rather than as a competitor, its HB-1 write-up;
"the original executor tracked spent token_ids in an in-memory set, so a
second executor starts empty and a captured decision can be spent again";
pointed straight at a live defect here.

`EnforcementGate` knew two durable backends, `REMORA_PG_DSN` and
`REMORA_CHAIN_DB`. The durability guard in `servers/api.py` admits three: the
D1 state endpoint was added for a container with no writable disk, and the
gate was never told about it. So this deployment **passed the guard and then
kept its consumed-grant ledger in a process-local set**, so a captured ACCEPT
execution token was redeemable again after any container restart, inside its
one-hour age window. Exactly the replay class the durable ledger exists to
close, reintroduced by a backend the guard accepted and the gate could not
use.

Fixed: the gate takes `state_endpoint` and consumes through the same D1
adapter, with the INSERT and the watermark bump in one atomic batch; the
PRIMARY KEY is the compare-and-set, so of two racers exactly one commits.
An unreachable store returns `consumed_ledger_unavailable` rather than
assuming unspent, because assuming unspent *is* the double-spend, and a
failed record does not burn the grant it could not write.

Live after the fix: `pep_consumed` and `pep_ledger_watermark` are in D1 with
matching counts.

`tests/test_gate_d1_ledger.py` pins the defect class itself, not just this
instance: it reads the backends the guard admits and asserts the gate has a
field for each, so a fourth backend cannot be added to one and forgotten in
the other.

Two things from that repo are recorded as open rather than adopted tonight:
**Ed25519** where REMORA's reference paths are HMAC (a real asymmetry gap;
an HMAC verifier must hold a key that can also mint), and **ambient
isolation**: their TM-A probes attempt `fork`, `exec`, `mmap` and `ptrace`
after locking the agent runtime. REMORA answers the same question from
credential custody; the two are complementary, not alternatives.

### What this deployment is not

It runs `REMORA_ENV=production` under the **default research profile**, not
`controlled_pilot`.

`controlled_pilot` additionally requires a signed ToolSpec bundle, a signing
key and a trusted-identity allowlist, and there is no signed bundle for the OT
registry yet. Setting `REMORA_RUNTIME_PROFILE=controlled_pilot` without one
would make the container refuse to start; correctly.

This is a named gap, not a hidden one. Until the bundle exists, `assess` takes
risk tier and action type from the deployment-owned registry module rather
than from signed authority. Set `REMORA_RUNTIME_PROFILE` once the bundle is
there; `remora/toolcall/runtime_profile.py` will verify the claim rather than
take it on trust.

## Adding a governed tool

Two places, and the split is the important part:

1. `deploy/ot-pilot/ot_registry.py`: the callable and its authoritative
   metadata. This is where risk tier, action type and everything else that
   decides an outcome lives. It is deployment-owned and server-side.
2. `workers/mcp-gateway/src/tools.ts`: the MCP schema: name, description,
   argument shape.

A field added in `tools.ts` can never widen authority. It only changes what
the agent is able to propose; what that proposal is *worth* is decided from
the registry. A caller cannot assert its way to an ACCEPT; see
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
