# What are the public interfaces?

This document maps the canonical `DecisionEnvelope` contract, the
`PolicyObservation` input, the decision engine, the Oracle ABC, adapters, the
enforcement (PDP/PEP) library, and the MCP tool surface. **Implementation
source is authoritative**; every signature below is verified against source by
`tests/test_api_reference_doc.py`, if this document drifts from the code, CI
fails.

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
| `causal_explanation` | Optional policy-only what-if analysis (`decision_scope="policy_only"`) |

Serialise with `envelope.to_dict()`. The audit hash chain
(`remora/audit/hash_chain.py`, class `AuditHashChain`) links records as
`hᵢ = SHA-256(hᵢ₋₁ ‖ record_json)`; modification of a past record breaks all
subsequent hashes. This is tamper-*evidence*, not tamper-prevention, see the
limitations section of README.md.

Note: the flat per-decision record used in result files
(`action`, `trust`, `H`, `D`, `phase`, …) is the *benchmark JSONL schema*
documented in [06-reproducibility.md](06-reproducibility.md), not this envelope.

---

## PolicyObservation, input contract

`PolicyObservation` (`remora/policy/observation.py`) is a frozen dataclass
with 59 fields; on the research `/v1/assess` path **all fields except
`question` are optional and caller-populated**, REMORA is stateless and
performs no detection itself (the engine treats `None` as "unknown, not
safe"). On `/v1/execution/*` this does NOT hold: trust-bearing fields are
derived server-side and client values can only lower trust, never raise it
— see the Trust boundary section below. Selected fields by group:

| Group | Fields (selection) |
|---|---|
| Identity | `question` (required), `domain`, `session_id` |
| Consensus observables | `trust_score`, `temperature`, `final_H`, `final_D`, `final_V`, `phase`, `valid_oracle_count`, `oracle_failures` |
| Evidence | `evidence_action`, `evidence_confidence`, `evidence_contradictions`, `evidence_supporters`, `evidence_signal_source`, `require_rag` |
| Risk & action | `risk_tier`, `action_type`, `target_environment`, `rollback_available`, `state_transition_uncertain` |
| Security flags | `adversarial_detected`, `schema_valid`, `tool_forbidden`, `argument_tainted`, `coercion_detected`, `blackmail_pattern_detected`, `arguments_satisfiable`, `argument_values_supported` |
| Verification | `counterfactual_passed`, `distribution_shift_detected`, `classification_confidence`, `classification_alternatives`, `model_misspecification_risk` |
| Session & fleet | `session_action_count`, `session_cumulative_risk`, `similar_action_seen_count`, `policy_generalization_risk`, `fleet_level_effect` |
| Binding | `tool_call_hash`, SHA-256 of the full canonical tool call (name, exact args, tenant, target); recompute before execution and refuse on mismatch |

Construct from a dict with `PolicyObservation.from_json_record(record)`
(unknown keys are ignored, misspelled safety flags therefore silently default
to their permissive value; validate producer-side).

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
`in_sample_calibration_warning`, `fallback_used`, `credal`.

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
(`remora/enforcement/gate.py`), in-process set by default; cross-restart
replay refusal is not yet directly tested. See `servers/execution_api.py` and
`docs/assurance/capability_register_v1.yaml` CAP-003 (WIRED_API_PATH).

### Execution state machine, `servers/execution_api.py` (`/v1/execution/*`)

The end-to-end path (REM-035): `POST /assess` (issues an ACCEPT token or
enqueues a review item), `POST /approve` (records the authenticated principal;
mandatory bounded TTL; profile-specific approval role enforced), `POST
/execute` (re-gates the fresh observation, binds the exact payload, consumes a
one-time grant, then dispatches the tool through the app-lifecycle
`GovernedToolDispatcher`), `GET /audit/verify` (recomputes the per-tenant
chain). RBAC: `assess`/`execute` capabilities gate assess/execute; `review`
gates approve; `read` gates audit.

**Authentication modes:** token-table mode (`REMORA_API_TOKENS`) maps each
bearer token to a fixed tenant and role — callers cannot forge either.
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

**Trust boundary (issue #34):** the execution request is a PROPOSAL only —
`tool_name`, exact `arguments`, requested `target_environment` (+
`idempotency_key`). Every authoritative safety signal (risk tier, domain,
action type, trust, phase, evidence status, schema validity, rollback
capability) is derived server-side from the tool registry; the legacy
client fields (`trust_score`, `phase`, `evidence_action`,
`evidence_confidence`, `risk_tier`, …) are ignored as unknown extras. The
only inbound safety influence is a DOWNGRADE: `schema_valid: false` or
`rollback_available: false` lowers trust ("world got riskier" feeds the
freshness re-gate); `true` never raises anything, including on tools the
registry does not pin. Since the policy-only kernel has no oracle or
evidence pipeline, trust/phase/evidence are unknown at assess time and the
engine fails toward VERIFY/ABSTAIN — no probabilistic ACCEPT can fire from
this path (server-side signal sources are #35/#39 scope).

**Tool dispatch (issue #13):** tool callables are registered exclusively via
trusted deployment configuration — the module named by
`REMORA_TOOL_REGISTRY_MODULE` must expose
`register_tools(register: Callable[[str, Callable], None])` and is imported
once per process; request payloads can never add or replace callables, so
downstream credentials stay app-side. The `/execute` response carries a
`tool_execution` block (`executed`, and `result` or `refusal_reason`) that
reports what actually happened; with no module configured the registry is
empty and every dispatch reports `executed: false` /
`refusal_reason: unknown_tool` — the research default stays side-effect free
but says so explicitly. Dispatch happens only after the PEP consumed the
grant, under an `ExecutionLease` bound to tenant, principal, tool, exact
arguments, target environment and the current policy-bundle hash; a tool that
raises burns the lease nonce and surfaces as
`refusal_reason: tool_failed_nonce_burned` in both response and audit record
(`tool_executed` / `tool_refusal_reason`).

**Execution state machine (external review 2026-07-27):** the re-gate only
ever AUTHORIZES — `ReviewQueue.execute()` sets the item to `authorized`, and
`executed` is recorded exclusively by `record_execution_outcome()` after the
dispatcher confirms the side effect; refusals and raising tools terminate as
`dispatch_refused` / `dispatch_failed`, so the persisted state never claims
an execution that did not happen. The audit chain carries a durable
`execution_authorized` INTENT entry appended before the external side effect
and an `execution_result` entry after it (linked via `intent_sequence_no`) —
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
`effect`
