# Benchmark Round 2026-07 — What We Ran, Why, and What the Numbers Mean

Written for a reader who has not followed the audit history. Machine-level
detail lives in [statistical_analysis_plan_v2.md](../assurance/statistical_analysis_plan_v2.md)
(the pre-registered plan) and
[rebenchmark_protocol_v1.md](../assurance/rebenchmark_protocol_v1.md).

## Why a new round at all

Three reasons, all found by external research audits in July 2026:

1. **The old numbers described old code.** Every benchmark artifact was
   frozen on 2026-07-20, but the decision engine and the thermodynamics
   layer (the χ susceptibility computation feeding trust scores) changed
   after that.
2. **The old consensus ensemble was three models from the same family**
   (all Meta LLaMA, all on Groq). Same-family models make correlated
   mistakes, so "3-oracle consensus" behaved closer to 2 independent
   voters — and one of the three models has since been removed from the
   provider's catalog entirely, making the old runs unreproducible.
3. **Protocol weaknesses**: labels loaded in the same process as decisions,
   a hardcoded `leakage_free: True`, metric names with inconsistent
   denominators, a "binomial test" that was actually a normal
   approximation, and a holdout whose operating point was picked with
   knowledge of the full dataset.

All of those were fixed first; this round is the first run under the
corrected protocol.

## The new consensus ensemble

Rule (enforced by code, `remora/oracles/families.py`): **no two oracles may
share a model weight family.**

| Oracle | Family | Why it qualifies |
|--------|--------|------------------|
| `llama-3.3-70b-versatile` | Meta LLaMA | strong generalist |
| `openai/gpt-oss-120b` | OpenAI (open-weight) | different training lineage |
| `qwen/qwen3.6-27b` | Alibaba Qwen | different lineage; runs with reasoning disabled so it answers in clean JSON |

All three hosted on Groq; hosting is shared, weight ancestry is not — the
correlation risk consensus must defend against lives in the weights.
Selection used only catalog availability and a 3-prompt JSON smoke test
(never benchmark data). The trio was committed to the pre-registered plan
BEFORE the first benchmark call.

## What was run

**Deterministic set** (no live models — exercises the policy layer):
toolcall v2 benchmark + significance + calibration + failure analysis +
ablation, governance-intelligence benchmark, and the blinded toolcall v3
evaluation executed as **two separate processes** (the deciding process
never loads the labels file). Task surface regenerated without the
author-annotation fields (`severity`/`tags`).

**Live set** (the full consensus → uncertainty-routing pipeline): each of
the 544 knowledge items is asked to all three oracles; their verdicts feed
entropy H / dissensus D, temperature, order parameter, susceptibility χ and
phase; the phase controller routes accordingly. The primary artifact is
**uncalibrated** — the previous "calibrated" variant rescaled temperatures
using a profile fitted on labelled outcomes, which is in-sample tuning.
Downstream: end-to-end policy evaluation and the selective holdout
(τ* locked on the training split; group-aware 80/20 split; exact binomial).

Every artifact carries a `.provenance.json` sidecar (git commit, worktree
state, Python version, dependency-lock hash, input hashes, seeds, command).

## How to read the results honestly

- **Two accuracies exist, on purpose.** The legacy `accuracy` counts an
  abstention as a wrong answer; the `selective` block reports
  `accuracy_answered` + `coverage` with abstention as its own category.
  REMORA is a selective system — judging it only by all-items accuracy
  is judging a fire alarm by how often it stays quiet.
- **The holdout result is directional, not proof.** With 544 items and
  18 % acceptance coverage, only ≈25 holdout items get accepted — too few
  for generalization language, whatever the p-value says. This is recorded
  in the plan's deviation table before results were seen.
- **What still cannot be claimed:** AgentHarm N=208 and the N=167
  regression corpus are imported historical artifacts (generated in the
  main implementation repo); they are integrity-checked here but not
  reproduced. The toolcall 0 % FAR is simulator-scoped and carried by the
  hard-block policy layer, not by consensus — unchanged this round.

## Results

*(filled from the round's artifacts when the live segment completes;
numbers in this section must match the artifacts byte-for-byte and every
rate names its denominator)*

## Where the artifacts live

`results/ablation_v2_n500_results.json` (consensus arms),
`results/thermodynamic_eval_n500_uncalibrated_results.json` (H/D → phase →
routing), `results/end_to_end_n500_v3.json`,
`results/selective_n500_holdout_results.json` (confirmatory H1′),
`results/toolcall_*` (policy layer), each with its provenance sidecar.
Old artifacts stay frozen and checksummed — superseded, never overwritten
retroactively.
