# Research Analysis Notes — 2026-06-30

> **HISTORICAL SNAPSHOT (2026-06-30).** Gate statuses, metrics, and plans in this
> document reflect the state on its date and are intentionally preserved
> unedited. For current gate status see
> [`docs/assurance/release_gates.md`](
> ../assurance/release_gates.md); for current metrics see the repository README.


**Covers:**
1. Error review of `analyse_av_remora_forskning.pdf`
2. Key findings from Zhang et al. 2024 (arXiv:2404.02655v2) — UF Calibration
3. Implementation recommendations for REMORA

---

## 1. Error Review: `analyse_av_remora_forskning.pdf`

This Norwegian-language review document covers REMORA governance, claim hygiene, calibration, OOD detection, and formal verification. Overall quality is high, but the following issues were identified.

### 1.1 Factual Error — Model Name "Qwen3.5-9B" (§2.2, Tabell 1)

**Issue:** Table 1 in Section 2.2 shows a cascade configuration "Qwen3.5-9B → GPT-4o-mini" with IR=91.9–92.6%, FPR=1.9–6.7%.

"Qwen3.5-9B" does not exist as a published model. The Qwen model family uses naming like Qwen2.5-7B, Qwen2.5-14B, Qwen3-8B, Qwen3-14B. No "Qwen3.5" series exists as of 2026-06-30.

Additionally, the companion paper_alignment document (created from the same Ge source) describes the cascade differently as "Qwen3.5-9B→Qwen2.5-14B" — inconsistent with the Norwegian doc's "Qwen3.5-9B → GPT-4o-mini". These two descriptions cannot both be correct.

**Action required:** Verify against original Ge paper (arXiv:2603.07191v2) for exact cascade model names. The cascade is most likely a local Qwen2.5-small → Qwen2.5-14B configuration. The paper_alignment_2026-06-30.md must also be corrected.

**Status:** Error confirmed — both the Norwegian analysis and paper_alignment use an incorrect model name from the Ge paper.

### 1.2 ECE Claim Verified (§5.2)

**Claim:** "fra 0.185 til 0.076" (ECE reduction from 0.185 to 0.076 via UF Calibration)

**Status: CORRECT.** Table 4 in Zhang et al. (2404.02655v2) shows for LLaMA2-13B-Chat:
- "Best Result (Others)" average ECE = 0.185 across 4 benchmarks
- "Ours (UF Calibration)" average ECE = 0.076

The claim is accurately attributed to [12] = Zhang et al. 2024.

### 1.3 Incomplete Reference List (§Sources)

The numbered source list (§ "Kilder") contains only short titles without full author names, publication years, arXiv IDs, or DOIs. References [3], [13], [15], [17], [20], [21], [24] are not locatable from title alone.

**Specifically missing:**
- [15] "Selective Classification of Sequential Data Using Inductive..." — critical for the ICP claim (§6.2) but not identifiable without full citation
- [13] "ICML 2026 Papers" — reference to a conference listing, not a specific paper
- [3] "AdaptiveGuard: Towards Adaptive Runtime Safety for LLM-Powered..." — should cite full arXiv ID

**Recommendation:** Convert the short-title list to full academic citations with arXiv IDs where available. This is required for any publication submission.

### 1.4 Subjective Section (§9 — Author Competence Profile)

Section 9 assesses the author's competence. This is appropriate for an internal review document but would not appear in a published paper. The technical strengths identified are:
- Advanced statistical knowledge (Wilson CI, Pseudo-Count Bootstrap) ✓
- Security architecture (multi-layer runtime barriers) ✓
- Claim hygiene methodology ✓

**Improvement areas noted in §9.2:**
- Gap between formal verification theory and runtime cost (TLA+/ProVe latency)
- Non-IID temporal drift: mathematical proofs for conformal validity under temporal correlation not formalized

These are **valid gaps** that should appear in REMORA's research roadmap.

### 1.5 Tips for Documentation Structure

Based on the analysis document, the following improvements would strengthen REMORA-research:

1. **Add Claim-Evidence Maps to README**: Each empirical claim links to its executable artifact. The Norwegian doc describes this as a needed improvement (§11.2) — implement it.

2. **Replace Wald CIs everywhere**: Current evaluation docs should use Wilson Score intervals, especially for metrics near 0 or 1 (FAR=0%, ECE=0.007). Add CIs to AII dashboard.

3. **Escalation matrix**: The document's Table 2 (§8.1) shows Low/Medium/High/Critical autonomy tiers with response times. REMORA has the architecture for this but the documentation doesn't expose it clearly. Add to architecture overview.

4. **Identity Blast Radius metric**: §8.2 introduces this concept — "the total scope of resources an autonomous identity can affect or destroy before a human operator can intervene." REMORA's RBAC controls this but doesn't compute or expose the metric.

5. **Roadmap structure**: The 12-week publication roadmap in §11.2 is useful — extract the statistical upgrade items (Wilson CI, Pseudo-Count Bootstrap) and add them as concrete REMORA improvement tickets.

---

## 2. UF Calibration — Zhang et al. 2024 (arXiv:2404.02655v2)

**Full citation:**
Zhang, M., Huang, M., Shi, R., Guo, L., Peng, C., Yan, P., Zhou, Y., and Qiu, X. 2024. "Calibrating the Confidence of Large Language Models by Eliciting Fidelity." arXiv preprint arXiv:2404.02655v2. Fudan University / Meituan.

### 2.1 Core Method: UF Calibration

RLHF-optimized LLMs exhibit overconfidence — their stated confidence does not match actual correctness rates. The paper decomposes confidence into two orthogonal dimensions:

**Uncertainty(Q):** How ambiguous is the question itself?
```
Uncertainty(Q) = -Σ(pi · log pi) / log M
```
Computed via K=10 samples, M = number of candidate answers. Normalized Shannon entropy.

**Fidelity F(ai):** How committed is the model to its chosen answer?

Elicitation procedure:
1. For answer ai with content oi, replace oi with "All other options are wrong."
2. Re-query the model under greedy decoding.
3. If the model switches, fidelity is low. Repeat until model selects the "wrong" option.
4. This builds a hierarchical fidelity chain C (e.g., "A→C→D").
5. Assign weights τ^i from right-to-left: rightmost (last choice) gets τ^1, etc. Default τ=2.
6. Normalized fidelity: FidelityC(ai) = τ^i / Σ(τ^j)
7. Overall fidelity F(ai) averaged across chains weighted by Psampled.

**Combined confidence:**
```
Conf(Q, ai) = (1 - Uncertainty(Q)) × F(ai)
```

**Results on LLaMA2-13B-Chat (ablation, Table 4):**
- Best competing method: ECE avg = 0.185
- UF Calibration: ECE avg = 0.076
- Temperature-robust: best ECE across all temperatures tested

**Limitation:** Requires known answer set (MCQA, classification, preference labeling). Not directly applicable to open-ended generation.

### 2.2 New Metrics: IPR and CE

These supplement ECE and should be adopted in REMORA's calibration monitoring:

**IPR (Inverse Pair Ratio):** Measures reliability diagram monotonicity.
```
IPR_M = IP / C(K, 2)
```
Where IP = number of inverse pairs in reliability diagram (bins where high-conf has lower accuracy than low-conf), K = non-empty bins, C(K,2) = K*(K-1)/2.

- IPR = 0: perfectly monotonic (ideal)
- IPR = 1: fully inverted (worst)
- ECE alone misses non-monotonic patterns; IPR catches them

**CE (Confidence Evenness):** Measures if confidence is spread across the full [0,1] range.
```
CE_M = -Σ(pi · log pi) / log M
```
Applied to density of each bin in the reliability diagram (not answer entropy — here pi = fraction of predictions falling in bin i).

- High CE: predictions spread across all confidence levels (informative)
- Low CE: all predictions cluster at 0.8-0.9 (model always says "likely" regardless of question)
- A model with ECE=0, IPR=0, but CE=0 is gaming calibration by always predicting the base rate

**The three-metric view:** ECE (accuracy), IPR (monotonicity), CE (spread) together define "truly well-calibrated" confidence. Per the paper: "We suggest that truly well-calibrated confidence should achieve a balance among ECE, IPR, and CE, rather than over-optimizing any of them."

### 2.3 Applicability to REMORA

| UF Technique | REMORA Application | Effort |
|---|---|---|
| Sampling K=10 for oracle decisions | AROMER critique already multi-sample; formalize Uncertainty(Q) | Low |
| Fidelity chain probe for oracle | Re-query oracle with "All other decisions are wrong" to verify commitment | Medium |
| IPR metric | Add to `/log` endpoint calibration section | Low |
| CE metric | Add to `/log` endpoint calibration section | Low |
| Conf(Q,ai) = (1-U)×F formula | Replace mean_score anchor with calibrated composite | High |
| Temperature-robust calibration | Current ECE=0.007 — verify this holds across temperature settings | Low |

**Priority implementation (Quick wins):**

1. **Add IPR and CE tracking to AROMER**: These require only the existing episode data (confidence scores + correctness labels). Can be computed alongside current ECE.

2. **Document oracle fidelity probe**: Add a fidelity verification step to the structured oracle prompt as an optional HIGH-confidence verification path.

3. **Cite Zhang et al. 2024 in calibration documentation**: Add to `docs/assurance/` and whitepaper wherever ECE is discussed.

---

## 3. Consolidated Improvement Recommendations

### Immediate (documentation only):

- [ ] Fix "Qwen3.5-9B" model name in paper_alignment_2026-06-30.md (verify against Ge arXiv)
- [ ] Add full citations with arXiv IDs to `analyse_av_remora_forskning.pdf` source list
- [ ] Add Zhang et al. 2024 (2404.02655v2) to paper_alignment document
- [ ] Add Corsi et al. 2021 to paper_alignment document
- [ ] Add IPR/CE metric definitions to `docs/aromer/learning-log-v2.md`
- [ ] Frame Stage 1 LOCAL_BLOCK rules as behavioral safety properties (Corsi et al. formalism)

### Phase 4 (code changes):

- [ ] Compute IPR and CE alongside ECE in the `/log` endpoint's calibration section
  - Requires: binned reliability data from episode outcomes vs. confidence scores
  - File: `workers/aromer/src/index.ts` — add to calibration computation block
- [ ] Add Wilson Score CI to AII dashboard next to point estimates
- [ ] Expose Identity Blast Radius concept in RBAC documentation

### Phase 5 (research):

- [ ] Evaluate UF Calibration fidelity chain on AROMER oracle decisions
- [ ] Evaluate IPR score on current episode set — if non-zero, investigate miscalibration direction
- [ ] Consider Pseudo-Count Regularized Bootstrap for F1-score CIs in AromerEvaluate

---

## 3. Formal Verification — Corsi et al. 2021 (UAI, PMLR 161:333–343)

**Full citation:**
Corsi, D., Marchesini, E., and Farinelli, A. 2021. "Formal Verification of Neural Networks for Safety-Critical Tasks in Deep Reinforcement Learning." *Proceedings of the Thirty-Seventh Conference on Uncertainty in Artificial Intelligence (UAI 2021)*. PMLR 161:333–343. Department of Computer Science, University of Verona.

### 3.1 Core Contribution: ProVe and Violation Rate

**Central insight:** Standard DRL metrics (cumulative reward, success rate) cannot detect adversarial input configurations — sparse regions of the input space where a correctly-rewarded policy makes irrational decisions. Formal verification fills this gap.

**Violation Rate (Def. 4.1):**
```
v = |X_UNSAT| / |X|
```
ProVe measures the fraction of the input domain where a safety property is violated. This is an upper bound on the actual probability of failure in deployment — the adversarial regions are typically not visited in standard rollouts (Fig. 3 in paper).

**Safe Rate (Def. 4.2):**
```
s = 1 − v
```

**Behavioral Safety Property (safe-decision form):**
```
Θ: If x₀ ∈ [a₀,b₀] ∧ ... ∧ xₙ ∈ [aₙ,bₙ] → yⱼ > yᵢ
```
Properties encode rational decisions without requiring deep domain knowledge (e.g., "if obstacle right and obstacle-free otherwise, always prefer left turn"). Properties cover general behavior, not every individual safe/unsafe case.

### 3.2 ProVe Algorithm

1. Encode input domain as matrix A₀ (m×2n: sub-areas × 2 bounds per input node).
2. Generate multiplication matrix B_{2n×4n} for GPU-parallel bisection.
3. Propagate each sub-area through the DNN (layer-by-layer bound computation via interval algebra, Moore 1963).
4. Check each output-bound: SAT / UNSAT / inconclusive (bounds overlap — bisect further).
5. Remove verified sub-areas; recursively split remaining.
6. Track violation_rate continuously. Discretization parameter ε limits maximum bisection depth (convergence guarantee).

**GPU advantage:** Matrix bisection is highly parallelizable. ProVe achieves **22x average speedup** over Neurify on ACAS benchmark (25526s → 1163s total). Especially effective on large properties that split into exponentially many sub-areas.

### 3.3 Key Results

**ACAS XU collision avoidance (Table 1 of paper):**
- 2 behavioral properties (θL, θR: never turn toward an intruder)
- Violation rate range: ~50% (worst model) to ~5% (best model), across 6 trained models achieving similar reward
- Strong correlation: violation_rate ≈ 10× actual collision_rate
- Models with identical reward can differ 10× in safety — reward alone is insufficient as a safety metric
- ProVe violation_rate with 2 domain-agnostic properties ≈ collision_rate under all 15 formal ACAS properties

**TurtleBot3 navigation (Fig. 4):**
- Safe rate is NOT correlated with success rate in early/late training phases
- Policy learns shorter paths at the cost of safety in the final training stage
- Motivates using violation_rate as a complementary training-time metric

**Timing:** At violation_rate ≈ 5%, runtime check per timestep < 0.01s. At 12%, requires ~1.02s — impractical for real-time control loops (hardware-dependent).

### 3.4 Applicability to REMORA

| ProVe Concept | REMORA Analog | Alignment |
|---|---|---|
| Safety property: If input ∈ [a,b] → yⱼ > yᵢ | Stage 1 LOCAL_BLOCK: if tool_call matches pattern → always block | Direct analog — both are "if X, always do Y" behavioral safety rules |
| Violation rate v = |X_UNSAT|/|X| | FAR (False Accept Rate) | FAR is empirical over observed episodes; violation_rate is formal (covers unvisited threat space too) |
| Safe rate s = 1−v | Stage 1 coverage | Both measure "what fraction of threat space is correctly handled" |
| Reachability set Γ(X, fθ) | Lyapunov V(t) = H(t) + λ·D(t) | Both track whether system output stays within a safe semantic region |
| ε discretization precision | CRC α calibration tolerance | Both control the precision/coverage tradeoff of formal guarantees |
| ProVe runtime controller | REMORA Shadow Mode | Both verify decisions in real-time before committing to execution |
| GPU-parallel matrix splitting | GO-STAR parallel 3-oracle ensemble | Both exploit computational parallelism for verification throughput |
| Behavioral property design (rational decisions) | AROMER MetaJudge scoring (rational governance decisions) | Both evaluate rational vs. irrational decision boundaries |

### 3.5 Limitations and Scope Boundaries

- ProVe requires DNN weight access (not black-box). REMORA's oracle is a remote Cloudflare Worker — direct DNN verification is not applicable.
- Violation rate is defined over continuous input domains; REMORA's tool-call inputs are partially discrete/symbolic.
- ProVe complexity is exponential in 1/ε — not feasible for REMORA's high-dimensional decision spaces without significant adaptation.
- **Takeaway:** ProVe validates the *design principle* (formal coverage metrics, behavioral properties, runtime verification) and provides the citation anchor for REMORA's formal safety claims.

### 3.6 Implementation Recommendations

**Immediate (documentation):**
- [ ] Cite Corsi et al. 2021 in `docs/assurance/` wherever "formal safety verification" is mentioned
- [ ] Frame Stage 1 LOCAL_BLOCK rules as "behavioral safety properties" in documentation (aligning with ProVe's formalism)
- [ ] Add violation_rate concept to REMORA's formal evaluation vocabulary

**Phase 5 (research):**
- [ ] Define REMORA's Stage 1 rules in property form: Θ: if tool_call ∈ [pattern_set] → decision = BLOCK
- [ ] Compute empirical violation_rate proxy from AgentHarm episodes (fraction of threat inputs blocked by Stage 1)
- [ ] Add ProVe-style property verification to AgentHarm harness for formal coverage measurement

---

## 4. Consolidated Improvement Recommendations

For REMORA-research documentation, the following literature organization improves academic credibility:

**Tier 1 — Core alignment (mandatory citations):**
- Shamsujjoha et al. 2024 (arXiv:2408.02205v2) — Swiss Cheese taxonomy
- Ge 2026 (arXiv:2603.07191v2) — LGA 4-layer architecture
- Zhang et al. 2024 (arXiv:2404.02655v2) — UF Calibration (ECE/IPR/CE)
- Bjøru 2026 (NTNU ISBN 978-82-353-0022-5) — Causal PS/PN attribution

**Tier 2 — Selective prediction / OOD:**
- Chen & Yoon 2024 (Google ASPIRE) — selective prediction for LLMs
- El-Yaniv & Wiener 2010 — selective classification foundational theory
- Kumar et al. 2023 — conformal prediction for LLM calibration

**Tier 3 — Supporting architecture:**
- Corsi et al. 2021 (UAI/PMLR 161) — formal verification of neural networks (ProVe, violation rate, behavioral safety properties)
- Kuhn et al. 2023 (ICLR) — Semantic Uncertainty (NLI-based, REMORA's H(t))
- Wang et al. 2023 — selective trust in LLM ensembles

Each REMORA claim category should cite at least one Tier 1 paper:
- Multi-layer defense → Shamsujjoha et al.
- Intent verification → Ge 2026
- Calibration → Zhang et al. 2024
- Selective abstention → ASPIRE / El-Yaniv
- Causal attribution → Bjøru 2026
- Formal safety properties / violation rate → Corsi et al. 2021
