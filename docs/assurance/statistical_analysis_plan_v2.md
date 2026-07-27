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

**Amendment 2026-07-27 (recorded BEFORE the first live benchmark call —
no ablation/thermodynamic evaluation had run):** the live segment moves
from Groq to **Cloudflare Workers AI**. Reason: the Groq free-tier daily
token quota is shared with the deployed production workers and was
exhausted on round day (persistent 429, `x-should-retry: false`), and the
operator directed the round to run on Workers AI. The family rule and
selection procedure are unchanged.

| Oracle | Model | Family | Host |
|--------|-------|--------|------|
| 1 | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Meta LLaMA | Cloudflare Workers AI |
| 2 | `@cf/qwen/qwen3-30b-a3b-fp8` | Alibaba Qwen | Cloudflare Workers AI |
| 3 | `@cf/mistralai/mistral-small-3.1-24b-instruct` | Mistral | Cloudflare Workers AI |

Selection basis (declared before any benchmark evaluation): Workers AI
catalog availability (live-verified against the account's model list,
2026-07-27) and a 3-prompt JSON-compliance smoke test through the same
prompt template the benchmark uses — no benchmark items or labels were
used to pick models. All candidates passed 3/3; `@cf/openai/gpt-oss-120b`
(OpenAI open-weight family) is the documented reserve if a trio member is
withdrawn mid-round. Host is shared (Cloudflare) — family diversity is
about weight ancestry, not hosting; a hosting outage affects availability,
not verdict correlation.

The originally declared Groq trio (`llama-3.3-70b-versatile`,
`openai/gpt-oss-120b`, `qwen/qwen3.6-27b`; qwen with
`reasoning_effort=none`, `max_tokens` 256→1024) remains recorded here and
selectable via `--backend groq` for reproduction attempts; it produced no
round artifacts.

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
| 2026-07-27 | Clarification recorded after round start: with n=544, an 80/20 group split and 18 % coverage, the expected holdout N_accepted is ≈25 — §4's own ≥100 bar for generalization language is structurally unreachable this round | This round's H1′ outcome is reported as a directional observation regardless of p-value; generalization claims require a future round on a larger item pool | The arithmetic was pointed out post-start by review; recording it explicitly prevents the result from being over-quoted |
| 2026-07-27 | Abstention-aware `selective` block ADDED to every ablation condition (`experiments/ablation_v2.py::selective_metrics`): n_answered, abstained-or-unparsed, coverage, accuracy_answered + Wilson CI. Legacy all-items `accuracy` unchanged | Review found the legacy metric scores abstention identically to a wrong answer (majority vote measured 29 % on yes/no BoolQ — below the 50 % chance floor), structurally penalizing selective conditions against always-answer baselines. Both metrics are now reported; neither replaces the other | Additive reporting fix found after round start but before any round artifact was written; H1′ analysis is untouched |
| 2026-07-27 | Live-segment provider changed Groq → Cloudflare Workers AI (§2 amendment above); trio re-selected from the Workers AI catalog under the unchanged family rule and smoke-test procedure | None on H1′ or any metric definition: no live benchmark call had been made, so no round artifact reflects the old trio. The deterministic segment (already committed at `2dd7b7c`) uses no live oracles and is unaffected | Groq free-tier daily token quota shared with deployed workers was exhausted (persistent 429); operator directed the round to run on Workers AI |
| 2026-07-27 | H1′ implementation error caught by external statistics review BEFORE merge: `selective_n500_holdout.py` computed the exact binomial against the HOLDOUT's own majority baseline (p = 0.082) instead of the §4-mandated training-split p₀. Corrected to p₀ = 0.848624 (training baseline); regenerated artifact reports p = 0.052 | Conclusion unchanged in kind: still above α = 0.05, CI still does not exclude p₀, still a directional observation under the N_accepted < 100 rule. The initially published p was CONSERVATIVE (larger than the correct value) | Script predated SAP v2's D-5 fix and was not updated when the plan was; the stale in-artifact provenance note has been rewritten to match §2/§4, including the reused-corpus caveat |
