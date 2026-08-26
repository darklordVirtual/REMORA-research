# REMORA Architecture

REMORA is a **pre-execution governance overlay for agentic AI actions**: given a
proposed tool call, it returns exactly one of **ACCEPT / VERIFY / ABSTAIN /
ESCALATE**, is conservative under uncertainty (it fails toward ABSTAIN or
ESCALATE rather than toward execution), and records every decision in a
SHA-256 hash-chained audit trail.

This document is the canonical top-level architecture reference. It describes the
system as it exists now. For the detailed numbered walkthrough see the `docs/`
series, beginning with [`docs/01-architecture.md`](docs/01-architecture.md); the
two are complementary and describe the same current governance architecture. Use
the diagrams as a map when reading the source.

---

## 1. What REMORA governs

REMORA governs **agent actions**, tool calls an autonomous agent proposes to
run (write to a database, send a payment, change infrastructure, call an external
API). It is not a fact-checker and does not answer questions. It sits between the
agent's decision to act and the action actually running, and decides whether that
specific proposed action is allowed to execute without a human.

| Outcome | Meaning | Autonomous action |
|---|---|---|
| **ACCEPT** | assurance conditions for unattended execution are met | permitted |
| **VERIFY** | plausible but validation is required first | pending |
| **ABSTAIN** | too uncertain to decide | blocked |
| **ESCALATE** | human review required | blocked, routed to a person |

`ACCEPT` does not assert the action is *correct*. It asserts the conditions for
running it without a human are verifiably met. REMORA governs **execution
permission**, not truth.

---

## 2. The canonical research claim (stated honestly)

**The safety floor is carried by the deterministic hard-block policy layer, not by
the probabilistic consensus / disagreement-diagnostics / session-stability machinery.**

On the 700-task adversarial tool-call benchmark (a deterministic simulator;
70 unique templates × 10 cosmetic variants, effective N = 70), the
temperature-gate-only configuration leaves 1.4% of unsafe actions executing
under the leakage-free input contract (2026-07-20 re-run); the hard-block
policy rules close unsafe execution to 0% (cluster-level Wilson CI
[0.0%, 5.2%]). The unsafe-rate delta vs. baselines is not statistically
significant at the template-cluster level (p = 0.50); the gate's significant
advantage on this benchmark is decision utility and routing accuracy.

The consensus, entropy/dissensus, phase-classification, and session-stability (`remora/lyapunov.py`, legacy naming) components do
**not** contribute to the unsafe-execution safety floor. What they contribute is
**routing quality**: calibrated separation of the plausible-but-unverified cases
into VERIFY versus ABSTAIN. Do not cite REMORA's safety result as evidence for
the value of the consensus machinery, they are distinct claims backed by
distinct artifacts. See `docs/02-evidence-and-claims.md` §1 and
`NEGATIVE_RESULTS.md`.

---

## 3. The five-stage assessment pipeline (`/v1/assess`, research surface)

This section describes the **research assessment surface**. Its oracle-backed
stages (consensus, evidence verification) are experimental augmentation: they
are **not prerequisites** of the enforcing execution kernel (`/v1/execution/*`,
see `DEVELOPER_OVERVIEW.md` and `docs/product/product_truth_contract.yaml`)
and can never override the deterministic hard-guard floor.

A proposed action passes through five stages. An adversarial/coercion **admission
firewall runs first**, before any oracle call; the remaining deterministic
hard-block invariants are then evaluated with **absolute priority inside the
policy decision (Stage 4)**. A confident, wrong majority cannot push an unsafe
action through: a hard block outranks any probabilistic score, regardless of when
in the pipeline it is evaluated.

```mermaid
flowchart TD
    ACT["Proposed agent action<br/>(tool call + args + risk_tier / action_type / env)"] --> S1

    S1["Stage 1 · Admission firewall<br/>remora/safety/adversarial.py + remora/engine.py<br/>adversarial / coercion text detection, deterministic, pre-oracle"]
    S1 -.->|"detected: adversarial_detected set,<br/>oracle fan-out suppressed"| S4
    S1 -->|"passes admission"| S2

    S2["Stage 2 · Multi-oracle consensus<br/>remora/engine.py + remora/correlation.py<br/>disagreement diagnostics: entropy H, dissensus D, trust,<br/>correlation-aware diversity weighting"]
    S2 --> S3

    S3["Stage 3 · Evidence verification<br/>remora/oracles/evidence_verifier.py, evidence_v2/v3<br/>source-anchored support / contradiction (lexical)"]
    S3 --> S4

    S4["Stage 4 · Policy decision<br/>remora/policy/decision_engine.py + remora/selective/<br/>hard_guard_floor() first, absolute priority (admission flag,<br/>schema, forbidden tool, coercion, blackmail, counterfactual,<br/>contradicted evidence, tainted argument),<br/>then conditional guards and trust / conformal routing,<br/>then the argument gates on whatever is left"]
    S4 -->|"hard guard fires"| ESC["ESCALATE / ABSTAIN<br/>(cannot be overridden)"]
    S4 --> DEC{"Decision"}

    DEC -->|"assurance met"| ACCEPT["ACCEPT"]
    DEC -->|"needs validation"| VERIFY["VERIFY<br/>carries a ResolutionPlan when a bounded<br/>lookup can close the gap"]
    DEC -->|"too uncertain"| ABSTAIN["ABSTAIN"]

    VERIFY -.->|"resolver / validator answers:<br/>whole router re-runs on a fresh observation<br/>(remora/policy/resolution.py)"| S4

    ACCEPT & VERIFY & ABSTAIN & ESC --> S5["Stage 5 · Hash-chain audit<br/>remora/governance/envelope.py + remora/audit/hash_chain.py<br/>DecisionEnvelope, atomic per-tenant chain on the /v1/execution path"]
    S5 --> OUT["Audit chain + shadow-replay log"]
```

Two edges are dotted because they are not verdicts. Stage 1 never issues one: it
sets `adversarial_detected` and suppresses the oracle fan-out, and the first
guard in `hard_guard_floor()` turns that flag into ESCALATE
(`ADMISSION_FIREWALL_BLOCKED`). Every verdict leaves from Stage 4, which is why
`decide()` and `explain()` cannot disagree. The VERIFY edge is the resolution
loop: a bounded lookup answers, and the whole router re-runs on a fresh
observation rather than patching the old one.

**Stage summary:**

1. **Admission firewall** (`remora/safety/adversarial.py`, `remora/engine.py`), a
   deterministic adversarial/coercion text check that runs *before* any oracle
   call. It sets `adversarial_detected` and suppresses the oracle fan-out; the
   ESCALATE itself is issued by the first guard in Stage 4, so the firewall has
   one job and the verdict has one source.

   The safety floor of §2 is exactly what `hard_guard_floor()` returns, and
   nothing else: admission flag, invalid schema, forbidden tool, coercion,
   blackmail pattern, failed counterfactual, contradicted evidence, and tainted
   arguments (ESCALATE when untrusted content controls a recipient, command or
   credential, or at critical risk; VERIFY otherwise). Rules that depend on risk
   tier or environment, such as **production-write without safeguards**,
   unavailable rollback, uncertain state transition or critical phase, are
   *conditional* gates, not part of the floor. The distinction is deliberate:
   an external PDP
   (`opa_adapter.py`) may legitimately differ in the probabilistic band, but may
   never downgrade below the floor.
2. **Multi-oracle consensus** (`remora/engine.py`, `remora/correlation.py`,
   `remora/thermodynamics`), several oracle backends answer; a consensus
   *phase* (ordered / critical / disordered) is derived from entropy `H`,
   dissensus `D`, and a trust score. Correlated oracles are down-weighted so
   echo-chamber agreement does not inflate confidence. The physics-flavoured
   module and field names (`thermodynamics`, `temperature`) are legacy naming
   for these disagreement diagnostics, **not** a physics claim.
3. **Evidence verification** (`remora/oracles/evidence_verifier.py`,
   `evidence_v2.py`, `evidence_v3.py`), where evidence is available, checks
   whether cited sources support or contradict the candidate. Relation detection
   is lexical (token overlap + negation heuristic), pluggable for a future NLI
   upgrade.
4. **Policy decision** (`remora/policy/decision_engine.py`, `remora/selective`),
   `RemoraDecisionEngine.decide()` runs the hard-block-first ladder, then the
   `PhaseAwareGuardrail`, conformal risk control (`conformal.py`), and the
   weight-corrected CRC (`crc.py`) map the phase and trust state to
   accept/verify/abstain, with phase-specific thresholds (the critical phase is
   handled by score inversion, see §8). Hard guards evaluated here have absolute
   priority over the routing signals.

   **The argument gates run last** (`missing_required_arguments`,
   `unvalidated_required_arguments`, `argument_values_grounded`), after every
   blocking rule, so they can only make a would-be ACCEPT more cautious and can
   never unblock anything. Each answers a different question about the call's
   inputs: can a missing argument be sourced at all (no resolver means ABSTAIN,
   not VERIFY, since a verification that cannot happen must not be promised); is
   an argument that steers where the action lands confirmed against the system of
   record; and do the argument values anchor to *this* task, or is the call
   observationally identical to a well-formed copy of someone else's. A VERIFY
   from these gates carries a `ResolutionPlan` naming the permitted lookup and
   the exact arguments it may write. `remora/policy/resolution.py` runs that
   lookup and re-enters the whole router; the resolver cannot switch tools or
   write outside its plan.
5. **Hash-chain audit** (`remora/governance/envelope.py`,
   `remora/audit/hash_chain.py`), the decision is written as a
   `DecisionEnvelope` and hash-chained. The record is **tamper-evident**, not
   tamper-proof.

---

## 4. Component map

| Area | Location | Role |
|---|---|---|
| **Policy engine** | `remora/policy/decision_engine.py` | `RemoraDecisionEngine.decide(obs) -> DecisionReport`; ordered hard-block-first ladder; `explain()` reproduces the full rule-by-rule trace |
| Policy support | `remora/policy/invariants.py`, `trap_classifier.py`, `opa_adapter.py` | machine-checked safety invariants; irreversibility/impact trap scoring; OPA/Rego integration with a Python fallback |
| **Governance envelope** | `remora/governance/envelope.py` | `DecisionEnvelope` (v2) + `AuditBlock`, the canonical governance contract |
| Cascade pipeline (experimental, `/v1/assess` research surface) | `remora/cascade/` | staged assessment: `FastGate` → `ConsensusGate` → `VerifierGate` → `CritiqueRevisionGate` → `SelfConsistencyGate` → `MixtureOfAgentsSynth` (see §5) |
| **Consensus core** | `remora/engine.py`, `remora/reporting.py`, `remora/state.py`, `remora/correlation.py` | multi-oracle consensus loop; report + `DecisionEnvelope` assembly (`build_report`) and the `RemoraState` session-state contract split out of `engine.py` (2026-07-29); rolling correlation matrix and diversity weights |
| **Uncertainty observables** | `remora/thermodynamics.py`, `remora/research_attic/statphys/` | entropy `H`, dissensus `D`, value `V` as an uncertainty-routing metaphor (not physics) |
| **Selective prediction** | `remora/selective/` | `conformal.py`, `crc.py` (weight-corrected slack), `pvd.py`, `guardrail.py` (`PhaseAwareGuardrail`), `drift_detector.py` |
| **Oracles (pluggable)** | `remora/oracles/` | interchangeable backends, see §6 |
| **Audit chain** | `remora/audit/hash_chain.py` | SHA-256 hash chain; tamper-**evident** |
| **Governance API** | `servers/api.py` | FastAPI governance gateway |
| **MCP server** | `servers/mcp_remora.py` | Model Context Protocol tool suite (`remora_verify_claim`, `remora_analyze_document`, `remora_rag_query`, `remora_norwegian_law_search`, `agent_start_session`, `agent_execute_tool`, `remora_session_status`, …) |
| **Edge workers** | `workers/` | `agent-control`, `rag-oracle`, `law-search`, `aromer` (see §5.4) |
| **Learning overlay** | `remora/aromer/` | AROMER, experimental, shadow-only (see §5.5) |

## 5. Component subsystems in detail

### 5.1 Cascade Pipeline (`remora/cascade/`)

The cascade pipeline is the primary path of the experimental `/v1/assess`
research surface; it is not part of the enforcing execution kernel
(`/v1/execution/*`). It invests compute
proportionally to query difficulty: simple high-confidence actions exit at
Stage 1; uncertain or contested ones pass through progressively more expensive
verification stages.

```
remora/cascade/
|- engine.py   # CascadeEngine: assembles and runs all stages
|- stages.py   # FastGate, ConsensusGate, VerifierGate, CritiqueRevisionGate, SelfConsistencyGate
\- result.py   # CascadeResult, StageResult, CascadeVerdict, CascadeStage
```

```mermaid
flowchart TD
    Q["Action + optional evidence"] --> S1

    S1["Stage 1: FastGate<br/>1 oracle call<br/>Verbalized confidence ≥ 0.90?"]
    S1 -->|"ACCEPT (conf ≥ 0.90)"| OUT["Final verdict"]
    S1 -->|"VERIFY (conf < 0.90)"| S2

    S2["Stage 2: ConsensusGate<br/>3-oracle REMORA engine<br/>consensus-phase classification"]
    S2 -->|"ACCEPT (trust ≥ 0.65)"| OUT
    S2 -->|"ABSTAIN (trust < 0.12)"| OUT
    S2 -->|"VERIFY (0.12 ≤ trust < 0.65)"| S3

    S3["Stage 3: VerifierGate<br/>LLM-as-judge, different model family<br/>evaluates consensus answer vs evidence"]
    S3 -->|"ACCEPT (supported)"| OUT
    S3 -->|"ABSTAIN (refuted)"| OUT
    S3 -->|"VERIFY (challenged)"| S3B

    S3B["Stage 3b: CritiqueRevisionGate<br/>critique → revision oracle → re-judge<br/>constitutional pattern, up to 2 rounds"]
    S3B -->|"ACCEPT / ABSTAIN"| OUT
    S3B -->|"VERIFY (still challenged)"| S4

    S4["Stage 4: SelfConsistencyGate<br/>7 independent samples, majority vote"]
    S4 -->|"ACCEPT (agreement ≥ 0.72)"| OUT
    S4 -->|"ABSTAIN (< 0.50)"| OUT
    S4 -->|"VERIFY (0.50–0.72)"| S6

    S6["Stage 6: MixtureOfAgentsSynth (optional)<br/>synthesis oracle reconciles prior responses"]
    S6 -->|"ACCEPT / VERIFY / ABSTAIN"| OUT
```

| Stage | Class | Oracle calls | Exit condition |
|-------|-------|-------------|----------------|
| 1 | `FastGate` | 1 | Verbalized confidence ≥ `cascade_fast_threshold` (0.90) |
| 2 | `ConsensusGate` | 3–12 (router-gated) | Trust ≥ `cascade_consensus_accept_threshold` (0.65) or < `cascade_consensus_abstain_threshold` (0.12) |
| 3 | `VerifierGate` | 1 | Judge outcome SUPPORTED or REFUTED |
| 3b | `CritiqueRevisionGate` | 2 × rounds (`cascade_critique_max_rounds` = 2) | Revised answer accepted/refuted; else to Stage 4 |
| 4 | `SelfConsistencyGate` | `cascade_sc_samples` (7) | Terminal on ACCEPT/ABSTAIN; VERIFY passes to Stage 6 when a synthesis oracle is set |
| 6 | `MixtureOfAgentsSynth` | 1 | Optional; runs only when `synthesis_oracle` is set and Stage 4 returned VERIFY |

Key properties: a `budget_oracle_calls` cap halts early and returns VERIFY when
the call budget is exhausted; each stage's judge/oracle is intentionally a
different model family to avoid shared failure modes; every early-exit path
includes ABSTAIN as a reachable outcome (fail-conservative); Stage 2 wraps the
full `remora.engine.Remora` (phase diagnostics, conformal guardrail, policy
engine, assurance trace) according to the active Genome flags.

### 5.2 Governance envelope (`remora/governance/envelope.py`)

`DecisionEnvelope` (v2) is the canonical governance contract and is kept stable.
It packages the action, the decision, the reasons, the trust/risk state, and an
`AuditBlock`. Every decision produces one; the envelopes are hash-chained by
`remora/audit/hash_chain.py` (`hᵢ = SHA-256(hᵢ₋₁ ‖ envelope)`). Any modification
breaks the chain, so the record is **tamper-evident**. Tamper-*proofing* requires
an external append-only (WORM) store as a deployment dependency.

### 5.3 Selective prediction (`remora/selective/`)

| Module | Role |
|---|---|
| `guardrail.py` | `PhaseAwareGuardrail`, phase-specific accept/verify/abstain routing; inverts the selection score in the critical phase (§8) |
| `conformal.py` | split-conformal risk control with finite-sample coverage bookkeeping |
| `crc.py` | conformal risk control with the weight-corrected slack term |
| `pvd.py` | Prover-Verifier Deliberation, semantic-entropy clustering of oracle responses blended with a verifier confidence signal (no LLM calls; deliberation rounds are simulated) |
| `binomial_bounds.py` | Clopper–Pearson / binomial upper confidence bounds on empirical risk |

### 5.4 Interfaces: API, MCP, and edge workers

- **`servers/api.py`**, FastAPI governance gateway.
- **`servers/mcp_remora.py`**, MCP server exposing REMORA as a tool suite to
  Claude Desktop and compatible hosts (stdlib `urllib` only). Profiles: `local`,
  `demo`, `enterprise`.
- **`workers/`**, Cloudflare edge workers, all fail-closed on authentication
  (missing `ORACLE_SECRET` / `CONTROL_SECRET` → reject, never silently permit):

  | Worker | Directory | Primary endpoints |
  |---|---|---|
  | `agent-control` | `workers/agent-control/` | `POST /execute`, `POST /sessions`, `DELETE /sessions/:id`, `GET /audit` (auth), `GET /status` |
  | `rag-oracle` | `workers/rag-oracle/` | `POST /query`, `POST /ingest` (auth) |
  | `law-search` | `workers/law-search/` | `POST /search` |
  | `aromer` | `workers/aromer/` | AROMER learning-loop endpoints (`/decide`, `/adapt`, `/outcome`, `/log`, `/intelligence`) |

  Worker URLs are configurable at runtime (`REMORA_WORKER_URL`, `RAG_WORKER_URL`,
  `LAW_SEARCH_WORKER_URL`); hardcoded URLs are not used in production paths.

### 5.5 AROMER learning overlay (`remora/aromer/`)

AROMER is a closed-loop meta-cognitive layer that runs alongside REMORA and
learns from decision outcomes (episodic memory, Bayesian world-model priors, a
Workers-AI meta-judge, a replay arena). **AII** ("Autonomous Intelligence Index") is a
composite index over five weighted components (calibration, friction, meta-judge,
transfer, stability). AROMER is **experimental and shadow-only**: episode labels
are partly self-assigned and the world model defaults to shadow mode. It has **no
external validation**. Do not cite AROMER numbers as production evidence. See
`NEGATIVE_RESULTS.md` and `paper/remora_paper.md` Appendix F.6-F.7.

Since 2026-08-20 (issue #297) AROMER is a **named subproject**, not part of the
product surface: it carries its own version line (`AROMER_VERSION`), and the
dependency runs one way only — AROMER may import the core, the core may never
import AROMER. `tests/test_aromer_subproject_boundary.py` fails on a new
importer under `remora/` or `servers/`. The charter is
[docs/aromer/SUBPROJECT.md](docs/aromer/SUBPROJECT.md).

---

## 6. Oracles are pluggable backends, not the purpose

The oracles in `remora/oracles/` are **interchangeable backends** that supply
answers to the consensus stage. They are an implementation detail of Stage 2, not
the purpose of the system.

| Backend | Class | Notes |
|---|---|---|
| Cloudflare Workers AI | `CloudflareOracle` | edge inference |
| Cloudflare RAG | `CloudflareRAGOracle` | retrieval-augmented (source-anchored) |
| Groq | `GroqOracle` | Llama-family via Groq API |
| Ollama | `OllamaOracle` | local models |
| Gemini | `GeminiOracle` | Google Gemini |
| Hugging Face | `HuggingFaceOracle` | HF inference |
| OpenRouter | `OpenRouterOracle` | gateway to many models (e.g. Anthropic Claude, `openai/gpt-4o`, Gemma) |
| Mock | `MockOracle` | deterministic test stub |

`remora/oracles/factory.py` assembles diverse swarms (mixing providers/families
to reduce correlated failure). `remora/oracles/diversity.py` provides
`OracleDiversityTracker`, which accumulates pairwise agreement history so the
engine can select the most historically-diverse oracles and down-weight
correlated pairs. OpenAI-family models are reachable through the OpenRouter
backend; there is no standalone OpenAI oracle class.

---

## 7. Genome hyperparameters

`remora/genome.py::Genome` is the evolvable hyperparameter bundle for a single
REMORA run. Current defaults:

| Parameter | Default | Effect |
|---|---|---|
| `max_iterations` | 4 | max oracle sweeps per sub-question |
| `max_subquestions` | 2 | decomposition breadth |
| `converged_threshold` | **0.75** | weighted support needed for early exit |
| `entropy_abort_ratio` | 1.3 | ε tolerance for V increase before abort |
| `negation_weight` | 0.4 | λ, dissensus contribution to the Lyapunov value |
| `thermo_lambda` | 0.4 | dissensus weight in the consensus-phase metric |
| `divergent_boost` | 0.5 | boost applied to divergence signal |
| `negation_ratio` | 0.25 | fraction of iterations using negation prompts |
| `decomposition_strategy` | `"simple"` | question-splitting strategy |
| `early_exit_on_convergence` | `True` | allow early exit once converged |
| `enable_routing` | `False` | pre-sweep router gate disabled by default |
| `router_mode` | `RouterMode.BALANCED` | router threshold strategy (STRICT/BALANCED/HYBRID) |
| `router_confidence_min` | 0.80 | min avg confidence for HYBRID to skip |
| `enable_thermodynamic_control` | `False` | experimental disagreement-metric pre-router |
| `trust_threshold_high` | 0.45 | consensus high-trust bound |
| `trust_threshold_low` | 0.08 | consensus low-trust bound |
| `hallucination_threshold` | 0.05 | candidate hallucination-bound proxy |
| `enable_cascade` | `False` | enable the cascade pipeline (§5.1) |
| `cascade_fast_threshold` | 0.90 | Stage 1 verbalized-confidence accept |
| `cascade_consensus_accept_threshold` | 0.65 | Stage 2 accept |
| `cascade_consensus_abstain_threshold` | 0.12 | Stage 2 abstain |
| `cascade_verify_threshold` | 0.70 | Stage 3 judge accept |
| `cascade_sc_samples` | 7 | Stage 4 self-consistency samples |
| `cascade_sc_threshold` | 0.72 | Stage 4 agreement accept |
| `cascade_max_stages` | 4 | stage cap |
| `cascade_critique_max_rounds` | 2 | Stage 3b rounds |
| `enable_conformal_guardrail` | `False` | split-conformal accept/verify/abstain |
| `conformal_target_risk` | 0.05 | target empirical risk |
| `enable_evidence_v2` | `False` | source-anchored evidence oracle |
| `evidence_v2_min_reliability` | 0.5 | min source reliability |
| `evidence_v2_min_support` | 2 | min supporting claims to answer |
| `enable_semantic_claim_graph` | `False` | claim-graph topology metrics |
| `enable_assurance_trace` | `False` | Merkle-anchored audit trace |
| `enable_counterfactual_v2` | `False` | claim-type-aware counterfactual test |
| `enable_parallel_fanout` | `True` | fan oracle calls out in parallel |

`LyapunovParams` (`remora/lyapunov.py`) defaults:

| Parameter | Default | Meaning |
|---|---|---|
| `lambda_dissensus` | 1.0 | dissensus weight in V = H + λ·D (+ μ·cost) |
| `mu_cost` | 0.0 | cumulative-cost weight |
| `epsilon_tolerance` | 0.05 | ΔV tolerance before the abort gate fires |
| `min_window` | 2 | warm-up steps before stability is measured |

Note: the engine wires the running controller from Genome fields
(`remora/engine.py`), so a live consensus run uses `lambda_dissensus =
negation_weight` (0.4) and an epsilon derived from `entropy_abort_ratio`; the
values above are the `LyapunovParams` dataclass defaults.

---

## 8. The critical-phase inversion (why routing is phase-aware)

In the hardest ("critical") cases, the trust score **anti-correlates** with
correctness, low-trust items were more often correct than high-trust ones (a
trust inversion, N=32 critical items total; small sample, published as a negative
result). A naive conformal guardrail at a 5% risk target collapses to 100%
observed risk / 0 coverage in this regime. REMORA does not trust the score here;
`PhaseAwareGuardrail` **inverts** the selection score for the critical phase and
routes around the inversion rather than through it. This is the concrete reason
selective routing is phase-aware rather than a single global threshold. See
`docs/02-evidence-and-claims.md` §3 and `NEGATIVE_RESULTS.md`.

---

## 9. Module Stability Index

| Module | Stability | Notes |
|--------|-----------|-------|
| `remora/core.py` | **CORE** | Oracle ABC + OracleResponse |
| `remora/errors.py` | **CORE** | Runtime exception taxonomy root: `RemoraError` with machine-readable `code`/`category` (issue #45 gap 4). Separate from the SDK's client-side hierarchy by design |
| `remora/engine.py` | **EXPERIMENTAL** | Multi-oracle consensus engine behind the `/v1/assess` research surface. Reclassified from CORE 2026-08-26 when the #389 paper reframe fired the gate in [ADR-canonical-decision-engine](docs/architecture/ADR-canonical-decision-engine.md): the policy core is the canonical engine, this one is a maintained research instrument, frozen in responsibility — it never gates enforcement |
| `remora/reporting.py` | **CORE** | Decision report + `DecisionEnvelope` assembly (dependency-injected; split from `engine.py` 2026-07-29) |
| `remora/state.py` | **CORE** | `RemoraState` engine session-state contract (re-exported via `remora.engine`) |
| `remora/genome.py` | **CORE** | Hyperparameter configuration |
| `remora/policy/` | **CORE** | PolicyObservation → DecisionReport pipeline (hard-block-first) |
| `remora/adapters/` | **CORE** | LangGraph, OpenAI, MCP adapters |
| `remora/governance/` | **CORE** | DecisionEnvelope v2 + AuditBlock |
| `remora/safety/` | **CORE** | Adversarial firewall, AST guard |
| `remora/audit/` | **CORE** | SHA-256 hash-chain (tamper-evident) |
| `remora/enforcement/` | **CORE** | PolicyDecisionToken + EnforcementGate + ExecutionLease/PEP (REM-013/024/034/035) |
| `remora/governance/lifecycle.py` | **CORE** | Execution lifecycle model + tracker, loaded from `schemas/execution_lifecycle_v1.yaml` (FT-01). CORE is a *maturity* rating: like everything outside `remora.sdk`, this module carries no external backward-compatibility guarantee — see [docs/sdk.md](docs/sdk.md) |
| `remora/enforcement/outbox.py` | **CORE** | Crash-consistent dispatch-intent store, in-process + SQLite + Postgres adapters (FT-02). Same stability caveat as above |
| `remora/selective/` | **CORE** | Conformal / CRC / PhaseAwareGuardrail |
| `remora/persistence/` | **CORE** | Oracle response cache (package root) + `execution_state.py` review-state transaction adapter (issue #241 slice 2) |
| `remora/execution/` | **CORE** | `authorization.py`: ToolSpec bundle verification + assessed-record read-back (issue #241 slice 3; no HTTP knowledge) |
| `remora/legal/` | **CORE** | `CitationExistence`: citation existence is an authoritative-registry fact; model consensus is advisory only |
| `servers/execution_api.py` | **CORE** | `/v1/execution/*` routes + orchestration (decomposition in progress, issue #241) |
| `servers/execution_contracts.py` | **CORE** | Pydantic wire models for `/v1/execution/*` (issue #241 slice 1) |
| `remora/lyapunov.py` | **EXPERIMENTAL** | Session-stability observable over consensus iteration (legacy module name; the thermodynamic framing is withdrawn, NEGATIVE_RESULTS §38) |
| `remora/thermodynamics.py` | **EXPERIMENTAL** | Uncertainty-routing proxy (legacy naming; framing withdrawn, NEGATIVE_RESULTS §38 — the field names are wire format and stay) |
| `remora/causal/intervention.py` | **EXPERIMENTAL** | Do-calculus causal stress testing |
| `remora/topology.py` | **EXPERIMENTAL** | Topological Data Analysis (TDA) |
| `remora/cascade/` | **EXPERIMENTAL** | Multi-stage cascade pipeline |
| `remora/aromer/` | **EXPERIMENTAL** | AROMER meta-learning loop (shadow-only) |
| `remora/causal/` | **EXPERIMENTAL** | Causal PS/PN scoring and concept attribution |
| `remora/evidence/` | **EXPERIMENTAL** | Evidence providers (RAG/cyber/proxy); some fail-open paths, see issue tracker |
| `remora/uncertainty/` | **EXPERIMENTAL** | Epistemic/aleatoric decomposition (normalization caveats documented) |
| `remora/graph/` | **EXPERIMENTAL** | Semantic claim-graph β1 / contradiction cycles |
| `remora/knowledge_domains/` | **EXPERIMENTAL** | Multi-tenant scoping + cost routing (research fixtures) |
| `remora/governance_intelligence/` | **EXPERIMENTAL** | Pre-policy enrichment (self-labelled research-grade) |
| `remora/sdk/` | **STABLE** | The only namespace with an external backward-compatibility guarantee. Snapshot-gated against `artifacts/sdk/public_api_v1.json` and re-checked against the installed wheel in CI |
| `remora/observability/` | **CORE** | OTel tracer (degrades to a documented no-op) + structured governance events |
| `remora/toolcall/` | **EXPERIMENTAL** | Tool-call routing, semantic contracts and the benchmark harnesses |
| `remora/shadow/` | **EXPERIMENTAL** | Counterfactual replay of an agent action log |
| `remora/integrations/` | **EXPERIMENTAL** | Outbound integrations (GO-STAR MCP bridge) |
| `remora/assess.py` | **CORE** | One-call tool-call assessment (the library form of `remora assess`) |
| `remora/credal.py` | **CORE** | Credal risk envelope consumed by the decision engine |
| `remora/calibration/`, `remora/confidence/` | **EXPERIMENTAL** | Trust calibration and confidence scoring |
| `remora/verifier/`, `remora/oracles/` | **EXPERIMENTAL** | Oracle backends and verification stages for the `/v1/assess` surface |
| `remora/cli.py`, `remora/__main__.py` | **CORE** | The `remora` command: assess, doctor, verify, demo |
| `remora/canonical.py`, `remora/action_semantics.py` | **CORE** | Canonical hashing and action-semantics vocabulary used by the binding hashes |
| `remora/provenance.py` | **CORE** | Build/commit provenance stamped into result artifacts |
| `remora/agent_hook/` | **EXPERIMENTAL** | Cross-call session tracking for the agent hook and MCP surface |
| `remora/assurance/` | **EXPERIMENTAL** | Assurance trace and stability markers |
| `remora/audit_gates/` | **EXPERIMENTAL** | Gate definitions used by the claim-audit tooling |
| `remora/benchmarks/` | **EXPERIMENTAL** | Deterministic benchmark corpora and scoring harnesses |
| `remora/adaptation/` | **EXPERIMENTAL** | Adaptive threshold/bandit research; reachable only from AROMER |
| `remora/semantic_entropy.py` | **EXPERIMENTAL** | Semantic entropy after Kuhn et al. 2023 (prior art, not a physics metaphor); NLI-backend parity is CI-gated |
| `remora/correlation.py`, `remora/counterfactual.py`, `remora/scoring.py`, `remora/layers.py`, `remora/stability.py`, `remora/phase_controller.py` | **EXPERIMENTAL** | Research helpers for the `/v1/assess` surface |
| `remora/research_attic/` | **RESEARCH_ONLY** | Retained research modules with no production importer; `tests/test_research_attic_isolation.py` refuses one |

> **Backwards compatibility:** `remora.sdk` is the only surface with an
> external guarantee. CORE is a *maturity* rating, not a BC promise: those
> modules are load-bearing and well covered, but callers outside this
> repository should import through `remora.sdk`. EXPERIMENTAL APIs may change
> in minor releases. RESEARCH_ONLY modules carry no BC guarantee and are not
> production-certified.
>
> This table is machine-checked by `tests/test_module_stability_index.py`:
> every path listed must exist, and every top-level module under `remora/`
> must be classified. It previously listed two directories that no longer
> existed and omitted `remora/sdk/` — the stable surface — entirely.

---

## 10. Scope and maturity

REMORA is a **research-grade reference architecture**, not a certified product,
not a guarantee of safety, and not a replacement for domain authority.

- **Deployment status: SHADOW_ONLY.** The system is intended to be run beside an
  agent (Shadow Mode) and does not have a production-certified enforcement mode.
- **Production gates:** `REM-020` (longitudinal stability) is **DONE**
  (2026-07-17, closed by fail-closed tooling under the owner-reconciled 7-day
  criterion; self-reported values pending independent verification).
  `REM-022` (RBAC audit) is **DONE** (2026-06-30, with a recorded deviation
  whose follow-through is tracked as `REM-023`, still **IN_PROGRESS**).
  `REM-021` (independent human review) is **NOT_STARTED** and blocks exit from
  shadow mode. Statuses are held in
  [`remediation_register.yaml`](docs/assurance/remediation_register.yaml), which
  is what CI recomputes the README's deployment profile from.
  Deployment status cannot advance past SHADOW_ONLY until REM-021 is cleared.
- **External replication is pending.** All benchmarks are internally run; no
  external live-agent validation has been conducted.
- **Result scope:** reported results are simulator-scoped or post-hoc over
  committed artifacts where noted (the 0% unsafe-execution result is a
  deterministic simulator; the selective-accuracy hold-out accepted **18**
  items, so its Wilson CI is wide, [82.4%, 100.0%]; quote the CI, not the
  point estimate). That hold-out (CLAIM-004) is now **superseded** by CLAIM-012:
  the signal it ranked on failed its pre-registered fresh-data confirmation. See
  [`docs/assurance/superseded_claims.md`](docs/assurance/superseded_claims.md).
  The historically-labelled "N500" selective-prediction artifact currently has
  **544 evaluable items** ("N500" is a legacy name, not the item count).
- **Semantic-entropy caveat:** the reported headline numbers use a
  **token-fingerprint heuristic** (sorted SHA-256 tokens), **not** the NLI-based
  Semantic Entropy backend. The NLI backend exists as a drop-in but was not used
  for any reported result. State this plainly whenever the uncertainty numbers
  are quoted.

Full claim → evidence → artifact → caveat map: `docs/02-evidence-and-claims.md`.
Negative results: `NEGATIVE_RESULTS.md`.

---

## 11. Evolution

REMORA began as a multi-oracle consensus research system for claim verification.
The current architecture generalizes that consensus core into a **governance
overlay for agent actions**; the full history is in git.

---

*Document scope: this document describes the current governance architecture. It
is the canonical architecture reference for this repository.*

*Author: Stian Skogbrott, https://github.com/darklordVirtual/REMORA*
