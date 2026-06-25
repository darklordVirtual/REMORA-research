# What are the public interfaces?

This document covers the canonical `DecisionEnvelope` contract, the
`PolicyObservation` fields, the core Oracle ABC, adapters, and the MCP tool
surface. Implementation source is authoritative; this document provides a
navigable map.

→ [01-architecture.md](01-architecture.md) for how these interfaces fit together.
→ [06-reproducibility.md](06-reproducibility.md) for the result JSONL schema.

---

## DecisionEnvelope — canonical governance contract

`DecisionEnvelope` is the single output type of every REMORA decision. It is
stable across versions. Do not add fields without updating the hash-chain schema.

Key fields (from `remora/audit/hash_chain.py` and `remora/engine.py`):

| Field | Type | Description |
|---|---|---|
| `action` | `"accept"` \| `"verify"` \| `"abstain"` \| `"escalate"` | Routing verdict |
| `trust` | float [0, 1] | Trust score from oracle consensus |
| `H` | float | Entropy (Shannon over verdict clusters, TokenFingerprintBackend) |
| `D` | float | Dissensus (fraction of oracles disagreeing with majority) |
| `phase` | `"ordered"` \| `"critical"` \| `"disordered"` | Thermodynamic phase |
| `policy_reason` | string | Human-readable policy decision reason |
| `decision_hash` | string | SHA-256 of this envelope linked to the chain |
| `timestamp` | ISO8601 string | Decision time |
| `unsafe_execution` | bool | Whether an unsafe execution was attempted |
| `model_providers` | list of {provider, model} | Oracles used |
| `prompt_template_version` | string | Template version for reproducibility |

The hash chain: `hᵢ = SHA-256(hᵢ₋₁ ‖ envelope_json)`. Any modification to a
past envelope breaks all subsequent hashes. This provides tamper-evidence, not
tamper-prevention — see `02-evidence-and-claims.md` §4 caveat.

---

## Oracle ABC

All oracles implement the same interface (`remora/core.py`):

```python
class Oracle(ABC):
    def ask(self, prompt: str, **kwargs) -> OracleResponse: ...

class OracleResponse:
    answer: str            # raw model response
    normalized: str        # normalised answer string
    confidence: float      # model confidence estimate [0, 1]
    provider: str          # provider identifier
    model: str             # model identifier
    latency_ms: float      # wall-clock call time
```

Oracles are pluggable. The recommended swarm uses three independent model
families — see `remora/cascade/stages.py: build_recommended_swarm()`.

---

## PolicyObservation

`PolicyObservation` is the structured input to `RemoraDecisionEngine`
(`remora/policy/observation.py`):

| Field | Type | Description |
|---|---|---|
| `action` | string | Proposed action name or question text |
| `action_type` | string | Category (tool_call, qa, agent_step, …) |
| `risk_tier` | string | `low` \| `medium` \| `high` \| `critical` |
| `oracle_responses` | list[OracleResponse] | Raw oracle outputs |
| `evidence_signal` | EvidenceSignal or None | Aggregated evidence scores |
| `trust` | float | Trust score computed by ConsensusGate |
| `H` | float | Entropy |
| `D` | float | Dissensus |
| `phase` | string | Phase classification |
| `session_id` | string or None | Session identifier for V(t) tracking |
| `access_context` | AccessContext or None | Clearance and tenant scope |

---

## RemoraDecisionEngine

`remora/policy/decision_engine.py`

```python
engine = RemoraDecisionEngine(policy_config=config)
envelope = engine.decide(observation: PolicyObservation) -> DecisionEnvelope
```

Hard-block invariants run before any probabilistic routing. The full invariant
list is in `remora/policy/invariants.py`.

Decision matrix by phase:

| Phase | Low-risk action | High/critical action |
|---|---|---|
| Ordered | `ACCEPT` when trust + policy pass | `VERIFY` or constrained `ACCEPT` with evidence |
| Critical | Phase-aware gating; often `VERIFY` | `ESCALATE` or `ABSTAIN` unless evidence resolves |
| Disordered | `ABSTAIN` | `ESCALATE` |

---

## Adapters

Adapters wrap REMORA into external agent frameworks (`remora/adapters/`):

### ActionGateResult

```python
class ActionGateResult:
    action: str         # ACCEPT / VERIFY / ABSTAIN / ESCALATE
    envelope: DecisionEnvelope
    allowed: bool       # True if action is permitted
    reason: str         # Human-readable reason
```

### LangGraphActionAdapter

```python
adapter = LangGraphActionAdapter(engine=engine)
result: ActionGateResult = adapter.gate(tool_name, tool_input, state)
```

### OpenAIToolCallingAdapter

```python
adapter = OpenAIToolCallingAdapter(engine=engine)
result: ActionGateResult = adapter.gate(tool_call: dict, context: dict)
```

---

## Safety — adversarial detection

`remora/safety/adversarial.py`

```python
from remora.safety.adversarial import detect_adversarial

flag = detect_adversarial(text: str) -> AdversarialFlag
# flag.detected: bool
# flag.patterns: list[str]   # matched pattern names
# flag.severity: str         # "low" | "medium" | "high"
```

Note: adversarial detection covers the action description text. It does not cover
`untrusted_context` payloads in tool results — this is an active gap documented
in `NEGATIVE_RESULTS.md` §2.

---

## MCP tools

The MCP server (`servers/mcp_remora.py`) exposes REMORA capabilities as Claude
tools over JSON-RPC stdio. Key tools:

| Tool | Purpose |
|---|---|
| `remora_consensus` | Multi-oracle consensus on a question or action |
| `remora_verify` | Evidence-backed verification of a claim |
| `remora_audit` | Retrieve audit ledger entries for a session |
| `remora_gate` | Full five-stage governance gate for a proposed tool call |
| `remora_shadow_replay` | Replay a recorded agent session for governance analysis |

Setup for Claude Code:
```bash
claude mcp add remora python /path/to/REMORA-research/servers/mcp_remora.py
```

Cloudflare Workers AI is optional; the server falls back to local Python oracle
paths without it.

---

## Cyber evidence provider

`remora/evidence/cyber.py`

```python
from remora.evidence import CyberEvidenceProvider

provider = CyberEvidenceProvider()
result = provider.triage(
    title="...", description="...", severity="critical",
    cve_ids=["CVE-2021-44228"], exposed=True, production=True,
)
# result.verdict.value        → "ESCALATE"
# result.exploit_classification.value → "KNOWN_EXPLOITED"
# result.matches[0].record.source → source label
```

Also implements the REMORA evidence provider interface for use in the oracle
pipeline. See `docs/cyber_evidence_layer.md`.
