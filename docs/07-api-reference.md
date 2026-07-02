# What are the public interfaces?

This document maps the canonical `DecisionEnvelope` contract, the
`PolicyObservation` input, the decision engine, the Oracle ABC, adapters, the
enforcement (PDP/PEP) library, and the MCP tool surface. **Implementation
source is authoritative**; every signature below is verified against source by
`tests/test_api_reference_doc.py` — if this document drifts from the code, CI
fails.

→ [01-architecture.md](01-architecture.md) for how these interfaces fit together.
→ [06-reproducibility.md](06-reproducibility.md) for the result JSONL schema.

---

## DecisionEnvelope — canonical governance contract

`DecisionEnvelope` (`remora/governance/envelope.py`) is the canonical v2
decision record: a nested, immutable, JSON-serialisable structure. Do not add
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
(`remora/audit/hash_chain.py`, class `HashChain`) links records as
`hᵢ = SHA-256(hᵢ₋₁ ‖ record_json)`; modification of a past record breaks all
subsequent hashes. This is tamper-*evidence*, not tamper-prevention — see the
limitations section of README.md.

Note: the flat per-decision record used in result files
(`action`, `trust`, `H`, `D`, `phase`, …) is the *benchmark JSONL schema*
documented in [06-reproducibility.md](06-reproducibility.md), not this envelope.

---

## PolicyObservation — input contract

`PolicyObservation` (`remora/policy/observation.py`) is a frozen dataclass
with 56 fields; **all fields except `question` are optional and
caller-populated** — REMORA is stateless and performs no detection itself
(the engine treats `None` as "unknown, not safe"). Selected fields by group:

| Group | Fields (selection) |
|---|---|
| Identity | `question` (required), `domain`, `session_id` |
| Consensus observables | `trust_score`, `temperature`, `final_H`, `final_D`, `final_V`, `phase`, `valid_oracle_count`, `oracle_failures` |
| Evidence | `evidence_action`, `evidence_confidence`, `evidence_contradictions`, `evidence_supporters`, `evidence_signal_source`, `require_rag` |
| Risk & action | `risk_tier`, `action_type`, `target_environment`, `rollback_available`, `state_transition_uncertain` |
| Security flags | `adversarial_detected`, `schema_valid`, `tool_forbidden`, `argument_tainted`, `coercion_detected`, `blackmail_pattern_detected` |
| Verification | `counterfactual_passed`, `distribution_shift_detected`, `classification_confidence`, `classification_alternatives`, `model_misspecification_risk` |
| Session & fleet | `session_action_count`, `session_cumulative_risk`, `similar_action_seen_count`, `policy_generalization_risk`, `fleet_level_effect` |

Construct from a dict with `PolicyObservation.from_json_record(record)`
(unknown keys are ignored — misspelled safety flags therefore silently default
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
ladder mirrors `decide()` rule-for-rule — parity is enforced by
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
outcomes — this adapter layer is the actual runtime blocking path.

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

`expires_at`, when set, is signed into the payload and enforced by
`token.verify()`. **Integration status:** this package is a library plus its
test suite; no runtime component in this repo issues or verifies tokens yet
(see the package docstring). Do not cite it as integrated enforcement.

---

## Safety — adversarial detection

`remora/safety/adversarial.py`:

```python
from remora.safety.adversarial import detect_adversarial

flagged: bool = detect_adversarial(text)
```

Returns a plain `bool` (pattern-based heuristic). It covers the action
description text only; it does not cover untrusted payloads inside tool
results — an active gap documented in `NEGATIVE_RESULTS.md`.

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
pipeline. See `docs/cyber_evidence_layer.md`.
