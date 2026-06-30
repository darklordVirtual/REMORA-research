# Research Paper Alignment Analysis
**Date:** 2026-06-30  
**Scope:** REMORA/AROMER alignment with three frontier papers  
**Papers reviewed:**
1. Shamsujjoha et al. (arXiv:2408.02205v2) — Swiss Cheese Model taxonomy of runtime guardrails
2. Ge (arXiv:2603.07191v2) — LGA 4-layer governance architecture for autonomous agent systems
3. Zhang et al. (arXiv:2404.02655v2) — UF Calibration: decomposing LLM confidence into Uncertainty and Fidelity

---

## 1. Paper Summaries

### 1.1 Shamsujjoha et al. 2024 — Swiss Cheese Taxonomy

**Citation:** Md Shamsujjoha, Qinghua Lu, Dehai Zhao, and Liming Zhu. 2024. "A Taxonomy of Multi-Layered Runtime Guardrails for Designing Foundation Model-Based Agents: Swiss Cheese Model for AI Safety by Design." *arXiv preprint arXiv:2408.02205v2*. CSIRO Data61.

**Method:** Systematic Literature Review (SLR), PICOC protocol, 1733 papers screened → 32 selected via 5-QAC quality assessment.

**Core contribution:** A three-category taxonomy for multi-layer runtime guardrails:

**Category 1 — External quality attributes (WHY guardrails):**  
Safety, Security, Privacy, Accuracy (hallucination/misinformation), Fairness, IP Protection, Performance, Cost

**Category 2 — Internal quality attributes (HOW to design):**  
Accuracy, Generalizability, Customizability, Adaptability, Traceability, Portability, Interoperability, Interpretability

**Category 3 — Design options (WHAT choices exist):**
- *Actions:* Block, Filter, Flag, Modify, Validate, Prioritize, Rate Limit, Parallel Calls, Retry, Fall Back, Human Intervention, Defer, Isolate, Simulate, Redundancy, Log
- *Targets:* Prompts, Models, External Data, Non-AI Components, and agent-specific: Goals, Context, Memory, Reasoning, Plans, Actions, Tools, Other Agents, Intermediate Results, Final Results
- *Scopes:* User, Organizational, Industry, System
- *Rules:* Uniform, Priority-enabled, Context-dependent, Soft (flexible) / Hard (non-negotiable)
- *Autonomy:* Automatic vs. Human Intervention
- *Modality:* Single-modal vs. Multimodal
- *Techniques:* Rule-based, ML (narrow / foundation), Hybrid

**Swiss Cheese Model application:** Multiple overlapping defense layers where each has "holes" (weaknesses) but together no single failure propagates. Applied across: input processing → model reasoning → action execution → output generation.

---

### 1.2 Ge 2026 — Layered Governance Architecture (LGA)

**Citation:** Yuxu Ge. 2026. "Governance Architecture for Autonomous Agent Systems: Threats, Framework, and Engineering Practice." *arXiv preprint arXiv:2603.07191v2*. University of York.

**Method:** Framework proposal + empirical evaluation on 1,081-sample bilingual (ZH/EN) benchmark across 3 threat classes and 10 verification conditions.

**Three formalized threat classes:**
- **TC1/TC2 — Agency Abuse:** Direct injection, indirect injection (poisoned documents), RAG poisoning
- **TC3 — Malicious Skill Plugins:** Exfiltration, privilege escalation, persistence, supply-chain execution

**LGA Four-Layer Architecture:**

| Layer | Mechanism | P50 Latency | Notes |
|-------|-----------|-------------|-------|
| L1 | OS-level sandbox (unshare) | 0.95 ms | Physical containment for FN |
| L2 | LLM intent judge: (task, tool_call) → ALLOW/BLOCK | 490–2200 ms | Dominant latency |
| L3 | HMAC-SHA256 capability tokens + JSON schema | <0.02 ms | Zero-trust protocol |
| L4 | Append-only fsync audit log | 4.1 ms | Immutable trail |

**Key empirical results (TC1/TC2, n=457 malicious):**
- Best local model: Qwen2.5-14B — ZH 98.2% IR / 9.7% FPR, EN 98.5% IR / 20.1% FPR
- Best precision: GPT-4o-mini — ZH 93.0% IR / 3.2% FPR, EN 95.4% IR / 12.3% FPR  
- NLI baselines (BART-MNLI, mDeBERTa): <10% IR — insufficient without task-specific tuning
- Local cascade (small Qwen→Qwen2.5-14B): 94.7–95.6% IR, 6.0–9.7% FPR — viable data-sovereign option [⚠️ exact cascade model name unverified — "Qwen3.5-9B" used in earlier notes does not correspond to a known model; verify against paper §4.2]
- TC3 harder: 75–94% IR; covert side-channel attacks partially blend with declared intent

**Critical statistical finding:** At 1% attack prevalence, even GPT-4o-mini (ZH, FPR=3.2%) yields only **22.7% PPV** — 3 out of 4 blocks are false positives. Consequence: Layer 2 must not be the sole gatekeeper; L1 sandbox is the always-on containment boundary.

**Adversarial robustness:** Purpose-built evasion samples reduce IR to 50–63%, with double-negation and authority-injection as hardest attacks.

**End-to-end pipeline:** 96% IR, P50=980ms total (L1+L3+L4 contribute only ∼18ms; LLM judge dominates).

---

### 1.3 Zhang et al. 2024 — UF Calibration

**Citation:** Zhang, M., Huang, M., Shi, R., Guo, L., Peng, C., Yan, P., Zhou, Y., and Qiu, X. 2024. "Calibrating the Confidence of Large Language Models by Eliciting Fidelity." *arXiv preprint arXiv:2404.02655v2*. Fudan University / Meituan.

**Problem:** RLHF-optimized LLMs exhibit systematic overconfidence — expressed confidence scores don't match actual correctness rates. Logit-based methods require T>2.0 (destabilizing outputs); verbalization-based methods biased toward fixed expressions.

**Core contribution: UF Calibration** — decomposes confidence into two orthogonal dimensions:

```
Conf(Q, ai) = (1 − Uncertainty(Q)) × F(ai)
```

**Uncertainty(Q):** Normalized Shannon entropy of K=10 sampled answers:
```
Uncertainty(Q) = −Σ(pi · log pi) / log M     [M = number of candidate answers]
```

**Fidelity F(ai):** Hierarchical fidelity chain via greedy decoding:
1. Replace chosen answer content oi with "All other options are wrong."
2. Re-query model (greedy). If model switches, fidelity is low; repeat until model selects the "wrong" option.
3. Chain: e.g., A→C→D (model prefers A; if A removed, prefers C; etc.)
4. Assign weight τ^i from right-to-left (τ=2 default); normalize.
5. Average fidelity across chains weighted by Psampled.

**Works without logits** (black-box compatible). Requires known candidate answer set — applies to MCQA, classification, preference labeling.

**Key results (LLaMA2-13B-Chat ablation, Table 4 of paper):**
- Best competing method ECE avg: 0.185 (across ARC/MMLU/CSQA/TruthfulQA)
- UF Calibration ECE avg: **0.076** (−59% vs. best baseline)
- Temperature-robust: maintains lowest ECE across all temperatures tested

**Two new calibration metrics proposed:**

*IPR (Inverse Pair Ratio)* — reliability diagram monotonicity:
```
IPR_M = IP / C(K, 2)     [IP = inverse pairs, K = non-empty bins; lower is better]
```

*CE (Confidence Evenness)* — spread of confidence across the full range:
```
CE_M = −Σ(pi · log pi) / log M     [pi = density per bin; higher is better]
```

ECE alone can be gamed (constant base-rate prediction achieves ECE=0 and IPR=0 but CE=0). All three together define "truly well-calibrated" confidence.

**Experiments:** 6 RLHF-LMs (GPT-3.5-Turbo, GPT-4-Turbo, LLaMA2-7B/13B/70B-Chat, Baichuan2-13B-Chat), 4 MCQA datasets, 0-shot setting.

---

## 2. REMORA Alignment Analysis

### 2.1 Swiss Cheese Model — Layer Coverage

REMORA implements multi-layered defense implicitly through:

| REMORA Layer | Swiss Cheese Analog | Coverage |
|---|---|---|
| Stage 1: `remora_hook.py` LOCAL_BLOCK | Input-processing guard | Deterministic, non-negotiable |
| Stage 2: Intent-drift (Jaccard ≥0.75/0.92) | Plan/reasoning guard | Statistical |
| Stage 3–5: GO-STAR oracle pipeline | Model-reasoning guard | Probabilistic, formal CRC |
| AROMER MetaJudge + FrictionOptimizer | Adaptive feedback guard | Self-improving |
| DecisionEnvelope v2 + hash chain | Output / audit guard | Cryptographic |
| Shadow Mode / Replay Engine | Retrospective guard | Counterfactual |

REMORA's layering is **stronger** than what Shamsujjoha et al. study covers — the paper surveys existing systems, while REMORA adds an adaptive learning layer (AROMER) not found in the SLR corpus.

### 2.2 Design Actions — Completeness Check

| Action | REMORA | Status |
|--------|--------|--------|
| Block | Stage 1 LOCAL_BLOCK + Stage 2 BLOCK decision | ✅ Strong |
| Filter | Stage 1 risk classification (LOW fast-path) | ✅ |
| Flag | ESCALATE decision → human review endpoint | ✅ |
| Modify | AROMER FrictionOptimizer adapts thresholds dynamically | ✅ |
| Validate | Full oracle pipeline (FastGate → ConsensusGate → VerifierGate → SelfConsistency) | ✅ Strong |
| Prioritize | Risk tiers (LOW/MEDIUM/HIGH/LOCAL_BLOCK) | ✅ Partial |
| Rate Limit | Not implemented | ❌ Gap |
| Parallel Calls | GO-STAR 3-oracle concurrent ensemble | ✅ |
| Retry | CritiqueRevision loop (max 2 rounds) | ✅ |
| Fall Back | Mode degradation: full REMORA → hard-blocks-only | ✅ |
| Human Intervention | ESCALATE + `/v1/review` endpoint | ✅ |
| Defer | ABSTAIN decision | ✅ |
| Isolate | No process-level isolation | ❌ Gap (see §3.1) |
| Simulate | Shadow Mode / Replay Engine | ✅ Unique |
| Redundancy | 3-oracle ensemble (Thompson bandit ensemble) | ✅ |
| Log | DecisionEnvelope v2 with hash chain, Prometheus | ✅ Strong |

### 2.3 Target Coverage

| Target | REMORA | Status |
|--------|--------|--------|
| Prompts | Phase 1 hook intercepts before tool execution | ✅ |
| Models | Oracle LLM guardrail | ✅ |
| External Data | RAG oracle guardrail (`remora-rag-oracle`) | ✅ |
| Non-AI Components | Tool-call gating via hook | ✅ |
| Actions | Primary target of REMORA governance | ✅ Core |
| Tools | Tool-type risk classification in Phase 1 | ✅ |
| Intermediate Results | AROMER EpisodicStore captures intermediate states | ✅ Partial |
| Final Results | DecisionEnvelope captures final decision | ✅ |
| Goals | Intent anchor (`scripts/remora_anchor.py`) | ✅ Partial |
| Context | Lyapunov V(t) = H(t) + λ·D(t) tracks semantic drift | ✅ Unique |
| Memory | EpisodicStore stores agent memory of decisions; no poisoning guard | ⚠️ Gap |
| Reasoning | Oracle pipeline evaluates reasoning but no explicit reasoning guard | ⚠️ Partial |
| Plans | Not explicitly targeted | ❌ Gap |
| Other Agents | Not explicitly covered; relevant for REMORA-edge | ❌ Gap |

### 2.4 LGA Layer-by-Layer Comparison

#### L1 Sandbox vs REMORA Stage 1

**LGA L1:** OS-level process isolation via `unshare`. Physical containment — even if L2 issues a false negative, the sandboxed process cannot actually damage the filesystem or network.

**REMORA Stage 1:** Deterministic LOCAL_BLOCK patterns (rm -rf, dd, mkfs, wrangler secret, force push, etc.). Non-negotiable hard stop via `remora_hook.py`.

**Assessment:** Functionally equivalent for covered threat patterns. **Gap:** REMORA's LOCAL_BLOCK does not physically isolate execution — it blocks at the hook level, but if a command is not in the LOCAL_BLOCK list, it executes with full host privileges. LGA's unshare sandbox provides defense-in-depth even for false negatives. This is a structural difference.

**Implication:** REMORA's Stage 1 must maintain comprehensive LOCAL_BLOCK coverage, since there is no physical containment fallback. The principle "never weaken the deterministic Stage 1 policy layer" is validated by LGA's finding that at 1% prevalence, any L2 judge produces PPV < 33% — the L1 sandbox is the essential always-on boundary.

#### L2 Intent Verification vs REMORA Oracle Pipeline

**LGA L2:** Single LLM judge receiving structured `(task, tool_call) → ALLOW/BLOCK` prompt. Best: Qwen2.5-14B (98.2–98.5% IR). Local small→large cascade improves FPR to 1.9–6.7% range [⚠️ cascade first-stage model name unverified in Ge paper; not "Qwen3.5-9B"].

**REMORA Stage 2–5:** Intent-drift (Jaccard) + FastGate → ConsensusGate → VerifierGate → CritiqueRevision → SelfConsistency + 3-oracle GO-STAR ensemble (llama-3.3-70b-fp8-fast, qwen3-30b-a3b-fp8, mistral-small-3.1-24b).

**Assessment:** REMORA's oracle is architecturally richer than LGA's L2. Key differentiators:
1. Multi-oracle ensemble vs single judge — reduces variance
2. Semantic Entropy (NLI-based) provides calibrated uncertainty, not just binary verdict
3. CRC provides formal coverage guarantee E[L(λ̂)] ≤ α + 1/(n+1) — LGA has no formal guarantee
4. Thompson bandit routing adaptively selects best oracle — LGA uses fixed model
5. AROMER MetaJudge provides ongoing calibration of the verification layer

**Learning from LGA:** The structured `(task, tool_call)` prompt template (Listing 1 in Ge 2026) is a proven approach yielding ≥93% IR across five models. REMORA's hook should ensure its oracle prompt always receives both the session intent anchor and the specific tool call in structured form. The current hook passes tool details but the oracle prompt structure should be reviewed against LGA's template for TC1/TC2 coverage.

#### L3 Zero-Trust vs REMORA Token/RBAC

**LGA L3:** HMAC-SHA256 capability tokens + JSON schema validation per tool call. Purpose: verify runtime behavior matches declared permissions.

**REMORA:** HMAC-SHA256 PDP token signing (`remora/enforcement/token.py`) + RBAC (`servers/api.py`, `_BUILTIN_ROLE_PERMISSIONS`, `_require_capability()`).

**Assessment:** Strong alignment at the authentication/authorization level. **Gap:** LGA specifically addresses TC3 (plugin permission boundary) — a declared tool that performs a covert side-channel. REMORA's RBAC controls API-level access but does not validate that a tool's runtime execution stays within its declared scope. This is the same gap LGA identifies in OpenClaw (G2). For REMORA, this means a tool granted `read_file` capability could potentially also write or exfiltrate data if not explicitly blocked by Stage 1.

#### L4 Audit vs REMORA DecisionEnvelope

**LGA L4:** Append-only fsync log (P50=4.1ms). Identified as a gap in OpenClaw (G4: mutable log).

**REMORA:** DecisionEnvelope v2 with HMAC-SHA256 signature, tenant-scoped hash chain (`previous_hash`), schema version, policy bundle hash, actor identity, timestamp. `verify_envelope_hash_chain()` in Shadow Mode.

**Assessment:** REMORA **exceeds** LGA's L4 design. REMORA's hash chain prevents log tampering even for an insider with database write access — a property LGA identifies as missing in OpenClaw and recommends for LGA. This is a genuine competitive advantage.

---

## 3. Gaps Identified

### 3.1 Process-Level Isolation (LGA L1 gap)

REMORA has no OS-level sandbox for tool execution. LGA's empirical finding that L2 judges yield <33% PPV at 1% prevalence makes L1 (physical containment) the essential always-on defense. **Mitigation within current architecture:** Maintain exhaustive LOCAL_BLOCK patterns and never reduce Stage 1 coverage. Longer-term: process-level isolation via WSL2/Docker for Bash tool calls.

### 3.2 Structured Tool-Call Judge Prompt

REMORA's oracle receives free-text questions but not a structured `(task_description, tool_call) → ALLOW/BLOCK` format. LGA demonstrates this structure achieves ≥93% IR across all LLM judges. **Recommendation:** Add a structured judge prompt variant to the hook's oracle call for tool-class decisions.

### 3.3 TC3 Permission-Boundary Enforcement

Malicious skill/plugin attacks (TC3: covert side-channel while performing declared operation) represent a structurally harder threat class (75–94% IR even with GPT-4o-mini). REMORA's current defense relies on Stage 1 pattern matching (e.g., blocking `wrangler secret`) and RBAC, but does not validate runtime execution scope vs declared permissions. **Recommendation:** Declare explicit tool permission schemas and validate at hook level.

### 3.4 PPV at Realistic Prevalence

REMORA's AII tracks calibration (ECE), friction (benign_review_rate), and FAR, but does not compute Positive Predictive Value (PPV) at realistic attack prevalence. At 1% prevalence with 10% FPR, PPV is ~9%. This is a missing operational metric.  
**Formula:** PPV = (IR × π) / (IR × π + FPR × (1−π)) where π = attack prevalence.

### 3.5 Multi-Agent Governance

Shamsujjoha et al. identify "Other Agents" as a guardrail target — governing inter-agent communications, preventing malicious agent collaboration, and managing multi-agent conflicts. REMORA currently governs single-agent tool calls. REMORA-edge (DIANA) involves multi-agent scenarios where this gap is directly relevant.

### 3.6 Memory Poisoning Protection

AROMER's EpisodicStore holds learning memory (past episodes). If an adversary could inject poisoned episodes (false labels), the learning loop would converge toward wrong thresholds. No explicit poisoning guard exists. The `do not tune on test data` rule in CLAUDE.md partially covers this, but a technical defense is missing.

### 3.7 Adversarial Robustness

LGA's adversarial probe shows IR drops to 50–63% under purpose-built evasion samples (double negation, authority injection, task disguise). REMORA's oracle has not been evaluated against adaptive attacks. Stage 1 (deterministic) is immune to LLM-level adversarial evasion for covered patterns, which provides a hard floor — this is REMORA's strongest adversarial defense.

### 3.8 Privacy Guardrails

Shamsujjoha et al. identify Privacy as a primary external quality attribute. REMORA masks secrets (CF_AIG_TOKEN etc.) but has no PII detection, data minimization guardrails, or GDPR-specific protections beyond organizational RBAC.

### 3.9 Calibration Monotonicity and Spread (Zhang et al. gap)

REMORA tracks ECE (currently 0.007) but not IPR or CE. ECE alone can be gamed: a model that always outputs the base-rate confidence has ECE=0 without being informative. Zhang et al. show that IPR (monotonicity) and CE (spread) are orthogonal dimensions that ECE misses.

**IPR gap:** REMORA's current oracle pipeline may exhibit non-monotonic calibration — high-confidence decisions could be systematically less accurate than medium-confidence decisions if the anchor threshold (exRiskScore 0.99) is too compressed. IPR would detect this.

**CE gap:** AROMER MetaJudge tends to score most critiques in the 0.95–0.99 range (narrow band). This low CE means the oracle confidence is not informative across the full range.

**Recommendation:** Add IPR and CE alongside ECE in the `/log` calibration section. Both can be computed from existing episode data (mean_score distribution vs. correctness labels). See `docs/researchpapers/analysis_notes_2026-06-30.md` §2.2 for formulas.

---

## 4. What REMORA Does Better

The following capabilities exceed what both papers study or propose:

| Capability | Papers' Scope | REMORA Advantage |
|---|---|---|
| Adaptive learning loop | Neither paper discusses runtime adaptation | AROMER self-improves via EpisodicStore + MetaJudge |
| Formal CRC guarantee | LGA has no formal guarantee | E[L(λ̂)] ≤ α + 1/(n+1) |
| Multi-oracle ensemble | LGA: single judge; Shamsujjoha: parallel calls at most | GO-STAR 3-oracle Thompson bandit |
| Counterfactual replay | Neither paper discusses shadow mode | Shadow Mode + Replay Engine unique |
| Hash-chain audit integrity | LGA identifies OpenClaw's mutable log as a gap | REMORA's hash chain + HMAC exceeds LGA L4 |
| Domain harm priors | Not discussed in either paper | DomainHarmPrior + OT/ICS domain pack |
| Causal attribution | Not discussed | Bjøru 2026 PS/PN causal framework |
| Lyapunov V(t) stability tracking | Not discussed | Formal stability monitoring via semantic entropy |
| AII composite quality index | Not discussed | 5-component weighted quality score |

---

## 5. Recommendations for REMORA Roadmap

**Phase 4 (current — before REM-020/021/022 gate):**
- [ ] Add PPV-at-prevalence metric to AII dashboard (low effort, high informational value)
- [ ] Review oracle hook prompt structure against LGA's `(task, tool_call)` template
- [ ] Expand LOCAL_BLOCK to cover TC3-class patterns (telemetry exfiltration signatures)
- [ ] Add IPR and CE calibration metrics to `/log` endpoint (Zhang et al. 2024)
- [ ] Verify cascade model name in Ge 2026 §4.2 — correct the "Qwen3.5-9B" error in this document

**Phase 5 (post-gate):**
- [ ] Implement declared tool permission schemas (JSON schema per tool type; validate at hook)
- [ ] Add adversarial robustness evaluation to AgentHarm harness
- [ ] Consider process-level isolation for Bash tool calls (WSL2/Docker via hook)
- [ ] Multi-agent governance design (relevant for REMORA-edge DIANA)
- [ ] Evaluate UF Calibration fidelity chain on AROMER oracle decisions (Zhang et al. 2024)
- [ ] Implement Wilson Score CIs for all calibration metrics in evaluation reports

---

## 6. Citations for REMORA Documentation

Any use of these papers in REMORA documentation, abstracts, or the whitepaper must use these exact citation forms:

```
Shamsujjoha, M., Lu, Q., Zhao, D., and Zhu, L. 2024. "A Taxonomy of Multi-Layered Runtime
Guardrails for Designing Foundation Model-Based Agents: Swiss Cheese Model for AI Safety
by Design." arXiv preprint arXiv:2408.02205v2. CSIRO Data61.

Ge, Y. 2026. "Governance Architecture for Autonomous Agent Systems: Threats, Framework,
and Engineering Practice." arXiv preprint arXiv:2603.07191v2. University of York.

Zhang, M., Huang, M., Shi, R., Guo, L., Peng, C., Yan, P., Zhou, Y., and Qiu, X. 2024.
"Calibrating the Confidence of Large Language Models by Eliciting Fidelity."
arXiv preprint arXiv:2404.02655v2. Fudan University / Meituan.
```

**Where citations apply in REMORA:**
- `docs/whitepaper/` — Section on multi-layer defense architecture (Shamsujjoha, Ge)
- `docs/whitepaper/` — Calibration and uncertainty quantification section (Zhang et al.)
- `docs/assurance/` — REM-021 external review prep: these papers validate REMORA's layered approach
- `REMORA-research/` — Architecture overview, credibility pack
- Any claim about "Swiss Cheese defense layering" → cite Shamsujjoha et al.
- Any claim about "LLM-based intent verification" → cite Ge 2026
- Any claim about ECE, calibration, or oracle confidence quality → cite Zhang et al. 2024
- IPR and CE metrics (to be added to REMORA) → Zhang et al. 2024

---

## 7. Verdict

**Alignment: Strong with identified gaps.**

REMORA's architecture is **well-aligned** with both papers' frameworks. REMORA implements the Swiss Cheese multi-layer model (Shamsujjoha et al.) and has analog layers for all four LGA layers (Ge). REMORA **exceeds** both papers in: adaptive learning, formal guarantee, multi-oracle ensemble, audit integrity, and counterfactual replay.

**Critical structural gap:** No OS-level process isolation (LGA L1 analog). REMORA compensates via exhaustive Stage 1 LOCAL_BLOCK — which must be maintained as the primary physical defense.

**Actionable learning:** LGA's finding that PPV collapses at realistic attack prevalence (22.7% at 1%) validates REMORA's friction-minimization design. The AII friction component (benign_review_rate=0, fri=1.000) directly addresses the usability cost of false positives that LGA identifies as the main deployment barrier.
