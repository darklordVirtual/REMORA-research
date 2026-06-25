# How were the experiments designed and what did they produce?

Each section covers one experiment type: design, artifact, N, and result. No
methodology text is repeated across sections.

→ [02-evidence-and-claims.md](02-evidence-and-claims.md) for the headline claims
these experiments support.
→ [06-reproducibility.md](06-reproducibility.md) for exact reproduce commands.
→ [04-negative-results-detail.md](04-negative-results-detail.md) for what did not
replicate cleanly.

---

## Experiment 1 — Selective QA acceptance (N302, N500)

**Research question:** Can REMORA's trust score selectively accept high-trust
answers with accuracy well above the baseline while covering a useful fraction of
the item set?

**Design:** Multi-oracle pipeline on QA items. Trust score T computed from
entropy H and dissensus D. Threshold τ* locked on training split (80% of data)
before holdout is touched. Metric: selective accuracy at τ* on the holdout split.

**N:** N302 calibration artifact; N500 (544-item) main artifact.

**Artifact:**
- `results/selective_n500_holdout_results.json`
- `paper/remora_paper.pdf` §8

**Result:**
- In-sample: 88.78% selective accuracy at 18% coverage (+47.6 pp over baseline).
- Holdout: 88.0% selective accuracy at 23.2% coverage (N_accepted = 25).
- Threshold τ* = 0.2032 (locked before holdout).
- Wilson CI [70.0%, 95.8%], one-sided binomial p = 1.45×10⁻⁵.

**Caveat:** N_accepted = 25. The CI is wide; 70.0% is the honest lower bound.

**Reproduce:**
```bash
python experiments/end_to_end_n500_v3.py
```

---

## Experiment 2 — Critical-phase trust inversion

**Research question:** Does the trust score behave differently in the
"critical" phase, and does inverting it improve routing?

**Design:** Phase classification partitions items into ordered, critical, and
disordered. In the critical phase, higher trust correlates with incorrect
answers. `PhaseAwareGuardrail` inverts the selection score for critical-phase
items.

**N:** 32 critical-phase items in the N500 calibration set (N=21 low-trust,
N=11 high-trust).

**Artifact:** `paper/remora_paper.pdf` §6.1, §13; `NEGATIVE_RESULTS.md`.

**Result:**
- Low-trust critical items: 71.4% correct (N=21).
- High-trust critical items: 27.3% correct (N=11).
- Naive conformal at 5% risk target: 100% observed risk / 0 coverage in critical
  phase.

**Caveat:** small sample (N=32 critical items). Published as a negative result.

---

## Experiment 3 — Adversarial tool-call benchmark v1 (252 tasks)

**Research question:** Can REMORA reduce unsafe tool-call execution versus
deterministic heuristic baselines?

**Design:** Deterministic simulator over 7 domains. No real shell/network/db
mutations. Safety model: unsafe execution occurs when `is_unsafe_if_executed=True`
and predicted action is `EXECUTE`.

**N:** 252 tasks.

**Artifact:** `artifacts/toolcall_benchmark_v1.json`.

**Result:** All strategies including heuristic baselines reach 0% unsafe
execution. The benchmark is not adversarially hard enough to differentiate.

**Finding:** Negative result — v2 was designed to address this. See
`NEGATIVE_RESULTS.md` resolved finding R8.

**Reproduce:**
```bash
python experiments/generate_toolcall_benchmark.py
python experiments/evaluate_toolcall_benchmark.py
python experiments/toolcall_ablation.py
```

---

## Experiment 4 — Adversarial tool-call benchmark v2 (700 tasks)

**Research question:** Can REMORA reduce unsafe execution under harder adversarial
conditions where heuristic baselines fail?

**Design:** 700-task simulator with 8 adversarial scenario families added over v1:
`safe_looking_dangerous`, `missing_context_high_risk`, `conflicting_intent`,
`regulated_ambiguity`, `production_target_ambiguity`, `counterfactual_trap`,
`prompt_injection`, `unsafe_destructive`.

Calibration split: 350 tasks. Validation split: 350 tasks. Blind test: 350
tasks (OOD within synthetic generator — not external real-world OOD).

**N:** 700 tasks.

**Artifact:**
- `artifacts/toolcall_benchmark_v2.json`
- `results/toolcall_benchmark_v2_summary.md`
- `results/toolcall_benchmark_v2_significance.json`
- `results/toolcall_benchmark_v2_calibration.json`
- `results/toolcall_benchmark_v2_blind_test.json`

**Result (full matrix, validation split):**

| Baseline | Unsafe exec rate | Mean utility | Accuracy |
|---|---:|---:|---:|
| single_model_heuristic | 0.2000 | −0.250 | 20.0% |
| majority_vote_heuristic | 0.1000 | 0.000 | 30.0% |
| self_consistency_heuristic | 0.1000 | 0.000 | 30.0% |
| verifier_heuristic | 0.2000 | −0.250 | 20.0% |
| remora_temperature_gate | 0.1000 | 0.270 | 70.0% |
| **remora_full_policy_gate** | **0.0000** | **0.620** | **90.0%** |

Statistical significance committed at `results/toolcall_benchmark_v2_significance.json`.

**Caveat:** deterministic simulator only. The 0% rate is a point estimate; 95%
Wilson CI [0.00%, 0.55%]. The hard-block policy layer — not the oracle consensus
— produces the 0% result. Do not cite as production safety evidence.

**Reproduce:**
```bash
python experiments/generate_toolcall_benchmark_v2.py
python experiments/evaluate_toolcall_benchmark_v2.py
python experiments/toolcall_ablation_v2.py
python experiments/toolcall_v2_significance.py
```

---

## Experiment 5 — Sandbox live execution harness

**Research question:** Does the 0% unsafe execution result hold under sandbox
execution where `EXECUTE` actions are run inside isolated local environments?

**Design:** `experiments/evaluate_toolcall_benchmark_v2_live_exec.py` executes
`EXECUTE` actions inside isolated local sandboxes (filesystem/sqlite/git/network-
state mock files). Does not touch production systems.

**Artifact:** `results/toolcall_benchmark_v2_live_results.json` (replay mode).

**Result (sandbox, 10-task sample):**

| Baseline | Unsafe exec rate | Sandbox unsafe effect rate |
|---|---:|---:|
| single_model_gpt | 0.1000 | 0.1000 |
| single_model_claude | 0.2000 | 0.2000 |
| majority_vote_3_models | 0.1000 | 0.1000 |
| remora_temperature_gate | 0.0857 | 0.0857 |
| **remora_full_policy_gate** | **0.0000** | **0.0000** |

---

## Experiment 6 — Stress replay (v3, 10k calls)

**Research question:** How does REMORA's policy behave under high-volume
deterministic replay?

**Design:** Deterministic stress replay over v3 tasks.
`make stress-toolcalls N_CALLS=10000 SEED=42`.

**N:** 10,000 calls, seed=42.

**Artifact:** `results/toolcall_stress_replay_10000.json`.

**Result:**

| Baseline | Unsafe exec rate | Mean utility | Human-review burden |
|---|---:|---:|---:|
| naive_tool_caller | 52.65% | −0.724 | 0.00% |
| majority_vote_caller | 16.30% | 0.133 | 50.82% |
| schema_only_validator | 3.45% | 0.453 | 37.16% |
| static_policy_gate | 6.07% | 0.327 | 34.54% |
| remora_full_policy_gate_v3 | 2.82% | 0.597 | 30.02% |

Delta vs naive: −49.83 pp unsafe execution, +1.321 mean utility, −100% critical
false accept rate.

**Caveat:** benchmark-scoped deterministic replay only. Not production traffic.

**Reproduce:**
```bash
make stress-toolcalls N_CALLS=10000 SEED=42
```

---

## Experiment 7 — Ordered-phase conformal coverage

**Research question:** Does conformal risk control achieve target coverage on
ordered-phase items across repeated calibration splits?

**Design:** Mondrian conformal guardrail with per-phase calibration. 20 repeated
calibration seeds. Target risk: 15%.

**Artifact:** `paper/remora_paper.pdf` §9.3.

**Result:** 99.9% coverage at 15% risk target on ordered-phase items, 0 of 20
seeds failing.

**Caveat:** holds for ordered phase only. Critical and disordered phases cannot
achieve meaningful conformal coverage — this is why `PhaseAwareGuardrail` and
the evidence router exist.

---

## Experiment 8 — Cross-domain governance benchmark

**Research question:** Do REMORA's governance verdicts hold across cyber, AI
governance, and finance evidence domains?

**Design:** Three domain evidence providers (CyberEvidenceProvider,
AIGovernanceProvider, FinanceEvidenceProvider) with exact identifier lookup and
lexical/RAG retrieval. Deterministic benchmark requiring no API keys.

**Artifact:** `artifacts/domain_benchmark_results.json`.

**Reproduce:**
```bash
make cyber-evidence
python experiments/domain_benchmark.py
```

---

## Experiment 9 — AROMER learning loop (experimental)

**Research question:** Does the AROMER closed-loop learning layer improve
governance without degrading the safety floor?

**Design:** Three profiles evaluated against an 85-case holdout (all
`can_train=False`): A (REMORA-only), B (AROMER cold), C (AROMER seeded, 18
episodes, one adapt() cycle). Holdout discipline: AROMER never adapts from
eval cases.

**N:** 85 holdout cases; 18 seed episodes for Profile C.

**Artifact:** `artifacts/aromer_learning_ablation_v1.json`.

**Result:**

| Metric | A: REMORA-only | B: AROMER cold | C: AROMER seeded |
|---|---|---|---|
| false_accept_rate | 0.000 | 0.000 | 0.000 |
| correct_intercept_rate | 1.000 | 1.000 | 1.000 |
| review_friction | 0.325 | 0.325 | 0.325 |
| coverage | 1.000 | 1.000 | 0.769 |
| verdict_accuracy | 0.769 | 0.769 | 0.585 |

> **Note:** this 85-case figure is the ablation holdout artifact. The live replay
> arena reported in `02-evidence-and-claims.md` (Claim 6) uses 93 cases — a different
> evaluation surface.

**Findings:** Safety floor intact. No friction reduction yet (18 seed episodes
insufficient). Profile C shows 23.1% coverage drop due to world model over-
abstaining with insufficient training data.

**Caveat:** EXPERIMENTAL. Labels are partly self-labeled. The world model
defaults to shadow mode. Not externally validated. Do not cite AROMER numbers
as production evidence. See `04-negative-results-detail.md` §2.
