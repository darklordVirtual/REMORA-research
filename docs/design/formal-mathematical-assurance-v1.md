# SDD — Formal Mathematical Assurance for REMORA v1.0

**Status:** PROPOSED / NOT IMPLEMENTED (2026-10-08). **Owner:** REMORA-research. **Scope:** research/shadow-mode. **Release impact:** none until explicitly gated and independently reviewed. **Reference:** `openai/math` is a methodological example, not proof of REMORA properties.

## 1. Purpose and threat model

Build a verifiable chain from *precisely scoped mathematical proposition* → model → machine-checked Lean proof → executable refinement tests → immutable evidence artifact → research-control matrix → bounded product claim. Target failures are: dispatch without applicable authority, replay of consumed lease, result relabelling, confusing execution reports with verified effects, and interpreting repeated correlated observations as independent trials.

**No claim that math proofs verify Python/TypeScript binaries, out-of-process isolation, key custody, or physical effects.** Existing federation-port/v0 remains unchanged. Proofs are not a replacement for cross-tenant, TOCTOU, concurrency, adversarial or deployment tests.

## 2. Baseline repository mapping (confirmed against uploaded REMORA source)

| Capability / boundary | Current code | Current tests / artifact | Correct scope |
|---|---|---|---|
| Lyapunov heuristics | `remora/lyapunov.py`, `remora/agent_hook/lyapunov_tracker.py` | `tests/test_lyapunov.py`, `tests/test_lyapunov_autonomy.py`, `results/lyapunov_aggregate_results.json` | Operational heuristic; drift/supermartingale premise **not established** |
| Anytime-valid Bernoulli inference | `remora/selective/confidence_sequence.py` | `tests/test_confidence_sequence.py`, `results/far_confidence_sequence_v1.json` | Offline only; overlapping episodes violate unproven independence premise |
| Governed authorization/dispatch | `remora/governance/`, `remora/enforcement/`, `remora/execution/` | Existing runtime/conformance tests | Code test evidence; NOT a formal proof |
| Federation authorization and report selection | `remora/federation/`, `integrations/federation-port/remora-adapter/`, `integrations/federation-port/remora-report-result/` | `tests/test_federation_bridge.py`, `tests/test_federation_report_selection.py` | V0 projections narrowed; runtime isolation **not established** |
| Research traceability | `docs/research/research_control_matrix_v1.yaml` | `scripts/generate_research_control_matrix.py --check`, `tests/test_research_control_matrix.py` | **Only existing implemented code and tests belong in the matrix** |

## 3. Required work packages

### FM-01 (P0) — Lean formal model of authorization and dispatch

New files: `formal/Remora/Authority/Model.lean`, `formal/Remora/Authority/Invariants.lean`, `formal/README.md`, pinned `formal/lean-toolchain`, `formal/lakefile.toml` and lock. Model states: `Proposed`, `Authorized`, `Consumed`, `Dispatched`, `Reported`, `EffectVerified`. Model action identity as (operation_id, principal, tenant, tool, typed canonical arguments digest, target, policy revision, toolspec digest, expiry). Make the boundary explicit: V0 authenticates only signed/projection fields; tenant label is not tenant identity.

**Theorems and adversarial cases:**
- FM-T01 `dispatch_requires_authority`: every modeled dispatch transition has valid, bound, not-yet-consumed authority immediately before dispatch (given transition guards).
- FM-T02 `consume_at_most_once`: no two modeled successful consume transitions share a single lease ID.
- FM-T03 `no_cross_subject_result`: a signed result about report A cannot establish report B without subject equality and digest binding.
- FM-T04 `reported_not_verified`: provider-confirmed transition does not imply `EffectVerified`.
- FM-T05 `refused_has_no_dispatch`: failed admission cannot produce dispatch in the same transition.
- FM-T06 `unknown_not_failed`: uncertain provider outcome is not rewritten into side-effect-free failed state.

Lean proofs MUST compile without `sorry`, `admit`, axioms added to bypass obligations, or hidden `unsafe` trust escapes. Pin mathlib/Lean revisions, record toolchain SHA and proof build manifest. Independently inspect assumptions (axioms are not bugs in general, but undeclared assumptions invalidate the claim). Use proof CI in a separate job, not a hard production gate initially.

### FM-02 (P0) — Refinement and correspondence to real code

Implement Python executable state model `tests/formal/model_oracle.py` and `tests/formal/test_refinement.py`; test trace projection against actual `ExecutionLease`, governed dispatcher, enforcement gate, federation result verifier where interfaces exist. Do not quietly mock the code under proof. Build explicit mapping `formal/refinement-map.yaml`: theorem ID → source module/function → executable test → counterexample fixture → limitation. Required 16+ new tests covering normal accept, wrong principal/tenant/target/toolspec/action, reused lease, parallel consume, expired grant, changed policy, wrong report subject, conflicting reports, and crash/retry. Tests must intentionally mutate preconditions and prove the oracle detects them. A formal theorem counts as **MODEL_PROVEN** only; Python-to-model correspondence stays **TESTED_REFINEMENT**, not code equivalence.

### FM-03 (P1) — Sequential assurance assumptions and bounds

Do not replace `remora/selective/confidence_sequence.py` without evidence. Add `experiments/formal_assurance/assumption_audit.py`, fixture `experiments/formal_assurance/overlapping_episodes.json`, and `tests/formal/test_assumptions.py` to flag overlapping observation IDs, temporal dependence, mixed epochs, reused ground truth and post-selected stopping. Contract: no numerical FAR confidence claim if prerequisite independent trials are **NOT_ESTABLISHED**. Where dependence is quantified, create distinct cluster-level estimands and test predeclared assumptions; do not reuse Bernoulli iid proof by relabelling cycles as independent. Compare confidence sequences against precommitted simulations and known edge cases.

### FM-04 (P2, optional research) — Lyapunov falsification study

Using `remora/lyapunov.py`, log trajectories, assumptions, selection bias and stopping. Check whether E[V(t+1)|history] <= V(t) holds on a predefined experiment; if not, publish the counterexamples and retain heuristic-only status. OpenAI StandardMap Lyapunov proof is about a different dynamical system, not a theorem about REMORA. No safety-gate change without independent holdout, ablations and rebenchmark.

### FM-05 (P2, optional research) — Adversarial state-game prototype

Finite attacker/controller/environment states; attacks: evidence substitution, replay, late conflicts, stale lease, misleading `provider_confirmed`; defender: ACCEPT, VERIFY, ABSTAIN, ESCALATE. Explicit costs and probability intervals; compare against exhaustive finite-state exploration. Do not transfer stochastic-game convergence guarantees without checking hypotheses.

## 4. Artifacts, schema and deterministic generation

Produce under `artifacts/formal-assurance/v1/<commit>/`:

- `manifest.json` (`remora-formal-assurance-manifest-v1`): git revision, Lean/mathlib lock digests, source/proof digests, test run IDs and counts, environment, UTC timestamp, local operator, source license attribution.
- `proof-results.json`: theorem id, status `MODEL_PROVEN | FAILED | NOT_EVALUATED`, assumption inventory, source pointers, compiler stdout SHA-256.
- `refinement-results.json`: theorem id, applicable runtime path, count, result and counterexample hashes; default `NOT_ESTABLISHED` on missing binding.
- `assumption-audit.json`: inference estimand, observation unit, independence/cluster/epoch status, overlap count and decision `QUOTABLE | NOT_ESTABLISHED`.
- `scope-boundaries.json`: nonclaims (runtime binary equivalence, completeness of credential surfaces, independent hardware evidence, authenticated tenant in V0, effect correctness).
- `checksums.sha256`: hashes of every file in canonical sorted order, excluding checksum file itself.

Create `schemas/formal-assurance-manifest-v1.schema.json`; a validator `scripts/validate_formal_assurance.py` must reject missing/duplicate proofs, wrong pin, unsupported status, noncanonical digest, missing assumptions, status promotion without a passing proof and impossible evidence paths. Add self-service runner `scripts/reproduce_formal_assurance.sh` with offline/lockfile mode; missing Lean or dependencies must emit `BLOCKED`, never `PASS`. Any direct CI links are provenance only, not independent verification.

## 5. Tests and security acceptance criteria

| ID | Acceptance criterion | Required independent test |
|---|---|---|
| FM-AC01 | all six Lean statements build under pinned versions | break a dispatch guard → proof or refinement fails |
| FM-AC02 | model has no unreviewed axioms/sorry | introduce `sorry` → CI fails |
| FM-AC03 | type/target/subject binding preserved | change int↔float, report id/digest, target → fail |
| FM-AC04 | lease consumed once | simultaneous attempts → max one success (subject to runtime atomicity) |
| FM-AC05 | explicit V0 limits | `tenant label` cannot become `authenticated tenant` in artifact |
| FM-AC06 | `provider_confirmed` != verified effect | adversarial provider response must not elevate effect claim |
| FM-AC07 | statistical units valid | reused episode ids → `NOT_ESTABLISHED` |
| FM-AC08 | deterministic artifacts | rerun fixed fixture, compare canonical hashes excluding run metadata |
| FM-AC09 | matrix grounded in code and tests | prospective `MODEL_PROVEN` with missing proof path rejected |
| FM-AC10 | no federation-port core modifications | compare pinned upstream `src/` before/after runs |
| FM-AC11 | safe failure | unavailable toolchain / failed build never emits PASS |
| FM-AC12 | no silent promotion | release/claim registers unchanged pending human evidence review |

Test counts are targets, **not presently passing results**. Hold a separate independent-run record before any `INDEPENDENTLY_ESTABLISHED` statement.

## 6. Research matrix, shelf, roadmap and docs update procedure

**Now:** record the proposal in `docs/13-research-frontier-roadmap.md` under a new RF-16 work package (RF-15 is referenced elsewhere: do not recycle). Add it to `docs/research/research_shelf_v1.yaml` only after verifying that schema's accepted fields, as `SCOPED`, not `ADOPTED`. Keep `docs/research/research_control_matrix_v1.yaml` as implemented-only: add NO RES entry for a merely proposed theorem. This SDD includes the matrix promotion contract; the generator should remain unchanged and green.

**Once code, proofs and tests exist:** add RES entry with `maturity: library_only` or approved equivalent, explicit `source`, `code`, `tests`, `evidence`, `boundary` following neighboring entries; then run `python scripts/generate_research_control_matrix.py` and `--check`. No runtime maturity promotion until the proved abstraction is connected to and tested against the governed path. Update `docs/09-related-work.md`, `docs/assurance/claim_register_v1.yaml`, `docs/assurance/capability_register_v1.yaml`, `docs/assurance/assurance_case_v1.md`, `docs/EVIDENCE_OF_CAPABILITY.md`, `NEGATIVE_RESULTS.md`, `paper/remora_paper.md` and `.tex` only with supported, scoped statements. Preserve falsifications and previous artifacts.

## 7. Reference literature and exact transferability

1. OpenAI, *Mathematical manuscripts and proof artifacts* (2026), https://github.com/openai/math (README, `lean/README.md`, `lean/formalization.yaml`). **Methodology/example only; not an REMORA proof**; repository warns unformalized work may contain issues.
2. OpenAI, `lean/OAI/Combinatorics/EditApproximation/Geometry/Regret.lean`, https://github.com/openai/math/blob/main/lean/OAI/Combinatorics/EditApproximation/Geometry/Regret.lean — finite telescoping/Bellman style proof; a methodological example, not a dispatch invariant.
3. OpenAI, `lean/OAI/Dynamics/StandardMap/EntropyLyapunov.lean`, https://github.com/openai/math/blob/main/lean/OAI/Dynamics/StandardMap/EntropyLyapunov.lean — Lyapunov/entropy formalization in another dynamical system; **not transferable directly**.
4. de Moura, Kong, Avigad, van Doorn & von Raumer (2015), *The Lean Theorem Prover (System Description)*, https://doi.org/10.1007/978-3-319-21401-6_26.
5. Howard, Ramdas, McAuliffe & Sekhon (2021), *Time-uniform, nonparametric, nonasymptotic confidence sequences*, Annals of Statistics, https://doi.org/10.1214/20-AOS1991.
6. Ramdas, Grünwald, Vovk & Shafer (2023), *Game-Theoretic Statistics and Safe Anytime-Valid Inference*, Statistical Science, https://doi.org/10.1214/23-STS894.
7. Lamport (2002), *Specifying Systems: The TLA+ Language and Tools for Hardware and Software Engineers*, https://lamport.azurewebsites.net/tla/book.html — alternative finite-state/temporal specification approach, not a Lean replacement.
8. REMORA internal: `docs/assurance/rebenchmark_protocol_v1.md`, `docs/interop/FEDERATION_BRIDGE.md`, `NEGATIVE_RESULTS.md`, `docs/research/research_control_matrix_v1.yaml`.

## 8. Release plan / done definition

Wave 0 (this patch): SDD, planned-roadmap cross-reference, documentation consistency test. Wave 1: six checked Lean properties and model counterexamples. Wave 2: runtime refinement tests; separate mismatch report. Wave 3: reproducible signed/digested evidence, negative corpus and research matrix promotion. Wave 4: external rerun on independent host, scope review. A PR may close each wave separately; Wave 0 does **not** justify adding new capabilities to claims or product messaging.

## 9. Addendum 2026-10-08: ordering, and mechanisms taken from comparable proof-artifact projects

**Counterexample first.** Wave 1 starts with a finite-state model that can
find faults (TLA+ checked with TLC or Apalache, Lamport 2002), not with a
Lean proof built to succeed. The model is validated against a fault already
known: federation-port contract probe CP-F1 (a late provider confirmation
lost when another worker took over an expired lease) must appear as a
counterexample of the model at the pinned revision, and must disappear in the
model of the patched runtime. A model that cannot find a known fault is not
evidence that an unknown one is absent. REMORA's own outbox carried the same
pattern (NEGATIVE_RESULTS.md §79), so the same model shape applies to both.
The Lean theorems of FM-01 follow for the properties the model checker has
already explored.

**Mechanisms adopted.** Six public proof-artifact projects were read on
2026-10-08 (repository contents through the GitHub API; no Lean project was
built). None runs CI for `sorry` or axioms; each check is a script someone
runs. Two have no licence file, so their designs are imitated and nothing is
copied.

| Mechanism | Seen in | REMORA form |
|---|---|---|
| Theorem statement in its own module, proof elsewhere, with a permitted-axiom allowlist checked against `#print axioms` | openai/math `lean/ComparatorChallenges/*.json`; lhl/ai-math-evidence | `formal/Remora/Statements.lean` frozen and hashed; build fails on any axiom outside `propext`, `Classical.choice`, `Quot.sound` |
| Manifest that states its own review status, default unchecked | openai/math `lean/formalization.yaml` (`review.status: unchecked`) | `proof-results.json` carries `review_status: unreviewed` until an independent run is recorded |
| Main result kept apart from supporting lemmas, with a scope note per result | openai/math `lean/docs/*.md` | One scope note per FM-T theorem: what it covers and what it does not |
| Checked tree and experimental tree, with written promotion criteria | stockedge/frontier-research `Experimental/README.md` | `formal/Experimental/` is never imported by the checked root |
| Several labels reported side by side, not a single grade; separate statement, proof, trust-base and provenance audits | lhl/ai-math-evidence `README.md` | MODEL_PROVEN and TESTED_REFINEMENT reported together, never merged |
| A skipped check is named as not verified | demonstrandum-research `verify_all.py --strict` | `BLOCKED` when the toolchain is missing (FM-AC11), never `PASS` |
| Dated verification record: toolchain, commands, output | lhl/ai-math-evidence `VERIFICATION.md` | The independent-run record that Wave 4 requires |
| Author-run kept apart from independent run | bonninr/awesome-ai-solved-math `CONTRIBUTING.md` | A producer run is never an independent run (as for the federation-port components) |

These projects are two to four months old and mostly single-author;
"independent" in some of them means a different AI model, not a different
person. They inform the artifact design; they are not prior art for any
REMORA property.
