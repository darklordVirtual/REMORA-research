# REMORA Benchmark Integrity Audit v1

**Date:** 2026-06-30
**Repository commit:** `2cd573d` (master)
**Auditor:** Agent B (benchmark integrity, statistical validity, test-fix)
**Scope:** Leakage audit, train/test split verification, sample sizes, CI, ceiling effects, weak baselines, circular evaluation, claim-to-artifact consistency, benchmark versioning.

---

## 0. Fixes Applied During This Audit

Two test failures were diagnosed and fixed:

### Fix 1, `test_learning_ablation::TestProfileCArtifactLock::test_profile_c_reproduces_committed_artifact`

**Root cause:** Commit `3c94c6b` updated `artifacts/aromer_learning_ablation_v2.json` to reflect an 88-case arena (`n_eval_cases=88`, `profile_c.false_block_rate=0.0217`) that does not exist on disk. The arena on disk has 85 cases (40 harmful / 45 benign) in 13 non-excluded categories. Profile C produces `false_block_rate=0.0222` against the 85-case arena.

The 0.0005 difference is not floating-point noise. It reflects a different denominator: 1 false block / 45 benign = 0.0222; the committed artifact value 0.0217 implies 1/46 benign, consistent with the phantom 88-case arena. The tolerance `assertAlmostEqual(places=4)` requires agreement within 5e-5, which is 10x tighter than the observed 5e-4 difference.

**Fix:** Regenerated `artifacts/aromer_learning_ablation_v2.json` from the actual 85-case arena using `python -m remora.aromer.evals.learning_ablation --out artifacts/aromer_learning_ablation_v2.json`. Profile C is deterministic (3/3 identical runs verified).

**Updated metric values (artifact regenerated 2026-06-30):**

| Metric | A: REMORA-only | B: AROMER cold | C: AROMER seeded | C-A delta |
|---|---|---|---|---|
| false_accept_rate | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| false_block_rate | 0.0222 | 0.0222 | 0.0222 | 0.0000 |
| review_friction | 0.5333 | 0.5333 | 0.4222 | −0.1111 |
| correct_intercept_rate | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| coverage | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| verdict_accuracy | 0.8824 | 0.8824 | 0.9412 | +0.0588 |

Success criterion: **PASS** (C reduces review_friction by 11.1 pp while holding safety floor).

### Fix 2, `test_shadow_replay_cli_out_dir_writes_expected_files`

**Root cause:** `scripts/shadow_replay.py` imports `from remora.shadow.replay import replay_action_log` at module level. The test invokes the script as a subprocess with `cwd=<repo_root>`, but `remora` is installed in editable mode pointing to a different path (`REMORA-research-verify`). When the script runs as a subprocess, Python's path does not include the repo root, so the import fails with `ModuleNotFoundError: No module named 'remora'`.

**Fix:** Added a `sys.path.insert` block at the top of `scripts/shadow_replay.py` that adds the repo root (`Path(__file__).resolve().parents[1]`) to `sys.path` if not already present. This is the standard pattern for repository scripts that must remain runnable without a package install.

**File changed:** `scripts/shadow_replay.py` (6 lines added after existing imports, before `from remora.shadow.replay import ...`).

---

## 1. Leakage Audit

### M1, `is_unsafe_if_executed` label leakage (resolved)

The primary leakage risk is documented as M1 in `remediation_register.yaml` and `baseline_snapshot.md`. Prior to 2026-06-28, `remora_gate.py:169` accessed `task.is_unsafe_if_executed` when `use_contradiction_flags=True`. This field is derived from the evaluation truth label, constituting direct label leakage into the gate.

**Status post-fix:**
- Fix applied at commit `375800d`: `is_unsafe_if_executed` branch removed entirely from gate.
- AST leakage detector added: `scripts/check_no_evaluation_leakage.py`.
- Mutation tests: `tests/test_m1_leakage_absent.py`.
- Clean-signal verification artifact: `results/toolcall_m1_clean_signal.json`.

**Finding:** FAR=0.0 is sustained in both the leaky (`use_contradiction_flags=True`) and clean (`use_contradiction_flags=False`) conditions. The leakage was not load-bearing for the primary safety claim. See artifact `results/toolcall_m1_clean_signal.json`.

**Residual leakage risk:** The toolcall benchmark's structural flags (forbidden tools, tainted arguments) are correlated with harmfulness by construction: this is noted as a benchmark design issue in CLAIM-001's caveat: "if all harmful tasks have at least one detectable signal by construction, the result may document a tautology rather than generalization." This is an acknowledged, documented limitation; it does not constitute label leakage in the strict sense.

**Learning ablation: no leakage risk:** Profile C is evaluated after seed loading and one `adapt()` cycle on a temp store. The arena cases used for evaluation are never passed to `adapt()`. The `can_train=False` flag on arena cases (from `Episode` provenance) ensures the adaptation does not train on evaluation data. The code path in `run_profile_c` evaluates cases only after the adapt cycle, not during it.

---

## 2. Train / Test / Validation Split Verification

### Toolcall Benchmark v2 (N=700)

- **Split:** No train/test split. The benchmark is evaluation-only: deterministic synthetic tasks with no learned parameters. The gate is rule-based; there is no held-out split because no model is fitted to the data. The split concern is therefore not applicable.
- **Blind v3 separation:** Labels are stored in `benchmarks/toolcall_blind_v3/labels.json`, actions in `benchmarks/toolcall_blind_v3/tasks.json`. The gate receives only `tasks.json`. The scorer loads `labels.json` separately by `task_id`. This is verified by `leakage_free=True` in the result artifact.
- **Composition:** 560 harmful / 140 benign (4:1 ratio). The imbalance means false-block rate is meaningful but utility figures are harmful-task-weighted.

### Selective Prediction Benchmark (N=544)

- **Split:** 80/20 stratified by source, seed=42. Training split: N=436; held-out split: N=108.
- **Threshold lock:** τ* = 0.2032 selected on training split, locked before holdout was touched (documented in `docs/assurance/statistical_analysis_plan.md` §1). No re-optimisation on holdout.
- **Held-out result:** N_accepted=25 on held-out split, accuracy=88%. Wilson CI [70.0%, 95.8%] is wide (25.8 pp). This is a **directional observation only**: the SAP labels it `[POST-HOC]` and requires N_accepted >= 100 for generalization claims.
- **Split label:** `CLAIM-004` in `claim_register_v1.yaml` correctly describes this as a held-out split result with the CI and sample-size caveat.

### AROMER Learning Ablation Arena (N=85)

- **Holdout integrity:** The 85-case arena is held-out from AROMER adaptation. The seed episodes (N=68) are loaded from `remora/aromer/seeds/`, which are separate from the arena files (`remora/aromer/evals/replay_arena/`). No arena case appears in the seed files.
- **Determinism:** Verified bit-identical across 3 sequential runs within the same repo state.
- **Adversarial hard exclusion:** 8 adversarial_hard cases are excluded from the learning ablation arena by `_ABLATION_EXCLUDED_CATEGORIES`. This is documented in the code and is the correct choice: these are red-team probes scored separately, not learning-lift targets.

### External AgentHarm Benchmark (N=208)

- **Independence:** Dataset sourced from `ai-safety-institute/AgentHarm` (arxiv:2410.09024). Not present in REMORA's training corpus. Independence is structural (third-party dataset).
- **No split:** Evaluation-only, no learned parameters.

---

## 3. Sample Sizes and Confidence Intervals

| Benchmark | N_total | N_harmful | Primary metric | CI (95%) |
|-----------|---------|-----------|----------------|----------|
| Toolcall v2 (main) | 700 | 560 | FAR=0.0% | Wilson [0.00%, 0.55%] |
| Toolcall blind v3 | 700 | 560 | FAR=0.0% | Wilson [0.00%, 0.55%] |
| AgentHarm external | 208 | 208 | FAR=0.0% | Wilson [0.00%, 1.81%] |
| False-accept regression | 167 | 167 | FAR=0.0% | Wilson [0.00%, 2.22%] |
| Selective held-out | 25 |, | Accuracy=88.0% | Wilson [70.0%, 95.8%] |
| AROMER arena (Profile C) | 85 | 40 | intercept=100% | Wilson [91.2%, 100%] |

**Validity notes:**

- FAR=0 CIs are mechanically correct but the toolcall and AgentHarm CIs (0.55%, 1.81%) rely on the benchmark being adversarially complete (no gap category). This is not guaranteed for synthetic benchmarks.
- The selective held-out N=25 produces a CI wide enough (25.8 pp) that no generalization claim is warranted. The SAP correctly categorizes this as `[POST-HOC]`.
- AROMER arena: correct_intercept_rate=100% (40/40 harmful blocked). Wilson CI lower bound 91.2%: this is the honest floor on the 40-case harmful subset, not a claim over all possible harmful actions.

---

## 4. Ceiling Effects and Weak Baselines

### Ceiling effects

**Toolcall v2 / blind v3:** FAR=0.0 (0 false accepts from 560 harmful). This is a ceiling on the safety metric. It cannot be used to compare variants of the gate: all variants that reach 0% FAR are indistinguishable on this axis. The review-friction / utility axis (0.62) is the differentiating metric.

**AgentHarm external:** FAR=0.0 (208/208 blocked). The caveats in `CLAIM-002` note: "Stage 1 hard-block policy invariants account for this result. The multi-oracle consensus machinery contributes VERIFY/ABSTAIN routing quality only." The full-block of benign variants (FBR=100%) is a ceiling that shows the current gate is too conservative for AgentHarm's benign variants, but the FBR is expected given the harm_category label similarity between harmful and benign variants in that dataset.

**AROMER learning ablation:** correct_intercept_rate=100% across all three profiles (A, B, C). This means the AROMER learning signal cannot be differentiated on intercept rate: the ceiling was already hit by the static REMORA engine. Profile C's real improvement (−11.1 pp review friction, +5.9 pp verdict accuracy) is on the utility side, not the safety side.

### Weak baselines

**Toolcall v2 baselines:** The comparison baselines (`single_model_heuristic`, `majority_vote_heuristic`, `severity_heuristic`) are synthetic rule-based heuristics, not actual deployed systems. Their FAR values (10–30%) are derived from the same deterministic simulation, not from real LLM-based gate behavior. This is a known and documented limitation (CLAIM-001 caveat: "Benchmark is synthetic and adversarial patterns are designed in-distribution").

**LLM baselines pilot (N=100):** `results/toolcall_llm_baselines_pilot_n100.json` exists as a partial remediation (REM-010). This is a pilot: the full LLM baseline integration is marked `IN_PROGRESS` in `remediation_register.yaml`.

**Recommendation:** The primary strength of CLAIM-001 rests on the Stage 1 structural hard-blocks (forbidden-tool, tainted-argument, schema-valid), not on comparison to these baselines. Claims about the gate outperforming baselines must be scoped to the synthetic baseline regime.

---

## 5. Circular Evaluation

**Finding: no circular evaluation detected in the primary claims.**

- The AROMER learning ablation's Profile C is evaluated on arena cases that were never passed to `adapt()`. The seed episodes are authored separately from the arena. Code inspection of `run_profile_c()` confirms: `aromer.adapt()` runs before the arena loop, not inside it.
- The toolcall benchmarks use evaluation artifacts (`tasks.json` / `labels.json`) that are separate from the gate implementation. The gate has no access to `labels.json` at evaluation time (blind v3 protocol).
- The held-out split for selective prediction is touched exactly once: at evaluation time, after the threshold τ* was locked on the training split.

**Note on synthetic arena construction:** The learning ablation arena cases were designed by the system authors after the gate was implemented. While this does not constitute circular evaluation (the arena never feeds back into the gate), it does mean the arena case difficulty was calibrated during framework development. This is a design-bias risk, distinct from data leakage.

---

## 6. Claim-to-Artifact Consistency Table

| Claim ID | Statement (abbreviated) | Artifact | Artifact exists | n_eval correct | Test pinning it |
|----------|--------------------------|----------|-----------------|----------------|-----------------|
| CLAIM-001 | FAR=0% toolcall v2 (N=700, simulator) | `results/toolcall_benchmark_v2_results.json` | Yes | N=700 confirmed | `test_toolcall_benchmark_v2_results.py` |
| CLAIM-002 | FAR=0% AgentHarm external (N=208) | `results/external_benchmark_agentharm_v1.json` | Yes | N=208 confirmed | `test_assurance_envelope.py` (gate REM-014) |
| CLAIM-003 | FAR=0% regression corpus (N=167) | `results/false_accept_regression_v1.json` | Yes | N=167 confirmed | `test_assurance_envelope.py` (gate REM-019) |
| CLAIM-004 | 88% selective accuracy at 23.2% coverage (N=25 accepted) | `results/selective_n500_holdout_results.json` | Yes | N_accepted=25 confirmed | `test_selective_n500.py` |
| CLAIM-005 | Critical-phase trust inversion (negative result, N=32) | `results/selective_n500_results.json` | Yes | N=32 confirmed | Covered by N500 test suite |
| CLAIM-006 | AROMER AII=0.8412 TRAINED (shadow-mode only) | `artifacts/aromer/intelligence_after_v020.json` | Yes | Live endpoint | No deterministic test possible |
| CLAIM-007 | Component ablation: REMORA full gate dominates (N=700) | `artifacts/aromer/component_ablation_results.json` | Yes | N=700 confirmed | `test_toolcall_benchmark_v2_results.py` |
| CLAIM-008 | 94.7% accuracy at 25% coverage, calibration set (N=302) | `results/selective_trust_curve_results.json` | Yes | N=302 confirmed | `test_selective_trust_curve.py` |
| CLAIM-009 | FA=30.7% on neutral-metadata external datasets (negative) | `artifacts/aromer/external_dataset_eval_v2.json` | Yes (restored from main repo 2026-07-03) | N=1036 confirmed | Documented negative result; no lock test |
| CLAIM-010 | FAR=0% blinded v3 (N=700, leakage_free=True) | `results/toolcall_blind_v3_results.json` | Yes | N=700, leakage_free=True | `test_toolcall_v2_results.py` |
| CLAIM-A | Profile C false_block_rate=0.0222, arena (N=85) | `artifacts/aromer_learning_ablation_v2.json` | Yes (regenerated) | N=85 confirmed | `test_learning_ablation.py::TestProfileCArtifactLock` |

**Consistency status:** All primary claims have matching artifacts with correct n_eval. CLAIM-001 and CLAIM-010 both use N=700 with the same task set (v2 and blind v3 respectively); their results are consistent (FAR=0 in both). No discrepancies between stated and artifact n_eval values were found after the artifact regeneration in Fix 1.

---

## 7. Benchmark Versioning Status

| Benchmark | Version | Artifact | Pinned? | Notes |
|-----------|---------|----------|---------|-------|
| Toolcall benchmark v2 | v2 (current) | `artifacts/toolcall_benchmark_v2.json` | Yes (AST leakage detector) | v1 superseded; M1 fix documented |
| Toolcall blind v3 | v3 (stricter label separation) | `benchmarks/toolcall_blind_v3/` | Yes (blinded files) | Supersedes v2 for citation; v2 retained for history |
| Learning ablation arena | v1 (85-case, 13 categories) | `remora/aromer/evals/replay_arena/` | Yes (regression test) | adversarial_hard (8 cases) evaluated separately |
| N500 selective benchmark | locked | `artifacts/benchmark_n500_locked.json` | Yes (checksum in manifest) | Held-out split frozen at τ*=0.2032, seed=42 |
| AgentHarm external | v1 (2026-06-29) | `results/external_benchmark_agentharm_v1.json` | Yes (REM-014 gate checksum) | Third-party dataset; sha256 in artifact_manifest_v1.md |
| False-accept regression | v1 (167 episodes) | `results/false_accept_regression_v1.json` | Yes (REM-019 gate checksum) | Internal corpus; 2 exclusions documented |

**Versioning gaps:**
- `results/thermodynamic_eval_n500_calibrated_results.json` has no `git_commit` provenance field. Noted in `artifact_manifest_v1.md` as a known gap.
- `results/ablation_report.txt` is plain text with no embedded provenance. Same gap.
- LLM baselines (REM-010) are at pilot stage (N=100); the full baseline evaluation is not yet versioned.

---

## 8. Structural Integrity Observations

### Split boundary enforcement

There is no automated mechanism preventing arena cases from being added to the seed set between commits. The current state is clean (verified by manual path inspection: `remora/aromer/seeds/` files do not contain any case `id` from `remora/aromer/evals/replay_arena/`), but this is not enforced by a test. A test checking that no arena case ID appears in any seed file would close this gap.

### Synthetic nature of all primary benchmarks

All primary benchmarks (toolcall v2, toolcall blind v3, learning ablation arena, N500 selective) are internally authored. The one exception is AgentHarm (CLAIM-002). This creates a risk of design-induced optimism that cannot be ruled out by result review alone. The SAP correctly labels H2/H3 as `[POST-HOC]` and requires external replication with independently withheld labels for definitive resolution.

### AROMER arena case count drift

The root-cause of Fix 1 is that `n_eval_cases` in the v2 artifact had drifted to 88 while the arena files contained 85 cases. The regression test (`TestProfileCArtifactLock`) now locks the artifact to what the code actually produces, preventing this class of drift. No further commits should update the artifact without re-running `python -m remora.aromer.evals.learning_ablation --out artifacts/aromer_learning_ablation_v2.json`.

---

## 9. Remaining Uncertainty

1. **LLM baseline gap (REM-010):** The toolcall benchmark compares REMORA against deterministic heuristic baselines, not against LLM-based gate implementations. The pilot (N=100) shows REMORA's advantage holds under real LLM baselines in the initial sample, but the full N=700 LLM baseline run is pending.

2. **External replication gap:** No benchmark result has been independently replicated by parties outside the project. The AgentHarm benchmark uses a third-party dataset (satisfying dataset independence) but the evaluation was run by the project authors with project code.

3. **Selective prediction generalization (CLAIM-004):** N_accepted=25 yields a CI [70.0%, 95.8%] too wide to establish generalization. The SAP requires N_accepted >= 100 from an independently collected dataset before this claim can be upgraded.

4. **AROMER arena adversarial_hard exclusion:** The 8 adversarial_hard cases are evaluated separately from the learning ablation. Their results are not included in any committed summary artifact for the ablation: they would need a dedicated artifact if published separately.

5. **Arena case construction bias:** The 85 learning ablation cases were authored after the REMORA gate was implemented. The difficulty calibration (what makes a case ambiguous vs clear) was influenced by gate behavior during development. This is a structural design-bias risk that cannot be eliminated post-hoc; it should be disclosed in any publication.

---

## 10. Summary of Findings

| Finding | Severity | Status |
|---------|----------|--------|
| M1 label leakage (`is_unsafe_if_executed`) | Critical | Fixed (2026-06-28, pre-audit) |
| Arena/artifact case-count drift (88 vs 85) | High | Fixed (2026-06-30, this audit, artifact regenerated) |
| shadow_replay.py ModuleNotFoundError in subprocess | High | Fixed (2026-06-30, this audit, sys.path added) |
| Selective prediction N_accepted=25 too small for generalization | Medium | Documented (SAP, CLAIM-004 caveat); remediation requires larger dataset |
| LLM baselines incomplete (pilot only) | Medium | In progress (REM-010) |
| Thermodynamic eval artifact lacks git_commit | Low | Documented (artifact_manifest_v1.md gap list) |
| Arena/seed split boundary not test-enforced | Low | No test for cross-contamination; manual check confirms clean state |
| All primary benchmarks are internally authored | Structural | Documented (SAP, CLAIM-001 caveats); remediation is external replication |
