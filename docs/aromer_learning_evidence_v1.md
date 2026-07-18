# AROMER Learning Evidence Report v1

> **Historical snapshot (2026-06-05, AROMER v1, 65–85 case arena).** This report documents the initial ablation evaluation with 18 seed episodes and a small arena; AROMER did not yet improve over static REMORA at this stage. The arena has since expanded to 96 cases (87.5% accuracy). Current evidence: `artifacts/aromer/replay_arena_report.json` (REMORA main repo); full trajectory in `paper/remora_paper.md Appendix F.6–F.7`.

**Date:** 2026-06-05
**Status:** RESEARCH PROTOTYPE, results are preliminary observations, not validated benchmarks
**Artifact:** `artifacts/aromer_learning_ablation_v1.json`

## Summary

Three governance profiles evaluated on a shared 85-case holdout set show that AROMER with 18 seed episodes does not yet improve verdict accuracy or reduce review friction compared to static REMORA. The safety floor (false_accept_rate, correct_intercept_rate) remains intact across all configurations. The measurement instrument is now in place for real-episode accumulation cycles.

## Method

Three governance profiles evaluated against the same 85-case replay arena (holdout, not used for AROMER adaptation):

| Profile | Description | Seed episodes |
|---|---|---|
| A: REMORA-only | Pure RemoraDecisionEngine, no AROMER layer | 0 |
| B: AROMER cold | Fresh AromerOrchestrator, no episodes | 0 |
| C: AROMER seeded | 18 seed episodes pre-loaded + one adapt() cycle | 18 |

**Holdout discipline:** The 65 eval cases are labelled `can_train=False`. AROMER never adapts from them. This ensures the comparison is honest.

## Results

| Metric | A: REMORA-only | B: AROMER cold | C: AROMER seeded | C-A delta |
|---|---|---|---|---|
| false_accept_rate | 0.000 | 0.000 | 0.000 | **0.000** |
| false_block_rate | 0.000 | 0.000 | 0.000 | 0.000 |
| correct_intercept_rate | 1.000 | 1.000 | 1.000 | 0.000 |
| review_friction | 0.325 | 0.325 | 0.325 | 0.000 |
| coverage | 1.000 | 1.000 | 0.769 | −0.231 |
| verdict_accuracy | 0.769 | 0.769 | 0.585 | −0.185 |

## Interpretation

### What the data confirms

- **Safety floor intact.** All three profiles maintain false_accept_rate = 0.000 and correct_intercept_rate = 1.000. AROMER adaptation does not weaken governance.
- **No friction reduction yet.** Review friction remains constant at 0.325 across all profiles. The 18 seed episodes provide insufficient calibration data for benign-context trust boosts.
- **World model activation costs coverage.** Profile C shows a 23.1% drop in coverage (1.000 → 0.769) due to the world model ABSTAIN-ing on out-of-distribution cases. Verdict accuracy follows (0.769 → 0.585) because ABSTAIN is counted as incorrect when the true label is ACCEPT or REJECT (REJECT is the holdout dataset's ground-truth label vocabulary, not an engine outcome: the engine's canonical outcomes are ACCEPT/VERIFY/ABSTAIN/ESCALATE).
- **Cold-start parity.** Profile B (AROMER with no seeds) behaves identically to Profile A (REMORA-only), confirming the default oracle path in AromerOrchestrator is working.

### What the coverage drop in Profile C means

The 23.1% coverage loss is not a safety regression. It is the conservatism cost of early world model activation with insufficient training data. With only 18 seed episodes, the world model has priors for only a handful of (domain, action_type, risk_tier) combinations. Contexts outside those combinations receive higher uncertainty estimates → the MetaJudge adapter recommends ABSTAIN (escalate to human review) instead of ACCEPT or REJECT.

As real episodes accumulate from claude_code_hook logging, the world model will see new distributions, calibrate P(harm | context) across more combinations, and recover coverage. The expected trajectory: after ~100 real labelled episodes, coverage should recover to >0.90, and verdict_accuracy should approach 0.75–0.80.

### The measurement gap: review_friction

Review friction is constant at 0.325 for all three profiles because the 65 eval cases are **deterministic synthetic benchmarks** designed to test governance logic, not real-world tool distribution. Synthetic cases include edge cases, red-team scenarios, and boundary conditions: they do not reflect the benign-tool-call mixture that creates friction in production (file reads, git status, npm installs, etc.).

Friction reduction can only be measured from real `claude_code_hook` episodes collected during live agent sessions. Those sessions automatically log (domain, action_type, risk_tier, user_accept, llm_verdict) tuples, which feed the PreToolUse/PostToolUse adapter flow.

## What AROMER needs to improve these metrics

1. **More real episodes**: the 18 seed episodes are not enough to calibrate the world model. Each real agent session adds 5–20 episodes via the PreToolUse/PostToolUse hooks. After ~100 real labelled episodes, the world model Expected Calibration Error (ECE) should drop below 0.10 for common tool categories.

2. **ECE-gated activation**: the world model activates automatically when ECE < 0.10 and n_high_confidence ≥ 10. At that point, known-benign contexts (git push, file reads) should receive trust boosts → lower friction.

3. **MetaJudge structured critique**: the new MetaJudge v2 schema produces `recommended_adjustment` objects with (domain, action_type, risk_tier, direction) tuples. As the oracle accumulates these, the adapter bridge has actionable signals to reduce friction in specific contexts.

## Success Criterion Status

| Criterion | Status | Evidence |
|---|---|---|
| C.false_accept_rate ≤ A.false_accept_rate | ✓ PASS | Both 0.000 |
| C.correct_intercept_rate ≥ A.correct_intercept_rate | ✓ PASS | Both 1.000 |
| C.review_friction < A.review_friction | ✗ NOT YET | Same: 0.325 (insufficient real episodes) |
| C.coverage ≥ A.coverage | ✗ NOT YET | C=0.769 < A=1.000 (world model over-abstains with 18 seeds) |

## Limitations and Caveats

1. **18 seed episodes is insufficient.** The world model needs ~100+ real labelled episodes across each (domain, action_type, risk_tier) combination before P(harm) priors are calibrated enough to reduce friction. Synthetic seeds alone cannot represent the live distribution.

2. **Synthetic eval cases.** The 65 replay arena cases are carefully designed synthetic benchmarks. They test that AROMER doesn't BREAK governance; they do not test that AROMER IMPROVES it on real-world distributions.

3. **No live oracle in ablation.** The ablation runs without Workers AI oracle calls (deterministic, no API required). The real AROMER system uses LLM oracle consensus which is not captured here.

4. **Profile C coverage drop.** With 18 seeds, the world model has priors for only a few (domain, action_type, risk_tier) combinations. Contexts outside those combinations receive higher uncertainty → more ABSTAIN verdicts. This will improve as real episodes accumulate.

5. **Verdict accuracy metric.** ABSTAIN is counted as incorrect when the holdout label is ACCEPT or REJECT. This is a strict measurement: it penalizes conservative (safe) behavior. Once friction reduction kicks in, we expect verdict_accuracy to remain ~0.75–0.80 while coverage increases.

## Next Measurement Target

Run this same ablation after:
- ≥ 100 real `claude_code_hook` episodes accumulated in D1 database
- At least 2 weeks of hourly AROMER cron cycles with live world model adaptation

**Expected trajectory:**
- Profile C review_friction < 0.25 (vs baseline 0.325)
- Profile C coverage recovering toward 0.90
- Profile C verdict_accuracy stable or improving as world model calibrates

## Reproducibility

```bash
python -m remora.aromer.evals.learning_ablation --json
# Artifact: artifacts/aromer_learning_ablation_v1.json
# Deterministic — no API keys required
# Runtime: ~2 seconds
```

To view the raw results:
```bash
cat artifacts/aromer_learning_ablation_v1.json | jq .
```

## References

- `remora/aromer/seeds/`, 18 seed episode JSONL files
- `remora/aromer/evals/learning_ablation.py`, ablation harness
- `remora/decision_envelope.py`, DecisionEnvelope contract
- `experiments/agentharm/README.md`, external validation roadmap

---

## v2 Results: Expanded Training Data (68 seed episodes)

Artifact: `artifacts/aromer_learning_ablation_v2.json`

Measured on the 85-case replay arena (40 harmful / 45 benign, expanded from 65
with prompt-injection, shell-execution, infra-DNS, and financial-transfer
categories).

| Metric | A: REMORA-only | B: AROMER cold | C: AROMER seeded | C-A delta |
|---|---|---|---|---|
| false_accept_rate | 0.000 | 0.000 | 0.000 | **0.000** |
| false_block_rate | 0.0222 | 0.0222 | 0.0222 | 0.000 |
| correct_intercept_rate | 1.000 | 1.000 | 1.000 | 0.000 |
| review_friction | 0.289 | 0.289 | 0.289 | 0.000 |
| coverage | 1.000 | 1.000 | 1.000 | 0.000 |
| verdict_accuracy | 0.9647 | 0.9647 | 0.9647 | 0.000 |

The single false_block (1/45 benign) is present in static REMORA (A) too, it is a
base-engine over-escalation on one of the new arena cases, **not** introduced by
AROMER. Training data: 18 → 68 seed episodes (+50 synthetic benign-domain coverage
episodes); see the synthetic-seed caveat below.

### Harness fidelity revision (2026-06-06)

Two fidelity bugs in the ablation harness were fixed; the numbers above are
post-fix and supersede all earlier figures in this document:

1. **Dropped `target_environment`.** The harness built the engine observation
   without `target_environment`, so the engine decided without knowing the
   action targeted prod. Passing it (the arena cases always carried it) raised
   baseline verdict_accuracy from 0.769 to **0.9647**, that is a measurement
   correction (the engine was previously under-informed), not a real accuracy
   gain.
2. **No adversarial detection.** The harness ran none. It now runs REMORA's real
   admission firewall (`Remora._detect_adversarial_input`) on the action
   description, mirroring the production pipeline in `engine.py`.

### Bidirectional world model (2026-06-07): AROMER is no longer a coverage cost

Earlier revisions of this document recorded Profile C *costing* 3.1 pp coverage
(1.000 → 0.9692): the world model could only ever *lower* trust, so its single
lever added caution and nothing else. The world model is now **bidirectional**
(`DomainHarmPrior.adjust_trust`): it lowers trust for proven-risky contexts and
*boosts* trust toward the statistically-justified bound `1 − ci_upper` for
contexts proven safe at high confidence. On this arena that recovers the lost
coverage, **Profile C now equals A** (coverage 1.000, accuracy 0.9647, FA 0.000).

On the synthetic arena there is no *reducible* friction to win (its friction is
the genuinely-ambiguous cases, correctly verified), so AROMER is **neutral** here
- `success` is honestly FALSE because there is no strict improvement to make. The
*positive* learning effect is demonstrated where reducible friction exists:

### Measurable, safe learning effect

`remora/aromer/evals/learning_effect.py` (artifact
`artifacts/aromer_learning_effect_v1.json`, test `tests/test_learning_effect.py`)
trains the world model on benign outcomes for safe contexts, then evaluates a
**held-out** set of distinct cases:

| Profile | review friction | false-accept | benign accepted |
|---|---|---|---|
| A: static REMORA | 1.000 | 0.000 | 0.000 |
| C: AROMER (trained) | **0.000** | **0.000** | **1.000** |

AROMER learned which contexts are safe and **eliminated review friction on
held-out benign actions while keeping false-accepts at zero**, previously
impossible. This is a controlled demonstration of the mechanism on
moderate-trust actions in the abstain zone; the magnitude on real traffic
depends on how many real benign actions fall there in proven-safe contexts.
Safety is preserved structurally: the boost never bypasses the engine's hard
gates (adversarial / malformed / forbidden-tool / tainted-argument all ESCALATE
before trust is consulted), and only fires for high-confidence, statistically-safe
contexts (n ≥ 20, p_harm < 0.10, 95% upper bound < 0.25).

### Reproducibility, determinism, and honest framing (v2)

**Reproducible result.** Regenerated 2026-06-07 from the current code and seed
set. `python -m remora.aromer.evals.learning_ablation --out
artifacts/aromer_learning_ablation_v2.json` produces exactly these numbers
(Profile C coverage 1.000, verdict_accuracy 0.9647). The regression test
`tests/test_learning_ablation.py::TestProfileCArtifactLock` re-runs Profile C
and fails if code, artifact, or this document drift apart.

**Determinism is per repo state, not across commits.** Each run is bit-identical
within a fixed repo state (verified: 3/3 identical runs). It is *not* stable
across commits, as the seed set and engine evolve, the "68-seed" Profile C
coverage number has moved (0.908 → 0.954 → 0.969). Every published number is
therefore stamped to the commit that produced it, and the regression test forces
artifact and doc to move together. Earlier committed values (0.908) were
snapshots from prior code states and are superseded by the locked 0.9692.

**This is an instrumentation check, not an external learning result.** The
coverage gain comes from hand-authored *synthetic* seed episodes
(`remora/aromer/seeds/23_benign_domain_coverage.seed.jsonl`, every record flagged
`synthetic:true`) whose (domain, action_type, risk_tier) tuples were chosen to
cover the same taxonomy the 85-case arena tests. It demonstrates that the world
model *can* build priors that reduce abstention when given matching training
data; it does **not** demonstrate generalisation to an independent distribution.
Read coverage 0.9692 as "the measurement instrument works," not as evidence of
transferable learning.

**Superseded by external holdout.** This 85-case synthetic ablation is an
internal smoke test. The claim-grade evaluation is an external, balanced
500-case holdout (AgentHarm-derived harmful cases + real logged benign episodes,
all `can_train=False`), tracked separately. Friction-reduction and transfer
claims wait for that artifact.
