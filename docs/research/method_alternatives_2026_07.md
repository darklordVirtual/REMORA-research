# Method Alternatives After the 2026-07 Round — Survey and Offline Tests

Status: research note. The offline results quoted here come from an
**exploratory** artifact
(`results/selection_signal_shootout_2026_07.json`, marked
`status: exploratory`) and are hypothesis-generating only — they exist to
decide what the next round (SAP v3) pre-registers, not to support claims.

## The three problems the round exposed

1. **Unweighted cross-family majority (85.3 %) underperformed the best
   single model (87.5 %).** Voting alone buys nothing.
2. **Discrete phase routing helped 0 / hurt 13 items**, and the phase
   labels are semantically miscalibrated ("critical" holds the easiest
   items). The *continuous* temperature signal still looks informative.
3. **H1′ is underpowered by design** (N_accepted = 18, p = 0.052): a
   per-round fixed-sample binomial cannot accumulate evidence across
   rounds.

## What we tested offline (zero new API calls)

Per-oracle votes were reconstructed from the round's response cache; the
same group-aware 80/20 split (seed 42) as H1′; everything supervised was
fit on the training split only. Holdout n = 108; all CIs overlap — treat
every delta as directional.

**Aggregators** (all holdout items):

| Aggregator | Accuracy | Wilson 95 % |
|---|---|---|
| majority (round baseline) | 87.0 % | [79.4, 92.1] |
| best single (llama-3.3-70b) | 88.9 % | [81.6, 93.5] |
| **confidence-weighted vote** | **89.8 %** | [82.7, 94.2] |
| log-odds weighted (Nitzan–Paroush, train-fit) | 87.0 % | [79.4, 92.1] |
| Dawid–Skene EM (unsupervised, train-fit) | 84.3 % | [76.2, 89.9] |

Reading: confidence weighting is the only aggregator that directionally
beats both majority and the best single model. Nitzan–Paroush collapses to
majority here because the three oracles' train accuracies are nearly equal
(the theorem only pays when competences differ). Unsupervised Dawid–Skene
*hurts* at this scale — dropped.

**Selection signals** (τ from train at a coverage target; prediction =
majority vote among accepted, as in H1′):

| Signal | @ ~0.10 | @ 0.18 (pre-registered point) | @ ~0.30 |
|---|---|---|---|
| neg_temperature | 100 % (12/12, cov .11) | 100 % (18/18, cov .17) | **100 % (28/28, cov .26)** |
| margin (vote split) | 97.4 % (37/38, cov .35)* | same* | same* |
| mean confidence | 97.6 % (40/41, cov .38)* | same* | same* |
| trust_score | 100 % (12/12, cov .11) | 96.0 % (24/25, cov .23) | 97.2 % (35/36, cov .33) |
| −χ (susceptibility) | 100 % (17/17, cov .16) | 92.0 % (23/25, cov .23) | 92.1 % (35/38, cov .35) |
| random floor | 83.3 % | 91.7 % | 89.3 % |

\* margin and raw confidence are too coarse to hit low coverage targets —
they overshoot to their natural operating points (~35–38 %).

Reading: temperature stays perfect out to ~26 % achieved coverage (28/28 —
a stronger directional showing than the pre-registered 18 % point), and is
the only signal that can be *tuned* into the low-coverage regime. But the
simple signals are far from useless: at the coverage they can reach,
margin/confidence hit ~97.5 %. The honest statement remains: temperature's
edge over a *continuous, calibrated* confidence baseline at matched
coverage is still unproven — that comparison is exactly what SAP v3 must
pre-register.

## Theorems and methods we had overlooked (or under-used)

### 1. Selective prediction with finite-sample guarantees

- **Selection with Guaranteed Risk (SGR)** — Geifman & El-Yaniv 2017:
  given a ranking signal, choose the threshold via a binomial tail bound
  so selective risk ≤ r* with confidence 1−δ. Directly replaces our
  "coverage percentile" thresholding with a *certified* operating point,
  and works at our sample sizes.
- **Conformal Risk Control** — Angelopoulos et al. 2024: the finite-sample
  criterion (n/(n+1))·R̂_n + B/(n+1) ≤ α that issue #11 already identified
  as the honest version of our selective router. Implementing real CRC
  both closes #11 and gives the acceptance gate a distribution-free
  guarantee under exchangeability.
- **Learn-then-Test** — Angelopoulos et al. 2021: threshold calibration as
  multiple hypothesis testing with family-wise error control; lets us
  certify *any* monotone risk (e.g. false-accept rate), not just accuracy.

### 2. Aggregation

- **Nitzan–Paroush optimal weighted majority** — tested; no gain while
  oracle competences are near-equal. Keep in the toolbox for trios with a
  weak member.
- **Confidence-weighted voting** — tested, directionally best. Next step:
  calibrate each oracle's self-reported confidence on the training split
  (Platt/isotonic) before weighting; uncalibrated LLM confidences are the
  known weak point.
- **Dawid–Skene / spectral meta-learners** — tested (DS); hurts at n=544
  with three near-equal voters. Not pursued.

### 3. Evidence accumulation across rounds (the N=18 problem)

- **E-values / test martingales (anytime-valid inference)** — Shafer &
  Vovk's testing-by-betting, Grünwald et al.'s safe tests: define an
  e-process for H0: accepted-accuracy ≤ p₀; each round MULTIPLIES the
  running e-value, and Ville's inequality gives a valid level-α test at
  every stopping time. This converts our situation — repeated small
  rounds, each underpowered — from a bug into a design: evidence composes
  across rounds with no alpha-spending correction, and optional stopping
  is legitimate. This is the single most useful methodological upgrade for
  the benchmark program.

### 4. Routing (replacing discrete phases)

- Drop ordered/critical/disordered as decision inputs; route on the
  **continuous** temperature percentile with an isotonic-calibrated
  (train-split-only) risk curve, or on per-item **conformal p-values**.
  The phase labels stay in artifacts as diagnostics, not as controls.

## Recommendation for SAP v3 (the ~1 200-real-item round)

1. Primary selective gate: temperature-ranked acceptance with an **SGR- or
   CRC-certified** threshold (guarantee stated in the plan), fit on the
   training half.
2. Pre-registered baseline comparison at matched coverage: calibrated
   mean-confidence and margin+confidence hybrid vs temperature.
3. Aggregator: pre-register confidence-weighted voting as a second arm
   next to majority.
4. Confirmatory statistics: e-process over rounds (anytime-valid), with
   the fixed-sample exact binomial retained as a per-round secondary.
5. Phase routing: excluded from the decision path; diagnostic only.
