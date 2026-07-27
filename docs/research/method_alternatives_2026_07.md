# Method Alternatives After the 2026-07 Round — Survey, Offline Tests, References

Status: research note. Every number below comes from the **exploratory**
artifact `results/selection_signal_shootout_2026_07.json`
(`status: exploratory`) and is hypothesis-generating only — it exists to
decide what SAP v3 pre-registers, never to support claims. Revised after
external statistical review 2026-07-27 (paired tests, matched-coverage
tie-breaking, method naming, guarantee caveats).

## The three problems the round exposed

1. **Unweighted cross-family majority (85.3 %) underperformed the best
   single model (87.5 %).** Voting alone buys nothing.
2. **Discrete phase routing helped 0 / hurt 13 items**, and the phase
   labels are semantically miscalibrated ("critical" holds the easiest
   items). The *continuous* temperature signal still looks informative.
3. **H1′ is underpowered by design** (N_accepted = 18, p = 0.052): a
   per-round fixed-sample binomial cannot accumulate evidence across
   rounds.

## Offline tests (zero new API calls)

Per-oracle votes replayed from the round's response cache; same
group-aware 80/20 split (seed 42) as H1′; supervised quantities fit on the
training split only. The "best single" model is **fixed a priori by
convention** (the round's condition-A model), not selected on the training
split — SAP v3 must pre-register or train-freeze that choice. Holdout
n = 108. The methods and coverage grid were chosen after the round's
primary results were known, on the same holdout, on a reused corpus —
everything here is directional.

### Aggregators — with PAIRED exact McNemar (the marginal-CI comparison
was the wrong test; predictions are strongly correlated on shared items)

| Aggregator | Accuracy | vs majority (discordants, p) |
|---|---|---|
| majority (round baseline) | 87.0 % | — |
| best single (fixed a priori) | 88.9 % | 3–1, p = 0.625 |
| confidence-weighted vote | 89.8 % | 3–0, p = 0.25 |
| train-fit log-odds voting, *inspired by* Nitzan–Paroush | 87.0 % | 0–0, p = 1.0 |
| one-coin latent-label EM, *inspired by* Dawid–Skene | 84.3 % | 0–3, p = 0.25 |

Reading: **no aggregator difference is established.** Confidence weighting
wins 3–0 discordant items against majority but that is p = 0.25 — and it
is one holdout item over best-single. The only significant pair is
confidence-weighted vs the one-coin EM (6–0, p = 0.031): the EM variant
genuinely hurts *in this one-coin form* — which does not indict the full
confusion-matrix Dawid–Skene family. The Nitzan–Paroush-style weights
collapse to majority because the three oracles' train competences are
nearly equal, and the optimality theorem assumes conditional independence
that correlated LLM errors violate — the arm is a heuristic here.

### Selection signals at REAL matched coverage

Coarse signals (margin, confidence) cannot reach low coverage by
thresholding — their raw operating points overshoot to 35–60 % coverage. A
label-independent hash tie-breaker forces every signal to every target;
`tie-fill` = the share of the accepted set picked by the tie-breaker
(chance within tied groups) rather than by the signal:

| Signal | acc @ matched ~0.13–0.24 cov | tie-fill | AURC (lower better) |
|---|---|---|---|
| neg_temperature | **100 %** (cov .13–.26) | 4–8 % | **0.0385** |
| margin | 96.2 % (cov .24) | 62 % | 0.0397 |
| mean confidence | 96.2 % (cov .24) | 62 % | 0.0435 |
| single-model confidence | 85.7 % (cov .26) | 100 % | 0.1012 |
| trust_score | 96.0 % (cov .23) | 4 % | 0.0687 |
| −χ (susceptibility) | 92.0 % (cov .23) | 4 % | 0.1174 |
| random floor | 91.7 % (cov .11) | — | 0.1196 |

Reading (directional): **temperature was the strongest continuous ranking
signal in this exploratory analysis of the reused corpus** — its accepted
sets are chosen by the signal (tiny tie-fill), while margin/confidence at
matched coverage are mostly chance-filling inside tied groups, and the
single-model confidence is uninformative at low coverage (100 % tie-fill).
The added value must still be confirmed on fresh data under a
pre-registered, paired comparison — margin's AURC (0.0397) is close enough
to temperature's (0.0385) that no superiority claim is possible.

### Certified gates demonstrated on round data (train-calibrated, exploratory)

- **SGR** (target risk 5 %, δ = 0.10, n_cal = 436): **not certifiable** —
  the Clopper–Pearson bound cannot reach 5 % at any coverage with this
  calibration size. A valid procedure returning nothing useful: exactly
  the "valid ≠ useful" small-sample behaviour the review warned about.
- **CRC** (α = 5 %): certifies **53 % train coverage** (criterion 0.048);
  realized on the holdout: 2 errors / 57 accepted (3.5 % conditional,
  1.9 % unconditional — within budget). NOTE the semantics: CRC controls
  the *expected unconditional* accepted-and-wrong loss of an exchangeable
  test point — not conditional accuracy among accepted, and nothing about
  distribution shift.

The asymmetry is real but it decides POWER, not the estimand. Per the
follow-up method review (2026-07-27): for a critical-infrastructure pilot
the defensible claim is the high-probability one ("with confidence
≥ 1 − δ, the error rate among autonomously accepted items is ≤ r\*"), and
an SGR run that cannot certify is an HONEST outcome — the system abstains
— not a reason to switch to the weaker expectation guarantee. SAP v3
therefore takes **SGR/LTT as primary** (with the zero-coverage outcome
explicitly legitimate and the sample-size arithmetic stated in the plan)
and **CRC as secondary** over a severity-weighted accepted-and-wrong loss
— using only the increasing severity component, because friction terms
make a combined loss non-monotone and CRC can fail arbitrarily on
non-monotone losses.

## Where the methods live

`remora/selective/risk_control.py` implements SGR (Geifman–El-Yaniv
Algorithm 1: binary search over thresholds, Bonferroni δ/m, exact
Clopper–Pearson bounds) and CRC ((n/(n+1))·R̂ + B/(n+1) ≤ α over the
monotone accepted-and-wrong loss) as LIBRARY code with tests. Nothing is
wired into the decision engine: integration is gated on the SAP v3 round
showing effect on fresh data. Both docstrings state the exchangeability
assumptions and that a certified threshold is a statistical guarantee
about the defined loss — never a general safety guarantee about an action.

## Evidence accumulation across rounds (the N = 18 problem)

E-processes (test martingales) give anytime-valid inference: a level-α
test valid at every stopping time by Ville's inequality, with evidence
composing multiplicatively across rounds. But composition is only valid
when each factor is a **conditionally valid e-value given all previous
information** — one cannot multiply arbitrary p-values or retroactively
constructed e-values. SAP v3 therefore treats this as a separate
long-term track with the preconditions fixed in advance: the exact null,
item inclusion rules, acceptance chosen before labels are opened, the p₀
policy across rounds, cluster/template dependence handling, the
model/provider-change policy, and no benchmark item counted twice.
E-processes fix optional stopping; they do **not** fix dataset reuse,
adaptive hypothesis construction, correlated observations, or estimand
drift between rounds.

## Routing: continuous and calibrated — not raw percentiles

Discrete ordered/critical/disordered labels leave the authoritative
decision path (they remain logged diagnostics). But a raw temperature
percentile is relative to the model trio, provider, benchmark population
and time period — it must be mapped to an empirical risk through a frozen
calibration procedure (isotonic regression on the development split, or
per-item conformal p-values) before any policy consumes it.

## Recommendation for SAP v3 (drafted in `docs/assurance/statistical_analysis_plan_v3.md`)

1. Three-way group-aware split: development (signal definitions +
   confidence calibration) / risk-calibration (certified threshold) /
   untouched test.
2. Primary arm: continuous temperature, one pre-registered
   transformation, one risk budget, **SGR/LTT high-probability**
   certification (zero certified coverage is a legitimate outcome); CRC
   as secondary over the increasing severity-weighted loss.
3. Baseline: calibrated mean confidence (and margin + calibrated
   confidence), compared at REAL matched coverage with the pre-registered
   label-independent tie-breaker.
4. Aggregation tested separately from selection (no confounded
   factorial shortcut): majority vs pre-registered calibrated
   confidence-weighted vote, paired exact McNemar.
5. Statistics: primary = the CRC guarantee holding on the untouched test;
   secondary = risk–coverage curves + AURC, paired method differences,
   fixed-sample exact binomial; e-process as a separate evidence track.
6. Phases: logged and visualized; cannot change
   ACCEPT/VERIFY/ABSTAIN/ESCALATE.

## References

- Y. Geifman, R. El-Yaniv (2017). *Selective Classification for Deep
  Neural Networks.* NeurIPS 2017.
  https://papers.neurips.cc/paper_files/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html
- A. N. Angelopoulos, S. Bates, A. Fisch, L. Lei, T. Schuster (2024).
  *Conformal Risk Control.* ICLR 2024.
  https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html
- A. N. Angelopoulos, S. Bates, E. J. Candès, M. I. Jordan, L. Lei
  (2021). *Learn then Test: Calibrating Predictive Algorithms to Achieve
  Risk Control.*
  https://www.gsb.stanford.edu/faculty-research/working-papers/learn-then-test-calibrating-predictive-algorithms-achieve-risk
- G. Shafer, V. Vovk et al. — game-theoretic statistics and safe
  anytime-valid inference (e-processes, Ville's inequality).
  https://pure.royalholloway.ac.uk/en/publications/game-theoretic-statistics-and-safe-anytime-valid-inference/
- S. Nitzan, J. Paroush (1982). *Optimal Decision Rules in Uncertain
  Dichotomous Choice Situations.* International Economic Review 23(2).
- A. P. Dawid, A. M. Skene (1979). *Maximum Likelihood Estimation of
  Observer Error-Rates Using the EM Algorithm.* JRSS Series C 28(1).
