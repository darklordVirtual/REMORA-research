# Statistical Analysis Plan v2 — Clean Benchmark Round 2026-07

**Pre-registered:** this document is committed BEFORE any evaluation of the
round it governs. Once the first live oracle call of the round is made, this
plan may only be changed by adding a dated deviation row to §6.

Supersedes SAP v1 for the 2026-07 round (SAP v1 stays as the record of the
previous round and its deviations D-1…D-5). Written to be readable by a
non-statistician; every rule states its *why*.

## 1. What this round is for

Regenerate the benchmark matrix frozen at commit `9c6eea0` (2026-07-20)
under a corrected protocol, so the numbers can be trusted:

- the decision engine and thermodynamics code changed after the freeze
  (χ rewrite in `a585202`), so the old numbers describe old code;
- the old consensus ensemble was three Meta LLaMA models — same weight
  family, correlated errors, effectively fewer independent voters than
  claimed (and one of the three no longer exists on the provider);
- the audit fixes (blinding, metric denominators, exact tests, provenance)
  must actually be exercised end to end.

## 2. Pre-registered consensus ensemble (cross-family)

**Rule: no two oracles in a consensus ensemble may share a model weight
family.** Enforced in code by `remora/oracles/families.py`
(`validate_cross_family`, fail-closed on unknown families) — construction
of a same-family swarm now raises.

| Oracle | Model | Family | Host |
|--------|-------|--------|------|
| 1 | `llama-3.3-70b-versatile` | Meta LLaMA | Groq |
| 2 | `openai/gpt-oss-120b` | OpenAI (open-weight) | Groq |
| 3 | `qwen/qwen3.6-27b` | Alibaba Qwen | Groq |

Selection basis (declared before any benchmark evaluation): current Groq
catalog availability and a 3-prompt JSON-compliance smoke test
(2026-07-27) — no benchmark items or labels were used to pick models.
Qwen runs with `reasoning_format=hidden` (chain-of-thought stripped);
`max_tokens` raised 256→1024 so reasoning-token budgets cannot truncate
answers. Host is shared (Groq) — family diversity is about weight ancestry,
not hosting; a hosting outage affects availability, not verdict correlation.

## 3. Pipeline under test

Full chain, no shortcuts: oracle fan-out → verdict extraction → weighted
support → entropy **H** / dissensus **D** → temperature / order parameter /
susceptibility χ / phase → phase-and-χ routing (`phase_controller`) →
policy engine decision. Runner: `experiments/thermodynamic_eval.py`
(module `remora.benchmarks.extended_v2_n500`, 544 items), consumed by
`experiments/end_to_end_n500_v3.py` and `scripts/selective_n500_holdout.py`.

**Calibration rule (declared before the first live call):** the primary
thermodynamic run is **uncalibrated** (`--calibration` omitted).
`calibrate_thermodynamics.py` fits phase/trust rescaling against labelled
outcomes (`d2_correct`), so a calibration fitted on the evaluation data is
in-sample tuning — the prior round's "calibrated" artifact had exactly this
problem. A calibrated variant may be reported only as a secondary analysis
with the calibration fitted on the TRAINING split alone.
The deterministic toolcall matrix (v2 + blind v3 two-phase + significance,
calibration, failures, ablation, governance-intelligence) is regenerated at
the same commit; it exercises the policy layer only (no live oracles) and
its blind-v3 run uses separate decide/score processes.

## 4. Confirmatory hypothesis (H1′)

**H1′:** selective acceptance by low temperature (signal fixed a priori:
`neg_temperature`; acceptance coverage fixed a priori: 18 % of training
split) yields holdout accuracy above the majority-vote baseline.

Why this is now legitimate pre-registration: the prior round *derived*
signal and coverage from the full dataset (SAP v1 deviation D-5). This
round declares them here, **before** the new ensemble has produced a single
temperature — the new oracle trio generates an entirely fresh dataset, so
nothing about it has been seen.

- Split: 80/20, seed 42, stratified by benchmark source AND group-aware by
  content hash (`_group_key` in `scripts/selective_n500_holdout.py`) —
  identical content can never sit on both sides.
- τ*: locked on the training split at the 18th percentile; never touched
  on holdout.
- Test: one-sided **exact** binomial, α = 0.05. Null p₀ = majority-vote
  accuracy computed on the **training split** (not the holdout — SAP v1
  deviation D-5 fixed).
- Effect size: Wilson 95 % CI on accepted holdout items.
- Reporting language: N_accepted < 100 → "directional observation" only;
  ≥ 100 → generalization language permitted if the CI excludes p₀.
- A negative or null result is published unchanged (NEGATIVE_RESULTS.md).

## 5. Metrics, provenance, execution discipline

- Metrics: canonical keys from
  [metric_definitions_v1.md](metric_definitions_v1.md); every quoted rate
  names its denominator.
- Every artifact gets a `result_provenance_v2` sidecar
  (`scripts/result_provenance.py`): git commit, worktree state, Python
  version, lock hash, input hashes, seeds, command.
- The round runs from a clean committed tree; the orchestrating commit is
  tagged `benchmark-round-2026-07`. Claim register / README / paper are
  updated only from the new artifacts, after the round completes.
- Out of scope (imported, cannot rerun here): AgentHarm N=208 and the
  N=167 regression corpus — they remain labelled historical/imported
  (rebenchmark_protocol_v1.md).

## 6. Deviations from this plan

| Date | Deviation | Impact | Why |
|------|-----------|--------|-----|
| — | (none yet) | | |
