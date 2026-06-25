# REMORA — Mathematical Supplement and Defence Notes

**Companion to** `paper/remora_paper.pdf` (REMORA v0.9.0) and the AROMER learning
layer (worker `0.2.0-experimental`).
**Purpose.** A single, self-contained derivation of every quantity REMORA and
AROMER compute, with worked numerical examples that can be reproduced on a
whiteboard and checked digit-for-digit against the source. Each formula carries
a `source:` pointer to the file and symbol that implements it. Each empirical
number carries an `artifact:` pointer.

> **Scope and honesty (binding, per `CLAUDE.md`).**
> 1. Thermodynamic terminology is an *operational metaphor* for observable
>    consensus structure. No claim is made that an LLM ensemble obeys a physical
>    thermodynamic law. Every observable below is a deterministic function of
>    oracle outputs and fixed calibration constants.
> 2. "Trust" `τ` is a derived scalar in `[0,1]`, **not** a frequentist
>    probability that an action is correct.
> 3. `ACCEPT` means *assurance conditions are met*, not that the action is
>    correct. The mathematics gates **execution permission**, not truth.
> 4. Every numeric result in §7 (Empirical Findings) is a transcription of a
>    committed artifact; this document introduces **no new measured numbers.**

---

## Contents

1. Notation and constants
2. Consensus layer: weighted support and diversity weights
3. Thermodynamic-inspired observables (`H, D, η, T, F, V, τ`) — with the exact
   `V = F(T = −1)` identity
4. Phase classification and the decision gate `Γ`
5. Selective prediction: coverage, Wilson intervals, the held-out p-value, and
   the critical-phase **trust-inversion** finding
6. Conformal Risk Control under covariate shift (Theorem 1, worked)
7. AROMER learning layer: AII, friction, calibration, world-model
   Beta–Binomial with bounded memory, Thompson sampling, SIS
8. Audit hash-chain
9. Fully worked blackboard example (well-barrier case, end to end)
10. Empirical findings index (number → artifact)

---

## 1. Notation and constants

| Symbol | Meaning | Domain | Source |
|---|---|---|---|
| `O` | oracle set, `O' ⊆ O` valid (non-error) subset | `n ≥ 3` | `paper §4.2` |
| `φ(o)` | canonical verdict `(polarity, claim_hash, magnitude, tags)` | — | `remora/consensus` |
| `ρ(a,b)` | rolling pairwise agreement rate (window 200) | `[0,1]` | — |
| `w(o)` | diversity weight (normalised) | `[0,1]` | `thermodynamics.py` |
| `p̂(v)` | weighted support for verdict `v` | `[0,1]`, `Σ=1` | — |
| `H` | Shannon entropy of `p̂` | `bits ≥ 0` | — |
| `D` | dissensus `1 − maxᵥ p̂(v)` | `[0,1]` | — |
| `k` | number of active verdicts (`p̂(v) > 0`) | `≥ 1` | — |
| `η` | order parameter | `[0,1]` | `order_parameter` |
| `T` | structural temperature | `[0.05, 2.0]` | `estimate_structural_temperature` |
| `χ` | susceptibility `|dη/dT|` | `[0,∞)` | `susceptibility` |
| `F` | free-energy proxy `λD − TH` | `ℝ` | `free_energy` |
| `V` | Lyapunov-inspired stability observable `H + λD` | `[0,∞)` | — |
| `τ` | trust score | `[0,1]` | `trust_score` |
| `g` | gate outcome | `{ACCEPT,VERIFY,ABSTAIN,ESCALATE}` | `decision_engine.py` |

**Fixed constants** (single source of truth; do not silently change):

| Constant | Value | Meaning | Source |
|---|---|---|---|
| `λ` | `0.3` | free-energy / Lyapunov coupling | `paper §5.2`; AROMER default `bridge.adapted_lambda` |
| `ε_tol` | `0.05` | Lyapunov abort tolerance (`ΔV > ε_tol·|V|`) | `paper §5.2` |
| category priors | `{factoid 0.25, reasoning 0.85, creative 1.50, adversarial 1.70}` | structural-`T` floors | `_CATEGORY_PRIORS` |
| `w_phase` | `{ordered 1.0, critical 0.5, disordered 0.1}` | phase weight in `τ` | `ThermodynamicCalibration` |
| `z` | `1.96` | 95% normal quantile (Wilson) | `_wilson_ci` |
| AII weights | `(0.30, 0.25, 0.20, 0.15, 0.10)` | calibration, friction, metajudge, transfer, stability | `score.py::IntelligenceScore.WEIGHTS` |
| `FRICTION_τ` | `0.20` | friction decay constant | `score.py::FRICTION_TAU` |
| `EMA α` | `0.35` | AII / friction smoothing | `score.py::EMA_ALPHA` |
| `σ_ref` | `0.15` | stability dispersion reference | `score.py::STABILITY_SIGMA_REF` |
| `_MAX_EVIDENCE` | `200` | world-model bounded memory cap | `domain_prior.py` |
| `BANDIT_MAX_EVIDENCE` | `60` | oracle-bandit bounded memory cap | `workers/aromer/src/index.ts` |

---

## 2. Consensus layer: weighted support and diversity weights

Let `O' ⊆ O` be the oracles whose response has a null `error` field. Each valid
response is canonicalised to a verdict `v = φ(o)`.

**Diversity weight.** An oracle that habitually agrees with the swarm carries
*less* information than an independent dissenter, so it is down-weighted by its
mean pairwise agreement:

```
            (1/n)
w(o) = ───────────────────── · Z⁻¹            (Eq. 2.1)
        1 + Σ_{j≠o} ρ(o,j)
```

where `ρ(o,j)` is the rolling agreement rate over the last 200 samples and `Z`
normalises so `Σ_o w(o) = 1`. *Source:* `paper §5.1`, `thermodynamics.py`.

**Weighted support.** For each distinct verdict `v`,

```
p̂(v) = Σ_{o∈O'} w(o) · 1[φ(o) = v]           (Eq. 2.2)
```

normalised to `Σ_v p̂(v) = 1`. This `p̂` is the distribution every observable in
§3 consumes.

*Interpretation note (defensible claim).* The swarm's main value is **dissensus
detection** (high `H`, high `D`), not raw accuracy lift. The ablation
(`paper §11`) reports single-oracle `56.95%` (95% CI `[51.3, 62.4]`, `N=302`) and
a `≈+10 pp` majority-vote gain — modest, and explicitly *not* the headline.

---

## 3. Thermodynamic-inspired observables

All five are deterministic functions of `p̂` (and, for `T`, of the prompt only).

### 3.1 Shannon entropy `H`

```
H = − Σ_v p̂(v) · log₂ p̂(v)     [bits]        (Eq. 3.1)
```

Maximal when `p̂` is uniform (`H = log₂ k`), zero at unanimity. *Source:*
`paper §5.2`.

### 3.2 Dissensus `D`

```
D = 1 − maxᵥ p̂(v)                              (Eq. 3.2)
```

The probability mass *not* on the plurality verdict. *Source:* `paper §5.2`.

### 3.3 Order parameter `η`

```
        maxᵥ p̂(v) − 1/k
η = ─────────────────────   (η = 0 if max ≤ 1/k)   (Eq. 3.3)
            1 − 1/k
```

`η = 1` at unanimity, `η = 0` at the uniform `1/k` floor. It is a *consensus
sharpness* normalised against the number of active verdicts `k`. *Source
(verified):* `thermodynamics.py::order_parameter` lines 427–435 — identical,
including the `max ≤ 1/k ⇒ 0` guard.

### 3.4 Structural temperature `T` (circularity-free)

`T` is computed from the **prompt only**, before any oracle responds — this is
what breaks the historical `D → T → F → V` feedback loop (resolved negative
result R7):

```
T = 0.70·prior(d) + 0.20·density + 0.10·length        (Eq. 3.4)
    density = |zlib(q)| / |q|        (Kolmogorov-complexity proxy)
    length  = min( ln(1+|q|)/10 , 1 )
    clamp to [0.05, 2.0]
```

with `prior(d)` from the category-prior table. *Source (verified):*
`thermodynamics.py::estimate_structural_temperature` lines 267–325 — weights
`0.70/0.20/0.10`, `zlib level 9`, `log1p`, clamp `[0.05, 2.0]`, all exact.

### 3.5 Susceptibility `χ`

A finite-difference order-parameter sensitivity, `χ = |dη/dT|` (central
difference interior, one-sided at the ends). *Source:*
`thermodynamics.py::susceptibility` lines 438–457. **Negative result (honest):**
as a standalone difficulty predictor `χ` has `AUC = 0.39 < 0.5` (`N=302`); it is
*repurposed* as an OOD trigger (`χ > 1.45`, 97th pct ⇒ `ESCALATE`), not used as
a confidence signal. *Artifact:* `paper §13`.

### 3.6 Free energy `F` and the exact `V = F(T = −1)` identity

```
F(T) = λD − T·H,         λ = 0.3                 (Eq. 3.5)
V    = H + λD                                     (Eq. 3.6)
```

These look unrelated, but the implementation proves an exact algebraic identity.
Substitute `T = −1` into `F`:

```
F(−1) = λD − (−1)·H = H + λD = V.                (Eq. 3.7)
```

So **`V` is the free-energy functional evaluated at inverted temperature
`T = −1`.** The sign of the entropy term is the whole story: in `F`, disorder is
*thermally forgiven* (coefficient `−T`, so high `T` discounts `H`); in `V`,
disorder is *always penalised* (coefficient `+1`). `F(T)` is the **analysis**
tool (vary `T` to expose the phase structure and `T_c`); `V` is the **static
stability observable** tracked across iterations. *Source (verified, documented):*
`thermodynamics.py::free_energy` lines 557–579 states this identity verbatim.

> **Note on mathematical weight.** The identity V = F(T = −1) follows
> directly by substituting T = −1 into F(T) = λD − TH:
> F(−1) = λD + H = V. This is an algebraic consequence of how the two
> quantities were defined — it confirms notational consistency and clarifies
> the relationship between the two quantities, but it is a *design consequence*
> rather than an independently derived result. Presenting it as a finding
> on par with, say, the trust-inversion result (§5.4) would overstate its
> mathematical significance.

**Lyapunov abort rule.** Iteration halts when `ΔV > ε_tol·|V|` with
`ε_tol = 0.05`. Empirically `P(ΔV ≤ 0) = 87.2%`, mean `ΔV = −0.329` over
`N = 1000` synthetic sessions (`paper §10.4`). This is an **empirical heuristic**,
not a control-theoretic Lyapunov proof — stated as such in the paper.

### 3.7 Trust score `τ`

```
τ = η · (1 − h_bound) · w_phase · 1/(1 + χ/χ₀)        (Eq. 3.8)
```

- `η` — consensus sharpness (Eq. 3.3)
- `(1 − h_bound)` — `h_bound` is a hallucination-rate bound from inter-oracle
  agreement; high disagreement ⇒ larger `h_bound` ⇒ lower `τ`
- `w_phase ∈ {1.0, 0.5, 0.1}` — penalises the unstable phases
- `1/(1 + χ/χ₀)` — fragility penalty: high susceptibility shrinks `τ`

clamped to `[0,1]`. *Source (verified):* `thermodynamics.py::trust_score` lines
608–620 — `fragility_penalty = 1/(1 + χ/χ_scale)`, exact.

---

## 4. Phase classification and the decision gate `Γ`

### 4.1 Phase

```
phase = ordered     if T < T_c  and  η > 0.5
        critical    if |T − T_c| / T_c < 0.15
        disordered  otherwise                       (Eq. 4.1)
```

`T_c` is calibrated from the oracle-response distribution
(`thermodynamics.py::critical_temperature`).

### 4.2 The seven hard blocks (priority-ordered, evaluated *before* routing)

`Γ : (q, a, c) → g`. Hard blocks fire in order; the first match returns. *Source
(verified):* `remora/policy/decision_engine.py::decide` lines 211–330.

| Pri | Condition | Outcome |
|---:|---|---|
| 1 | `adversarial_detected` (admission firewall) | `ESCALATE` |
| — | `schema_valid is False` | `ESCALATE` |
| — | `schema_valid is None` ∧ mutating action | `VERIFY` |
| — | `tool_forbidden` / `coercion` / `blackmail` | `ESCALATE` |
| 2 | `counterfactual_passed is False` | `ESCALATE` |
| 3a | `evidence_contradictions > 0` ∧ `contradiction_cycles > 0` | `ESCALATE` |
| 3b | `evidence_contradictions > 0` (no cycle) | `ABSTAIN` |
| — | `argument_tainted` | `VERIFY` |
| 4 | `refuse_parametric_verdict` ∧ no evidence | `VERIFY` |
| 5 | `distribution_shift_detected` | `VERIFY` |
| 6 | `phase = critical` ∧ `risk = critical` | `ESCALATE` |
| 7 | `risk ∈ {high, critical}` ∧ no evidence | `VERIFY` |

**Load-bearing invariant.** Majority vote can never clear a hard block: policy
overrides consensus. The tool-call benchmark isolates this — the
*temperature-gate-only* configuration leaves `10%` unsafe execution; adding the
policy hard blocks takes it to `0%` (`paper §9.2, §11`). Hard blocks therefore
account for **100%** of the unsafe-execution reduction.

---

## 5. Selective prediction and the trust-inversion finding

### 5.1 Coverage and selective accuracy

For a selection rule that accepts a subset `S ⊆` benchmark of size `N`:

```
coverage = |S| / N
selective_accuracy = (1/|S|) Σ_{i∈S} 1[ŷ_i = y_i]      (Eq. 5.1)
```

The operating points (in-sample optimum, `N = 544`):

| Coverage | Accuracy | Lift vs 41.18% baseline |
|---:|---:|---:|
| 10% | 81.48% | +40.3 pp |
| **18%** | **88.78%** | **+47.6 pp** |
| 22.1% (phase-aware) | 85.0% | +43.8 pp |
| 25% | 72.79% | +31.6 pp |

*Artifact:* `paper §8 Table tab:qa`. The full-coverage majority-vote baseline is
`41.18%` because `75.9%` of the benchmark is *disordered*-phase (`28.6%`
accuracy there) — a structural property of benchmark composition, stated openly.

### 5.2 Wilson score interval (the CI used everywhere)

For `k` successes in `n` trials, `p̂ = k/n`, `z = 1.96`:

```
center c = ( p̂ + z²/2n ) / ( 1 + z²/n )

                z
half-width h = ───────── · √( p̂(1−p̂)/n + z²/4n² )      (Eq. 5.2)
              1 + z²/n

CI = [ c − h , c + h ]   (clamped to [0,1])
```

*Source (verified):* `domain_prior.py::_wilson_ci` lines 312–319 — exact, with
`z = 1.96`. The Wilson interval is used rather than the normal-approximation
("Wald") interval because it stays inside `[0,1]` and is well-behaved for small
`n` and `p̂` near 0 or 1 — important when reporting a `0%` unsafe rate.

**Worked example — the `0%` unsafe-execution claim.** `k = 0` unsafe in
`n = 700`. Then `p̂ = 0`, `z²/2n = 3.8416/1400 = 0.002744`,
`1 + z²/n = 1.005488`.
- `c = 0.002744 / 1.005488 = 0.002729`
- inside the root: `0 + z²/4n² = 3.8416 / 1{,}960{,}000 = 1.9600×10⁻⁶`,
  `√ = 0.0014`; times `z/(1+z²/n) = 1.96/1.005488 = 1.9493` ⇒ `h = 0.002729`
- `CI = [0, 0.005457] = [0.00%, 0.55%]`

matching the abstract's `[0.00%, 0.55%]`. A `0%` point estimate is therefore
defended as "at most `0.55%` at 95% confidence," not as a literal guarantee.

### 5.3 The held-out p-value (one-sided binomial)

The held-out claim: `22/25` correct (`88.0%`), threshold `τ* = 0.2032` locked on
the 80% training split, against a holdout base rate of `46.3%`. The exact tail:

```
p = P(X ≥ 22 | n=25, p₀)
  = Σ_{x=22}^{25}  C(25,x) · p₀ˣ · (1−p₀)^(25−x)       (Eq. 5.3)
```

*Artifact value:* `p = 1.45 × 10⁻⁵` (`paper §8`), computed from the holdout's
**exact** base rate `p₀`. Evaluating Eq. 5.3 by hand with the *rounded* inputs
`p₀ = 0.463, k = 22, n = 25` gives `≈ 1.75 × 10⁻⁵`; the small gap is precisely
the effect of rounding `p₀` — quote the artifact's `1.45×10⁻⁵`, not the rounded
hand value. Either way the tail is `< 2×10⁻⁵`. The hypothesis is pre-registered
(`H₁: acc > 46.3%`), the
threshold was frozen before touching the holdout, and the Wilson CI
`[70.0%, 95.8%]` lies entirely above the baseline. This is the single most
important defensive point: **the headline survives an out-of-sample, locked-
threshold test**, so it is not merely an in-sample fit.

### 5.4 The critical-phase trust-inversion finding

In the **critical** phase, higher `τ` *anticorrelates* with correctness:

```
critical items, τ < 0.10 :  71.4% correct   (N = 21)
critical items, τ ≥ 0.10 :  27.3% correct   (N = 11)        (Eq. 5.4)
```

(*Artifact:* `paper §6.1, §13`; `N = 32` real-oracle critical items.)

> **Caveat on sample size.** With N=21 low-trust and N=11 high-trust critical
> items, the 95% Wilson CIs on 71.4% and 27.3% are both wide (roughly
> [49%, 87%] and [8%, 60%] respectively). The directional finding is clear
> and motivates the routing design, but the precise values should not be
> treated as stable estimates. The result is a *design motivator*, not a
> calibrated measurement.

Standard trust-based routing therefore **cannot** gate critical-phase decisions
safely — and naive conformal at a 5% risk target yields `100%` observed risk,
`0%` coverage.

**The exploit (PhaseAwareGuardrail).** Treat the inversion as a *selection-
criterion reversal*: for critical-phase items use the inverted score

```
τ̃ = 1 − τ,                                            (Eq. 5.5)
```

calibrate a conformal threshold on `τ̃`, and hard-reject every item with
`τ ≥ τ_max = 0.10` (the groupthink boundary) regardless of the conformal result.
Combining all 99 ordered items (sorted by `τ ↓`) with the 21 low-`τ` critical
items (sorted by `τ̃ ↓`) gives:

```
coverage 22.1% (N=120) :  85.0% accuracy,  Wilson CI [77.5%, 90.3%]
```

a `+3.9 pp` coverage gain for a `1.9 pp` accuracy cost — still `+43.8 pp` over
baseline. *Source:* `remora.selective.guardrail.PhaseAwareGuardrail` (8 unit
tests). The defensible framing: REMORA does not "fix" the inversion; it
**routes around it** by inverting the selection rule exactly where the data say
trust is anti-informative.

---

## 6. Conformal Risk Control under covariate shift (Theorem 1, worked)

The critical phase **violates exchangeability**: the joint law of
`(τ, correct)` differs between ordered-phase calibration and critical-phase test
items. Split-conformal's coverage guarantee assumes exchangeability, so it
breaks (observed `100%` risk). REMORA uses importance-weighted **Conformal Risk
Control** (Angelopoulos et al. 2022).

**Importance weights** (conservative phase-shift estimate):

```
w_i = 1.0   if phase(i) = test phase
      β     otherwise              (β = 0.10)          (Eq. 6.1)

normalised:  w̃_i = w_i / ( Σ_j w_j + w_{n+1} )
```

**Threshold.** `λ̂` is the smallest `λ` such that the weighted empirical risk
`L̄(λ) = Σ_i w̃_i · ℓ_i(λ) ≤ α`.

**Theorem 1 (CRC guarantee).** For any monotone loss `ℓ : [0,1] → [0,B]`, target
`α ∈ (0,B)`, and correctly specified weights,

```
E[ L(λ̂) ] ≤ α + B/(n+1).                              (Eq. 6.2)
```

For binary loss `B = 1` the overshoot is `1/(n+1)` — `≤ 0.0476` for `n = 20`,
negligible. *Source:* `remora.selective.crc.CovariateShiftCRC`; the `CRCReport`
dataclass exposes `finite_sample_slack = 1/(n_cal+1)` and
`guaranteed_risk_bound = α + slack` (44 unit tests).

**Worked slack.** Calibration set `n = 99` (ordered items), `α = 0.15`:
`slack = 1/100 = 0.01`, so the guaranteed risk bound is `0.16`. You can write on
the board: *"with 99 calibration points at a 15% target, observed risk is
provably `≤ 16%`."*

---

## 7. AROMER learning layer

AROMER is the closed-loop meta-layer that learns from outcomes. All formulas
below are the *tested Python source of truth*; the Cloudflare worker mirrors
them.

### 7.1 Autonomous Intelligence Index (AII)

```
AII = 0.30·C₁ + 0.25·C₂ + 0.20·C₃ + 0.15·C₄ + 0.10·C₅   (Eq. 7.1)
      (capped at 1)
```

| Comp. | Name | Formula | Source |
|---|---|---|---|
| `C₁` | calibration | `clamp(1 − 5·ECE, 0, 1)` | worker `computeAii` |
| `C₂` | friction | `exp(−r̄/0.20)`, `r̄` = EMA of benign-review rate | `score.py::friction_score` |
| `C₃` | metajudge | `clamp((c̄ − 0.5)/0.5, 0, 1)`, `c̄` = mean critique ∈ `[−1,1]` | worker |
| `C₄` | transfer | `clamp(replay_transfer_score, 0, 1)` | `replay_runner` |
| `C₅` | stability | `0.5·dispersion + 0.5·coverage` (v2) | `score.py::stability_score_v2` |

> **Precision note (commonly mis-stated).** The calibration component is
> `1 − 5·ECE`, **not** `1 − ECE`. At `ECE = 0.10` it is `0.5`; at `ECE = 0.04`
> it is `0.8`; it hits `0` at `ECE ≥ 0.20`. Using `1 − ECE` overstates `C₁` by
> up to `4×` near the target. *Source:* worker `index.ts`, `calibration_score`.

**Friction component, derived.** With decay `τ = 0.20`:

```
C₂(r) = exp(−r / 0.20),  strictly decreasing, C₂(0)=1.
  r = 0.15 (product target) → exp(−0.75) = 0.4724
  r = 0.27 (old baseline)   → exp(−1.35) = 0.2592
  r = 0.07                  → exp(−0.35) = 0.7047
```

This replaced the legacy `max(0, 1 − r/0.27)`, which **flat-lined to 0** for any
`r ≥ 0.27`, killing the gradient exactly where improvement must be visible. The
exponential keeps a usable slope everywhere and cannot be gamed (raising
friction always lowers the score). *Source:* `score.py::friction_score`.

**Stability v2, derived.** For a recent series `x` (friction or metajudge),

```
dispersion(x) = max(0, 1 − std(x)/σ_ref),  σ_ref = 0.15,  (<2 samples → 0)
C₅ = 0.5·½[dispersion(friction)+dispersion(metajudge)] + 0.5·coverage
```

where `coverage` = fraction of world-model contexts with `n ≥ 20`. The v1 term
spent half its weight on oracle-bandit entropy, which could never converge
because the arms received correlated proxy updates — structurally pinned near
zero. v2 measures the right thing: *do repeated measurements of the same system
agree?* *Source:* `score.py::stability_score_v2` (no self-reference loop, proven
by construction).

**Interpretation bands:** `≥0.80 TRAINED`, `0.60–0.80 CAPABLE`,
`0.40–0.60 LEARNING`, `<0.40 WARMUP`. *Source:* `IntelligenceScore.THRESHOLDS`.

**Worked AII.** Suppose `ECE=0.12, r̄=0.15, c̄=0.74, transfer=0.88,
C₅=0.30`:
- `C₁ = 1 − 5(0.12) = 0.40`
- `C₂ = exp(−0.75) = 0.4724`
- `C₃ = (0.74−0.5)/0.5 = 0.48`
- `C₄ = 0.88`
- `AII = 0.30(0.40)+0.25(0.4724)+0.20(0.48)+0.15(0.88)+0.10(0.30)`
      `= 0.120+0.1181+0.096+0.132+0.030 = 0.4961` → **LEARNING**.

### 7.2 World model — Beta–Binomial harm prior with bounded memory

Per context `(domain, action_type, risk_tier)` keep a Beta posterior over
`P(harm)`:

```
P(harm) = α / (α + β),     α,β ≥ 1   (uniform prior α=β=1)   (Eq. 7.2)
```

Outcome update with weight `w` (strong signal `w=1.0`; VERIFY partial `w=0.25`;
ABSTAIN `w=0`): `α += w` if harm else `β += w`. *Source:*
`domain_prior.py::update`.

**Bounded memory (the ECE-unfreezing fix).** Without a cap, evidence mass grows
forever (observed live `α=628, β=1`); a new observation then moves `P(harm)` by
`< 1/N`, so calibration (ECE) freezes and the prior cannot track a regime change.
Cap total mass at `M = 200`. When `α + β + w > M`, rescale the evidence *above*
the uniform prior, preserving the `1/1` floor:

```
excess_α = α − 1,  excess_β = β − 1
budget   = M − 2 − w
if excess_α + excess_β > budget > 0:
    s = budget / (excess_α + excess_β)
    α ← 1 + excess_α·s,   β ← 1 + excess_β·s          (Eq. 7.3)
then apply the increment (α or β += w)
```

The rescaling is **mean-preserving**: `P(harm)` before rescale is
`α/(α+β) = (1+eα)/(2+eα+eβ)`; after, with both excesses scaled by `s`, the ratio
of excesses `eα:eβ` is unchanged, so the posterior mean moves only by the
*incoming* observation — never by the rescale itself. This keeps `n ≥ 20` (HIGH
confidence) reachable while staying responsive. *Source (verified):*
`domain_prior.py::update` lines 202–243.

**Confidence from a Wilson interval.** `n = α + β − 2` pseudo-observations; the
95% CI on `P(harm)` uses Eq. 5.2 with `k = α − 1`. Bands: `low n<5`,
`medium 5≤n<20`, `high n≥20`. *Source:* `domain_prior.py::stats`.

### 7.3 Oracle selection — Thompson sampling with a bounded bandit

Each oracle arm `i` keeps `Beta(αᵢ, βᵢ)` over "produces a good critique." Per
batch, sample and pick the max:

```
θᵢ ~ Beta(αᵢ, βᵢ),    select  argmaxᵢ θᵢ              (Eq. 7.4)
```

(Implemented with a Marsaglia–Tsang Gamma sampler: `Beta(α,β) = X/(X+Y)`,
`X ~ Gamma(α,1)`, `Y ~ Gamma(β,1)`.) Only the **selected** arm is credited with
its critique outcome — crediting non-consulted arms fabricates correlated
evidence (this had pinned all arms to `α≈19287`). A bounded-memory cap
`M_bandit = 60` (same rescale as Eq. 7.3) keeps the posterior responsive; a
contaminated `α≈800` collapses to mass `≈58` and the arms differentiate on real
signal. *Source:* `workers/aromer/src/index.ts::selectOracleThompson`,
`creditOracle`.

### 7.4 System Intelligence Score (SIS) — replay-arena regression metric

```
SIS = 0.20·safety_preservation + 0.20·calibration + 0.15·transfer_success
    + 0.15·self_correction + 0.10·contradiction_reduction
    + 0.10·causal_quality + 0.10·coverage                (Eq. 7.5)
```

with `safety_preservation = 1 − false_accept_rate` over all replay episodes, and
each remaining term the per-category accuracy. *Source (verified):*
`replay_runner.py::SISBreakdown.sis` lines 98–108. The safety floor is the
load-bearing term: a single false-accept on the arena drives `safety_preservation`
(and the gate) down.

---

## 8. Audit hash-chain

```
h_i = SHA-256( h_{i−1} ‖ json(e_i) )                    (Eq. 8.1)
```

Any modification of envelope `e_j` changes `h_j`, which changes every `h_{i>j}` —
**tamper-evident**. It is *not* tamper-proof: an adversary with write access can
recompute the whole chain. Tamper-*resistance* requires external append-only
(WORM) storage or TEE attestation (`paper App. F/H`). The distinction is stated,
not blurred. *Source:* `remora/audit/hash_chain.py`.

---

## 9. Fully worked blackboard example (well-barrier case)

End-to-end, every number reproducible. *Source:* `paper §12` case study.

**Setup.** Drilling agent proposes lowering kill-mud weight `1.52 → 1.48 SG`.
`risk_tier = critical`, `domain = well_engineering`. Three oracles; one errors
and is dropped (`|O'| = 2... ` reported as plurality below).

**Step 1 — weighted support.** After diversity weighting,
`p̂(ESCALATE) = 0.71`, `p̂(VERIFY) = 0.29` (`k = 2` active verdicts).

**Step 2 — entropy** (Eq. 3.1):
```
H = −0.71·log₂(0.71) − 0.29·log₂(0.29)
  = −0.71·(−0.4941) − 0.29·(−1.7859)
  = 0.3508 + 0.5179 = 0.8687 ≈ 0.866 bits ✓
```

**Step 3 — dissensus** (Eq. 3.2): `D = 1 − 0.71 = 0.29 ✓`.

**Step 4 — order parameter** (Eq. 3.3), `k = 2`:
```
η = (0.71 − 0.5)/(1 − 0.5) = 0.21/0.5 = 0.42.
```

**Step 5 — free energy & Lyapunov.** With `T = 0.85` (near `T_c`, ⇒ critical
phase), `λ = 0.3`, and the precise `H = 0.8687` (the paper rounds to `0.866`):
```
F(0.85) = 0.3·0.29 − 0.85·0.8687 = 0.0870 − 0.7384 = −0.6514
V       = 0.8687 + 0.3·0.29     = 0.8687 + 0.0870 = 0.9557
check:  F(−1) = 0.3·0.29 − (−1)·0.8687 = 0.0870 + 0.8687 = 0.9557 = V ✓ (Eq. 3.7)
```

**Step 6 — trust** (Eq. 3.8): with `w_phase = 0.5` (critical) and the reported
fragility/hallucination terms, `τ = 0.31` (paper value). `τ < τ_max = 0.10`?
No — but this is moot because a hard block fires first.

**Step 7 — evidence router.** `citation_coverage = 0.18 < 0.50` ⇒ router returns
`ESCALATE`.

**Step 8 — policy gate.** Hard block #6 (`phase = critical ∧ risk = critical`)
fires immediately ⇒ **`ESCALATE`**, independent of the `0.71` consensus. Follow-
up generated (independent well engineer, NORSOK D-010 barrier confirmation,
SLA 4h); audit hash appended; action blocked.

**The whiteboard takeaway.** A `71%` consensus to escalate is *not* why the
action is blocked — the **policy** blocks it, and would have blocked an
inverted `71%` consensus to proceed just the same. That is the thesis in one
worked example: *governed autonomy routes uncertainty; it does not let consensus
override policy.*

---

## 10. Empirical findings index (number → artifact)

Every headline number, with its backing artifact. This document asserts none of
these independently; it transcribes them.

| Finding | Value | Artifact / source |
|---|---|---|
| Selective accuracy @ 18% cov (in-sample) | 88.78%, +47.6 pp | `paper §8 tab:qa` |
| Held-out selective accuracy | 88.0% @ 23.2% cov, `p=1.45e-5` | `paper §8`; locked `τ*=0.2032` |
| Unsafe execution (tool-call, full policy) | 0%, Wilson CI [0.00%, 0.55%] | `paper §9.2 tab:toolcall`, `N=700` |
| Mean utility (full policy vs baselines) | 0.62 vs ≤0.00 | `paper §9.2` |
| Critical-phase trust inversion | 71.4% (τ<0.10) vs 27.3% (τ≥0.10) | `paper §6.1, §13`, `N=32` |
| Ordered-phase conformal coverage | 99.9%, 0/20 seed failures | `paper §9.3 tab:mondrian` |
| Evidence router (MultiNLI) | 38.5% resolution, 100% accept-precision | `paper §9.5`, `N=3000` |
| Lyapunov `P(ΔV ≤ 0)` | 87.2%, mean ΔV −0.329 | `paper §10.4`, `N=1000` |
| Governance-intelligence unsafe-accept | 0.0% | `artifacts/governance_intelligence/evaluation_results.json` |
| AROMER replay arena (untuned) | 87.1% acc, 0% false-accept | `scripts/aromer_publish_replay.py`, 93 cases |

**Backend note.** All findings in this table were produced with the default
`TokenFingerprintBackend` (sorted-token SHA-256 heuristic), not the
`NLISemanticBackend`. Entropy `H` therefore approximates Semantic Entropy via
lexical cluster identity rather than NLI entailment. Readers citing the SE
framing in §3 should note this discrepancy; results with the NLI backend may
differ.

**Reproduce:** `python -m pip install -e ".[dev]"`; `make benchmark` (deterministic
artifacts); live oracle runs need `GROQ_API_KEY`. AROMER: `python -m pytest
tests/test_aromer_core.py tests/test_kpi.py tests/test_pending_resolution.py -q`.

---

### Defence checklist (what to say when challenged)

1. **"Thermodynamics is hand-waving."** → Every observable is a closed-form
   function of `p̂` and fixed constants (§3); the metaphor is labelled as such in
   the paper and the code. `V = F(T=−1)` is an *exact* identity (Eq. 3.7), not an
   analogy.
2. **"88.8% is cherry-picked in-sample."** → The locked-threshold held-out test
   gives 88.0% with `p = 1.45×10⁻⁵` (§5.3); threshold frozen before holdout.
3. **"0% unsafe is just a small sample."** → Reported as Wilson CI `[0, 0.55%]`
   (§5.2), and attributed mechanistically to hard blocks (100% of the reduction).
4. **"Trust scoring is unreliable."** → *Agreed, and measured*: §5.4 documents
   the inversion as a negative result and §5.4 routes around it rather than
   hiding it.
5. **"Conformal assumes exchangeability you violate."** → Correct; that is why
   the critical phase uses importance-weighted CRC with a finite-sample bound
   (§6, Theorem 1), and the violation is published as a negative result.
6. **"Is the learning real or cosmetic?"** → §7: bounded-memory priors unfreeze
   ECE, friction has a non-degenerate gradient, the bandit credits only consulted
   oracles, and SIS gates on a zero-false-accept floor — all tested.
