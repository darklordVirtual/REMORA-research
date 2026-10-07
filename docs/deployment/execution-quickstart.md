# Execution-path deployment quickstart

The shortest path from a clean machine to a governed `assess`, `approve`,
`execute`, `dispatch` round with a durable, verifiable audit trail. Everything
here is the enforcing path (`/v1/execution/*` + `GovernedToolDispatcher` under
an `ExecutionLease`), not the advisory library call.

For a new developer, external reviewer or pilot partner, **use the strict
runtime profile below**. It deliberately refuses the weaker registry-only path
so a handoff cannot accidentally demonstrate a configuration that would never
be acceptable for a controlled deployment.

**Read this first: what this deployment is and is not.** REMORA governs the
tools *you register with it*. The PEP is not unbypassable until the dispatcher
fronts the real credentials for those tools: an application that keeps a
second, ungoverned path to the same side effects has opted out of enforcement.
Status per capability is recorded in
[`../assurance/capability_register_v1.yaml`](../assurance/capability_register_v1.yaml).

## 1. Install

```bash
# From a clone (what every other document in this repo assumes):
python -m pip install -e ".[api,postgres]"

# Or build a wheel first and install that:
python -m build            # writes dist/remora_assurance-<version>-py3-none-any.whl
python -m pip install "dist/remora_assurance-<version>-py3-none-any.whl[api,postgres]"
```

The package is not published to PyPI: REMORA is source-available under
BUSL-1.1, so install from a clone or from a wheel you built.

The wheel ships `remora/`, `servers/` and `schemas/`. `api` pulls FastAPI and
uvicorn; `postgres` pulls the drivers used by durable multi-worker paths.

For a source checkout:

```bash
python -m pip install -e '.[dev,api,postgres]'
```

## 2. Select the handoff profile first

For technical review:

```bash
export REMORA_RUNTIME_PROFILE=review
export REMORA_ENABLED_SURFACES=execution
```

For a bounded pilot:

```bash
export REMORA_RUNTIME_PROFILE=controlled_pilot
export REMORA_ENV=production
export REMORA_ENABLED_SURFACES=execution
```

The profiles mean:

| Profile | Signed ToolSpec | Durable execution state | Intended use |
|---|---:|---:|---|
| `development` | optional | optional | local development/tests |
| `research` | optional | optional | benchmarks/shadow research |
| `review` | **required** | **required** | external developer/reviewer handoff |
| `controlled_pilot` | **required** | **required** | bounded pilot; also requires `REMORA_ENV=production` |

An unset `REMORA_RUNTIME_PROFILE` remains `research` for backward compatibility.
Nothing is silently promoted into a stronger trust contract.

### Optional authoritative execution context

Set `REMORA_REQUIRE_EXECUTION_CONTEXT=1` and
`REMORA_EXECUTION_CONTEXT_MODULE=my_app.execution_identity` to require the
execution-context binding on assessment, review, ACCEPT redemption and
dispatch. Existing profiles do not enable it automatically.

The module exports `execution_context_provider`, implementing
`ExecutionContextProvider` from
[`remora/governance/execution_identity.py`](../../remora/governance/execution_identity.py):

| Method | Deployment responsibility |
|---|---|
| `capture(proposal_id, tenant, principal, tool_call_hash)` (keyword arguments) | Return an immutable `ExecutionContextV1` from trusted session, inference-gateway and deployment records. Its subject must match the authenticated principal, and its proposal, tenant and call must match the arguments. |
| `current_build_provenance_digest()` | Return the executor's current build-provenance SHA-256 digest from deployment-owned state. |
| `data_scope_valid(context)` | Return exactly `True` only while the recorded classification and declared access scope remain valid under deployment policy. |

Provider failures must raise `ExecutionContextRefused` with a bounded reason;
they must not return guessed values. Capture requires a deployment-declared
runtime hash, a build-provenance digest and named authorities with evidence
references for subject, initiating model, runtime and data scope. V1 accepts
no arbitrary extensions, floats or free-form metadata maps. Digest values are
lowercase SHA-256 hex; authority references are identifiers, not evidence
validated independently by REMORA.

The model authority's evidence reference must identify the exact initiating
inference event. A current model configuration or an ambiguous match between
identical calls is insufficient; the provider must refuse capture when it
cannot establish that lineage.

Capture happens before assessment. The context digest enters the observation,
the grant's call/context/proposal binding and authorization-context hash, and
the signed lease. Review and workers read the original canonical context from
the tenant chain; they never recapture it. The executor checks its own cached
startup runtime identity, current build provenance and classification validity
before consuming the lease nonce. It does not compare the initiating model to
a currently active model.

In a custody split, configure the provider on both domains. The authority
captures the intended executor runtime identity; the executor supplies its own
build and data-scope checks. The remote hop carries the historical context,
whose digest and lineage must match the signed lease. Runtime declarations
remain deployment assertions, not hardware attestation.

The tenant chain retains canonical context bytes and their digest on the
assessment. Execution results retain the context hash, execution ID (the
single-use grant JTI) and dispatch-check evidence. Durable outbox settlement
preserves these fields for crash recovery. Persistence across restart requires
the durable chain configuration described below; an in-memory development
chain is not durable evidence.

Effect receipts for a context-bound dispatch must carry its `execution_id`
and `execution_context_hash`. SDK consumers pass the latter to `verify_effect`
and use the recorded execution ID, rather than a locally invented ID.
Evidence export projects the historical context without consulting today's
provider or configuration. This path implements no TRACE exporter or TRACE
signing identity.

`execution_context_authoritative_binding` remains `NOT_ESTABLISHED` pending
deployment evidence for source authority and the end-to-end property. Neither
`runtime_capability_surface_completeness` nor
`implementation_effect_non_transitivity` is upgraded. Data scope covers
`proposal_input` and/or `declared_tool_access`; it does not classify unknown
downstream data.

## 3. Configure the strict execution path

For `review` and `controlled_pilot`, the execution path refuses to resolve tool
metadata unless these trust prerequisites are present:

| Variable | Purpose | Strict profile |
|---|---|---:|
| `REMORA_TOOLSPEC_BUNDLE` | Signed authority for callable identity, schema, risk/action metadata, target policy, credential scope and idempotency contract | **required** |
| `REMORA_TOOLSPEC_VERIFY_KEYS` | Ed25519 public keys trusted to sign the bundle. The runtime can verify with them and author nothing; each signer is named by its derived key id | **required** |
| `REMORA_TOOLSPEC_PINNED_DIGEST` | The one bundle this deployment accepts. A signature proves who signed, the pin proves which bundle is current | **required** |
| `REMORA_TOOLSPEC_SIGNING_KEY` | v1 HMAC model, outside strict profiles only. A strict runtime that holds it is refused at startup in every role, because an HMAC verifier can author bundles | **refused** |
| `REMORA_TOOL_REGISTRY_MODULE` | Deployment-owned callable registry; callers cannot inject tools | **required** |
| `REMORA_PG_DSN` or `REMORA_CHAIN_DB` | Durable execution state: tenant chain, review state and one-time-grant ledger | **required** |
| `REMORA_PDP_SIGNING_KEY` | Signs the short-lived PDP → PEP grant | **required** |
| `REMORA_ENVELOPE_SIGNING_KEY` | Signs each envelope's audit hash; without it every audit record is written with `signature: null` and the chain is tamper-evident in name only | **required** |
| `REMORA_EXECUTION_DOMAIN_ROLE` | `authority` or `executor`: which half of the custody split this process is (property E). An unset role is refused, because one process being both halves is what the split removes | **required** |
| `REMORA_EFFECT_CREDENTIAL_ENV_NAMES` | Comma-separated names of the environment variables that hold downstream effect credentials. The authority domain must not hold them; the executor must. Empty is refused as vacuous | **required** |
| `REMORA_SEMANTIC_BUNDLE_MODULE` | Module exposing `resolve_intent` (or `resolve_intent_detailed`). Strict profiles require a resolver (property D): without one every call would hard-abstain, so startup refuses instead | **required** |

Fastest path to a configuration that satisfies all of the above:

```bash
remora init-review          # writes .remora/ with keys, bundle, registry, intents
set -a; . .remora/authority.env; set +a
remora doctor               # every strict prerequisite, named, before serve
```

Hand-written equivalent:

```bash
export REMORA_RUNTIME_PROFILE=review
export REMORA_ENABLED_SURFACES=execution

export REMORA_TOOLSPEC_BUNDLE=/run/remora/toolspec-bundle.json
# Both printed by the offline signer, which keeps the seed:
#   python -m remora.toolcall.toolspec_sign --seed-file signer.seed \
#       --bundle unsigned.json --out /run/remora/toolspec-bundle.json
export REMORA_TOOLSPEC_VERIFY_KEYS='<ed25519 public key, hex>'
export REMORA_TOOLSPEC_PINNED_DIGEST='<bundle digest>'
export REMORA_TOOL_REGISTRY_MODULE=my_app.remora_registry
export REMORA_PDP_SIGNING_KEY='replace-me-too'
export REMORA_ENVELOPE_SIGNING_KEY='replace-me-as-well'
export REMORA_LEASE_SIGNING_KEY='replace-me-three'

# Custody split (property E) and intent provenance (property D). The
# authority process holds no effect credential; run a second process with
# REMORA_EXECUTION_DOMAIN_ROLE=executor that holds ACME_SMTP_PASSWORD and
# REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC instead of the signing keys.
export REMORA_EXECUTION_DOMAIN_ROLE=authority
export REMORA_EFFECT_CREDENTIAL_ENV_NAMES=ACME_SMTP_PASSWORD
export REMORA_SEMANTIC_BUNDLE_MODULE=my_app.remora_semantic_bundle

# Multi-worker / partner-shaped review:
export REMORA_PG_DSN='postgresql://remora:...@postgres/remora'

# Or, for a single-node technical review:
# export REMORA_CHAIN_DB=/var/lib/remora/execution.db
```

Key generation:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Production server prerequisites

`REMORA_ENV=production` additionally requires the API/auth and control-plane
settings enforced by `servers/api.py`, including tenant-aware tokens and a
durable DecisionEnvelope store.

If **only** `REMORA_ENABLED_SURFACES=execution` is mounted, an oracle backend
and retrieval evidence pack are **not** required because `/v1/assess` and
`/v1/rerun` are unmounted. If the `assess` surface is enabled, production mode
requires an explicit non-mock oracle backend and a usable evidence store.

Useful variables beyond the strict-profile minimum:

| Variable | Purpose |
|---|---|
| `REMORA_API_TOKENS` | token → `(tenant, role)` mapping in production |
| `REMORA_API_BEARER_TOKEN` | production bearer token prerequisite |
| `REMORA_CONTROL_PLANE_DSN` or `REMORA_CONTROL_PLANE_DB` | durable DecisionEnvelope/control-plane store |
| `REMORA_LEASE_SIGNING_KEY` | separate lease signing key; may fall back to PDP key |
| `REMORA_AUDIT_SIGNING_KEY` | HMAC for tenant-chain entries |
| `REMORA_SEMANTIC_BUNDLE_MODULE` | deployment-owned semantic contracts/state/validators |
| `REMORA_INTENT_SOURCE_FILE` | approved intent reference source for the research bundle |
| `REMORA_OUTBOX_STALE_SECONDS` | stale dispatch reconciliation window; default 900 s |
| `REMORA_MAX_TOOL_RESULT_BYTES` | retained tool-result preview cap; full result remains hashed |
| `REMORA_MAX_REQUEST_BYTES` | request body cap in bytes (default 1048576); larger bodies get HTTP 413 |
| `REMORA_MAX_EXECUTION_JSON_BYTES` | strict-JSON admission cap on `/v1/execution/*` and `/v1/assess` (default 1048576); refused bodies get HTTP 400 with a `code` |
| `REMORA_MAX_EXECUTION_JSON_DEPTH` | maximum JSON nesting on the same surfaces (default 32); duplicate member names, `NaN`/`Infinity`, unpaired surrogates and invalid UTF-8 are refused regardless of this value |

## 4. Build a ToolSpec bundle

A strict-profile tool is not authorized merely because a Python callable with
that name exists. The ToolSpec is the deployment-owned statement of what that
callable *means*.

The schema is `schemas/tool_spec_v1.yaml`; the implementation and signing
helpers are in `remora/toolcall/toolspec.py`. A ToolSpec covers, among other
things:

- stable tool/callable identity and implementation digest;
- JSON argument schema;
- risk tier, action type and domain;
- allowed targets;
- credential scope;
- idempotency semantics;
- optional semantic/effect metadata.

The same signed identity is resolved at assessment and checked again before
dispatch. A spec changed between those points is refused rather than silently
reinterpreting an old approval.

## 5. Write the callable registry module

Tools come only from deployment configuration; request payloads cannot add or
replace callables, so downstream credentials remain app-side.

```python
def register_tools(register):
    register("my_tool", my_tool_callable)
```

Start from [`../../servers/tool_registry_research.py`](../../servers/tool_registry_research.py)
for the registry interface, but do not copy its research classifications as
production policy. Your Signed ToolSpec is the authority for the strict path.

## 6. Run

```bash
uvicorn servers.api:app --host 0.0.0.0 --port 8000
```

For a deployment-shaped example, use the OT pilot stack:

```bash
docker compose -f deploy/ot-pilot/docker-compose.yml up --build -d
python deploy/ot-pilot/run_ot_battery.py
docker compose -f deploy/ot-pilot/docker-compose.yml down -v
```

A useful negative test is to remove one strict prerequisite and confirm that
startup/policy identity construction or the first execution-path lookup fails
closed instead of falling back to the legacy path.

## 7. Verify before trusting

```bash
python -m remora doctor --json
curl -s localhost:8000/v1/health
```

Then drive one full round:

1. `POST /v1/execution/assess`: the server derives authoritative context and
   resolves the signed ToolSpec. ACCEPT receives a short-lived single-use
   grant; VERIFY/ESCALATE enters review.
2. `POST /v1/execution/approve`: authenticated approval with bounded TTL.
3. `POST /v1/execution/execute`: fresh re-gate, exact-call binding, PEP
   consume, lease creation and governed dispatch.
4. The dispatch outbox records `DISPATCH_PENDING`, then `DISPATCHING`, then a terminal
   outcome. An undeterminable side effect becomes `UNKNOWN`; it is not blindly
   retried.
5. Effect verification and tenant audit records make the proposal-to-effect
   lifecycle inspectable.

Verify the chain:

```bash
curl -s localhost:8000/v1/execution/audit/verify -H "Authorization: Bearer $TOK"
curl -s localhost:8000/v1/audit/chain/verify     -H "Authorization: Bearer $TOK"
python scripts/verify_envelope_chain.py --store-db <path>
```

Run the handoff-focused tests before the full suite:

```bash
python -m pytest tests/test_runtime_profile.py -q
python -m pytest tests/test_toolspec_execution_wiring.py -q
python -m pytest tests/test_execution_outbox_wiring.py -q
python -m pytest tests/test_token_hardening.py -q
python -m pytest tests/test_execution_api.py -q
```

Then:

```bash
python -m pytest tests/ -q
```

## 8. Operational logging

The tenant audit chain and the operational log answer different questions.
The chain is the governance record (what was authorised, under which policy,
by whom) and it is what an auditor reads. The operational log is what an
on-call engineer reads: what the process did, when, and whether it worked.

The safety core emits structured events on the `remora.governance` logger.
Nothing is emitted unless you configure a handler for it:

```python
import logging

logging.getLogger("remora.governance").setLevel(logging.INFO)
```

| Event | Emitted when | Level |
|---|---|---|
| `decision.made` | every policy decision, at the engine's build choke point | INFO |
| `decision.invariant_violated` | a decision broke a `CORE_INVARIANTS` check and was withdrawn to ESCALATE | ERROR |
| `lease.issued` | an execution lease is minted | INFO |
| `grant.checked` | the PEP accepts or refuses a grant; `consumed=true` marks a spent one-time grant | INFO / WARNING when refused |
| `dispatch.settled` | an outbox row reaches a terminal state | INFO / WARNING unless SUCCEEDED |

Each record carries a structured payload on the `remora` attribute for
machine consumption, alongside the rendered message.

**Field names are screened.** `governance_event` raises `SecretFieldError`
rather than logging a field whose *name* looks like a credential. Log an
identifier (`token_jti`), a digest (`tool_args_hash`) or a boolean
(`token_verified`); never the value. A logging call must never become the
reason a key leaks.

## Known limits

- REMORA cannot enforce a tool the agent can reach through another credential
  or network path outside the governed dispatcher.
- A benchmark or passing test suite is not external field validation.
- Some capabilities in the repository are optional, experimental or only
  wired to reference paths; use the capability register rather than code
  presence as the maturity source of truth.
- Shadow/research status and external-replication caveats remain in force; a
  strict runtime profile is a configuration guard, not a certification.

Start a review with [`../../DEVELOPER_OVERVIEW.md`](../../DEVELOPER_OVERVIEW.md),
then `ARCHITECTURE.md`, then the capability/claim registers. Do not begin by
reverse-engineering the experiments directory.

## Asynchronous dispatch (opt-in, issue #82)

By default `POST /v1/execution/execute` dispatches synchronously in the
API process. With `REMORA_ASYNC_DISPATCH=1` the API answers **202 after
durable authorization** (the queue's EXECUTE outcome and the
dispatch-intent row commit in one transaction) and a standalone worker
performs the dispatch half:

```bash
REMORA_ASYNC_DISPATCH=1 uvicorn servers.api:app &
python scripts/run_dispatch_worker.py --interval 5   # or --once
python scripts/run_outbox_reconciler.py --interval 300
```

The worker claims exclusively before any grant is minted, refuses intents
past their persisted `authorization_expires_at`, caps the minted token at
that expiry, re-verifies the persisted payload against the recorded
binding, and records the original requester as the actor with its own
identity as `executed_by`. Poll `GET /v1/execution/proposals/{id}` for
the outcome (the 202 body is `ExecutionPendingResponse`; the Python SDK
returns `PendingExecution`).

Status: implemented behind the flag and covered by CI and contract
tests; **not enabled in any reference profile**, so the reference
deployments stay synchronous until the async activation gate (issue
#423) closes. Both scripts refuse an in-process outbox: durable state
(`REMORA_PG_DSN`/`REMORA_CHAIN_DB`) is mandatory.
