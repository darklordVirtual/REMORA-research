# What are the public interfaces?

This document maps the canonical `DecisionEnvelope` contract, the
`PolicyObservation` input, the decision engine, the Oracle ABC, adapters, the
enforcement (PDP/PEP) library, and the MCP tool surface. **Implementation
source is authoritative**; every signature below is verified against source by
`tests/test_api_reference_doc.py`, if this document drifts from the code, CI
fails.

## The HTTP surface, concretely

The machine-readable contract is [`schemas/openapi.json`](../schemas/openapi.json)
(OpenAPI 3.1). CI fails on drift between it and the routes, so it is the
authority for request and response shapes, and for how many there are; this
document explains them.

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
curl -s localhost:8000/v1/ready
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

Lease nonces reach the same durable state. `DurableNonceStore`
(`remora/enforcement/nonce_store.py`) backs `GovernedToolDispatcher` over
Postgres, SQLite or D1, built from the same three environment variables as the
consumed-jti ledger so the two cannot drift apart the way they once did. With
none of them set, the in-process `NonceLedger` remains and a lease is
single-use per process rather than globally. That is the library and research
configuration. A deployment running more than one dispatcher must configure a
backend.

When the PostgreSQL store stops answering, a request that needs it answers
503 `durable_state_unavailable` with a `correlation_id`. The driver raised
`OperationalError` (psycopg v3 or psycopg2), and nothing was decided or
executed. The request can be retried once the store is back. Other unhandled
errors stay 500, and neither body carries the driver's message.
`GET /v1/health` is a liveness probe and does not read the store.
`GET /v1/ready` is the readiness probe. It connects to `REMORA_PG_DSN` (or
opens `REMORA_CHAIN_DB` read-only) with a two-second bound and answers 200
`ready`, or 503 `not_ready` with `checks.durable_state: unavailable` while the
store does not answer. It reports `not_configured` without a durable store and
`not_checked` for the Worker state endpoint alone, which it does not reach. It
takes no token, so one answer is reused for a second instead of opening a
connection per request.

---

## PolicyObservation, input contract

`PolicyObservation` (`remora/policy/observation.py`) is a frozen dataclass
with 82 fields; on the research `/v1/assess` path **all fields except
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
| Flow control | `flow_status`, `flow_confidentiality_violation`, `flow_integrity_violation`, `flow_epoch`, `flow_digest`. Set only by `/v1/execution/*` with `REMORA_FLOW_CONTROL=1`, from the flow context and the signed ToolSpec; no request field sets them. Rungs F1 to F6 read the first three (IFC-05b) |
| Execution identity | `execution_context_hash`, optional digest of deployment-owned context captured before assessment and bound through authorization, dispatch and effect evidence; see [execution quickstart](deployment/execution-quickstart.md#optional-authoritative-execution-context) |

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
- Registry labels only, on the library path (PRF-040, 2026-10-18).
  `assess_tool_call` and `what_if_tool_call` take `registry=`, a mapping
  from tool name to `risk_tier`/`action_type`. Labels the caller passes or
  name inference fills are capped: an ACCEPT becomes VERIFY with the reason
  `caller_labels_untrusted`. A tool a supplied registry does not name is
  assessed as critical/unknown. `ToolCallAssessment.label_source` records
  the source, and `should_execute` is True only for ACCEPT with
  `label_source == "registry"`.
- Registry labels only, on `/v1/assess`, `/v1/rerun` and the adapters
  (RMR-AUD-011, 2026-10-18).
  - `/v1/assess` with a `tool_call` takes `risk_tier` and `action_type`
    from the server's registry, the same `resolve_tool_metadata` that
    `/v1/execution/*` uses. A request `risk_tier` may only raise the
    registered tier. An `action_type` that differs from the registry's caps
    ACCEPT (`registry_label_conflict`). The environment is the riskier of
    the declared and requested one. A tool nobody classified is
    critical/unknown, and the request's labels are ignored.
  - Without a `tool_call` there is no tool to look up, so the request's
    labels are the caller's. An engine ACCEPT becomes VERIFY with
    `caller_labels_untrusted`, in `policy_decision` and in the stored
    envelope.
  - The response carries `label_source` (`registry`, `unregistered`,
    `caller` or `none`) and `label_cap`. The audit record keeps
    `label_source`.
  - `/v1/rerun` keeps an ACCEPT only when the original assessment's
    labels came from the registry. A record without `label_source` is
    treated as the caller's.
  - The action-gate adapters in `remora/adapters/` take `registry=` in the
    same shape as `assess_tool_call`. Without one, an ACCEPT becomes VERIFY
    and `ActionGateResult.label_cap` says why. `HttpGateway` sends the
    `tool_call`, and the adapter keeps the server's `label_source` and
    verdict.

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
    label_source: str = "caller"   # "registry", "unregistered" or "caller"
    label_cap: str | None = None   # why an ACCEPT was lowered to VERIFY
```

Adapters are constructed with `gateway=` (not `engine=`); the concrete
in-process gateway is `LocalGateway` (`remora/adapters/gateway.py`, exposing
`assess_sync()`), which wraps an `EngineLike` such as `Remora`. Pass the
deployment's `registry=` too: without it, the `risk_tier`/`action_type`
given to `intercept` are the caller's and cannot produce
`should_execute=True` (RMR-AUD-011):

```python
gateway = LocalGateway(engine)                      # wraps the in-process engine
registry = {"search_docs": {"risk_tier": "low", "action_type": "read"}}
adapter = LangGraphActionAdapter(gateway=gateway,   # or OpenAIToolCallingAdapter,
                                 registry=registry) # CrewAIActionAdapter, AutoGenActionAdapter
result = adapter.intercept(
    action_name=..., action_args=..., proposed_by=..., domain=...,
    risk_tier=..., action_type=..., target_environment=..., context=...,
)  # -> ActionGateResult

oai = OpenAIToolCallingAdapter(gateway=gateway)
wrapped = oai.intercept_tool_call(...)  # OpenAI-shaped convenience wrapper
```

The adapters do not raise on a non-ACCEPT outcome. `ActionGateResult.should_execute`
is False, and the caller must not run the action; the `AsyncLocalGateway`
docstring shows the pattern. The adapters never hold the tool, so they block
only as far as the caller obeys them. The enforcing path is `/v1/execution/*`
with the `GovernedToolDispatcher`.

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
`GovernedToolDispatcher`; the executing principal must be the proposer, or the
delegate the proposal named, and the task must be the proposal's, or the call
is refused with 409 `context_mismatch` before the approval is touched; a risk
tier that differs from the one the approval was reviewed at voids the approval
as `approval_invalidated`, so it is re-approved under the role the current tier
requires, and so does an approval requirement that changed since the approval
or was never recorded with it), `GET /audit/verify` (recomputes the per-tenant
chain and reports `records_checked`; an `empty` chain is flagged because it is
trivially valid). Its `hash_chain_status` (`INTACT` or `BROKEN`) and
`signature_status` are separate: `CHECKED` when this process holds
`REMORA_AUDIT_SIGNING_KEY`, `NOT_CHECKED_NO_KEY` when the records are signed but
it does not, and `UNSIGNED` when no record carries a signature. `valid` covers
only the checks that ran (RMR-CR-007). The control-plane
`GET /v1/audit/chain/verify` follows record links only and says so with
`verification_scope: linkage_only` and `signature_status: NOT_CHECKED`. RBAC: `assess`/`execute` capabilities gate assess/execute;
`review` gates approve; `read` gates audit. `review` also gates `POST /revoke-principal`, which withdraws a principal's authority after the fact. An approval that principal granted is invalidated at the execution re-gate, not rewritten. The chain therefore shows both the approval and the revocation. With `REMORA_WS1_ADMISSION=atomic`, `review` also gates `POST /revoke-authority`. It revokes or reinstates a WS1 evidence source (`source:<id>`) by advancing its authority epoch under the admission lock, together with an `authority_revoked` or `authority_reinstated` audit event. Evidence read before the change no longer admits. Without the mode the route answers 409. In that mode an admitted call is checked again just before it is sent. A change committed after the admission refuses the send: `tool_execution.refusal_reason` is `permit_refused` and `permit_refusal` names the cause. `tool_execution.permit` records the check, and `at_effect: NOT_ESTABLISHED` marks that a revocation during the send is not seen.

`review` also gates `POST /v1/execution/stop` and `POST /v1/execution/resume`, the operator's stop switch (SDD unified capability execution v1.1, P0 item 7; gate G10). A stop writes one durable flag for the tenant: the authority-epoch subject `execution:stop`, in the store the lease nonce ledger uses (`REMORA_PG_DSN` or `REMORA_CHAIN_DB`). An `execution_stopped` event commits in the same transaction. While it is set the authority mints nothing (`execution_stopped`). Every governed dispatcher, in this process or in a separate execution domain reading the same store, refuses before anything is spent: no nonce, no limit reservation, no recorder intent. A lease refused this way runs after the resume if it has not expired. `/v1/execution/execute` and `/v1/execution/execute-accepted` read the flag before they touch the approval or the token and answer 409 `execution_stopped` (503 `execution_stop_unverifiable`), so a stopped approval or ACCEPT token also runs after the resume. A stop set between that read and the dispatch is refused by the dispatcher, with the approval spent. A call already past its nonce finishes, because effects cannot be undone; nothing executed is touched and no evidence is deleted. A store that cannot answer refuses as `execution_stop_unverifiable`. `GET /v1/execution/stop` (`read`) returns the flag and the epoch of the last change. A deployment on `REMORA_STATE_ENDPOINT` alone has no epoch store and therefore no stop; the routes answer 409 and the dispatcher binds no check.

**Rejection, effects and the proposal trail.** `POST /reject` (`review`)
refuses a pending review item terminally and requires a `reason`. The
recorded reviewer is the authenticated principal, and a rejected item can
never be approved or executed afterwards. `POST /proposals/{proposal_id}/effect`
(`execute`) appends one effect verification exactly as reported, mismatches
included. It requires `execution_id`, `tool_id`, `status` (one of the five
published statuses), `reason_code` and `verifier_identity`, and carries
`execution_context_hash` for a context-bound dispatch. Another tenant's
proposal is a 404. `POST /proposals/{proposal_id}/effect-receipt` records a
verdict REMORA computes from a receipt signed by a registered verifier key
(CAPR-07/08). The contract comes from the signed ToolSpec v5 `postcondition`
block and the approved arguments. A status the receipt claims is kept beside
the computed one, never in its place. It is a 503 without registered verifier
keys. `GET /proposals/{proposal_id}` (`read`) returns the proposal's current
state. `GET /proposals/{proposal_id}/invocation-evidence` (`read`) exports one
executed direct ACCEPT, signed under `REMORA/EVIDENCE/v1`. It carries the grant
and lease bytes their signatures cover, so a verifier holding only public keys
can check it offline. It is a 503 without an evidence signing key. `GET /proposals/{proposal_id}/lifecycle` (`read`) returns
the ordered chain trail plus the dispatch verdict, and
`GET /proposals/{proposal_id}/envelope` (`read`) derives the proposal-to-effect
envelope from that trail on read; it is never stored. `POST /effects` and
`POST /effects/close` (`execute`) are the effect domain of the three-domain
mediation split (NTA-2 phase 3). The domain verifies the lease and that it was
dispatched, derives authority from its own ToolSpec ceiling, and answers
`REFUSED` or `EXECUTED` without raising. A lease for another tenant is a 409. A lease
judged under flow control carries `flow_recipients_digest`; the request then carries
`flow_recipients`, the set the executor computed, and a missing or different set is
`flow_recipients_mismatch` (IFC-12).

**Execution context (opt-in).** `REMORA_REQUIRE_EXECUTION_CONTEXT=1` with
`REMORA_EXECUTION_CONTEXT_MODULE` naming a deployment provider binds a
deployment-owned execution context through assessment, review, grant, lease,
dispatch and effect recording; `/dispatch-leased` then takes the historical
context as `execution_context`. The authority of the deployment sources stays
`NOT_ESTABLISHED` (`execution_context_authoritative_binding`). Setup is in the
[execution quickstart](deployment/execution-quickstart.md#optional-authoritative-execution-context).

**Delegated execution (opt-in):** by default only the proposer executes what
it proposed, on the review path and with an ACCEPT token. A proposal may name
`delegated_executor`, a service identity that executes on the proposer's
behalf. `POST /assess` admits it only when the risk-profile config declares it
for this agent in this tenant, under
`tenant_access.<tenant>.delegated_executors` as
`{service_identity: [agent, ...]}`; `access_defaults` does not apply. Otherwise
the assessment is refused with 409 and nothing is assessed:
`delegate_not_declared`, `delegate_cross_tenant` when the identity is declared
only under another tenant, or `delegate_is_proposer`. The shipped config
declares none. An admitted delegate is written to the `assessed` record and
bound into the ACCEPT token's authorization context. `GET /proposals/{id}` and
`POST /approve` return it and the `approved` event records it, so the reviewer
approves it with the call. The delegate re-presents the same
`delegated_executor` and is compared as the proposer it acts for. A delegate
added, swapped or stripped after assessment is `context_mismatch`, and so is
any other principal. The delegate cannot approve the item it will execute (403
`approver_is_delegated_executor`). `execution_authorized` records the delegate
as `actor` with `acting_for` naming the proposer, and the execution lease is
minted with the delegate as `actor_identity`. The
delegation is checked at assess only: withdrawing the declaration later does
not void an item already assessed, while revoking the approver still does.

**Proposal binding:** `POST /execute` re-presents the call, and the fields
outside the payload hash must be the ones assessed. Those are `schema_valid`,
`rollback_available`, `untrusted_context`, `intent_ref`, `derivations`, the
task, `plan`, `task_type` and `delegated_executor`. The `assessed` record
carries `proposal_envelope_hash` over them (the idempotency key excepted). A
different proposal is refused with 409 `binding_refused` before the approval
is touched (RMR-AUD-001). An item assessed before this binding has no hash and
is refused the same way, so it must be proposed again. Arguments, tool and
target stay bound by the queue's payload hash, as before. A riskier world
still comes from the server side: ToolSpec, state, revocation and risk
metadata re-gate as before. The intent authority the reviewer approved is
also bound. An `intent_authority_hash` that differs from the `assessed`
record's is `context_mismatch`, as at ACCEPT-token redemption. That holds when
the reference changed and when the authority behind the same reference did
(RMR-AUD-006).

**Approved escalations:** an item records the decision reasons it was
enqueued with, and its approval records them as `approved_reasons`. An
approved ESCALATE survives the execution re-gate when the fresh decision is
ACCEPT, VERIFY or ESCALATE and every fresh reason is among the approved ones.
Re-deciding the observation the reviewer saw therefore no longer voids it
(RMR-AUD-002). A new reason, or a fresh ABSTAIN, voids it as
`approval_invalidated`. An approved VERIFY keeps the earlier rule.

**Approval policy binding:** an approval records the approver's
authenticated role and the role the item's tier required (`required_role`, null
when the profile names none). It also records `approval_policy_hash`, a hash of
that requirement and the tenant's `reviewer_roles`. All three are on the
approval and on the `approved` event. `POST /execute` and the async worker
recompute the hash for the fresh observation. A typical cause of a difference
is an edited `schemas/risk-profiles.yaml` and a restart with the item in a
durable queue. The approval is then void as `approval_invalidated`
(`approval_policy_changed`), and the item returns for approval under the
current rule. An approval stored without the record, such as one persisted before this
binding, is voided the same way (`approval_policy_unbound`).

**Task identity and loop safety (Q7.2):** a tool call may carry `context_id`
and `task_id`, in A2A's vocabulary, both or neither (one alone is a 422).
When present, the task is bound into the ACCEPT token's authorization
context and into the execution lease. Redeeming the token under another
task, or with the task stripped, is refused as `context_mismatch` before the
grant is spent. `POST /dispatch-leased` refuses a lease from another task as
`task_mismatch`. Every assessment that names a task is recorded in the
context's loop safety state (`remora/governance/loop_safety.py`). A context
that has reached a limit (by default 3 denials, 1 authority probe, or 2 tool
switches straight after a denial) cannot ACCEPT: the decision becomes
ESCALATE with reason `loop_safety_escalate`. An unreadable loop store is a
503 and nothing is assessed. `GET /loop-safety/{context_id}` reads a
context's state, and `POST /loop-safety/reset` starts it again. The reset
takes a `policy_ref` and a `reason`, both mandatory, is recorded on the
tenant chain, and keeps the earlier events. Both routes need `review`.
`REMORA_REQUIRE_TASK_IDENTITY=1` refuses every call that names no task with
409 `task_identity_required` before anything is decided or consumed. It is
off by default because callers must first send the fields. The loop limits
are defaults that no study has calibrated.

**Meet composition (COMP-01):** every decision is the least executable of
its components (`ABSTAIN < ESCALATE < VERIFY < ACCEPT`). ABSTAIN is lowest
because it has no approval route; ESCALATE has one. The components are the
cascade, every hard guard that fires, every conditional gate that fires, the
rest of the policy as it would decide without them, and any external cap. A
stricter component that fires after the first match still binds, and its
reason is appended. Library callers can pass `caps` to
`RemoraDecisionEngine.decide` and `explain`, with reason `monitor_cap` for a
learned monitor, `protocol_cap` for a control protocol, or
`precondition_cap` for a WS1 execution precondition that is not PROVED
(`remora/verification/`, library only). A cap can only lower a decision
([ADR](architecture/ADR-flow-meet-composition.md)).

**Flow contexts (RF-02, opt-in):** with `REMORA_FLOW_CONTROL=1`,
`POST /v1/contexts` mints a flow context for derived information-flow
control ([roadmap](13-research-frontier-roadmap.md)). The body
names the `user_principal` (`user://<tenant>/...`), the `model_principal`,
an optional `q_principal` and an optional `parent_context_id`. The response
is the server-minted `context_id` and `label_epoch`. Every processor must be
authorized by the processing policy in `REMORA_FLOW_PROCESSING_POLICY`;
otherwise the mint is a 403 `processing_not_authorized`. The route needs
`assess`. With the switch off it is a 409 `flow_control_disabled`.

With the switch on, `/v1/execution/assess` and the re-gates at execute and
dispatch run the flow check for every call (IFC-05b). The call must carry a
`context_id` minted here, by the same principal; otherwise it ABSTAINs with
`flow_context_unknown`. Other refusals are `flow_state_unavailable`,
`flow_handle_invalid` and `toolspec_flow_policy_missing` (ABSTAIN),
`flow_confidentiality_violation` (ESCALATE) and
`flow_integrity_violation_verify` or `_escalate`. A refusal carries the code
and nothing about recipients, fields or handles. Tool results do not yet
raise a context's label (IFC-04b), so in this release only a raise recorded
by other means changes a decision.

**WS1 execution preconditions (#953, opt-in, default off):**
`REMORA_WS1_MODE` is `off`, `shadow` or `enforce`; any other value refuses
startup. Under the `review` and `controlled_pilot` runtime profiles, `enforce`
also requires `REMORA_WS1_ADMISSION=atomic`: legacy admission spends the grant
after the WS1 re-gate, so evidence that lapsed in between would still be
spent. A mode other than off needs `REMORA_WS1_DEPLOYMENT_MODULE`, a module
exposing `build_ws1_deployment()`: the precondition registry, verifiers,
resolvers, read capabilities, monitor profile and budget. `/assess` then runs
the WS1 loop after every other component, records it under `ws1` in the chain
and returns `ws1.mode`, `ws1.status` and `ws1.final_action`. In shadow nothing
else changes. In enforce any WS1 cap makes the call ABSTAIN with
`precondition_cap` or `monitor_cap`, and an ACCEPT token binds
`ws1_binding_hash` in its authorization context. `/execute-accepted`,
`/execute` and the async worker run the gate again with fresh lookups before
anything is consumed and refuse with `ws1_regate_refused`; a moved requirement
set or profile refuses as `context_mismatch`. Under
`REMORA_WS1_ADMISSION=atomic`, a review item whose admission refuses returns no
`execution_grant`: the grant minted before the admission is spent in place and the
chain records `execution_grant_withheld`. Enforce refuses startup without
`REMORA_FLOW_CONTROL=1` and evidence named for the prerequisite IFC work
packages ([design](design/ws1-deterministic-authorization-learned-monitoring-v1.md)).

**Cumulative limits (opt-in, default off):** a check on one call cannot see
that three payments pass a budget, that small setpoint moves add up, or that
a fan was started too often. `REMORA_LIMITS_FILE` names a YAML or JSON
`remora-cumulative-limits/v1` policy and `REMORA_LIMITS_LEDGER` where its
reservations are kept: a SQLite file on one host, or a PostgreSQL DSN
(`postgresql://...` or a libpq `key=value` string) that every executor shares.
On Postgres every ledger transaction takes one advisory lock. Two hosts
reserving against the same limit are therefore serialized, as one host's
SQLite transactions are, and the schema is created on first open under that
lock.
Either one without the other refuses startup. A SQLite ledger beside
authority state on `REMORA_PG_DSN` refuses startup under every profile unless
`REMORA_LIMITS_LEDGER_SCOPE=single_host` declares that one host runs
executors. That pairing is the shape a second executor host can join, and that
host would keep its own budget. With the authority state on SQLite as well,
nothing needs declaring.

The policy has four parts. `meters` says what one call of a tool consumes. A
`sum` meter reads an amount argument, a `count` meter charges `per_call`, and
a `change` meter charges how far an absolute value moves from the last value
REMORA let through for that resource. A meter has a fixed `unit` or a
`unit_argument`, an optional `resource_argument` and a `scale`. `limits`
cap a quantity per tenant, optionally per sliding `window_seconds`. A limit
is for one `principal` or `"*"` (one total shared by all principals). Its
`resource` is one id, `"*"` (each resource apart) or absent (all together).
`baselines` give each `change` resource its starting value, with a
`seed_id`. `coverage` is `listed` or `all_writes`.

```json
{"schema": "remora-cumulative-limits/v1", "coverage": "all_writes",
 "meters": {
   "transfer_payment": [{"quantity": "spend", "kind": "sum", "argument": "amount",
                         "unit_argument": "unit"}],
   "set_supply_air_setpoint": [{"quantity": "setpoint_movement", "kind": "change",
                                "argument": "value", "scale": 10, "unit": "degC",
                                "resource_argument": "unit"}],
   "start_fan": [{"quantity": "fan_starts", "kind": "count", "unit": "starts",
                  "resource_argument": "unit"}]},
 "limits": [
   {"limit_id": "q4-spend", "tenant": "acme", "quantity": "spend", "unit": "JPY",
    "max": 20000, "principal": "agent-1"},
   {"limit_id": "supply-air", "tenant": "acme", "quantity": "setpoint_movement",
    "unit": "degC", "max": 20, "window_seconds": 3600, "principal": "*", "resource": "*"},
   {"limit_id": "fan-starts", "tenant": "acme", "quantity": "fan_starts",
    "unit": "starts", "max": 3, "window_seconds": 3600, "principal": "*", "resource": "*"}],
 "baselines": [{"tenant": "acme", "quantity": "setpoint_movement", "resource": "AHU-1",
                "value": 19.0, "seed_id": "2026-10-22"}]}
```

Here `max: 20` at scale 10 is 2.0 degC of movement per hour per unit, shared
by every agent. Moving back counts as movement. A value that is not an
integer at the meter's scale, such as 19.05 at scale 10, is refused, so a
move cannot be split into steps too small to count. A negative amount is
refused too.

The governed dispatcher reserves a metered call against every limit it
matches as its last check before the lease nonce is spent. A call that does
not fit never reaches the tool, and `tool_execution.refusal_reason` names
the reason. `limit_exceeded` is the main one. `limit_undeclared` means no
limit matches a meter. `limit_tool_unmetered` means a write tool has no meter
under `all_writes`, and `limit_coverage_unknown` that neither its signed
ToolSpec nor the deployment's semantic bundle says whether it writes. `limit_amount_invalid`, `limit_unit_invalid` and
`limit_resource_invalid` reject an unreadable call, and
`limit_invocation_differs` a flow-resolved invocation that would meter differently from
the approved wire form. `limit_principal_invalid` refuses a principal, and
`limit_unit_invalid` and `limit_resource_invalid` a unit or resource, that contains the
ledger's key separator. `limit_baseline_unknown`
means a `change` resource has no known value. `limit_resource_busy` means
another change to it has not settled. `limit_changed` means a limit was
edited under an existing `limit_id`; declare a new id instead. The last two
are `limit_principal_missing` and `limit_ledger_unavailable`.

After the tool runs, the dispatcher records whether it ran. A write that
raised leaves its resource unknown until a baseline with a new `seed_id` is
declared, because REMORA cannot tell where the equipment ended up.

A `change` meter can instead be `"observed": true`. The deployment then names
a module in `REMORA_LIMITS_OBSERVER_MODULE` that exposes
`observe_limit_value(tenant, quantity, resource)` and returns the value the
equipment reports. Movement is measured from that value before each change,
rounded up, so a change made outside REMORA is not charged and a change REMORA
makes is never missed. After the tool runs, the value is read back. If the
equipment did not reach the target, the dispatcher logs
`dispatch.limit_target_not_reached`, and the next change starts from the
value read back. An observed meter needs no baseline and no re-seed after a
failed write. An observation that fails or is not a finite number refuses as
`limit_observation_unavailable`. A policy with observed meters and no
observer refuses startup.

The plant can change between the read the reservation is charged from and
the write. Just before the tool runs, the dispatcher reads each observed
resource again. If it moved, the write does not happen. The call refuses as
`limit_state_changed`, the lease's nonce is spent, its reservation is
given back and a `change` meter's value is put back where it was; nothing was
written, so nothing is unknown. A meter may also name `previous_field`, a field of the tool's
result in which the controller reports the value it replaced. The movement
from that value to where the plant ended up is charged, and anything beyond
the reservation is logged as `dispatch.limit_charged_after_the_fact` and
counts against later changes. Without such a report, a change in the last
moment before the write is charged as reserved. Only a conditional write at
the controller closes that window.

The limits are bound to the authority that sets them and to every decision
made under them. `REMORA_LIMITS_TRUSTED_KEYS` lists the Ed25519 public keys of
that authority. With it, `REMORA_LIMITS_FILE` must be a
`remora-cumulative-limits-signed/v1` envelope signed by one of those keys
(`scripts/sign_limit_policy.py`), so a REMORA host cannot write itself a
larger budget. The digest of the limit policy is part of the policy identity
(`limits_policy_hash`, `cumulative_limits` in the coverage block), so an ACCEPT
token issued under one set of limits refuses under another. The assessment of
a proposal records the digest too. An approval is refused with 409
`limits_changed` on `/execute` and in the async worker when the limits it was
given under were turned off, relaxed or replaced. Limits turned on after an
approval apply at dispatch. The dispatcher enforces the policy it verified at
startup, built from the same bytes it digested. When the file at
`REMORA_LIMITS_FILE`, or the limit settings, change without a restart, every
call refuses with `limit_policy_changed` at `/assess` and at dispatch, whether
the new file is smaller, larger or fails verification. A restart verifies and
enforces the new policy. The signature covers the `policy` block only:
`signed_at` is unsigned metadata that no decision reads, though the digest
covers it. `REMORA_REQUIRE_LIMITS=1` makes limits mandatory:
startup refuses without limits, without trusted keys, or with coverage other
than `all_writes`. The `controlled_pilot` runtime profile requires it, together
with `REMORA_LIMITS_FILE`, `REMORA_LIMITS_LEDGER`, `REMORA_LIMITS_TRUSTED_KEYS`
and `REMORA_REQUIRE_IDEMPOTENCY` (below), and a PostgreSQL `REMORA_LIMITS_LEDGER`
whenever `REMORA_PG_DSN` is set; `review` and `research` do not,
and the OT pilot sets `REMORA_REQUIRE_LIMITS` itself. `/assess`
gives the same answer earlier as a 409 and records `limit_refused` on the
chain. That check reserves nothing; the reservation at dispatch is what
holds.

A policy may declare, per tool, the `idempotency.key_arguments` that identify
one operation (for a payment: payee, amount, unit and reference). A second
call with the same key refuses before anything is charged:

- `limit_duplicate_in_flight` while the first is reserved or running;
- `limit_duplicate_operation` after it ran;
- `limit_outcome_unknown` while its outcome is unknown.

It runs only once the first provably did not. Without a declared key, two
calls are two operations, so a deployment that declares none charges one
payment proposed twice twice. `REMORA_REQUIRE_IDEMPOTENCY=1` closes that.
Startup refuses while a metered write tool declares no key. A call to a tool
the startup check could not classify refuses as `limit_key_undeclared`, or as
`limit_coverage_unknown` when the deployment cannot say whether it writes.

A reservation is given back only when the call provably did not run:

- the fence refused;
- the tool raised `ToolDidNotExecute(source, detail)` and the policy names
  `source` in `non_execution.<tool>.trusted_sources`. The dispatch reports
  `tool_did_not_execute` either way. From a source the policy does not name,
  the call is held as unknown like any other raised call, so an adapter
  cannot free spent budget on its word. Only the budget trusts even the
  declared source. The execution outcome stays UNKNOWN, because FAILED needs
  a `PreEffectProof` and no dispatch path produces one;
- the lease expired before the tool started;
- a reviewer resolved the outcome and the deployment checked the evidence.

A call whose outcome is unknown holds its reservation. `GET
/v1/execution/limits/unresolved` lists such calls. `POST
/v1/execution/limits/resolve` (`operation_id`, `executed`, `evidence_ref`,
`reason`, `review` capability) settles one from what the rail or plant
reports: `executed=false` returns the reservation, `executed=true` keeps it.
The principal the call was charged to may not resolve it (409
`limit_resolver_is_principal`). Before anything changes, the module named by
`REMORA_LIMITS_EVIDENCE_MODULE` (exposing
`check_limit_evidence(tenant, operation, evidence_ref)`, which returns a
mapping whose `executed` is `true` or `false`) is asked about the evidence.
Without such a module every resolution refuses (409
`limit_evidence_unchecked`) and the budget stays held; a checker that raises
or cannot tell refuses as `limit_evidence_unavailable`, and one that
disagrees with the reviewer as `limit_evidence_disputed`. The ledger records the decision first; the
chain record `limit_operation_resolved` (reviewer, evidence, the module that
checked it, `resolved_at`) is appended afterwards, keyed by the operation so it
cannot be written twice. The response's `audit_recorded` says whether that
append succeeded; when the chain was unreachable, the resolution stands in the
ledger and the next limits call appends the record. A crash between the two
steps therefore leaves no undocumented release, only a record that arrives
late. The checker is only as trustworthy
as the deployment's source; REMORA verifies that it answered and agreed, not
that the rail told the truth. Hosts share a limit only when they share the
Postgres ledger; separate SQLite files are separate limits. A
`change` meter that is not observed tracks the values REMORA let through, not
the plant.
NEGATIVE_RESULTS.md §97 has the measurement and CAP-031 the caveats.
[provenance/verified-prior-art-cumulative-limits-2026-10-23.md](../provenance/verified-prior-art-cumulative-limits-2026-10-23.md)
lists the prior art these limits build on and what may not be claimed for them.

**Other settings the API reads:** `REMORA_TOOLSPEC_REVOKED_IDENTITIES` is a
comma-separated list of ToolSpec signing identities that are refused even when
trusted (checked before trust, so revocation wins). `REMORA_EXECUTION_TIMEOUT_SECONDS`
bounds a remote execution-domain call (default 120). `REMORA_RISK_PROFILE_PATH` and
`REMORA_OPA_POLICY_PATH` replace the risk-profile file and name the OPA policy file;
both enter the policy identity. `REMORA_PDP_SIGNING_KID` and `REMORA_LEASE_SIGNING_KID`
set the key ids stamped on grants and leases. `REMORA_RETRIEVAL_TOP_K`,
`REMORA_BASE_EVIDENCE_JSONL` and `REMORA_RUNTIME_EVIDENCE_JSONL` configure the
assess surface's retrieval. `REMORA_SLO_LATENCY_P95_MS`,
`REMORA_SLO_ESCALATION_RATE_MAX` and `REMORA_SLO_ORACLE_COST_PER_ASSESS_USD_MAX`
set the SLO thresholds the metrics endpoint reports against (defaults 2000, 0.30,
0.05).

**Capability sets (WS8 Q8.2, opt-in):** with
`REMORA_CAPABILITY_POLICY_FILE` naming a YAML or JSON capability policy,
the API resolves an `EffectiveCapabilitySet` for every call. It uses the
authenticated principal, the tenant, the call's `target_environment` and its
optional `task_type`, and takes nothing else from the request. A call with no
task type resolves to no tools. `/assess` records the capability block on the
chain and in the response. A tool outside the set is ABSTAIN with reason
`capability_not_allowed`. `/execute` and `/execute-accepted` refuse such a
tool with 409 before anything is consumed. They resolve the set again at
dispatch and sign its digest into the lease. `/dispatch-leased` takes the set
as `capability_set`, and refuses one whose content no longer matches its
digest. The dispatcher refuses a lease whose set is missing, mismatched,
expired, or bound to another principal, tenant or environment.
`REMORA_REQUIRE_CAPABILITY_SET=1` refuses any lease without a capability
digest. The task type is declared by the caller. It is intersected with the
principal's own tools, so it can never widen them.
`GET /capabilities?task_type=...&target_environment=...` (Q8.3) returns the
same set projected for an agent. It returns the set, an OpenAI tool list
holding only the tools in the set, and the capability exposure ratio
(exposed over registered tools). A tool outside the set is absent from the
list, and it is still refused if a client calls it anyway. Without a
capability policy the route answers 404.
A capability policy may carry `constraints` per tool (Q8.4). The
`allowed_fields` key limits which argument keys a call may use. `conditions`
compare an argument or a trusted-state fact with a literal (`eq`, `ne`, `in`,
`not_in`, `lt`, `lte`, `gt`, `gte`), or require an argument to equal a state
fact (`equals_state`). State is read only through the `read(source,
arguments)` function of the module named by
`REMORA_CAPABILITY_STATE_MODULE`. An out-of-scope argument is
`capability_argument_mismatch`, and a violated state condition is
`capability_scope_violation`. A condition that needs state no reader can
supply is `capability_state_unverifiable`. The same checks run at `/assess`,
at the execution pre-check and in the dispatcher.
With `REMORA_CAPABILITY_EPOCH_MODULE` naming a module with
`current(tenant_id, principal_id)` and `revoked(capability_set_id)` (Q8.6),
each set is issued under the current principal, tenant, policy and ToolSpec
epochs, and the dispatcher reads them again. A set issued under an older
epoch refuses as `capability_stale`, and a revoked one as
`capability_revoked`. A source that cannot answer refuses as
`capability_epoch_unverifiable`.
The evidence export carries a `capability_decision` section with every
capability check recorded for the proposal (Q8.7). Its `evidence_coverage`
section adds the contract `success_established_v1`. That contract is complete
only when the chain holds an assessment the capability check allowed, the
authorization, an execution that ran and a verified effect. Executor success
alone never completes it. A proposal assessed without a capability policy
reports the missing capability decision.

**Checks between authority and effect (WS7, all opt-in):** each setting
below binds one check into the governed dispatcher. Every check runs after
the lease verifies and before the nonce is consumed, so a refusal leaves the
lease unspent. An unset setting leaves dispatch as it was.

| Setting | Check | Refusals |
|---|---|---|
| `REMORA_EFFECT_REGISTRY_MODULE` (`build_resolver()`) | The implementation, resource and effect kind a call resolves to are signed into the lease and resolved again at dispatch | `resolved_effect_mismatch`, `unresolved_reference` |
| `REMORA_STATE_REVISION_MODULE` (`read_revision(resource)`) | A call may carry `plan` (`plan_id`, `reads`, `depends_on`); its dependencies are re-read before the write | `stale_plan`, `plan_state_unverifiable` |
| `REMORA_RECORDER_ADDRESS` with `REMORA_RECORDER_MANDATORY_TOOLS` | The intent is appended to the independent recorder (`python -m remora.audit.recorder`) before the named tools run | `recorder_unavailable` |
| `REMORA_PROCEDURE_MODULE` (`contract()`, `trace_for(lease)`) | A step that would violate the procedure's safety obligations is refused before it runs | `procedure_violation`, `procedure_trace_unavailable` |
| `REMORA_CAM_FILE` (ADR-UE-03) | The digest of the activation manifest the authority loaded at startup is signed into the lease as `cam_digest` and recorded in the `assessed` event; the executor compares it with the manifest it loaded. A manifest-bound lease where none is loaded, a lease without one where one is in force, and different manifests refuse | `cam_unbound`, `cam_lease_unbound`, `cam_changed`, `cam_unverifiable` |
| `REMORA_FLOW_CONTROL=1` (IFC-06) | The flow decision the authority judged (context epoch, verdict digest, hash of the call with every handle resolved) is signed into the lease; the executing domain compares its live context and the arguments the tool is about to receive against it, never against a value of its own. The check then holds the context with a dispatch fence on its event stream, taken at the sequence the check read, until the result commits, so a raise after the check or a second call in the same context refuses before its tool runs; the fence is renewed while the tool runs and through the commit and release, and expires with the lease TTL only for a process that died mid-call; the commit's final ownership check is the same compare-and-swap append that records it, so a commit whose fence lapsed withholds the result (`result_withheld`). An expired fence cannot reverse an external side effect the tool already caused: it withholds the result and refuses the competing call, nothing more. The recipients the verdict approved are signed into the lease as `flow_recipients_digest` (IFC-12, first slice): the mediator admits a network effect only on a host among them (`capability_recipient_not_approved` in the effect record), and the effect domain verifies the set the worker presents (`flow_recipients_mismatch`). A recipient-bound lease for a mediated tool presented without a set (an executor with flow control off) refuses `flow_recipients_required`. On `/dispatch-leased` a lease whose signature does not verify is refused before the flow check writes to the context | `flow_lease_unbound`, `flow_epoch_changed`, `flow_digest_changed`, `flow_dispatch_contended`, `resolved_call_mismatch`, `flow_recipients_changed`, `flow_recipients_required`; withheld: `flow_dispatch_fence_expired` |

The evidence export (`GET /proposals/{proposal_id}/evidence`) carries an
`evidence_coverage` section in its hashed manifest. It says, for the claims
`authorized_execution_v1` and `executed_effect_v1`, whether the evidence is
`COMPLETE`, `AUTHENTIC_BUT_INCOMPLETE`, `INCONCLUSIVE` or `TAMPERED`, and
what is missing. A plan is signed into the lease when the call is executed,
not into the ACCEPT token at assessment. It guards against premises that
moved, not against a different plan presented later.

**Semantic reading (`GET /proposals/{proposal_id}/semantic-assessment`).**
When the semantic shadow is on (`REMORA_SEMANTIC_SHADOW`, see
[integrations/jev_decision_provider.md](integrations/jev_decision_provider.md)),
Jev's reading of a proposal is recorded beside the audit chain and served
here. Every response carries `authoritative: false` and an `advisory` text,
and no approval, resolution or execution path reads it. Read capability is
required and the route is tenant-scoped: another tenant's proposal is a 404.

| Field | Meaning |
|---|---|
| `status` | `available`, `failed`, or why there is no reading: `not_enabled`, `pending`, `tenant_not_opted_in`, `request_not_resolved`, `dropped`, `unknown` |
| `for` | `verifier` at VERIFY (a machine lookup), `approver` at ESCALATE (a person) |
| `verification_focus` | checks for the lookup, worst first: `confirm_target`, `confirm_intent`, `confirm_scope`, `exclude_untrusted_text` |
| `attention` | the same concerns in plain words, with value and cut |
| `answers` | every answer with its question, value, cut and, for a score, the nearest level's label |
| `would_change_to` | the action Jev's answers would have produced, when it differs |
| `profile`, `language`, `caveats` | the deployment profile, its language, and the caveats that apply to it |

**Authentication modes:** token-table mode (`REMORA_API_TOKENS`) maps each
bearer token to a fixed tenant and role; callers cannot forge either. An
`X-Remora-Tenant` header may be omitted or repeat the credential's tenant;
one naming another tenant is refused with 403. Single-token mode
(`REMORA_API_BEARER_TOKEN`) takes tenant and role from caller-asserted
headers, so it is **development only**: outside development every request in
that mode is refused with 403. Dev mode (no credentials) runs without auth.
`REMORA_ENV` has two values, `development` (also unset, blank or `dev`) and
`production` (also `prod`); any other value, such as `staging`, refuses
startup instead of being read as either. The strict runtime profiles
(`review`, `controlled_pilot`) require `REMORA_API_TOKENS` (RMR-CR-003).

**Idempotency:** `idempotency_key` deduplicates `POST /assess` per tenant
and authenticated principal. The assess permission is checked first. The key
is then reserved before anything is assessed, so concurrent retries share one
decision and at most one execution token. A retry with the same key and the
same request returns the stored answer. The same key with a different request
is a 409 (`idempotency_key request_mismatch`), and a key another request still
holds after a 10 s wait is a 409 (`idempotency_key in_progress`). The store is
durable under `REMORA_PG_DSN` or `REMORA_CHAIN_DB`; otherwise it is a bounded
in-process LRU (10 000 entries), where an evicted key re-runs assess.

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
  (only ACCEPT/VERIFY execute; a changed risk tier or approval requirement
  voids the approval), all transitions hash-chained.
- `remora/governance/degradation.py`, `DegradationRecorder` (G0–G4 ladder with
  tamper-evident transitions) and `g4_refuses()`.
- `remora/governance/a2a_envelope.py`, `A2AGovernanceEnvelope`, `RegisteredKey`
  (principal-bound per-link keys), `sign_delegation_link()`.
- `remora/governance/activation_manifest.py`: the Capability Activation
  Manifest of SDD unified capability execution v1.1 §3 (ADR-UE-03), contract
  `capability-activation/v1` (`schemas/capability_activation_manifest_v1.yaml`).
  `CapabilityManifest.from_dict` parses one entry per registered capability
  with the per-deployment fields only. It refuses a restated register fact
  (`hook`, `status`, `evidence`), a mode outside the vocabulary, a requested
  mode outside `allowed_modes` and `ALLOW` as a fail mode. `digest` is the
  SHA-256 of the sorted, compact body, which later slices pin as `cam_digest`.
  `sign_manifest` and `verify_signed_manifest` use Ed25519 under
  `REMORA/CAPABILITY-MANIFEST/v1` (`scripts/sign_capability_manifest.py`).
  `load_manifest_from_env` reads `REMORA_CAM_FILE` and the public keys in
  `REMORA_CAM_TRUSTED_KEYS`; it refuses an unsigned manifest under a strict
  profile and a signed one it cannot check. No runtime reads the manifest
  yet. The effective mode, the startup validation, the lease field and the
  catalogue route are the next slices, and every mode is NOT_ESTABLISHED
  until they land.
- `remora/governance/capability_activation.py`: the effective mode per
  capability, from the signed requested mode, the premises this process can
  verify (`PREMISES`, each stating what it checks) and the registered maturity
  in the packaged catalogue `capability_catalogue_v1.json`. A capability absent
  from the manifest is `DISABLED`. A failed or unverifiable premise applies the
  entry's fail mode (`DISABLED`, or `BLOCKED`, never allow). An enforcing
  request below `WIRED_API_PATH` is downgraded to the highest non-enforcing
  allowed mode. `servers/api.py` computes the report at startup
  (`CAPABILITY_ACTIVATION`). With `REMORA_CAM_REQUIRED=1` startup refuses
  without a loadable manifest, with an entry the catalogue does not have, and,
  under a strict profile, with a registered capability left out.
  Migrated flags must agree with a loaded manifest: `REMORA_REQUIRE_LIMITS`
  set means CAP-031 is requested `ENFORCE` or `VERIFY`, unset means it is not;
  a disagreement refuses startup whether or not the manifest is required.
  `GET /v1/system/capabilities` (`read`) serves the catalogue joined with the
  report: per capability its registered maturity, primary hook, requested and
  effective mode, reasons and premise results, and the manifest's digest and
  whether it was signed. Without a manifest every mode is `NOT_ESTABLISHED`.
  No signer key id or credential is returned.
- **Effective modes at dispatch.** With a manifest loaded, every dispatch
  requires the capabilities that authorize it to be effective `ENFORCE`:
  CAP-003 (the signed grant) and CAP-013 (lease dispatch), plus CAP-031 while
  cumulative limits are configured. Any other mode refuses before the nonce,
  so nothing is spent: `capability_not_enforcing:<CAP>:<mode>`, and a
  capability absent from the manifest counts as `DISABLED`. Only `ENFORCE`
  authorizes an effect. `VERIFY` sends outcomes to human review on the
  decision path, and `SHADOW`, `EVIDENCE_ONLY`, `OFFLINE`, `DISABLED` and
  `BLOCKED` authorize nothing (`MODE_CONTRACT` in
  `remora/governance/capability_activation.py`). A manifest named by
  `REMORA_CAM_FILE` that did not load, for example on a bad signature,
  refuses every dispatch as `cam_not_loaded`. Without `REMORA_CAM_FILE`
  nothing changes. Other capabilities are not checked at dispatch, because
  most are evidence, research or observation mechanisms.

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
