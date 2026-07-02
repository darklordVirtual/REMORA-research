# Theoretical Foundations — Feature Proposals v1

**Status:** PROPOSED / NOT_IMPLEMENTED — every item in this document is
roadmap. Nothing here is a claim about the current system. Per
`docs/claim_hygiene.md`, no item may be described as a REMORA capability
until its acceptance artifact (defined per proposal below) exists on disk.

**Date:** 2026-07-02
**Context:** REMORA currently imports two formal frameworks: Lyapunov
stability tracking (`remora/policy/thermodynamic_braking.py`, paper §6) and
thermodynamic-style uncertainty observables (`remora/thermodynamics/` —
explicitly scoped as "an uncertainty-routing metaphor, not physics",
ARCHITECTURE.md). The 2026-06-25 external peer review was skeptical of
metaphor-dressing; the lesson encoded here is that **each theory import must
land as a falsifiable artifact (a test, a bound in a JSON, a gate), not as
paper vocabulary**. This document evaluates ten candidate imports against
that bar.

**Evaluation dimensions per proposal:**
- *Plugs into* — the existing component/file the theory would attach to.
- *What it buys* — concrete utility: a guarantee, a corrected statistical
  procedure, or theoretical grounding for something currently heuristic.
- *Literature* — primary references.
- *Cost* — implementation effort and dependency footprint.
- *Risk* — ways the import could become metaphor-inflation or overclaim.
- *Acceptance artifact* — what must exist on disk before any claim is made.

---

## Priority matrix (summary)

| # | Proposal | Plugs into | Utility class | Cost | Priority |
|---|----------|-----------|---------------|------|----------|
| 1 | Anytime-valid inference (e-processes, confidence sequences) | REM-020 longitudinal gate; drift detection | Fixes a statistically invalid procedure in an active release gate | Low (stdlib) | **P1** |
| 2 | Barrier certificates / forward invariance | Stage-1 hard blocks; `invariants.py` | Upgrades "measured, not proven" to a machine-checked proof for the deterministic layer | Medium | **P1** |
| 3 | Condorcet jury theorem + Dawid–Skene | Multi-oracle consensus; correlation weighting | Theoretical grounding for two existing honest findings | Low (analysis + doc) | **P2** |
| 4 | Byzantine quorum bounds | Oracle quorum gate | Honest, principled quorum sizing statement | Trivial (doc + 1 test) | **P2** |
| 5 | Neyman–Pearson framing | FAR/FBR trade-off reporting | Formalizes the AgentHarm FBR=100% corner solution | Trivial (doc) | **P2** |
| 6 | Imprecise probability / Γ-maximin | `remora/credal.py` minimax gate | Free legitimacy: the mechanism already is Γ-maximin | Trivial (doc + citation) | **P2** |
| 7 | MDL / normalized compression distance | `PromptDriftDetector` zlib heuristic | Grounds an existing heuristic in established theory | Trivial (doc + citation) | **P3** |
| 8 | Adaptive conformal inference | `remora/selective/` under drift | Coverage guarantees under distribution shift | Medium | **P3** |
| 9 | Ruin theory | Session cumulative-risk gate | Probabilistic bound for the "boiling frog" gate | Medium | **P3** |
| 10 | Prover–verifier games / debate | `remora/selective/pvd.py` | Defines what real deliberation would require | High (research) | **P4** |

P1 = recommend implementing next; P2 = low-cost reframing of existing
mechanisms, batchable; P3 = worthwhile if the relevant component becomes
load-bearing; P4 = research direction, not a near-term feature.

---

## 1. Anytime-valid inference: e-processes and confidence sequences — **P1**

> **Status update 2026-07-02: IMPLEMENTED (library + artifact).**
> `remora/selective/confidence_sequence.py` (Beta-mixture confidence
> sequence, stdlib-only) + `tests/test_confidence_sequence.py` (17 tests,
> including a seeded demonstration that per-step Wilson monitoring violates
> its nominal level while the sequence holds) +
> `scripts/compute_far_confidence_sequence.py` →
> `results/far_confidence_sequence_v1.json` (0/168 cycles → 95%
> time-uniform upper bound 4.72%). Registered as CLAIM-011 (theoretical).
> The REM-020 criterion itself is unchanged pending owner sign-off — the
> bound is reported as supplementary in `release_gates.md`. The
> conformal-martingale drift detector remains unimplemented.

**Problem being solved.** REM-020 (release gate, IN_PROGRESS) monitors FAR
continuously over a 7-day window and will be closed the day the criterion
holds (`docs/assurance/release_gates.md`, `results/longitudinal_stability_v1.json`).
Fixed-sample intervals (Wilson, Clopper–Pearson — used throughout the repo)
are valid only at a single, pre-committed sample size. Monitoring
continuously and acting the day a threshold is crossed is *optional
stopping*, which invalidates fixed-N coverage guarantees (the "peeking"
problem). The current gate is therefore statistically vulnerable to exactly
the kind of reviewer objection the repo works hardest to avoid.

**The theory.** Confidence sequences are interval estimators valid
*uniformly over time*: P(∀n: θ ∈ CIₙ) ≥ 1−α. They descend from Ville's
inequality for nonnegative supermartingales (Ville 1939) and Robbins-school
sequential analysis (Darling & Robbins 1967), with modern nonparametric,
nonasymptotic constructions in Howard et al. (2021) and betting-based
constructions for bounded variables in Waudby-Smith & Ramdas (2024). The
companion concept — e-values/e-processes ("testing by betting", Shafer 2021;
Vovk & Wang 2021; survey in Ramdas et al. 2023) — gives sequential tests
that remain valid under continuous monitoring and arbitrary stopping.

**Plugs into.**
- REM-020: replace/augment the windowed FAR check with a time-uniform
  confidence sequence on the FA rate; the gate closes when the upper
  confidence bound stays below threshold — valid regardless of when it is
  inspected.
- `remora/selective/drift_detector.py`: a conformal-martingale drift
  detector (Vovk, Nouretdinov & Gammerman 2003) as a principled complement
  to the current KS test; anytime-valid, no fixed test schedule needed.
- Any future "monitor a rate, act when it crosses" gate (FBR tracking,
  oracle failure rates).

**What it buys.** Replaces a statistically invalid procedure in an *active
release-blocking gate* with a provably correct one. This is the highest
utility-to-effort item in the document: it converts a likely external-review
finding into a methodological strength.

**Literature.**
- Ville, J. (1939). *Étude critique de la notion de collectif.* Gauthier-Villars.
- Darling, D. A. & Robbins, H. (1967). Confidence sequences for mean, variance, and median. *PNAS* 58(1).
- Howard, S. R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). Time-uniform, nonparametric, nonasymptotic confidence sequences. *Annals of Statistics* 49(2).
- Shafer, G. (2021). Testing by betting: a strategy for statistical and scientific communication. *JRSS-A* 184(2).
- Vovk, V. & Wang, R. (2021). E-values: calibration, combination and applications. *Annals of Statistics* 49(3).
- Ramdas, A., Grünwald, P., Vovk, V. & Shafer, G. (2023). Game-theoretic statistics and safe anytime-valid inference. *Statistical Science* 38(4).
- Waudby-Smith, I. & Ramdas, A. (2024). Estimating means of bounded random variables by betting. *JRSS-B* 86(1).
- Vovk, V., Nouretdinov, I. & Gammerman, A. (2003). Testing exchangeability on-line. *ICML 2003.*

**Cost.** Low. Betting-style confidence sequences for a Bernoulli rate are
~100 lines of stdlib Python. No new dependencies.

**Risk.** Low. The construction is exact, not asymptotic; the main risk is
wider intervals than Wilson at any fixed N (the price of time-uniformity) —
which must be communicated, not hidden.

**Acceptance artifact.** `remora/selective/confidence_sequence.py` +
dedicated tests + `results/longitudinal_stability_v2.json` carrying a
time-uniform upper bound on FAR alongside the existing fields, and
release_gates.md REM-020 criterion restated in terms of the sequence.

---

## 2. Barrier certificates / forward invariance of the safe set — **P1**

**Problem being solved.** The canonical safety claim rests on the
deterministic Stage-1 hard-block layer (`remora/policy/decision_engine.py`),
currently evidenced by invariant enumeration tests
(`tests/test_policy_invariants_prop.py`), mutation tests, and benchmark
FAR=0 results — with the standing caveat that Lyapunov results are "a
measurement of empirical behavior, not proof" (paper §10.4).

**The theory.** A barrier certificate (Prajna & Jadbabaie 2004; stochastic
version Prajna, Jadbabaie & Pappas 2007) is a function B(x) with B ≤ 0 on
the safe set, B > 0 on the unsafe set, and a non-increase condition along
system trajectories — establishing *forward invariance*: trajectories
starting safe stay safe. Control barrier functions (Ames et al. 2019) are
the control-synthesis form. For stochastic systems, nonnegative
supermartingales play the role of barriers (Kushner 1967; Chakarov &
Sankaranarayanan 2013), which connects directly to REMORA's existing
Lyapunov machinery.

**Plugs into.**
- The decision engine's rule ladder: define the unsafe set as
  {observations where ACCEPT would violate a hard invariant} and prove — by
  exhaustive case analysis over the finite discrete signal space, which is
  machine-checkable — that no ACCEPT path is reachable from it. The
  existing INV-1..INV-12 invariants and the explain()/decide() parity
  harness (`tests/test_explain_decide_parity.py`) are the natural
  substrate: the parity test already establishes that the ladder equals its
  trace; a barrier formulation would establish what the ladder guarantees.
- `thermodynamic_braking.py`: the Lyapunov-derivative trust penalty could be
  restated as a discrete-time barrier condition on the trust dynamics.

**What it buys.** Upgrades the safety floor from "tested exhaustively on a
grid" to "proven as forward invariance of a formally defined safe set" for
the deterministic layer. This is the difference between an empirical claim
and a theorem about the artifact — precisely the kind of statement external
reviewers asked for. It does *not* extend to caller-supplied detection
signals (the guarantee remains conditional on inputs, which must be stated).

**Literature.**
- Prajna, S. & Jadbabaie, A. (2004). Safety verification of hybrid systems using barrier certificates. *HSCC 2004*, LNCS 2993.
- Prajna, S., Jadbabaie, A. & Pappas, G. J. (2007). A framework for worst-case and stochastic safety verification using barrier certificates. *IEEE Trans. Automatic Control* 52(8).
- Ames, A. D., Coogan, S., Egerstedt, M., Notomista, G., Sreenath, K. & Tabuada, P. (2019). Control barrier functions: theory and applications. *ECC 2019.*
- Kushner, H. J. (1967). *Stochastic Stability and Control.* Academic Press.
- Chakarov, A. & Sankaranarayanan, S. (2013). Probabilistic program analysis with martingales. *CAV 2013.*

**Cost.** Medium. The deterministic proof is a bounded model-checking
exercise over the observation signal space (SMT solver like Z3, or
exhaustive enumeration given the discrete flags); the honest scoping ("the
safe set is defined over engine inputs, not world states") requires careful
writing.

**Risk.** Medium. The main failure mode is overclaiming scope: a barrier
proof over `PolicyObservation` inputs says nothing about detector quality
upstream. The claim must be phrased as *conditional* forward invariance.

**Acceptance artifact.** A machine-checked proof artifact (e.g.
`artifacts/barrier_certificate_v1/` with the SMT encoding + verification
log, or an exhaustive-enumeration script with committed output) + a paper
section stating the conditional guarantee and its exact scope.

---

## 3. Condorcet jury theorem + Dawid–Skene oracle reliability — **P2**

**Problem being solved.** The multi-oracle consensus layer is currently
justified operationally. Two honest findings lack theoretical framing:
(a) three same-family Llama oracles provide only "partial diversity"
(paper §13.5, RR Q4); (b) correlation-weighted consensus (69.54%) does not
beat raw majority vote (82.78%) on full-coverage accuracy (paper §11.3,
Table 2).

**The theory.** Condorcet's jury theorem (1785): if voters are independent
with competence p > 1/2, majority-vote accuracy increases monotonically in
n and → 1. Both assumptions matter: under correlated votes the theorem
degrades sharply (Ladha 1992), and the *optimal* weighted rule under known
competences weights each voter by log(pᵢ/(1−pᵢ)) (Nitzan & Paroush 1982;
overview in Grofman, Owen & Feld 1983). Dawid & Skene (1979) give the EM
procedure for estimating per-rater (here: per-oracle) confusion matrices
from agreement data without ground truth.

**Plugs into.**
- `remora/correlation.py` (diversity weights): the correlation penalty is a
  heuristic approximation of the Condorcet correlation correction — this
  can be stated and tested.
- §11.3/§13.5 of the paper: both findings become *predictions* of the
  theory rather than surprises — same-family oracles violate independence,
  and log-odds weighting (not correlation-penalized averaging) is the
  optimal aggregation under the model.
- AROMER's oracle selection: Dawid–Skene competence estimates as input to
  the weighting, replacing researcher-chosen constants.

**What it buys.** Explains two documented results, converts the
"distinct model families" design requirement (§4.1) from an intuition into
a theorem-backed requirement, and provides a principled path (Nitzan–Paroush
weights over Dawid–Skene estimates) if weighted aggregation is revisited.

**Literature.**
- de Condorcet, N. (1785). *Essai sur l'application de l'analyse à la probabilité des décisions rendues à la pluralité des voix.*
- Nitzan, S. & Paroush, J. (1982). Optimal decision rules in uncertain dichotomous choice situations. *International Economic Review* 23(2).
- Grofman, B., Owen, G. & Feld, S. L. (1983). Thirteen theorems in search of the truth. *Theory and Decision* 15.
- Ladha, K. K. (1992). The Condorcet jury theorem, free speech, and correlated votes. *American Journal of Political Science* 36(3).
- Dawid, A. P. & Skene, A. M. (1979). Maximum likelihood estimation of observer error-rates using the EM algorithm. *Applied Statistics (JRSS-C)* 28(1).

**Cost.** Low. An analysis notebook/script computing Dawid–Skene estimates
and Nitzan–Paroush weights on the existing N=302/N=544 per-item oracle
records (`artifacts/benchmark_n500_locked.json` has per-item data), plus a
related-work paragraph.

**Risk.** Low. Purely explanatory unless weighting is changed; if weighting
*is* changed, it must go through the full benchmark + claim-register cycle.

**Acceptance artifact.** `results/oracle_reliability_dawid_skene_v1.json`
(per-oracle confusion estimates + implied optimal weights + comparison
against current weighting on the committed benchmarks).

---

## 4. Byzantine quorum bounds — **P2**

**Problem being solved.** The oracle quorum gate
(`decision_engine.py`, MIN_REQUIRED_ORACLE_VOTES=2 of n=3) is motivated in
a code comment by indistinguishability from "a degraded or compromised
oracle pool" — Byzantine-fault language without the accompanying
mathematics.

**The theory.** Reaching agreement with f Byzantine (arbitrarily faulty /
adversarial) participants requires n ≥ 3f+1 (Pease, Shostak & Lamport 1980;
Lamport, Shostak & Pease 1982). Byzantine quorum systems (Malkhi & Reiter
1998) generalize to read/write quorums; PBFT (Castro & Liskov 1999) is the
canonical practical protocol. Crash faults (non-adversarial) need only
n ≥ 2f+1.

**Plugs into.** The quorum gate's documentation and the paper's threat
model (`docs/assurance/threat_model` items on oracle compromise).

**What it buys.** The honest, publishable statement: *with n=3 oracles and
a 2-vote quorum, REMORA tolerates f=1 crash-faulted oracle and f=0
Byzantine oracles; robustness against a single actively compromised oracle
requires n ≥ 4.* This converts vague compromise language into a precise,
falsifiable design parameter and gives the roadmap criterion for growing
the oracle pool.

**Literature.**
- Pease, M., Shostak, R. & Lamport, L. (1980). Reaching agreement in the presence of faults. *JACM* 27(2).
- Lamport, L., Shostak, R. & Pease, M. (1982). The Byzantine generals problem. *ACM TOPLAS* 4(3).
- Malkhi, D. & Reiter, M. (1998). Byzantine quorum systems. *Distributed Computing* 11(4).
- Castro, M. & Liskov, B. (1999). Practical Byzantine fault tolerance. *OSDI '99.*

**Cost.** Trivial: a documentation section, a threat-model row, and one
test asserting the documented tolerance (a single adversarial oracle CAN
flip outcomes at n=3 — documenting the limitation, in the spirit of
`test_policy_engine_audit_v1.py`'s honest-gap tests).

**Risk.** None if stated as a limitation; the risk would be implying BFT
robustness the quorum does not have.

**Acceptance artifact.** Threat-model update + an honest-gap test
(`tests/` demonstrating single-Byzantine-oracle influence at n=3).

---

## 5. Neyman–Pearson framing of the FAR/FBR trade-off — **P2**

**Problem being solved.** The flagship external result (AgentHarm N=208:
FAR=0%, FBR=100%) is a corner solution — everything blocked. README now
discloses this, but the repo lacks the standard decision-theoretic frame
for *why* a corner solution is a defensible v1 and what calibrated
improvement means.

**The theory.** The Neyman–Pearson lemma (1933) characterizes the optimal
test at a fixed type-I error budget: the likelihood-ratio test maximizes
power subject to α. NP *classification* (Scott & Nowak 2005; Tong, Feng &
Li 2018) transfers this to learning: minimize type-II error (here: benign
friction, FBR) subject to a hard constraint on type-I error (here: unsafe
accepts, FAR ≤ α).

**Plugs into.** Results reporting (paper §10, README evidence section) and
any future threshold calibration: the target is the NP-optimal operating
point at FAR ≤ α, not accuracy maximization.

**What it buys.** (a) The precise statement that FAR=0/FBR=100 is the
trivially feasible point of the NP program, valuable as a floor but not as
a discriminator; (b) the correct objective for the next iteration
(minimize FBR s.t. FAR ≤ α with α from the release gates); (c) inoculation
against the reviewer objection "your safety result is just blocking
everything" — pre-empted by framing it as the feasible corner of a
constrained program, with the movement plan stated.

**Literature.**
- Neyman, J. & Pearson, E. S. (1933). On the problem of the most efficient tests of statistical hypotheses. *Phil. Trans. R. Soc. A* 231.
- Scott, C. & Nowak, R. (2005). A Neyman–Pearson approach to statistical learning. *IEEE Trans. Information Theory* 51(11).
- Tong, X., Feng, Y. & Li, J. J. (2018). Neyman–Pearson classification algorithms and NP receiver operating characteristics. *Science Advances* 4(2).

**Cost.** Trivial (documentation). A calibrated NP threshold would be a
separate, full-cycle feature.

**Risk.** None at the documentation level.

**Acceptance artifact.** Paper/README paragraphs restating the AgentHarm
result in NP terms; roadmap entry for NP-calibrated thresholds with its own
acceptance criteria.

---

## 6. Imprecise probability / Γ-maximin decision rule — **P2**

**Problem being solved.** `remora/credal.py` computes interval-valued harm
estimates and `decision_engine.py`'s minimax gate escalates on worst-case
loss over the interval. This *is* the Γ-maximin decision rule from
imprecise-probability theory — currently presented without lineage, so it
reads as ad hoc.

**The theory.** Credal sets and lower/upper previsions (Walley 1991) are
the standard formalization of interval-valued uncertainty; Γ-maximin
(choose the act with the best worst-case expectation over the credal set)
is one of the canonical decision rules (Troffaes 2007 surveys the
alternatives — Γ-maximax, E-admissibility, maximality — and their
trade-offs). Gilboa & Schmeidler (1989) give the axiomatic foundation
(maxmin expected utility with multiple priors). Augustin et al. (2014) is
the modern reference text.

**Plugs into.** `remora/credal.py` docstrings, paper §5, related work.
Optionally: evaluate E-admissibility as an alternative gate criterion
(Troffaes argues Γ-maximin can be overly conservative — which for a safety
gate is a *feature*, and that argument should be made explicitly).

**What it buys.** Free legitimacy — the mechanism already implements a
well-axiomatized rule; citing it converts "homemade interval heuristic"
into "Γ-maximin over a credal set constructed from oracle disagreement",
and the conservatism critique from the IP literature becomes a documented
design choice rather than an oversight.

**Literature.**
- Walley, P. (1991). *Statistical Reasoning with Imprecise Probabilities.* Chapman & Hall.
- Gilboa, I. & Schmeidler, D. (1989). Maxmin expected utility with non-unique prior. *Journal of Mathematical Economics* 18(2).
- Troffaes, M. C. M. (2007). Decision making under uncertainty using imprecise probabilities. *International Journal of Approximate Reasoning* 45(1).
- Augustin, T., Coolen, F. P. A., de Cooman, G. & Troffaes, M. C. M. (eds.) (2014). *Introduction to Imprecise Probabilities.* Wiley.

**Cost.** Trivial (docstrings + paper paragraph + citations).

**Risk.** None; strictly descriptive.

**Acceptance artifact.** Updated `credal.py` module docstring + paper §5
lineage paragraph + related-work entries.

---

## 7. MDL / normalized compression distance for drift — **P3**

**Problem being solved.** `PromptDriftDetector`
(`remora/selective/drift_detector.py`) uses zlib compression density and
log-length z-tests — presented as a heuristic.

**The theory.** Minimum Description Length (Rissanen 1978; Grünwald 2007)
formalizes "regularity = compressibility"; the similarity metric and
normalized compression distance (Li et al. 2004; Cilibrasi & Vitányi 2005)
give a universal, parameter-free similarity measure computable with any
real compressor — zlib density against a calibration corpus is a one-sided
special case.

**Plugs into.** `drift_detector.py` documentation; optionally upgrade the
detector to proper NCD against the calibration set (pairwise compressed
sizes), which is a small, testable change.

**What it buys.** Grounds an existing heuristic; the NCD upgrade would make
the detector sensitive to *content* novelty rather than only
density/length shifts, with the same zero-dependency footprint.

**Literature.**
- Rissanen, J. (1978). Modeling by shortest data description. *Automatica* 14(5).
- Li, M., Chen, X., Li, X., Ma, B. & Vitányi, P. (2004). The similarity metric. *IEEE Trans. Information Theory* 50(12).
- Cilibrasi, R. & Vitányi, P. (2005). Clustering by compression. *IEEE Trans. Information Theory* 51(4).
- Grünwald, P. (2007). *The Minimum Description Length Principle.* MIT Press.

**Cost.** Trivial for citation; low for the NCD upgrade (+ recalibration of
the detector's thresholds and its fail-open sample floor).

**Risk.** Low. NCD's theoretical guarantees assume "normal" compressors;
zlib approximately qualifies — state this.

**Acceptance artifact.** For the upgrade: revised detector + tests +
before/after comparison on the committed drift fixtures.

---

## 8. Adaptive conformal inference under distribution shift — **P3**

**Problem being solved.** Split-conformal guarantees (`remora/selective/`)
assume exchangeability; deployment traffic drifts. ARCHITECTURE.md briefly
referenced an (unimplemented) `adaptive_conformal.py` — the reference was
removed 2026-07-02; this proposal is the real version of that ambition.

**The theory.** Weighted conformal prediction restores coverage under known
covariate shift (Tibshirani et al. 2019 — already the basis for
`crc.py`'s importance weights). Adaptive conformal inference (Gibbs &
Candès 2021) goes further: an online update of the miscoverage level that
achieves the target coverage *in time-average over arbitrary distribution
shift*, with follow-up work for general online settings (Gibbs & Candès
2024; Zaffran et al. 2022 for time series).

**Plugs into.** A new `remora/selective/adaptive_conformal.py` implementing
the ACI recursion over the decision stream, feeding the Mondrian/marginal
thresholds that `RemoraDecisionEngine` accepts as constructor parameters
(currently static, calibrated offline).

**What it buys.** A coverage statement that survives drift — the current
guarantees are honest but static, and the repo's own caveats flag
split-seed and shift sensitivity. ACI's guarantee is exactly the form
REMORA's shadow-mode stream needs. Interacts with proposal 1 (both are
online-validity upgrades).

**Literature.**
- Tibshirani, R. J., Barber, R. F., Candès, E. J. & Ramdas, A. (2019). Conformal prediction under covariate shift. *NeurIPS 2019.*
- Gibbs, I. & Candès, E. J. (2021). Adaptive conformal inference under distribution shift. *NeurIPS 2021.*
- Zaffran, M., Féron, O., Goude, Y., Josse, J. & Dieuleveut, A. (2022). Adaptive conformal predictions for time series. *ICML 2022.*
- Gibbs, I. & Candès, E. J. (2024). Conformal inference for online prediction with arbitrary distribution shifts. *JMLR* 25.

**Cost.** Medium: the recursion is simple, but wiring online threshold
updates into the (currently stateless) engine crosses an architectural
boundary — "REMORA is stateless; all fields caller-populated"
(`observation.py`). The update loop must live in the caller/AROMER layer,
not the engine.

**Risk.** Medium. ACI guarantees *time-average* coverage, not per-period —
easy to overclaim; and online threshold adaptation is a new attack surface
(an adversary manipulating the stream drags the threshold), which the
threat model must cover before this ships.

**Acceptance artifact.** `remora/selective/adaptive_conformal.py` + tests +
a shadow-replay evaluation artifact showing realized coverage under an
induced shift, with the time-average scope stated in the caveat.

---

## 9. Ruin theory for session cumulative risk — **P3**

**Problem being solved.** The session sequential-risk gate
(`decision_engine.py`: session_cumulative_risk > 0.80 → VERIFY) guards
against "boiling frog" attacks with a hand-set threshold on a hand-summed
score.

**The theory.** Ruin theory (Lundberg 1903; Cramér 1930; modern treatment
Asmussen & Albrecher 2010) studies exactly this object: a reserve process
under a stream of stochastic claims, with the Cramér–Lundberg inequality
bounding the probability that cumulative claims ever exhaust the reserve —
i.e. a *whole-horizon* bound on threshold crossing, not a per-step check.

**Plugs into.** The session gate: model per-action risk contributions as
claims against a session risk budget; choose the budget/threshold so the
ruin bound (probability any session accumulates past the true danger level)
is below a target.

**What it buys.** Converts an arbitrary 0.80 into a derived quantity with a
stated survival guarantee, and gives the session gate the same
"bound-in-an-artifact" character as the conformal layer. Note the honest
dependency: the bound is only as good as the per-action risk-score model,
which is caller-supplied.

**Literature.**
- Lundberg, F. (1903). *Approximerad framställning af sannolikhetsfunktionen / Återförsäkring af kollektivrisker.* Uppsala.
- Cramér, H. (1930). *On the Mathematical Theory of Risk.* Skandia Jubilee Volume.
- Asmussen, S. & Albrecher, H. (2010). *Ruin Probabilities* (2nd ed.). World Scientific.

**Cost.** Medium: requires a distributional model of per-action risk scores
(estimable from AROMER's episode corpus) before any bound is meaningful.

**Risk.** Medium — this is the proposal most susceptible to
metaphor-inflation: without a validated claims distribution, a
Cramér–Lundberg bound is decoration. Do not import the vocabulary before
the distributional homework exists.

**Acceptance artifact.** An artifact deriving the session threshold from a
fitted claims distribution + the resulting ruin bound + sensitivity
analysis; gate threshold in `decision_engine.py` updated to reference it.

---

## 10. Prover–verifier games and debate — **P4**

**Problem being solved.** `remora/selective/pvd.py` ("Prover-Verifier
Deliberation") currently *simulates* deliberation rounds — a deterministic
backend re-scores unchanged inputs (disclosed in the docstring;
ARCHITECTURE.md now describes it accurately). The module name promises a
mechanism the literature actually defines.

**The theory.** AI safety via debate (Irving, Christiano & Amodei 2018)
proposes adversarial two-agent argumentation judged by a weaker verifier,
with complexity-theoretic backing in doubly-efficient debate (Brown-Cohen,
Irving & Piliouras 2023). Prover–verifier games (Anil et al. 2021)
formalize checkability as a game-theoretic training objective;
Kirchner et al. (2024) demonstrate legibility gains for LLM outputs at
scale.

**Plugs into.** A real PVD v2: critical-phase items routed to an actual
multi-round prover/verifier exchange between oracles from *different*
families (interacting with proposal 3's independence requirements), with
the verifier's verdict feeding the evidence router.

**What it buys.** A principled mechanism for exactly the stratum where
REMORA's signals fail (critical phase, trust inversion, CLAIM-005): debate
is designed for cases where direct evaluation is unreliable but
adversarial checking is feasible.

**Literature.**
- Irving, G., Christiano, P. & Amodei, D. (2018). AI safety via debate. arXiv:1805.00899.
- Anil, C., Zhang, G., Wu, Y. & Grosse, R. (2021). Learning to give checkable answers with prover-verifier games. arXiv:2108.12099.
- Brown-Cohen, J., Irving, G. & Piliouras, G. (2023). Scalable AI safety via doubly-efficient debate. arXiv:2311.14125.
- Kirchner, J. H., Chen, Y., Edwards, H., Leike, J., McAleese, N. & Burda, Y. (2024). Prover-verifier games improve legibility of LLM outputs. arXiv:2407.13692.

**Cost.** High — live multi-round LLM interaction, new evaluation design,
real API spend; this is a research project, not a feature.

**Risk.** High. Debate's effectiveness is itself an open research question;
importing it prematurely would repeat the semantic-entropy pattern
(mechanism implemented, never load-bearing in reported results — M5).

**Acceptance artifact.** A pre-registered experiment plan (SAP-style) BEFORE
implementation; then a benchmark artifact on the N=32→larger critical-phase
stratum comparing PVD v2 against the existing routing.

---

## Cross-cutting recommendations

1. **Sequencing.** Implement #1 (confidence sequences) first — it fixes an
   active release gate and is a few hours of stdlib work. Batch #4/#5/#6/#7
   as a single "theoretical grounding" documentation wave (all trivial, all
   pure legitimacy gains). #2 (barrier certificate) is the highest-prestige
   item and should target the next paper revision. #3 requires only the
   per-item oracle records already on disk. #8/#9/#10 wait until their
   component is load-bearing.
2. **Claim hygiene.** Each adoption gets a claim-register entry at
   `theoretical` evidence level on merge, promotable only per
   `evidence_levels.md` rules. The acceptance artifacts above are the
   promotion criteria.
3. **Anti-metaphor rule.** If a proposal ships without its acceptance
   artifact, it must not appear in README/paper prose. This document is the
   only place PROPOSED items may be described.
