# Statistical Analysis Plan v3 — IN FORCE (round start 2026-07-27)

**Status: IN FORCE** as of the round-start commit on branch
`round/sap-v3` (2026-07-27). From the round's first live oracle call,
changes require a dated deviation row in §8. SAP v2 remains the record of
the 2026-07 N544 round.

Design follows the external statistical review of 2026-07-27 and the
exploratory analysis in
`docs/research/method_alternatives_2026_07.md` — deliberately NARROWER
than the 2026-07 round: one primary question, one certified procedure,
paired statistics, and no method chosen after seeing this round's labels.

## 1. Primary question

> Can a temperature-based selection rule control selective error risk at a
> pre-declared budget, with LARGER certified coverage than a calibrated
> confidence baseline, on fresh data?

## 2. Data

- **Corpus (frozen): `remora.benchmarks.sap_v3_n1200`, n = 1231 items**
  (89 TruthfulQA + 1142 BoolQ), generated 2026-07-27 by
  `python scripts/build_benchmark.py --preset sap_v3_n1200 --hf-only
  --exclude-module remora.benchmarks.extended_v2_n500 --seed 20260727
  --truthfulqa-per-domain 500 --boolq-per-domain 1500` — HF sources only
  (no curated/adversarial additions), content-hash-deduplicated against
  the 544-item 2026-07 corpus (296 overlapping items excluded) and
  near-duplicate-filtered internally (624 removed). Domain skew (83 %
  general) is accepted and reported; stratification is by SOURCE.
- Group-aware by content hash throughout; an item's group never straddles
  a split boundary.
- **Round seed: 20260727** (corpus sampling, splits, bootstrap).
- **Three-way split (seeded, group-aware, stratified by source),
  implemented as two applications of the group-aware stratified split:
  stage 1 holdout-fraction 0.60 → development = the 40 % side; stage 2
  holdout-fraction 0.50 on the remainder → risk-calibration and test:**
  1. **Development** (40 %): define/calibrate signals — temperature
     transformation, per-oracle confidence calibration (isotonic), the
     label-independent tie-breaker. Nothing else sees these labels.
  2. **Risk calibration** (30 %): fit the certified thresholds (SGR
     primary, CRC secondary — see §4; a stale "CRC primary" parenthetical
     survived here into the in-force commit, resolved as §8 D-1). Never
     reused for development.
  3. **Test** (30 %): untouched until every procedure is frozen; every
     confirmatory number is computed here exactly once.
- The same development-split calibration may NOT be refit on later splits;
  all fitted objects are serialized and hashed before the test split is
  opened.

## 3. Oracles and aggregation

- Ensemble: the cross-family rule of SAP v2 §2 stands (no two oracles
  share a weight family; `validate_cross_family` enforced). **Frozen for
  this round (Cloudflare Workers AI, live-verified 2026-07-27):**
  `@cf/meta/llama-3.3-70b-instruct-fp8-fast` (Meta LLaMA),
  `@cf/qwen/qwen3-30b-a3b-fp8` (Alibaba Qwen),
  `@cf/mistralai/mistral-small-3.1-24b-instruct` (Mistral); documented
  reserve `@cf/openai/gpt-oss-120b` (OpenAI open-weight) if a member is
  withdrawn mid-round. Sampling temperature 0.3, max_tokens 512, the
  round's standard verdict-JSON prompt.
- Baseline single model: pre-registered here (the strongest model of the
  trio by DEVELOPMENT-split accuracy, frozen before risk calibration).
- Aggregation is tested SEPARATELY from selection (no confounded
  factorial): majority vote vs calibrated confidence-weighted vote,
  paired exact McNemar on the test split. The selection arms all use
  majority predictions, so any selection effect is attributable to the
  selector alone.

## 4. Primary arm (selection)

- Signal: consensus temperature, continuous; ONE pre-registered
  transformation (negation; no rescaling fitted outside the development
  split). The signal is a RANKING score with no inherent safety meaning;
  all safety semantics come from the certification procedure below.
- **Primary certification: high-probability selective risk control
  (SGR/LTT)** on the risk-calibration split — Geifman–El-Yaniv
  Algorithm 1 with exact Clopper–Pearson bounds, target selective risk
  **r\* = 0.05** among accepted, confidence **1 − δ = 0.90**. This
  estimand ("with probability ≥ 1 − δ the error rate among autonomously
  accepted items is ≤ r\*") is the defensible one for a
  critical-infrastructure pilot; a marginal expectation guarantee is not
  sufficient alone (method review 2026-07-27).
- **Zero certified coverage is a legitimate, reportable outcome.** The
  2026-07 demo showed SGR cannot certify r\* = 0.05 at n_cal = 436 unless
  the clean low-temperature prefix is long (the Clopper–Pearson bound
  needs roughly ln(δ/m)/ln(1 − r\*) ≈ 90 consecutive accepted items with
  ~0 errors at these settings). If certification fails, the honest result
  is "no autonomous-accept threshold is certifiable at this budget" — the
  system abstains; the budget is not softened after seeing data.
- **Secondary certification: CRC** on the same split, α = 0.05, over the
  plain 0/1 ACCEPTED-AND-WRONG loss (B = 1). The severity-weighted
  variant is DEFERRED: this knowledge corpus carries no harm-category
  annotations, and inventing severity labels post hoc would be exactly
  the adaptive loss construction CRC forbids. When a harm-annotated
  corpus exists, only the INCREASING severity component is admissible —
  friction terms (unnecessary VERIFY/ABSTAIN) decrease as acceptance
  grows, making a combined loss non-monotone in the threshold, and CRC
  can fail arbitrarily on non-monotone losses. Friction is reported
  descriptively, never inside the CRC loss. CRC's guarantee is IN
  EXPECTATION for an exchangeable test item; that semantics is quoted
  wherever the result is.
- Report on the test split: realized conditional and unconditional
  selective risk, certified vs realized coverage, Wilson CIs.

## 5. Baseline arms (selection)

- Calibrated mean confidence (isotonic per oracle on development split,
  averaged), and margin + calibrated-confidence hybrid.
- Compared at REAL matched coverage using the pre-registered
  label-independent tie-breaker (hash of item id); tie-fill fraction
  reported for every arm. AURC over the full test ranking as the
  coverage-free comparison; paired bootstrap CI on the AURC difference.

## 6. Statistics — three separated claims

**Claim A (ranking):** temperature ranks low-risk items better than the
pre-registered baselines. Evidence: AURC with paired bootstrap CI on the
difference, and accuracy-among-accepted at REAL matched coverage (paired
exact McNemar on the shared accepted sets). Marginal CIs are never used
for method comparisons.

**Claim B (risk control):** the threshold chosen by the frozen SGR
procedure controls the declared selective risk under the stated
assumptions. Evidence: the certification held on risk calibration AND the
realized selective risk on the untouched test split ≤ r\*. Success
language requires both; a certified-but-not-realized outcome is reported
as a guarantee-assumption failure, not explained away.

**Claim C (cumulative evidence; separate long-term track):** an e-process
for H₀: selective risk ≥ r\*, with preconditions fixed now: acceptance
rule frozen before labels are opened; each e-factor conditionally valid
given the full prior history (never a product of retrofitted p-values);
items enter at most once across all rounds (content-hash registry);
cluster dependence handled by group-level blocking; any model/provider
change starts a NEW e-process (no estimand mixing). Each round appends an
evidence-register record:
`{round_id, null_hypothesis, protocol_hash, model_bundle_hash,
input_population_hash, e_factor, cumulative_e_value}`; rejection at level
α needs the cumulative e-value ≥ 1/α (Ville). This track is DESCRIPTIVE
until its design has passed review by a statistician with sequential-
analysis competence — it is its own statistical design, not a SAP
footnote — and is promoted in a future SAP.

Also reported: fixed-sample exact binomial against the pre-registered
p₀ = majority accuracy on the DEVELOPMENT split (never the test split's
own baseline); risk–coverage curves.

Reporting language: every guarantee statement is quoted together with its
loss definition, data distribution, calibration sample, model and policy
versions, coverage, and statistical assumptions. Negative results are
published unchanged.

## 7. Phases and architecture

- ordered/critical/disordered phase labels are logged and visualized but
  CANNOT influence ACCEPT/VERIFY/ABSTAIN/ESCALATE in this round.
- The certified-gate library (`remora/selective/risk_control.py`) is
  wired into the decision path ONLY if Claim B succeeds; the integration
  lands as a separate reviewed change after the round. Statistical risk
  control can never override the deterministic hard guards: forbidden
  actions stay policy-blocked regardless of any certificate.

## 8. Deviations from this plan

| Date | Deviation | Impact | Why |
|------|-----------|--------|-----|
| 2026-07-27 | D-1: internal contradiction found post-start — §2's risk-calibration bullet still said "(CRC primary, SGR sensitivity)" from the pre-revision draft, while §4 explicitly declares SGR/LTT primary. §4 is the operative protocol: the SGR-primary revision (commit 632628d) predates the round-start commit, and the analysis ran SGR-primary | None on results — the analysis followed §4 | Textual leftover from the draft revision; §2 corrected with a pointer to this row |
| 2026-07-27 | D-2: PAV isotonic calibration had two implementation bugs found by external review AFTER the first analysis pass: order-dependent pooling of tied confidence values, and exact-endpoint queries mapping to the wrong block. Fixed, tests added, analysis REPLAYED from the committed collection artifact (zero new oracle calls) | All confidence-calibrated numbers regenerated; the first-pass artifact is superseded. Temperature's SGR non-certification is independent of the bug and stands | LLM confidences are coarse (many exact ties), so the tie bug hits exactly this data |
| 2026-07-27 | D-3: family-wise certification reported alongside the marginal per-arm claims — three arms were certified in parallel, so promoting a winning arm is selection-among-three; a Bonferroni δ/3 row per arm is added to the artifact. Engine-integration clause (§7) interpreted strictly: it was written for the PRIMARY (temperature) arm, which failed Claim B — a baseline arm's success does not trigger integration; it earns its own frozen confirmation round | Hybrid-arm language capped at "promising pre-registered secondary"; no engine wiring from this round | Multiplicity and clause-scope points from the post-round external review |
