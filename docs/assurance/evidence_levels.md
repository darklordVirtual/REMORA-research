# REMORA Evidence Levels Taxonomy

**Version:** 1.0  
**Date:** 2026-06-30  
**Implements:** docs/assurance/claim_register_v1.yaml schema field `evidence_level`

This taxonomy establishes the ordered evidence levels used in the REMORA claim
register. Levels are ordered from weakest to strongest. Each claim in
`docs/assurance/claim_register_v1.yaml` must carry exactly one level.

Do not promote a claim to a higher level without satisfying ALL criteria for
that level. Do not demote a claim without documenting the reason in
`NEGATIVE_RESULTS.md` or the claim register caveat.

---

## Level Definitions

### 1. `theoretical`

**Definition:** A claim derived from mathematical definitions, model assumptions,
or analytical argument, without empirical measurement.

**Criteria:**
- Claim follows from stated definitions or assumptions (A1–AN)
- Assumptions are documented alongside the claim
- No benchmark or simulation result is required
- May be verified numerically but the verification uses only symbolic/algebraic checks

**How to cite:**
> "Derived under assumptions A1–A4. See `remora/theory/`."

**Typical REMORA examples:**
- MaxEnt/Gibbs free-energy identity for the vote-space model
- Joint convergence bound (Thompson Sampling + adapter gradient variance)
- Scaling law formula for average regret

**Promotion path:** Promote to `internal_simulation` when empirical checking
passes in a synthetic environment.

---

### 2. `internal_simulation`

**Definition:** A claim measured within a deterministic synthetic or replayed
simulation environment. No external dataset; no live model calls.

**Criteria:**
- Artifact file committed to the repository
- Deterministic: running the script produces the same artifact
- No external API key, live network connection, or external model required
- Explicit caveat that simulation does not transfer to field deployment

**How to cite:**
> "Observed in deterministic simulator under this benchmark. No live tool calls."

**Typical REMORA examples:**
- Building-light demo split-action gating (`scripts/demo_building_lights.py`)
- AROMER replay arena accuracy (96-case curated arena)
- AII trajectory during seeding experiments (`NEGATIVE_RESULTS.md §4–§13`)

**Promotion path:** Promote to `internal_benchmark` when the result is locked in
a committed result artifact with a regression test.

---

### 3. `internal_benchmark`

**Definition:** A claim measured on a committed artifact-backed benchmark with
a regression test. Artifact is deterministic and on disk. Benchmark is internally
authored or curated.

**Criteria:**
- Committed result artifact (`results/*.json` or `artifacts/*.json`)
- Automated regression test that fails if the result changes
- Benchmark design is documented (N, split, signal, threshold)
- Caveats on in-distribution optimism documented

**How to cite:**
> "Supported on the committed benchmark artifact. Simulator-scoped; external
> replication pending."

**Typical REMORA examples:**
- FAR=0% on toolcall_benchmark_v2 (`results/toolcall_benchmark_v2_results.json`)
- 88.8% selective accuracy (in-sample) (`results/selective_n500_results.json`)
- 94.7% selective trust at 25% coverage (`results/selective_trust_curve_results.json`)
- Component ablation results (`artifacts/aromer/component_ablation_results.json`)

**Promotion path:** Promote to `regression_tested` when the result passes a
dedicated regression test AND a blinded/separated evaluation protocol.

---

### 4. `regression_tested`

**Definition:** A claim that has passed a dedicated regression test AND meets
stricter protocol requirements (blinded label separation OR historical corpus
re-evaluation). The result is protected against silent regression.

**Criteria:**
- All criteria for `internal_benchmark` met
- PLUS one of:
  (a) Blinded benchmark: labels separated from candidate actions at file level,
      AND gate receives no label-derived information, AND verified by invariant tests
  (b) Historical corpus re-evaluation: scenarios drawn from a prior documented
      failure mode, AND re-evaluated with the current system, AND exclusions documented
- Regression test explicitly named in claim register

**How to cite:**
> "Regression-tested: FAR=0% confirmed on blinded benchmark (leakage_free=True)
> AND historical corpus (167 documented false-accept episodes)."

**Typical REMORA examples:**
- FAR=0% on blinded v3 benchmark (`results/toolcall_blind_v3_results.json`, REM-009)
- FAR=0% on historical regression corpus (`results/false_accept_regression_v1.json`, REM-019)

**Promotion path:** Promote to `externally_benchmarked` when an independently
sourced dataset (external to the project) is used and the result replicated.

---

### 5. `externally_benchmarked`

**Definition:** A claim measured on an independent externally-sourced benchmark
dataset that was not designed or curated by the REMORA project.

**Criteria:**
- All criteria for `regression_tested` met
- PLUS: dataset is externally sourced (not authored by REMORA team)
- Dataset is publicly available with a citable reference
- Dataset was NOT present in REMORA's training corpus (external validity)
- Result is committed as an artifact

**How to cite:**
> "Measured on external benchmark [citation] (N=X). External validity: dataset
> not present in training corpus. Artifact: results/..."

**Typical REMORA examples:**
- FAR=0% on AgentHarm (arxiv:2410.09024, ai-safety-institute, N=208), REM-014
  (`results/external_benchmark_agentharm_v1.json`)

**Promotion path:** Promote to `independently_replicated` when a party external
to the REMORA project reproduces the result independently.

---

### 6. `independently_replicated`

**Definition:** A claim independently replicated by a party external to the
REMORA project, under a documented protocol, with no involvement from the
original authors in the replication run.

**Criteria:**
- All criteria for `externally_benchmarked` met
- PLUS: independent replicator identified (not author-adjacent)
- Replication protocol published
- Replication artifact committed or publicly accessible
- No author involvement in running the replication

**How to cite:**
> "Independently replicated by [party] on [date] under protocol [doc].
> Replication artifact: [path/URL]."

**Status in REMORA:** No claims at this level as of 2026-06-30.
This level is required for REM-021 (independent human review) to close for
behavioral claims; methodological review alone is insufficient.

**Promotion path:** Promote to `field_observed` when the result is observed in
a live deployment environment with real consequences.

---

### 7. `field_observed`

**Definition:** A claim observed in a real deployment environment with genuine
operational consequences (not simulation, not replay).

**Criteria:**
- All criteria for `independently_replicated` met
- PLUS: result observed in production or shadow-mode with real agent actions
- Deployment environment documented (architecture, operator, context)
- Adverse events and limitations documented

**How to cite:**
> "Observed in production deployment at [operator] over [period]. N=[X] real
> agent actions. Limitations: [..."

**Status in REMORA:** No claims at this level. REMORA is `SHADOW_ONLY` as of
2026-06-30. One production gate remains (REM-021, independent human review)
before any deployment outside shadow mode; REM-020 closed 2026-07-17 and
REM-022 closed 2026-06-30 with recorded deviation (REM-023).

**Promotion path:** Promote to `externally_validated` when an independent
external party formally validates the field result.

---

### 8. `externally_validated`

**Definition:** A claim that has been formally validated by an independent
external party with documented methodology, in a field or production context.

**Criteria:**
- All criteria for `field_observed` met
- PLUS: independent external validation report exists
- Validator has no conflict of interest
- Validation scope, methodology, and limitations documented
- Validator has signed a conflict-of-interest declaration

**How to cite:**
> "Externally validated by [party] on [date]. Report: [path]. Scope and
> limitations: [doc]."

**Status in REMORA:** No claims at this level. `externally_validated` is the
target level for production deployment certification. It is permanently
forbidden to use this label without a committed validation report from an
independent external party.

---

## Demotion and Downgrade Rules

A claim may be involuntarily demoted when:

1. A regression test fails (demote to at most `theoretical`)
2. A negative result is discovered that invalidates the measurement
3. An artifact is found to have used evaluation-only fields (M1-class leakage)
4. The benchmark protocol is found to have a construct validity violation

Demotions MUST be documented in `NEGATIVE_RESULTS.md` and in the claim register
caveat field. Do not silently remove claims; mark them `status: demoted` and add
the reason.

---

## Relationship to Claim Status Labels

The claim register also uses status labels from `docs/claim_register.md`:

| Status label | Typical evidence_level range |
|---|---|
| `externally_validated` | externally_validated |
| `internally_supported` | internal_benchmark .. regression_tested |
| `simulator_only` | internal_simulation .. internal_benchmark |
| `theoretical` | theoretical |
| `candidate` | theoretical .. internal_simulation |
| `failed` | any (claim tested and disproven) |

Use the `evidence_level` field (this taxonomy) in the machine-readable YAML.
Use the status label in README and paper text.
