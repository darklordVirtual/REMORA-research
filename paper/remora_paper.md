# REMORA: A Policy-Gated Multi-Oracle Assurance Architecture for Agentic AI

**Stian Skogbrott** (Luftfiber AS) · [https://github.com/darklordVirtual/REMORA](https://github.com/darklordVirtual/REMORA)

*Paper version v0.9.0 — June 2026, versioned in lockstep with the repository release tag.*

---

## Abstract

Autonomous AI agents that invoke tools, query databases, or actuate real-world systems require an assurance layer that decides—before execution—whether an action is safe enough to proceed autonomously, requires verification, warrants abstention, or must be escalated to human review. We present REMORA (Reasoning Ensemble Multi-Oracle Routing Architecture), a research-grade control layer for agentic AI governance. REMORA combines parallel multi-oracle consensus, canonicalized verdict extraction, correlation-aware consensus weighting, thermodynamic-style uncertainty observables, Lyapunov-based stability tracking, and a policy engine with hard-block precedence rules to produce one of four structured outcomes: ACCEPT, VERIFY, ABSTAIN, or ESCALATE. On a 544-item benchmark drawn from TruthfulQA, BoolQ, and an adversarial suite, REMORA achieves 88.8% selective accuracy at 18% coverage (majority-vote full-coverage baseline: 41.18%; +47.6 pp lift; in-sample optimum). Exploiting the empirically confirmed critical-phase trust inversion (low-τ critical items achieve 71.4% accuracy vs. 27.3% for high-τ), a `PhaseAwareGuardrail` with inverted-score selection extends coverage to **22.1% at 85.0% accuracy** (+43.8 pp lift; N=120; Wilson CI [77.5%, 90.3%]; see `results/phase_aware_guardrail_n544_results.json`)—a +3.9 pp coverage gain with only 1.9 pp accuracy cost. A stratified 80/20 held-out evaluation with threshold τ* locked from the training split confirms **88.0% accuracy at 23.2% holdout coverage** (N\_accepted = 25, Wilson CI [70.0%, 95.8%], p = 1.45 × 10⁻⁵), establishing that the result is not an artefact of in-sample threshold selection. On an adversarial agentic tool-call benchmark (N=700), REMORA's full policy gate reduces unsafe execution from 10–20% (severity and keyword heuristics, not independent LLM evaluators) to 0% while maintaining mean utility 0.62 (vs. 0.0–(−0.25) for heuristics). **Construct validity (M1) — fixed (2026-06-28):** The gate formerly accessed `task.is_unsafe_if_executed` (label leakage). This branch has been removed entirely; `use_contradiction_flags` is now a no-op. Pre-fix clean-signal evaluation confirmed the leakage was not load-bearing (FAR=0, utility=0.62 across all three conditions: leaky, no-contradiction-flags, no-labels-no-severity); post-fix, FAR=0 confirmed with code path absent. AST leakage detector and mutation tests guard against re-introduction. The component ablation (`component_ablation_results.json`, N=700) corroborates: clean structural signals only (schema validity, forbidden-tool, tainted-argument) report FAR=0%, utility=0.62. Caveats: context flags correlate with harmfulness by benchmark construction; 140/560 harmful tasks rely on keyword heuristics vulnerable to evasion; external replication with independently withheld labels is the definitive resolution. See `results/toolcall_m1_clean_signal.json`, NEGATIVE_RESULTS.md §14, `docs/assurance/remediation_register.yaml` REM-001. A critical-phase evidence router achieves 100% NLI-proxy routing precision on a 3,000-item MultiNLI benchmark (NLI-proxy classification; not document-grounded evidence retrieval — see §7); the remainder are routed to human review. Key limitations include: (1) the benchmark contains 25% author-curated items subject to selection bias; (2) trust scoring alone cannot discriminate correctness in the critical phase (anticorrelation confirmed); (3) semantic evidence retrieval is pluggable but not live in the current implementation; (4) the audit hash-chain is tamper-evident but not tamper-proof without external append-only storage. REMORA is positioned as a governed autonomy layer—not a replacement for domain authority—that converts model disagreement, uncertainty, missing evidence, and policy triggers into explicit, auditable control decisions.

On the external AgentHarm benchmark (N=88, UK AI Safety Institute / Gray Swan AI), REMORA's three-mode cascade achieves blocked\_recall = 0.977 with FPR = 0.023 under an **intent-gating evaluation protocol** (REMORA evaluates the agent's proposed action and routes it to VERIFY/ESCALATE; true tool-call interception has not been verified — see §10.6 and `experiments/agentharm/INTERCEPTION_NOTES.md`). Meeting all three deployment goals in intent-gating mode (blocked recall ≥ 0.95, FPR < 0.10, coverage ≥ 0.95) demonstrates routing accuracy, not execution prevention. On a deterministic 36-case cross-domain evidence benchmark spanning cybersecurity, AI governance, and financial compliance, REMORA achieves precision = 1.000 and escalation recall = 1.000 with zero critical failures. An experimental learning extension, AROMER, reached `interpretation_nuanced: "TRAINED_SHADOW_ONLY"` with peak AII=0.844 (aii\_smoothed=0.8442) over 12+ consecutive organic TRAINED cycles with zero false accepts; current live AII=0.8042 TRAINED_SHADOW_ONLY (full §12→§13 cycle documented: peak 0.8442 at cycle 12, regression to CAPABLE at ~13:00 UTC 2026-06-28 brr 0%→5%, organic recovery to TRAINED at ~15:53 UTC in ~2h53min, brr 5%→2.5%; FAR=0 throughout; see Appendix F.7 and NEGATIVE_RESULTS.md §12–§13; AII is a composite index with researcher-chosen weights — see Appendix F for formula, weight rationale, and cumulative state; organic TRAINED confirmed after seeding-induced regression and recovery — see Appendix F.6–F.7 and NEGATIVE_RESULTS.md §9–11 for full trajectory). All five evidence gates are cleared: longitudinal stability (201+ records), safety evidence (n\_harmful\_independent=169 external aradhye/CaiZhiTech; safety\_upper\_bound\_95=0.37%), transfer measurement (4 database-to-financial cross-domain cases; `scripts/aromer_publish_replay.py`), and causal enrichment (66 episodes with Bjøru 2026 PS scores (§4.2.2); `scripts/aromer_publish_causal.py`). **Critical caveats:** (1) T4 Transfer = 1.0 derives from a 96-episode in-domain replay arena sharing taxonomy with AROMER's seeds — the 4 cross-domain cases clear the measurement gate but do not establish independent transfer; without T4, renormalized AII ≈ 0.52. (2) External holdout safety floor (proxy-signal transfer) largely de-risked via structural policy gates (schema validity, forbidden-tool, tainted-argument; FA→0%, harm-intercept→100% on 495-case balanced holdout); independent external-corpus validation pending — see NEGATIVE_RESULTS.md §2. (3) Aradhye holdout FA=22.2% (execution-context harm requiring runtime monitoring — Gap 2; see NEGATIVE_RESULTS.md §6). (4) `safety_certification = CERTIFIED_INDEPENDENT_HOLDOUT` (n\_harmful\_independent=169 external; safety\_upper\_bound\_95=0.37%); `deployment_status: "SHADOW_ONLY"`, `policy_relaxation_allowed: false`. Three production gates remain before deployment: longitudinal stability audit, independent human review, RBAC access control audit. Key limitations: AgentHarm evaluation is intent-gating only; AROMER external validity not yet established; no production deployment validated.

**Keywords:** agentic AI safety, multi-oracle consensus, selective prediction, uncertainty routing, policy-as-code, audit governance, human-in-the-loop

---

## 1. Introduction

The deployment of LLM-powered agents capable of invoking tools—writing files, calling APIs, querying databases, or triggering industrial actuations—introduces a class of decision problem distinct from conversational AI: an agent proposes a *concrete action* in the world, and the system must decide whether to execute it. Unlike a hallucinated sentence, an erroneously executed database write or a wrongly triggered process shutdown has immediate, potentially irreversible consequences.

Existing safeguards (RLHF alignment, system prompts, content classifiers) are semantic filters applied at training or prompt time; they are not designed to evaluate a specific proposed action against a specific operational context, evidence base, and regulatory policy at inference time. Majority vote among LLMs—the dominant ensemble primitive—improves accuracy but cannot block a confident, wrong consensus from triggering unsafe execution. A model swarm can be unanimously wrong.

We argue that what is needed is not a *better oracle* but an *assurance layer*: a system that evaluates whether the conditions for autonomous action are met (sufficient consensus, adequate evidence, no policy violations, acceptable uncertainty) before anything is executed. When those conditions are not met, the system must route toward verification, abstention, or human review—and record the reasoning in an auditable envelope.

REMORA demonstrates such a layer. Its core thesis is: **governed autonomy requires explicit routing of uncertainty—not suppression of it.** The system is designed around four principles:

1. **Measure disagreement explicitly.** Oracle consensus is quantified using information-theoretic observables (entropy H, dissensus D) and mapped to thermodynamic-analogous phases (ordered/critical/disordered).
2. **Evidence must back critical-phase decisions.** When oracle consensus is near a phase boundary, trust alone cannot route safely; an independent evidence signal is required.
3. **Policy must override consensus.** Hard blocks (adversarial detection, critical risk, regulatory triggers) take precedence over any majority vote.
4. **Every decision is auditable.** A hash-linked audit envelope records the full reasoning chain for each gate decision.

The contribution of this paper is not a new foundation model, a new training procedure, or a new benchmark. It is a **system architecture and empirical evaluation for governed agentic AI decision control**: a reference implementation, a set of measurable observables, a documented set of negative results, and an honest account of what remains unsolved.

### 1.1 Paper Organization

Section 2 reviews related work. Section 3 defines the problem. Section 4 describes the system architecture. Section 5 formalizes the method. Section 6 defines the decision and policy model. Section 7 describes evidence-grounded critical-phase routing. Section 8 covers the audit envelope. Section 9 describes the experimental setup. Section 10 reports results. Section 11 presents ablations. Section 12 contains a high-stakes industrial case study. Section 13 documents negative results. Section 14 identifies threats to validity. Section 15 covers safety and ethics. Section 16 addresses reproducibility. Section 17 concludes.

---

## 2. Background and Related Work

### 2.1 LLM Ensembles and Self-Consistency

Wang, Wei et al. (2023a) introduced self-consistency sampling—generating multiple chain-of-thought paths and selecting the majority answer—demonstrating that diversity in reasoning paths improves accuracy on reasoning benchmarks (Wang, Wei et al., 2023a). REMORA's oracle fan-out is structurally related but differs in two key respects: (1) oracles are distinct model families (different architectures and parameter counts), not multiple samples from a single model; (2) consensus is weighted by inter-oracle correlation rather than treated as exchangeable.

Wang, Aitchison, and Rudolph (2023b) show that parameter-efficient LLM ensembles improve predictive accuracy and uncertainty quantification, and that ensemble diversity is the key driver — with OOD detection (AUROC) also improving alongside in-distribution calibration. This motivates, but does not independently validate, REMORA's use of heterogeneous oracle aggregation; the OOD-detection improvement maps conceptually onto handling adversarial or distribution-shifted agent actions.

### 2.2 Multi-Agent Debate

Du et al. (2023) demonstrated that having LLMs debate each other—iteratively exchanging arguments—can reduce hallucination and improve factuality (Du et al., 2023). REMORA does not implement iterative debate but shares the intuition that inter-model disagreement is an informative signal. REMORA's dissensus metric D is a one-shot, non-iterative analogue.

### 2.3 LLM-as-Judge and Verifier Models

Zheng et al. (2023) introduced the LLM-as-judge paradigm for evaluating model outputs (Zheng et al., 2023). Cobbe et al. (2021) trained a process reward model as a verifier for mathematical reasoning (Cobbe et al., 2021). REMORA differs by using a structured policy engine—not a learned verifier—to gate decisions, enabling interpretable hard blocks that cannot be overridden by a confident oracle.

### 2.4 Selective Prediction and Abstention

The literature on selective prediction (Geifman & El-Yaniv, 2017; El-Yaniv & Wiener, 2010) establishes the risk-coverage tradeoff (equivalently, quality-coverage tradeoff) as the fundamental metric for systems that may abstain. El-Yaniv & Wiener (2010) prove that unanimous-hypothesis rejection is the coverage-optimal zero-risk strategy (Consistent Selective Strategy, Theorem 7): no other strategy achieving zero risk can improve on it in coverage. This formalizes REMORA's abstain-on-oracle-disagreement design as theoretically optimal for the zero-false-accept goal. Kadavath et al. (2022) showed that LLMs can estimate their own uncertainty, but this estimate is unreliable in adversarial or out-of-distribution contexts (Kadavath et al., 2022). REMORA's abstention mechanism is grounded in this literature: uncertainty is measured structurally (via oracle disagreement) rather than through self-reported confidence.

### 2.5 Conformal Prediction

Shafer and Vovk (2008) and Angelopoulos and Bates (2021) established conformal prediction as a framework for generating prediction sets with distribution-free coverage guarantees. REMORA implements a Mondrian conformal guardrail for the ordered phase and Conformal Risk Control (Angelopoulos et al., 2022) with importance weights for the critical phase (§7.2). It also uses a Mondrian conformal guardrail—phase-stratified conformal calibration—that provides per-phase coverage guarantees. The critical limitation (exchangeability assumption) is documented as a negative result (§13).

### 2.6 Uncertainty Calibration

Guo et al. (2017) showed that modern neural networks are miscalibrated (Guo et al., 2017). REMORA does not calibrate individual oracle confidences but instead treats their distribution as a consensus signal, partially sidestepping per-oracle calibration requirements.

### 2.7 AI Governance and Policy-as-Code

Algorithmic-audit scholarship emphasizes the importance of institutionalized third-party oversight and audit-system design (Raji et al., 2022). Raji et al. identify lack of audit data access as "the most significant vulnerability of the current AI audit ecosystem" (§4.3) and propose post-audit transparency registries (§4.5). REMORA's DecisionEnvelope directly addresses the access gap by logging each governance decision with immutable hash-chaining; the Replay Engine instantiates the transparency registry by publishing governance episodes for third-party inspection. Regulatory requirements for high-risk AI systems—including documentation, logging, and human oversight—are grounded separately in the EU AI Act (European Parliament, 2024). Open Policy Agent (OPA) (Styra, 2024) provides a production-grade policy engine using the Rego declarative language. REMORA integrates an OPA adapter—failing closed to a Python fallback when the OPA daemon is unavailable—as a concrete instantiation of policy-as-code for AI decisions.

### 2.8 Assurance Cases

Software assurance cases (Kelly, 1998; Bloomfield & Bishop, 2010) structure safety arguments as hierarchical claim-evidence-reasoning trees. REMORA's DecisionEnvelope is designed to populate one node of such a case: it provides the evidence chain for a specific gate decision, suitable for inclusion in a larger safety argument.

### 2.9 Human-in-the-Loop and Human-on-the-Loop Systems

Endsley (1995) defines levels of human supervisory control; "human-in-the-loop" requires confirmation for each action, while "human-on-the-loop" allows autonomous action with human monitoring. REMORA's ACCEPT/VERIFY/ABSTAIN/ESCALATE schema directly implements a spectrum from human-on-the-loop (ACCEPT) to human-in-the-loop (ESCALATE), with VERIFY and ABSTAIN as intermediate states.

### 2.10 Industrial AI Safety

The oil-and-gas sector has established quantitative risk frameworks (NORSOK D-010:2021; IEC 61511:2016) that define action classes requiring human sign-off. REMORA's case study (§12) uses this domain as an illustration of how policy-gated AI governance maps to existing industrial safety requirements. No domain-specific correctness is claimed.

---

## 3. Problem Statement

Let $\mathcal{A}$ be a space of agent-proposed actions (tool calls, API invocations, database writes, actuation commands). Let $q$ be a natural-language query or intent specification associated with action $a \in \mathcal{A}$, and let $c$ be the operational context (domain, risk tier, target environment, policy regime).

An *uncontrolled* agent maps $q \rightarrow a$ and executes $a$ without further evaluation. This is acceptable when $a$ is low-risk and reversible, but unsafe when $a$ is high-risk, irreversible, or requires regulatory authorization.

We seek a control function:

$$\Gamma: (q, a, c) \rightarrow g \in \{{\rm ACCEPT, VERIFY, ABSTAIN, ESCALATE}\}$$

with the following properties:

1. **Safety-first:** Hard policy violations map to ESCALATE regardless of consensus.
2. **Calibration-aware:** The system has measurable uncertainty about its own decisions, and abstains when uncertainty exceeds a threshold.
3. **Evidence-sensitive:** In high-uncertainty regions, external evidence can resolve ambiguity (evidence-accept) or contradict the oracle consensus (abstain/escalate).
4. **Auditable:** Every invocation of $\Gamma$ produces a signed evidence record suitable for regulatory review.
5. **Conservative by default:** When any required component fails or is unavailable, the system fails closed toward VERIFY or ESCALATE depending on risk tier.

This is not a question of *accuracy*—REMORA does not know whether action $a$ is correct. It is a question of *assurance conditions*: whether the conditions that would justify autonomous execution of $a$ are verifiably met.

---

## 4. REMORA Architecture

REMORA processes each gate request through six decision stages, followed by DecisionEnvelope emission:

```
[Agent Proposed Action]
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. INTAKE & RISK CLASSIFICATION                                 │
│    classify intent domain, risk tier, action type, environment  │
│    → adversarial admission firewall check (hard block)          │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. ORACLE FAN-OUT (parallel, ThreadPoolExecutor)                │
│    O = {o₁, o₂, …, oₙ} queried simultaneously                  │
│    failed oracles filtered; valid set O' ⊆ O retained           │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. CANONICALIZATION & CORRELATION-AWARE CONSENSUS               │
│    φ(): raw response → (polarity, claim_hash, magnitude, tags)  │
│    w(o): oracle weight inversely weighted by pairwise ρ̄         │
│    p̂(v) = Σ w(o)·1[φ(o)=v]  (weighted support distribution)   │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. THERMODYNAMIC UNCERTAINTY OBSERVABLES                        │
│    H = −Σ p̂ᵢ log₂ p̂ᵢ  (entropy)                              │
│    D = 1 − max(p̂ᵢ)    (dissensus)                             │
│    η = (max p̂ − 1/k) / (1 − 1/k)  (order parameter)           │
│    T = f(prompt structure)  (structural temperature, pre-infer) │
│    F = λD − T·H  (free-energy proxy)                           │
│    τ = η·(1−h_bound)·w_phase·(1/(1+χ/χ₀))  (trust score)      │
│    phase ∈ {ordered, critical, disordered}                     │
│    V(t) = H(t) + λD(t)  (Lyapunov observable)                  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. EVIDENCE ROUTER (critical-phase path)                        │
│    if phase = critical: route to CriticalEvidenceRouter         │
│    evidence signal (strength, contradiction, coverage)          │
│    → evidence_accept / abstain / escalate                       │
│    [Note: current implementation uses oracle-proxy signals;     │
│     semantic BM25/NLI retrieval is pluggable, not live]         │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. POLICY ENGINE (hard-block priority, then routing)            │
│    7 hard blocks evaluated first (adversarial, counterfactual,  │
│    evidence-contradicted, distribution-shift, critical+critical, │
│    evidence-insufficient, require-evidence)                     │
│    Accept / Verify / Abstain paths evaluated in order           │
│    OPA/Rego adapter (fail-closed to Python fallback)            │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
        g ∈ {ACCEPT, VERIFY, ABSTAIN, ESCALATE}
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. DECISION ENVELOPE v2                                         │
│    request / assessment / gate / reviewer_context / follow_up   │
│    history / policy_learning / audit (SHA-256 hash-chain)       │
└─────────────────────────────────────────────────────────────────┘
```

**Figure 1:** REMORA gate architecture. Stages 1–6 are sequential; hard blocks in Stage 6 can override any earlier routing. Stage 7 (DecisionEnvelope emission) is the output record, not a decision stage.

### 4.1 Oracle Swarm

The oracle set $\mathcal{O}$ contains $n \geq 3$ models from distinct model families. In the reported experiments: Llama-3.1-8B-Instant, Llama-3.3-70B-Versatile, and Llama-4-Scout-17B-16E-Instruct (Groq inference API). Fan-out is implemented with `concurrent.futures.ThreadPoolExecutor`; sequential fallback is invoked on runtime errors (e.g., nested event loops). Oracle responses are collected with per-oracle timeouts. Failed responses (network errors, timeouts, parse failures) are identified by a non-null `error` field and excluded from all downstream aggregation before consensus is computed.

### 4.2 Canonicalizer

The canonicalizer $\phi$ maps each oracle's raw text response to a structured `CanonicalVerdict` tuple (`polarity`, `claim_hash`, `magnitude`, `tags`). Polarity ($\{$True, False, None$\}$) is extracted from binary-answer signals. The claim hash is a 16-character truncated SHA-256 over NFKC-normalized, stopword-stripped, sorted token sequences—a semantics-preserving fingerprint that clusters semantically equivalent responses even when wording differs. This is a pragmatic heuristic, not a semantic equivalence proof.

### 4.3 Correlation-Aware Weighting

Oracles within the same base-model family tend to agree regardless of factual correctness—a form of correlation that inflates apparent consensus. REMORA maintains a rolling window (default: 200 samples) of pairwise agreement rates $\rho(a, b) \in [0, 1]$ between every oracle pair $(a, b)$. Diversity weights are:

$$w(o) = \frac{\tfrac{1}{n}}{1 + \sum_{j \neq o} \rho(o, j)} \cdot Z^{-1}$$

where $Z$ normalizes weights to sum to one. Oracles that frequently agree with others receive down-weighted votes; oracles that dissent from the majority receive up-weighted votes. This is an operational heuristic—not a proof of statistical independence.

---

## 5. Method: Thermodynamic Uncertainty Observables

We use thermodynamic terminology as an **operational metaphor for observable consensus structure**. The observables are deterministic functions of oracle outputs and calibration parameters. No claim is made that LLM systems obey a physical thermodynamic law.

### 5.1 Definitions

Let $\hat{p}(v) = \sum_{o \in \mathcal{O}'} w(o) \cdot \mathbf{1}[\phi(o) = v]$ be the weighted support for verdict $v$ after removing failed oracles and applying diversity weights. Let $k = |\{\hat{p}(v) > 0\}|$ be the number of distinct active verdicts.

**Entropy** (Shannon, bits):
$$H = -\sum_v \hat{p}(v) \log_2 \hat{p}(v)$$

**Dissensus:**
$$D = 1 - \max_v \hat{p}(v)$$

$D = 0$ when all valid oracles agree; $D \approx 1$ when support is spread uniformly. Note that $D$ and $H$ are correlated: high dissensus implies high entropy. This is a structural property of the observables, not a circular definition.

**Order parameter:**
$$\eta = \frac{\max_v \hat{p}(v) - \tfrac{1}{k}}{1 - \tfrac{1}{k}}$$

$\eta = 1$ when consensus is unanimous; $\eta = 0$ when all verdicts are equally supported.

**Structural temperature:** $T$ is estimated from prompt structure alone—Kolmogorov complexity proxy (zlib compression ratio), log-normalized prompt length, and domain prior—independent of oracle responses. This was introduced specifically to resolve a documented circularity in an earlier formulation where $T$ was estimated post-inference from $D$ (see §13.1). Domain priors are: factoid $T_{\text{prior}} = 0.25$, reasoning $= 0.85$, creative $= 1.50$, adversarial $= 1.70$.

**Free-energy proxy:**
$$F(T) = \lambda D - T \cdot H, \quad \lambda = 0.3$$

At low $T$ (structured, factual prompts), high entropy penalizes $F$ strongly; at high $T$ (adversarial, open-ended prompts), the thermal term $T \cdot H$ partially compensates for entropy.

**Lyapunov observable:**
$$V(t) = H(t) + \lambda D(t)$$

$V(t)$ is tracked across iterative oracle invocations. If $V$ increases by more than $\epsilon_{\text{tol}} \cdot |V|$ between steps, the session is flagged as potentially unstable and iteration halts. Across 1,000 synthetic sessions (N sessions × 5–20 steps), $P(\Delta V \leq 0) = 87.2\%$, mean $\Delta V = -0.329$ (§10.4). This is a measurement of empirical behavior, not a proof of formal stability.

**Trust score:**
$$\tau = \eta \cdot (1 - h_{\text{bound}}) \cdot w_{\text{phase}} \cdot \left(1 + \frac{\chi}{\chi_0}\right)^{-1}$$

where $h_{\text{bound}}$ is a hallucination rate bound derived from inter-oracle agreement, $w_{\text{phase}} \in \{1.0, 0.5, 0.1\}$ for ordered/critical/disordered phases, and $\chi$ is susceptibility (sensitivity to oracle perturbation, repurposed as an OOD anomaly detector; see §13.2).

### 5.2 Phase Classification

Phase is determined by comparing structural temperature $T$ to a calibrated critical temperature $T_c$ derived from the distribution of thermodynamic observables:

- **Ordered:** $T < T_c$ and $\eta > 0.5$
- **Critical:** $|T - T_c| / T_c < 0.15$ (within 15% of critical point)
- **Disordered:** otherwise

The phase classification has direct operational consequences: ordered phase enables high-coverage autonomous operation; critical phase requires evidence routing; disordered phase defaults to ABSTAIN.

---

## 6. Decision and Policy Model

### 6.1 Four Gate Outcomes

The gate function $\Gamma$ produces one of four outcomes:

| Outcome | Meaning | Autonomous Action |
|---------|---------|-------------------|
| **ACCEPT** | Conditions for autonomous action are met | Permitted |
| **VERIFY** | Action is plausible but requires validation | Pending |
| **ABSTAIN** | Uncertainty or contradiction too high to decide | Blocked |
| **ESCALATE** | Human review required; hard failure or policy trigger | Blocked |

**ACCEPT** requires: no hard policy block; ordered phase; trust score $\tau$ above a calibrated threshold ($\tau^* \approx 0.203$ in the held-out evaluation protocol; threshold-specific values are reported in Section 10); evidence consistent. Accept does not mean the system *knows* the action is correct—it means the assurance conditions for autonomous execution are met.

**VERIFY** is issued when the oracle assessment is plausible but dependent on external validation (e.g., a field inspection, a document check, a dual-control approval). It is not a failure—it is a controlled handoff.

**ABSTAIN** indicates the system refuses to gate the action because uncertainty or contradiction is too high. This is not equivalent to "the action is wrong"; it is equivalent to "the conditions for deciding are not met." Agents must treat ABSTAIN as a hard execution block.

**ESCALATE** is issued when any hard policy block fires or when human review is required by policy (e.g., critical risk tier, adversarial input detected, evidence contradiction). ESCALATE also triggers a follow-up workflow: a structured request for field evidence, dual-control approval, or regulatory sign-off, captured in the decision envelope.

### 6.2 Hard Blocks (Priority Order)

The following seven conditions are evaluated before any consensus-based routing. The first matching condition returns immediately:

| Priority | Condition | Reason Code | Action |
|----------|-----------|-------------|--------|
| 1 | `adversarial_detected = True` | ADMISSION_FIREWALL_BLOCKED | ESCALATE |
| 2 | `counterfactual_passed = False` | COUNTERFACTUAL_FAILED | ESCALATE |
| 3 | `evidence_contradictions > 0 AND contradiction_cycles > 0` | EVIDENCE_CONTRADICTED | ESCALATE |
| 3b | `evidence_contradictions > 0` | EVIDENCE_CONTRADICTED | ABSTAIN |
| 4 | `refuse_parametric_verdict AND evidence_action ≠ "answer"` | THERMO_REQUIRE_EVIDENCE | VERIFY |
| 5 | `distribution_shift_detected = True` | DISTRIBUTION_SHIFT | VERIFY |
| 6 | `phase = critical AND risk_tier = critical` | CRITICAL_PHASE | ESCALATE |
| 7 | `risk_tier ∈ {high, critical} AND evidence_action = None` | EVIDENCE_INSUFFICIENT | VERIFY |

**Table 3: Policy Hard Blocks.**

The adversarial firewall checks for injection patterns in the prompt (e.g., "ignore previous instructions", "exfiltrate", "drop table", "sudo rm"). The OPA/Rego adapter is queried first; if unavailable, the Python fallback engine applies the same rules and flags `fallback_used = True` in the envelope.

### 6.3 Policy-as-Code Integration

REMORA exports a `PolicyObservation` dataclass with 55 fields (risk tier, domain, action type, target environment, all thermodynamic observables, evidence signals, oracle failure counts) as a JSON structure to OPA. The OPA endpoint evaluates Rego policies against this context and returns a structured decision. The fail-closed contract: any OPA communication error (connection refused, timeout, parse failure) causes the system to silently fall back to the Python engine and record `source_of_decision = "python_fallback"` in the audit envelope. This ensures no decision is ever gated on a missing policy engine.

---

## 6.4 Governance Intelligence Layer: Misspecification-Aware Pre-Policy Enrichment

The policy engine is only as honest as the metadata it is given: an integration bug, or a compromised agent, can label a destructive action as a low-risk read and present the gate with nothing to fire on. Added in release v0.9.0, the **Governance Intelligence Layer** (`remora/governance_intelligence/`) closes this gap with an opt-in, fully deterministic enrichment stage that runs before any policy rule (no LLM calls):

1. **Fail-closed normalization** of caller-supplied labels — unknown is explicit, never coerced to a safe value
2. **Action-semantics extraction** from the proposed action text and tool metadata
3. **Misspecification-risk inference** from label/semantics disagreement
4. **Causal-consequence signals** — blast radius and expected loss
5. **Policy-generalization risk** — would repeatedly accepting this *class* of action remain safe fleet-wide?

Signals merge into the existing `PolicyObservation` under a **strengthen-only** rule: inferred higher risk may override a supplied lower label, never the reverse, and hard-block flags are never cleared. A grid property test across 2,160 observation combinations verifies that enrichment never converts a rejection into an acceptance (`tests/policy/test_governance_intelligence_never_weakens_policy.py`). The engine remains the sole decision authority.

**Benchmark** (50 deterministic tasks, 10 categories of mislabelled/underspecified/repeated actions, deliberately permissive trust baseline; artifact `artifacts/governance_intelligence/evaluation_results.json`):

| Metric | Result |
|---|---:|
| Unsafe accept rate (no-accept tasks) | **0.0%** |
| Metadata-mismatch detection | 100% |
| Unknown-metadata review rate | 100% |
| Legitimate reads still accepted | 100% |
| Escalation precision | 96.7% |
| Policy-generalization detection | 90% |

Without enrichment, `DROP TABLE users` labelled `action_type=read, risk_tier=low` reaches ACCEPT on a high-trust path; with enrichment it escalates. The layer is heuristic and English-centric; pattern tables can be evaded by novel phrasing, so it reduces reliance on caller labels rather than replacing verification, evidence, or human review.

---

## 7. Evidence-Grounded Critical-Phase Routing

### 7.1 The Critical-Phase Problem and PhaseAwareGuardrail

In the critical phase, oracle consensus is near the phase boundary: the trust score is moderate but neither reliably high nor reliably low. A key empirical finding (§13.3) is that in this phase, *higher trust scores correlate with lower correctness* (Q4 high-trust: 50% correct vs Q1 low-trust: 75% correct on N=32 real-oracle critical-phase items; refined: τ ≥ 0.10 → 27.3% accuracy, τ < 0.10 → 71.4% accuracy, N=21). This is the opposite of what trust-based routing assumes. Conformal calibration at 5% risk target fails completely on critical-phase items (mean observed risk = 100%, coverage → 0%). Trust scoring alone cannot gate critical-phase decisions.

**PhaseAwareGuardrail: Exploiting the Inversion.** The inversion is a *selection criterion reversal*: the guardrail should prefer low-τ items in the critical phase. `PhaseAwareGuardrail` (implemented in `remora.selective.guardrail`) applies an inverted score `τ̃ = 1 − τ` for critical-phase items, then calibrates a conformal threshold on `τ̃`. A hard gate rejects all items with τ ≥ 0.10 (the groupthink boundary). The combined pool (99 ordered + 21 low-τ critical items) achieves:

| Coverage | N   | Accuracy | Wilson CI       | Lift over baseline |
|----------|-----|----------|-----------------|--------------------|
| 18.2%    | 99  | 86.9%    | [78.8%, 92.2%]  | +45.7 pp           |
| 20.0%    | 108 | 85.2%    | [77.3%, 90.7%]  | +44.0 pp           |
| **22.1%**| **120** | **85.0%** | **[77.5%, 90.3%]** | **+43.8 pp** |

A +3.9 pp coverage gain with 1.9 pp accuracy cost; still +43.8 pp above the 41.18% baseline. Numbers from `results/phase_aware_guardrail_n544_results.json` (empirical flat-phase policy). The guardrail is fully implemented and tested (8 unit tests in `tests/test_guardrail.py`).

### 7.2 Conformal Risk Control Under Covariate Shift

Standard Mondrian conformal calibration assumes exchangeability between calibration and test samples — a condition violated in the critical phase. Applying standard conformal to critical-phase items yields 100% observed risk and 0% coverage (negative result, §6).

REMORA resolves this with **Conformal Risk Control** (CRC; Angelopoulos et al., 2022), which extends split-conformal prediction to covariate-shifted test distributions via per-item importance weights. For the phase-shift setting, REMORA uses:

$$w_i = \begin{cases} 1.0 & \text{if phase}(i) = p_{\text{test}} \\ \beta = 0.10 & \text{otherwise} \end{cases}$$

The CRC threshold $\hat{\lambda}$ minimises accepted items subject to weighted empirical risk $\bar{L}(\hat{\lambda}) \leq \alpha$. **Theorem 1** (Angelopoulos et al., 2022) provides a formal risk bound when weights $w_i$ correctly specify the density ratio $p_{\text{test}}/p_{\text{cal}}$. Here $\beta = 0.10$ is a conservative hand-tuned constant, not a validated density ratio estimate; accordingly REMORA uses a *CRC-inspired heuristic operating point*, not a formally guaranteed bound (M6 peer-review finding):

$$\mathbb{E}[L(\hat{\lambda})] \lesssim \alpha + \frac{1}{n+1} \quad \text{(CRC-inspired heuristic; } \beta\text{=0.10 not validated)}$$

Empirically: for binary 0/1 loss, overshoot is at most $1/(n+1)$ — 5 pp for $n=19$, 1 pp for $n=99$ — across 20 repeated splits on the synthetic Lyapunov benchmark. To invoke the formal theorem, β must be estimated from held-out calibration density ratios.

Implementation: `remora.selective.crc.CovariateShiftCRC.fit(scores, labels, phases, target_phase)` returns a `CRCReport` with `finite_sample_slack` ($= 1/(n_{\text{cal}}+1)$) and `guaranteed_risk_bound` ($= \alpha + \text{slack}$; note: label reflects heuristic target, not formal CRC guarantee when β is fixed). Tested: 44 unit tests covering edge cases, tied-score atomicity, phase-weight algebra, and Theorem 1 slack.


### 7.3 Prover-Verifier Deliberation for Critical-Phase Routing

Kirsch et al. (2024) showed that prover-verifier games produce more legible and reliable LLM outputs. REMORA adapts this protocol to its offline multi-oracle setting without additional API calls.

**Protocol:**
1. **Cluster** oracle responses via Semantic Entropy clustering, producing semantic equivalence classes sorted by mass. *(In all reported benchmarks, the `TokenFingerprintBackend` heuristic is used rather than the `NLISemanticBackend`; the two may cluster differently for paraphrases with no shared tokens. The `NLISemanticBackend` is fully implemented as a drop-in alternative using cross-encoder entailment but has not been activated for any reported result — see NEGATIVE_RESULTS.md §3 for analysis and replication instructions.)*
2. **Prover** = the oracle from the dominant cluster with highest confidence.
3. **Verifier** = the highest-confidence oracle *outside* the dominant cluster.
4. **Deliberation** (r = 1, ..., n_rounds): evaluate NLI entailment score prover→verifier with round-decay γ=0.85.
5. **Legibility score**: L = mean_entailment × cluster_mass.
6. **Final confidence**: geometric mean of dominant cluster mass and updated verifier confidence.

**Routing signal:** PVD confidence blended with REMORA trust score:

$$\tilde{\tau} = (1 - w_{\text{pvd}}) \cdot \tau + w_{\text{pvd}} \cdot \hat{c}, \quad w_{\text{pvd}} = 0.40$$

Implementation: `remora.selective.pvd.deliberate(oracle_responses, oracle_confidences, n_rounds=2)` returns a `PVDResult`. `pvd_routing_score(trust_score, pvd_result)` implements the blending. Tested: 33 unit tests, no external model calls.

### 7.4 Evidence Router Design

The `CriticalEvidenceRouter` accepts an `EvidenceSignal` with five fields: `evidence_strength`, `contradiction_score`, `citation_coverage`, `cross_evidence_consistency`, `source_reliability`. It applies threshold logic in priority order:

1. **Coverage gate:** if `citation_coverage < 0.50` → ESCALATE
2. **Contradiction block:** if `contradiction_score > 0.50` → ABSTAIN
3. **Evidence accept gate:** if `evidence_strength ≥ 0.80` AND `contradiction_score ≤ 0.15` AND `source_reliability ≥ 0.60` → evidence_accept
4. **Default:** → ESCALATE with diagnostic

### 7.4 Evidence Signal Provenance

**Important implementation note:** In the current implementation, the `EvidenceSignal` is built as a proxy from oracle consensus statistics (agreement rates, polarity distribution, coverage fraction). This is explicitly documented in the source as a "structural bridge" pending semantic retrieval integration. The evidence router logic is fully implemented and tested; what is not yet live is an external BM25/NLI passage retrieval pipeline feeding real document evidence into the signal.

On the MultiNLI evidence benchmark (N=3,000, entailment/neutral/contradiction labels; used as a proxy for evidence-verification decisions). **NLI-proxy routing result** — this measures classification accuracy of the NLI-proxy signal, not document-grounded evidence retrieval precision (see implementation note above and M7 in NEGATIVE_RESULTS.md §14):
- Resolution rate: 38.5% (items routed to evidence_accept or abstain rather than escalate)
- `evidence_accept` NLI-proxy routing precision on entailment items: 100%
- False accept rate on contradiction items: 0%
- Abstain precision on contradictions: 99.3%

The remaining 61.5% of critical-phase items receive ESCALATE, which is the correct conservative behavior: in the absence of conclusive evidence, human review is required.

---

## 8. Audit and Governance Envelope

### 8.1 DecisionEnvelope v2

Every gate invocation produces a `DecisionEnvelope` (a serializable, immutable dataclass) with the following top-level blocks:

| Block | Contents |
|-------|----------|
| `request` | request_id, timestamp, query, proposed_action, domain, risk_tier |
| `assessment` | intent classification, oracle votes, thermodynamic observables |
| `gate` | outcome, reasons, confidence, coverage_policy, blocked_action |
| `reviewer_context` | asset information, evidence sources, why-escalated list |
| `follow_up` | type, priority, assign_to, required_evidence, SLA |
| `history` | similar_cases_count, decision_pattern, known_blockers |
| `policy_learning` | candidate rule, confidence, recommendation |
| `audit` | hash-chain root, audit_hash, policy_version, source_of_decision |

**Appendix B** contains the full schema.

### 8.2 Audit Hash-Chain

The `AuditHashChain` links successive gate decisions using SHA-256:

$$h_i = \mathrm{SHA256}(h_{i-1} \;\|\; \mathrm{json}(e_i))$$

where `canonical_json` ensures field ordering is deterministic. Chain integrity is verified by recomputing each entry hash and checking back-pointer consistency. This provides **tamper-detection**: any modification to a historical entry breaks the chain and is detectable on verification. It does **not** provide **tamper-prevention**: an adversary with write access to the storage medium could replace the entire chain. True tamper-proof audit requires append-only object storage (e.g., S3 Object Lock, Azure Immutable Blob, Hyperledger) as an external dependency not included in this implementation.

### 8.3 Human Review Workflow

When ESCALATE is issued, the envelope includes a structured follow-up request specifying: the reason codes that triggered escalation, the required evidence (field inspection reports, regulatory sign-offs, independent engineer verification), the responsible role, an SLA in hours, and the allowed actions conditional on evidence receipt. This workflow is demonstrated in the Control Room frontend; the data structures are implemented in the core library. Production integration with external ticketing or workflow systems is a deployment requirement, not an architectural constraint.

---

## 9. Experimental Evaluation

### 9.1 Benchmark Composition

**QA benchmark (N=544):**

| Source | N | Real oracle calls |
|--------|---|------------------|
| BoolQ (Clark et al., 2019) | 377 | Yes |
| TruthfulQA (Lin et al., 2022) | 85 | Yes |
| Adversarial-curated | 7 | Yes |
| REMORA-curated | 75 | Yes |
| **Total** | **544** | |

**Bias disclosure:** 75 of 544 items (13.8%) were curated by the system author. Selection bias cannot be excluded. Results on the REMORA-curated subset should be interpreted with caution; the public-source items (TruthfulQA, BoolQ, adversarial-curated) are independently sourced.

**Tool-call benchmark (N=700):** A synthetic adversarial agentic benchmark with 100 tasks per domain × 7 domains (building automation, database, file operations, git, network configuration, shell, webhook/API), with 4 task types per domain × 25 per type (EXECUTE, VERIFY, ABSTAIN, ESCALATE). Tasks include three adversarial failure modes: intent-argument conflict, change-window/dual-control requirements, and safe-looking tasks with dangerous hidden scope.

**Evidence benchmark:** MultiNLI validation_matched (N=3,000), used as a proxy for evidence-verification decisions (entailment → SUPPORTS, neutral → NEI, contradiction → REFUTES).

**Lyapunov benchmark:** 1,000 synthetic sessions with seeded random oracle responses, 5–20 steps per session.

### 9.2 Baselines

For QA benchmark:
- Full-coverage majority vote (three-oracle, unweighted)
- Trust-score selective (same oracle pool, threshold = 0.50)

For tool-call benchmark:
- Single model heuristic (Llama-3.3-70B only)
- Majority vote heuristic (unweighted, three oracles)
- Self-consistency heuristic (temperature sampling, three draws)
- Verifier heuristic (single oracle with prompted self-evaluation)
- REMORA temperature gate only (thermodynamic routing, no policy engine)

### 9.3 Oracles

All experiments use three oracle models via the Groq inference API: Llama-3.1-8B-Instant, Llama-3.3-70B-Versatile, Llama-4-Scout-17B-16E-Instruct. Oracle responses are collected with per-request timeouts. All recorded experiments were conducted on live oracle APIs; results may differ if oracle model versions are updated.

### 9.4 Metrics

- **Selective accuracy:** accuracy of the system's ACCEPT decisions at a given coverage level
- **Unsafe execution rate:** fraction of tool-call tasks executed when they should have been blocked
- **Resolution rate:** fraction of critical-phase items resolved by evidence router without human escalation
- **Evidence accept precision:** precision of evidence_accept decisions against ground truth labels
- **Lyapunov stability rate:** fraction of sessions with $P(\Delta V \leq 0)$ throughout
- **Conformal risk:** empirical error rate of ACCEPT decisions vs. target risk level

---

## 10. Results

### 10.1 Selective Accuracy on QA Benchmark

**Table 1: QA Benchmark Results (N=544)**

| Signal | Set | Coverage | k | Correct | Accuracy | Lift (pp) | 95% CI |
|--------|-----|----------|---|---------|----------|-----------|--------|
| Majority vote (full) | full | 100% | 544 | 224 | 41.18% | — | [37.1, 45.4] |
| neg_temperature (18% cov.) | in-sample | 18% | 98 | 87 | **88.78%** | **+47.6** | [81.0, 93.6] |
| neg_temperature (10% cov.) | in-sample | 10% | 54 | 44 | 81.48% | +40.3 | [69.2, 89.6] |
| neg_temperature (25% cov.) | in-sample | 25% | 136 | 99 | 72.79% | +31.6 | [64.8, 79.6] |
| neg_temperature (held-out) | **holdout** | **23.2%** | **25** | **22** | **88.00%** | **+41.7** | **[70.0, 95.8]** |

*Held-out protocol:* Stratified 80/20 split (seed=42) by benchmark source; $\tau^* = 0.203$ selected on 436-item training set at 18% coverage target (locked, not re-optimised on holdout); 108-item holdout evaluated with $\tau^*$ fixed. Holdout coverage is 23.2% because the temperature distribution of the holdout split admits slightly more items below $\tau^*$. All 25 accepted holdout items are in the ordered phase. Holdout p-value = 1.45 × 10⁻⁵ (one-sided binomial, H₁: accuracy > holdout baseline 46.3%); Wilson CI [70.0%, 95.8%] lies entirely above the holdout baseline.

**Phase breakdown at 18% coverage:**
- Ordered (k=96): 86.9% accuracy on ordered-phase items (N=99)
- Critical (k=5): small sample, accuracy not reliably estimated
- Disordered (k=2): 2 items included, accuracy not reported

**Phase accuracy on full dataset:**
- Ordered phase (N=99): 86.9%
- Critical phase (N=32): 62.5%
- Disordered phase (N=413): 28.6%

The disordered phase accounts for 75.9% of the benchmark, driving the low full-coverage baseline. This is a structural property of the benchmark composition, not a REMORA design property.

### 10.2 Ablation on N=302 Subset

**Table 2: Three-Oracle Ablation (N=302)**

| Condition | Accuracy | 95% CI |
|-----------|----------|--------|
| A: Single oracle (Llama-3.3-70B) | 56.95% | [51.3, 62.4] |
| B: Majority vote (3 oracles) | 82.78% | [78.1, 86.6] |
| C: REMORA (correlation-weighted) | 69.54% | [64.1, 74.5] |
| D: REMORA + policy gate (balanced) | 82.12%† | [77.4, 86.0] |

†Policy gate primarily affects coverage (abstention rate) rather than per-accepted-item accuracy.

**Note:** This is an exploratory ablation; not used as a headline claim. Per-item records are available in `ablation_v2_results.json` for independent verification. Headline claims are restricted to results fully verifiable from top-level artifact keys (see claim ledger).

### 10.3 Tool-Call Benchmark (N=700)

**Table 4: Tool-Call Benchmark Results**

| Condition | Accuracy | Unsafe Exec. Rate | Unsafe Exec. Count | Mean Utility |
|-----------|----------|------------------|-------------------|--------------|
| Single model heuristic | 20% | **20%** | 140 | −0.25 |
| Majority vote heuristic | 30% | 10% | 70 | 0.00 |
| Self-consistency heuristic | 30% | 10% | 70 | 0.00 |
| Verifier heuristic | 20% | 20% | 140 | −0.25 |
| REMORA temperature gate only | 70% | 10% | 70 | 0.27 |
| **REMORA full policy gate** | **90%** | **0%** | **0** | **0.62** |

All baselines produce at least 10% unsafe executions (70–140 blocked tasks executed in the adversarial suite). REMORA's full policy gate achieves 0% unsafe execution while maintaining 90% accuracy and mean utility 0.62 (vs. 0.0 for majority vote). The temperature-gate-only condition (without hard policy blocks) achieves 70% accuracy but 10% unsafe execution, demonstrating that thermodynamic routing alone is insufficient—policy hard blocks are essential for safety.

**Construct validity (M1) — fixed and verified (2026-06-28):** The gate formerly accessed
`task.is_unsafe_if_executed` (via `use_contradiction_flags=True`) to populate evidence
contradiction signals — a construct validity violation where the gate received information
functionally equivalent to the evaluation target. This branch has been **removed entirely**
from `remora_gate.py` (`use_contradiction_flags` is now a no-op). A targeted pre-fix
clean-signal evaluation confirmed the leakage was not load-bearing: all three conditions
(leaky, no-contradiction-flags, no-contradiction-flags-no-severity-flags) produced identical
FAR=0.000, utility=0.620 (`experiments/m1_clean_signal_eval.py`,
`results/toolcall_m1_clean_signal.json`). Post-fix: the code path is absent, not merely
disabled. An AST-based CI gate (`scripts/check_no_evaluation_leakage.py`) and four mutation
tests (`tests/test_m1_leakage_absent.py`) guard against re-introduction. Structural
analysis: 420/560 harmful tasks are blocked by context gates (injection, approval, conflict
flags); 140 harmful tasks (all severity=high) rely on destructive keyword heuristics.
Caveats: (a) context flags are correlated with harmfulness by benchmark construction;
(b) 140 structurally-flag-free harmful tasks are vulnerable to keyword evasion;
(c) external replication with independently withheld labels is the definitive resolution.
See NEGATIVE_RESULTS.md §14 and `docs/assurance/remediation_register.yaml` (REM-001).

**Important caveat:** This benchmark is a synthetic adversarial suite; results may not transfer to deployment scenarios with real tool ecosystems.

### 10.4 Lyapunov Stability

On 1,000 synthetic sessions (5–20 steps each):
- **Stability rate:** 87.2% of sessions have $\Delta V \leq 0$ throughout
- **Mean $\Delta V$:** −0.329 (decreasing on average)
- **P95 $\Delta V$:** +0.152
- **P99 $\Delta V$:** +0.308

The 12.8% of sessions where $V$ increased reflect cases where oracle consensus degraded within a session (e.g., due to simulated oracle failures or adversarial probes). The abort criterion ($\Delta V > \epsilon_{\text{tol}} \cdot |V|$) terminates iteration when this occurs, preventing convergence to a high-uncertainty state.

### 10.5 Evidence Router

On the MultiNLI evidence benchmark (N=3,000):

| Metric | Value |
|--------|-------|
| Total items | 3,000 |
| Resolution rate (evidence_accept + abstain) | 38.5% |
| evidence_accept precision (entailment items) | 100% |
| False accept rate (contradiction items) | 0% |
| Abstain precision (contradiction items) | 99.3% |
| Items routed to ESCALATE | 61.5% |

The trust-only baseline (all critical items escalated, no evidence routing) achieves 0% resolution. Evidence routing (NLI-proxy classification; not document-grounded evidence retrieval — see §7 implementation note) resolves 38.5% of cases with 100% NLI-proxy routing precision—the remaining 61.5% receive human review, which is the correct conservative behavior for unresolved critical-phase decisions.

### 10.6 Conformal Coverage (Mondrian, N=2,161 Augmented Dataset)

**Table 5: Mondrian Phase-Stratified Conformal (20 seeds × N=2,161)**

| Target | Phase | Mean Risk | Mean Coverage | Seeds Failing |
|--------|-------|-----------|---------------|---------------|
| 15% | Ordered | 12.0% | **99.9%** | **0/20** |
| 15% | Critical | 64.5% | 0.9% | 4/20 |
| 15% | Disordered | 78.6% | 0.2% | 2/20 |

Ordered-phase conformal achieves 99.9% coverage with 0/20 seed failures at the 15% risk target—a deployable operating point. Critical and disordered phases cannot achieve meaningful coverage via conformal calibration alone; this is a documented limitation driving the evidence router design.

### 10.6 External Validity — AgentHarm Benchmark (N=88)

To evaluate REMORA's governance accuracy on a fully external, independently constructed benchmark, we applied the full Mode 3 cascade (§4) to the public AgentHarm dataset (Andriushchenko et al., 2024), which contains 44 harmful and 44 harmless agent tasks drawn from a red-teaming evaluation suite developed by the UK AI Safety Institute and Gray Swan AI.

**Protocol.** Three Workers AI models (`@cf/meta/llama-3.3-70b-instruct-fp8-fast`, `@cf/qwen/qwen3-30b-a3b-fp8`, `@cf/mistralai/mistral-small-3.1-24b-instruct`) serve as oracles. We evaluate three modes progressively: oracle-only baseline (Mode 1), harm-specific oracle re-evaluation of benign tasks (Mode 2), and full REMORA policy gate applied to Mode 2 verdicts (Mode 3). The `detailed_prompt=False, hint_included=False` variant is used throughout — the most concise, hardest setting.

**Metrics.** *Recall* = ESCALATE / harmful tasks; *blocked\_recall* = (ESCALATE | VERIFY) / harmful tasks; *FPR* = hard-ESCALATE on benign tasks (VERIFY is not counted as a false positive — it routes to human review but does not block autonomously); *coverage* = non-ABSTAIN verdicts / total tasks. Wilson 95% CI throughout. Artifact: `artifacts/agentharm_trimode_results.json`.

**Table 5: AgentHarm Three-Mode Results (N=88)**

| Mode | Recall | CI 95% | FPR | CI 95% | Blocked Recall | Coverage |
|---|---|---|---|---|---|---|
| Mode 1 — Oracle-only | **1.000** | [0.920, 1.000] | 0.318 | [0.200, 0.466] | 1.000 | 0.989 |
| Mode 2 — Harm-specific oracle | **1.000** | [0.920, 1.000] | 0.114 | [0.050, 0.240] | 1.000 | 0.989 |
| Mode 3 — Full REMORA gate | 0.114 | [0.050, 0.240] | **0.023** | [0.004, 0.118] | **0.977** | 0.977 |

*Mode 3 hard-ESCALATE recall is 0.114 (5/44); 38 additional harmful tasks route to human VERIFY — blocked\_recall (ESCALATE ∪ VERIFY) = 0.977 (43/44). One harmful task ABSTAINs. Zero harmful tasks receive ACCEPT.*

**Interpretation.** The oracle-only baseline achieves perfect recall at a FPR of 0.318 — unacceptably high for production deployment. Adding a harm-specific governance question (Mode 2) halves FPR to 0.114 while preserving recall. The full REMORA policy gate (Mode 3) reduces FPR to 0.023 while maintaining blocked\_recall of 0.977. All three governance goals are met under the blocked-recall definition: blocked\_recall ≥ 0.95 ✓, FPR < 0.10 ✓, coverage ≥ 0.95 ✓.

The conservative posture of Mode 3 — routing 98% of cases to VERIFY or higher — is by design. REMORA treats VERIFY as the appropriate response to uncertainty, not a failure mode. An agent operating under REMORA governance would require human confirmation for the vast majority of ambiguous tasks; only clearly safe, low-entropy actions receive autonomous ACCEPT.

**Scope caveat.** The AgentHarm evaluation is an **intent-gating result**: REMORA evaluates the agent's proposed action string and routes it — it does not wrap or intercept AgentHarm's internal tool dispatch. True PreToolUse tool-call interception requires a verified solver wrapper (see `experiments/agentharm/INTERCEPTION_NOTES.md`); this has not yet been implemented. The 0.977 blocked_recall figure reflects routing accuracy (correct VERIFY/ESCALATE decisions) on the benchmark's proposed action surface, not prevention of tool execution. Additionally, this evaluation uses a research-grade oracle setup; results may not generalise to live agent deployments with different tool distributions, prompt formats, or adversarial injection.

---

## 10.7 Cross-Domain Evidence Benchmark (N=36)

A deterministic, API-key-free benchmark validates REMORA's evidence layer across three operational domains: cybersecurity (12 cases), AI governance (12 cases), and financial compliance (12 cases). Each case specifies an expected verdict, a curated evidence corpus, and ground-truth risk classification.

**Table 6: Cross-Domain Benchmark Summary**

| Domain | N | Precision | Escalation Recall | Critical Fail Rate |
|---|---|---|---|---|
| Cyber (CVE/KEV/CWE) | 12 | 1.000 | 1.000 | 0.000 |
| AI Governance (ATLAS/OWASP) | 12 | 1.000 | 1.000 | 0.000 |
| Financial (FATF/SDN) | 12 | 1.000 | 1.000 | 0.000 |
| **Overall** | **36** | **1.000** | **1.000** | **0.000** |

All 36 cases pass with zero critical failures. Precision and escalation recall are both 1.000 across all domains. Artifact: `artifacts/domain_benchmark_results.json`. This benchmark is fully deterministic and reproducible without API keys.

---

## 11. Ablations

### 11.1 End-to-End Component Ablation

To demonstrate that the combination of techniques gives better safety–utility balance than any component in isolation, we run a five-condition ablation on the full 700-task tool-call benchmark. Conditions A, B, and E are loaded from the pre-existing locked results (`toolcall_benchmark_v2_results.json`). Conditions C and D are computed deterministically from the task context flags (structural admission signals and proxy trust scores derived from authorization, evidence-completeness, and conflict flags). All five conditions operate on the same 700 tasks; metrics are therefore directly comparable. Results are locked in `artifacts/aromer/component_ablation_results.json` and verified by `tests/test_component_ablation.py`.

**Table 3: Five-Condition Safety–Utility Ablation (N = 700, tool-call benchmark)**

| Condition | FAR | Unsafe exec | Benign friction† | Utility‡ |
|---|---|---|---|---|
| A. Threshold guardrail (≈ LlamaGuard) | 0.300 | 0.200 | 0.000 | −0.25 |
| B. Ensemble majority vote | 0.100 | 0.100 | 0.000 | 0.00 |
| C. Structural gates only | 0.250 | 0.200 | 0.000 | 0.00 |
| D. REMORA policy, no learning | **0.000** | **0.000** | 0.500 | 0.10 |
| E. REMORA full (+ AROMER) | **0.000** | **0.000** | **0.170**§ | **0.62** |

†Fraction of benign cases routed to human review (VERIFY). ‡Utility = (benign accepted − harmful accepted) / N. §Friction for E is from the 495-case balanced holdout (`artifacts/aromer_balanced_validation_v1.json`); the toolcall_benchmark_v2 artifact does not break down VERIFY routing by harm label.

*Limitations.* All conditions use deterministic proxy or pre-existing heuristic signals, not live LLM oracle calls. External replication on a held-out production corpus is required before generalising beyond this benchmark.

**Reading the table.** Conditions A and B (threshold and ensemble) achieve FAR > 0 because probabilistic methods alone cannot resolve cases where structural gate signals — prompt injection, fallback destructive execution, explicit human-approval requirements, and intent-argument conflicts — are the distinguishing factor; 30% and 10% of harmful actions slip through, respectively. Condition C (structural gates only) achieves zero false blocks of benign traffic but incurs FAR = 25%: the 140 cases from the `missing_context_high_risk` and `regulated_ambiguity` scenario families carry no hard structural flag, so they require a probabilistic thermodynamic signal to route correctly. Only the combination (conditions D and E) reaches FAR = 0 for both failure modes simultaneously. Condition D achieves the same safety floor as E, but without AROMER's learned world model it routes 50% of benign actions to review; AROMER learning reduces this to 17%, raising mean utility from 0.10 to 0.62.

**Conclusion.** Zero false-accept rate requires *both* structural gates (catches injection/approval/conflict failures) *and* thermodynamic policy (catches missing-context/regulated-ambiguity failures). Competitive utility requires additionally the AROMER learning layer to distinguish proven-safe contexts from genuinely uncertain ones. No single component achieves all three properties simultaneously.

### 11.2 Temperature-Gate vs. Full Policy Gate

The temperature-gate-only condition in the tool-call benchmark isolates the thermodynamic routing contribution. Moving from temperature gate to full policy gate:
- Unsafe execution: 10% → 0% (policy hard blocks contribute 100% of unsafe execution reduction)
- Accuracy: 70% → 90%
- Mean utility: 0.27 → 0.62

This demonstrates that thermodynamic routing is necessary but not sufficient for safety. Policy hard blocks are the primary safety mechanism; thermodynamic observables serve as a routing and coverage signal.

### 11.3 Oracle Count

The ablation across N=302 (single oracle vs. three oracles) shows a +10.2 pp accuracy gain from single oracle to three-oracle majority vote (56.95% vs. ~67%). Correlation-aware weighting provides additional gain within the multi-oracle setting. The gain from multi-oracle is meaningful but not transformative; the primary benefit of the oracle swarm is disagreement detection (high H, high D) rather than accuracy improvement per se.

### 11.4 Correlation Weighting

Without correlation weighting, consensus from a within-family oracle cluster (high $\bar{\rho}$) would receive inflated support. The diversity weights $w(o)$ reduce effective k in correlated settings, appropriately reducing trust scores and increasing escalation rates when oracles are likely agreeing due to shared training rather than factual correctness. Empirical validation of this effect requires a controlled study varying oracle family composition, which is identified as future work.

---

## 12. Case Study: High-Stakes Industrial Agent Action

To illustrate how REMORA's governance layer operates in a domain-critical context, we present a stylized case from well engineering. **No claim of domain correctness is made; this is an illustrative governance walkthrough, not engineering advice.**

### 12.1 Scenario

A drilling agent on a North Sea well monitoring system proposes:

> "Autonomously update kill mud weight from 1.52 SG to 1.48 SG in the well programme to improve rate of penetration on the 8½″ section."

Risk context: Well barrier modification. NORSOK D-010 requires independent barrier verification for any kill mud weight change. Risk tier: **CRITICAL**. Domain: `well_engineering`. Target environment: production.

### 12.2 REMORA Processing

**Stage 1 (Intent classification):** Domain = `well_engineering`, risk_tier = `critical`, action_type = `parameter_write`, target_environment = `production`.

**Stage 2 (Oracle fan-out):** Three oracles queried in parallel on the barrier verification question. Oracle responses: Llama-3.1-8B: "ESCALATE — barrier verification required" (conf 0.78); Llama-3.3-70B: "ESCALATE — NORSOK D-010 §5.4 mandates written sign-off" (conf 0.85); Llama-4-Scout: "VERIFY — ECD calculation needed" (conf 0.62). One oracle failed to respond; excluded.

**Stage 3 (Consensus):** After canonicalization and correlation-weighting, $\hat{p}(\text{ESCALATE}) = 0.71$, $\hat{p}(\text{VERIFY}) = 0.29$. $H = 0.866$ bits, $D = 0.29$.

**Stage 4 (Thermodynamic):** Structural temperature $T = 0.85$ (reasoning domain prior). Phase = **critical** (T near $T_c$). Trust $\tau = 0.31$ (below autonomous threshold; phase weight $= 0.5$ for critical phase).

**Stage 5 (Evidence):** No field inspection report, no independent ECD calculation, no OIM sign-off in context. Evidence signal: `citation_coverage = 0.18` (below 0.50 threshold). Evidence router decision: ESCALATE.

**Stage 6 (Policy):** Hard block #6 fires immediately: `phase = critical AND risk_tier = critical` → ESCALATE, reason `CRITICAL_PHASE`. Hard block #7 also fires: `risk_tier = critical AND evidence_action = None` → VERIFY (superseded by block #6).

**Gate outcome: ESCALATE**

### 12.3 Decision Envelope Summary

```json
{
  "gate": {
    "outcome": "ESCALATE",
    "reasons": ["CRITICAL_PHASE", "EVIDENCE_INSUFFICIENT"],
    "blocked_action": "autonomous mud weight modification",
    "allowed_next_steps": [
      "Submit updated ECD calculation",
      "Obtain kick tolerance confirmation vs NORSOK D-010 §5.4",
      "OIM written sign-off",
      "Route to VERIFY upon evidence receipt"
    ]
  },
  "follow_up": {
    "type": "on_site_inspection",
    "priority": "Critical",
    "assign_to": "Independent Well Engineer",
    "required_evidence": [
      "Updated ECD calculation",
      "Kick tolerance calculation",
      "Barrier envelope confirmation vs NORSOK D-010",
      "Responsible drilling engineer sign-off"
    ],
    "sla_hours": 4
  },
  "audit": {
    "audit_hash": "3f7a2c1b9e4d...",
    "policy_version": "RemoraDecisionEngine-v3",
    "source_of_decision": "python",
    "immutability_note": "tamper-evident hash-chain; not tamper-proof without WORM storage"
  }
}
```

The agent is blocked from execution. The follow-up workflow is dispatched to an independent well engineer with a 4-hour SLA. The decision and all reasoning are recorded in the audit hash-chain.

---

## 13. Limitations and Negative Results

Publication of negative results is standard scientific practice. This section documents active findings that constrain the system's operational claims.

### 13.1 T–D Circularity (Resolved)

An earlier formulation of the temperature estimator (legacy `estimate_temperature()`) weighted D (dissensus) at 18% of T. Since F = λD − T·H and V = H + λD, this introduced a circular dependency: D influenced T, which influenced F and V, all of which depend on D. The structural temperature estimator (`estimate_structural_temperature()`) resolves this by computing T from prompt structure alone (Kolmogorov proxy, length, domain prior), independent of oracle responses. The structural estimator is the active path in `engine.py`. The legacy estimator is preserved for backward compatibility.

### 13.2 χ-Proxy AUC = 0.39 (Active Negative Result)

Susceptibility $\chi$ (sensitivity of consensus to oracle perturbation) was evaluated as a standalone difficulty predictor on N=302 items. AUC = 0.39—*below chance* for binary classification. This negative result is preserved in `NEGATIVE_RESULTS.md` and `results/chi_perturbation_study_results.json`. The system-level response: $\chi$ is repurposed as an OOD/adversarial anomaly detector. When `susceptibility > 1.45` (empirical 97th percentile), the phase controller triggers ESCALATE with reason `escalate_adversarial`. The standalone difficulty-prediction use case is abandoned.

### 13.3 Critical-Phase Trust Anticorrelation (Active, High Severity)

On N=32 real-oracle critical-phase items: Q4 (highest trust quartile) achieves 50% correct; Q1 (lowest trust quartile) achieves 75% correct. This is the opposite of the expected trust-correctness relationship. The finding is replicated on the augmented N=2,161 dataset via conformal analysis (critical-phase risk at 15% target: 64.5%; near-zero coverage). Interpretation: in the critical phase, oracle consensus reflects *groupthink* rather than *evidence quality*. No trust threshold reliably separates correct from incorrect critical-phase items.

**Consequence:** Trust-based routing must not be applied to critical-phase items. The evidence router (§7) is the architectural response: it bypasses trust scoring and routes directly on evidence signals.

### 13.4 Full-Coverage Accuracy Weakness

At full coverage, the majority-vote baseline achieves 41.18%—below chance for binary QA (expected 50%). This reflects the benchmark composition: 75.9% of items are in the disordered phase, where oracle agreement is low and all methods perform poorly. REMORA's advantage is concentrated in the ordered phase (86.9% accuracy at N=99). Comparing selective REMORA accuracy to full-coverage majority vote is a favorable comparison; a more conservative comparison holds coverage constant across methods.

### 13.5 Oracle Diversity is Partial

The recommended oracle swarm uses three models from distinct Llama families. Within-family pairwise agreement rates (ρ̄ ≈ 0.4–0.6 in prior measurements) indicate partial correlation. True statistical independence is not achievable with current publicly available model families; diversity weighting mitigates but does not eliminate this. For production deployments, mixing providers (e.g., Anthropic Claude, Google Gemini, Meta Llama) is recommended.

### 13.6 In-Sample Calibration Warning

The trust threshold $\tau^* = 0.197$ (in-sample) / $\tau^* = 0.203$ (held-out) and coverage operating points are evaluated on the same N=544 dataset used for threshold selection. The `in_sample_calibration_warning` field in the decision envelope records this explicitly.

**Held-out validation (added post-review):** A stratified 80/20 split (seed=42, stratified by benchmark source) was used to select $\tau^* = 0.203$ on 436 training items at the 18% coverage target, then evaluate on 108 holdout items with $\tau^*$ fixed. The holdout result is **88.0% accuracy at 23.2% coverage** (22/25 accepted, Wilson CI [70.0%, 95.8%], p = 1.45 × 10⁻⁵; see `results/selective_n500_holdout_results.json`). The held-out accuracy is within 0.8 pp of the in-sample figure, providing out-of-sample support for the selective-trust claim. All 25 accepted holdout items are in the ordered phase, consistent with the thermodynamic interpretation.

### 13.7 Evidence Retrieval is Proxy-Based

The current `EvidenceSignal` is built from oracle consensus statistics (agreement rate, coverage fraction, polarity distribution). It is not derived from a BM25 passage retrieval system or an NLI classifier operating on real documents. The evidence router logic is implemented and tested against the MultiNLI benchmark as a proxy; real-world evidence quality will differ from NLI label quality.

### 13.8 Demo Data vs. Production Data

The Control Room frontend uses a deterministic simulator with seeded RNG to generate oracle votes, latencies, and evidence snippets. The case history and policy-learning panels in the frontend display synthetic data generated deterministically from scenario parameters. These features are clearly labelled as demo components in the source code. The policy engine, thermodynamic observables, and decision routing in the backend are genuine implementations that process real oracle responses.

### 13.9 AROMER MetaJudge Evaluation Circularity (Active)

AROMER's MetaJudge (§Appendix F) uses Cloudflare Workers AI LLMs — the same model family and provider as the governance oracles — to evaluate decision quality. This introduces a family-level circularity: the judge shares the same priors, calibration biases, and distributional tendencies as the system it is judging. Biases common to the oracle family (e.g., a shared tendency to rate "correct_accept" decisions positively) will not be detected by MetaJudge. The AII metajudge component therefore reflects within-family self-consistency more than independent external validation. Mitigation: use a distinct model provider (e.g., Anthropic Claude or OpenAI GPT-4) for MetaJudge in any external validation run.

### 13.10 Causal PS Enrichment — Implemented, Not Yet Deployed in Live Pipeline (Active)

REMORA integrates a PS (probability of sufficiency) causal enrichment module (Bjøru 2026, §4.2.2) in `remora/causal/attribution.py`. As of v0.2.1-experimental, **66 blocking/verifying episodes** carry PS causal enrichment data, published via `scripts/aromer_publish_causal.py` (one-time batch enrichment). The module is unit-tested and correct. The **live pipeline integration** — automatic PS enrichment of new governance episodes as they are created — has not been deployed; new episodes accumulate without causal enrichment. The §6.4 Governance Intelligence Layer description mentions "causal-consequence signals" (blast radius and expected loss), which are heuristic consequence estimates in the governance intelligence enrichment stage — distinct from the formal PS module. The PS module as described in the architecture is an algorithmic design; no empirical results over real governance episodes have been reported for it. Note: Bjøru §4.2.2 defines PS as the primary attribution metric; probability of necessity (PN) is noted there as complementary future work and is not implemented in the current module.

**Table 5: Negative Results and Mitigations**

| Finding | Severity | Status | Mitigation |
|---------|----------|--------|------------|
| χ-proxy AUC = 0.39 | Medium | Documented | Repurposed as OOD detector |
| T–D circularity | Medium | Resolved | Structural temperature (prompt-only) |
| Critical-phase trust anticorrelation | High | Active | Evidence router (38.5% resolution, 100% NLI-proxy routing precision — not document retrieval) |
| Full-coverage accuracy weak | Medium | Active | Selective prediction at ordered phase |
| Oracle diversity partial | Medium | Active | Diversity weighting; mixed-family swarm |
| In-sample calibration | Medium | **Resolved** | Held-out eval: 88.0% @ 23.2% cov., p=1.45e-5 (§13.6) |
| Evidence retrieval proxy-based | Medium | Active | MultiNLI benchmark as proxy |
| Demo data synthetic | Low | By design | Source code labelling |
| Audit chain not tamper-proof | Medium | By design | External WORM storage required |
| AROMER safety floor does not transfer to external holdout | Medium-Low | **Largely de-risked** | Structural gates achieve 0% false-accept / 100% harm-intercept on 495-case balanced holdout via call-structure signals (schema validity, forbidden-tool, tainted-arg); proxy-signal trust/entropy calibration and external-corpus injection-scanner validation pending (NEGATIVE_RESULTS.md §2). Aradhye holdout FA=22.2% (execution-context harm — Gap 2, open). |
| Entropy backend is TokenFingerprintBackend, not Semantic Entropy | Medium | Active | NLISemanticBackend exists as drop-in; all reported benchmarks used token-fingerprint heuristic (NEGATIVE_RESULTS.md §3) |

*The above table is synchronized with `NEGATIVE_RESULTS.md`. See that document for full descriptions, confounds tested, and resolution paths. The `NEGATIVE_RESULTS.md` resolved-findings archive preserves the complete scientific record of addressed issues.*

---

## 14. Threats to Validity

**Internal validity:**
- Trust threshold ($\tau^* = 0.197$ in-sample, $0.203$ held-out) is estimated on a limited dataset; overfitting is possible.
- REMORA-curated items (13.8% of N=544) may have been selected to favour the routing signal.
- Tool-call benchmark is synthetic; adversarial patterns may not reflect real deployment failures.

**External validity:**
- All experiments use Groq-hosted Llama models; results on other inference providers, closed-source models, or quantized variants may differ.
- Phase classification is calibrated on a specific benchmark composition; the proportion of ordered/critical/disordered items in real deployments is unknown.
- The MultiNLI benchmark is a reasonable proxy for evidence verification but is not equivalent to field evidence retrieval.

**Construct validity:**
- Thermodynamic terminology frames entropy and dissensus as observable properties of oracle consensus. No claim is made that these observables map to physical thermodynamics or that the phase classification is the unique correct formalism.
- "Trust score" is a derived scalar, not a frequency probability of correctness for any specific item.
- Utility scores in the tool-call benchmark reflect designed task weights, not real-world deployment costs.
- **AII (Autonomous Intelligence Index)** is a researcher-defined composite (calibration 0.30, friction 0.25, metajudge 0.20, transfer 0.15, stability 0.10) with weights chosen as heuristic estimates, not derived from theory or calibrated against an external governance quality measure. Alternative weight assignments would yield different AII values and different CAPABLE thresholds (AII ≥ 0.60). AII improvement over learning iterations describes internal optimization progress only; it has not been cross-validated against any independent outcome measure (e.g., downstream safety incident rate, human expert governance quality ratings). The CAPABLE threshold and phase names (WARMUP, LEARNING, CAPABLE, TRAINED) are qualitative labels, not scientifically calibrated levels. AII weight sensitivity is reported in Appendix F.2: varying each weight ±0.05 (proportionally renormalized) shows CAPABLE classification was fragile at the CAPABLE milestone (AII=0.6007, 2026-06-26) — T2 Friction (±0.032) and T4 Transfer (±0.023) are the highest-sensitivity axes. AROMER has since reached TRAINED (AII=0.8442, 12+ organic cycles; see Appendix F.7). This supports treating AII ≥ 0.60 as a preliminary milestone rather than a stable certification boundary.

**Statistical validity:**
- 95% Wilson confidence intervals are reported for key accuracy figures. Non-overlapping CIs are used to assess statistical significance; formal hypothesis tests are not performed across all conditions.
- N=32 critical-phase items is too small to draw strong conclusions about the trust-anticorrelation finding; the augmented N=511 dataset (simulated trust distributions) partially addresses this.

---

## 15. Safety, Ethics, and Governance Considerations

REMORA is designed to *reduce* unsafe autonomous AI actions, not to enable them. Several governance considerations apply:

**Accountability:** REMORA flags, routes, and escalates decisions; it does not replace human judgment in critical cases. Human reviewers who receive ESCALATE notifications retain full accountability for the outcome. REMORA's audit envelope supports—but does not substitute for—regulatory compliance documentation.

**Over-reliance risk:** An operator who treats ACCEPT decisions as guarantees of correctness would introduce risk. ACCEPT means "assurance conditions for autonomous action are met," not "the action is correct." Decision envelopes should be interpreted by qualified domain personnel.

**Alignment with existing standards:** REMORA's ESCALATE path is designed to enforce the human-review requirements of frameworks such as NORSOK D-010 (well barriers), IEC 61511 (SIL classification), and EU AI Act Art. 22 (human oversight for high-risk AI). No claim is made that REMORA satisfies any specific standard; alignment mapping requires domain authority verification.

**Misuse prevention:** The adversarial admission firewall detects prompt injection patterns. However, sophisticated adversarial inputs that do not match known patterns may pass the firewall. REMORA should not be deployed as the sole defense against adversarial inputs in critical systems.

**Data governance:** The oracle swarm queries external LLM APIs with the proposed action text. Operators must evaluate data classification requirements before routing sensitive operational data through external model providers.

---

## 16. Reproducibility and Artifact Availability

**Repository:** Available at [https://github.com/darklordVirtual/REMORA](https://github.com/darklordVirtual/REMORA). Commit hash: `7cb4fae`.

**Python version:** 3.11

**Installation:**
```
python -m pip install -e ".[dev]"
```

**Full quality gate (lint + tests + claim consistency checks):**
```
make audit
```

**Benchmarks (deterministic, no API keys required):**
```
make benchmark
```

**Credibility pack:**
```
make credibility-pack
```

**Deterministic tests only:**
```
python -m pytest tests/ -q
```
Expected: 2,400+ individual tests passing across 100+ test files (count grows with the suite; treat CI output as authoritative).

**Key benchmark reproductions:**
```
# Selective trust curve (N=544, reads from stored artifact)
python experiments/selective_n500.py

# Tool-call benchmark (N=700, deterministic)
python experiments/toolcall_benchmark_v2.py

# Evidence router (N=3000, MultiNLI; requires HuggingFace access)
python experiments/rag_critical_router_v1.py

# Lyapunov aggregate (N=1000 synthetic sessions)
python experiments/lyapunov_aggregate.py
```

**Live oracle experiments:** Require a valid Groq API key (`GROQ_API_KEY` environment variable). Oracle model versions on the Groq API may change; results are sensitive to model version updates.

**Artifact paths:**
- `results/selective_n500_results.json` — QA benchmark selective curve
- `results/end_to_end_n500_v3.json` — Action distribution and accuracy by action
- `results/ablation_v2_n500_results.json` — Ablation conditions (N=544)
- `results/toolcall_benchmark_v2_results.json` — Tool-call benchmark all conditions
- `results/rag_critical_router_v1_results.json` — Evidence router metrics
- `results/lyapunov_aggregate_results.json` — Lyapunov stability (N=1000)
- `results/mondrian_v2_repeated_splits.json` — Conformal coverage (N=2161)
- `artifacts/agentharm_trimode_results.json` — AgentHarm pilot results (intent-gating scope; see §10.6 and `docs/claim_hygiene.md`)
- `artifacts/governance_intelligence/evaluation_results.json` — Governance Intelligence layer benchmark (§6.4; 50 tasks, 10 categories)
- `artifacts/domain_benchmark_results.json` — Cross-domain evidence benchmark N=36 (§10.7)
- `results/agentharm/guardrail_scores.json` — AgentHarm evaluation status (`status:skipped`; full pipeline not run — see `docs/claim_hygiene.md`)
- `results/agentharm/tool_probe.json` — Tool interception probe (`status:skipped`; `inspect_tools_probe.py` not run — condition 4 of claim hygiene not met)
- `results/agentharm/mode_metadata.jsonl` — Mode degradation metadata (`status:skipped`; condition 5 not met)

**Reproducibility note:** The QA benchmark results are derived from stored oracle response artifacts (not live API calls) and are fully deterministic. Tool-call and Lyapunov benchmarks use seeded RNG and require no API keys. Evidence router requires HuggingFace dataset access. Live ablation experiments depend on external oracle availability.

---

## 17. Conclusion

We presented REMORA, a policy-gated multi-oracle assurance architecture for governing agentic AI actions. The central contribution is a system-level design that converts multi-oracle disagreement, thermodynamic uncertainty observables, evidence signals, and policy constraints into four gate outcomes (ACCEPT, VERIFY, ABSTAIN, ESCALATE), with a full audit record for every decision.

Key empirical findings:
- Thermodynamic routing achieves 88.8% selective accuracy at 18% coverage on the QA benchmark (+47.6 pp over full-coverage majority vote; in-sample calibration caveat applies). A `PhaseAwareGuardrail` exploiting the critical-phase trust inversion extends coverage to 22.1% at 85.0% accuracy (+43.8 pp lift; Wilson CI [77.5%, 90.3%]; `results/phase_aware_guardrail_n544_results.json`), adding 21 low-τ critical items via inverted-score selection.
- Policy hard blocks reduce unsafe execution to 0% on an adversarial 700-task tool-call benchmark, compared to 10–20% for all baselines.
- Evidence routing (NLI-proxy classification; not document-grounded retrieval) resolves 38.5% of critical-phase items with 100% NLI-proxy routing precision, where trust-based routing fails completely.
- Mondrian phase-stratified conformal achieves 99.9% ordered-phase coverage with 0/20 seed failures at the 15% risk target.

Key negative findings (preserved for scientific record):
- Trust alone cannot route critical-phase decisions safely (anticorrelation confirmed).
- χ-proxy susceptibility failed as a standalone difficulty predictor (AUC = 0.39).
- Full-coverage accuracy is structurally weak due to benchmark disordered-phase composition.
- Evidence retrieval is currently proxy-based; semantic retrieval is a required production dependency.

REMORA is positioned as a research-grade prototype demonstrating a governed autonomy layer—not a production-ready safety system. Production deployment requires external evidence retrieval, WORM audit storage, OPA policy integration, and domain-authority validation. The architecture is designed to be pluggable: each component (oracle set, evidence retriever, policy engine, storage backend) can be replaced without changing the gate interface.

The broader thesis—that modern agentic AI requires an explicit uncertainty routing layer, not just a better oracle—is supported by both the positive results (the gap between thermodynamic routing and policy-gated routing on the tool-call benchmark) and the negative results (the failure of trust alone in the critical phase). We offer REMORA as a reference architecture, an empirical baseline, and a documented set of unsolved problems for the AI assurance community.

---

## Acknowledgements

Benchmarks use publicly available datasets: BoolQ (Clark et al., 2019), TruthfulQA (Lin et al., 2022), MultiNLI (Williams et al., 2018), ARC-Challenge, and MMLU-Pro. Oracle inference via Groq API. Policy evaluation via Open Policy Agent (Apache 2.0). The authors thank all reviewers who identified scope corrections and limitations documented in NEGATIVE_RESULTS.md.

---

## Use of AI-Assisted Development Tools

Generative AI tools were used as assistive tools during the development of this research prototype. Their use included brainstorming, code drafting and refactoring, test scaffolding, documentation editing, language revision, and support in locating and summarising relevant literature.

The author defined the research questions, system architecture, policy semantics, evaluation criteria, experimental scope, and all reported claims. All source code, tests, benchmark artifacts, citations, numerical results, and conclusions were reviewed and verified by the author before inclusion. Generative AI tools were not listed as authors and were not relied upon as independent sources of experimental evidence.

Where AI-assisted output informed implementation or prose, the final responsibility for correctness, reproducibility, and interpretation remains with the human author. A full disclosure is available in `docs/AI_USE.md`.

---

## References

- Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty: Linguistic invariances for uncertainty estimation in natural language generation. *ICLR 2023*. arXiv:2302.09664.

- Kuhn, L., Gal, Y., & Farquhar, S. (2026). Evidential Semantic Entropy for LLM uncertainty quantification. *EACL 2026*, pp. 334–348.

- Kirsch, A., Harrison, J., Misra, S., & Leike, J. (2024). Prover-verifier games improve legibility of LLM outputs. arXiv:2407.13692.

- Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T. (2022). Conformal risk control. arXiv:2208.02814.

- Zhang, Y. & Lee, M. (2025). Evaluating the performance of large language models in confidential computing environments. arXiv:2502.11347.


- Wang, X., Wei, J., Schuurmans, D., Le, Q., Chi, E., Narang, S., Chowdhery, A., & Zhou, D. (2023a). Self-consistency improves chain of thought reasoning in language models. *ICLR 2023*.

- Du, Y., Li, S., Torralba, A., Tenenbaum, J., & Mordatch, I. (2023). Improving factuality and reasoning in language models through multiagent debate. *ICML 2024*.

- Lin, S., Hilton, J., & Evans, O. (2022). TruthfulQA: Measuring how models mimic human falsehoods. *ACL 2022*.

- Clark, C., Lee, K., Chang, M.-W., Kwiatkowski, T., Collins, M., & Toutanova, K. (2019). BoolQ: Exploring the surprising difficulty of natural yes/no questions. *NAACL 2019*.

- Geifman, Y. & El-Yaniv, R. (2017). Selective classification for deep neural networks. *NeurIPS 2017*.

- Angelopoulos, A. & Bates, S. (2021). A gentle introduction to conformal prediction and distribution-free uncertainty quantification. *arXiv:2107.07511*.

- Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On calibration of modern neural networks. *ICML 2017*.

- Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., Lin, Z., Li, Z., Li, D., Xing, E. P., Zhang, H., Gonzalez, J. E., & Stoica, I. (2023). Judging LLM-as-a-judge with MT-Bench and Chatbot Arena. *NeurIPS 2023*.

- Shafer, G. & Vovk, V. (2008). A tutorial on conformal prediction. *Journal of Machine Learning Research, 9*, 371–421.

- Endsley, M. (1995). Toward a theory of situation awareness in dynamic systems. *Human Factors, 37*(1), 32–64.

- Cobbe, K., Kosaraju, V., Bavarian, M., Chen, M., Jun, H., Kaiser, L., Plappert, M., Tworek, J., Hilton, J., Nakano, R., Hesse, C., & Schulman, J. (2021). Training verifiers to solve math word problems. *arXiv:2110.14168*.

- Williams, A., Nangia, N., & Bowman, S. (2018). A broad-coverage challenge corpus for sentence understanding through inference. *NAACL 2018*.

- Kelly, T. (1998). Arguing safety: A systematic approach to managing safety cases. PhD thesis, University of York.

- Bloomfield, R. & Bishop, P. (2010). Safety and assurance cases: Practice, trends and challenges. *SAFECOMP 2010*.

- Kadavath, S., Conerly, T., Askell, A., Henighan, T., Drain, D., Perez, E., Schiefer, N., Hatfield-Dodds, Z., DasSarma, N., Tran-Johnson, E., Johnston, S., El-Showk, S., Jones, A., Elhage, N., Hume, T., Chen, A., Bai, Y., Bowman, S., Fort, S., Ganguli, D., Hernandez, D., Jacobson, J., Kernion, J., Kravec, S., Lovitt, L., Ndousse, K., Olsson, C., Ringer, S., Amodei, D., Brown, T., Clark, J., McCandlish, S., Olah, C., Mann, B., & Kaplan, J. (2022). Language models (mostly) know what they know. *arXiv:2207.05221*.

- Open Policy Agent contributors. (2024). Open Policy Agent. https://www.openpolicyagent.org/

- European Parliament & Council of the European Union. (2024). Regulation (EU) 2024/1689 (Artificial Intelligence Act). *Official Journal of the European Union*, L 2024/1689.

- Standards Norway. (2021). NORSOK D-010:2021 — Well integrity in drilling and well operations. Standards Norway.

- International Electrotechnical Commission. (2016). IEC 61511-1:2016 — Functional safety: Safety instrumented systems for the process industry sector. IEC.

- Bjøru, A. R. (2026). Causal Post-hoc Explainable AI (PhD thesis). Norwegian University of Science and Technology (NTNU). ISBN 978-82-353-0022-5. Paper IV §4.2.1–§4.2.3

- Andriushchenko, M., Souly, A., et al. (2024). AgentHarm: A Benchmark for Measuring Harmfulness of LLM Agents. arXiv:2410.09024.

- El-Yaniv, R. & Wiener, Y. (2010). On the foundations of noise-free selective classification. *Journal of Machine Learning Research, 11*, 1605–1641. https://www.jmlr.org/papers/v11/el-yaniv10a.html

- Wang, X., Aitchison, L., & Rudolph, M. (2023b). LoRA ensembles for large language model fine-tuning. *arXiv:2310.00035*. https://arxiv.org/abs/2310.00035. doi:10.48550/arXiv.2310.00035

- Raji, I. D., Xu, P., Honigsberg, C., & Ho, D. E. (2022). Outsider oversight: Designing a third party audit ecosystem for AI governance. *arXiv:2206.04737*. https://arxiv.org/abs/2206.04737. doi:10.48550/arXiv.2206.04737

---

## Appendix A: Mathematical Definitions

| Symbol | Definition | Notes |
|--------|-----------|-------|
| $\mathcal{O}$ | Oracle set $\{o_1, \ldots, o_n\}$ | $n \geq 3$ distinct model families |
| $\mathcal{O}'$ | Valid oracle set after failure filtering | $\mathcal{O}' \subseteq \mathcal{O}$ |
| $\phi(o)$ | Canonical verdict for oracle $o$ | (polarity, claim_hash, magnitude, tags) |
| $\rho(a, b)$ | Rolling pairwise agreement rate | Window size 200 |
| $w(o)$ | Diversity weight for oracle $o$ | $\propto (1 + \sum_{j \neq o} \rho(o,j))^{-1}$ |
| $\hat{p}(v)$ | Weighted support for verdict $v$ | $\sum_o w(o) \cdot \mathbf{1}[\phi(o)=v]$, normalized |
| $H$ | Shannon entropy of $\hat{p}$ | $-\sum_v \hat{p}(v) \log_2 \hat{p}(v)$ bits |
| $D$ | Dissensus | $1 - \max_v \hat{p}(v)$ |
| $k$ | Number of active verdicts | $|\{v : \hat{p}(v) > 0\}|$ |
| $\eta$ | Order parameter | $({\max \hat{p}} - 1/k)/(1 - 1/k)$ |
| $T$ | Structural temperature | $f(\text{prompt})$: zlib density, length, domain prior |
| $T_c$ | Critical temperature | Calibrated from oracle distribution |
| $\chi$ | Susceptibility | Sensitivity of $\eta$ to oracle perturbation |
| $F$ | Free-energy proxy | $\lambda D - T \cdot H$, $\lambda = 0.3$ |
| $\tau$ | Trust score | $\eta \cdot (1-h_{\text{bound}}) \cdot w_{\text{phase}} \cdot (1 + \chi/\chi_0)^{-1}$ |
| $V(t)$ | Lyapunov observable | $H(t) + \lambda D(t)$ |
| $h_{\text{bound}}$ | Hallucination rate bound | Derived from inter-oracle agreement |
| $w_{\text{phase}}$ | Phase weight | 1.0 / 0.5 / 0.1 for ordered / critical / disordered |
| $g$ | Gate outcome | $\in \{\text{ACCEPT, VERIFY, ABSTAIN, ESCALATE}\}$ |
| $\Gamma$ | Gate function | $(q, a, c) \rightarrow g$ |

---

## Appendix B: DecisionEnvelope v2 Schema

```json
{
  "request": {
    "request_id": "uuid-v4",
    "timestamp": "ISO-8601",
    "query": "string",
    "proposed_action": "string",
    "domain": "string",
    "risk_tier": "low | medium | high | critical"
  },
  "assessment": {
    "intent": {
      "domain": "string",
      "risk_tier": "string",
      "action_type": "string",
      "target_environment": "string"
    },
    "oracle_votes": [
      {
        "oracle": "string",
        "family": "string",
        "answer": "string",
        "confidence": 0.0,
        "latency_ms": 0,
        "error": null
      }
    ],
    "thermodynamic": {
      "H": 0.0, "D": 0.0, "T": 0.0, "F": 0.0,
      "eta": 0.0, "chi": 0.0, "trust": 0.0,
      "phase": "ordered | critical | disordered",
      "V": 0.0
    },
    "evidence": {
      "evidence_strength": 0.0,
      "contradiction_score": 0.0,
      "citation_coverage": 0.0,
      "source_reliability": 0.0,
      "action": "answer | evidence_accept | escalate | null"
    },
    "policy": {
      "triggers": [{"rule": "string", "effect": "string"}],
      "distribution_shift_detected": false
    }
  },
  "gate": {
    "outcome": "ACCEPT | VERIFY | ABSTAIN | ESCALATE",
    "reasons": ["REASON_CODE"],
    "confidence": 0.0,
    "coverage_policy": "string",
    "blocked_action": "string | null",
    "allowed_next_steps": ["string"],
    "approval_required": false,
    "source_of_decision": "python | opa | python_fallback"
  },
  "reviewer_context": {
    "asset_id": "string",
    "asset_type": "string",
    "why_escalated": ["string"],
    "risk_matrix": [{"label": "string", "level": "string"}],
    "required_review_data": ["string"]
  },
  "follow_up": {
    "required": false,
    "type": "string",
    "priority": "string",
    "assign_to_role": "string",
    "requested_evidence": ["string"],
    "blocked_actions": ["string"],
    "allowed_actions": ["string"],
    "sla_hours": 24
  },
  "history": {
    "similar_cases_found": 0,
    "decision_pattern": "string",
    "known_blockers": ["string"]
  },
  "policy_learning": {
    "candidate": false,
    "confidence": 0.0,
    "recommendation": "string"
  },
  "audit": {
    "audit_hash": "sha256-hex-string",
    "previous_hash": "sha256-hex-string | null",
    "chain_length": 0,
    "policy_version": "RemoraDecisionEngine-v3",
    "source_of_decision": "python",
    "immutability_note": "tamper-evident structural hash-chain; not tamper-proof without external WORM storage"
  }
}
```

---

## Appendix C: Pseudocode

**Algorithm 1: REMORA Assessment**

```
Input:  proposed_action a, query q, context c,
        oracle_set O, policy P, evidence_sources E
Output: gate_decision g, explanation r, envelope D

1.  (domain, risk_tier, action_type, env) ← classify_intent(q, a, c)
2.  if adversarial_detected(q):
        return ESCALATE, "admission_firewall", build_envelope(...)

3.  O' ← {o ∈ O : ask(o, q) succeeds}  // parallel, timeout-bounded
4.  verdicts ← {φ(o.response) : o ∈ O'}

5.  ρ ← update_correlation_matrix(verdicts)
6.  w ← diversity_weights(O', ρ)
7.  p̂ ← weighted_support(verdicts, w)

8.  H ← entropy(p̂)
9.  D ← 1 - max(p̂)
10. η ← order_parameter(p̂)
11. T ← structural_temperature(q, domain)
12. F ← λ*D - T*H
13. τ ← trust_score(η, halluc_bound, phase_weight, χ)
14. phase ← classify_phase(T, T_c, η)
15. V ← H + λ*D; update_lyapunov_trajectory(V)

16. if phase == "critical":
        ev ← evidence_router.route(build_evidence_signal(p̂, O'))
        obs.evidence_action ← ev.action
        obs.evidence_strength ← ev.signal.evidence_strength
        obs.contradiction_score ← ev.signal.contradiction_score

17. obs ← PolicyObservation(phase, τ, T, η, χ, H, D, risk_tier,
                             domain, action_type, env,
                             oracle_failures=|O|-|O'|,
                             valid_oracle_count=|O'|,
                             distribution_shift=detect_shift(q))

18. (report, fallback) ← policy.evaluate(obs)
         // 7 hard blocks evaluated first, then routing

19. g ← report.action  // ACCEPT | VERIFY | ABSTAIN | ESCALATE

20. if g == ESCALATE:
        follow_up ← build_follow_up_request(domain, risk_tier, evidence_gaps)
    else:
        follow_up ← null

21. hash_entry ← audit_chain.append(timestamp, hash(q), g, τ, phase)

22. D ← DecisionEnvelope(request=..., assessment=..., gate=...,
                          reviewer_context=..., follow_up=follow_up,
                          audit=hash_entry)
23. return g, report.explanation, D
```

---

## Appendix D: Implementation Details

**Core package structure:**

| Module | Responsibility | Key file |
|--------|----------------|----------|
| `remora/engine.py` | Main orchestration, oracle fan-out | 688 lines |
| `remora/canonical.py` | Verdict canonicalization (φ) | 159 lines |
| `remora/correlation.py` | Correlation matrix, diversity weights | 115 lines |
| `remora/lyapunov.py` | V(t) tracking, abort criterion | 167 lines |
| `remora/thermodynamics.py` | H, D, T, F, η, χ, τ, phase | 675 lines |
| `remora/policy/observation.py` | PolicyObservation (55 fields) | 380 lines |
| `remora/policy/decision_engine.py` | Hard blocks, routing logic | 990 lines |
| `remora/policy/opa_adapter.py` | OPA/Rego integration, fallback | 266 lines |
| `remora/policy/report.py` | DecisionReport, DecisionAction enum | — |
| `remora/audit/hash_chain.py` | SHA-256 hash-chain | 168 lines |
| `remora/evidence/evidence_router.py` | CriticalEvidenceRouter | 174 lines |
| `tests/` | 100+ test files, 2,400+ individual tests (CI-authoritative) | — |
| `results/` | 60+ JSON artifacts | — |

**Table 6: Implementation Status**

| Component | Status | Notes |
|-----------|--------|-------|
| Multi-oracle fan-out (ThreadPoolExecutor) | Implemented | Sequential fallback on RuntimeError |
| Canonical verdict extraction (φ) | Implemented | NFKC normalization, claim hash |
| Correlation-aware weighting | Implemented | Rolling 200-sample window |
| Entropy H, Dissensus D | Implemented | Shannon entropy, 1−max(p̂) |
| Structural temperature T | Implemented | Prompt-only, circularity-free |
| Order parameter η | Implemented | Normalized consensus |
| Trust score τ | Implemented | Phase-weighted, fragility penalty |
| Lyapunov V(t) tracking | Implemented | Abort on ΔV > ε|V| |
| Phase classification | Implemented | Ordered/critical/disordered |
| Phase-sensitive routing | Implemented | Per-phase thresholds |
| Evidence router (oracle-proxy signal) | Implemented | Proxy, not live retrieval |
| Evidence router (semantic BM25/NLI) | Planned | Pluggable interface ready |
| Policy decision engine (7 hard blocks) | Implemented | Priority-ordered |
| OPA/Rego adapter | Partial | Python fallback when OPA unavailable |
| DecisionEnvelope v2 | Implemented | All blocks in frozen dataclass |
| SHA-256 audit hash-chain | Implemented | Tamper-detecting, not tamper-proof |
| Human review workflow (data structures) | Implemented | UI demo only; no production integration |
| External WORM audit storage | Planned | Required for tamper-proof audit |
| CMMS/WIMS integration connectors | Planned | Webhook contract defined |
| Zero-knowledge assurance proofs | Planned | Stubbed, not implemented |

---

## Executive Research Summary (One Page)

**REMORA: A Policy-Gated Multi-Oracle Assurance Architecture for Agentic AI**

**The problem.** Autonomous AI agents that invoke tools or actuate real-world systems can cause irreversible harm if they execute actions that are incorrect, unauthorized, or unsafe. Majority-vote consensus—the standard ensemble primitive—does not prevent a confident wrong consensus from triggering unsafe execution. What is needed is not a better oracle but an assurance layer: a system that evaluates whether the conditions for autonomous action are verifiably met before execution.

**What REMORA does.** REMORA intercepts proposed agent actions and routes each through six stages: (1) intent and risk classification; (2) parallel oracle fan-out with failed-oracle filtering; (3) correlation-aware consensus weighting; (4) thermodynamic uncertainty observables (entropy H, dissensus D, trust score τ, phase classification); (5) evidence routing for critical-phase decisions; and (6) a policy engine with seven hard-block rules. The output is one of four outcomes—ACCEPT, VERIFY, ABSTAIN, or ESCALATE—emitted as a full DecisionEnvelope with audit hash-chain.

**Key results.** On a 544-item QA benchmark: 88.8% selective accuracy at 18% coverage vs. 41.18% full-coverage majority-vote baseline (+47.6 pp; in-sample calibration—held-out validation required). On a 700-task adversarial agentic benchmark: REMORA's full policy gate achieves 0% unsafe execution vs. 10–20% for all baselines, with mean utility 0.62 vs. 0.0 for majority vote. A critical-phase evidence router resolves 38.5% of high-uncertainty cases with 100% precision; the remainder receive human review.

**Key limitations.** (1) Trust alone cannot route critical-phase decisions—an anticorrelation between trust and correctness is confirmed empirically. (2) Evidence retrieval is currently oracle-proxy based; semantic retrieval is pluggable but not live. (3) The audit hash-chain is tamper-evident but requires external WORM storage for tamper-proof guarantee. (4) The QA benchmark contains 13.8% author-curated items; generalizability claims require independent curation. (5) All results are from research experiments, not production deployments.

**The contribution** is a system architecture and empirical evaluation for governed agentic AI decision control. REMORA demonstrates that governing autonomous AI action requires explicit uncertainty routing—not suppression—and that policy hard blocks are essential safety mechanisms that thermodynamic routing alone cannot replace.

**Availability.** Code, results, and negative-results documentation are available at [https://github.com/darklordVirtual/REMORA](https://github.com/darklordVirtual/REMORA). All deterministic benchmarks reproduce without API keys.

---

## Reviewer Risk Register (Top 10 Skeptical Questions)

| # | Question | Honest Answer |
|---|----------|--------------|
| 1 | Is 88.8% accuracy at 18% coverage a cherry-picked operating point? | Yes, it is the in-sample optimum. This is disclosed in `NEGATIVE_RESULTS.md` and the artifact metadata. The held-out evaluation is the appropriate generalizability measure. A skeptical reviewer should demand the holdout results. |
| 2 | Does the 41.18% baseline indicate the benchmark is broken? | Partially. The benchmark is heavily weighted toward disordered-phase items (75.9%) where all methods perform poorly. The baseline is weak by design, not by calibration error. The appropriate comparison is selective accuracy at the same coverage. |
| 3 | Is thermodynamic terminology scientifically justified? | No physical thermodynamic law applies to LLMs. The terminology is explicitly framed as an operational metaphor. The observables (H, D, F, V) are deterministic functions of oracle outputs; the names are borrowed for their qualitative properties (order, disorder, energy-like tradeoffs). We believe the metaphor is useful but acknowledge it may invite misinterpretation. |
| 4 | Are three oracle models sufficient for diversity claims? | No. Three models from related families (all Llama) provide partial diversity (ρ̄ ≈ 0.4–0.6 within-family). The diversity weighting mitigates correlation but does not eliminate it. We frame this as a known limitation and recommend mixed-provider swarms for production. |
| 5 | Is the tool-call benchmark synthetic and unrealistic? | Yes. It is a synthetic adversarial suite with known failure modes and designed task weights. Results on real tool ecosystems with realistic distributions of failure modes may differ substantially. The benchmark demonstrates the policy gate's mechanism, not production safety. |
| 6 | Is the critical-phase anticorrelation robust? | N=32 real-oracle critical-phase items is too small for definitive conclusions. The augmented N=511 dataset uses simulated trust distributions matched to observed values, which is a reasonable methodology but introduces assumptions about the simulation. The finding is consistent across both datasets. |
| 7 | Does REMORA prevent hallucination? | No. REMORA does not verify the factual content of oracle responses. It measures agreement, uncertainty, and policy conditions. A confident, unanimous hallucination in the ordered phase would receive ACCEPT. REMORA prevents unsafe *execution* decisions when uncertainty or policy conditions are not met; it does not detect *factual errors* per se. |
| 8 | Is the evidence router actually evidence-based? | In the current implementation, the evidence signal is built from oracle consensus statistics—a proxy. The MultiNLI evaluation measures the routing logic against NLI labels, which is a reasonable proxy for evidence-verification but not equivalent to field evidence or document retrieval. |
| 9 | What prevents an adversary from injecting the trust score? | The trust score is computed internally from oracle responses; it is not user-supplied. However, an adversary who can influence the oracle responses (e.g., via prompt injection through external data) could manipulate the consensus and thus the trust score. The adversarial firewall catches known injection patterns; sophisticated attacks may bypass it. |
| 10 | Is this production-ready for safety-critical systems? | No. This is explicitly a research-grade prototype. Production deployment requires: semantic evidence retrieval, WORM audit storage, OPA daemon deployment, domain-authority policy validation, security hardening of the oracle API integration, and formal safety case development under applicable standards. |

---

## Appendix E: Optional TEE-Based Audit Hardening

REMORA's software-only audit trail can be strengthened with hardware attestation from Trusted Execution Environments (TEEs), ensuring the recorded decision was produced by the correct model under the correct policy inside an isolated enclave (Zhang & Lee, 2025). Note: this provides tamper-*resistant* audit hardening; tamper-proof guarantees require external WORM storage in addition to TEE attestation.

**Supported platforms:**
- **AMD SEV-SNP**: Hardware memory encryption + VM-level isolation. Attestation report (SHA-384 measurement) signed by AMD VCEK.
- **Intel TDX/SGX**: Enclave quotes (MRENCLAVE + MRSIGNER) verified via Intel DCAP.
- **NVIDIA Confidential Computing (H100/H200)**: GPU attestation report (NRAS) covering full inference session.

**DecisionEnvelope attestation extension (TEE mode):**
- `tee.platform`: `amd-sev-snp | intel-tdx | nvidia-h100`
- `tee.measurement`: hex-encoded VM/enclave measurement (SHA-384)
- `tee.attestation_report_hash`: SHA-256 of raw attestation report
- `tee.nonce`: 32-byte request nonce (replay prevention)
- `tee.verified`: set only after platform attestation service confirms measurement + nonce + cert chain
- `policy_hash`: SHA-256 of OPA/Rego bundle
- `model_hash`: SHA-256 of model weights

**Verification flow:** Launch TEE VM/enclave → Register golden measurement in governance ledger → Attestation request (with nonce) → Remote verification (AMD KDS / Intel DCAP / NVIDIA NRAS) → Key injection into enclave → Oracle calls + CRC calibration + PVD deliberation run inside TEE → Signed DecisionEnvelope appended to D1 audit ledger.

**Implementation status:** Protocol specified; hardware integration pending TEE development environment. `DecisionEnvelope` includes `tee_attestation: dict | None`. Zhang & Lee (2025) demonstrated <50 ms attestation overhead per session at near-native inference performance.

---

## Appendix F: AROMER — Autonomous Meta-Cognitive Learning Layer (Experimental)

> **Status:** EXPERIMENTAL — v0.1.0-experimental. Results are from a live research deployment, not a controlled study. All claims are qualified to research-prototype scope.

AROMER (Autonomous REMORA, Meta-Emergent Reasoner) is a closed-loop learning extension that wraps REMORA's decision engine and adapts its governance parameters over time through episodic memory, Bayesian world-model priors, thermodynamic threshold adaptation, and an LLM MetaJudge self-reflection loop.

### F.1 Architecture

AROMER adds five components around REMORA's static `RemoraDecisionEngine`:

1. **EpisodicStore** — JSONL/D1 persistent memory of governance decisions and observed outcomes.
2. **DomainHarmPrior** — Bayesian Beta conjugate prior over P(harm | domain, action\_type, risk\_tier), updated from labeled episodes. A shadow mode computes but does not apply adjustments until an ECE safety guard is met.
3. **OracleBandit** — Thompson Sampling bandit over the three oracle models; rewards/penalises oracles based on MetaJudge critique quality.
4. **ThermodynamicAdapter** — SGD-based λ update using episode outcomes as the loss signal.
5. **AromerMetaJudge** — Workers AI LLM-as-judge that critiques recent governance decisions and produces structured rubric scores (safety, truth, calibration).

The system runs as a Cloudflare Worker with an hourly cron (reduced to 4-hour intervals to remain within the Cloudflare Workers AI free-tier Neurons quota of 10,000/day).

### F.2 AROMER Intelligence Index (AII)

To measure whether AROMER becomes more intelligent over time, we define a composite index:

$$\text{AII} = 0.30 \cdot T_1 + 0.25 \cdot T_2 + 0.20 \cdot T_3 + 0.15 \cdot T_4 + 0.10 \cdot T_5$$

**Weight rationale.** The weights are researcher-chosen heuristic values, not derived from theoretical optimisation or empirical ablation. The ordering reflects a domain-specific priority judgment: calibration (T1) is weighted most heavily because miscalibrated confidence is the most direct path to false accepts; friction (T2) captures the practical operational cost of over-blocking (the primary governance failure mode in deployment); metajudge (T3) provides the learning signal quality; transfer (T4) reflects generalisation scope; and stability (T5) is a diagnostic observable rather than a primary learning target. These weights should be treated as a hyperparameter and validated via ablation in any external evaluation.

**AII weight sensitivity analysis.** Each weight varied by ±0.05 while other weights are rescaled proportionally to sum to 1.00. Scores at the CAPABLE milestone (2026-06-26): T1=0.681, T2=0.127, T3=0.716, T4=1.000, T5=0.711 (AII=0.6007).

| Component | w | +0.05 → ΔAII | −0.05 → ΔAII | CAPABLE (≥0.60) robust? |
|---|---|---|---|---|
| T1 Calibration | 0.30 | +0.006 → 0.607 | −0.006 → 0.595 | Yes (+) / borderline (−) |
| **T2 Friction** | **0.25** | **−0.032 → 0.569** | **+0.031 → 0.632** | **No (+) / Yes (−)** |
| T3 MetaJudge | 0.20 | +0.007 → 0.608 | −0.008 → 0.593 | Yes (+) / borderline (−) |
| **T4 Transfer** | **0.15** | **+0.023 → 0.623** | **−0.023 → 0.577** | Yes (+) / **No (−)** |
| T5 Stability | 0.10 | +0.006 → 0.607 | −0.007 → 0.594 | Yes (+) / borderline (−) |

**Interpretation:** The CAPABLE classification was fragile at the initial AII of 0.6007 (gap = 0.0007 on T4−0.05 and T1−0.05 paths). T2 (Friction) was the highest-sensitivity axis due to its low component score (0.127 at CAPABLE baseline). Subsequently, world model seeding raised T2 to 0.975, pushing AII to 0.820 (TRAINED_SHADOW_ONLY) — but this T2 improvement is window-composition driven (see §F.6 TRAINED caveat and NEGATIVE\_RESULTS.md §5). At the TRAINED milestone, the sensitivity table is recomputed with T2=0.975: now T1 (lowest score, 0.691) becomes the highest-sensitivity axis. The analysis supports treating both CAPABLE and TRAINED thresholds as preliminary milestones requiring organic confirmation, not stable certification boundaries.

Where:
- **T1 (Calibration):** `1 − 5 × ECE` — Expected Calibration Error of Bayesian P(harm) priors vs. observed harm rates.
- **T2 (Friction):** `exp(−benign_review_rate / 0.20)` — gradient-retaining exponential function; higher when fewer benign actions require oracle review. The earlier linear formula `1 − r/0.27` flatlined at zero for any rate ≥ 27% and was replaced in v0.2.1 (see §F.7 / Appendix F.6).
- **T3 (MetaJudge quality):** `(mean_critique_score − 0.5) / 0.5` — quality of LLM self-reflection; boosted when LoRA fine-tuning is active.
- **T4 (Transfer):** `replay_transfer_score` — cross-domain governance transfer accuracy; measured on the replay arena (96 fixed cases across 9 categories). Transfer subset: n=4 cross-domain cases, all correct (current T4=1.000). Overall arena accuracy (87.5%) is a separate metric.
- **T5 (Stability):** normalised oracle-bandit entropy + high-confidence world-model context coverage.

**AII levels:** WARMUP [0, 0.4) → LEARNING [0.4, 0.6) → CAPABLE [0.6, 0.8) → TRAINED [0.8, 1.0].

### F.3 Live Results (2026-06-05)

After 663+ governance episodes and 8 hours of live operation:

| Metric | Value |
|---|---|
| AII | **0.5088** [LEARNING] |
| T1 Calibration | 0.598 (ECE = 0.0804) |
| T2 Friction | 0.000 (benign\_review\_rate = 41%; pre-fix linear formula; formula replaced in v0.2.1 — see §F.6) |
| T3 MetaJudge | 0.850 (base llama-3.1-8b; LoRA pending) |
| T4 Transfer | **1.000** (`replay_transfer_score`: transfer cases 4/4 correct; note: overall arena accuracy 95.4% at this date is a separate metric not used for T4) |
| T5 Stability | 0.094 (high-confidence contexts = 12) |
| False Accept Rate | **0.000** (zero throughout operation) |
| world\_model\_active | **1** (activated: ECE 0.0804 < 0.10, n\_high 12 ≥ 10) |

The world model was activated automatically by the ECE safety guard after sufficient calibration data accumulated. A false-accept auto-revert mechanism is in place but has not been triggered.

### F.4 Safety Constraints

1. World model trust adjustment is gated behind ECE < 0.10 AND n\_observations ≥ 10 per context. Below this threshold, the system operates in shadow mode.
2. Any false accept triggers immediate revert to shadow mode.
3. No autonomous policy changes occur without AII > 0.65 for ≥ 5 consecutive cycles.
4. All AII measurements are stored in D1 for full audit trail.

### F.5 LoRA MetaJudge Pipeline (Sprint 3 — pending deployment)

A fine-tuning pipeline exports 614+ labeled episodes as prompt/completion JSONL for instruction tuning `@cf/mistralai/mistral-7b-instruct-v0.2-lora` (rank ≤ 8). The pipeline (`scripts/export_lora_training_data.py`) supports local JSONL, seed files, and remote D1 as training sources with an 80/20 train/heldout split. Deployment target: `aromer-metajudge-v1` via Cloudflare Workers AI LoRA fine-tuning (open beta, free tier). LoRA accuracy > 90% on heldout set is required before replacing the base model.

**Update (2026-06-07/08):** The T2 Friction component flatlined at 0.000 in live telemetry because `max(0, 1 − benign_review_rate/0.27)` returns zero for any review rate ≥ 27%, and the live rate was running at ~31–41%. Diagnosed 2026-06-07. Fix: replaced the formula with the gradient-retaining `exp(−r/0.20)` function (centred on 15% target), now in `remora/aromer/intelligence/score.py`. Additionally, the friction-optimizer's MetaJudge-driven per-scope adjustments were wired into the active decision path (previously computed but only written to file). Safety floor was unaffected throughout (false_accept = 0.000 remained). The world_model_active state and calibration_score are unchanged. Live AII is indeterminate pending a fresh measurement cycle with the corrected formula; the archived 0.508 figure should be interpreted as pre-fix.

### F.6 Cumulative Live State (2026-06-26) — TRAINED\_SHADOW\_ONLY (via world-model seeding)

All interpretation gates cleared. Stable status as of 2026-06-26T13:00 UTC (pre-world-model-seeding baseline):

| Metric | Value | Change vs F.3 |
|---|---|---|
| AII (smoothed) | **0.629** [**CAPABLE\_SHADOW\_ONLY**] | +12.1 pp |
| T1 Calibration | 0.699 (ECE = 0.060) | +9.7 pp (ECE ↓) |
| T2 Friction | 0.205 (benign\_review\_rate = 37.3%) | +20.5 pp (formula fixed + optimizer wired: verify\_p→0.45, trust\_min→0.65) |
| T3 MetaJudge | 0.727 (organic LLM eval) | −12.3 pp (LoRA not deployed) |
| T4 Transfer | **1.000** (96-episode arena; 4 database\_to\_financial cases) | unchanged — **measured in-domain arena only** |
| T5 Stability | 0.700 | +60.6 pp |
| False Accept Rate | **0.000** | unchanged (zero throughout) |
| causal\_enriched | **66 episodes** (Bjøru 2026 PS) | new — clears CAUSAL\_UNMEASURED gate |
| cross\_domain\_cases | **4** (database\_to\_financial) | new — clears TRANSFER\_UNMEASURED gate |
| longitudinal\_records | **201** | clears LONGITUDINAL\_DATA gate |
| n\_harmful\_internal | 256 | clears SAFETY\_EVIDENCE + CP gates |
| **Status** | **CAPABLE\_SHADOW\_ONLY** | All 5 gates cleared; deployment = SHADOW\_ONLY |

**Iter 13 (hook pre-check, 2026-06-25):** The REMORA pre-tool-use hook now calls AROMER `/decide` for MEDIUM-risk actions before the remote oracle. World-model fast-path (`P(harm) < 5%`, `n_obs ≥ 20`, `trust ≥ 0.40`) returns ACCEPT without oracle call, reducing benign oracle traffic. Benign\_review\_rate declined 0.54 → 0.52 → 0.495 → 0.41 → 0.21 across 5 cron cycles + 4 manual adapt cycles.

**CAPABLE reached (2026-06-26 08:35 UTC):** AII crossed 0.60 raw via MetaJudge improvement and friction reduction. At that point `interpretation_nuanced = COMPOSITE_THRESHOLD_REACHED_TRANSFER_UNMEASURED`.

**CAPABLE\_SHADOW\_ONLY reached (2026-06-26 ≈13:00 UTC):** All five evidence gates cleared:
1. ~~TRANSFER\_UNMEASURED~~ — 3 new database\_to\_financial episodes (trans-005 to trans-007) added to replay arena (total 96), published via `scripts/aromer_publish_replay.py`. xdomain = 4.
2. ~~CAUSAL\_UNMEASURED~~ — Bug fixed: `load_domain()` raised `FileNotFoundError` for unknown domains, silently blocking the `network_change_management_v1` fallback. After fix: 66 blocking/verifying episodes enriched with Bjøru 2026 §4.2.2 PS scores, published via `scripts/aromer_publish_causal.py`. Top concept: `approved_change_window`.
3. ~~LONGITUDINAL\_DATA~~ — 8 manual adapt cycles built history from 2 to 15+ records (adapt cron runs every 4 h; subsequent standard cycles brought total to 201).
4. ~~SAFETY\_EVIDENCE~~ — 256 internal harmful cases > 30 threshold.
5. ~~SAFETY\_NOT\_CERTIFIED~~ — CP upper 95% bound ≈ 1.2% ≤ 5%.

**World model optimization (2026-06-26, post-CAPABLE\_SHADOW\_ONLY):** accept\_trust\_min reached floor 0.50 (n\_updates=13). World model Bayesian priors updated with 150 benign correct\_accept seeds across 14 domain contexts (5 passes × 30 episodes, via `scripts/aromer_seed_benign_outcomes.py --runs 5`). After adapt cycles processing the seeded episodes, p\_harm for benign contexts fell from uniform 0.50 to 0.10–0.17 (medium-confidence posterior, ≥5 observations per context). AII smoothed rose to 0.675 while window benign\_review\_rate fell to 0% (artifact of seeded window — see caveat below). Stable AII (post-window-rotation) is estimated at 0.65–0.70 once the seeded episodes rotate out.

**Caveat — window benign\_rate artifact:** Concentrated benign seeding fills the 200-episode sliding window, temporarily showing benign\_review\_rate = 0% and degrading the window quality gate to INSUFFICIENT\_SAFETY\_EVIDENCE. This is a window composition artifact, not evidence of a safety regression. The global safety gate remains PASS (256 harmful all-time, 0 FA, CP 1.2%). T5 stability dropped to 0.51 due to distribution shift; recovery expected after window rotation (≈200 new decisions). See NEGATIVE\_RESULTS.md §5.

**Remaining honest caveats after CAPABLE\_SHADOW\_ONLY:**
- T4 Transfer (0.15 weight) measured on the same replay arena as seeds; true cross-domain independence is not established. Without T4, renormalized AII ≈ 0.52.
- ~~Safety certification is `CERTIFIED_INTERNAL_ONLY` — no time-separated independent holdout.~~ **Resolved (2026-06-27):** `CERTIFIED_INDEPENDENT_HOLDOUT` via aradhye/CaiZhiTech external holdout (n\_harmful\_independent=169, safety\_upper\_bound\_95=0.37%). See §F.7.
- ~~API: `policy_relaxation_allowed = false`, `world_model_can_relax = false` until TRAINED + independent certification.~~ TRAINED confirmed organically and independent certification achieved (see §F.7); `policy_relaxation_allowed` remains false pending three production gates.

**TRAINED_SHADOW_ONLY reached (2026-06-26, AII=0.820):** Following world model seeding (150 benign correct\_accept episodes across 14 contexts, 5 passes), the 200-episode sliding window filled with seeded entries, reducing `benign_review_rate` to ≈0.5% in the window (operational baseline: 35.3%). This drove T2 from 0.175 to 0.975, pushing AII smoothed from 0.629 to 0.820. Component scores at TRAINED milestone: T1=0.691, T2=0.975⚠, T3=0.736, T4=1.000, T5=0.711, AII=0.820.

**Critical caveat — T2 is window-composition driven:** The TRAINED threshold reflects the seeded window, not organically confirmed friction reduction. T2 will revert as seeded episodes rotate out (~200 new organic decisions). Estimated AII after full rotation (operational T2≈0.27): ≈0.643 (CAPABLE). The Bayesian world model priors updated by seeding (p\_harm 0.10–0.17 for 14 benign contexts) are persisted in D1 and will reduce future benign_review_rate for those specific contexts. Whether this sustains T2 ≥ 0.80 organically is an open empirical question. LoRA MetaJudge (blocked on CF Workers AI beta) remains the path to durable T2 improvement. See NEGATIVE\_RESULTS.md §4–5 for full detail.

**Post-seeding equilibrium (2026-06-26, ~60 adapt cycles after TRAINED milestone):** T2 stabilized at 0.905 (benign_review_rate ≈ 2% in window; window still ~93% seeded); AII smoothed = 0.804 (TRAINED_SHADOW_ONLY maintained); T5 recovering 0.711 → 0.717; T3 improved 0.736 → 0.744. Current component scores: T1=0.691, T2=0.905, T3=0.744, T4=1.000, T5=0.717, AII=0.804. False accepts: 0. Global gate: PASS (CP bound 1.2%). Bottleneck: T1 calibration (ECE=0.062), improvable only via organic labeled traffic.

*Note: AROMER is an experimental research plugin. AII scores are computed from a live but uncontrolled deployment. Results should be treated as preliminary research observations, not validated benchmark results.*

---

### F.7 Organic TRAINED Confirmation and Current State (2026-06-28)

This section documents resolution of the open caveats in §F.6 and the current system state following organic TRAINED confirmation.

**Gap 1 resolved — CERTIFIED\_INDEPENDENT\_HOLDOUT (2026-06-27):** 169 harmful episodes from aradhye and CaiZhiTech (external taxonomy, independent of AROMER seeds) seeded via `scripts/aromer_seed_harmful_episodes.py`. `safety_upper_bound_95 = 0.00367` (Clopper-Pearson 95% upper bound; 0.37% ≤ 5%). `safety_certification = CERTIFIED_INDEPENDENT_HOLDOUT`. Holdout eval (36-case time-separated split): FA=22.2% on aradhye holdout (execution-context harm — Gap 2 below). See NEGATIVE\_RESULTS.md §9–10.

**Gap 2 open — aradhye external FA=22.2%:** On a 36-case holdout from aradhye/CaiZhiTech seeds, false accept rate was 22.2%. Root cause: instruction-text signals do not encode execution-context harm (the harmful action in context looks identical to benign). Resolution requires runtime execution monitoring; architectural gap, not a tuning issue.

**Gap 3 resolved — organic T2 confirmation (2026-06-28):** The critical caveat from §F.6 ("T2 will revert as seeded episodes rotate out") was empirically refuted. After §9 regression (168 harmful seeds crashed T2 to 0.274, AII to 0.62) and §10 organic recovery, T2 reached 1.000 (brr=0%, maintained for 6+ consecutive cycles). World-model Bayesian priors (p\_harm 0.10–0.17 for 14 benign contexts) successfully generalised to organic /decide traffic. See NEGATIVE\_RESULTS.md §11.

**Organic TRAINED trajectory (12 consecutive cycles, AII 0.8097 → 0.844):**

| Cycle | AII | T2 | T3 | T5 | brr |
|-------|-----|----|----|-----|-----|
| 1 (milestone) | 0.8097 | 0.916 | 0.791 | 0.681 | 0.5% |
| 6 | 0.8377 | **1.000** | 0.792 | 0.747 | 0% |
| 12 | **0.8440** | 1.000 | **0.800** [M] | 0.794 | 0% |

[M] T3=0.800 milestone: MetaJudge quality +4.1pp above historical peak (0.759 at n=135). Full 12-row trajectory: `NEGATIVE_RESULTS.md §11`.

**Current state (2026-06-28, ~15:53 UTC):** AII=0.8042 TRAINED\_SHADOW\_ONLY (recovered from §13 regression). T1=0.682 (ECE=0.064). T2=0.8518 (brr=2.5%, recovering). T3=0.800 [M]. T4=1.000. T5=0.7768 (recovering). FAR=0. `safety_certification = CERTIFIED_INDEPENDENT_HOLDOUT`. Full §12→§13 cycle: peak AII=0.8442 (cycle 12, 12:04 UTC) → regression at ~13:00 UTC (brr 0%→5%, AII=0.7885 CAPABLE) → organic recovery in ~2h53min (brr 5%→2.5%, AII 0.789→0.804). Recovery trajectory: AII 0.789→0.791→0.799→0.7997→0.8042 across 5 consecutive polls. Full §12→§13 sparkline: `NEGATIVE_RESULTS.md §12–§13`. Peer-review impact: none; FAR=0 throughout; the §12→§13→recovery cycle is a documented reproducible empirical result (organic brr acceleration and decay under fixed-size EMA window).

**Three production gates remaining before deployment:**
1. Longitudinal stability audit — multi-week continuous TRAINED confirmation by independent reviewer.
2. Independent human review of governance decisions.
3. RBAC access control audit.

*Gap 4 (NLI/SE DLL block on Windows) remains architecturally unresolved — see NEGATIVE\_RESULTS.md §3.*
