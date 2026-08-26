# Rebenchmark Protocol v1 — Prerequisites for the Next Result Freeze

Status: **preconditions phase**; protocol fixes land first; no new headline
numbers are published until one clean, SHA-bound benchmark round has run.
Source: external research audit 2026-07-27 (five P0 methodological blockers,
all verified against code).

## Preconditions (before any rerun)

| # | Blocker | Fix | Status |
|---|---------|-----|--------|
| P0-1 | Doc/artifact mismatch (AROMER 87.5/96 vs artifact 0.871/93) | Docs corrected to artifact; hard bind added in `check_claim_consistency.py` | DONE 2026-07-27 |
| P0-2 | Author annotations (severity/tags) in the blind task surface; LLM baseline prompt leaked severity | Adapter neutralization + AST annotation tier + generator drop; baseline prompt fixed, N=100 pilot caveated | DONE 2026-07-27 (surface regeneration happens in the clean round) |
| P0-3 | Labels loaded in the decision process; hardcoded `leakage_free: True` | Two-phase decide/score protocol; leakage flag computed from the task surface | DONE 2026-07-27 (run the phases as separate processes in the clean round) |
| P0-4 | Inconsistent FAR/FBR denominators across scorers | Canonical metrics in [metric_definitions_v1.md](metric_definitions_v1.md); disambiguated keys emitted by scorers | DONE 2026-07-27 (docs re-quote at the clean round) |
| P0-5 | Holdout not pristine: in-sample signal/coverage, normal-approx "binomial", same-sample null | Exact binomial implemented; SAP deviations D-4/D-5 disclosed; clean-run requirements below | PARTIAL — statistical redesign executes at the clean round |

## Requirements for the clean round (SAP v2)

Pre-register, before any label is opened:

1. **Signal and coverage target** fixed in a committed SAP v2, not derived
   from in-sample analysis.
2. Group-based split: template/family/scenario-level groups, not just
   benchmark-source stratification (near-duplicate variants must not
   straddle the split).
3. Exact binomial (or group-stratified bootstrap/permutation), never a
   normal approximation at small N; the null baseline must not be computed
   from the evaluation sample itself.
4. Process isolation: decision job runs with no labels present
   (`toolcall_blind_v3_eval.py decide` in its own process/venv), scoring
   job joins by task_id, and an attestation step verifies hashes before any
   `leakage_free_verified` claim.
5. **Regenerated task surface** from `generate_blind_benchmark_v3.py`
   (severity/tags gone; simulator-generated context marked as such).
6. **Full provenance** on every artifact via
   `scripts/result_provenance.py`: git commit, worktree state, Python
   version, dependency-lock hash, input hashes, seeds, command.
7. Run from a **clean tagged commit**; update claim register, README, paper
   and manifest only from the new artifacts.

## Mandatory step when a re-run changes a number: retire the old one

Updating the claim register is **not** enough, and assuming it is has already
cost this repository once. On 2026-07-27 the SAP v2 clean round re-issued
`results/selective_n500_holdout_results.json`, retiring these figures:
N_accepted 25 → 18, accuracy 88.0% → 100.0%, coverage 23.2% → 16.7%, CI
[70.0%, 95.8%] → [82.4%, 100.0%], p 1.45e-5 → 0.052. The register was updated
the same day. Twelve documents, including `ARCHITECTURE.md`,
`06-reproducibility.md` and the paper, were not, and kept presenting the
superseded numbers as current until an audit on 2026-07-31 found them by hand.

The claim-anchor mechanism could not have caught it: anchors are opt-in, so
they only value-check paragraphs someone already remembered to bind. Prose that
quotes a number without an anchor is invisible to the gate.

**So: whenever a re-run changes a published number, add the old form of it to
that claim's `retired_values:` list in `claim_register_v1.yaml`, in the same
commit as the new number.** Write the strings as they actually appear in prose
(`"N_accepted=25"`, `"[70.0%, 95.8%]"`, `"23.2% coverage"`), including the
spacing variants you expect. Then run:

```bash
python scripts/check_claim_provenance.py
```

The gate fails once per occurrence and names the file and line, so the first
run **enumerates the blast radius for you**: every document that still needs
updating, in one list, at the moment of the change rather than months later.

Fix each hit one of two ways, and only these two:

- **Update it** to the current value. This is the default.
- **Mark the paragraph as a historical record** (the words "superseded",
  "retired", "historical", "outdated", "no longer" or "stale" anywhere in the
  paragraph satisfy the gate). Use this only where the point of the text *is*
  what a previous round measured: a peer-review finding as written, a
  superseded SAP, a worked derivation in the supplement. Never use it to avoid
  updating something that should have been updated.

Retired values are never removed once added: they are what stops a stale figure
being reintroduced by a later copy-paste.

## Re-run matrix

Everything below was last regenerated 2026-07-20 (commit 9c6eea0) or
earlier, while `remora/thermodynamics.py` (χ rewrite), `remora/engine.py`
and `remora/policy/` changed after that date:

- Toolcall blind v3 + v2 (+ LLM baselines pilot, contaminated prompt)
- Cluster significance, calibration, failure analysis, component ablation
- Governance-intelligence benchmark
- Selective N544 evaluation + critical trust split + Mondrian/repeated splits
- AROMER replay + learning ablation (if AROMER code changed)

## Cannot be rerun in this repository

- **AgentHarm N=208** (`external_benchmark_agentharm_v1.json`): imported
  historical result from the main implementation repo (commit `483d1b02`).
  This repo can only structure-verify it. Either reevaluate against current
  SHA in the correct environment, or keep it labelled historical/imported.
- **Historical false-accept corpus N=167** (`false_accept_regression_v1.json`):
  requires main repo, AROMER worker and D1 data (commit `27fe2a11`). Same
  choice: reevaluate in its environment or keep it labelled historical.

Until then, both remain what the manifest says they are: frozen, checksummed
snapshots protecting the promoted baseline, not evidence about current code.
