# Governed MCP Gateway on Cloudflare — v1

**Status:** proposal
**Scope:** slice 1 of the Cloudflare deployment programme — a single-tenant
governed MCP gateway. Later slices are named in "Out of scope" and are not
designed here.

## Purpose

Put a verifiable execution boundary between an MCP client (Claude, ChatGPT,
Codex) and the systems it can change, deployed on Cloudflare, using the
existing REMORA enforcement path unmodified.

The agent sees ordinary MCP tools. Every call is routed through
assess → approve → execute before any side effect. The MCP handler holds no
credential to the downstream system; only `GovernedToolDispatcher` does. That
is what makes this an execution boundary rather than a filter, and it is the
property the deployment exists to demonstrate.

## Measured basis

Measured 2026-08-23 against `deploy/ot-pilot/Dockerfile` under Docker with
CPU and memory caps matching Cloudflare instance types. Local x86; Cloudflare
adds scheduling and image pull, so these are a floor and a relative ranking,
not absolute predictions.

| Instance | vCPU | Memory | Cold start | Warm assess p50 |
| --- | --- | --- | --- | --- |
| `lite` | 1/16 | 256 MiB | 17.7–18.6 s | 280 ms |
| `basic` | 1/4 | 1 GiB | 4.1–4.4 s | 92 ms |
| `standard-1` | 1/2 | 4 GiB | 2.3 s | 133 ms |

`standard-1` was measured under host contention and is noisy; `lite` and
`basic` are clean, repeated, consistent.

Peak RSS across the full OT battery (27 assess, 6 approvals, 7 executes) is
**69.5 MiB**. Memory is not the binding constraint — even `lite` has 3.7x
headroom. CPU is, and the cost sits in the framework: `import servers.api`
is 952 ms cumulative uncapped, of which FastAPI is 287 ms and
`importlib.metadata` 226 ms. REMORA's own modules are marginal
(`remora.adapters.storage`, 67 ms). Lazy-importing REMORA code cannot reach a
`lite`-viable cold start, because the cost is not REMORA's.

### Instance choice

Containers bill memory and disk on *provisioned* resources; only CPU moved to
actual usage (2025-11-21). Against the Workers Paid allowances (25 GiB-hours
memory, 200 GB-hours disk, 375 vCPU-minutes):

| Mode | Cost beyond the $5 plan | Latency |
| --- | --- | --- |
| `basic` always on | ~$7/month | no cold start |
| `lite` always on | ~$1.74/month | 280 ms per call |
| `basic` wake-on-demand | ~$0 for the first 150 wakes | 4.4 s per cold call |

**Decision: `basic`, always on.** Wake-on-demand saves roughly $7 a month and
pays 4.4 s of latency on every cold MCP call. For one tenant that is a bad
trade. Wake-on-demand becomes correct at multi-tenant scale with a container
per tenant, where the 4.4 s lands on the first call of a session rather than
on every call, and `sleepAfter` covers the rest of the session. It is
deliberately deferred, not rejected.

## Architecture

```
Claude / ChatGPT
      | MCP over Streamable HTTP + OAuth
      v
remora-mcp-gateway (Worker)      identity -> tenant -> proposal
      |
      v
RemoraContainer (basic, always on)
servers.api, REMORA_ENABLED_SURFACES=execution
      |
      v
durable execution state (Postgres)
```

The Worker owns the MCP protocol and OAuth. The container owns policy and
enforcement, unchanged from `deploy/ot-pilot/`. No policy logic is
reimplemented in TypeScript: a second implementation would make REMORA's own
parity the thing to prove, and that is not a cost this slice should carry.

### Naming

`remora-mcp-gateway`. The account already holds a `remora` Worker and a
`remora-audit` D1 database; neither is touched.

## Open question: durable state transport

`remora/persistence/execution_state.py` speaks psycopg or sqlite3 directly.
Container disk is ephemeral, so a container-local SQLite file is not durable
state — that is exactly the failure mode REMORA's own history records, where a
volatile ledger made one-time grants replayable.

Cloudflare's documentation describes `enableInternet` and outbound
interception consistently in terms of **HTTP**. Whether a container may open a
raw TCP connection for the Postgres wire protocol is not stated. This is
unresolved and is the first thing step 2 tests.

- **If raw TCP works:** the container connects directly to a managed Postgres
  over TLS. No new persistence code. The provider is deliberately not chosen
  here: it only matters once the transport is known, and choosing it earlier
  would be a decision made without the fact that constrains it.
- **If it does not:** the fallback is a Hyperdrive binding reached through the
  Worker, which requires a new HTTP-backed durable-state backend in
  `remora/persistence/`. That is real new code in the most
  security-critical part of the codebase, and it changes this slice's size.

No work depending on the answer starts before step 2 reports it.

## Tool surface

The OT registry's tools, exposed as ordinary MCP tools:

`read_sensor`, `adjust_setpoint`, `set_valve_position`, `acknowledge_alarm`,
`create_work_order`, `close_work_order`.

### The VERIFY path

Measurement shows 25 of 27 OT cases resolve to `verify`. This is the normal
path, not an edge case, and MCP has no native "wait for human approval"
semantics.

The tool returns immediately with a proposal ID and status
`pending_approval`; a separate `remora.approval_status` tool lets the agent
poll. Blocking the MCP call until a human answers would time out in both
Claude and ChatGPT.

## Deploy sequence

Each step is verified before the next begins.

1. **Multi-stage Dockerfile.** The current image is 621 MB, of which 206 MB is
   `gcc` and `libpq-dev` left in the runtime layer. Acceptance: the OT battery
   is still green locally, and the image is smaller.
2. **Container alone on Cloudflare**, no MCP. Acceptance: the
   `controlled_pilot` profile starts fail-closed, and the durable-state
   transport question above is answered.
3. **MCP Worker in front**, connected to Claude Code locally.
4. **OAuth via Cloudflare Access.**
5. **End to end:** agent -> assess -> approve -> execute -> effect
   verification -> evidence.

## Testing

`deploy/ot-pilot/run_ot_battery.py` is already an end-to-end contract: 27
cases including tamper cases that must be refused. The acceptance criterion
for this slice is that the battery runs green **against the deployed
gateway**, not only locally. A tamper case that passes is a failed deploy.

## Out of scope

Each becomes its own slice with its own design: exeQta knowledge-graph
integration, approval console, usage metering and billing, credential
onboarding, multi-tenant provisioning, wake-on-demand.
