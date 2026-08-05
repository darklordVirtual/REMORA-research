# Execution-path deployment quickstart

The shortest path from a clean machine to a governed `assess → approve →
execute → dispatch` round with a durable, verifiable audit trail. Everything
here is the enforcement-grade path (`/v1/execution/*` + `GovernedToolDispatcher`
under an `ExecutionLease`), not the advisory library call.

**Read this first — what this deployment is and is not.** REMORA governs the
tools *you register with it*. The PEP is not unbypassable until the dispatcher
fronts the real credentials for those tools (REM-024, in progress): an
application that keeps a second, ungoverned path to the same side effects has
opted out of enforcement. The lease nonce ledger is in-process (REM-025), so
run one API process per tenant-critical deployment until that closes. Status
ladder per capability: [`../assurance/capability_register_v1.yaml`](../assurance/capability_register_v1.yaml).

## 1. Install

```bash
python -m pip install <remora-wheel>[api,postgres]
```

The wheel ships `remora/`, `servers/` and `schemas/` (contract-tested by
`tests/test_packaging_contract.py`; REM-045). `api` pulls FastAPI/uvicorn;
`postgres` pulls both Postgres drivers the durable paths import.

## 2. Configure

Production mode (`REMORA_ENV=production`) refuses to start unless the
fail-closed set is complete:

| Variable | Purpose | Production |
|---|---|---|
| `REMORA_API_TOKENS` | Token → `(tenant, role)` map; the only mode with real role separation | required |
| `REMORA_API_BEARER_TOKEN` | Also required in production, in addition to the token table above — the startup check asks for both. Set it to any token that appears in `REMORA_API_TOKENS`. | required |
| `REMORA_RUNTIME_EVIDENCE_JSONL` (or the shipped `datasets/remora_knowledge_v1/evidence_packs/evidence_objects.jsonl`) | Retrieval evidence store. Production refuses to start when it resolves to an **empty** store, and the check runs at import time even for deployments that only use `/v1/execution`. Ship the pack or point this at your own. | required |
| `REMORA_CONTROL_PLANE_DSN` (or `REMORA_CONTROL_PLANE_DB`) | Durable DecisionEnvelope store (`postgres://` / `sqlite:` / SQLite path) | required |
| `REMORA_PG_DSN` (or `REMORA_CHAIN_DB`) | Durable execution state: tenant audit chain, review queue, one-time-grant ledger | required |
| `REMORA_ORACLE_BACKEND` | Real oracle backend; `mock`/`auto` refused | required |
| `REMORA_PDP_SIGNING_KEY` | Signs `PolicyDecisionToken` (mandatory expiry, jti) | required in practice — unsigned tokens are rejected by the strict gate |
| `REMORA_LEASE_SIGNING_KEY` | Signs `ExecutionLease` (falls back to PDP key) | recommended |
| `REMORA_AUDIT_SIGNING_KEY` | HMAC over tenant-chain entries | recommended |
| `REMORA_ENVELOPE_SIGNING_KEY` | HMAC over envelope hashes | recommended |
| `REMORA_TOOL_REGISTRY_MODULE` | Deployment-owned tool registry (section 3) | required for dispatch |
| `REMORA_SEMANTIC_BUNDLE_MODULE` | Deployment-owned semantic bundle: tool contracts + signatures + validators + state, hashed and consulted by `build_full_observation` on assess/execute (SHELF-020) | optional — without it the registry-only path runs |
| `REMORA_INTENT_SOURCE_FILE` | Research-profile intent source: JSON map of `intent_ref` → approved workflow intent (`servers/semantic_bundle_research.py`) | optional |
| `REMORA_MAX_TOOL_RESULT_BYTES` | Cap on how much of a tool result is retained in the response/audit record; the full result is always hashed (`remora/enforcement/result_envelope.py`) | optional — default 65536 |

Key generation: `python -c "import secrets; print(secrets.token_hex(32))"`.
Rotation policy: [`../assurance/rbac_policy_v1.md`](../assurance/rbac_policy_v1.md).

Without durable state the server still starts in development mode, logs a
warning, and reports `execution_state_durable: false` — and a consumed
execution grant becomes replayable after a restart. That configuration is for
development only.

## 3. Write the tool registry module

Tools come **only** from this module — request payloads can never add or
replace callables, so downstream credentials stay app-side. The contract:

```python
def register_tools(register: Callable[[str, Callable], None]) -> None:
    register("my_tool", my_tool_callable)
```

Start from the shipped research profile,
[`servers/tool_registry_research.py`](../../servers/tool_registry_research.py):
two side-effect-bounded tools (sandboxed artifact write, read-only telemetry)
that make the full chain demonstrable, and an explicit list of what it refuses
to register and why. Copy it, replace the tools with yours, and keep the
discipline: governance metadata bound to callable identity, never to the
caller or the tool's name.

```bash
export REMORA_TOOL_REGISTRY_MODULE=my_app.remora_registry
```

## 4. Run

```bash
uvicorn servers.api:app --host 0.0.0.0 --port 8000   # mounts /v1/execution/*
```

**Or run the whole thing in containers.** `deploy/ot-pilot/` is a working
production-mode pilot: API plus PostgreSQL, an example tool registry and
semantic bundle, and a battery of OT cases that drives the full chain and
prints the metrics.

```bash
docker compose -f deploy/ot-pilot/docker-compose.yml up --build -d
python deploy/ot-pilot/run_ot_battery.py
docker compose -f deploy/ot-pilot/docker-compose.yml down -v
```

The compose file supplies every fail-closed prerequisite rather than weakening
the check — removing any one of them and watching the API refuse to start is
the fastest way to confirm the guarantee is real.

## 5. Verify before trusting

```bash
python -m remora doctor --json        # env self-check; warns on non-durable state
curl -s localhost:8000/v1/health
```

Then drive one full round and check the trail it leaves:

1. `POST /v1/execution/assess` — ACCEPT returns a signed 300 s one-time token;
   VERIFY/ESCALATE enqueues for review.
2. `POST /v1/execution/approve` — authenticated approver role, bounded TTL.
3. `POST /v1/execution/execute` — re-decides on a fresh observation
   (equal-or-safer executes, stricter invalidates, changed args are refused),
   consumes the grant atomically, dispatches through the lease-bound
   dispatcher.
4. Verify the chain, three independent ways:

```bash
curl -s localhost:8000/v1/execution/audit/verify -H "Authorization: Bearer $TOK"
curl -s localhost:8000/v1/audit/chain/verify     -H "Authorization: Bearer $TOK"
python scripts/verify_envelope_chain.py --store-db <path>   # offline, no server
```

A replayed token must come back `token_already_consumed`; a crash mid-dispatch
must leave an authorization row with no result row, never a side effect with
no record. Overdue review items sweep to ABSTAIN on every queue interaction;
a deployment whose queues can sit fully idle past the review TTL should
schedule `ReviewQueue.expire_due()` for wall-clock expiry.

The complete production-mode stack — API, Postgres and operator console with
a 15-case OT battery and an immutable evidence archive — ships as one command:
`docker compose -f deploy/ot-pilot/docker-compose.yml up --build -d`
(console at `localhost:8081`, Swagger at `localhost:8080/docs`).

## Known limits (the honest part of the label)

- Advisory until the dispatcher fronts your real tool credentials (REM-024).
- Lease nonces are per-process (REM-025); the jti ledger *is* durable when
  section 2's state backend is configured.
- Tool interception has not been independently validated (REM-030).
- Shadow-mode research software: no production certification, no external
  replication. See the README Limitations section.

→ Air-gapped specifics: [`onprem-airgapped.md`](onprem-airgapped.md) ·
Azure topology: [`azure-reference-architecture.md`](azure-reference-architecture.md) ·
Full endpoint semantics: [`../07-api-reference.md`](../07-api-reference.md)
