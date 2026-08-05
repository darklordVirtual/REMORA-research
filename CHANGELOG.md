# Changelog

All notable changes to this repository are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project is
research-grade software; version tags mark review handoffs, not production
releases.

## [0.10.0] - 2026-07-25

### Licensing

- Changed the license for new REMORA versions to the Business Source
  License 1.1 (source-available). Licensor: Stian Skogbrott. No commercial
  use is permitted without a separate REMORA Commercial License and
  compensation agreed with the Licensor.
- Change Date 2030-07-25; Change License GNU GPL v2.0 or later (BSL's
  covenant requires a GPL-compatible change license).
- Added `LICENSING.md`, `COMMERCIAL_LICENSE.md`, `COPYRIGHT.md`,
  `TRADEMARKS.md`, `THIRD_PARTY_NOTICES.md`, and `LICENSES/BUSL-1.1.txt`;
  rewrote `NOTICE`; migrated ~400 source headers to
  `SPDX-License-Identifier: BUSL-1.1`.
- Historical versions prior to 0.10.0 keep the license terms they were
  actually distributed with; no new grants are made under those terms.
- Added `scripts/check_license_policy.py` as a CI gate against legacy
  open-source license metadata drift, and a contribution-licensing/CLA
  section to the contributing docs.

## [Unreleased]

### /v1/assess runs the semantic authority: envelope hashes go live (2026-08-05)

- SHELF-020 follow-up (paper abstract, third finding — mechanism side):
  `/v1/assess` accepts an optional `tool_call` block
  (`tool_name`, `arguments`, `intent_ref`, `untrusted_context`;
  `extra="forbid"` so semantic verdicts can never be smuggled in). With
  `REMORA_SEMANTIC_BUNDLE_MODULE` configured it runs the SAME authoritative
  context builder as `/v1/execution/assess` — the new shared
  `semantic_call_context()` in `servers/execution_api.py`
  (`build_full_observation` underneath; no endpoint assembles semantic
  fields by hand) — and records the results into the DecisionEnvelope:
  `tool_contract_bundle_hash` and `intent_authority_hash` now have a live
  producer (they were carried-but-never-populated), and `tool_args_hash`
  upgrades to the canonical execution/lease preimage when a concrete call
  is present. Response gains a `semantic` block mirroring the execution
  path; OpenAPI export and generated TS client regenerated.
- Honesty boundary, stated in code and shelf: on this question-based path
  the semantic verdicts are RECORDED for audit; the gate decision still
  comes from the engine pipeline. Decision impact of semantic verdicts on
  /v1/assess is a separate unshipped step, and discrimination through the
  wired path remains UNMEASURED until SAP v4 (no numbers cited).
- Tests: `tests/test_assess_semantic_wiring.py` (computed-hash recording,
  None-absence without bundle or tool_call, 422 on verdict smuggling,
  canonical args-hash binding); execution-path parity suite unchanged and
  green after the refactor.
### Cloudflare workflows guard on secret presence instead of failing red (2026-08-05)

- `sync-papers-to-r2.yml` failed hard on its first-ever run (the old
  paper-PDF auto-commit carried `[skip ci]`, so the sync trigger had been
  silently dead since creation; no repo Actions secrets are configured).
  Both it and push-triggered `deploy-aromer-worker.yml` now use the
  established presence-guard convention (`codegraph-index.yml`,
  `deploy-frontend.yml`): dependent steps skip with a visible
  `::warning::` annotation naming the consequence (stale public PDFs /
  stale live worker) instead of redding master.
- New static guard `tests/test_workflow_secret_guards.py`: unattended
  (push/schedule) workflows referencing `CLOUDFLARE_API_TOKEN` must
  contain a recognized presence-guard; `workflow_dispatch`-only workflows
  are exempt — there a hard failure IS the loud surface.
- Publishing to R2 / deploying workers from CI requires the maintainer to
  add `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` repo secrets.

### FT-13 slice 2: SDK documentation, external example, stability policy (2026-08-05)

- New `docs/sdk.md` (DOC-301): the stable-surface contract for
  `remora.sdk` — install, stability classification and deprecation policy
  (snapshot-gated surface, CHANGELOG-announced deprecations), the governed
  loop, public-symbol groups, error taxonomy, and an explicit list of what
  is NOT stable.
- New `examples/sdk_quickstart.py`: runnable external example driving the
  full governed loop through `remora.sdk` only — offline demo against the
  real ASGI app in-process (dev single-token mode, research tool registry,
  two personas: agent credential + reviewer credential), or remote mode via
  `REMORA_URL`. Shows the honest outcomes: evidence-free read ABSTAINs,
  prod write routes to review, the agent's self-approval is a typed
  `authorization_denied` refusal, the reviewer approves, execution
  dispatches, and the audit chain verifies.
- Smoke test `test_examples_sdk_quickstart_runs_clean` pins the example's
  outcome spread (ABSTAIN / VERIFY / refused self-approval / executed tool
  / valid audit chain) alongside the existing quickstart tests.
- Remaining FT-13 DoD criteria after this slice: clean-install wheel test
  exercising the sdk extra (CI workflow change, ships separately), async
  client, OpenAPI-generated transport, adapters, `remora.sdk.testing`.
### Paper PDF ships via PR, never a direct master push (2026-08-05)

- Fixed the red `compile` job on master: `compile-paper.yml` auto-committed
  the recompiled `paper/remora_paper.pdf` straight to master, which branch
  protection (PRs only) rejects with GH006. The refreshed PDF now ships as an
  auto-maintained PR on the `ci/paper-pdf` branch; merging stays a human
  decision. Known limitation (documented in the workflow): `GITHUB_TOKEN`
  PRs do not trigger required checks — close/reopen the PR or use the admin
  override.
- Added `tests/test_workflow_master_push_guard.py`: a static scan over the
  workflow YAML that fails on the two known direct-push mechanisms
  (`git-auto-commit-action` targeting master, explicit `git push` to master
  in run-steps). Declared-pattern guard, not an exhaustive proof; branch
  protection remains the runtime backstop.

### Research truth sync P0/P1: matrix and paper match the code (2026-08-05)

- External review (2026-08-05) found the control matrix lagging the code
  and four literature misattributions. RES-003 no longer claims CRC as
  implemented: retitled "CRC-inspired weighted empirical selective
  routing", `finite_sample_risk_control` removed, new maturity
  `empirically_evaluated_adaptation` (crc.py's own docstring is the
  authority); RES-008 reclassified `conceptual_translation_implemented`
  (governance translation, not the Hope architecture); RES-001 scope
  states the deterministic, binary policy-level PS/PN
  operationalisation. Regression tests pin all three.
- Paper (.md and .tex in lockstep): Cobbe et al. corrected to outcome
  verifiers ranking complete solutions (not process reward models);
  Kadavath et al. nuanced (promising self-knowledge, weaker calibration
  on novel tasks); Endsley 1995 attributed to situation-awareness
  theory (not "supervisory control levels"); the .tex-only claim that
  El-Yaniv & Wiener discuss softmax under covariate shift removed; two
  intro sentences claiming CRC as implemented reworded to CRC-inspired.
- `MixtureOfAgentsSynth` docstring: single-stage aggregation inspired
  by MoA, not an implementation of the multi-layer architecture; Wang
  et al.'s MMLU gains attributed to their setup, not this component.
- Queued from the same review (not in this change): RES-004 split,
  per-source `relationship` field, unique source ids + bibliography
  keys, function-level registration, bidirectional CI scan, generated
  .tex.

### FT-13 slice 1: `remora.sdk` — the third-party client surface (2026-08-05)

- New `remora/sdk/` package: `RemoraClient` (sync, httpx, remote mode),
  frozen wire-bound models (`ToolCall`, `AssessmentResult`,
  `ApprovalResult`, `ExecutionResult`, `AuditVerification`,
  `SemanticAssessment`, `AuditRef`) and a typed error hierarchy rooted in
  `RemoraError(code, request_id, retryable)`. `DecisionAction` is
  re-exported from the canonical policy enum — no parallel vocabulary.
  Covers assess → approve → execute → audit-verify against
  `/v1/execution/*`; no server contract changed.
- The public surface is snapshot-gated: `artifacts/sdk/public_api_v1.json`
  (regenerate with `scripts/export_sdk_public_api.py`) +
  `tests/test_sdk_public_api.py` fail CI on any unreviewed symbol change.
- New `sdk` extra (`pip install "remora[sdk]"`); models and errors import
  without httpx. 30 new tests, including the full review loop end-to-end
  through the SDK against the in-process ASGI app.
- Remaining for FT-13 (queued slices): async client, OpenAPI-generated
  transport layer, framework adapters, `remora.sdk.testing`, external
  quickstart example, semver/deprecation policy.

### Fasttrack definition-of-done enforced machinally in the register (2026-08-05)

- Maintainer review 2026-08-05: a fasttrack slice counts as delivered only
  when ten reusability criteria hold (single module/responsibility, no
  duplicated abstraction, documented public API, unit+integration tests,
  negative/failure paths, ADR on contract change, OpenAPI/schema updates,
  runnable external example, stability classification, clean-install wheel
  test). `docs/assurance/fasttrack_register_v1.yaml` now declares the
  criteria (`definition_of_done`, `dod_enforced_from`), and the new
  `tests/test_fasttrack_register.py` fails CI if an item is flipped to DONE
  without a per-criterion `dod:` evidence mapping (pre-enforcement gate0
  closures are explicitly grandfathered). The review's structural goal — a
  small stable SDK surface (`remora.core_api` et al.) separated from
  experimental/research namespaces — is tracked as FT-13 rather than left
  as prose.

### FT-01/02: lifecycle state machine as a committed model (2026-08-05)

- `schemas/execution_lifecycle_v1.yaml` declares the canonical
  proposal-to-effect states, legal transitions, terminal set and the
  maintainer's v1 decisions (synchronous execute, append-only envelope
  revisions, UNKNOWN as explicit terminal with manual+optional-probe
  resolution). Honestly scoped: assess/review/authorize stages are realized
  today (FT-01 slices 1–2); outbox states are declared AHEAD of FT-02 and
  claimed nowhere as wired; EFFECT_* states are deliberately absent until
  FT-04. Structural invariants pinned by
  `tests/test_execution_lifecycle_schema.py` (reachability, terminal-state
  closure, decision recording).

### FT-01 slice 2: the envelope path adopts the proposal identity (2026-08-05)

- `/v1/assess` now mints the same canonical `proposal_id` vocabulary as
  `/v1/execution`: one uuid4 is both the `proposal_id` and the
  `request_id`, and the stored DecisionEnvelope's request identity is that
  value. The former `q_hash-` prefix was informational only (nothing parses
  `request_id`; the question hash remains in `question_hash`). Additive:
  `AssessResponse` gains `proposal_id`.

### FT-01 slice 1: proposal_id threads the execution lifecycle (2026-08-05)

- Per the merged lifecycle design (PR #135) and the maintainer's contract
  decisions: `/v1/execution/assess` mints one canonical `proposal_id`,
  carried on the observation (surviving the durable review queue), returned
  in every response, stamped on every tenant-chain record (assessed,
  approved, execution_authorized, execution_result and refusal events), and
  set as the execution grant's `request_id`. Additive only: pre-lifecycle
  items report `proposal_id: null`. An external reviewer can now start from
  a proposal_id and follow the action across records without out-of-band
  reconstruction — envelope adoption, outbox states and effect verification
  are the next slices.

### Property-based invariant testing of the PEP one-time-grant contract (2026-08-05)

- Proof-depth slice 4 (`tests/test_gate_replay_properties.py`): a consumed
  grant refused every searched later attempt (replay counts 1–10,
  in-process) with `token_already_consumed`, and non-consuming checks never
  spent the grant. No counterexample in 50 examples per property, three
  seeds. Searched validation over the declared domain — cross-process and
  durable-ledger paths are not covered here.

### Property-based invariant testing of the review-queue TTL contract (2026-08-05)

- Proof-depth slice 3 (`tests/test_review_queue_properties.py`): across
  searched integer-hour TTL/advance combinations, one sweep expired exactly
  the overdue items to `EXPIRED_TO_ABSTAIN` — never a non-overdue one — and
  an expired item was never approvable afterwards. No counterexample in 60
  examples per property, three seeds; covers the public in-memory surface
  only (not the durable adapters, concurrency, or crash boundaries).

### Property-based invariant testing of the engine's hard-guard floor (2026-08-05)

- Proof-depth slice 2 (`tests/test_policy_engine_properties.py`): over a
  declared domain of seven signal groups (not the full PolicyObservation
  surface), no counterexample was found to the hard guards — critical risk
  never ACCEPTed, a production target with unknown risk never ACCEPTed, and
  a detected adversarial pattern always ESCALATEd (100 examples per
  property, three fixed seeds). Searched validation, not formal proof.
  hypothesis added to the dev extras/lock after the first property push
  revealed it was never installed in CI.

### Property-based invariant testing for the enforcement core (2026-08-05)

- New `tests/test_enforcement_properties.py` (Hypothesis) searches a
  declared generated domain (flat str/int/bool dicts, additive top-level
  mutations) instead of hand-picked examples: the tenant chain verified
  after every searched append sequence and detected every searched
  single-entry tamper; a lease refused the searched argument mutations with
  `tool_args_hash_mismatch`; an expired token never verified. No
  counterexample found; searched validation, not formal proof. First slice
  of the core-component proof-depth track.

### MCP session status emits the documented fields (2026-08-05)

- `remora_session_status` documented drift score, autonomy level
  (FULL/SUPERVISED/HUMAN_REQUIRED) and the consecutive-critical-phase count
  as outputs, but the handler emitted none of them although the tracker
  implements and tests all three. `LyapunovTracker.summary()` now carries
  `latest_drift`, `consecutive_critical` and `autonomy_level`, and the MCP
  handler prints them — the previously computed-but-unconsumed autonomy tier
  gains its documented reporting consumer.

### Hook G4: mutations meet the refusal regardless of risk tier (2026-08-05)

- In the production profile, file-writing tools (`Write`/`Edit`/`MultiEdit`/
  `NotebookEdit`) previously took the LOW fast-exit when the risk classifier
  scored the path LOW (unlisted extensions outside code directories) — a real
  mutation bypassed the documented G4 fail-closed refusal during a
  control-plane partition. Those tools now always reach the remote/G4 stage
  in production; read-only LOW tools keep the fast path, and the research
  profile is unchanged. Honest residual stated in the resilience plan:
  shell-borne mutations are covered only as far as the classifier scores
  them above LOW. The five hook env knobs are now documented.

### Assurance case: degradation-recording claim scoped to reality (2026-08-05)

- The G3 stop-argument asserted "mode degradation is always recorded" as
  implemented evidence, but `DegradationRecorder` has no production caller —
  the mechanism is built and tested, and no live path emits transition
  events. The assurance case now carries the same wiring caveat as the
  capability register (WIRED_REFERENCE_PATH): tracked integration work, not
  an implemented guarantee. Wiring the recorder into hook and control-plane
  link monitors is queued.

### AuditBlock.hash preimage documented per producer (2026-08-05)

- The `hash` field's docstring claimed one preimage; the two live producers
  compute different ones (server: chained SHA-256 over previous_hash + full
  envelope JSON; library: unchained state digest with a truncated question
  preimage — full arguments bound by `tool_args_hash`). The docstring now
  states both, and that verifiers must key the recompute on the producer.

### Policy layer: honest field status, unreachable reason removed (2026-08-05)

- Four `PolicyObservation` fields (`majority_support`,
  `rho_response_agreement`, `conformal_score`, `gainability_score`) are
  marked offline-analysis-only in the schema: always `None` from the live
  producer, read by no live decision path. `DecisionReason.CONFORMAL_VERIFY`
  removed — both conformal branches only ever emit ACCEPT or ABSTAIN, and a
  reason that cannot occur is contract noise. These edits move
  `policy_bundle_hash` (policy source files), by design.

### Library envelopes carry the measured policy identity (2026-08-05)

- `remora.assess_tool_call`'s envelope — documented as the canonical
  auditable record — shipped `policy_bundle_hash=None` and never used the
  full-argument `tool_call_hash` the observation already computed. Both are
  now populated exactly as the server path records them; the remaining,
  stated limitation is that library-path envelopes are unchained/unsigned.

### Security claims match the enforced mechanism (2026-08-05)

- `docs/08-security.md` credited "allowlist-only tool execution" to
  `schemas/risk-profiles.yaml` (`approved_tools`) — a key the runtime never
  reads. The enforced allowlist is the dispatcher registry (only
  deployment-registered callables execute; unknown tools refuse); the OWASP
  rows now cite that mechanism, and the risk-profiles header states which
  keys are read at runtime versus declarative policy intent. Editing the
  YAML moves `policy_bundle_hash`, by design.
- `policy_engine_audit_v1.md` F-4 scoped by path: server envelopes now carry
  the canonical bundle hash (closed); the library path
  (`remora/reporting.py`) still ships `None` and is named as the open half.

### Nonce failures are readable, refusals name the real cause (2026-08-05)

- `NonceLedger` recorded tool-failure reasons write-only; `failure(nonce)`
  now exposes them, and a retry after a tool that raised refuses with
  `nonce_consumed_by_failed_execution` (state unknown) instead of posing as
  a plain replay. The Swagger contract enumerates the refusal-reason sets
  and names their canonical sources (`lease.py`, `token.py`).

### Review-queue TTL→ABSTAIN is now reachable in the served API (2026-08-05)

- `ReviewQueue.expire_due()` existed and was tested, but nothing in
  `servers/execution_api.py` ever called it: an overdue PENDING item that no
  one touched stayed PENDING indefinitely, while the assurance docs claimed
  unattended items expire. Every queue interaction (assess enqueue, approve,
  execute) now sweeps overdue items to `EXPIRED_TO_ABSTAIN` first, inside
  the durable transaction. Docs restated precisely: a fully idle queue
  expires on its next touch; wall-clock idle expiry requires scheduling
  `expire_due()`.

### Contract honesty: EffectBlock relabeled, config gap closed (2026-08-05)

- `EffectBlock` on the canonical DecisionEnvelope was documented as
  decision-to-effect execution state, but no producer populates it: the
  envelope producer never dispatches, and the dispatching path records its
  outcome in the tenant audit chain without building an envelope. Docstring
  and API reference now say exactly that (reserved, unpopulated); wiring the
  outcome into the envelope is tracked follow-up work.
- `REMORA_MAX_TOOL_RESULT_BYTES` (result retention cap, default 65536,
  full result always hashed) was read by the code but missing from the
  execution quickstart's configuration table — added.

### Frontend: typecheck clean and CI-gated (2026-08-05)

- Fixed the pre-existing TypeScript errors (recharts 3.x Tooltip/Legend
  content-prop types, react-day-picker v10 `month_grid` slot rename, and a
  discriminated-union collapse in `benchmarks.tsx` — plus a latent React
  `key` bug in the chart tooltip that the typing exposed) and added
  `tsc --noEmit` to the verify job, so frontend type drift now fails CI.

### Typed OpenAPI contract for /v1/execution (2026-08-05)

- The four execution operations now carry documentation-typed response
  models (`ExecutionAssessResponse`, `ExecutionApproveResponse`,
  `ExecutionExecuteResponse`, `ExecutionAuditVerifyResponse`), closed enums
  for `decision` and `outcome`, a shared `ErrorDetail` model with documented
  401/403/404/409 statuses, and real operation descriptions — the contract a
  generated client needs instead of `Record<string, unknown>`.
- Deliberately attached via `responses={200: {"model": ...}}`, not
  `response_model=`: handlers keep returning plain dicts, so the wire format
  — conditional keys absent (never null), semantic booleans present even
  when null, timestamps as pre-serialized ISO strings — stays byte-identical.
  Pinned by `tests/test_execution_openapi_contract.py`.
- The contract is now a committed artifact: `schemas/openapi.json`, exported
  deterministically by `scripts/export_openapi.py` and drift-gated in CI
  (`--check`), so client generators consume a reviewed document rather than
  a runtime snapshot. Identity-shaped request fields document their
  unverified-metadata semantics, the pilot tokens are marked demo-only, and
  `ToolCallRequest` ships worked examples for Swagger try-out.
- Generated TypeScript client types: `frontend/src/generated/remora-api.ts`
  is produced from the committed contract by `npm run api:types`
  (openapi-typescript) and drift-gated in CI — a contract change that skips
  regeneration is a red build. Generated code is excluded from lint and
  covered by the frontend typecheck gate.

### Policy identity: API hash bound to the canonical policy source set (2026-08-05)

- `_policy_component_hashes()` in `servers/api.py` hashed only
  `decision_engine.py`, although `remora/policy/versioning.py` defines the
  canonical seven-file policy source set and promises full coverage. A change
  to e.g. `thresholds.py` could therefore move governance outcomes while
  outstanding leases kept verifying — and the audit trail kept recording —
  an unchanged policy identity. The composite is now bound to
  `compute_policy_bundle_hash()`.
- Consequence stated plainly: replaying envelopes recorded before this change
  reports `stable_policy_hash: false`. That is correct — the effective policy
  identity they were recorded under is not the current one.
- **F-03 slice 2 (#83):** the composite now also carries the effective
  tool-policy identity — the authoritative `TOOL_REGISTRY` metadata plus the
  spec and source digest of `REMORA_TOOL_REGISTRY_MODULE` and
  `REMORA_SEMANTIC_BUNDLE_MODULE` (resolved without importing; an
  unresolvable module is an explicit marker in the hash). Changing what a
  tool name means now refuses outstanding leases. `/v1/policy/version`
  exposes the new `tool_registry_hash` component. Residual under #83:
  registry signing, per-tool argument schema and credential scope.

### OT pilot: evidence archive and design-system console (2026-08-05)

- **Console UI is the frontend's design system, not a hand-rolled page.**
  The pilot console is a Vite SPA under `frontend/src/pilot/` sharing
  `styles.css` tokens, primitives and the component library with the main
  site (`npm run pilot:dev` / `pilot:build`). The console image builds it in
  a node stage; `app.py` serves the bundle and answers 503 with build
  instructions when it is missing.
- **Immutable evidence archive with retrieval.** Every battery run writes a
  run directory (manifest, results, metrics, chain verification, report)
  under `REMORA_EVIDENCE_ROOT`; the console exposes run history, manifest
  retrieval and zip download (`/api/evidence/runs[...]`) with strict run-id
  validation. Retention keeps the newest `REMORA_EVIDENCE_KEEP` runs and
  names every directory it prunes.
- **`GET /v1/execution/audit/verify` reports `records_checked` and `empty`.**
  An empty chain is trivially valid and must be distinguishable from
  verified history; the evidence bundle's
  `execution_chain_records_checked` field previously always recorded 0
  because the endpoint never returned a count.
- **Hardened pilot images.** Both pilot images run as uid 10001 with
  healthchecks and OCI labels; CI builds the pilot UI bundle so a frontend
  change cannot silently break the pilot's Docker build.
- **Evidence fidelity.** The bundle now maps the envelope chain's `breaks`
  into its problems lists (they were silently dropped), records the measured
  SHELF-020 semantic hashes instead of `None`, reports `dirty_worktree` as
  unknown rather than asserting clean, and the console run history shows an
  empty chain as `empty`, never as green proof.

### SHELF-020: semantic layer wired into /v1/execution (2026-08-04)

- **One authoritative context builder.** With `REMORA_SEMANTIC_BUNDLE_MODULE`
  configured, `/v1/execution/assess` and `/execute` build their observation
  through `build_full_observation` — the same function the routing benchmarks
  lock — over a deployment-declared `SemanticBundle` (tool signatures,
  contracts, validator bindings, state index). New module
  `remora/toolcall/semantic_bundle.py`; shipped research profile
  `servers/semantic_bundle_research.py`. Parity 4 in
  `tests/test_shelf020_parity.py` pins field-identity between the execution
  path and the builder.
- **Hashes computed, never declared.** `bundle_hash` (signatures + contracts
  + validators) and `state_hash` are derived from the declarations;
  constructing a bundle with an asserted hash refuses. Both are recorded in
  the assess audit record, and `bundle_hash` + `intent_authority_hash` bind
  into the `ExecutionLease` at execute time (fields added 2026-08-04).
- **Intent provenance enforced.** The request may carry only an opaque
  `intent_ref`, resolved server-side against a source declared in
  `docs/research/task_intent_authority_v1.md`; an inline intent or a
  `tool_matches_goal` assertion in the request body is ignored. New
  request field `untrusted_context` is downgrade-only (declares taint,
  never raises trust).
- **Honest absence preserved.** Without a bundle module the registry-only
  path runs unchanged and the audit record carries empty hashes; semantic
  fields stay `None`. Discrimination through the wired path is unmeasured
  (SAP v4 pending) — no accuracy number exists for it.

### DecisionEnvelope persistence and execution-state durability (2026-08-03)

- **Durable envelope storage.** Added `SQLiteControlPlaneStore`: until now the
  only durable control-plane backend was PostgreSQL, so any deployment without
  it stored every `DecisionEnvelope` in process memory and lost the whole
  audit trail on restart. Selected via `REMORA_CONTROL_PLANE_DSN=sqlite:…` or
  `REMORA_CONTROL_PLANE_DB=<path>`.
- **No silent volatility.** `/v1/metrics` and `/v1/policy/version` now report
  `control_plane_durable` and `execution_state_durable`, and a non-durable
  backend logs a warning at startup. The in-memory store is refused in
  production.
- **Verifiable trail.** Added `GET /v1/audit/chain/verify`,
  `remora.shadow.replay.load_envelopes_jsonl` / `verify_envelope_file`, and
  `scripts/verify_envelope_chain.py`, so a stored trail can be re-checked
  from disk by someone who was not present for the run. Previously the hash
  chain could only be verified in the memory of the producing process.
- **BREAKING (production deployments): durable execution state is now
  required.** `REMORA_ENV=production` fails closed unless `REMORA_PG_DSN` or
  `REMORA_CHAIN_DB` is set. Without one, the tenant audit chain, review queue
  and the PEP's consumed-jti ledger were all process-local, which meant a
  one-time execution grant consumed by one worker was accepted again by a
  second worker or after a restart. Regression tests:
  `tests/test_token_hardening.py::test_durable_ledger_refuses_the_replay_from_a_second_gate`
  (a second gate over the same ledger file, same process; no test spawns a new
  interpreter, so restart behaviour is inferred from the shared ledger).
- **Worker governance records.** `workers/agent-control` now writes a
  hash-chained `DecisionEnvelope` v2 per `/execute` (including refused calls)
  into new D1 tables, with `GET /envelopes`, `/envelopes/{id}` and
  `/envelopes/verify`. It previously stored only a call log with no decision
  contract and no predecessor linkage. The chain uses the REM-034 hash
  contract; cross-language agreement with Python is gated in CI by
  `tests/test_worker_envelope_chain.py`.
- **CI gates strengthened.** The shadow-replay smoke job now verifies the
  persisted chain and asserts that tamper detection actually fires, instead of
  only checking that output files are non-empty.
- Corrected the `NonceLedger` docstring, which claimed the same in-process
  limitation as `EnforcementGate`'s jti ledger; that ledger does persist when
  configured, while `NonceLedger` still has no durable adapter (REM-025).

### Reconciled with master; master's CI was red (2026-07-31)

- **Claim numbering.** Master had already merged CLAIM-014 ("system
  demonstration") and CLAIM-015 ("argument-value grounding"). This branch had
  independently registered different claims under the same two ids. Master's
  numbering wins — it merged first and is what other documents cite — so the
  duplicates from this branch are dropped and the one genuinely new claim, the
  **sealed BFCL blind track**, is registered as **CLAIM-016**. It is the only
  entry in the register carrying `blindness: blind`; master had no claim for
  that artifact at all.
- **`status` split into two fields.** Master used
  `status: development_measurement_not_blind`; this branch used
  `status: active | superseded`. One key was answering two questions, so
  `status` now means *is this claim current* and the new `blindness: blind |
  development` means *was it a blind evaluation*. A development measurement can
  be perfectly current; a superseded claim may well have been blind when made.
  The provenance gate validates both.
- **Master's own CI was red and is fixed here.** `ruff` reported 9 errors
  (unused imports, a multi-import line, trailing whitespace) across four files
  added on master, and `tests/test_evidence_verifier.py` failed on all three
  Python versions with `ModuleNotFoundError: No module named 'numpy'` — the
  local-NLI branch softmaxes with numpy, which ships with the `analysis` extra,
  while the deterministic job installs `[dev,causal,api]`. That test now
  `importorskip`s numpy: it covers an optional-dependency path, not a core one.
- Master's `cast()`-based mypy fix is replaced by the validating variant from
  this branch, for the reasons recorded in commit 4274aeb: `cast()` silences
  the checker without checking, and `.get("required_params", ())` would turn a
  missing required field into a signature claiming the tool needs no arguments.

### Build fix: mypy gate was red on the routing modules (2026-07-31)

- `ToolRegistry.to_json_dict` / `from_json_dict` were annotated
  `dict[str, dict[str, list[str]]]`, a shape the serialized form never had —
  `effect` is a string and `param_values` a nested map. Introduced an explicit
  `RegistryEntry` alias for the union the format actually admits, and narrowed
  each field on read. A malformed registry file now fails loudly at load
  instead of surfacing later as a routing decision made on a mistyped field.
- `serialize_snapshot(db: dict)` was being called with a task *list*. Split out
  `canonical_json_bytes(payload: object)` and had `serialize_snapshot` delegate
  to it; byte output is unchanged, so every committed snapshot hash still holds.
- `validator_study` carried the outcome through a filter that had already
  established its plan was present, then re-read the optional field. It now
  carries the plan itself.
- Added `types-PyYAML` to the `dev` extra. It was pinned in
  `requirements-lock.txt` but declared by no extra, so `-c` pinned a version pip
  was never asked to install and the CI mypy step failed on `import yaml` in two
  modules that pass locally.

### Superseded-result archive (2026-07-31)

- Every claim now declares `status: active | superseded`; a superseded claim must
  name the claim that replaced it. Nothing is deleted — CLAUDE.md forbids that —
  but a result the project has moved past no longer sits in the reader's path as
  if it were current.
- **CLAIM-004** (temperature-selective holdout) → superseded by CLAIM-012, the
  fresh-data round that falsified the signal. **CLAIM-008** (selective trust
  curve, 94.7% at 25% coverage) → superseded by CLAIM-013: the curve ranks on
  `neg_temperature` and 94.7% is a calibration-set upper bound, so it moved off
  the README front page into `docs/03-experiments.md`, anchored there.
- New `scripts/generate_superseded_claims.py` renders
  `docs/assurance/superseded_claims.md` from the register, with `--check` for CI;
  wired into `ci.yml`'s generated-doc drift step and into `make audit`.
- `check_claim_provenance.py` gains guardrail 5: status must be declared and
  valid, a superseded claim must name an existing non-superseded successor, and
  **no superseded claim may be anchored on the README front page**. The gate
  caught CLAIM-008 on the first run.

### README readability pass (2026-07-31)

- Rewrote the front page for a first-time reader: plain-language outcome table,
  results stated as what was measured rather than as metric names, and the
  jargon moved into a collapsible glossary. Negative results are linked, not
  front-loaded — the full record stays in `NEGATIVE_RESULTS.md`.
- Corrected the architecture diagram against `decide()`: the admission firewall
  sets `adversarial_detected` and suppresses the model fan-out (dotted edge) but
  does not issue the verdict — `hard_guard_floor()` does; the argument gates run
  *after* trust routing, not before; and the VERIFY → bounded lookup → re-entry
  loop is now drawn. Every node names the module or symbol it stands for, and
  line breaks use `<br/>` instead of `\n`.

### Claim coverage for the routing track (2026-07-31)

- Registered the tool-call routing track in the authoritative claim register,
  which previously stopped at CLAIM-013 while §19–§35 of `NEGATIVE_RESULTS.md`
  accumulated results with no register entry:
  - **CLAIM-014** (`externally_benchmarked`) — the sealed BFCL v3 blind track:
    four of five pre-registered targets met, the fifth (known-wrong-call
    ACCEPT 86.8% vs a ≤20% bar) missed and published as measured.
  - **CLAIM-015** (`internal_benchmark`) — argument value grounding, labelled
    **development measurement, not blind**, carrying the 86.8% blind record
    alongside the 11.6% development number so the two cannot be quoted apart.
  - **CLAIM-016** (`internal_simulation`) — declared validator bindings
    recovering read utility 0% → 100% in the UNKNOWN regime, plus the
    seven-condition degradation study, both scoped as mechanism studies.
- Added `tests/test_routing_claim_artifacts.py`: the sealed blind record is now
  pinned by CI (status, locked commit, holdout hash, all five target values), so
  an edit that quietly repairs the published miss fails instead of shipping.
- Added the six routing artifacts to `artifact_manifest_v1.md` under a documented
  addition note that distinguishes the never-regenerable blind record from the
  development artifact that is expected to move with the engine.
- Rewrote `README.md`: results lifted to the front, each with the caveat that
  keeps it honest and a link to the register entry governing it; a "Where it
  fails" summary pointing into `NEGATIVE_RESULTS.md` (which remains the sole
  home of the full negative record); corrected the architecture diagram to show
  the VERIFY → bounded resolver → router re-entry loop and the admission
  firewall's direct block edge; test count refreshed from ~3700 to ~4400.

### Statistical precision (2026-07-30) — SGR diagnostics and wording (issue #85 / review F-07)

- `sgr_threshold` on the rejected path now reports the **best (smallest)
  evaluated Clopper–Pearson bound** as `risk_bound`, matching the
  dataclass contract — previously it returned the *last visited* bound,
  which made the SAP v3 sidecar report temperature `risk_bound=0.99`
  when the best evaluated bound was ≈0.0844. Frozen artifacts keep their
  recorded values; the semantics note travels with the code.
- Docstrings and claim documents no longer describe the SGR result as
  "the largest acceptance set": the binary-search walk is optimal only
  under a monotone bound (with zero observed errors the CP bound
  *decreases* with coverage, so a larger passing set can exist that the
  walk never visits — pinned by a regression test with the review's
  counterexample). Certified=False now reads, everywhere, as "the
  pre-registered SGR procedure returned zero certified coverage", not
  "no coverage is certifiable". The CRC full-scan variant's "largest
  set" claim is correct and unchanged.
- SAP v3 Claim B: a certified-but-not-realized test outcome is
  investigated before being labelled a guarantee-assumption failure —
  the permitted δ event and ordinary sampling variation are acknowledged
  alternative explanations.

### Opt-in policy option (2026-07-31) — low-consequence ACCEPT

- **New `RemoraDecisionEngine(low_consequence_accept=True)`, off by default.**
  Default behaviour and `policy_version` are unchanged; a default engine
  produces byte-identical decisions to before.
- Motivation, measured on the routing benchmark
  (`results/routing_bench_v1_results.json`): ACCEPT recall was 0% in every arm
  except one that declared every action low-risk, which then accepted 88.5% of
  known-wrong calls. The cause is that every existing ACCEPT path requires an
  oracle-derived consensus signal, so a clean read-only call falls through to
  `default_safe_abstain`. Action semantics could only ever block; they could
  never permit.
- The path fires only on read-only `action_type` with no negative safety signal
  (untainted, not forbidden, valid schema, no adversarial/coercion/blackmail
  flag, no evidence contradiction, no distribution shift, not production). Every
  condition is written so `None` never satisfies it.
- It is placed immediately before the default abstain, after every hard guard
  and blocking gate, so it can only convert a fall-through and can never preempt
  a block. `tests/test_low_consequence_accept.py` asserts that over a grid of
  observations and re-checks the paths pinned by
  `tests/test_escalate_semantics_guard.py`.
- **What it asserts is consequence, not correctness.** The engine cannot tell a
  correct read from an incorrect one from observable data. Reports from this
  path carry a distinct `coverage_policy` rather than the generic ACCEPT
  wording, which would falsely claim an evidence/trust basis.
- **Measured.** Enabling it takes ACCEPT recall 0% → 75.0%
  (Wilson [70.0%, 79.4%]) and overall routing accuracy 18.5% → 44.5%, while
  ABSTAIN recall stays at the baseline 62.5% (see `arguments_satisfiable`
  below). Residual cost: 89 of 227 known-wrong calls accepted, all read-only.
  A deployment that cannot tolerate a wasted read must leave this off.

### New observation field (2026-07-31) — `arguments_satisfiable`

- **`PolicyObservation.arguments_satisfiable: bool | None`.** Can every required
  parameter of the proposed call be sourced — from the task, from a prior
  result, or from another available tool? Caller-supplied from a tool registry,
  like every other field; `remora/toolcall/routing/tool_registry.py` is a
  reference extractor that reads Python tool signatures by AST.
- The low-consequence ACCEPT path rejects a **confirmed** `False`. `None` is
  unknown and does not disqualify, so sources whose schemas have not been
  extracted keep working. Exported to OPA for parity; documented in
  `docs/07-api-reference.md` (58 fields).
- **This field replaces `blast_radius` as the fix for the ABSTAIN loss, on
  evidence.** An earlier note in this changelog proposed a disclosure or
  blast-radius signal. Inspecting all ten lost cases refuted that: they were
  `search_lat_lon` with no latitude obtainable, `timestamp_diff` with no clock
  available, `unit_conversion` with no amount to convert. `unit_conversion` is
  pure arithmetic — about as bounded as a call gets — and still wrong. The
  shared property is unobtainable arguments, not scope of effect.
- Effect: ABSTAIN recall in the enabled arm goes 0% → 62.5%, exactly the
  baseline, and known-wrong accepts fall 101 → 89.
- The registry now also covers tau2 (85 signatures, up from 38), which required
  extending the extractor to public methods of top-level classes — tau2 exposes
  its tools as methods on a domain class rather than as module functions. That
  extension gained coverage but moved no routing metric; see
  `NEGATIVE_RESULTS.md` §20 for why, and for the adapter artifact that briefly
  made it look like an 80.9% reduction in known-wrong call accepts.
- A required parameter already present in the proposed call counts as sourced.
  The check gates a proposed call, so a value already in it was obtained
  somewhere; whether legitimately is `argument_tainted`'s question. Without
  this, tau2's multi-turn tasks read as unsatisfiable because the value came
  from a conversation turn the single-call view does not contain.
- Extraction detail worth keeping: a parameter defaulted to `None` counts as
  required. `None` is the standard Python sentinel for "not supplied", so
  `search_weather_around_lat_lon(days=0, latitude=None, longitude=None)` needs
  coordinates even though all three parameters carry defaults. Treating them
  all as optional made an unsatisfiable call look satisfiable and left two
  cases unfixed until a test caught it.

### Policy behavior change (2026-07-31) — RemoraDecisionEngine-v5

- **Temperature ACCEPT now excludes the critical phase.** The marginal
  (phase-blind) conformal ACCEPT path has always carried an
  `obs.phase != "critical"` exclusion, because trust anti-correlates with
  correctness in that phase (ARCHITECTURE.md §8, CLAIM-005) and a phase-blind
  threshold would accept exactly the items most likely to be wrong. The
  temperature ACCEPT path is the same kind of phase-blind aggregate over the
  oracle distribution but was missing the guard, so a low temperature could
  silently override critical-phase VERIFY routing. Both paths now agree.
- This is a **tightening**: it removes an accept path, it does not add one.
  Measured effect on the N500 v3 round: temperature-calibrated coverage falls
  18% → 5.7% (31/544). Accuracy on the accepted set is asserted separately and
  is unaffected. `tests/test_end_to_end_n500_v3.py` is re-baselined to the
  3–10% band with the rationale recorded in the test.
- Engine `policy_version` bumped `RemoraDecisionEngine-v4` → `-v5`. The
  illustrative Rego policy has no temperature ACCEPT path, so there is no
  engine/OPA parity change and no new conformance golden case.
- Promoted benchmark artifacts remain v4 (and earlier) snapshots with their
  recorded provenance; regeneration under v5 follows
  `docs/assurance/rebenchmark_protocol_v1.md`. FAR-based claims are unaffected
  by construction — the removed path only ever produced ACCEPT, so any item it
  no longer accepts moves to a blocking outcome.

### Policy behavior change (2026-07-30) — RemoraDecisionEngine-v4

- **Tainted arguments at CRITICAL risk now ESCALATE** (new reason
  `tainted_argument_escalate`) instead of the approvable VERIFY floor —
  a reviewer can no longer wave through an unsanitized critical write
  (issue #40, option c; option b — sanitize + revalidate before approval
  is grantable — remains the tracked target state in #40). Non-critical
  tiers keep the established `tainted_argument_verify` floor unchanged.
- Engine `policy_version` bumped `RemoraDecisionEngine-v3` → `-v4`; the
  illustrative Rego policy and the OPA conformance golden set carry the
  same tier-dependent rule (engine/OPA parity pinned by a new
  `tainted_argument_critical` golden case).
- Promoted benchmark artifacts remain v3 snapshots with their recorded
  provenance; regeneration under v4 follows
  `docs/assurance/rebenchmark_protocol_v1.md` (both outcomes block
  autonomous execution, so FAR-based claims are unaffected by
  construction — the VERIFY/ESCALATE mix is what shifts).

### Refactoring & code hygiene (2026-07-29)

- **Engine decomposition recorded (commit 6213f1a / PR #68).** That squash
  commit's message described only the policy `thresholds.py` + `trace.py`
  extraction, but its diff also landed an engine decomposition that had been
  sitting uncommitted and was swept in by an over-broad `git add -A`:
  `remora/engine.py` slimmed (~1156 → 783 lines), with `remora/reporting.py`
  (`build_report`, dependency-injected report + `DecisionEnvelope` assembly;
  `Remora.report()` delegates to it) and `remora/state.py` (`RemoraState`,
  re-exported via `from remora.engine import RemoraState`) extracted from it.
  Behaviour was unchanged (full suite identical to the pre-refactor baseline).
  This entry and a `git note` on 6213f1a record the true scope; shared master
  history is not rewritten.
- **Policy value objects extracted (6213f1a).** The 12 heuristic decision
  thresholds → `remora/policy/thresholds.py`; `PolicyTrace` /
  `PolicyRuleEvaluation` → `remora/policy/trace.py`. Both were added to the
  hashed policy bundle (`versioning.py::_POLICY_SOURCE_FILES`); threshold
  values are unchanged and pinned.
- **Post-#68 hygiene sweep.** Removed a dead, divergent evidence-signal helper
  from `engine.py` (and its orphan import); renamed `reporting.build_envelope`
  → `_build_envelope` (removing a name collision with
  `assurance.envelope.build_envelope`) and added its type annotations; added
  dedicated `tests/test_reporting.py` + `tests/test_state.py` for the two
  extracted modules (previously transitively covered only); pinned the 12th
  heuristic threshold value; registered the new modules in the architecture
  docs and Module Stability Index; corrected the policy-bundle "Files covered"
  prose (6 → 7 files) and re-anchored the policy engine audit to symbol
  references; synced the paper `.md` abstract to the improved `.tex` (plus a
  "note on terminology") and refreshed stale Appendix D line counts.

### Security (workers/frontend hardening, 2026-07-28 — issue #55)

- **AROMER worker fail-closes all writes.** Every mutating (POST) endpoint
  (/episode, /outcome, /adapt, /critique, /decide, /scan-result,
  /replay-report) now requires `Authorization: Bearer <AROMER_WRITE_SECRET>`;
  with the secret unset the worker refuses all writes (503). Anonymous callers
  could previously overwrite episodes, set ground truth, poison world-model
  priors and forge replay-transfer provenance feeding the AII score. GET
  telemetry stays public. **Rollout:** `wrangler secret put
  AROMER_WRITE_SECRET` on the worker AND set it in every write client's env
  (the replay publisher now sends it; other operational scripts must too).
- **Frontend no longer re-exposes the control plane anonymously.**
  `executeTool` (store_artifact / audit_decision), `getAudit`, and the session
  functions now require an operator access token checked server-side against
  `REMORA_APP_ACCESS_TOKEN` (fail-closed: unset ⇒ control plane disabled).
  `verifyCloudflareToken` no longer returns the CF token id/expiry to the
  client.
- **agent-control audit is fail-closed after execution.** A failed final audit
  write now returns HTTP 500 (`AUDIT_WRITE_FAILED`) instead of a clean 200 —
  the governance record can no longer silently go missing. The `store_artifact`
  human-in-the-loop approval, which could never succeed (the approval hash
  included `audit_id`, so re-submission never matched), now hashes the input
  with `audit_id` excluded and works.
- **rag-oracle honesty + logic fixes:** documented that `clearance_levels` /
  `tenant_id` are caller-asserted (a scoping convenience, NOT an enforced
  boundary without an upstream authenticator); fixed the dead
  `ENABLE_DUAL_CONSENSUS` (`|| true` constant), the `legallov` router-regex
  typo, and the English "for" token that routed English queries to the
  multilingual index.
- **law-search:** LIKE wildcards (`%` / `_`) in caller citations are now
  escaped, closing a wildcard-injection that returned arbitrary rows.
- **Doc/config drift corrected to match code:** agent-control README no longer
  claims a nonexistent `EGRESS_ALLOWLIST`, `EOS` tool family / `EOS_API_KEY`,
  or an "append-only immutable" audit log (approvals are `UPDATE`s); the
  `go-star-remora` service binding is flagged as an external, non-reproducible
  dependency; personal machine paths replaced with `<repo-root>`.
- **Frontend telemetry "Pilot SLOs" tiles are labelled simulated** — they were
  hardcoded 100% / 0.00% literals reading as measured production posture, with
  no artifact binding.
- Remaining items needing coordinated rollout / an identity layer (real ABAC
  enforcement, egress-allowlist implementation, aromer worker tsconfig,
  frontend deploy-token scoping) are tracked in issue #55 follow-ups.

### Fixed (deep self-review, 2026-07-28 night — gates, provenance, portability, honesty)

- **Two `make audit` gates that could not fail are now real.**
  `scripts/_check_imports.py` printed `FAIL` lines but always exited 0;
  `scripts/render_claims.py` printed a fabricated "all dynamic numbers
  updated" success while doing nothing. The import checker now exits
  non-zero on any failure; the render stub is honest that it is a no-op and
  points at the gates that actually enforce number/artifact binding.
- **Follow-ups to today's own review fixes** (caught re-reviewing the diff):
  the N4 production role-pinning now uses the canonical `_is_production_mode()`
  so the `"prod"` alias is covered; the N1 SQLite rollback now also restores
  the in-memory queue/tenant mirrors (not just the DB row), and its test no
  longer masks the gap with a manual clear. Added the four missing
  behavioral tests (production role pinning, idempotency LRU eviction,
  oracle-proxy reliability fallback, adversarial-flag cache).
- **Do-not-silently-skip-failures enforced in more scorers:**
  `experiments/agentharm/score_guardrail.py` now degrades its artifact
  `status` to `degraded` and records dropped arms / log parse errors instead
  of emitting `status:ok` on partial data; `learning_ablation.py` raises
  when seed loading fails completely (was silently a cold-vs-cold "seeded"
  run); `check_no_evaluation_leakage.py` now fails on unparseable runtime
  files instead of excluding them while claiming full coverage.
- **Invented-result removed:** `balanced_validation.py` derived its
  diagnosis narrative from the measured values — the previous hardcoded
  string asserted a failure mode even on runs recording zero false accepts.
- **Provenance/portability:** `result_provenance.py` LF-normalizes the
  artifact hash to match the manifest protocol (Windows working trees
  diverged); the deterministic-round runner fails on missing declared inputs
  instead of dropping them from the sidecar; the live-round lock uses a real
  Windows existence probe instead of `os.kill(pid, 0)` (which would
  terminate the peer); `toolcall_blind_v3_eval.py` writes a POSIX artifact
  path; account-id-bearing base URLs are redacted in the AgentHarm preflight
  prints.
- **Coverage gate raised 60 -> 75** (actual coverage is 83%).
- **Hygiene:** personal `C:\Users\Stian\REMORA\...` paths in `mcp_test.py`
  and two hook docstrings replaced with repo-relative / `<repo-root>`;
  stale `bun.lock` references removed from `.prettierignore` and
  `codegraph.paths.ts`; dead `all_findings.txt` exemption removed from the
  docs gate; four missing modules (`evidence`, `uncertainty`, `graph`,
  `knowledge_domains`, `governance_intelligence`) added to the Module
  Stability Index.
- Live-surface security findings (unauthenticated AROMER worker, frontend
  control-plane re-exposure) and eval-integrity findings (stale
  `aromer_learning_ablation_v1` success artifact, seed-manifest arithmetic,
  `uncertainty/decompose` formula drift, vacuous multitenant leak check) are
  tracked in issues #55 and #56 — they need coordinated secret rollout /
  artifact regeneration, not a blind patch.

### Fixed (external code review part 2, 2026-07-28 evening — servers/enforcement/periphery)

- **N1 — SQLite transaction branch committed on exception.**
  `db_transaction_state`'s SQLite path ran INSERT+commit in `finally`, so an
  exception inside an execution-API handler persisted partially mutated
  review-queue state; the Postgres path already rolled back. The SQLite
  branch now mirrors Postgres semantics (rollback on exception, persist on
  success), pinned by `test_sqlite_transaction_rolls_back_on_exception`.
- **N4 — single-token auth mode: self-asserted role neutralised in
  production.** The `X-Remora-Role` header is caller-asserted; in
  `REMORA_ENV=production` it is now ignored (role pinned to `operator`), so
  approval-role gating cannot be satisfied by self-assertion. Docstring
  states plainly that single-token mode has no role separation; role
  separation requires the token-table mode.
- **N2 — idempotency cache bounded** (LRU, 10k entries) instead of an
  unbounded process-lifetime dict.
- **N5 — oracle-proxy evidence no longer reports `source_reliability=1.0`
  when no correlation model is supplied**; the uninformative fallback now
  reports 0.5 honestly (accept-gate behavior unchanged — strength already
  capped below the gate).
- **N6 — private cross-module import removed**: `REASON_TO_LABEL` is public
  in `remora/causal/explanation.py`; `counterfactual.py` imports the public
  name.
- **N7 — MetaJudge worker URL overridable** via
  `REMORA_METAJUDGE_WORKER_URL` (constructor argument still wins).
- **N8 — personal machine path** in the `mcp_remora.py` docstring replaced
  with a `<repo-root>` placeholder.
- **N9/N10 — frontend hygiene**: stale `bun.lock` removed (CI is npm-only);
  package renamed from the scaffold name `tanstack_start_ts` to
  `remora-frontend` in `package.json` and the lockfile.
- N3 (two tool registries that can drift) is the same problem as issue #38
  (unified ToolDefinition) and is tracked there, not patched piecemeal.

### Fixed (external code review round 2, 2026-07-28 — consensus identity and math hygiene)

- **F1 — verdict fingerprints no longer hash self-reported confidence.**
  `CanonicalVerdict.fingerprint()` previously included `magnitude`, which
  `_coerce_magnitude` populated from the oracle's `"confidence"` field; since
  free-text oracles practically never repeat a confidence value, identical
  claims landed in distinct consensus buckets, inflating entropy H and
  dissensus D and making `early_exit_on_convergence` near-unreachable.
  Identity is now (polarity, claim_hash, tags); the metadata-sensitive hash
  survives as `full_fingerprint()` (no consensus path uses it). NOTE: this
  changes live-oracle H/D/V dynamics from this commit forward. Committed
  benchmark artifacts retain pre-fix semantics and are frozen per
  `docs/assurance/rebenchmark_protocol_v1.md`; the next SHA-bound round runs
  with the corrected identity.
- **F2 — one authority for irreversible action types.** `remora/engine.py`
  (5 entries) and `remora/credal.py` (10 entries) each kept their own set, so
  the rollback heuristic and the credal worst-case-loss multiplier could
  disagree about the same `action_type`. Both now import the 11-entry union
  from the new leaf module `remora/action_semantics.py` — strictly more
  conservative in both consumers. Parity pinned by
  `tests/test_action_semantics.py`.
- **F3 — `potts_energy` docstring corrected** (formula and worked example
  carried a spurious factor 2 the code never had; code and committed
  artifacts unchanged).
- **F4 — zlib density clamped to 1.0** in `estimate_structural_temperature`
  and `estimate_temperature_prior`: zlib's fixed header pushed the raw
  compression ratio to ~5 for two-character prompts, inflating structural
  temperature for short trivial inputs. The prior's docstring no longer
  claims the raw ratio lies in (0, 1].
- **F5 — repo hygiene:** removed committed scratch files (`test_dc.py`,
  `fix_execution_api.py`, `all_findings.txt`) and the committed wheel build
  artifact; `*.whl` is now gitignored.
- **F6 — small fixes:** stale "removed in v0.7.0" deprecation wording in
  `remora/topology.py` (and, caught by the round-2 re-verification, the
  identical message in `remora/zkp.py`); `_normalize_risk_tier` docstring
  incorrectly listed "CRITICAL" as a value that becomes 'unknown' (case is
  normalised first); dead `_last` variable and duplicate `trajectory()` call
  in `Remora.report()`; coercion regex now compiled once at module level;
  the one Norwegian Makefile comment translated. The admission-firewall
  result is now cached on `RemoraState.adversarial_detected` (set once by
  `run()`; `report()` falls back to computing it for states built outside
  `run()`), removing the duplicate adversarial scan per report.

### Changed (documentation clarity and drift alignment, 2026-07-28)

- README front page rewritten for first-time readers: a "Key terms" section
  defines every abbreviation and benchmark concept in plain language; the
  negative headline results (temperature falsification, N544 holdout,
  critical-phase trust inversion) moved with their claim anchors to a new
  headline table at the top of `NEGATIVE_RESULTS.md` — moved, not removed.
- `docs/README.md` rewritten in English as the single authoritative
  documentation index, organized by reader goal; superseded documents are no
  longer linked (succession is tracked in the document register). Deleted the
  competing Norwegian `docs/INDEX.md` and its register entry.
- Aligned documentation with shipped code: the paper's wiring table now
  reflects the dispatched `/v1/execution/*` PEP path (wired 2026-07-27); the
  API reference scopes "caller-populated" fields to `/v1/assess` only; the
  documentation-governance spec now states honestly which checks are HARD vs
  ADVISORY; the nested-governance layer model matches the eight layers in
  `remora/governance/nested_governance.py`.

### Fixed (CI and governance tooling, 2026-07-28)

- The scheduled AROMER telemetry workflow pushed from a detached HEAD with an
  unqualified refspec and had failed every run since the telemetry-branch
  strategy landed; the push is now fully qualified and verified green.
- `run_docs_gate` (audit-gates API) previously ignored the historical-ban
  list it built and only ever matched one hardcoded filename, and its
  unregistered-document check was limited to a test-only filename prefix.
  It now enforces both checks generically, scoped to git-tracked files, and
  the formerly empty metatest asserts the unregistered-document failure.
- Committed the pre-SAP-v3 Groq-live N500 artifacts under
  `results/superseded_groq_live_2026-07-27/` with an explicit superseded
  notice and their provenance sidecars, instead of leaving them untracked.

### Changed (complete Apache-2.0 removal, 2026-07-25)

- Owner decision: remove every REMORA-authored reference to the Apache-2.0
  license so the whole repository points only to BUSL-1.1 / the REMORA
  Commercial License. Converted the demo banners, the AROMER master document,
  the HF dataset card, the knowledge/cyber dataset license notes, the archived
  infographic, and a claim-register snapshot to BUSL-1.1; dropped the optional
  "OPA (Apache 2.0)" phrasing from the paper acknowledgements; deleted the
  now-obsolete `scripts/migrate_license_headers.py`; deleted the
  `v0.9.0-apache-last` boundary tag; and reworded the enforcement-gate labels
  to "legacy-license drift".
- Deliberately KEPT (removing these would misrepresent third parties or break
  the ban's own enforcement): the third-party upstream license facts in
  `THIRD_PARTY_NOTICES.md` (OPA and TruthfulQA are genuinely Apache-2.0) and
  the Kubernetes-docs source license in the knowledge dataset manifest; the
  "Apache Jena" product name in `rdf_export.py`; Apache-software CVE content in
  the cyber-evidence dataset; and the Apache SPDX strings inside
  `scripts/check_license_policy.py`, which names them only to DETECT and forbid
  them. The license-policy gate confirms no REMORA-authored Apache metadata
  remains.

### Changed (Grok review P1 — calibrated vs heuristic thresholds, 2026-07-25)

- The hand-tuned decision thresholds (ordered-high-trust 0.72, evidence
  confidence 0.7, low-trust 0.2, minimax ambiguity width 0.15, env/session
  0.80, classification/misspecification 0.60, session count 100, policy
  generalization 0.70, similar-action flood 50) were promoted from inline
  magic numbers to named module constants in `remora/policy/decision_engine.py`
  under an explicit HEURISTIC section, with a header that separates them from
  the CALIBRATED thresholds (temperature T*≈0.1972, conformal) which remain
  constructor-injected from committed artifacts and are never hard-coded.
  Each heuristic constant is documented as hand-tuned and NOT artifact-backed
  (claim hygiene). Values are unchanged; `tests/test_policy_threshold_constants.py`
  pins each to its historical value and asserts the calibrated thresholds stay
  injection-only.

### Changed (Grok review P1 — decide/explain single source, 2026-07-25)

- The 25 uniform conditional policy gates (between the hard-guard floor and
  the ACCEPT tail) now live once in `_CONDITIONAL_GATES`;
  `RemoraDecisionEngine.decide()` returns on the first gate that fires and
  `explain()` records every gate from the same ordered inventory, so the audit
  trace can no longer drift from the decision when a gate is added. Behaviour
  is unchanged (each gate's predicate is self-contained). New
  `tests/test_decide_explain_single_source.py` locks decide/explain agreement
  across a broad battery. The hard-guard floor (already centralised in
  `hard_guard_floor()`), the two-phase schema-unverified handling, and the
  ACCEPT/VERIFY/ABSTAIN tail remain literal. Also documented that the
  non-ACCEPT `risk_estimate` values are relative labels, not calibrated
  probabilities (Grok review 4.4).

### Fixed (review round 3b, 2026-07-25)

- **R3-01**: the selective-risk component no longer claims the CRC theorem.
  `CovariateShiftCRC` → `WeightedEmpiricalSelectiveRouter` (alias kept); code
  and all three paper sources state why Theorem 1 cannot attach (threshold
  rule omits the B/(n+1) term; accepted-conditional loss is not monotone);
  `finite_sample_slack`/`nominal_risk_bound` are documented as informational
  reference values only. All evidence for the component is empirical.
- **R3-02**: `load_seeds()` resolves the episodes path once via
  `REMORA_AROMER_HOME`-aware `state_paths` and passes a concrete path to both
  golden-episode calls; the `Path.home()` fallback is gone. New end-to-end
  test imports the real seed packs under an override home.
- **R3-03**: the stale-claim guard now also scans
  `remora_mathematical_supplement.md`; the supplement's "hallucination-rate
  bound" wording is fixed to the false-consensus-proxy framing, its worked
  CRC example is marked illustrative-only, and the main paper's threshold
  direction ("minimises accepted items") is corrected to maximum coverage.

### Fixed (review round 3, 2026-07-25)

- **F-10 completed**: ALL AROMER default state paths now resolve through
  `remora/aromer/state_paths.py` at call time with `REMORA_AROMER_HOME`
  override — including `DomainHarmPrior` (previously a module-level
  `Path.home()`), the seed loader, the promotion ledger, and the friction
  optimizer; a new test exercises the full persistence graph under the
  override (fixes the four read-only-home failures the re-review found).
- **Paper honesty (second round)**: `h_bound` reframed as a heuristic
  false-consensus risk proxy (not a mathematical bound); χ OOD use marked
  exploratory; "Seven hard blocks" → seven headline controls with a pointer
  to the full gate inventory; λ=0.3 documented as paper config vs library
  default 1.0; remaining "no tagged release" text fixed.
- **Stale-claim CI guard**: `tests/test_paper_no_stale_claims.py` fails if
  superseded values or withdrawn formulations re-enter either paper source
  (caught one live leftover on its first run).
- **Postgres operational evidence**: new CI job runs the DSN-gated tenant-
  chain contract tests (including the F-04 HMAC signing test) against a real
  postgres:16 service and fails if they skip.
- **Request IDs**: full uuid4 hex suffix (was 12 hex chars).
- **Contributors**: Erlend Barli (erlendbarli) added to CONTRIBUTORS.md and
  the paper acknowledgements.

### Fixed (external paper-to-code review 2026-07-24)

- **Publication-blocking headline (paper .tex)**: the LaTeX source still
  carried the withdrawn tool-call numbers (baselines 10–20%, task-level
  Wilson [0.00%, 0.55%], "700 independent tasks"); abstract, results table,
  and conclusion now match the authoritative claim register (effective N=70
  clusters, cluster-level Wilson [0.0%, 5.2%], baselines 1.4%, safety delta
  not significant at p=0.50, significant gains utility +0.456 and accuracy,
  "unsafe acceptance" wording, no real side effects).
- **Implemented ≠ integrated**: implementation tables in both paper sources
  gained an "Integrated in /v1/assess" column; OPA, Governance Intelligence,
  PhaseAwareGuardrail, CRC, and the PVD-inspired score are labeled offline/
  adapter components; correlation weighting is marked per-request in the API.
- **CRC honesty**: `CRCReport.guaranteed_risk_bound` → `nominal_risk_bound`,
  `weighted_holdout_risk` → `holdout_risk`; docstrings state the Theorem-1
  guarantee does not attach under fixed-β phase-heuristic weights.
- **PVD reframed**: "PVD-inspired offline agreement score" (no training game,
  no live deliberation); Kirchner et al. citation corrected (was "Kirsch,
  Harrison, Misra, & Leike").
- **Audit wording**: envelopes are attribute-frozen (not deep-frozen);
  evidence records are hash-chained and HMAC-signed only when the signing
  key is configured; "deployable operating point" → "stable internal
  benchmark operating point"; undefined `fig:arch`/`sec:se` references fixed;
  paper version now cites tag `review-v1`. Tracked as REM-046.

### Fixed (external technical review 2026-07-24)

- **Actor binding enforced (F-02)**: an `ExecutionLease` issued to a named
  actor now refuses to verify/dispatch without a matching authenticated
  identity (`actor_identity_required` / `actor_identity_mismatch`);
  previously the actor was signed audit metadata a stolen lease ignored.
- **Token not-before (F-03)**: `PolicyDecisionToken.verify()` rejects tokens
  whose `issued_at` lies in the future (`token_not_yet_valid`), closing the
  path where a future-dated five-minute token was accepted for ~30 days.
- **Postgres audit signatures (F-04)**: `PostgresTenantChain.append()` now
  writes the HMAC signature in the same transaction, matching the SQLite
  contract; previously every entry verified as `signature_missing` once
  `REMORA_AUDIT_SIGNING_KEY` was configured.
- **Request-ID collisions (F-08)**: `/v1/assess` and `/v1/rerun` IDs use a
  uuid4 suffix instead of monotonic-milliseconds modulo 1e6 (repeated every
  ~16.7 minutes and could interleave audit records).
- **AROMER state path (F-10)**: default `~/.aromer` paths are resolved at
  instantiation with a `REMORA_AROMER_HOME` override, so locked-down homes
  no longer break the default-configured store/bridge.
- **Register honesty (F-09, F-01, F-05)**: REM-015 retitled to "captured
  development environment snapshot" (its old title promised uv.lock/SBOM/
  digests its own notes denied — REM-027 stays the only supply-chain gate);
  REM-035 now states that `/v1/execution/execute` consumes the grant without
  invoking a tool; new REM-045 records that the built wheel omits `servers/`
  and the Postgres drivers; the README architecture diagram marks "Execute"
  as the caller's step pending PEP integration.

### Fixed (REM-021 handoff consolidation)

- **Source-of-truth scoping completed**: the thermodynamics ledger
  (`docs/thermodynamics/claim_ledger.yaml`) and its credibility-pack copy no
  longer call themselves the overall "single source of truth"; the external
  review checklist now starts claim integrity from
  `docs/assurance/claim_register_v1.yaml`; the authoritative register is
  shipped in the credibility pack (`claim-register.yaml`); and the guard test
  scans YAML and pack files, not only Markdown.
- **AgentHarm register drift**: the remediation register no longer says
  "external validity guaranteed" or "10/10 gate tests";
  `scripts/run_agentharm_benchmark.py` is marked as a separate local protocol,
  not a reproduce artifact, in line with the imported-historical
  classification of CLAIM-002.
- **Stale-green hardening**: the committed (dirty-worktree) test attestation
  was removed from the repository and gitignored; the attestation workflow
  deletes any leftover attestation files before generating, so `if: always()`
  can only ever upload freshly generated PASS or FAIL files.
- **SHA-bound handoff**: the review-tag workflow now also builds the
  governance benchmark pack, verifies that the pack manifest `commit_sha` and
  the attestation commit equal `github.sha`, and uploads a single combined
  handoff artifact (`remora-review-handoff-<sha>`).
- **CONTRIBUTING.md / provenance spec**: removed self-referential
  "redirect stub" and duplicated-path text around `docs/05-claim-hygiene.md`.

### Fixed (external-review readiness)

- **CLAIM-005** critical-phase trust inversion is now backed by a committed,
  reproducible artifact (`results/critical_trust_split_v1.json`); the headline
  numbers were corrected to their aggregate-consistent values (low-trust 76.2%,
  high-trust 36.4% at the τ=0.10 boundary) across the register, docs, and paper.
- **Single source of truth**: `docs/assurance/claim_register_v1.yaml` is now the
  sole authoritative claim register; conflicting statements in companion docs
  were aligned and a guard test added.
- **AgentHarm (CLAIM-002)** reclassified as an imported-historical result with a
  structural verifier (`tests/test_rem014_external_benchmark.py`); the
  non-matching reproduce command was removed.
- **Reviewer pack** rebuilt with clean-dir builds, per-file SHA-256, commit SHA,
  and lockfile hashes; the stale task-level Wilson bound was replaced by the
  canonical cluster-level figure.
- **Review docs**: resolved the `enterprise/` catalog contradiction, made the
  stage-order review question testable, and fixed a dead evidence-and-claims link.

### Added

- CI-generated review attestation from a clean checkout
  (`.github/workflows/attestation.yml`, `--require-clean`).
- Dependabot configuration for pip, npm, and GitHub Actions.
- `CITATION.cff` and `CODE_OF_CONDUCT.md`.
- Theory roadmap proposals: value of information, optimal stopping.
