# Statistical Analysis Plan v3 — DRAFT (not yet in force)

**Status: DRAFT.** This plan governs the next benchmark round (the
~1 200-fresh-item power round). It takes force at the commit that starts
that round; until then it may be revised freely. Once the round's first
live oracle call is made, changes require a dated deviation row in §8.
SAP v2 remains the record of the 2026-07 round.

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

- ~1 200 REAL items (BoolQ + TruthfulQA via the HF loaders), deduplicated
  by content hash against the 544-item 2026-07 corpus — no reused items.
- Group-aware by content hash throughout; an item's group never straddles
  a split boundary.
- **Three-way split (seeded, group-aware, stratified by source):**
  1. **Development** (40 %): define/calibrate signals — temperature
     transformation, per-oracle confidence calibration (isotonic), the
     label-independent tie-breaker. Nothing else sees these labels.
  2. **Risk calibration** (30 %): fit the certified thresholds (CRC
     primary, SGR sensitivity). Never reused for development.
  3. **Test** (30 %): untouched until every procedure is frozen; every
     confirmatory number is computed here exactly once.
- The same development-split calibration may NOT be refit on later splits;
  all fitted objects are serialized and hashed before the test split is
  opened.

## 3. Oracles and aggregation

- Ensemble: the cross-family rule of SAP v2 §2 stands (no two oracles
  share a weight family; `validate_cross_family` enforced). Provider and
  exact model ids are frozen in this plan before the round starts, with
  one documented reserve per slot.
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
  split).
- Certification: **Conformal Risk Control** on the risk-calibration split
  over the monotone accepted-and-wrong loss, budget **α = 0.05**,
  B = 1. The controlled quantity is the expected UNCONDITIONAL selective
  loss of an exchangeable test item; this semantics is quoted wherever
  the result is quoted.
- Sensitivity analysis (secondary, same splits): SGR
  (Geifman–El-Yaniv Algorithm 1, δ = 0.10) — expected to be conservative
  or vacuous at this calibration size; reported either way.
- Report on the test split: realized unconditional and conditional
  selective risk, certified vs realized coverage, Wilson CIs.

## 5. Baseline arms (selection)

- Calibrated mean confidence (isotonic per oracle on development split,
  averaged), and margin + calibrated-confidence hybrid.
- Compared at REAL matched coverage using the pre-registered
  label-independent tie-breaker (hash of item id); tie-fill fraction
  reported for every arm. AURC over the full test ranking as the
  coverage-free comparison; paired bootstrap CI on the AURC difference.

## 6. Statistics

- **Primary endpoint:** the CRC criterion held on risk calibration AND
  realized unconditional selective loss on the test split ≤ α, with the
  certified coverage reported. Success language requires both.
- Secondary: risk–coverage curves, AURC with paired bootstrap,
  temperature-vs-baseline accuracy among accepted at matched coverage
  (paired exact McNemar on the shared accepted sets), fixed-sample exact
  binomial against the pre-registered p₀ = majority accuracy on the
  DEVELOPMENT split (never the test split's own baseline).
- **E-process track (separate, long-term):** an e-value for
  H₀: selective error risk > α, computed per round from test-split items
  only, with these preconditions fixed now: acceptance rule frozen before
  labels are opened; items enter at most once across all rounds
  (content-hash registry); p₀ policy: development-split baseline of each
  round; cluster dependence handled by group-level blocking; any
  model/provider change starts a NEW e-process (no mixing of estimands).
  The running e-value is reported descriptively until this track is
  promoted in a future SAP.
- Reporting language: certified + realized ⇒ "controls risk at α on this
  distribution"; anything less stays directional. Negative results are
  published unchanged.

## 7. Phases and architecture

- ordered/critical/disordered phase labels are logged and visualized but
  CANNOT influence ACCEPT/VERIFY/ABSTAIN/ESCALATE in this round.
- The certified-gate library (`remora/selective/risk_control.py`) is
  wired into the decision path ONLY if the primary endpoint succeeds;
  the integration lands as a separate reviewed change after the round.

## 8. Deviations from this plan

| Date | Deviation | Impact | Why |
|------|-----------|--------|-----|
| (none — draft) | | | |
