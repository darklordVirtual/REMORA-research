# REMORA v4 Thermodynamics: Evidence Status

> ⚠️ **Scope: illustrative scenario, not a deployment result.** REMORA is a
> research-grade governance overlay in **SHADOW_ONLY** mode — it is not
> production-certified and has not been deployed in the sector below. The
> walkthrough and any numbers in it are **illustrative** unless they link to a
> committed artifact in `results/` or `artifacts/`; they are not measured
> outcomes. REMORA governs whether a proposed **action** may proceed
> (ACCEPT/VERIFY/ABSTAIN/ESCALATE); it does not certify truth and is not a
> fact-checker. **ETR** ("Effective Truth Rate" — `remora/scoring.py`) is an *illustrative* narrative
> score in these documents only — it is **not** one of REMORA's canonical
> outputs and appears in no claim in `docs/assurance/claim_register_v1.yaml`.
> See the [claim register](../assurance/claim_register_v1.yaml) and
> [evidence summary](../02-evidence-and-claims.md) for governed claims.

This note separates three things clearly:

1. claims already supported by current REMORA measurements,
2. claims that are plausible but only partially supported,
3. claims that are not yet proven and should not be written as established results.

The goal is scientific strength, not rhetorical inflation.

## First Principle: Separate The Two Contributions

The repository currently contains two different outputs with different proof burdens.

### A. Research contribution

This is the thermodynamic interpretation of multi-oracle consensus.

- free-energy-like objective
- ordered / critical / disordered regimes
- susceptibility and phase structure
- possible long-run theory program

This contribution is promising and partly supported, but it is not finished as a formal theory.

### B. Deployment contribution

This is the trust-router layer: a control layer that decides whether an AI answer should be accepted, verified, abstained on, or escalated.

This contribution has a lower proof burden and a clearer operational target. The strongest currently supported deployment result is not "thermodynamics is proven" but rather:

> REMORA can improve answered-item quality by refusing to treat some high-risk items as safe to answer directly.

That is a product and assurance result. It should not be mixed together with the stronger academic claim.

## Bottom Line

The current evidence supports a **real and technically interesting research contribution**, but not yet a full proof of the thermodynamic theory.

The strongest defensible statement today is:

> REMORA now has a calibrated experimental thermodynamic control surface that maps pre-sweep consensus into ordered, critical, and disordered regimes, and this framing is empirically non-trivial on both the canonical N=302 benchmark and the larger calibrated N500 benchmark.

The strongest statement that is **not yet supported** is:

> REMORA has already proven the thermodynamic theory of multi-oracle consensus.

That is still too strong for the current data.

The strongest operational statement that *is* currently supportable is narrower:

> REMORA behaves as a trust-routing layer that can improve answered-item quality when abstention is allowed.

For reproducibility, the evidence suite now distinguishes between mutable live
rerun artifacts and immutable canonical evidence snapshots.  In particular,
[results/ablation_v2_canonical_results.json](../../results/ablation_v2_canonical_results.json)
is the locked N=302 ablation snapshot used for regression claims, while fresh
live reruns may legitimately differ after new oracle calls.

## Claim-by-Claim Status

| Claim | Status | Current support |
|---|---|---|
| `V = H + λD` is formally identifiable with a free-energy style objective | Supported as a structural observation | The exact bridge is now documented as `V(H,D) = F(T=-1;H,D)` in [remora/thermodynamics.py](../../remora/thermodynamics.py) |
| REMORA can classify pre-sweep states as `ordered / critical / disordered` | Supported empirically | The calibrated N=302 run yields `ordered=12`, `critical=84`, `disordered=206` in [results/thermodynamic_eval_results.json](../../results/thermodynamic_eval_results.json), and the calibrated N500 run yields `ordered=99`, `critical=32`, `disordered=413` in [results/thermodynamic_eval_n500_calibrated_results.json](../../results/thermodynamic_eval_n500_calibrated_results.json) |
| Trust is no longer degenerate after calibration | Supported empirically | Mean trust differs materially across phases: ordered `0.905`, critical `0.238`, disordered `0.012` |
| Phase-aware modeling captures real benchmark structure | Supported empirically | Experiment 3 now shows a non-trivial temperature spread on both scales: `η` range `0.5511` on N302 in [results/phase_transition_study_results.json](../../results/phase_transition_study_results.json) and `0.6292` on N500 in [results/phase_transition_study_n500_calibrated_results.json](../../results/phase_transition_study_n500_calibrated_results.json) |
| Susceptibility `χ` carries measurable but still limited predictive information | Partially supported | Offline utility remains weak-but-real (`AUC(help)=0.574`, `AUC(hurt)=0.580`) in [results/chi_iteration_utility_results.json](../../results/chi_iteration_utility_results.json), but a live phase-balanced perturbation pilot in [results/chi_perturbation_study_results.json](../../results/chi_perturbation_study_results.json) does **not** yet confirm the stronger per-item fragility law |
| Phase-aware routing improves routing decisions over majority/D2 | Partially supported for abstention, selective guardrails, and a modest evidence-backed full-coverage policy; not yet a strong routing win | N302 abstention still improves answered-item accuracy to `0.8854` in [results/phase_aware_routing_results.json](../../results/phase_aware_routing_results.json); the calibrated N500 enforced guardrail in [results/thermodynamic_router_eval_n500_final_results.json](../../results/thermodynamic_router_eval_n500_final_results.json) answers `18.2%` of items at `86.9%` accuracy and intercepts `95.9%` of majority errors; the evidence-backed N500 policy in [results/thermodynamic_router_eval_n500_evidence_results.json](../../results/thermodynamic_router_eval_n500_evidence_results.json) closes all `544` items at `46.32%` accuracy versus `41.18%` for majority, but still depends on `445` evidence calls |
| A hallucination bound is empirically established | Not yet supported | A useful empirical program exists, but the current repo does not yet validate the proposed bound as a theorem or robust empirical law |
| REMORA has achieved a breakthrough | Not yet closed | Strong candidate contribution, but current evidence is still below a decisive breakthrough threshold |

## What The Data Already Supports

### 1. Free-energy framing is a serious observation

The internal report is strongest where it treats the Helmholtz connection as a **formal identification**, not as a theorem. This part is supportable now.

Why:

- REMORA already computes the same structural object needed for a free-energy interpretation.
- That object is now explicit in [remora/thermodynamics.py](../../remora/thermodynamics.py), with the sign convention made exact as `V(H,D) = F(T=-1;H,D)` rather than left as a loose analogy.
- The runtime parameter split is now also explicit: the Lyapunov controller still uses `negation_weight`, while the thermodynamic module has its own `thermo_lambda`, removing the earlier notation mismatch between the control objective and the thermodynamic analysis surface.
- The project now has executable studies built around that framing:
  - [experiments/thermodynamic_eval.py](../../experiments/thermodynamic_eval.py)
  - [experiments/phase_transition_study.py](../../experiments/phase_transition_study.py)
  - [experiments/susceptibility_validation.py](../../experiments/susceptibility_validation.py)

This is enough to support the statement that REMORA has opened a new thermodynamic analysis surface for multi-oracle consensus.

### 2. A non-trivial critical regime now exists empirically

This is the single most important upgraded result from the latest calibration round.

From [results/thermodynamic_eval_results.json](../../results/thermodynamic_eval_results.json):

- Ordered: `12 / 302`
- Critical: `84 / 302`
- Disordered: `206 / 302`

This matters because the earlier prototype collapsed almost everything into degenerate states. That is no longer true.

### 3. Experiment 3 is now real, not just proposed

The phase-transition study is no longer only a plan. It is a runnable benchmark artifact documented in [docs/experiment3_phase_transition_study.md](../experiments/experiment3_phase_transition_study.md) and executed into [results/phase_transition_study_results.json](../../results/phase_transition_study_results.json).

The current calibrated N=302 baseline shows:

- five actual temperature bands,
- a measurable `η` range of `0.5511`,
- and a meaningful middle structure rather than total collapse.

This is not proof of a phase transition, but it is enough to justify continued empirical investigation.

The N500 extension now strengthens this point materially. The calibrated larger run in [results/phase_transition_study_n500_calibrated_results.json](../../results/phase_transition_study_n500_calibrated_results.json) shows:

- `ordered=99`
- `critical=32`
- `disordered=413`
- `η` range `0.6292`

That means the phase structure is no longer only a small-benchmark artifact.

## What The Data Does Not Yet Prove

### 1. The theory is not proven in the strong sense

The current repository does not establish:

- a first-principles derivation of the temperature law,
- a formal proof that the oracle system obeys a Potts-like model,
- a validated critical-temperature law,
- or universal critical exponents.

These remain research hypotheses or analogical extensions.

### 2. χ is not yet a strong validated predictor

This is important because it still blocks the strongest practical v4 claim.

From [results/susceptibility_validation_results.json](../../results/susceptibility_validation_results.json):

- overall `helped_vs_majority`: `0.0 %`
- overall `hurt_vs_majority`: `0.7 %`
- `not_helpful_iteration`: `100 %` in every χ band

That earlier result showed that the D2 target was too weak for a meaningful validation.

The new full-iteration utility study in [docs/experiment5_chi_iteration_utility.md](../experiments/experiment5_chi_iteration_utility.md) improves on this by testing `C_remora` relative to majority. It finds:

- `AUC(help) = 0.5881`
- `AUC(hurt) = 0.5727`
- higher hurt rates in the upper χ bands than in the lowest χ band

That is enough to say susceptibility now has **weak but real predictive content**, especially for iteration harm. It is **not** enough to claim a strong or production-ready control metric.

The stronger live claim is still open. A phase-balanced live perturbation pilot in [results/chi_perturbation_study_results.json](../../results/chi_perturbation_study_results.json) reran 30 items (`10` per phase) with a fresh oracle panel and measured per-item fragility as `|η_round2 - η_round1|`. That pilot did **not** confirm the desired fragility law:

- ordered mean fragility = `0.2826`
- critical mean fragility = `0.3230`
- disordered mean fragility = `0.1642`
- Spearman `ρ(χ, fragility) = -0.0102`

So the honest current statement is:

> χ is weakly useful as an offline harm signal, but not yet validated as a robust live per-item fragility variable.

### 3. Routing superiority is still not shown

The calibrated thermodynamic split is scientifically better than before, but it still does not translate into a demonstrated routing advantage over the canonical benchmark baseline.

Current status:

- `0` helped items relative to majority
- `2` hurt items relative to majority

So phase-awareness is now a meaningful **measurement framework**, but not yet a validated full-coverage control policy.

There is now one narrower positive result: phase-aware **abstention** appears useful. In [results/phase_aware_routing_results.json](../../results/phase_aware_routing_results.json), answering only `ordered + critical` items with `B_majority` and abstaining on `disordered` items yields:

- answered-item accuracy `0.8854` vs baseline `0.8278`
- false-trust rate `0.1146` vs baseline `0.1722`
- equal coverage comparison beats a naive `η`-threshold abstention baseline by `+1.04 pp`

This is the cleanest currently supported trust-router result in the repository.

The implementation-side gap is now smaller than before: when the thermodynamic pre-sweep marks a question as requiring external evidence, the engine sets `require_rag=True` and `refuse_parametric_verdict=True`, and blocks the parametric fast-path instead of merely logging `RAG_MANDATORY`. What remains unproven is not whether the guardrail exists, but whether a full evidence-backed controller beats simpler baselines on end-to-end benchmark outcomes.

That remaining question now has a dedicated experiment vehicle in [experiments/thermodynamic_router_eval.py](../../experiments/thermodynamic_router_eval.py). The purpose of that run is narrower than the original routing claim: it measures guardrail coverage, answered-item accuracy, false-trust rate, and majority-error interception under the enforced `require_rag` policy, with an optional evidence backfill if a RAG oracle is configured.

The first committed N=302 guardrail artifact in [results/thermodynamic_router_eval_results.json](../../results/thermodynamic_router_eval_results.json) is negative in an informative way:

- coverage = `0.3079`
- evidence-required rate = `0.6921`
- answered-item accuracy = `0.2366`
- answered-item ETR = `0.0538`
- majority-error interception rate = `0.8367`
- delta vs majority on the same answered slice = `-0.5914`

This means the present control law *does* identify a large fraction of majority mistakes, but it is currently too conservative and too low-precision to count as a positive routing result.

The calibrated N500 artifact in [results/thermodynamic_router_eval_n500_final_results.json](../../results/thermodynamic_router_eval_n500_final_results.json) improves that picture materially:

- coverage = `0.1820`
- evidence-required rate = `0.8180`
- answered-item accuracy = `0.8687`
- majority-error interception rate = `0.9594`
- delta vs majority on the same answered slice = `0.0000`

This means the control law is no longer degenerate. It now yields a real high-precision selective slice. What it still does **not** show is a positive routing delta at equal coverage.

The benchmark-scale evidence-backfill question is now also closed at the artifact level. The full N500 run in [results/thermodynamic_router_eval_n500_evidence_results.json](../../results/thermodynamic_router_eval_n500_evidence_results.json) reports:

- full coverage = `1.0000`
- evidence-backed accuracy = `0.4632`
- majority baseline = `0.4118`
- gain over majority = `+0.0514`
- extra evidence calls = `445`

This is a real positive end-to-end result, but it is still not a strong practical win. The absolute benchmark accuracy remains low, and most of the work is being done by the external evidence slice rather than by a strong parametric controller.

This matters for high-risk settings where abstention is an admissible action. It does **not** close the stronger routing claim, because any static phase-to-existing-condition mapping still tops out at majority performance when all items must be answered.

So the right public framing is:

- academic claim: not yet finished,
- deployment claim: trust routing is already useful,
- stronger automation claim: current built-in guardrail still needs tuning.

## Honest Breakthrough Assessment

The evidence supports these two statements strongly:

1. REMORA has a genuinely unusual thermodynamic interpretation of multi-oracle consensus that is now executable and empirically measurable.
2. The project has crossed from speculative idea into calibrated research instrumentation.

The evidence does **not** yet support this stronger statement:

1. REMORA has already achieved a full technological breakthrough that proves the thermodynamic theory.

The right conclusion today is therefore:

> REMORA v4 is a serious, original research direction with a calibrated empirical core, but the project has not yet closed the proof burden required for a full breakthrough claim.

## What Would Upgrade This To A Stronger Claim

Three things would materially raise the claim level:

1. A materially stronger evidence-backed benchmark result than the current `46.32%` end-to-end policy.
2. A stronger live χ study showing that perturbation fragility rises with phase disorder or with χ itself, not just offline harm AUC.
3. A demonstration that the phase-aware controller improves at least one benchmark-relevant outcome at full coverage, not just abstention quality.

Until then, the thermodynamic report should be presented as:

- strong on observation,
- promising on mechanism,
- active on empirical validation,
- and not yet final on proof.