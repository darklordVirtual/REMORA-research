# Experiment Manifest Spec v1

Every experiment directory (`experiments/<name>/`) should carry an
`experiment_manifest.yaml`: lightweight, machine-checkable metadata that makes
exploratory work traceable **without** production-grade ceremony. A manifest
is a statement about an experiment's *lifecycle*; the strength of its
*results* is tracked separately, per claim, in
[claim_register_v1.yaml](claim_register_v1.yaml) using the
[evidence_levels.md](evidence_levels.md) ladder. Keeping these orthogonal is
deliberate: an experiment with FAR > 0 can be excellent research — the result
simply stays a candidate until promoted through the claim register.

Checker: `scripts/check_experiment_manifests.py` (runs in the
documentation-governance CI job). Malformed manifests fail HARD; missing
manifests and missing provenance sidecars are ADVISORY backlog.

## Required keys

| Key | Meaning |
|-----|---------|
| `experiment_id` | Unique id across all manifests (convention: `EXP-<NAME>-NN`) |
| `title` | One-line human title |
| `status` | Lifecycle status, see below |
| `hypothesis` | What the experiment tests, stated before results are read |
| `result_artifacts` | Repo-relative paths the experiment produces (may not exist yet — advisory) |

## Lifecycle statuses

| Status | Meaning |
|--------|---------|
| `exploratory` | Hypothesis forming; results are candidates only |
| `preregistered` | Decision rule frozen before any test-split data is seen |
| `in_progress` | Runs underway |
| `completed` | Runs done, artifacts final — positive **or negative**; negative results are first-class and are never deleted |
| `superseded` | Replaced by a newer experiment (name it in notes) |
| `abandoned` | Stopped; manifest stays, results stay candidates |

## Recommended keys

`baseline` (what the result is compared against), `policy_configuration`
(frozen thresholds/arms), `seeds` (or `seed_note` explaining why not),
`datasets`, `promotion_target` (a `CLAIM-*` id, or `none` — promotion runs
through the claim register and its gates, never through this manifest),
`known_limitations`.

## What a manifest does NOT do

- It does not make claims. README/paper numbers still require the exact
  result artifact and the claim-register gates (`docs/05-claim-hygiene.md`).
- It does not gate CI on experimental outcomes. A rising FAR inside an
  experiment is a *result* to report, not a build failure. Hard safety gates
  (REM-014/REM-019) protect the *promoted baseline artifacts*, which
  experiments do not touch.
- It does not replace artifact provenance sidecars
  ([artifact_provenance_spec_v1.md](artifact_provenance_spec_v1.md)) — the
  sidecar proves how an artifact was produced; the manifest states why.

## Example

See [experiments/agentharm/experiment_manifest.yaml](../../experiments/agentharm/experiment_manifest.yaml)
(pre-registration: [PREREGISTERED.md](../../experiments/agentharm/PREREGISTERED.md)).
