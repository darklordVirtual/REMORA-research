# REMORA Quality Program v1

Status: proposal, 2026-09-27. This specification plans work. Every capability
it names keeps the status the capability register gives it today, and no
requirement below counts as met until its acceptance test and artifact exist.

## 1. Purpose

REMORA has a strong governed-execution core and a much wider research surface.
The evidence behind the research surface is thinner than the process around it.
This program has three aims:

1. Make every committed result reproducible from the code at `HEAD`, or mark
   it explicitly as live or frozen.
2. Make the evaluation large and real enough to carry the claims REMORA wants
   to make about false accepts and multi-model behaviour.
3. Carry the governed-execution core from a reference path to a deployable,
   externally checkable product, closing the open gaps in the order that
   unblocks the most.

The method is spec-driven. Each requirement has an identifier, a testable
acceptance criterion, the artifact that proves it, and the gate that keeps it
proven. Work is done in the order of section 7.

## 2. Baseline

Verified on `master` at `85b4c97` on 2026-09-27.

| Area | Observed state | Source |
|---|---|---|
| Capabilities | 7 `WIRED_API_PATH`, 3 `WIRED_REFERENCE_PATH`, 1 `PERSISTED_ATOMIC`, 7 `IMPLEMENTED_LIBRARY`; deployment `SHADOW_ONLY` | `docs/assurance/capability_register_v1.yaml` |
| Remediation | 32 `DONE`, 6 `IN_PROGRESS`, 9 `NOT_STARTED` (among them REM-021, REM-025, REM-026, REM-027, REM-030) | `docs/assurance/remediation_register.yaml` |
| Committed results | 126 files under `results/*.json`; 45 are named by a test, check script or workflow. The CI job "Deterministic reproduction round" byte-compares the 11 files the 2026-07 round writes; nothing checks the rest. | `git ls-files`, `.github/workflows/ci.yml` |
| Known drift | `results/toolcall_benchmark_v2_live_results.json` (2026-06-25) no longer matches replay at `HEAD`. Unsafe executions: `verifier_model` 140 committed, 10 today; `REMORA_temperature_gate` 60 committed, 0 today. | PR #583 description |
| Multi-model baselines | All 700 `single_model_*` decisions per model in `artifacts/toolcall_live_cache_v1.json` are heuristic replay seeds; no live model answered them | cache `raw.source` |
| Harmful sample | Safety replay arena: 93 episodes, 48 harmful; the safety gate warns that 48 is below the 299 its own rule needs. The external AgentHarm run holds 208 harmful items, also below 299. | `make replay`, `scripts/check_safety_gate.py`, `results/external_benchmark_agentharm_v1.json` |
| Runtime surface | Completeness of the agent's callable tool surface is `NOT_ESTABLISHED`; RES-013 covers only REMORA's own opt-in reference runtime | capability register `unestablished_properties` |
| Package breadth | 57 top-level packages under `remora/`, classified CORE or EXPERIMENTAL in the Module Stability Index | `ARCHITECTURE.md` |
| Dated research instruments | `build_mixed_swarm` and `experiments/ablation.py` name `anthropic/claude-3.5-sonnet`, retired 2025-10-28 | PR #582 |

## 3. Scope

In scope: the evidence pipeline, the evaluation sets, the governed-execution
core and its runtime-surface extension, the MCP tool contracts, and the
maintainability of the package boundary.

Out of scope for v1:

- New research framings or new theory modules.
- Promoting any capability status without the evidence the register requires.
- Any production or externally-verified claim before REM-021 and REM-030 are `DONE`.
- Rewording frozen or pre-registered documents.

## 4. Requirements

Priority `P0` blocks everything after it. `P1` is the main body of work. `P2`
follows once its dependencies close.

### WS1. Reproducible evidence (P0)

| ID | Requirement | Acceptance criterion | Artifact | Gate |
|---|---|---|---|---|
| Q1.1 | Every committed `results/*.json` has a reproduction class: `regenerable` (deterministic, no keys), `live` (needs keys, carries a provenance sidecar) or `frozen` (historical, never regenerated). | A check fails on any results file without a class, and on a class that names no generator. | `docs/assurance/results_manifest_v1.yaml` | new `scripts/check_results_manifest.py` in the claim-hygiene CI job |
| Q1.2 | Every `regenerable` result is regenerated in CI and compared with the committed file. | A docgate test per generator; any difference fails with the changed keys. `scripts/evaluate_runtime_surface.py --check` is the model to follow. | generator `--check` modes | `pytest -m docgate` |
| Q1.3 | The known drift in `toolcall_benchmark_v2_live_results.json` is resolved without losing the old numbers. | The old file moves to the superseded archive with its date. The regenerated file carries a dated resolution note. Every claim that cited the old numbers passes claim review again. | superseded archive entry, claim-register update | `generate_superseded_claims.py --check`, `check_claim_provenance.py` |
| Q1.4 | A result states where each baseline's decisions came from. | Each `single_model_*` baseline carries `decision_source` with the value `replay_seed` or `live:<model>`. The claim gate refuses a claim that cites a `replay_seed` baseline as model evidence. | result schema field | `check_claim_metric_bindings.py` extension |

### WS2. Evaluation strength (P1)

| ID | Requirement | Acceptance criterion | Artifact | Gate |
|---|---|---|---|---|
| Q2.1 | The harmful set is large enough for the FAR claim the project makes. | At least 299 labelled harmful episodes. With zero false accepts this bounds the one-sided 95 % FAR at about 1 % (rule of three). The safety gate fails a FAR claim below that size. | extended replay arena, pre-registered SAP | `check_safety_gate.py` in strict mode |
| Q2.2 | The multi-model tool-call baseline is measured on live models. | One live run of benchmark v2 on at least three model families, using the model-keyed cache from PR #583, with provenance sidecars. The run reports refusals and unusable answers per model. | `results/toolcall_benchmark_v2_live_*` with `mode: live` | Q1.1 class `live`, `check_experiment_manifests.py` |
| Q2.3 | A held-out adversarial set is written and labelled by people outside the core authors. | Labels are frozen before the first REMORA run on the set; the SAP records the freeze commit. | held-out set, SAP | pre-registration check |
| Q2.4 | Instruments on retired models are either re-run or frozen. | `build_mixed_swarm` and `experiments/ablation.py` either move to current models as a new, dated round, or their results are classed `frozen` with the retirement noted. | results manifest entries | Q1.1 |

### WS3. Runtime surface and authority (P1)

These continue RES-013. None of them changes the global property from
`NOT_ESTABLISHED` until Q3.1, Q3.2 and Q3.3 are all met on a deployment.

| ID | Requirement | Acceptance criterion | Artifact | Gate |
|---|---|---|---|---|
| Q3.1 | An observer runs inside one external agent host and reports the tools that host offers the model. | For one named host, the observer's list matches the host's actual offered list in an integration test. An injected tool appears in the observation. The observation is signed with the runtime identity. | host adapter, integration test | new test module, coverage floor |
| Q3.2 | The observed surface is bound to the execution authority. | `ExecutionLease` carries the surface digest from assessment. Under the strict profile, dispatch refuses when the current digest differs. A shadow period first measures how often the digest changes on legitimate runs. | lease field, shadow metrics artifact | lease contract tests, `check_capability_freshness.py` |
| Q3.3 | Credential scope is observed from the credential issuer, not declared by the tool provider. | Each tool receives a scoped credential from an issuer REMORA can query. `verify_credential_scope` compares the signed spec with the issued scope, and the pinned no-caller test is updated with that evidence. | issuer adapter, updated pin | `tests/test_toolspec_bound_at_dispatch.py` |
| Q3.4 | Callable identity covers more than the source span. | The digest covers the module file and its resolved import closure, or the container image digest where the tool runs in a container. A dependency change fails verification. | digest producer | `test_surface_reference_integration.py` extension |
| Q3.5 | Surface and effect evidence survive a restart. | `SurfaceRuntime` writes through the SQLite or Postgres `TenantAuditChain` adapter. AST-011 moves to a durable adapter in the authority-state register. | adapter wiring | `check_authority_state_durability.py` |

### WS4. Production hardening (P2)

The remediation register already defines what `DONE` means for each item.
This program fixes only the order and the dependency.

| Order | Item | Why this position |
|---|---|---|
| 1 | REM-037 CI reproducibility and stricter gates | Hash-locked installs are the base for REM-027 and for trusting any regenerated result |
| 2 | REM-025 Durable audit integrity | Q3.5 and every effect receipt depend on it |
| 3 | REM-026 Database-enforced tenant isolation | Needed before any shared deployment |
| 4 | REM-027 Secure software supply chain | Builds on REM-037 |
| 5 | REM-030 Independent tool-interception validation | Tests WS3 from outside |
| 6 | REM-021 Independent human review | Reviews the claims after WS1 to WS3 have settled them |

### WS5. Focus and maintainability (continuous)

| ID | Requirement | Acceptance criterion | Artifact | Gate |
|---|---|---|---|---|
| Q5.1 | The governed-execution core is a separable product. | An import contract states that CORE packages in the Module Stability Index import no EXPERIMENTAL package. The wheel has a `core` install set that installs no research dependency. | import contract, packaging extra | new import-contract test, wheel-contract CI job |
| Q5.2 | EXPERIMENTAL packages show they are alive. | Each EXPERIMENTAL package names a test and either a result or a roadmap item. A package with neither for two review cycles gets an explicit keep or archive decision, recorded in `ARCHITECTURE.md`. | stability index column | `test_module_stability_index.py` extension |
| Q5.3 | The new runtime-surface modules meet the core coverage standard. | Per-package floors for `remora/toolcall/surface_*.py` and `runtime_surface.py`, set at measured coverage. | floors in `scripts/check_coverage_thresholds.py` | coverage job |
| Q5.4 | Retired model identifiers cannot enter live code again. | A check fails on a retired Claude, OpenAI or Gemini identifier outside frozen or historical paths. | retired-model list | new check script |
| Q5.5 | A local checkout gives the same test result as CI. | `test_module_stability_index.py` ignores directories that hold only `__pycache__`. `make bootstrap` documents the CI install set. | test fix, Makefile note | full suite green locally |

### WS6. Tool contract accuracy (continuous)

| ID | Requirement | Acceptance criterion | Artifact | Gate |
|---|---|---|---|---|
| Q6.1 | Every MCP tool parameter either changes what the handler sends or is described as echo-only. | A contract test per tool calls the handler with each parameter varied and compares the outgoing payload. PR #583 contains the first two. | contract tests | `tests/test_mcp_remora.py` |
| Q6.2 | Tool descriptions name no backend composition the handler cannot show. | The descriptions contain no fixed model names or counts unless the handler reads them from the response. | test on `TOOLS` | same |

## 5. Design notes

**Results manifest (Q1.1, Q1.2).** One YAML entry per results file: path,
class, generator command, and for `live` the provenance sidecar. The check
script reads the manifest and the tracked files and reports both directions:
files without an entry and entries without a file. Generators gain a
`--check` mode that renders to memory and compares with the committed file,
the same shape `scripts/evaluate_runtime_surface.py` already uses. The CI
deterministic round already byte-compares its own outputs; Q1.2 extends that
job to every other `regenerable` file instead of adding a second mechanism.
The manifest complements the provenance sidecars of
`artifact_provenance_spec_v1.md`: a sidecar records how one run was
produced, the manifest records how the file can be reproduced now.

**Decision source (Q1.4).** The benchmark writes `decision_source` beside each
baseline's metrics. The value comes from the cache entry's `raw.source` and
model. A mixed run, some tasks live and some seeded, reports `mixed` and
counts per source. That value fails Q1.4 for a model-evidence claim.

**Surface binding (Q3.2).** The digest is added to the lease as one more
signed field, optional in the research profile and
required in the strict profile. Shadow mode records digest changes with the
reason (registration, replacement, metadata) for at least one full evaluation
cycle before strict refusal is enabled. The false-alarm rate from that shadow
period goes into the capability caveat.

**Callable closure (Q3.4).** For in-process tools, hash the defining module
file and every module in its import closure that is inside the deployment.
For containerised tools, use the image digest the runtime reports. Both
digests are recorded; the signed ToolSpec names which one it expects.

## 6. Verification

| Stage | What is checked | By |
|---|---|---|
| Per requirement | Its acceptance test, and its artifact regenerates | the gate in its row |
| Per pull request | Full suite, ruff, mypy, docgate, claim gates, prose ratchet | existing CI |
| Per work stream | A dated resolution note in this document, with the commit | review |
| Program end | Section 8 metrics measured and recorded | results manifest |

A requirement that misses its acceptance criterion is recorded in
`NEGATIVE_RESULTS.md` with the measured value.

## 7. Order of work

| Phase | Contents | Starts when |
|---|---|---|
| A | WS1 complete; Q5.4, Q5.5 | now |
| B | Q2.1, Q2.2, Q2.4; Q5.1, Q5.3; Q6.1, Q6.2 | Q1.1 and Q1.2 are met |
| C | Q3.1 to Q3.5; REM-037, REM-025 | Q1.4 is met; Q2.2 has one live run |
| D | Q2.3; REM-026, REM-027, REM-030, REM-021 | C is complete on one deployment |

## 8. Success measures

| Measure | Baseline | Target |
|---|---|---|
| Results with a reproduction class | 0 of 126 | 126 of 126 |
| `regenerable` results verified in CI | none systematically | all |
| Labelled harmful episodes | 48 (replay arena), 208 (AgentHarm) | at least 299 in the set a FAR claim cites |
| Model families in a live tool-call run | 0 | at least 3 |
| Runtime-surface requirements Q3.1 to Q3.3 met on a deployment | 0 of 3 | 3 of 3 |
| P3 remediation items `DONE` among REM-021, REM-025, REM-026, REM-027, REM-030 | 0 of 5 | 5 of 5 |
| Local full suite equal to CI | 1 local-only failure | 0 |

## 9. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Regenerating results changes published numbers | Claims fall | Q1.3 route: archive, re-review, dated note; never a silent overwrite |
| Live runs cost money and hit refusals | Incomplete tables | Model-keyed cache and non-answer reporting from PR #583; a budget agreed per run |
| Surface binding refuses legitimate runs | Operators disable it | Shadow period with measured false alarms before strict mode |
| Process load slows delivery | Fewer improvements ship | Automate each gate once; no manual register edits that a script can check |
| Independent reviewers are unavailable | REM-021 and Q2.3 stall | Start recruiting in phase B |

## 10. Decisions for the owner

1. Which external agent host is first for Q3.1.
2. The budget for the live run in Q2.2 and which three model families it uses.
3. Whether the `core` install set in Q5.1 becomes the default distribution.
4. Who performs the independent review for REM-021 and labels the Q2.3 set.

## Resolution notes

**2026-09-28, Q1.1, Q5.3, Q5.4, Q5.5 (PR #585).** The results manifest is
measured: every generator was run offline in a clean worktree of `85b4c97`.
Outcome: 41 regenerable, 5 drifted, 12 live, 25 unverified, 22 frozen,
21 sidecars. `toolcall_benchmark_v1_results.json` no longer reproduces the
baseline numbers three claim-ledger entries cite; that review is Q1.3.
