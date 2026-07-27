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
| `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Meta LLaMA | strong generalist |
| `@cf/qwen/qwen3-30b-a3b-fp8` | Alibaba Qwen | different training lineage |
| `@cf/mistralai/mistral-small-3.1-24b-instruct` | Mistral | third independent lineage |

All three hosted on Cloudflare Workers AI; hosting is shared, weight
ancestry is not — the correlation risk consensus must defend against lives
in the weights. Selection used only catalog availability and a 3-prompt
JSON smoke test (never benchmark data). An earlier Groq-hosted trio was
declared first, but the Groq free-tier daily token quota (shared with the
deployed workers) was exhausted before any live benchmark call could be
made; the provider change is recorded as a dated SAP v2 amendment and
deviation row, and the Groq trio produced no round artifacts.
`@cf/openai/gpt-oss-120b` is the documented reserve model.

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
- **`selective_n1000` is NOT evidence.** That artifact mixes 456 synthetic
  items drawn from the same distribution and explicitly SIMULATED
  RAG-oracle numbers (its own docstring says so). Synthetic replication
  adds N without adding information, so its CIs and p-values are not
  valid — and its real-data slice shows the selective lift shrinking from
  +25.5 pp to +1.0 pp at 5 % coverage, which is exactly why this round
  sticks to directional language. The honest path to N_accepted ≥ 100 is
  a future round on ~1 200 REAL items (BoolQ/TruthfulQA via the HF
  loaders) with a pre-registered 50/50 split.

## Results

All numbers below are read directly from the round artifacts; every rate
names its denominator.

**Deterministic set** (policy layer, no live oracles — committed `2dd7b7c`):
gate invariants unchanged versus the 2026-07-20 freeze. Toolcall v2
full-policy-gate: FAR 0.0 (0/560 harmful of N=700), accuracy 0.90 (630/700).
Blind v3 two-phase decide/score: FAR 0.0, accuracy 0.90 (630/700),
`leakage_free` computed true from the regenerated task surface,
false-block rate 0.50 (70/140 benign).

**Live consensus set** (Workers AI cross-family trio, 544 items,
`results/ablation_v2_n500_results.json`):

| Condition | All-items accuracy (n=544) | Answered | Coverage | Accuracy among answered |
|---|---|---|---|---|
| A single oracle (llama-3.3-70b fp8) | 87.5 % [84.5, 90.0] | 539 | 99 % | 88.3 % |
| B majority (3-oracle) | 85.3 % [82.1, 88.0] | 524 | 96 % | 88.5 % |
| C REMORA (no routing) | 75.9 % [72.2, 79.3] | 456 | 84 % | 90.6 % |
| D2 balanced routing | 82.9 % [79.5, 85.8] | 503 | 92 % | 89.7 % |

The two-metrics story is exactly why the abstention-aware block exists:
REMORA conditions trade all-items accuracy for selectivity — they answer
fewer items and are more accurate on the ones they answer.

**Thermodynamic phases** (`thermodynamic_eval_n500_uncalibrated_results.json`,
UNCALIBRATED primary per SAP): ordered n=31 (majority accuracy 93.5 %),
critical n=245 (94.3 %), disordered n=268 (76.1 %). Routing helped 0 and
hurt 13 items versus majority — a negative result reported as-is.

**End-to-end policy decisions** (`end_to_end_n500_v3.json`, n=544):
accept 18.6 %, verify 32.2 %, abstain 49.3 %, escalate 0 %.

**Confirmatory H1′** (`selective_n500_holdout_results.json`; τ* locked on
the training split at the 18th percentile, group-aware 80/20 split seed 42):
on the 108-item holdout, low-temperature acceptance selected 18 items, all
18 correct (100 %, Wilson CI [82.4 %, 100 %]) at 16.7 % coverage — +12.96 pp
over the 87.04 % holdout majority baseline. Exact one-sided binomial
p = 0.082: **not significant at α = 0.05**, and the CI does not exclude the
baseline. By the pre-registered reporting rule (N_accepted = 18 < 100) this
is a directional observation only; the honest path to a powered test
remains the planned ~1 200-real-item round.

## Where the artifacts live

`results/ablation_v2_n500_results.json` (consensus arms),
`results/thermodynamic_eval_n500_uncalibrated_results.json` (H/D → phase →
routing), `results/end_to_end_n500_v3.json`,
`results/selective_n500_holdout_results.json` (confirmatory H1′),
`results/toolcall_*` (policy layer), each with its provenance sidecar.
Old artifacts stay frozen and checksummed — superseded, never overwritten
retroactively.
