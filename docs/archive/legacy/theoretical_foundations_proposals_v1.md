> **NOTICE:** This document is **HISTORICAL** and has been explicitly archived. Referencing this document as truth in any runtime processes, algorithms, papers or claims is strictly prohibited in the active repository.

---


# Theoretical Foundations: Feature Proposals v1

**Status:** PROPOSED / NOT_IMPLEMENTED, every item in this document is
roadmap. Nothing here is a claim about the current system. Per
`docs/05-claim-hygiene.md`, no item may be described as a REMORA capability
until its acceptance artifact (defined per proposal below) exists on disk.

**Date:** 2026-07-02
**Context:** REMORA currently imports two formal frameworks: Lyapunov
stability tracking (`remora/policy/thermodynamic_braking.py`, paper §6) and
thermodynamic-style uncertainty observables (`remora/thermodynamics.py`, 
explicitly scoped as "an uncertainty-routing metaphor, not physics",
ARCHITECTURE.md). The 2026-06-25 external peer review was skeptical of
metaphor-dressing; the lesson encoded here is that **each theory import must
land as a falsifiable artifact (a test, a bound in a JSON, a gate), not as
paper vocabulary**. This document evaluates twelve candidate imports against
that bar.

**Evaluation dimensions per proposal:**
- *Plugs into*: the existing component/file the theory would attach to.
- *What it buys*, concrete utility: a guarantee, a corrected statistical
  procedure, or theoretical grounding for something currently heuristic.
- *Literature*, primary references.
- *Cost*: implementation effort and dependency footprint.
- *Risk*: ways the import could become metaphor-inflation or overclaim.
- *Acceptance artifact*: what must exist on disk before any claim is made.

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
| 11 | Value of information as the VERIFY-vs-ABSTAIN criterion | VERIFY/ABSTAIN branch of `decision_engine.py`; evidence router; AROMER oracle selection | Formalizes an implicit routing heuristic as one falsifiable criterion (VOI > 0) | Low (retrospective) / High (live gate) | **P2** |
| 12 | Optimal stopping (Bellman recursion) for the verification loop | VERIFY / sequential oracle loop; complements `confidence_sequence.py` (#1) | Cost-optimal stopping layer atop the fixed VERIFY rule | Medium/High | **P3** |

P1 = recommend implementing next; P2 = low-cost reframing of existing
mechanisms, batchable; P3 = worthwhile if the relevant component becomes
load-bearing; P4 = research direction, not a near-term feature.

---

## 1. Anytime-valid inference: e-processes and confidence sequences, **P1**

> **Status update 2026-07-02: IMPLEMENTED (library + artifact).**
> `remora/selective/confidence_sequence.py` (Beta-mixture confidence
> sequence, stdlib-only) + `tests/test_confidence_sequence.py` (17 tests,
> including a seeded demonstration that per-step Wilson monitoring violates
> its nominal level while the sequence holds) +
> `scripts/compute_far_confidence_sequence.py` →
> `results/far_confidence_sequence_v1.json` (0/168 cycles → 95%
> time-uniform upper bound 4.72%). Registered as CLAIM-011 (theoretical).
> The REM-020 criterion itself is unchanged pending owner sign-off, the
> bound is reported as supplementary in `release_gates.md`. The
> conformal-martingale drift detector remains unimplemented.

**Problem being solved.** REM-020 (release gate, closed 2026-07-17 under the 7-day criterion) monitors FAR
continuously over a 7-day window and will be closed the day the criterion
holds (`docs/assurance/release_gates.md`, `results/longitudinal_stability_v1.json`).
Fixed-sample intervals (Wilson, Clopper–Pearson, used throughout the repo)
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
companion concept, e-values/e-processes ("testing by betting", Shafer 2021;
Vovk & Wang 2021; survey in Ramdas et al. 2023), gives sequential tests
that remain valid under continuous monitoring and arbitrary stopping.

**Plugs into.**
- REM-020: replace/augment the windowed FAR check with a time-uniform
  confidence sequence on the FA rate; the gate closes when the upper
  confidence bound stays below threshold, valid regardless of when it is
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
wider intervals than Wilson at any fixed N (the price of time-uniformity), 
which must be communicated, not hidden.

**Acceptance artifact.** `remora/selective/confidence_sequence.py` +
dedicated tests + `results/longitudinal_stability_v2.json` carrying a
time-uniform upper bound on FAR alongside the existing fields, and
release_gates.md REM-020 criterion restated in terms of the sequence.

---

## 2. Barrier certificates / forward invariance of the safe set, **P1**

**Problem being solved.** The canonical safety claim rests on the
deterministic Stage-1 hard-block layer (`remora/policy/decision_engine.py`),
currently evidenced by invariant enumeration tests
(`tests/test_policy_invariants_prop.py`), mutation tests, and benchmark
FAR=0 results, with the standing caveat that Lyapunov results are "a
measurement of empirical behavior, not proof" (paper §10.4).

**The theory.** A barrier certificate (Prajna & Jadbabaie 2004; stochastic
version Prajna, Jadbabaie & Pappas 2007) is a function B(x) with B ≤ 0 on
the safe set, B > 0 on the unsafe set, and a non-increase condition along
system trajectories, establishing *forward invariance*: trajectories
starting safe stay safe. Control barrier functions (Ames et al. 2019) are
the control-synthesis form. For stochastic systems, nonnegative
supermartingales play the role of barriers (Kushner 1967; Chakarov &
Sankaranarayanan 2013), which connects directly to REMORA's existing
Lyapunov machinery.

**Plugs into.**
- The decision engine's rule ladder: define the unsafe set as
  {observations where ACCEPT would violate a hard invariant} and prove, by
  exhaustive case analysis over the finite discrete signal space, which is
  machine-checkable, that no ACCEPT path is reachable from it. The
  existing INV-1..INV-12 invariants and the explain()/decide() parity
  harness (`tests/test_explain_decide_parity.py`) are the natural
  substrate: the parity test already establishes that the ladder equals its
  trace; a barrier formulation would establish what the ladder guarantees.
- `thermodynamic_braking.py`: the Lyapunov-derivative trust penalty could be
  restated as a discrete-time barrier condition on the trust dynamics.

**What it buys.** Upgrades the safety floor from "tested exhaustively on a
grid" to "proven as forward invariance of a formally defined safe set" for
the deterministic layer. This is the difference between an empirical claim
and a theorem about the artifact, precisely the kind of statement external
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

## 3. Condorcet jury theorem + Dawid–Skene oracle reliability, **P2**

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
  heuristic approximation of the Condorcet correlation correction, this
  can be stated and tested.
- §11.3/§13.5 of the paper: both findings become *predictions* of the
  theory rather than surprises, same-family oracles violate independence,
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

## 4. Byzantine quorum bounds, **P2**

**Problem being solved.** The oracle quorum gate
(`decision_engine.py`, MIN_REQUIRED_ORACLE_VOTES=2 of n=3) is motivated in
a code comment by indistinguishability from "a degraded or compromised
oracle pool", Byzantine-fault language without the accompanying
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
flip outcomes at n=3, documenting the limitation, in the spirit of
`test_policy_engine_audit_v1.py`'s honest-gap tests).

**Risk.** None if stated as a limitation; the risk would be implying BFT
robustness the quorum does not have.

**Acceptance artifact.** Threat-model update + an honest-gap test
(`tests/` demonstrating single-Byzantine-oracle influence at n=3).

---

## 5. Neyman–Pearson framing of the FAR/FBR trade-off, **P2**

**Problem being solved.** The flagship external result (AgentHarm N=208:
FAR=0%, FBR=100%) is a corner solution, everything blocked. README now
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
everything", pre-empted by framing it as the feasible corner of a
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

## 6. Imprecise probability / Γ-maximin decision rule, **P2**

**Problem being solved.** `remora/credal.py` computes interval-valued harm
estimates and `decision_engine.py`'s minimax gate escalates on worst-case
loss over the interval. This *is* the Γ-maximin decision rule from
imprecise-probability theory, currently presented without lineage, so it
reads as ad hoc.

**The theory.** Credal sets and lower/upper previsions (Walley 1991) are
the standard formalization of interval-valued uncertainty; Γ-maximin
(choose the act with the best worst-case expectation over the credal set)
is one of the canonical decision rules (Troffaes 2007 surveys the
alternatives (Γ-maximax, E-admissibility, maximality) and their
trade-offs). Gilboa & Schmeidler (1989) give the axiomatic foundation
(maxmin expected utility with multiple priors). Augustin et al. (2014) is
the modern reference text.

**Plugs into.** `remora/credal.py` docstrings, paper §5, related work.
Optionally: evaluate E-admissibility as an alternative gate criterion
(Troffaes argues Γ-maximin can be overly conservative, which for a safety
gate is a *feature*, and that argument should be made explicitly).

**What it buys.** Free legitimacy, the mechanism already implements a
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

## 7. MDL / normalized compression distance for drift, **P3**

**Problem being solved.** `PromptDriftDetector`
(`remora/selective/drift_detector.py`) uses zlib compression density and
log-length z-tests: presented as a heuristic.

**The theory.** Minimum Description Length (Rissanen 1978; Grünwald 2007)
formalizes "regularity = compressibility"; the similarity metric and
normalized compression distance (Li et al. 2004; Cilibrasi & Vitányi 2005)
give a universal, parameter-free similarity measure computable with any
real compressor, zlib density against a calibration corpus is a one-sided
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
zlib approximately qualifies, state this.

**Acceptance artifact.** For the upgrade: revised detector + tests +
before/after comparison on the committed drift fixtures.

---

## 8. Adaptive conformal inference under distribution shift, **P3**

**Problem being solved.** Split-conformal guarantees (`remora/selective/`)
assume exchangeability; deployment traffic drifts. ARCHITECTURE.md briefly
referenced an (unimplemented) `adaptive_conformal.py`, the reference was
removed 2026-07-02; this proposal is the real version of that ambition.

**The theory.** Weighted conformal prediction restores coverage under known
covariate shift (Tibshirani et al. 2019, already the basis for
`crc.py`'s importance weights). Adaptive conformal inference (Gibbs &
Candès 2021) goes further: an online update of the miscoverage level that
achieves the target coverage *in time-average over arbitrary distribution
shift*, with follow-up work for general online settings (Gibbs & Candès
2024; Zaffran et al. 2022 for time series).

**Plugs into.** A new `remora/selective/adaptive_conformal.py` implementing
the ACI recursion over the decision stream, feeding the Mondrian/marginal
thresholds that `RemoraDecisionEngine` accepts as constructor parameters
(currently static, calibrated offline).

**What it buys.** A coverage statement that survives drift, the current
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
boundary, "REMORA is stateless; all fields caller-populated"
(`observation.py`). The update loop must live in the caller/AROMER layer,
not the engine.

**Risk.** Medium. ACI guarantees *time-average* coverage, not per-period, 
easy to overclaim; and online threshold adaptation is a new attack surface
(an adversary manipulating the stream drags the threshold), which the
threat model must cover before this ships.

**Acceptance artifact.** `remora/selective/adaptive_conformal.py` + tests +
a shadow-replay evaluation artifact showing realized coverage under an
induced shift, with the time-average scope stated in the caveat.

---

## 9. Ruin theory for session cumulative risk, **P3**

**Problem being solved.** The session sequential-risk gate
(`decision_engine.py`: session_cumulative_risk > 0.80 → VERIFY) guards
against "boiling frog" attacks with a hand-set threshold on a hand-summed
score.

**The theory.** Ruin theory (Lundberg 1903; Cramér 1930; modern treatment
Asmussen & Albrecher 2010) studies exactly this object: a reserve process
under a stream of stochastic claims, with the Cramér–Lundberg inequality
bounding the probability that cumulative claims ever exhaust the reserve, 
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

**Risk.** Medium, this is the proposal most susceptible to
metaphor-inflation: without a validated claims distribution, a
Cramér–Lundberg bound is decoration. Do not import the vocabulary before
the distributional homework exists.

**Acceptance artifact.** An artifact deriving the session threshold from a
fitted claims distribution + the resulting ruin bound + sensitivity
analysis; gate threshold in `decision_engine.py` updated to reference it.

---

## 10. Prover–verifier games and debate, **P4**

**Problem being solved.** `remora/selective/pvd.py` ("Prover-Verifier
Deliberation") currently *simulates* deliberation rounds, a deterministic
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

**Cost.** High, live multi-round LLM interaction, new evaluation design,
real API spend; this is a research project, not a feature.

**Risk.** High. Debate's effectiveness is itself an open research question;
importing it prematurely would repeat the semantic-entropy pattern
(mechanism implemented, never load-bearing in reported results, M5).

**Acceptance artifact.** A pre-registered experiment plan (SAP-style) BEFORE
implementation; then a benchmark artifact on the N=32→larger critical-phase
stratum comparing PVD v2 against the existing routing.

---

## 11. Value of information as the VERIFY-vs-ABSTAIN criterion, **P2**

**Problem being solved.** `remora/policy/decision_engine.py` routes between
VERIFY and ABSTAIN with a priority rule-cascade, not a trust threshold: VERIFY
fires on specific *resolvable* signals (`SCHEMA_UNVERIFIED_VERIFY`,
`THERMO_REQUIRE_EVIDENCE`, `CRITICAL_PHASE`, `SESSION_RISK_VERIFY`, and a dozen
siblings) and ABSTAIN is the safe fall-through (`DISORDERED_NO_EVIDENCE`,
`LOW_TRUST`, and finally `DEFAULT_SAFE_ABSTAIN`). Operationally this already
approximates "verify when a verification would change the decision, abstain
when nothing productive is available," but the criterion is *implicit*,
spread across ~20 hand-ordered rules, so it is neither stated as one
principle nor falsifiable as one.

**The theory.** Value of information (VOI). For each available verification
action a_v ∈ {fetch an authoritative source, validate the schema, run a
read-only preflight, consult an extra oracle family, request human sign-off},
define
  VOI(a_v) = R_now − E[R | after a_v] − C(a_v),
where R is expected decision risk (probability of a wrong ACCEPT weighted by
its cost) and C(a_v) the cost of running a_v. The decision-theoretic rule is
then VERIFY iff max_a VOI(a) > 0 (some affordable verification is expected to
reduce risk by more than it costs) and ABSTAIN iff max_a VOI(a) ≤ 0 (no
productive or affordable verification path exists, so fall through to the safe
default). This is the classical value-of-information calculation: expected
value of perfect/sample information in Raiffa & Schlaifer (1961), Howard's
(1966) information value theory, and Lindley's (1956) Bayesian measure of the
information provided by an experiment. Russell & Wefald (1991) apply exactly
this object to the metareasoning question "is it worth computing or checking
more before acting?", the meta-level analogue of REMORA's VERIFY/ABSTAIN
split, and Krause & Guestrin (2009) characterize the complexity and
near-optimal selection of information-gathering actions.

**Plugs into.**
- The VERIFY/ABSTAIN branch of `remora/policy/decision_engine.py`: the
  cascade's VERIFY returns and its terminal `DEFAULT_SAFE_ABSTAIN`
  fall-through are, respectively, the max_a VOI > 0 and max_a VOI ≤ 0 regions.
  The proposal *names* that criterion over the existing ladder; it does not
  replace the working safety floor.
- `remora/evidence/evidence_router.py` (`CriticalEvidenceRouter`): choosing
  among evidence-accept / abstain / escalate given evidence quality is a
  per-action VOI comparison (strong evidence → large risk reduction;
  conflicting or absent evidence → none), so its accept/contradiction/
  coverage thresholds are an implicit VOI boundary that can be stated as one.
- AROMER's verification-action selection, the OracleBandit surfaced through
  `remora/aromer/integration/bridge.py` (`select_oracles`) and called from
  `remora/aromer/orchestrator.py`: "which oracle family to consult next" is a
  choice of the argmax-VOI action, giving the bandit an explicit objective
  rather than an implicit ranking.

**What it buys.** Converts an implicit routing heuristic into a single
explicit, falsifiable criterion: VERIFY-vs-ABSTAIN is not "mid trust vs low
trust" but "an affordable verification exists that would change the decision
vs it does not." This gives a principled, per-action reason for each split
that is more precise than a trust threshold, and, crucially, a *measurable*
target (realized risk reduction) against which the cascade's implicit boundary
can be audited retrospectively.

**Literature.**
- Lindley, D. V. (1956). On a measure of the information provided by an experiment. *Annals of Mathematical Statistics* 27(4).
- Raiffa, H. & Schlaifer, R. (1961). *Applied Statistical Decision Theory.* Harvard University Graduate School of Business Administration.
- Howard, R. A. (1966). Information value theory. *IEEE Transactions on Systems Science and Cybernetics* 2(1).
- Russell, S. & Wefald, E. (1991). Principles of metareasoning. *Artificial Intelligence* 49(1-3).
- Krause, A. & Guestrin, C. (2009). Optimal value of information in graphical models. *Journal of Artificial Intelligence Research* 35.

**Cost.** Low for the retrospective measurement: the Stage-1 engine is
deterministic, so it can be replayed offline over the locked benchmark and the
resulting VERIFY/ABSTAIN decisions paired with ground truth, no engine change
and no new dependencies. Medium/high for a *live* VOI gate: that needs a
calibrated P(error | x) and a validated risk-reduction model E[R | after a_v],
neither of which the stateless engine currently holds.

**Risk.** Overclaim. VOI presupposes a calibrated risk model and P(error | x),
both caller-supplied; if the information-value estimator is not validated the
criterion is decoration, a relabelled trust threshold in decision-theoretic
costume. The retrospective artifact must therefore report *realized* VOI
against benchmark ground truth, not a self-consistent model estimate, and the
live gate stays PROPOSED until that estimator is validated (the same
discipline proposal 9 imposes on its ruin bound). The formalization also must
not be read as changing the tested cascade: it describes what the ladder
already does, it does not touch the safety floor.

**Acceptance artifact.** `results/voi_retrospective_v1.json`: a retrospective
VOI evaluation on the committed benchmark. Replay the deterministic engine
offline over `artifacts/benchmark_n500_locked.json` (544 items with
`ground_truth`, `source_confidence`, `is_adversarial`), and for each item the
cascade routed to VERIFY estimate, from the recorded outcome and the
committed per-action risk breakdown (`risk_by_action` in
`results/end_to_end_n500_v3.json`), whether the available verification
actually reduced realized decision risk (positive realized VOI: the
verification would have flipped a wrong ACCEPT, or confirmed a correct one at
less cost than the error it averts). Report the aggregate fraction of VERIFY
decisions with positive realized VOI, and the fraction of ABSTAIN
fall-throughs where no available action had positive VOI, stating the decision
rule explicitly as max_a VOI(a) > 0. Registered at `theoretical` evidence
level (CLAIM-style, supplementary in `release_gates.md`); the engine criterion
is unchanged pending owner sign-off.

---

## 12. Optimal stopping (Bellman recursion) for the verification loop, **P3**

**Problem being solved.** Every VERIFY the cascade emits is really the
decision to *pay for one more verification step*, an oracle round, a
re-check, a human touch, in the hope the added evidence resolves the
item. The engine already makes this call, but with a fixed rule:
`remora/policy/decision_engine.py` fires VERIFY on specific resolvable
signals (tainted argument, schema-unverified write, partial oracle
quorum, credal interval genuinely wide from oracle disagreement,
`session_cumulative_risk > 0.80`) and lets ABSTAIN be the safe
fall-through. What is *implicit* and untested is the cost-benefit
judgment underneath, whether the expected uncertainty reduction from
another step is worth its oracle cost and latency. This proposal
formalizes that judgment so it becomes falsifiable, without touching the
deterministic safety floor.

**The theory.** Optimal stopping (Wald 1947; Chow, Robbins & Siegmund
1971; Peskir & Shiryaev 2006) treats "act now vs. gather more
information" as a sequential decision problem solved by a Bellman
recursion (Bellman 1957; Bayesian sequential form in DeGroot 1970):

  V(s) = min{ L_accept(s), L_abstain(s), C_verify + E[V(s') | s] }

where s is the current evidence/uncertainty state of an item under
verification, L_accept and L_abstain are the terminal losses of
committing now (an unsafe accept, or the friction of routing to a
human), C_verify is the cost + latency of one more verification step,
and E[V(s') | s] is the expected continuation value after that step. The
optimal policy *stops* (accepts or abstains) when a terminal loss beats
the continuation value and *continues* (VERIFY) otherwise, an
optimal-stopping boundary in state space. Wald & Wolfowitz (1948) proved
the sequential-probability-ratio test optimal in exactly this
cost-vs-error sense; in the partially observed case a verification step
is precisely an information-gathering action in a POMDP (Kaelbling,
Littman & Cassandra 1998).

This is the *complement* of proposal 1. Confidence sequences
(`remora/selective/confidence_sequence.py`, IMPLEMENTED) give a
*statistically* valid stopping boundary, when it is safe to stop
monitoring under continuous peeking. Optimal stopping gives the
*economically* valid boundary, when it is cost-optimal to stop paying
for evidence. Value of information (proposal 11, its sibling in this
batch) is the one-step (myopic) special case: VOI scores the marginal
next step, whereas the Bellman recursion scores the whole remaining
sequence of steps.

**Plugs into.**
- The sequential oracle-consultation / VERIFY loop: the repeated
  `remora/policy/decision_engine.py` `decide()` invocations as evidence
  accrues across an episode. VERIFY is the "continue" action; ACCEPT and
  the `DEFAULT_SAFE_ABSTAIN` fall-through are the two "stop" actions.
  The Bellman policy would live in the caller/AROMER loop that decides
  whether to re-consult, never inside the deterministic ladder, which
  stays the safety floor.
- `remora/selective/confidence_sequence.py`: the statistical stopping
  boundary (#1) and the cost-optimal stopping boundary stack, stop when
  *either* it is statistically safe to stop or further evidence is not
  worth its price.
- AROMER's episode corpus (`artifacts/aromer_train_episodes.jsonl`,
  `artifacts/aromer_holdout_episodes.jsonl`, accessed via
  `remora/aromer/experience/store.py`): supplies the transition model
  E[V(s') | s], how the recorded uncertainty features (`trust_score`,
  `entropy_H`, `dissensus_D`) actually evolve after a verification step,
  estimated offline from recorded episodes.

**What it buys.** An explicit, tunable, auditable policy that trades
oracle cost, latency, residual risk, expected uncertainty reduction, and
remaining verification budget against one another, replacing a fixed
"these signals → VERIFY" rule with a decision that can be measured and
defended. It also yields a principled stopping rule for *how many*
verification rounds an item warrants before a forced ABSTAIN, which the
current cascade leaves entirely to the caller.

**Literature.**
- Bellman, R. (1957). *Dynamic Programming.* Princeton University Press.
- Wald, A. (1947). *Sequential Analysis.* Wiley.
- Wald, A. & Wolfowitz, J. (1948). Optimum character of the sequential probability ratio test. *Annals of Mathematical Statistics* 19(3).
- Chow, Y. S., Robbins, H. & Siegmund, D. (1971). *Great Expectations: The Theory of Optimal Stopping.* Houghton Mifflin.
- DeGroot, M. H. (1970). *Optimal Statistical Decisions.* McGraw-Hill.
- Peskir, G. & Shiryaev, A. N. (2006). *Optimal Stopping and Free-Boundary Problems.* Birkhäuser.
- Kaelbling, L. P., Littman, M. L. & Cassandra, A. R. (1998). Planning and acting in partially observable stochastic domains. *Artificial Intelligence* 101(1-2).

**Cost.** Medium/High. The Bellman recursion itself is standard, but it
needs a transition model E[V(s') | s] that does not exist yet. It is
estimable *offline* from the AROMER episode corpus (fit how the
uncertainty features move after a verification step); the offline policy
is then tractable by backward induction over a discretized state. The
online problem, updating the policy live as the transition model drifts,
is materially harder and stays out of scope until the sequential
verification loop is load-bearing. Hence P3.

**Risk.** High for overclaim. "Optimal" is optimal *only* with respect
to the assumed loss constants (C_verify, L_accept, L_abstain) and the
estimated transition model, both of which are caller/AROMER-supplied,
this must be stated wherever the word "optimal" appears. This is the
proposal most exposed to metaphor-inflation after ruin theory (#9): a
Bellman recursion over an unvalidated transition model is decoration. Do
not import the vocabulary before the transition model is fitted and its
predictive accuracy on held-out episodes is reported.

**Acceptance artifact.** `results/optimal_stopping_policy_v1.json`: an
offline optimal-stopping policy computed by backward induction on a
transition model fitted to `artifacts/aromer_train_episodes.jsonl`,
evaluated on the disjoint `artifacts/aromer_holdout_episodes.jsonl`,
plus a head-to-head against the current VERIFY heuristic on the
committed corpus, reporting whether the Bellman policy *Pareto-improves*
verification cost (oracle rounds spent) against safety (false-accept /
missed-escalation rate). No claim is made unless the artifact shows a
Pareto improvement, and the transition-model fit quality on holdout is
reported alongside it.

---

## Cross-cutting recommendations

1. **Sequencing.** Implement #1 (confidence sequences) first, it fixes an
   active release gate and is a few hours of stdlib work. Batch #4/#5/#6/#7
   as a single "theoretical grounding" documentation wave (all trivial, all
   pure legitimacy gains). #2 (barrier certificate) is the highest-prestige
   item and should target the next paper revision. #3 requires only the
   per-item oracle records already on disk. #8/#9/#10 wait until their
   component is load-bearing. #11 (value of information) and #12
   (optimal stopping) are a matched pair that formalizes the
   VERIFY/ABSTAIN split: #11 is the myopic one-step special case and can
   land retrospectively on the committed benchmark, whereas #12 is the
   sequential generalization that waits until the multi-round
   verification loop is load-bearing.
2. **Claim hygiene.** Each adoption gets a claim-register entry at
   `theoretical` evidence level on merge, promotable only per
   `evidence_levels.md` rules. The acceptance artifacts above are the
   promotion criteria.
3. **Anti-metaphor rule.** If a proposal ships without its acceptance
   artifact, it must not appear in README/paper prose. This document is the
   only place PROPOSED items may be described.
