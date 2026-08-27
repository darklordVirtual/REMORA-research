# What are the public interfaces?

This document maps the canonical `DecisionEnvelope` contract, the
`PolicyObservation` input, the decision engine, the Oracle ABC, adapters, the
enforcement (PDP/PEP) library, and the MCP tool surface. **Implementation
source is authoritative**; every signature below is verified against source by
`tests/test_api_reference_doc.py`, if this document drifts from the code, CI
fails.

## The HTTP surface, concretely

The machine-readable contract is [`schemas/openapi.json`](../schemas/openapi.json)
(OpenAPI 3.1, 23 paths). CI fails on drift between it and the routes, so it is
the authority for request and response shapes; this document explains them.

A first round-trip against a development-profile server, which is the shortest
path to a 200 before the strict-profile prerequisites are configured:

```bash
# Development profile: in-process stores, no ToolSpec bundle required.
# Never use this configuration for anything you would not undo by hand.
export REMORA_ENV=development
export REMORA_API_BEARER_TOKEN=dev-token
export REMORA_ORACLE_BACKEND=mock
export REMORA_API_ALLOW_MOCK_ORACLES=true
python -m uvicorn servers.api:app --port 8000
```

Read the token from the environment rather than pasting it into a command;
a bearer token on a command line ends up in shell history and in process
listings:

```bash
AUTH="Authorization: Bearer ${REMORA_API_BEARER_TOKEN}"

# 1. Is it up, and what policy is it running?
curl -s localhost:8000/v1/health
curl -s localhost:8000/v1/policy/version -H "$AUTH"

# 2. Gate a proposed tool call.
curl -s localhost:8000/v1/assess   -H "$AUTH"   -H "Content-Type: application/json"   -d '{
        "question": "Restart the payments worker in production",
        "tool_call": {
          "tool_name": "restart_service",
          "arguments": {"service": "payments-worker", "environment": "prod"}
        }
      }'
```

The response carries the decision, the reasons that produced it, and the
envelope's audit block. Abridged: the full response has 15 top-level keys and
`policy_decision` carries 11 fields; `schemas/openapi.json` is the complete
contract:

```json
{
  "request_id": "…",
  "proposal_id": "…",
  "policy_decision": {
    "action": "abstain",
    "reasons": ["evidence_contradicted"],
    "human_review_required": false,
    "evidence_required": true,
    "source_of_decision": "hard_block"
  },
  "envelope": {
    "audit": {
      "hash": "…",
      "previous_hash": null,
      "genesis": true,
      "signature": null,
      "policy_bundle_hash": "sha256:…",
      "policy_components": {
        "covers": {
          "policy_engine": "sha256:…",
          "risk_profile": "sha256:…",
          "envelope_schema": "sha256:…",
          "tool_registry": "sha256:…",
          "engine_mode": "sha256:…",
          "opa_policy": null
        },
        "not_covered": ["adapter_state", "delegation_state"]
      },
      "schema_version": "2"
    }
  }
}
```

**`policy_components` is the per-component form of `policy_bundle_hash`, and
its `not_covered` half is not decoration.** The composite is built over the
same six components, so it can say *that* the trust base differed and never
*which part*: two independently signed records carrying only the composite
compare wholesale. Recording the components makes a component-by-component
join constructible, which is what tells a verifier that an authorization was
evaluated against the trust base actually in force at the enforcement point,
a question that can fail with no change at all if a stale snapshot was read.

`not_covered` names trust-base elements the decision depends on that carry no
digest here. A record that lists coverage and stays silent about the rest
reads as complete coverage. A component that is configured but absent (OPA
with no policy path set) carries `null` rather than being dropped, because
present-and-unset and not-a-component-here are different facts.

The execution surface writes the same block twice: on `execution_authorized`
as the view the PDP decided against, and on `execution_result` re-read after
dispatch. The closure record deliberately re-reads rather than copying the
admission value; a join that cannot fail proves nothing.

The key is absent, not null, on records written before it existed; see
`POST_V2_AUDIT_KEYS` in `remora/governance/envelope.py`.

The decision key is **`policy_decision`**, not `decision`. `action` is one of
`accept`, `verify`, `abstain`, `escalate`. `reasons` names every rule that
fired, in the order the ladder evaluated them; that list, not the action
alone, is what an audit reads, and every value is a member of
`DecisionReason` (`remora/policy/report.py`).

**The action shown above is illustrative, not fixed for this request.**
`/v1/assess` consults the evidence layer, and the same call returns `abstain`
where a local NLI backend is installed and `verify` where evidence is merely
inconclusive. That is the surface behaving as designed (an unresolved
evidence question is a reason to hold, not to decide), but it means you must
branch on the returned `action`, never on the one printed in a document. The
enforcing `/v1/execution/*` path does not have this property: it runs the
policy engine under the execution profile, where a probabilistic signal can
structurally never produce ACCEPT.

Two things in that response are worth reading closely. `signature` is `null`
because the development profile has no `REMORA_ENVELOPE_SIGNING_KEY`;
production refuses to start without one, precisely so this field is never
null there. And `genesis: true` is *recorded*, not inferred from
`previous_hash` being null; a failed chain lookup raises rather than
silently restarting the chain.

This exact round trip is executed by `tests/test_api_reference_examples.py`,
so the response shown above cannot drift from the one the server returns.

For the enforcing surface (`/v1/execution/*`: assess, then approve, then execute, with
a single-use grant and an execution lease) see
[deployment/execution-quickstart.md](deployment/execution-quickstart.md); it
requires the strict-profile prerequisites and is not reachable from the
development configuration above.

→ [01-architecture.md](01-architecture.md) for how these interfaces fit together.
→ [06-reproducibility.md](06-reproducibility.md) for the result JSONL schema.

---

## DecisionEnvelope, canonical governance contract

`DecisionEnvelope` (`remora/governance/envelope.py`) is the canonical v2
decision record: a nested, JSON-serialisable structure of frozen dataclasses (attribute-immutable; nested list/dict fields are not deep-frozen). Do not add
blocks without updating the envelope hash and schema.

| Block | Contents |
|---|---|
| `request` | The proposed action: who proposed it, domain, risk tier, action type, target environment |
| `assessment` | Consensus observables (trust, H, D, phase), evidence signals, policy inputs |
| `gate` | Outcome (`accept` / `verify` / `abstain` / `escalate`), reasons, policy version |
| `reviewer_context` | What a human reviewer needs when the outcome is VERIFY/ESCALATE |
| `follow_up` | Required follow-up actions and their state |
| `history` | Session-level history references |
| `policy_learning` | Signals exported to the (experimental) learning layer |
| `audit` | SHA-256 hash-chain linkage and audit metadata |
| `effect` | Reserved for decision-to-effect execution state (`executed`, `tool_call_hash`, `effect_outcome`, `ledger_entry`) — **no producer populates it yet**: the execution outcome is recorded in the tenant audit chain, not in the envelope |
| `causal_explanation` | Optional policy-only what-if analysis (`decision_scope="policy_only"`) |

Serialise with `envelope.to_dict()`. The audit hash chain
(`remora/audit/hash_chain.py`, class `AuditHashChain`) links records as
`hᵢ = SHA-256(hᵢ₋₁ ‖ record_json)`; modification of a past record breaks all
subsequent hashes. This is tamper-*evidence*, not tamper-prevention, see the
limitations section of README.md.

Note: the flat per-decision record used in result files
(`action`, `trust`, `H`, `D`, `phase`, …) is the *benchmark JSONL schema*
documented in [06-reproducibility.md](06-reproducibility.md), not this envelope.

### Where envelopes are stored

An envelope that is not persisted is not an audit trail. The REST gateway
writes every envelope to a control-plane store selected at startup:

| Backend | Selected by | Durable | Scope |
|---|---|---|---|
| `postgres` | `REMORA_CONTROL_PLANE_DSN=postgresql://…` | yes | multi-node |
| `sqlite` | `REMORA_CONTROL_PLANE_DSN=sqlite:///path.db` or `REMORA_CONTROL_PLANE_DB=path.db` | yes | single node |
| `in_memory` | neither variable set (development only) | **no** | process lifetime |

`InMemoryControlPlaneStore` exists for tests and local iteration. It loses
every envelope when the process exits, so it is refused in
`REMORA_ENV=production`, it logs a warning at startup, and both
`GET /v1/metrics` and `GET /v1/policy/version` report
`control_plane_durable: false`. Treat decisions from a non-durable run as
unrecorded.

Retrieval and proof:

- `GET /v1/envelope/{request_id}` returns the stored envelope.
- `GET /v1/audit/{request_id}` returns its audit record.
- `GET /v1/audit/chain/verify` walks the tenant's whole persisted trail and
  confirms each record links to its predecessor, so a removed or spliced
  decision is detectable. It reports `records_checked` alongside
  `chain_valid`: an empty trail verifies trivially and proves nothing.

Off-platform verification (an auditor recomputing hashes on their own
machine, trusting no endpoint) uses `scripts/verify_envelope_chain.py`.

### Execution-layer state is a separate durability decision

The envelope store above covers `/v1/assess`. The execution layer
(`/v1/execution/*`) keeps its own state: the per-tenant audit chain, the
review queue, and the PEP's consumed-jti ledger. These are durable only when
`REMORA_PG_DSN` (multi-node) or `REMORA_CHAIN_DB` (single-node SQLite) is set.

With neither, the consequence is not only a lost audit trail. The consumed-jti
ledger is what makes an execution grant single-use, so a grant already
consumed by one worker is accepted again by a second worker, or by the same
worker after a restart. Production mode fails closed rather than start in
that configuration; development mode allows it, logs a warning, and reports
`execution_state_durable: false` on `/v1/metrics` and `/v1/policy/version`.

Known remaining limit: `NonceLedger` in `remora/enforcement/lease.py`, which
backs `GovernedToolDispatcher` leases, has no durable adapter at all. A lease
nonce is single-use per process, not globally. Deployments running more than
one dispatcher process must not rely on it as a global guarantee (REM-025).

---

## PolicyObservation, input contract

`PolicyObservation` (`remora/policy/observation.py`) is a frozen dataclass
with 76 fields; on the research `/v1/assess` path **all fields except
`question` are optional and caller-populated**, REMORA is stateless and
performs no detection itself (the engine treats `None` as "unknown, not
safe"); see the assess-time authorities subsection below for the two
server-side cuts into that freedom. On `/v1/execution/*` it does NOT hold:
trust-bearing fields are derived server-side and client values can only
lower trust, never raise it; see the Trust boundary section below.
Selected fields by group:

| Group | Fields (selection) |
|---|---|
| Identity | `question` (required), `domain`, `session_id` |
| Consensus observables | `trust_score`, `temperature`, `final_H`, `final_D`, `final_V`, `phase`, `valid_oracle_count`, `oracle_failures` |
| Evidence | `evidence_action`, `evidence_confidence`, `evidence_contradictions`, `evidence_supporters`, `evidence_signal_source`, `require_rag` |
| Risk & action | `risk_tier`, `action_type`, `target_environment`, `rollback_available`, `state_transition_uncertain`, `proposed_tool_name` |
| Intent authority | `intent_authority_present` — did this call arrive under an intent the deployment resolved from a source it controls (a signed work order, a ticket of record)? Resolved server-side from `intent_ref`; the agent may name which authority it acts under and can never assert that it exists. `True` only when resolution succeeded; `False` when an `intent_ref` was presented and did not resolve; `None` when none was presented. Required for `GROUNDED_READ_ACCEPT` |
| Resolution | `missing_required_arguments`, `argument_resolver_tools`, `unvalidated_required_arguments` — required parameters absent from the call and the authoritative tools that could supply them. Non-empty with resolvers available yields VERIFY carrying a `ResolutionPlan`; without them, ABSTAIN |
| Security flags | `adversarial_detected`, `schema_valid`, `tool_forbidden`, `argument_tainted`, `coercion_detected`, `blackmail_pattern_detected`, `arguments_satisfiable`, `argument_values_supported`, `argument_values_grounded` + `ungrounded_arguments` (a derived value can ground via a verified `DerivationReceipt`: verbatim source span + whitelisted deterministic transform, re-executed server-side — `remora/toolcall/routing/derivation.py`), deployment-owned `argument_scope_valid` + `scope_violating_arguments`, strict-profile `intent_provenance_required` + `intent_provenance_resolved`, `tool_matches_goal`, `untrusted_controlled_arguments` |
| Verification | `counterfactual_passed`, `distribution_shift_detected`, `classification_confidence`, `classification_alternatives`, `model_misspecification_risk` |
| Session & fleet | `session_action_count`, `session_cumulative_risk`, `similar_action_seen_count`, `policy_generalization_risk`, `fleet_level_effect` |
| Binding | `tool_call_hash`, SHA-256 of the full canonical tool call (name, exact args, tenant, target); recompute before execution and refuse on mismatch |

Construct from a dict with `PolicyObservation.from_json_record(record)`
(unknown keys are ignored, misspelled safety flags therefore silently default
to their permissive value; validate producer-side).

---

### Assess-time authorities on the research path (2026-08-05)

Two server-side authorities cut into `/v1/assess`'s caller freedom:

- **Semantic authority on request.** An assess request may carry an
  optional `tool_call` block (`tool_name`, `arguments`, `intent_ref`,
  `untrusted_context`; unknown keys rejected with 422, so semantic
  verdicts cannot be smuggled in). With `REMORA_SEMANTIC_BUNDLE_MODULE`
  configured, the same authoritative context builder as
  `/v1/execution/assess` runs; the computed `tool_contract_bundle_hash`
  and `intent_authority_hash` are recorded into the envelope's audit
  block, and `tool_args_hash` upgrades to the canonical execution/lease
  preimage. The semantic verdicts are RECORDED on this path; the gate
  decision still comes from the question-based engine pipeline, and
  discrimination through the wired path is unmeasured (SAP v4 pending).
- **Raise-only metadata on the library path.** `assess_tool_call`
  (`remora/assess.py`) clamps a declared `risk_tier` that undercuts the
  deterministic name-heuristic floor UP to the floor, and floors a
  declared read on a write-verb tool to the inferred write family. Every
  clamp is recorded in `ToolCallAssessment.floored`, never silent. The
  floor clamps explicit declarations only; unset fields stay unset and
  the engine fail-closes on them.

---

## RemoraDecisionEngine

`remora/policy/decision_engine.py`:

```python
engine = RemoraDecisionEngine(
    temperature_threshold=None,        # ACCEPT path inert unless set
    conformal_trust_threshold=None,    # ACCEPT path inert unless set
    conformal_phase_thresholds=None,   # Mondrian per-phase ACCEPT/ABSTAIN
)
report = engine.decide(obs: PolicyObservation)   # -> DecisionReport
trace  = engine.explain(obs: PolicyObservation)  # -> PolicyTrace
```

`decide()` returns a **`DecisionReport`** (`remora/policy/report.py`) with
fields: `action`, `reasons`, `risk_estimate`, `confidence`, `coverage_policy`,
`evidence_required`, `human_review_required`, `audit_root`, `explanation`,
`raw_observation`, `source_of_decision`, `policy_version`,
`in_sample_calibration_warning`, `fallback_used`, `credal`, `resolution_plan`.

Hard-block invariants run with absolute precedence before any probabilistic
routing; the machine-checkable invariant list is `CORE_INVARIANTS` in
`remora/policy/invariants.py`. `explain()` returns a `PolicyTrace` whose rule
ladder mirrors `decide()` rule-for-rule, parity is enforced by
`tests/test_explain_decide_parity.py`. The default (bare) constructor leaves
all calibrated ACCEPT paths inert; ACCEPTs then come only from the
evidence-supported and ordered-high-trust paths.

---

## Oracle ABC

All oracles implement the same interface (`remora/core.py`):

```python
class Oracle(ABC):
    @property
    def name(self) -> str: ...
    def _call(self, prompt: str) -> tuple[str, float, float]: ...  # subclass hook
    def ask(self, prompt: str) -> OracleResponse:                  # public entry

@dataclass
class OracleResponse:
    provider: str          # provider identifier
    raw_text: str          # raw model response text
    extracted: dict        # first JSON object extracted from the response
    cost_usd: float        # accumulated call cost
    latency_ms: float      # wall-clock call time
    error: str | None      # populated on failure (failed oracles are filtered)
```

Oracles are pluggable. The recommended three-family swarm is built by
`build_recommended_swarm()` in `remora/oracles/factory.py`.

---

## Adapters

Adapters wrap REMORA into agent frameworks (`remora/adapters/action_gate.py`).
All gateways return an **`ActionGateResult`**:

```python
@dataclass(frozen=True)
class ActionGateResult:
    envelope: DecisionEnvelope
    should_execute: bool   # True only when the gate outcome is ACCEPT
```

Adapters are constructed with `gateway=` (not `engine=`); the concrete
in-process gateway is `LocalGateway` (`remora/adapters/gateway.py`, exposing
`assess_sync()`), which wraps an `EngineLike` such as `Remora`:

```python
gateway = LocalGateway(engine)                      # wraps the in-process engine
adapter = LangGraphActionAdapter(gateway=gateway)   # or OpenAIToolCallingAdapter,
                                                    # CrewAIActionAdapter, AutoGenActionAdapter
result = adapter.intercept(
    action_name=..., action_args=..., proposed_by=..., domain=...,
    risk_tier=..., action_type=..., target_environment=..., context=...,
)  # -> ActionGateResult

oai = OpenAIToolCallingAdapter(gateway=gateway)
wrapped = oai.intercept_tool_call(...)  # OpenAI-shaped convenience wrapper
```

`AsyncLocalGateway.execute_gated(...)` raises `PermissionError` for non-ACCEPT
outcomes: this adapter layer is the actual runtime blocking path.

---

## Enforcement (PDP/PEP library)

`remora/enforcement/` provides the signed-token decision boundary (REM-013):

```python
token = PolicyDecisionToken.issue(action, observation_hash, request_id,
                                  issued_at, expires_at=None)  # HMAC-SHA256
gate = EnforcementGate(strict=True)
gate.check(token, expected_observation_hash=...)   # verify only
gate.enforce(token, action_fn)                      # raises PermissionError unless ACCEPT
```

Every token carries a **mandatory** signed `expires_at` (a default TTL is
applied at issue when unset; `verify()` rejects any token without expiry as
`missing_expiry`), a unique `jti` for one-time consumption, and an optional
signed `audience`. `EnforcementGate.check(token, obs_hash, consume=True)`
verifies the signature, expiry, max age and audience, and atomically consumes
the `jti` so a token can authorise exactly one execution.

**Integration status (SHADOW_ONLY):** the PDP→PEP token flow is wired into the
live app via the execution API, `POST /v1/execution/assess` issues a
short-lived signed token on ACCEPT, and `POST /v1/execution/execute` re-gates
the fresh observation and consumes a one-time grant through the gate. The
`jti`-consumption store persists to a `pep_consumed` table when
`REMORA_PG_DSN` (Postgres) or `REMORA_CHAIN_DB` (SQLite) is configured
(`remora/enforcement/gate.py`), in-process set by default. A second gate over
the same durable ledger refuses the replay
(`tests/test_token_hardening.py::test_durable_ledger_refuses_the_replay_from_a_second_gate`);
no test spawns a new interpreter, so behaviour across an actual process restart
is inferred from the shared ledger rather than directly observed. See
`servers/execution_api.py` and
`docs/assurance/capability_register_v1.yaml` CAP-003 (WIRED_API_PATH).

### Execution state machine, `servers/execution_api.py` (`/v1/execution/*`)

Wire models for these endpoints live in `servers/execution_contracts.py`
(re-exported by `execution_api`); the transactional review-state writes below
run through `remora/persistence/execution_state.py`, and ToolSpec
resolution/binding through `remora/execution/authorization.py` (issue #241).

The end-to-end path (REM-035): `POST /assess` (issues an ACCEPT token or
enqueues a review item), `POST /approve` (records the authenticated principal;
mandatory bounded TTL; profile-specific approval role enforced), `POST
/execute` (re-gates the fresh observation, binds the exact payload, consumes a
one-time grant, then dispatches the tool through the app-lifecycle
`GovernedToolDispatcher`), `GET /audit/verify` (recomputes the per-tenant
chain and reports `records_checked`; an `empty` chain is flagged because it is
trivially valid). RBAC: `assess`/`execute` capabilities gate assess/execute;
`review` gates approve; `read` gates audit.

**Authentication modes:** token-table mode (`REMORA_API_TOKENS`) maps each
bearer token to a fixed tenant and role; callers cannot forge either.
Single-token mode (`REMORA_API_BEARER_TOKEN`) reads tenant/role from
caller-asserted headers and therefore has **no role separation**; in
`REMORA_ENV=production` the role header is ignored and pinned to
`operator`, so approval-role gating cannot be satisfied in this mode (see
SECURITY.md). Dev mode (no credentials + `REMORA_ENV=development`) runs
without auth; production without credentials is a startup error.

**Idempotency:** `idempotency_key` deduplicates `POST /assess` per tenant.
The cache is a bounded in-process LRU (10 000 entries); an evicted key
simply re-runs assess, which has no side effects beyond a fresh audit
record.

**Trust boundary (issue #34):** the execution request is a PROPOSAL only;
`tool_name`, exact `arguments`, requested `target_environment` (+
`idempotency_key`, and optionally `intent_ref` / `untrusted_context`, both
covered below). Every authoritative safety signal (risk tier, domain,
action type, trust, phase, evidence status, schema validity, rollback
capability) is derived server-side from the tool registry; the legacy
client fields (`trust_score`, `phase`, `evidence_action`,
`evidence_confidence`, `risk_tier`, …) are ignored as unknown extras. The
only inbound safety influence is a DOWNGRADE: `schema_valid: false` or
`rollback_available: false` lowers trust ("world got riskier" feeds the
freshness re-gate); `true` never raises anything, including on tools the
registry does not pin. Since the policy-only kernel has no oracle or
evidence pipeline, trust/phase/evidence are unknown at assess time and the
engine fails toward VERIFY/ABSTAIN; no probabilistic ACCEPT can fire from
this path (server-side signal sources are #35/#39 scope).

**Semantic bundle (SHELF-020):** with `REMORA_SEMANTIC_BUNDLE_MODULE`
configured (module contract: `build_semantic_bundle()` and optionally
`resolve_intent(intent_ref)`, `resolve_intent_detailed(intent_ref)` and
`validate_argument_scope(tool_name, arguments, tenant)`, see
`remora/toolcall/semantic_bundle.py`;
shipped research profile: `servers/semantic_bundle_research.py`), the
assess/execute observation is built by `build_full_observation` (the same
authoritative context builder the routing benchmarks lock) over the
deployment-declared tool signatures, contracts, validator bindings and state
index. The request may carry an opaque `intent_ref`, resolved server-side
against a deployment-controlled source (`docs/research/task_intent_authority_v1.md`);
the MCP gateway accepts either `owner/repo#123` (GitHub issue authority) or
`task:<subject>` (protected graph-intent authority), depending on the enabled
tool set. An unresolved reference stays publicly generic and fail-closed; the
internal audit distinguishes `intent_not_authorized` from
`intent_resolution_failed` for operations without exposing a resolution
oracle to the caller.
the intent itself can never ride in the request, and request extras asserting
`tool_matches_goal` or an inline intent are ignored. `untrusted_context` is
downgrade-only: declaring it marks the call's arguments tainted, omitting it
raises nothing. The response's `semantic` block reports the computed
`tool_contract_bundle_hash`, `state_hash`, `intent_authority_hash`, the
tri-state `tool_matches_goal` / `expected_effect_matches`, per-argument
grounding, and the deployment-owned argument-scope verdict. A confirmed scope
violation hard-ABSTAINS before review and is re-evaluated on approved-item
redemption; human approval cannot widen a tenant binding. The same hashes are
appended to the tenant audit chain at assess time and bound into the
`ExecutionLease` at execute time. Without a bundle module the legacy
registry-only path runs, recorded as empty hashes; absent semantics stay
`None`, never defaulted. Discrimination through this path is unmeasured
(SAP v4 pending); no accuracy number may be cited for it.

**Tool dispatch (issue #13):** tool callables are registered exclusively via
trusted deployment configuration; the module named by
`REMORA_TOOL_REGISTRY_MODULE` must expose
`register_tools(register: Callable[[str, Callable], None])` and is imported
once per process; request payloads can never add or replace callables, so
downstream credentials stay app-side. The `/execute` response carries a
`tool_execution` block (`executed`, and `result` or `refusal_reason`) that
reports what actually happened; with no module configured the registry is
empty and every dispatch reports `executed: false` /
`refusal_reason: unknown_tool`; the research default stays side-effect free
but says so explicitly. Dispatch happens only after the PEP consumed the
grant, under an `ExecutionLease` bound to tenant, principal, tool, exact
arguments, target environment and the current policy-bundle hash; a tool that
raises burns the lease nonce and surfaces as
`refusal_reason: tool_failed_nonce_burned` in both response and audit record
(`tool_executed` / `tool_refusal_reason`).

**Execution state machine (external review 2026-07-27):** the re-gate only
ever AUTHORIZES; `ReviewQueue.execute()` sets the item to `authorized`, and
`executed` is recorded exclusively by `record_execution_outcome()` after the
dispatcher confirms the side effect; refusals and raising tools terminate as
`dispatch_refused` / `dispatch_failed`, so the persisted state never claims
an execution that did not happen. The audit chain carries a durable
`execution_authorized` INTENT entry appended before the external side effect
and an `execution_result` entry after it (linked via `intent_sequence_no`);
a crash mid-dispatch leaves an authorization with no matching result, never
a side effect with no record. Item→tenant bindings and approvals are written
inside the same durable transaction as the queue state (SQLite/Postgres),
restart-proven by test.

### Governance modules (library)

- `remora/governance/tenant_chain.py`, `TenantAuditChain` (in-process) and the
  durable `SQLiteTenantChain` / `PostgresTenantChain` adapters (REM-034):
  `entry_hash` covers previous-hash, tenant, sequence and timestamp;
  `append()` is atomic; `verify()` recomputes and checks the HMAC signature.
- `remora/governance/review_queue.py`, `ReviewQueue`: enqueue (VERIFY/ESCALATE
  only), TTL→ABSTAIN, mandatory-expiry approvals, execution-time re-gate
  (only ACCEPT/VERIFY execute), all transitions hash-chained.
- `remora/governance/degradation.py`, `DegradationRecorder` (G0–G4 ladder with
  tamper-evident transitions) and `g4_refuses()`.
- `remora/governance/a2a_envelope.py`, `A2AGovernanceEnvelope`, `RegisteredKey`
  (principal-bound per-link keys), `sign_delegation_link()`.

Wiring status per module is authoritative in
`docs/assurance/capability_register_v1.yaml`.

---

## Safety, adversarial detection

`remora/safety/adversarial.py`:

```python
from remora.safety.adversarial import detect_adversarial

flagged: bool = detect_adversarial(text)
```

Returns a plain `bool` (pattern-based heuristic). It covers the action
description text only; it does not cover untrusted payloads inside tool
results: an active gap documented in `NEGATIVE_RESULTS.md`.

---

## MCP tools

The MCP server (`servers/mcp_remora.py`) exposes 14 tools over JSON-RPC stdio:

| Tool | Purpose |
|---|---|
| `remora_analyze_document` | Multi-oracle analysis of a document |
| `remora_verify_claim` | Evidence-backed verification of a claim |
| `remora_legal_analysis` | Legal-domain analysis pipeline |
| `remora_verify_legal_citations` | Validate legal citations in a text |
| `remora_norwegian_law_search` | Search Norwegian law sources (Cloudflare worker) |
| `remora_rag_search` | RAG retrieval search |
| `remora_rag_query` | RAG retrieval + synthesis query |
| `remora_repo_search` | Search indexed repository content |
| `remora_codegraph_scope` | Code-graph scope lookup |
| `remora_status` | Server/pipeline status |
| `remora_session_status` | Status for a governed agent session |
| `agent_start_session` | Open a governed agent session |
| `agent_execute_tool` | Gate + execute a tool call inside a session |
| `agent_audit_log` | Retrieve the session audit log |

Setup for Claude Code:
```bash
claude mcp add remora python /path/to/REMORA-research/servers/mcp_remora.py
```

Cloudflare Workers AI is optional; the server falls back to local Python
oracle paths without it.

---

## Cyber evidence provider

`remora/evidence/cyber.py`:

```python
from remora.evidence import CyberEvidenceProvider

provider = CyberEvidenceProvider()
result = provider.triage(
    title="...", description="...", severity="critical",
    cve_ids=["CVE-2021-44228"], exposed=True, production=True,
)
# result.verdict.value                  → "ESCALATE"
# result.exploit_classification.value   → "KNOWN_EXPLOITED"
# result.matches[0].record.source       → source label
```

Also implements the REMORA evidence provider interface for use in the oracle
pipeline. See `docs/integrations/cyber_evidence_layer.md`.
