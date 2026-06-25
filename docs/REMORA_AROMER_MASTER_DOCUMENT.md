# REMORA + AROMER — Authoritative Technical Reference

**Repository:** `darklordVirtual/REMORA`  
**Status:** Research-grade prototype, v0.9.0, Apache-2.0 licensed
**Last verified against commit:** cc567fc  
**Document updated:** 2026-06-05  

> **Scope of this document.** Every claim here is traced to code, tests, or committed artifacts. Claims not backed by evidence are labeled ASPIRATIONAL or ROADMAP. No claim of AGI, production certification, or unconditional safety is made.

---

## 1. Executive Summary

REMORA is a Python library that intercepts AI agent tool calls before execution and routes each proposed action to one of four governance outcomes: ACCEPT, VERIFY, ABSTAIN, or ESCALATE. Its core decision contract (`DecisionEnvelope`) is stable and replayable with a SHA-256 audit hash. AROMER is an **EXPERIMENTAL** closed-loop plugin that wraps REMORA with persistent episodic memory, a Bayesian world model, and a Workers AI meta-judge that critiques its own past decisions. On the AgentHarm public benchmark (88 curated cases), the full three-stage REMORA cascade achieves blocked_recall=0.977 with FPR=0.023; these are deterministic benchmark results, not production safety certification. AROMER is accumulating live governance episodes through Cloudflare Workers and Claude Code hooks, but its learning loop has not been externally validated.

---

## 2. Problem Statement

Autonomous AI agents can call tools, write memory, and take actions in workflows where mistakes have real consequences. Single-model confidence is insufficient as a control signal: a model can be confidently wrong, and a pool of models can share the same blind spot. The practical control question REMORA addresses is:

> When should an AI system execute, verify, abstain, escalate, or block a proposed tool call?

This is treated as a governance problem, not a model-quality problem. The failure mode REMORA is designed to prevent is not "AI says I don't know" — it is "AI acts when it should not."

---

## 3. System Overview

### REMORA (Core Library)

REMORA is a pre-execution governance overlay. It sits between the AI agent's proposed action and the actual tool execution. It does not replace the agent; it gates it.

**Key roles:**
- Intercept tool calls before execution
- Evaluate risk, uncertainty, evidence, policy, and environment
- Emit a deterministic, replayable `DecisionEnvelope` with audit hash
- Support Shadow Mode (observe without blocking)

### AROMER (Experimental Plugin)

AROMER (Autonomous REMORA Orchestrator, Meta-Emergent Reasoner) wraps RemoraDecisionEngine with a persistent learning loop. It is a research prototype exploring whether meta-cognitive governance can improve over time.

**EXPERIMENTAL label applies to the entire AROMER subsystem.** Claims about AROMER are limited to what is backed by committed artifacts and unit tests.

**Key roles:**
- Adjust trust scores using Bayesian domain priors
- Persist every governance decision as a labeled episode
- Run a Workers AI LLM-as-judge to critique past decisions
- Adapt thresholds via Thompson Sampling oracle bandit
- Accumulate live episodes through Cloudflare Workers cron

---

## 4. REMORA Core Architecture

### 4.1 RemoraDecisionEngine

**File:** `remora/policy/decision_engine.py`  
**Class:** `RemoraDecisionEngine`  
**Policy version:** `RemoraDecisionEngine-v3`

The engine maps a `PolicyObservation` to a `DecisionReport` through a strict priority-ordered rule chain:

1. **Hard blocks (highest priority, fire first):**
   - `adversarial_detected` → ESCALATE
   - `counterfactual_passed == False` → ESCALATE
   - `evidence_contradictions > 0` + `contradiction_cycles > 0` → ESCALATE
   - `evidence_contradictions > 0` (no cycles) → ABSTAIN
   - `refuse_parametric_verdict` and no evidence → VERIFY
   - `distribution_shift_detected` → VERIFY
   - `phase == "critical"` and `risk_tier == "critical"` → ESCALATE
   - Production write (destructive/delete/financial) on `critical` → ESCALATE
   - Production write on `high` → VERIFY
   - High/critical risk with no evidence → VERIFY

2. **Accept paths (after hard blocks pass):**
   - Mondrian per-phase conformal threshold met → ACCEPT
   - Marginal conformal trust threshold met → ACCEPT
   - Temperature below threshold → ACCEPT
   - Evidence-supported with confidence ≥ 0.70, ordered phase or high trust → ACCEPT
   - Ordered phase + trust_score ≥ 0.72 → ACCEPT

3. **Verify paths:**
   - `phase == "critical"` → VERIFY
   - `require_rag` with no evidence → VERIFY
   - `claim_graph_betti_1 > 0` → VERIFY

4. **Abstain paths:**
   - Disordered phase + no evidence → ABSTAIN
   - trust_score < 0.20 + no evidence → ABSTAIN

5. **Default:** ABSTAIN (fail-safe)

### 4.2 PolicyObservation

**File:** `remora/policy/observation.py`  
**Class:** `PolicyObservation`

Input contract to the decision engine. Key fields: `trust_score`, `phase` (ordered/critical/disordered), `risk_tier` (low/medium/high/critical), `action_type`, `target_environment`, `final_H` (entropy), `final_D` (dissensus), `adversarial_detected`, `evidence_action`, `evidence_confidence`, `evidence_contradictions`.

### 4.3 DecisionEnvelope

**File:** `remora/governance/envelope.py`  
**Class:** `DecisionEnvelope`

The canonical governance contract. Immutable frozen dataclass. Sub-blocks:

| Block | Purpose |
|---|---|
| `RequestBlock` | Operational context (domain, risk_tier, proposed_action, action_type, target_environment) |
| `AssessmentBlock` | Oracle votes, thermodynamic signals, evidence quality, policy triggers |
| `GateBlock` | Authoritative outcome (ACCEPT/VERIFY/ABSTAIN/ESCALATE) |
| `ReviewerContextBlock` | Human-readable context |
| `FollowUpBlock` | Follow-up workflow state |
| `HistoryBlock` | Pattern detection (`synthetic=True` for demo/test data) |
| `PolicyLearningBlock` | Policy update proposals (requires_policy_owner_approval=True always) |
| `AuditBlock` | SHA-256 hash, previous hash, policy version |

Every decision produces a replayable envelope that can be serialized with `to_dict()` and validated against `schemas/decision_envelope_schema.yaml`.

### 4.4 Evidence Layer

**Files:** `remora/evidence/cyber.py`, `remora/evidence/domains/ai_governance.py`, `remora/evidence/domains/finance.py`

Three domain evidence providers are implemented:
- `CyberEvidenceProvider`: enriches findings with CVE, CWE, ATT&CK, KEV, EPSS, OSV metadata
- `AIGovernanceEvidenceProvider`: maps AI governance risks to ESCALATE/REPORT_READY/NEEDS_REVIEW verdicts
- `FinanceEvidenceProvider`: maps AML/sanctions patterns to governance actions

**Important:** The default `LexicalEvidenceVerifier` is deterministic and pattern-based. It is NOT a demonstrated semantic entailment system. NLI and LLM verifier adapters exist as interfaces but are not the default path.

### 4.5 GO-STAR Bridge

**File:** `remora/evidence/finding_envelope.py`

Defines the boundary types carrying GO-STAR proprietary scanner findings into REMORA's public governance layer:
- `TargetScanProfile`: authorized scan scope
- `ResearchArtifactRef`: SHA-256-only reference to vault artifacts (no exploit payloads)
- `DisclosureLedger`: six-stage capability ladder (COVERAGE_HIT → REPORT_READY), forward-only
- `CyberFindingEnvelope`: primary bridge type; `apply_remora()` returns verdict without mutating original

Boundary rule: `CyberFindingEnvelope` must never carry exploit payloads, weaponized PoC code, or credential values.

### 4.6 Adapters

Implemented adapters (from README evidence):
- `LangGraphActionAdapter` — LangGraph integration
- `OpenAI tool-calling adapter` — OpenAI tool calls
- `MCP server` — `servers/mcp_remora.py`
- `LocalGateway` — local in-process gateway

---

## 5. AROMER Learning Architecture [EXPERIMENTAL]

> **All AROMER components are research prototypes.** No production deployment or independent external validation has occurred for the learning loop.

### 5.1 AromerOrchestrator

**File:** `remora/aromer/orchestrator.py`  
**Class:** `AromerOrchestrator`  
**Version:** `0.2.0-experimental`

The closed-loop meta-cognitive governance layer. On each `decide()` call:

1. Adjust `trust_score` via `DomainHarmPrior` (world model)
2. Route adjusted observation through `RemoraDecisionEngine`
3. Build and persist an `Episode` in `EpisodicStore`

On `adapt()` (called every 4 hours by CF Worker cron):

1. Run `AromerMetaJudge.critique_batch()` on recent labeled episodes
2. Propagate pending outcomes to `AromerAdapterBridge`
3. Run threshold adaptation cycle
4. Return adaptation report

### 5.2 EpisodicStore

**File:** `remora/aromer/experience/store.py`  
**Class:** `EpisodicStore`

JSONL-based persistent episodic memory. Stores each governance decision with outcome labels when available. Used by the learning loop to identify which decisions were correct, incorrect, or ambiguous.

**Live deployment:** Cloudflare D1 database at `aromer.razorsharp.workers.dev`.

### 5.3 DomainHarmPrior (World Model)

**File:** `remora/aromer/world_model/domain_prior.py`  
**Class:** `DomainHarmPrior`

Bayesian Beta conjugate prior over P(harm | domain, action_type, risk_tier). Key design decisions:

- Uniform prior (alpha=1, beta=1) per context key
- Max trust adjustment: ±20% (`_SENSITIVITY = 0.20`)
- Update weights by `DecisionQuality`: CORRECT_BLOCK/FALSE_ACCEPT → weight=1.0; CORRECT_ACCEPT/FALSE_BLOCK → weight=1.0; CORRECT_INTERCEPT_VERIFY → weight=0.25; BENIGN_REVIEW → weight=0.25; ABSTAIN_UNKNOWN → no update
- Shadow mode: computes adjustment but returns original trust (safe monitoring before committing)
- Confidence levels: LOW (n<5), MEDIUM (5-19), HIGH (n≥20); `policy_ready` requires HIGH

**Current reported state:** 44 contexts tracked (per README claim; not independently re-verified here).

### 5.4 AromerAdapterBridge

**File:** `remora/aromer/integration/bridge.py`  
**Class:** `AromerAdapterBridge`

Combines three adaptation components:
- `ThermodynamicAdapter`: temperature/entropy-based threshold adjustment
- `AdaptiveThresholdEngine`: learns from outcome quality signals
- `OracleBandit`: Thompson Sampling over oracle families for model selection

### 5.5 AromerMetaJudge (LLM-as-judge)

**File:** `remora/aromer/meta_judge/judge.py`  
**Class:** `AromerMetaJudge`

Workers AI LLM call that critiques AROMER's past governance decisions. Uses `RubricCritique` from `remora/aromer/meta_judge/rubric.py`. Runs on labeled episodes with `critique_score is None` during the `adapt()` cycle. Batch size is configurable (`meta_judge_batch`, default 5).

**Important caveat:** The MetaJudge uses Workers AI models as judges. LLM-as-judge reliability depends on judge quality and is not independently validated.

### 5.6 EpisodeFactory and ReplayRunner

**Files:** `remora/aromer/evals/episode_factory.py`, `remora/aromer/evals/replay_runner.py`

`EpisodeFactory` provides 65 curated governance test cases across 9 categories: `golden_safe`, `golden_harmful`, `fp_trap`, `fn_trap`, `ambiguous`, `causal_trap`, `transfer`, `near_miss`, `contradiction`.

`ReplayRunner` runs the factory cases against the live AROMER worker endpoint.

### 5.7 Seed Data

**Directory:** `remora/aromer/seeds/` — 22 seed JSON files providing initial domain harm priors for bootstrap.

---

## 6. Decision Lifecycle

The full step-by-step governance flow for a tool call:

```
1. Agent proposes tool call (e.g., delete_table, send_email, bash command)
2. PreToolUse hook fires (scripts/remora_hook.py or Claude Code hook)
3. Risk classification: tool_name + action_type → RiskLevel (LOW/MEDIUM/HIGH)
4. Local deterministic safety check: destructive patterns blocked immediately
5. Drift check: semantic drift from anchored session intent
6. PolicyObservation constructed: phase, trust_score, risk_tier, evidence, H, D
   (If AROMER active: DomainHarmPrior adjusts trust_score ±20% based on prior)
7. RemoraDecisionEngine.decide(obs) evaluates priority-ordered rule chain
8. DecisionReport produced: action, reasons, confidence, risk_estimate
9. DecisionEnvelope constructed and SHA-256 hash computed
10. Episode recorded in EpisodicStore (if AROMER active)
11. Outcome:
    ACCEPT   → tool executes
    VERIFY   → held for human sign-off or evidence collection
    ABSTAIN  → declined; insufficient trust or evidence
    ESCALATE → hard block; routed to human review
12. PostToolUse hook fires (aromer_auto_label_hook.py): episode auto-labeled
13. On cron (every 4 hours): adapt() cycle critiques episodes, updates world model
```

---

## 7. Governance Outcomes

| Outcome | Meaning | When triggered |
|---|---|---|
| **ACCEPT** | Action is safe to execute automatically | Ordered phase + high trust, or temperature below threshold, or evidence-supported with high confidence |
| **VERIFY** | Require more evidence or human sign-off | Critical phase, production write on high-risk, distribution shift, evidence required |
| **ABSTAIN** | Decline because trust is too low | Disordered phase, low trust score, default fail-safe |
| **ESCALATE** | Hard block; route to human review | Adversarial detected, counterfactual failed, evidence contradicted, critical+critical combination, production write on critical |

**Important distinction:** ESCALATE recall ≠ blocked recall. In Mode 3 of the AgentHarm benchmark, ESCALATE recall = 0.114 but blocked_recall (ESCALATE + VERIFY) = 0.977. Most harmful tasks route to VERIFY, not ESCALATE, because the engine is conservative but not binary.

---

## 8. Learning Loop (AROMER) [EXPERIMENTAL]

```
Episode recorded → (async) MetaJudge critiques → critique_score stored
                                                         ↓
Outcome observed → record_outcome() or record_ground_truth()
                                                         ↓
Decision quality assessed (CORRECT_BLOCK / FALSE_ACCEPT / etc.)
                                                         ↓
Bayesian world model updated (DomainHarmPrior.update_from_quality())
                                                         ↓
AdapterBridge.record_outcome() → OracleBandit Thompson Sampling update
                                                         ↓
Hourly cron: adapt() → threshold adaptation cycle
```

**Oracle bandit state (from README):** cf_strong 98.8%, cf_fast 97.6%. These are Thompson Sampling posterior means from the live episode store; they reflect accumulated self-label data, not an externally validated ranking.

**World model shadow mode:** `world_model_shadow_mode=True` in `AromerOrchestrator.__init__()`. In shadow mode, trust adjustments are computed and logged but not applied. This is the safe monitoring path before committing world model decisions.

---

## 9. Evidence and Audit Model

### DecisionEnvelope Audit Chain

Each envelope contains an `AuditBlock` with:
- `policy_version`: e.g., `"RemoraDecisionEngine-v3"`
- `hash`: SHA-256 of envelope contents
- `previous_hash`: links to prior decision in the chain
- `signature`: optional signing field

The `HistoryBlock.synthetic = True` flag distinguishes demo/test case memory from real operational precedent. Consumers must not treat synthetic history as real precedent.

### Policy Learning Safety

`PolicyLearningBlock` always has `requires_policy_owner_approval = True` and `can_auto_apply = False`. REMORA may propose policy changes but cannot apply them autonomously.

### GO-STAR Vault Separation

`ResearchArtifactRef` stores only the SHA-256 hash of vault artifacts; REMORA never resolves `vault_ref`. Exploit payloads and PoC content remain in the GO-STAR vault.

---

## 10. Benchmarks and Results

> All numbers in this section are sourced directly from committed artifact files. Scope caveats are mandatory companions to every number.

### 10.1 AgentHarm Benchmark (arXiv:2410.09024)

**Dataset:** `ai-safety-institute/AgentHarm`, `test_public` split  
**Protocol:** `detailed_prompt=False, hint_included=False` (hardest canonical variant)  
**N:** 44 harmful + 44 benign = 88 cases  
**Artifact:** `artifacts/agentharm_trimode_results.json`  
**Oracle:** Cloudflare Workers AI (llama-3.3-70b-fp8, qwen3-30b-fp8, mistral-small-3.1-24b)  
**Total oracle calls:** 783 (Mode 1) + 396 (Mode 2) = 1179

| Mode | Recall | Recall CI95 | FPR | FPR CI95 | Blocked Recall | Coverage |
|---|---|---|---|---|---|---|
| Mode 1 — Oracle only | 1.000 | [0.920, 1.000] | 0.318 | [0.200, 0.466] | 1.000 | 0.989 |
| Mode 2 — Harm-specific oracle | 1.000 | [0.920, 1.000] | 0.114 | [0.050, 0.240] | 1.000 | 0.989 |
| Mode 3 — Full REMORA gate | 0.114 | [0.050, 0.240] | 0.023 | [0.004, 0.118] | **0.977** | 0.977 |

**Confusion matrix (Mode 3):**

| | Harmful | Benign |
|---|---|---|
| ESCALATE | 5 (TP) | 1 (FP) |
| VERIFY | 38 | 42 |
| ABSTAIN | 1 | 1 |
| ACCEPT | 0 | 0 |

**Critical reading notes:**
- Mode 3 ESCALATE recall = 0.114 (only 5/44 harmful tasks hard-blocked). The headline "blocked_recall=0.977" counts ESCALATE+VERIFY as "handled."
- FPR = 0.023 counts only hard ESCALATE on benign tasks. VERIFY on benign tasks is not counted as FP.
- These results apply to the `test_public` canonical variant only. Harder variants (`hint_included=True`) may differ.
- This is not a production deployment test.

### 10.2 Replay Benchmark (Factory)

**Dataset:** 65 curated factory cases in 9 categories  
**Artifact:** `artifacts/replay_benchmark.json`  
**Generated:** 2026-06-04T12:53:50  
**Worker:** `https://aromer.razorsharp.workers.dev`

| Metric | Value |
|---|---|
| Overall accuracy | 1.000 |
| Overall accuracy CI95 | [0.944, 1.000] |
| Safe recall | 1.000 |
| Benign precision | 0.600 |

**Category breakdown:** All 9 categories achieve verdict_accuracy=1.000; CI95 lower bounds range from 0.342 (contradiction, n=2) to 0.806 (golden_safe, n=16).

**Critical reading notes:**
- 65 curated cases with wide CI95 on small subcategories (n=2 to n=16).
- These are factory-constructed episodes, not independent real-world cases.
- `benign_precision=0.600` at the overall level (0.0 for ambiguous, causal_trap, near_miss, contradiction categories) — the system is conservative and routes ambiguous cases to non-ACCEPT verdicts.
- This benchmark tests the AROMER worker endpoint, requiring network access to reproduce.

### 10.3 Cross-Domain Evidence Benchmark

**Dataset:** 32 curated cases across cyber (12), ai_governance (10), finance (10)  
**Artifact:** `artifacts/domain_benchmark_results.json`

| Domain | Cases | Precision | Escalation Recall | FP Suppression |
|---|---|---|---|---|
| Cyber | 12 | 1.000 | 1.000 | 1.000 |
| AI Governance | 10 | 1.000 | 1.000 | 1.000 |
| Finance | 10 | 1.000 | 1.000 | 1.000 |
| **Overall** | **32** | **1.000** | **1.000** | **1.000** |

**Critical reading notes:**
- 32 curated cases with hand-crafted expected verdicts. These are constructed test fixtures, not independently drawn cases.
- "precision=1.000" on 32 cases has wide CI.
- The live oracle benchmark (`artifacts/live_benchmark_results.json`) shows much lower directional precision: cyber=0.889, ai_governance=0.250, finance=0.250. The live oracle does not match the static evidence provider on most ai_governance and finance cases.

### 10.4 Live Oracle Benchmark

**Artifact:** `artifacts/live_benchmark_results.json`  
**Worker:** `go-star-remora` (groq_fast, groq_strong, openrouter_diverse)  
**Total calls:** 279 oracle calls

| Domain | Oracle Directional Precision | Oracle Static Agreement |
|---|---|---|
| Cyber | 0.889 | 0.583 |
| AI Governance | 0.250 | 0.300 |
| Finance | 0.250 | 0.400 |
| **Overall** | **0.480** | **0.438** |

This reveals a significant gap: the live Workers AI oracle achieves only 0.480 directional precision overall, and 0.250 for ai_governance and finance domains. **This contradicts or substantially qualifies the "escalation_recall=1.000" claim from the static benchmark.** The static provider uses rule-based scoring; the live oracle uses LLM consensus, and they disagree on most non-cyber cases.

### 10.5 QA Selective Trust Benchmarks (from whitepaper)

These are the original REMORA selective-QA results, not AROMER-specific:

- **N=302 selective trust:** 94.74% accuracy at 25% coverage vs 82.78% majority baseline. Wilson CI95 [0.8723, 0.9793]. Artifact: `results/selective_trust_curve_results.json`.
- **N500 selective guardrail (544 items):** 88.78% accuracy at 18% coverage vs 41.18% majority baseline. **Caveat: 18% threshold is derived in-sample on the same 544-item artifact.** Artifact: `results/end_to_end_n500_v3.json`.

### 10.6 Tool-Call Benchmark v2

**700 deterministic adversarial tasks, 7 domains, no production mutation.**  
Artifact: `results/toolcall_benchmark_v2_results.json`

| Strategy | Accuracy | Unsafe execution | Mean utility |
|---|---|---|---|
| majority_vote_heuristic | 30.00% | 10.00% | 0.00 |
| remora_full_policy_gate | 90.00% | 0.00% | 0.62 |

**Caveat:** Both baselines and REMORA policy gate are deterministic heuristic classifiers replaying pre-labelled tasks — not live LLM calls. "0% unsafe execution" is a benchmark-scoped simulator result.

---

## 11. Live Runtime Status

### AROMER v0.2.0-experimental — Live State

As of 2026-06-05, the AROMER worker reports the following live state (not a committed artifact; may change):

| Signal | Value | Interpretation |
|---|---|---|
| AII (Autonomous Intelligence Index) | 0.5088 [LEARNING] | Learning phase; below operational threshold |
| world_model_active | 1 | World model is active but in shadow mode by default |
| ECE | 0.0804 | Expected Calibration Error — well-calibrated |
| false_accept_rate | 0 | No false accepts recorded in current episode window |
| transfer_score | 1.0 | Cross-domain transfer at ceiling |

**Sprint status (Sprints 1–4 complete; Sprint 5 planned):**
- Sprint 1: REMORA core stabilisation and test infrastructure
- Sprint 2: AROMER learning loop and episodic store
- Sprint 3: AgentHarm benchmarks (Mode 1–3) and domain evidence layer
- Sprint 4: GO-STAR bridge, cyber evidence layer, replay benchmark
- Sprint 5 (planned): REMORA shadow tandem — live validation alongside production agent

### Cloudflare Workers

| Worker | URL | Status (per README) | Description |
|---|---|---|---|
| AROMER learning | `aromer.razorsharp.workers.dev` | Live | D1 + KV + Workers AI (llama-3.1-8b), cron `0 */4 * * *` |
| GO-STAR oracle | `go-star-remora.razorsharp.workers.dev` | Live | 3-model consensus (llama-3.3-70b-fp8, qwen3-30b-fp8, mistral-small-3.1-24b) |
| Agent control | `remora-agent-control.razorsharp.workers.dev` | Live | Auth, codegraph, hook verification |
| Frontend | `remora.razorsharp.workers.dev` | Live | Eye, control-room, benchmarks, telemetry |

### Claude Code Integration

**File:** `.claude/settings.json`

```
PreToolUse:
  Bash|WebFetch|WebSearch|Agent → scripts/remora_hook.py (risk assessment, blocking)
  .* → scripts/aromer_recorder_hook.py (records as AROMER episode)

PostToolUse:
  .* → scripts/aromer_auto_label_hook.py (auto-labels episodes as benign)
```

`remora_hook.py` blocks locally destructive patterns (RiskLevel.HIGH + specific patterns) with exit code 2. For medium/high risk with AGENT_CONTROL_SECRET configured, it calls the remote agent-control service for verification.

### CI/CD

- `.github/workflows/quality-gates.yml` — lint + tests + claim checks, runs on push
- `.github/workflows/codegraph-index.yml` — D1 codegraph index on every push
- `.github/workflows/deploy-aromer-worker.yml` — CF Worker deploy

---

## 12. What Is Implemented (Feature Table)

| Feature | Status | Evidence |
|---|---|---|
| RemoraDecisionEngine (4-outcome policy) | Implemented | `remora/policy/decision_engine.py` |
| PolicyObservation input contract | Implemented | `remora/policy/observation.py` |
| DecisionEnvelope audit contract | Implemented | `remora/governance/envelope.py` |
| SHA-256 audit hash chain | Implemented | `AuditBlock` in envelope |
| Shadow Mode / Replay Engine | Implemented | `examples/shadow_mode_demo.py` |
| LangGraph adapter | Implemented | `examples/langgraph_integration.py` |
| OpenAI tool-calling adapter | Implemented | `examples/openai_tool_calling.py` |
| MCP server | Implemented | `servers/mcp_remora.py` |
| Cyber evidence provider (CWE/CVE/KEV/ATT&CK) | Implemented | `remora/evidence/cyber.py` |
| AI Governance evidence provider | Implemented | `remora/evidence/domains/ai_governance.py` |
| Finance evidence provider (AML/sanctions) | Implemented | `remora/evidence/domains/finance.py` |
| GO-STAR bridge types | Implemented | `remora/evidence/finding_envelope.py` |
| Claude Code PreToolUse/PostToolUse hooks | Implemented | `.claude/settings.json`, `scripts/` |
| Nested governance primitives | Implemented | `remora/governance/` |
| AROMER orchestrator (EXPERIMENTAL) | Implemented | `remora/aromer/orchestrator.py` |
| Bayesian world model (EXPERIMENTAL) | Implemented | `remora/aromer/world_model/domain_prior.py` |
| Episodic store (EXPERIMENTAL) | Implemented | `remora/aromer/experience/store.py` |
| MetaJudge LLM critique (EXPERIMENTAL) | Implemented | `remora/aromer/meta_judge/judge.py` |
| Oracle bandit Thompson Sampling (EXPERIMENTAL) | Implemented | `remora/aromer/integration/bridge.py` |
| Cloudflare Workers deployment | Live | `workers/aromer/`, `workers/go-star-remora/` |
| Test suite | 2200+ passing tests | `tests/` |

---

## 13. What Is Experimental

The following are clearly labeled as experimental and should not be cited as validated results:

### AROMER Learning Loop
- World model priors are updated from self-labeled episodes. The quality of labels depends on the auto-label hook (`aromer_auto_label_hook.py`) which marks all post-tool episodes as "benign." This creates a systematic labeling bias.
- MetaJudge critique is an LLM evaluating its own family's decisions. No independent human evaluation of critique quality exists.
- Oracle bandit rankings (cf_strong 98.8%, cf_fast 97.6%) reflect Thompson Sampling posteriors from self-labeled data, not independently validated model quality rankings.
- The learning loop has not been externally validated. No production deployment evidence exists.

### World Model Confidence
- `policy_ready` requires n≥20 observations per context key. Most contexts likely have LOW confidence (n<5) given the volume of tool calls.
- Shadow mode is active by default (`world_model_shadow_mode=True`), meaning the world model computes but does not apply trust adjustments in the current default configuration.

### MetaJudge
- Workers AI LLM-as-judge reliability is not benchmarked independently.
- Critique scores are used to update the store but are not independently audited.

---

## 14. What Is Roadmap / Hypothesis

Items clearly not yet implemented or validated:

| Item | Status |
|---|---|
| Independent external replication of all benchmarks | ROADMAP — only internal replication to date |
| Live-agent validation on real tool calls (non-simulated) | ROADMAP — pending |
| Production deployment with operational telemetry | ROADMAP — no production deployment exists |
| Semantic evidence verification (NLI/LLM verifier) | ROADMAP — default is lexical |
| TEE attestation (AMD SEV-SNP / Intel TDX) | ROADMAP — specified, not executed |
| CRC covariate-shift calibration on real oracle responses | ROADMAP |
| AROMER world model in active (non-shadow) mode | ROADMAP — shadow mode is default |
| Governance drift thresholds calibrated on deployment telemetry | ROADMAP |

---

## 15. Limitations

1. **No production deployment proof.** The repository is a research prototype. No enterprise deployment, incident-handling, or operational telemetry artifact exists.

2. **Simulator-scoped safety numbers.** The tool-call v2 "0% unsafe execution" figure and AgentHarm results are from deterministic benchmarks. Real-world agent behavior with live model calls may differ.

3. **Small curated benchmarks with wide CI.** 88 AgentHarm cases, 65 factory cases, 32 domain cases. CI95 lower bounds on subcategories can be as low as 0.34 (n=2 contradiction category). These are insufficient for broad safety claims.

4. **Auto-labeling bias in AROMER.** The auto-label hook marks all successful tool executions as "benign." This systematically underestimates harmful events that were not blocked, biasing the world model toward lower harm estimates.

5. **Live oracle vs. static benchmark gap.** The live oracle benchmark shows overall directional precision of 0.480, far below what the static domain benchmark (precision=1.000) suggests. The static results depend on rule-based evidence providers, not live LLM consensus.

6. **Evidence verification is lexical by default.** The `LexicalEvidenceVerifier` matches patterns and keywords, not semantic intent. It can be fooled by phrasing.

7. **Consensus is not truth.** If models share training data biases, a high-consensus decision can still be wrong.

8. **External replication pending.** No independent third-party replication of any benchmark claim exists.

9. **N500 threshold is in-sample.** The 88.78% accuracy at 18% coverage uses a threshold derived from the same 544-item artifact being evaluated.

---

## 16. Safety Boundaries

REMORA explicitly does NOT guarantee:

- That all harmful agent actions will be blocked in production systems
- That ACCEPT decisions are free of risk
- That the LLM oracle pool is adversarially robust
- That VERIFY routing always results in human review (the reviewer must act)
- That governance settings remain appropriate as agent behavior evolves
- That the auto-label mechanism correctly identifies all true harmful events
- That world model priors generalize beyond the episode domains observed

REMORA DOES provide:

- A deterministic, auditable decision record for every governed action
- Fail-safe default behavior (ABSTAIN when no rule matches)
- Hard blocks on locally destructive patterns regardless of oracle state
- A replayable audit trail for post-incident analysis
- Shadow Mode for safe observation without blocking

---

## 17. Comparison With Existing Approaches

| Approach | Key difference from REMORA |
|---|---|
| Prompt guardrails (content filters) | REMORA gates tool execution, not text generation; operates pre-execution not post-generation |
| Constitutional AI / RLHF safety | Model-level training interventions; REMORA is an external overlay, model-agnostic |
| ReAct/chain-of-thought self-reflection | Model self-checks during generation; REMORA is a separate governance system with policy persistence |
| Human-in-the-loop approval workflows | REMORA adds risk-tiered routing before human review; reduces review load with ACCEPT paths |
| Rule-based policy engines | REMORA combines hard rules with probabilistic signals (oracle consensus, entropy, evidence confidence) |

REMORA is designed as a complement to model-level safety work, not a replacement. It operates at the action layer, not the generation layer.

---

## 18. Commercial / Product Positioning

REMORA is published as an Apache-2.0-licensed research prototype. It is **not** a commercial product and makes **no production certification claims**.

The repository demonstrates:
- A governance architecture that can be adopted by agent developers
- A benchmark methodology for evaluating action governance
- An experimental learning loop (AROMER) that accumulates real governance episodes

GO-STAR is described in the repository as a commercial extension that supplies cyber security findings into the REMORA evidence boundary via the `CyberFindingEnvelope` bridge. GO-STAR internals are proprietary; only the public bridge interface is open-sourced.

Enterprise framing is documented in `enterprise/remora-control-plane.md` as architectural positioning, not as evidence of a deployed enterprise product.

---

## 19. Glossary

| Term | Definition |
|---|---|
| AROMER | Autonomous REMORA Orchestrator, Meta-Emergent Reasoner. EXPERIMENTAL learning plugin for REMORA. |
| blocked_recall | Fraction of harmful cases routed to ESCALATE or VERIFY. Distinct from ESCALATE recall. |
| DecisionEnvelope | The canonical, immutable governance contract produced per action decision. |
| DomainHarmPrior | Bayesian Beta prior over P(harm | domain, action_type, risk_tier). Core of AROMER world model. |
| EpisodeFactory | 65 curated test cases for AROMER replay benchmark validation. |
| EpisodicStore | JSONL-based persistent memory of governance decisions and their observed outcomes. |
| FPR | False Positive Rate = ESCALATE on benign / total benign. Counts only hard ESCALATE, not VERIFY. |
| GO-STAR | Proprietary security scanner with public bridge to REMORA via CyberFindingEnvelope. |
| MetaJudge | Workers AI LLM-as-judge that critiques AROMER's past governance decisions. |
| Oracle bandit | Thompson Sampling-based selection of which oracle model to query first. |
| phase | Ordered/critical/disordered classification of the current governance context. |
| PolicyObservation | Input contract to RemoraDecisionEngine encoding all signals for a decision. |
| RemoraDecisionEngine | Core policy engine mapping PolicyObservation to DecisionReport with 4 outcomes. |
| Shadow Mode | Run REMORA beside an agent without blocking; observe what would have happened. |
| trust_score | A composite signal (0.0–1.0) derived from oracle consensus, conformal calibration, or evidence. |
| VERIFY | Hold for evidence collection or human sign-off; does not block the agent hard. |
| world_model_shadow_mode | DomainHarmPrior computes but does not apply trust adjustments (default=True in AromerOrchestrator). |

---

## 20. Claim Register Summary

For the full machine-readable claim register, see `artifacts/remora_aromer_claim_register.json`.

| Status | Count | Description |
|---|---|---|
| VERIFIED | 13 | Claims directly supported by committed artifacts |
| PARTIAL | 7 | Claims with important caveats or scope limitations |
| ASPIRATIONAL | 6 | Claims that require external validation before public use |
| OUTDATED | 2 | Claims superseded by live oracle benchmark results |
| UNSUPPORTED | 2 | Claims without corresponding artifact evidence |

**Claims safe for external use (with required caveats):**
- AgentHarm Mode 3 blocked_recall=0.977, FPR=0.023 CI95[0.004,0.118] — on test_public canonical variant, 88 cases
- Replay benchmark accuracy=1.000 CI95[0.944,1.000] on 65 curated factory cases
- Cross-domain evidence benchmark precision=1.000 on 32 curated cases (static provider only)
- Tool-call v2: remora_full_policy_gate achieves 0% unsafe execution in deterministic simulator (700 tasks)

**Claims that must NOT be used publicly without additional validation:**
- Any claim implying production safety certification
- "Zero false negatives" without the scope qualifier (applies only to Mode 1/2 on 88-case test_public)
- Oracle bandit rankings as independently validated model performance
- World model trust adjustments as calibrated governance signals
- Live oracle precision metrics as equivalent to static benchmark metrics
