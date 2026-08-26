# Research Modes: Two Ladders, Kept Apart

REMORA separates **how mature a piece of research is** from **how ready the
system is to be deployed**. Both ladders already exist as machine-checked
registers; this page names the split so nobody re-derives it; and so nobody
concludes that research must clear deployment gates to exist in this repo.
It answers a recurring external-review suggestion ("split research maturity
from deployment readiness") by pointing at where each half already lives.

## Ladder 1 — Deployment readiness (system-level)

Defined in [release_profiles_v1.yaml](../assurance/release_profiles_v1.yaml),
recomputed by CI from the capability and remediation registers; the declared
profile cannot be raised by editing prose.

`RESEARCH_REFERENCE`, `SHADOW_PILOT` (= `SHADOW_ONLY`), `CONTROLLED_PILOT`,
`LIMITED_ENFORCEMENT`, `PRODUCTION`

The two hard safety gates required by `RESEARCH_REFERENCE` (REM-014
AgentHarm external benchmark, REM-019 historical zero-false-accept
regression) protect the **promoted baseline artifacts**. They are closed and
frozen; new experiments neither depend on them nor threaten them.

## Ladder 2 — Research/evidence maturity (per claim, per experiment)

Two orthogonal registers:

- Claims: each entry in
  [claim_register_v1.yaml](../assurance/claim_register_v1.yaml) carries an
  `evidence_level` from the ordered ladder in
  [evidence_levels.md](../assurance/evidence_levels.md)
  (`theoretical → … → externally_validated`). Only promoted claims may
  appear in README/paper/product statements.
- Experiments: each `experiments/<name>/` carries an
  `experiment_manifest.yaml`
  ([spec](../assurance/experiment_manifest_spec_v1.md)) with a lifecycle
  status (`exploratory`, `preregistered`, `in_progress`, `completed`, or
  `superseded`/`abandoned`). Negative outcomes are first-class results.

## What this means in practice

- An experiment with FAR > 0 is **a result, not a CI failure**. CI's
  zero-FAR gates regression-test the frozen baseline artifacts
  (`results/external_benchmark_agentharm_v1.json`,
  `results/false_accept_regression_v1.json`), not new work.
- The decision engine keeps exactly one authoritative semantics
  (conservative, fail-closed). Research questions about "what would the
  engine do without gate X" are answered in **shadow replay**, which carries
  ablation arms (`no_gate`, `policy_only_gate`, `no_hard_guards`,
  `hardblocks_only` in the AgentHarm harness); counterfactual data with
  zero enforcement impact. There is deliberately no "research personality"
  in the live engine.
- Promotion is one-directional: experiment to claim register (with artifact +
  provenance sidecar) → README/paper. The gates sit at promotion, not at
  exploration.

## Non-negotiables (unchanged by any of this)

No invented results; no tuning on test data; claims require artifacts;
negative results are kept; secrets stay masked (see [CLAUDE.md](../../CLAUDE.md)
and [05-claim-hygiene.md](../05-claim-hygiene.md)).
