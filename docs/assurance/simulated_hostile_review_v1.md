# Simulated Hostile Review v1 — Readiness Gaps for a Physics/XAI/Ethics Reviewer

> **RECONCILIATION NOTE (2026-07-17).** This is a findings register from the
> 2026-07-02/03 hostile-review round, preserved verbatim (it quotes defects
> deliberately and is excluded from stale-string scanning). Several items
> listed as OPEN below have since been fixed — including the non-canonical
> AROMER/AII expansions and the "three production gates" phrasing — and
> `docs/breakthrough_proof.md` was renamed to
> `docs/empirical_evidence_record.md` (2026-07-17). Do not treat OPEN
> statuses in this document as current; the live status surface is
> `release_gates.md` + `remediation_register.yaml`.


**Status:** INTERNAL — findings register + remediation plan. Nothing here is a claim.
**Date:** 2026-07-02
**Method:** Three independent review passes over the full repository, simulating
the reviewer archetype most dangerous to this project: a physics-trained
researcher in explainable AI and AI ethics, publicly critical of AI hype and of
physics vocabulary borrowed without physical content, who *will* check
citations, run the demos, and read the code behind the claims.
Pass A: physics-metaphor and XAI rigor (code + paper). Pass B: literature
alignment against the 2024–2026 agent-safety field, with web verification of
existing citations. Pass C: fresh-eyes coherence audit of the surfaces the
2026-07-02 reconciliation campaign did *not* cover (docs/01, docs/02,
docs/use-cases/, docs/07-api-reference, frontend, demo scripts, secondary docs).

**Verdict:** The inner ring — README ↔ ARCHITECTURE ↔ paper ↔ claim register ↔
artifacts — is now largely coherent and would survive scrutiny. The project
fails this reviewer today on three fronts: (1) **two broken literature
references, one of them load-bearing** — the exact failure mode that ends a
review; (2) **one module and several secondary docs that violate the repo's own
anti-metaphor discipline**, including a "this is NOT a metaphor" claim resting
on an invalid derivation; (3) **a middle ring of documentation
(docs/07-api-reference, docs/use-cases/, README demo, frontend prose) that
tells a different — sometimes fictional — story than the code**. All are
fixable; none is fixable by tightening prose alone.

Cross-references: external peer review 2026-06-25 (NEGATIVE_RESULTS §14);
reconciliation campaign 2026-07-02 (commits 635ee69..cd06fda);
`theoretical_foundations_proposals_v1.md` (anti-metaphor rule).

---

## P0 — Submission blockers (fix before any external review)

### P0-1. Citation integrity: two references are wrong, one is load-bearing
- `paper/remora_paper.md` References: **"Kuhn, L., Gal, Y., & Farquhar, S.
  (2026). Evidential Semantic Entropy… EACL 2026, pp. 334–348"** — the paper
  at ACL Anthology `2026.eacl-long.334` is by **Kunitomo-Jacquin,
  Marrese-Taylor, Fukuda & Hamasaki**, pp. 7107–7122. The author list was
  pattern-matched from the 2023 predecessor and the page range hallucinated
  from the anthology ID. This is the signature of an LLM-fabricated citation;
  a reviewer who checks one reference will check this one.
- **"Zhang, Y. & Lee, M. (2025) … arXiv:2502.11347"** — that arXiv ID is
  **Dong & Wang, "Evaluating the Performance of the DeepSeek Model in
  Confidential Computing Environment"**. Worse: the paper's TEE section
  attributes a specific quantitative claim ("<50 ms attestation overhead…")
  to the non-existent "Zhang & Lee". The number must be re-verified against
  Dong & Wang before it can be kept at all.
- Minor: Du et al. dated 2023 but published ICML 2024; AgentHarm should be
  cited as **ICLR 2025**, not bare arXiv; Raji et al. venue is AIES '22.
- **Fix:** correct or delete both entries; re-verify the TEE numbers; add a
  CI check that every reference resolves (arXiv ID ↔ title match is
  scriptable). *This violates CLAUDE.md's "no invented results" rule and is
  the single highest-priority item in this document.*

### P0-2. `remora/theory/maxent_grounding.py` claims the physics is literal — with an invalid proof
Docstring: *"REMORA's free energy F(T) = λD − TH is NOT a metaphor. It is the
negative log partition function of the Gibbs distribution that solves the
MaxEnt consensus problem exactly."* This contradicts the paper's own
disclosure ("No claim is made that LLM systems obey a physical thermodynamic
law") and ARCHITECTURE.md. The derivation is wrong: the MaxEnt Lagrangian
fixes the H-coefficient at 1; the "temperature" T is smuggled in as a
"Lagrange multiplier for H", which is incoherent (H is the objective). The
same file asserts a second-order phase transition "same as the Potts model"
with no derivation (mean-field Potts for k≥3 is first-order) and calls T=−1
"imaginary temperature" (it is negative). The claim is laundered into
`docs/claim_register.md` as a "Theoretical derivation".
**Fix:** rewrite the docstring to what the code actually verifies (a
numerical identity in a hand-constructed exponential family at T=1); strike
"NOT a metaphor", the phase-transition and VI claims; correct
`docs/claim_register.md`. This one file undoes the repo's hedging discipline.

### P0-3. `docs/07-api-reference.md` is substantially fictional
6 of 8 spot-checked APIs are wrong, and the MCP tools table lists **five
tools that do not exist** (`remora_consensus`, `remora_verify`,
`remora_audit`, `remora_gate`, `remora_shadow_replay`) while the real server
registers 14 differently-named tools. `decide()` documented as returning
`DecisionEnvelope` (actual: `DecisionReport`); PolicyObservation,
OracleResponse, `detect_adversarial`, ActionGateResult, and the LangGraph
adapter are all documented with fields/signatures that don't exist.
**Fix:** regenerate the API reference from source (mkdocstrings is already in
the docs extra), or rewrite by hand against code; add a doc-vs-code signature
test in the style of `test_doc_consistency.py`.

### P0-4. Related work ignores the field the paper competes in
The References contain **zero guardrail systems, zero agent-safety benchmarks
besides AgentHarm, zero AI-control work**. Mandatory additions, verified:
- *Guardrails:* Llama Guard (Inan et al. 2023, arXiv:2312.06674; + LG3/LG4),
  LlamaFirewall (Chennabasappa et al. 2025, arXiv:2505.03574), NeMo
  Guardrails (Rebedea et al., EMNLP 2023 demos), Constitutional Classifiers
  (Sharma et al. 2025, arXiv:2501.18837), Rule-Based Rewards (Mu et al.,
  NeurIPS 2024), GuardAgent (Xiang et al., ICML 2025), AgentSpec (Wang et
  al. 2025, arXiv:2503.18666).
- *Permissioning (preempts REMORA's roadmap and answers the FBR critique):*
  Progent (Shi et al. 2025, arXiv:2504.11703 — ASR 41.2%→2.2% on AgentDojo
  *while preserving utility*), CaMeL (Debenedetti et al. 2025,
  arXiv:2503.18813 — provable security by construction).
- *Benchmarks:* AgentDojo (NeurIPS 2024 D&B), ToolEmu (ICLR 2024), InjecAgent
  (ACL Findings 2024), R-Judge (EMNLP Findings 2024), τ-bench
  (arXiv:2406.12045) — the paper already promises replication on τ-bench and
  ToolEmu without citing them.
- *UQ:* **Farquhar et al., Nature 630 (2024)** — the canonical semantic-entropy
  follow-up, currently uncited while H(t) is built on the 2023 paper; Mohri &
  Hashimoto (ICML 2024, conformal factuality); Yadkori et al. 2024
  (arXiv:2405.01563, conformal abstention — directly preempts §7.2's framing).
- *AI control:* Greenblatt et al., ICML 2024 (arXiv:2312.06942). REMORA *is*
  a trusted-monitoring control protocol in their taxonomy; the threat model
  must add the strategically subversive policy model.
- *Regulatory:* COMPL-AI (arXiv:2410.07959) to anchor the "suitable for
  regulatory review" claim.
- The four papers analyzed in `paper_alignment_2026-06-30.md` (Shamsujjoha,
  Ge, Zhang UF, Corsi) are mandated citations there but **absent from the
  paper's References** — the positioning was never propagated.
**Fix:** new related-work subsection "Runtime guardrails, permissioning, and
AI control" (~15 citations above); reposition "unique" claims (Shadow
Mode/Replay is preempted conceptually by ToolEmu; say "unique among the four
compared papers").

### P0-5. Read arXiv:2606.08539 ("AgentTrust: A Self-Improving Trust Layer for AI-Agent Actions") immediately
Title-level, this is REMORA+AROMER's thesis published elsewhere in 2026 and
currently invisible to the repo. Also check Membrane (arXiv:2606.05743).
Novelty positioning cannot be written until these are read and differentiated.

### P0-6. Paper cites causal artifacts that do not exist
Paper §13.10 cites `remora/causal/attribution.py` (absent),
`scripts/aromer_publish_causal.py` (absent; only `aromer_publish_replay.py`
exists), and "66 episodes with Bjøru 2026 PS scores" (no artifact found).
The CAUSAL_UNMEASURED gate closure rests on these. Violates CLAUDE.md.
**Fix:** commit the module/script/artifact from the main repo, or downgrade
§13.10 to roadmap and reopen the gate; if they live in the private repo, say
so at every citation site (same treatment as CLAIM-009).

---

## P1 — Major (would each draw a hostile review paragraph)

### Mathematics and physics vocabulary
1. **2D Potts critical exponents on a mean-field 3-oracle system**
   (`remora/thermodynamics.py` `critical_exponent_gamma`: γ = 7/4, 13/9, 7/6
   are exact *2D lattice* values; the repo's own `statphys/potts.py` says the
   model is mean-field, where γ=1). Delete or relabel "reference values, not
   applicable"; remove `gamma_exponent` from `PhaseDiagram`.
2. **`compute_phase_diagram` fabricates curves** (hard-coded η(T) with the 2D
   Ising β=1/8 exponent). Only tests reference it — rename
   `illustrative_phase_diagram` + "synthetic, not measured" docstring.
3. **"Hallucination bound" is clamped so it cannot bind** (ρ capped at 0.49
   while the paper reports within-family ρ̄≈0.4–0.6 — the clamp silently
   understates false-consensus risk and inflates τ). Remove the clamp or
   rename `false_consensus_risk_proxy`; purge "bound" from §5.1.
4. **`proofs/hallucination_bound_theorem.py` has a direction error**
   (q^⌊n/2⌋ ≤ q^(n/2) is false for q<1, odd n; at the deployed n=3 the
   argument supports q^1, not q^1.5) and an unstated pair-independence
   assumption. Fix the bound to q^⌊n/2⌋, add the assumption as A5, downgrade
   "theorem" language until re-verified.
5. **Live "susceptibility" χ is a constant** (algebraically ≡ 1/T_c whenever
   clamps don't bind — not a sensitivity), *and* χ has AUC 0.39 (below
   chance, §13.2) yet still multiplies the headline trust score. Compute by
   actual perturbation, or remove χ from τ, or show the ablation that keeps it.
6. **Vocabulary slippage in secondary docs:** `docs/thermodynamic_abs.md`
   ("continuous thermodynamic trajectory", "proportionally scalar",
   "Gold Standard … proven in test boundaries" — no disclaimer),
   README "phase transitions" for AII threshold crossings, abstract
   "theoretical ceiling reached" for a heuristic composite,
   `statphys/gibbs.py` "formal analytic continuation" for a sign flip.
   **Fix:** one canonical disclaimer doc linked from every file using the
   vocabulary; rewrite `thermodynamic_abs.md`; repo-wide audit for
   "proven/exact/not a metaphor". Consider the renames that lose nothing:
   T → difficulty prior, F → routing objective, phases → consensus regimes,
   `LyapunovController` → consensus-progress monitor (H and D can stay,
   qualified). λ is 0.3/0.4/1.0 in three places — reconcile.

### XAI honesty
7. **No human evaluation of any explanation exists** — yet explain() promises
   "human-readable audit trails … compliance". Add the explicit limitation
   now; plan a small expert comprehension study (this is also the reviewer's
   own research home turf — the absence will be noticed in minutes).
8. **"Causal" machinery is honest what-if replay wearing Pearl vocabulary:**
   `CausalEdge`/`model.edges` are never read by any code; do-calculus is
   invoked but no identification happens (none is needed — the SCM is the
   engine). Rename to "policy what-if analysis" or make the graph
   load-bearing. Three unrelated things share the name "counterfactual";
   the worst is the benchmark's `COUNTERFACTUAL_FAILED` hard block, which in
   `toolcall/remora_gate.py` is **a severity/keyword lookup** — rename the
   flag (e.g. `premise_stress_check_failed`) and disclose in §6.2.

### Documentation/code coherence (middle ring)
9. **README "Building Automation Demo" is a hardcoded mock:**
   `scripts/demo_building_lights.py` imports nothing from `remora/`; the
   92%/96% "confidence" values are literals; outcomes are ALLOW/BLOCK — a
   vocabulary that exists nowhere else (canonical: ACCEPT/VERIFY/ABSTAIN/
   ESCALATE). The linked use-case doc describes a different scenario.
   **Fix:** either wire the demo through `RemoraDecisionEngine` with real
   outcomes, or label it "illustrative mock — not the engine" in README and
   script; align vocabulary either way.
10. **`docs/use-cases/` tells the pre-pivot story:** REMORA described as a
    question-answering consensus engine ("It is not a fact-checker" —
    ARCHITECTURE.md); an undefined "ETR" metric carries quantitative claims
    (87%/91%); production-implying language ("Auto-confirm", "your own REMORA
    deployment", BACnet/MODBUS integration) with **zero SHADOW_ONLY
    disclaimers in the whole directory**; an unartifacted "~3% false
    positives"; invented SEC-filing examples not labeled illustrative; broken
    links out of the repo. **Fix:** rewrite the directory against the
    action-governance story, define or remove ETR, add the standard
    research-scope banner to every file, register or delete every number.
11. **`docs/02-evidence-and-claims.md` is 5 claims behind the register**
    (missing CLAIM-002 — the flagship external result — 007, 009, 010, 011),
    contains two headline numbers that are in no register (99.9% ordered-phase
    coverage; replay_accuracy=0.875), has no claim anchors, and cites the
    stale PDF as artifact. **Fix:** regenerate from the register (ideally
    literally — a script that renders this doc from claim_register_v1.yaml
    would make drift impossible), and extend the provenance gate's anchor
    coverage to it.
12. **Frontend violates the register's own quoting rules in unbound surfaces:**
    `cascade.tsx` says "94.7% @ 25% *abstain*" (operating point inverted —
    it's 25% coverage ≈ 75% abstain) and presents the 82.8% majority-vote
    *baseline* as a REMORA result; `index.tsx` quotes 88% without the Wilson
    CI that CLAIM-004 mandates; `content/whitepaper.ts` claims an "RDF audit
    graph with OTel telemetry" — neither exists in `remora/` (audit is a
    SHA-256 hash chain) — and lists integrations as "Integrated" that aren't.
    **Fix:** correct the strings; extend `test_frontend_benchmark_snapshot.py`
    (or claim anchors) to bind the prose surfaces, not just
    benchmark-snapshot.json.
13. **Stale references that survived the campaign:** README line ~224 still
    says "eligible close 2026-07-07" (contradicting line 100 of the same
    file); `docs/claim_register.md` has 2026-07-07 twice, "Day 25/30", and
    two Makefile targets that don't exist (`make check-live`,
    `make rem020-check`); `paper/hf_dataset_card.md` 2026-07-07;
    `paper/remora_mathematical_supplement.md` still presents "the seven hard
    blocks" as complete with a hardcoded line-range pointer;
    `docs/REMORA_AROMER_MASTER_DOCUMENT.md` has a **third** AROMER expansion
    ("Autonomous REMORA Orchestrator, Meta-Emergent Reasoner"); register
    CLAIM-006 caveat still says "Three production gates remain" (REM-022 is
    DONE, and REM-023 now exists); register header still stamped 2026-06-30;
    `run_external_benchmark_agentharm.py` survives in three assurance docs;
    ARCHITECTURE §5.5 expands AII as "AROMER Intelligence Index" vs README's
    "Autonomous Intelligence Index". **Fix:** mechanical sweep; then extend
    the provenance gate with a stale-string denylist so these cannot recur.
14. **`docs/01-architecture.md`:** references non-existent
    `enterprise/nested_governance_layers.yaml`; wrong module path for
    `OracleDiversityTracker`; degenerate module table. Small fixes.

### Statistics presentation
15. **AII precision theater:** reported to 4 significant figures with
    researcher-chosen weights; T₂'s formula was changed mid-experiment
    (1−r/0.27 → exp(−r/0.20)) making the trend non-comparable across the
    break. Report ≤2 decimals, mark the metric-version break on every trend,
    never say "theoretical ceiling", and lead with the honest
    renormalized-AII≈0.52-without-T₄ caveat rather than trailing it.
16. **Operating thresholds without CIs:** τ*=0.2032 to 4 decimals from N=544;
    the τ≥0.10 "groupthink boundary" driving PhaseAwareGuardrail rests on
    N=21 vs N=11. CIs beside every threshold; label the 0.10 boundary
    provisional.

---

## P2 — Minor (batchable)

- Four ceremonial write-ups of the one-line V=F(T=−1) identity — collapse to
  match the supplement's honest "design consequence" note.
- `potts.py` "exact result T_c = J(k−1)/k" — cite or delete ("exact" is
  unearned; mean-field q≥3 Potts is first-order).
- Causal domain YAMLs: keep the partial-specification disclosure; no
  generalization claims.
- `docs/06-reproducibility.md` Claim 5 points at the stale PDF instead of the
  committed JSONs it could name.
- Use-case README: "8 tools" vs 14 actual; "three Cloudflare Workers" vs four.
- `theoretical_foundations_proposals_v1.md` proposes
  `remora/selective/adaptive_conformal.py` — fine as roadmap, but the doc
  should carry its PROPOSED banner near those lines too.

---

## What already withstands this reviewer (do not break while fixing)

NEGATIVE_RESULTS discipline incl. published below-chance χ AUC and the T–D
circularity confession; the claim register + provenance gate + anchors; the
explain/decide parity harness (a genuine answer to post-hoc-faithfulness
critique); paper's own "Is thermodynamic terminology scientifically
justified? No physical law applies" Q&A; per-claim caveats-as-part-of-claim
rule; the 2026-06-25 external review being documented verbatim; anytime-valid
REM-020 bound; stage-1-vs-consensus anti-conflation rule. The reviewer's
summary line: *"the discipline exists but is not enforced uniformly"* — the
remediation goal is uniformity, not new machinery.

---

## Execution plan

| Wave | Items | Effort | Owner-blocking? |
|------|-------|--------|-----------------|
| 1 — **CLOSED 2026-07-03** | P0-1 citations (Dong & Wang corrected incl. removal of the unsupported "<50 ms" figure; fabricated EACL-2026 entry deleted; Farquhar et al. Nature 2024 added and cited in-text; Du et al./AgentHarm/Raji venues fixed), P0-2 maxent docstring rewritten with explicit withdrawal note + claim_register.md row corrected, P1-13 stale sweep (incl. 3 additional hits found by the new denylist), P1-14 docs/01 fixes. The provenance gate now carries a stale-string denylist so the P1-13 class cannot recur. | hours | no |
| 2 — **CLOSED 2026-07-03** | P0-3: docs/07-api-reference.md rewritten against source (real DecisionReport/PolicyObservation/OracleResponse/adapter/MCP surfaces; enforcement integration-status stated) and bound by `tests/test_api_reference_doc.py` (16 introspection tests, incl. bidirectional MCP-tool coverage). Bonus find: the code's own docstrings referenced a nonexistent `DirectPolicyGateway` class in 7 places — corrected to the real `LocalGateway`. P1-9: demo rewritten to drive the real `RemoraDecisionEngine` (canonical outcomes + engine reason codes; README transcript regenerated from actual output; bound by `tests/test_demo_building_lights.py`). P1-12: frontend strings corrected (94.7% @ 25% *coverage* + calibration-set caveat; 82.8% labeled as majority-vote baseline; 88% now carries its Wilson CI; RDF/OTel audit fiction replaced with the real SHA-256 hash chain) and bound by `tests/test_frontend_prose_claims.py`. | 1–2 days | no |
| 3 — **CLOSED 2026-07-03** | P0-4: new paper §2.11 "Runtime Guardrails, Agent Permissioning, and AI Control" — content guardrails (Llama Guard, NeMo, Constitutional Classifiers, RBR), agent-level systems (LlamaFirewall, GuardAgent, AgentSpec), permissioning frontier (Progent, CaMeL — explicitly pre-empting the corner-point reading), benchmarks (AgentDojo, ToolEmu, InjecAgent, R-Judge, τ-bench; ToolEmu acknowledged as conceptual precedent for Shadow Mode — "unique" claims corrected in paper_alignment doc), AI control (Greenblatt et al. — REMORA framed as trusted-monitoring protocol with the subversive-agent gap stated), COMPL-AI, and the four alignment-doc papers promoted into References. §2.5 extended with the conformal-for-LLMs boundary (Mohri & Hashimoto; Yadkori et al.). P0-5: AgentTrust (arXiv:2606.08539) and Membrane (arXiv:2606.05743) read and differentiated in §2.11 — the load-bearing difference: AgentTrust self-distills judge decisions into its enforcement rules, REMORA's floor is fixed policy-as-code with a never-weakens-tested learning layer. References: 36 → 60 entries, sorted. | 1–2 days | reading required |
| 4 — **CLOSED 2026-07-03** | Math corrections (behavior-preserving where artifacts depend on it, honest-relabel otherwise): theorem inequality direction fixed (`hallucination_bound_theorem.py`: q^⌊n/2⌋ not q^n/2, explicit A5 between-pair-independence assumption, no-clamp honest values, tests + breakthrough_proof.md table recomputed); runtime `hallucination_bound` relabeled a heuristic proxy with both departures (n/2 exponent + 0.49 clamp understating within-family risk) documented in-code and in paper §5.1; `critical_exponent_gamma` and `compute_phase_diagram` docstrings state they are 2D-lattice decoration / synthetic illustration feeding no routing; live χ disclosed in paper §5.1 as algebraically 1/T_c (verified) rather than a measured sensitivity; groupthink τ≥0.10 boundary labeled provisional (N=21 vs 11); abstract "theoretical ceiling" → "structural composite ceiling (arithmetic property)"; F.2 metric-version-break warning + ≤2-decimal guidance; λ 0.3/0.4/1.0 reconciled at the definition site; gibbs.py T=−1 relabeled a sign convention; potts.py "exact result" softened with first-order q≥3 note; README "phase transitions" → "labeled threshold crossings"; `thermodynamic_abs.md` fully rewritten with a vocabulary disclaimer (removed "proportionally scalar", "Gold Standard … proven"). Runtime numerics unchanged; all committed artifacts still valid. | 2–3 days | rename decisions |
| 5 — **CLOSED 2026-07-03** | P1-10: SHADOW_ONLY/illustrative banner + ETR definition added to all 8 use-case files and the directory README; identity reframed to action-governance ("not a fact-checker"); unartifacted "~3% false positives" removed (replaced with the honest N=75 sample framing); "8 tools"→14; broken external go-star links neutralized. P1-11: docs/02 given a complete-claim-set table binding all 11 register claims (was 5 behind), with the register named source of truth. P1-7: new paper §13.11 states no human evaluation of explanations exists (faithfulness is machine-verified via the parity harness; comprehensibility is not), and that the causal module does no identification (SCM is the engine). | 2–3 days | no |
| P0-6 — **CLOSED 2026-07-03** | Causal artifacts located in the main repo and restored: `remora/causal/attribution.py` + `search.py` (paper §13.10 citation now resolves; imports verified; `tests/test_causal_search_attribution.py` copied, 22 pass), and the two CLAIM-009 artifacts `external_dataset_eval*.json` — which also emptied the provenance baseline (0 baselined violations). The D1-publishing script `aromer_publish_causal.py` legitimately stays in the main repo (needs live-Worker infra, like CLAIM-003's script); the two paper citations that implied it lives here are annotated. | — | done (main repo access used) |

Gate rule for closure: each item closes only with a commit reference here, and
Waves 1–2 must land before any external reviewer is invited (REM-021).
