# MCP execution surfaces (stage H, 2026-10-07)

> Producer-owned map, AI-assisted (Claude Code). Mapped at master `7c24e0d`;
> the consequential claims were re-checked against the code before
> publication. Deployed state is not visible from the repository and is
> marked UNVERIFIED where it matters.

This document lists every place in the repository where an MCP client can
make a tool run. For each place it says how authority reaches the effect,
and which of the strict v2 protections the path actually reaches. The aim
is the one in the security programme: every privileged MCP tool behind
REMORA, as enforced architecture rather than a deployment pattern. This map
shows how far that is true today.

## Summary

| Surface | Transport | Lease-gated | Effects mediated | Effect credentials held by | Strict v2 reached | Bypass |
|---|---|---|---|---|---|---|
| S1 `servers/mcp_remora.py` | stdio JSON-RPC | no | no | the stdio process | none | by design: direct egress and local reads; writes go to S3 |
| S2 `workers/mcp-gateway` | HTTP JSON-RPC `/mcp`, Worker to container | yes | no | executor container (GitHub token), Worker bindings (D1) | custody split when configured; not BindingPolicy, mediation or signature v2 | executor credentials and SQL outside the lease (acknowledged) |
| S3 `workers/agent-control` `/execute` | HTTP | only with `EXECUTION_SERVICE` bound, which the shipped config leaves commented out | no | the Worker (R2, D1, service bindings) | none | by configuration: `store_artifact` writes R2 without REMORA execution |
| S4 `scripts/remora_hook.py` | Claude Code hook | advisory only | n/a | n/a | none | advisory |

There is no MCP serve command in `remora/cli.py`. Only S2 runs the full
REMORA path: assess, grant, ExecutionLease and GovernedToolDispatcher.

## S1: local stdio MCP server

`servers/mcp_remora.py` serves a static list of fourteen tools over stdio
for Claude Desktop. `tools/call` runs the handler in-process; there is no
lease, grant or dispatcher. Most handlers send the agent's text to the
consensus, RAG or law-search Workers. The privacy profile decides which
endpoints exist: `local` (the default) blanks them all, while `demo` and
`enterprise` reach the network. `remora_repo_search` reads repository files and
`remora_session_status` reads a directory the agent names, both ungated. The
one governed tool, `agent_execute_tool`, hands off to S3. None of the strict
protections applies here, and none is claimed.

## S2: governed MCP gateway (Cloudflare Worker)

`workers/mcp-gateway` verifies the Cloudflare Access assertion on `/mcp`
(`src/admission.ts`) and translates `tools/call` into REMORA's execution API.

- **Path.** `assess` first. ACCEPT redeems the token at
  `/v1/execution/execute-accepted`; VERIFY or ESCALATE stores the call in a
  Durable Object, and the approved call is executed at `/v1/execution/execute`
  from that stored state. Both routes reach `_dispatch_under_lease` and the
  GovernedToolDispatcher. With the Ed25519 keys and `EXECUTION` configured,
  the authority container mints the lease and forwards it to the executor.
- **Binding.** The exact call is bound by `canonical_tool_call_hash` (name,
  arguments, tenant, target), and the lease is re-hashed before the tool runs.
  The agent never re-supplies arguments: execution uses the stored call.
  Numbers the Worker would change are refused before binding once #783
  (RMR-CR-013) is merged.
- **Effects.** Not mediated. The GitHub and knowledge-graph tools register
  with `register(name, fn)` (`deploy/gateway/gh_registry.py`,
  `deploy/gateway/kg_registry.py`), and no effect domain is configured. The
  executor holds `REMORA_GITHUB_TOKEN`, has internet egress, and reaches the
  graph and state D1 databases with unrestricted SQL through `graph.internal`
  and `state.internal`.
- **Strict v2.** Not reached as shipped. `REMORA_DEPLOYMENT_PROFILE` is
  `staging` (`wrangler.toml`), no `REMORA_RUNTIME_PROFILE` or
  `REMORA_BINDING_POLICY` is set, and signatures default to format v1. Turning
  a strict profile on as configured would fail custody: the authority
  container declares no `REMORA_EXECUTION_DOMAIN_ROLE`, no
  `REMORA_EFFECT_CREDENTIAL_ENV_NAMES` is set, and the executor receives
  `REMORA_PDP_SIGNING_KEY` (recorded in `src/index.ts` as a known exposure).
- **Found while mapping, fixed separately.** The API built the tool
  dispatcher before deciding whether to forward, so a strict authority raised
  `CustodyViolation` on every dispatch. Fixed in #785.

## S3: Agent Control Plane Worker

`workers/agent-control` `/execute` takes a shared bearer secret and runs a
static catalogue. When both `EXECUTION_SERVICE` and `EXECUTION_API_TOKEN` are
bound, approval-required tools use the canonical assess and execute-accepted
path. The shipped `wrangler.toml` leaves that binding commented out, so
`store_artifact` runs inside the Worker after a local D1 single-use approval
and writes R2 directly. The approval binds a hash of the input that the agent
sends again at execution time; that hash is not canonical JSON.

## S4: advisory hook

`scripts/remora_hook.py` is a PreToolUse hook that allows or blocks a Claude
Code tool call. It runs no tool and gates nothing outside the hook.

## Open gaps

1. S2 effects are not mediated. Making `effect_mediation` REQUIRED needs the
   gateway registry to register mediated tools against an effect domain
   (CR-005 provides the mechanism; the gateway does not use it yet).
2. S2 cannot start under a strict profile as configured (domain role, effect
   credential declaration, PDP key in the executor).
3. S2's executor reaches D1 with unrestricted SQL and holds a credential with
   internet egress, outside any lease.
4. S2's Worker isolate holds `REMORA_GITHUB_TOKEN` as a secret and a writable
   graph binding, broader than its header comment states.
5. S2 maps a missing `Mcp-Session-Id` to a shared proposal store; `/approve`
   relies on the REMORA approver role rather than `admitMcp`.
6. S3 runs writes in-Worker unless `EXECUTION_SERVICE` is bound, with a
   non-canonical input hash and arguments re-sent by the agent.
7. S1 `agent_audit_log` calls S3's `/audit` without the bearer S3 requires,
   and `remora_session_status` reads an agent-chosen directory.
8. Deployed state is UNVERIFIED: which secrets are set on the live Workers
   (Ed25519 keys, `EXECUTION`, `ACCESS_*`, `REMORA_PG_DSN`, `EXECUTION_SERVICE`)
   cannot be read from the repository.

## What this does not claim

The map is of the repository. It does not show what a given deployment
configures, and it does not establish that any credential is unreachable
outside REMORA. `credential_non_bypassability` and
`runtime_capability_surface_completeness` stay NOT_ESTABLISHED.
