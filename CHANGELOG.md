# Changelog

This file lists externally relevant changes by release. Fine-grained development history remains available in Git commits and pull requests; the pre-cleanup changelog remains recoverable from repository history rather than being duplicated as a current documentation artifact.

## Unreleased

### Security (hostile review 2026-10-08)

- A strict profile no longer dispatches on the in-process nonce ledger: a
  `GovernedToolDispatcher` without a durable nonce store refuses with
  `nonce_store_not_durable` before anything is recorded or consumed (H-01).
  The API path already used a durable store under strict profiles.
- `REMORA_LEASE_REVOKED_KIDS` revokes v2 lease signing keys by derived key
  id; their leases refuse as `lease_key_revoked` and stay readable as
  history (H-03).
- Tool-call arguments nested deeper than 64 levels are refused as a value
  error instead of exhausting recursion (H-06). No canonical form changes.
- Disposition of every finding:
  `docs/assurance/reviews/2026-10-08-hostile-review/DISPOSITION.md`.

### Interoperability

- Mutation check for the federation-port components:
  `integrations/federation-port/mutation_check.py` applies single-edit faults
  to each `adapter.ts`, reseals and re-signs the fixtures, runs the component's
  tests and fails on a survivor that is not listed with a reason in that
  component's `mutation-equivalents.json`, or on a listed entry that no longer
  survives. `reproduce.sh` and CI run it (`--skip-mutation` leaves it out).
  Its first run found 34 of 107 faults surviving the authorization
  component's 17 tests, among them a correctly sized wrong signature
  (NEGATIVE_RESULTS.md §78); 31 held-out tests close them. The run now reports
  152 of 152 federation-port tests (44 upstream, 48 and 60 REMORA), 102 of
  107 and 122 of 131 faults killed, every survivor listed as equivalent.
  No adapter bytes changed.
- `remora-research/report-result` refuses two signed results for the selected
  report that are not the same statement (`conflicting_results_for_report`).
  Before this the first of them decided the verdict, which the component's
  own description ruled out; the maintainer's mutation check of its test suite
  found it (NEGATIVE_RESULTS.md §77). Forty held-out tests were added to that
  suite, each selection case run on the component alone before the runtime,
  and `reproduce.sh` now reports 120 of 120 (44 upstream, 17 and 59 REMORA).
  The artifact digest changed and the manifest is resealed.
- New federation-port/v0 component `remora-research/report-result`
  (`integrations/federation-port/remora-report-result`). It gates a new action
  on REMORA's signed native result for one explicitly requested earlier report.
  Several reports without a request are refused. Its evidence keeps the
  selected report's identity and digest, the selection rule and the native
  result beside the claim status. The projection map exports
  `remora.report_result` as NARROWED, since V0 checks run before dispatch.
  LATE and LATE-CONFLICT are evaluated per report in an unmodified runtime, and
  `reproduce.sh` now reports 80 of 80 (44 upstream, 17 and 19 REMORA).
- `integrations/federation-port/remora-adapter/reproduce.sh` reproduces the
  adapter the way the other outside adapters on #177 do: installed into
  federation-port's tree at `92d5078`, sealed with its `scripts/seal.ts`, with
  `src/` checked unmodified, federation-port's suite and the adapter's tests
  in one run (61 of 61: 44 upstream, 17 REMORA), `tsc`, and REMORA's own
  acceptance suites reported separately as JSON. The CI job now runs that
  script. The adapter test also typechecks inside federation-port's tree.
- Federation results name the subject they are about (report-specific
  binding). A result now identifies its subject (operation, report, execution
  attempt or effect observation), how it was selected, and the native result
  with a bounded reason, signed together in `REMORA/FEDERATION-RESULT/v1`.
  Several eligible reports with no declared selector produce no result, and a
  result for one report does not verify for another. Projection records move
  to `remora-federation-projection-v2`; v1 records stay readable and are
  never read as carrying a report binding. Raised by Rul1an on
  aeoess/agent-governance-vocabulary#177 (LATE and LATE-CONFLICT). No
  federation-port core change.
- REMORA Federation Bridge and a federation-port/v0 adapter
  (`docs/interop/FEDERATION_BRIDGE.md`). `remora/federation` projects
  REMORA's native claims onto a federation transport as PRESERVED, NARROWED,
  NOT_ESTABLISHED or UNSUPPORTED, from a versioned projection map and the
  transport's capability declaration, and a projection only weakens a claim.
  Over federation-port/v0, exact-call binding exports only the narrower
  `remora.port_v0.bound_action` and expiry only `remora.authorization_unexpired`;
  principal binding, custody isolation and effect verification are not
  exported, and `provider_confirmed` never becomes `EFFECT_VERIFIED`. The
  adapter (`integrations/federation-port/remora-adapter`) verifies REMORA
  evidence signed in `REMORA/FEDERATION-ACTION/v1` and runs in CI inside an
  unmodified federation-port runtime at a pinned revision.

### Security

- Effect verdicts state their vantage and scope (CR-008). Every effect
  verification record, the `/proposals/{id}/effect` response, the lifecycle
  report, the envelope ledger and the SDK view carry `vantage`
  (`same_deployment`) and `scope` (`declared_delta_only`), so
  `EFFECT_VERIFIED` cannot be read as independent confirmation that nothing
  else changed. `independent` is only derived from an `ObservationVantage`,
  never asserted. Older records are reported with the vantage the recorder
  admitted, marked `vantage_recorded: false`.
- The Workers refuse numbers they would change (CR-013). mcp-gateway's
  JSON-RPC endpoint and agent-control's execute endpoint read the raw body
  and refuse an integer beyond 2^53−1, a float literal JavaScript would write
  as an integer (`1.0`, `1e2`) and a literal too large for a double, instead
  of forwarding the converted value for REMORA to bind. **Breaking** for
  callers that send such values: send them as strings.
- The runtime wheel no longer ships the generated benchmark datasets
  (CR-014). `remora/benchmarks/extended_v2.py`, `extended_v2_n500.py` and
  `sap_v3_n1200.py` (1.5 MB of inline items, imported by nothing at runtime)
  stay in the source tree and the sdist for research use. A test and the CI
  wheel job refuse a shipped dataset or any dataset-sized module. Import them
  from a source checkout.
- A strict v2 deployment can execute end to end (security programme stage
  I). Running the `remora init-review` scaffold as three real processes
  found that no runtime was bound into a lease without an execution context
  provider, so a strict executor refused every call
  (`runtime_identity_undeclared`). The authority now signs its own declared
  runtime (`REMORA_RUNTIME_*`) into the lease when there is no execution
  context; an undeclared runtime binds nothing, as before. The scaffold now
  declares one shared runtime, names the authority's execution endpoint, and
  gives its human reviewer the `senior_authority` role its demo tool's risk
  tier requires. `tests/test_strict_v2_three_domain_e2e.py` runs the three
  processes and attacks them.
- A strict authority can forward to its execution domain. The API built the
  tool dispatcher before deciding whether to execute locally or forward, and
  building it registers the registry's callables, which custody refuses in the
  authority domain. A strict authority therefore raised `CustodyViolation` on
  every dispatch. It now builds the dispatcher only when it executes locally.
  Found while mapping the MCP execution surfaces.
- Signature format v2 for the tenant audit chain (CR-011, C3). v1 entries
  are never re-signed. The first v2 append writes an
  `AUDIT_VERSION_TRANSITION` record naming the final v1 head and
  `REMORA/AUDIT/v2`; from it on every entry is signed `v2:` + HMAC over the
  tagged entry hash, and a chain never goes back. The verifier reads each
  entry's era from the chain's structure; misplaced v1 or v2 signatures and
  repeated or malformed transitions are findings, checkable without the key.
  `verification_statuses` adds `signature_format`. Memory, SQLite and
  Postgres chains.
- Signature format v2 for PolicyDecisionToken (CR-011, C2). Token v1 (HMAC
  over untagged canonical JSON) is frozen. v2 signs
  `REMORA/POLICY-GRANT/v2 || 0x00 || payload` with `format: v2` inside the
  signed payload, so it cannot be relabelled as v1. A strict v2 contract
  issues only v2 and refuses a v1 token as live authority
  (`token_format_legacy`); `PolicyDecisionToken.verify_historical()` reads
  v1. The key stays symmetric: v2 is domain separation, not the
  decision/enforcement boundary of RMR-CR-002.
- Signature format v2 for ExecutionLease (CR-011, C1). Lease format v1
  (`ed25519`, `hmac-sha256`, untagged) is frozen with golden vectors in
  `vectors/v1/`. Format v2 (`ed25519-domain-v2`) signs
  `REMORA/EXECUTION-LEASE/v2 || 0x00 || payload` and names its key by the
  derived key id. A strict v2 contract issues only v2, requires the Ed25519
  lease seed on the authority, and refuses a v1 lease for dispatch
  (`lease_format_legacy`) before the nonce is spent; v1 stays readable as
  historical evidence (`ExecutionLease.verify_historical()`). Elsewhere v1
  stays the default; `REMORA_SIGNATURE_FORMAT=v2` opts in. **Breaking** for
  strict v2 deployments: cut over after one lease TTL. Design:
  `docs/design/signature-format-v2.md`.
- Mandatory effect mediation under the strict v2 contract (CR-005). ToolSpec
  schema version 3 adds the signed fields `effect_mode` (MEDIATED | NONE) and
  `credential_policy.direct_effect_credentials`. `effect_mediation` is a core
  binding: a spec with no stated mode, a MEDIATED tool registered unmediated,
  a NONE tool that declares capabilities or is not read-only, and an executor
  that holds effect credentials (no `REMORA_EFFECT_ENDPOINT`) all refuse, at
  startup, at registration and at dispatch before the nonce is spent.
  `remora init-review` now writes three domains (authority, executor, effect)
  with a mediated demo tool and a capability policy. **Breaking** for strict
  v2 deployments: re-sign bundles as schema version 3 with an effect mode,
  register write tools mediated, and move effect credentials to an effect
  domain, or select `review/v1` explicitly. Whether a deployment's effect
  credentials are unreachable outside the mediator stays NOT_ESTABLISHED.
  Design: `docs/design/binding-policy-v1.md`.
- BindingPolicy and versioned strict contracts (CR-006, A2). `review` and
  `controlled_pilot` are now contract v2 (`review/v1` stays selectable
  explicitly and is recorded as legacy). v2 requires `REMORA_BINDING_POLICY`,
  which states every binding as REQUIRED, NOT_APPLICABLE (per read-only tool,
  for `resolved_effect` only) or UNVERIFIABLE (declared gap, non-core only).
  A missing binding, or a REQUIRED one without its comparator, refuses
  startup, and a strict profile now refuses at API import rather than on the
  first request. At dispatch every REQUIRED binding is compared before the
  nonce is spent. `remora init-review` writes a policy and a closed effect
  registry for its demo tool. `EnforcementGate.enforce()` is deprecated.
  **Breaking** for strict deployments: add a BindingPolicy, or select
  `review/v1` explicitly. Design: `docs/design/binding-policy-v1.md`.
- The runtime-surface binding is active on the API path (CR-006, A1). Every
  lease the API mints signs the signed execution surface (pinned bundle digest
  and every spec's tool id and hash), and the dispatcher compares it with the
  surface it actually offers. Under a strict profile a tool registered on the
  executor that the signed contract does not describe refuses every dispatch
  (`surface_changed`), and a lease naming no surface refuses
  (`surface_unbound`). Outside strict profiles the comparison runs in shadow.
- ToolSpec trust is asymmetric and pinned under strict profiles (RMR-CR-001).
  `review` and `controlled_pilot` require `REMORA_TOOLSPEC_VERIFY_KEYS` and
  `REMORA_TOOLSPEC_PINNED_DIGEST`, refuse HMAC-signed bundles, and refuse a
  runtime that holds `REMORA_TOOLSPEC_SIGNING_KEY`. Bundles are signed offline
  with Ed25519 (`python -m remora.toolcall.toolspec_sign`); the signer is
  named by its derived key id, so a label cannot impersonate another key.
  **Breaking for strict deployments:** re-sign and pin before upgrading.
  Contract: `schemas/toolspec_signing_ed25519_v1.yaml`.
- `remora.crypto`: domain-separated Ed25519 signing, the foundation for
  RMR-CR-011. No other artifact uses it yet.
- The tenant derives from the credential (RMR-CR-003). `REMORA_ENV` has one
  reading (`remora.profiles.deployment_environment`): development or
  production, and any other value, such as `staging`, refuses startup.
  Single-token mode is development only. A token-table credential's tenant
  cannot be widened by `X-Remora-Tenant` (403). Strict profiles require
  `REMORA_API_TOKENS`; `remora init-review` now writes a token table with
  separate operator and reviewer credentials. **Breaking** for deployments
  that ran single-token mode outside development or set another
  `REMORA_ENV` value.
- Separation of duties on the execution API (RMR-CR-004). Under a strict
  profile, or with `REMORA_REQUIRE_DISTINCT_APPROVER`, `/v1/execution/approve`
  refuses with 403 when the approver is the principal that proposed the call,
  whatever its role (`approver_is_proposer`), or when the proposer cannot be
  established (`proposer_unknown`). The `approved` event records both
  principals. Previously one `admin` credential could propose, approve and
  execute the same call.
- One failure outcome for every consumed-grant ledger backend (RMR-CR-015).
  A Postgres or SQLite outage used to escape the gate as an exception, with
  no `grant.checked` event and no refusal record; it is now the named refusal
  `consumed_ledger_unavailable` that D1 already used, with a
  `grant.ledger_unavailable` event naming the backend. A grant whose write
  never committed stays unspent. D1 also names read timeouts and malformed
  answers.
- Audit verification states which checks ran (RMR-CR-007).
  `GET /v1/execution/audit/verify` adds `hash_chain_status` and
  `signature_status` (`CHECKED`, `NOT_CHECKED_NO_KEY`, `UNSIGNED`): a verifier
  without the signing key used to report `valid: true` for a history
  re-chained with its signatures stripped. `GET /v1/audit/chain/verify` adds
  `verification_scope: linkage_only` and `signature_status: NOT_CHECKED`.
  Additive fields; persisted records are unchanged.
- The PDP token's issuer is compared when `REMORA_PDP_ISSUER` is set on the
  verifying side (`issuer_mismatch`), and the token is documented as what it is
  on the execution API: an in-process, one-time grant record, not a trust
  boundary between decision and enforcement (RMR-CR-002). The best-practice gap
  audit downgrades PDP/PEP separation from implemented to partial.

## 0.12.0 — 2026-10-07

The research release that publishes the paper revision of 2026-10-07. It
adds opt-in execution-context binding, capability sets, task identity and
loop safety, and the Federation self-service and admission tooling, and it
records the first external second-implementation runs of the frozen boundary
contracts. Three properties stay declared NOT_ESTABLISHED: runtime capability-surface
completeness, implementation effect non-transitivity and authoritative
execution-context binding.

### Added

- Execution-context binding (#754, opt-in). With
  `REMORA_REQUIRE_EXECUTION_CONTEXT=1` and a deployment provider in
  `REMORA_EXECUTION_CONTEXT_MODULE`, a deployment-owned context (subject,
  proposal-initiating model, scoped data classification, build and runtime
  provenance) is captured before assessment. Its digest is bound through
  review, grant, lease, dispatch and effect verification as
  `execution_context_hash`. Without a context, legacy authorization hashes and
  signed lease bytes are unchanged. The authority of the deployment sources is
  declared `NOT_ESTABLISHED` (`execution_context_authoritative_binding`).
- Capability sets, WS8 (#612 to #618). `REMORA_CAPABILITY_POLICY_FILE`
  resolves an `EffectiveCapabilitySet` per call from the authenticated
  principal, tenant, environment and declared task type. The set is enforced at
  assess, execute and dispatch and signed into the lease.
  `GET /v1/execution/capabilities` projects it into the agent's tool list.
  Argument and trusted-state constraints, delegation that cannot widen
  authority, revocation epochs re-read at dispatch, and success established by
  evidence rather than by the executor complete the series. The capability
  minimisation study (#619) is in `experiments/`.
- Task identity and loop safety, Q7.2 (#504, #605 to #607). A call may carry
  A2A `context_id` and `task_id`; the task is bound into the ACCEPT token and
  the lease, and redeeming under another task is refused. Loop safety state is
  kept per context and turns ACCEPT into ESCALATE at a limit.
  `GET /v1/execution/loop-safety/{context_id}` and `POST .../loop-safety/reset`
  read and reset it. `REMORA_REQUIRE_TASK_IDENTITY=1` refuses calls without a
  task. The default limits are uncalibrated.
- Federation self-service and review-only external admission (#756).
  `scripts/interop_self_service.py` runs the frozen v1 boundary cases against
  REMORA's own primitives from a pinned snapshot. External operators submit
  signed observations that `scripts/interop_external_admission.py` validates
  for review against an operator registry of public keys; admission confers no
  authority.
- Fail-closed boundary discovery (#741): `docs/interop/remora-boundaries-v1.yaml`
  and the generated `artifacts/interop/remora-boundary-summary-v1.json`. Each
  maturity claim is bound to committed capability, artifact and run evidence,
  and the gates fail on drift.
- External reproductions of the three frozen boundary contracts (#739). Probity
  ran them with a second implementation; the records are `NOT_INDEPENDENT`, and
  the contracts' lifecycle is `REPRODUCED`.
- `scripts/reproduce_custody.py` (#763): an authority and executor in separate
  processes with an Ed25519 lease and a SQLite nonce store, covering replay
  after restart, concurrent dispatch and declared custody violations. The
  interop matrix gains a table of external lifecycle records.
- Gate-correctness study v1 (#601, `experiments/gate_correctness/`,
  preregistered): the same episodes under deliberately broken validators.
  It measures how far enforcement depends on the correctness of the gate's own
  state.
- Paper revision 2026-10-06 (#746): custody and execution claims scoped to the
  strict profile and declared credential topology; effect non-transitivity
  stated as an open boundary problem; the DecisionEnvelope finalisation path
  corrected.

- First prior-art review round for the provenance ledger: PA-REV-001 to
  PA-REV-017 in `provenance/PRIOR_ART.yaml` classify PROV-01 to PROV-17
  against canonical pre-2026 literature (seven KNOWN_PRIOR_ART, six
  RELATED_PRIOR_ART, two REMORA_EXTENSION, two REMORA_COMPOSITION; no
  ORIGINAL_CLAIM or POTENTIALLY_DISTINCT). PACE (arXiv:2610.01349,
  2026-10-01) is recorded as independent convergence that postdates the
  REMORA records. The classification vocabulary in `provenance/POLICY.yaml`
  and both schemas gained the finer-grained values, each concept record now
  names its review, and `provenance/prior-art-review-2026-10-04.md` is the
  human-readable report. Reviews are AI-assisted and marked as such.
- Sequential assurance layer, RF-14 slice 1 (`remora/selective/sequential_assurance.py`):
  per-decision resolved-outcome records with epoch and cluster identity, a
  premise gate reporting ESTABLISHED / PARTIALLY_ESTABLISHED / NOT_ESTABLISHED /
  CONTRADICTED, an empirical-Bernstein confidence sequence for bounded
  outcomes beside the existing Beta-mixture sequence, an e-process against a
  preregistered rate threshold, epoch reset on policy/ToolSpec/model changes,
  and a machine-readable `SequentialAssuranceReceipt`
  (`results/sequential_assurance_receipt_v1.json`, regenerated by
  `scripts/compute_sequential_assurance.py` over the committed AROMER holdout
  fixture). Library and offline generator only; no action-authority path
  reads it, and CLAIM-011 stays cycle-scoped. The committed receipt reports
  PARTIALLY_ESTABLISHED because the fixture carries no cluster identifiers.
  The monitor counts neutral `event` flags only; mapping ground-truth labels
  onto events lives in the evaluation layer
  (`remora/aromer/evals/sequential_assurance_adapter.py`), so the runtime
  package stays clean under `scripts/check_no_evaluation_leakage.py`.
- Provenance ledger (`provenance/`): one record per register concept
  (`PROV-01` to `PROV-17`) joining the first-recorded commit to the
  canonical specification, implementation, tests, conformance suites,
  interop contracts, capabilities and claims that express it; a prior-art
  register with no review recorded yet, so every concept is classified
  `UNKNOWN`; an external-adoption register of five documented events; a
  snapshot manifest digested from one commit's tree, checked in CI; a
  signature gate over the protected paths, armed by `POLICY.yaml`; and a
  per-tag provenance manifest in the release workflow. Registration records
  priority and content, not invention.
- Federation interop surface (`artifacts/interop/`): `FEDERATION.yaml`
  participation manifest with five FED invariants; `interop-result-v1`, a
  bounded result schema with provenance, per-case records, five independence
  levels (`L0_SELF_TEST` to `L4_INDEPENDENT_HOST_RUN`) and ceiling booleans
  fixed at false; three execution-boundary fixture packages
  (`exact-call-binding-v1`, 15 cases; `fresh-authority-v1`, 14;
  `effect-evidence-v1`, 12) with zero-REMORA reference verifiers and a
  REMORA-side evaluator over the real lease, gate and effect-verification
  primitives; one consumed edge, `agentavow-tool-manifest-e8-v0.1` (8 cases,
  profile assumed, marked experimental); author-run records (L0, advance
  nothing); a generated `docs/interop/INTEROP_MATRIX.md`; and a CI
  publication gate that refuses a result without claim ceiling or
  provenance. The three boundary contracts are `FROZEN` at `fe324dd7`; the
  E8 contract is `DRAFT`. No external run exists.
- `conformance/autoreview-to-effect-v1/`: five adversarial post-approval
  vectors (argument mutation, identity change, alternate tool, stale policy,
  claimed success versus authoritative state) and one control. Author-run
  against REMORA: 6 of 6 match. A naive boolean-gate adapter matches only the
  control and diverges on all five, which is the evidence that the vectors
  discriminate. Not run against any third-party system.
- `conformance/safety-case-evidence-profile-v0.1/`: five safeguard claims
  (containment maintained, monitor active, unauthorized execution prevented,
  run paused on violation, postcondition verified) laid out as claim, producer
  evidence, independent verification, evidence sufficiency and verdict. 22
  synthetic cases; producer evidence is checked never to move a verdict. Two
  claims delegate to the frozen evidence-sufficiency checker, so the open
  findings in NEGATIVE_RESULTS.md §73 apply to them.
- Evidence-sufficiency v1.3 (`conformance/evidence-sufficiency-v1.3/`,
  `docs/design/evidence-sufficiency-v1.3.md`). A systematic mutation sweep
  (mutmut, 489 mutants of the frozen checker) found 112 mutants the v1.2
  corpus could not tell apart, in seven families (NEGATIVE_RESULTS.md §65).
  v1.3 carries the 53 v1.2 cases verbatim and adds cases E21-E23 for mapping
  key order, a rejection contract for malformed input, verdict-envelope checks
  and eleven metamorphic relations declared in `invariants.json`. The sweep
  now leaves 20 survivors, every one named and classified as equivalent under
  the pinned contract in `docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`;
  `scripts/mutation_evidence_sufficiency.py` fails on a new survivor and runs
  in the scheduled mutation workflow. `tests/test_evidence_sufficiency_v1_3.py`
  scores one representative fault per family against both runners and checks
  the relations on generated inputs with Hypothesis. The new checks were
  written after the sweep named the gaps, so their kills are not independent
  evidence; the spec records a blind external protocol for that.
  Internal stress tests, same day, fitted and not independent confirmation:
  `model.json` is a table-driven reference
  model interpreted over the whole premise lattice (61,544 documents), and
  the checker must agree at every point; a second operator set
  (`scripts/mutation_evidence_sufficiency_ast.py`, 705 first-order and 200
  second-order mutants) is scored in process with a per-mutant redundancy
  reading; 42 typed-premise faults that only the model caught became the 23
  lattice-derived K1 cases, and three `isinstance` relaxations became
  rejections R18-R20. The second set leaves 4 named survivors, all argued
  equivalent (NEGATIVE_RESULTS.md §66).
- An independent analysis of evidence-sufficiency v1.3, recorded in
  `docs/assurance/external_adequacy_evidence_sufficiency_v1.md` with its
  package in `artifacts/independent-analysis-2026-09-30/`. 43 faults chosen
  without reading v1.3: v1.2 kills 42 on the runner row, v1.3 kills 43. The
  fault list was hashed locally, not committed publicly, so the run does not
  meet section 8 of the v1.3 spec. It found stale numbers in the record, now
  corrected (NEGATIVE_RESULTS.md §67). Every historical sweep row now has a
  command that reproduces it:
  `scripts/mutation_evidence_sufficiency.py --scoring-suite
  evidence-sufficiency-v1.2` and
  `scripts/mutation_evidence_sufficiency_ast.py --corpus first-run` or
  `--corpus without-k1`. Their raw outputs are committed in
  `artifacts/evidence-sufficiency-mutation-2026-09-30/`, and `--workers 1`
  scores the second set without a process pool.
- Specification mutation of the evidence-sufficiency model
  (`scripts/spec_mutation_evidence_sufficiency.py`, v1.3 spec section 13):
  446 first-order and 300 second-order mutants of the rules in `model.json`,
  each run as a checker, with equivalence computed by enumeration. The
  catalogue and criterion were pushed before the first score. The runner
  kills every live mutant; the authored cases miss twelve cross-branch
  premise faults, so the pre-registered criterion S-2 is not met
  (NEGATIVE_RESULTS.md §68). The corpus is unchanged in that change. The sweep
  runs in the mutation workflow.
- Evidence-sufficiency v1.4 (`conformance/evidence-sufficiency-v1.4/`): v1.3
  verbatim plus 22 cases derived from a rule-coverage criterion
  (`scripts/rule_coverage_evidence_sufficiency.py`, v1.3 spec section 14)
  that defines adequacy from `model.json` alone, MC/DC-style per decisive
  outcome. The runner fails on any of its 80 obligations left open. The
  derivation rule, its output digest and a held-out mutant catalogue were
  pushed before v1.4 existed. v1.4 kills every live specification mutant of
  both catalogues on the authored cases alone, and the specification gate
  now scores v1.4 against an empty baseline. The held-out test had little
  power, and 17 of the 22 cases kill nothing another case does not in any
  catalogue measured (NEGATIVE_RESULTS.md §69).
- A committed harness for blind external runs of the evidence-sufficiency
  corpus (`scripts/score_heldout_faults.py`, v1.3 spec section 8). It checks
  the fault file against its public digest, scores v1.2 to v1.4 in the three
  rows, and applies the pre-registered criterion. It reproduces the
  independent analysis's own raw rows for all 43 of its faults.
- A pre-registered blind probe of evidence-sufficiency v1.4
  (`artifacts/evidence-sufficiency-blind-probe-2026-09-30/`): six
  context-free agents wrote 60 checker faults and 36 reimplementation
  variants without seeing the corpus. Row 3 of v1.4 kills 80 of 83 decision
  faults and row 1 kills 76, the same as v1.3. Six faults survive every row,
  three of them a `null` state value (NEGATIVE_RESULTS.md §70). The
  corpus is unchanged.
- Evidence-sufficiency v1.5 (`conformance/evidence-sufficiency-v1.5/`):
  classes instead of fault lists. Rule-coverage profile v2 derives 274 cases
  (every value class of every premise, including absence and `null`; every
  pair of failing guards; 26 state pairs); the model lattice is wider; new
  runner sections generate the input contract (container types, 24 non-JSON
  value classes, near misses of `premise_source` and claims) and check that
  no returned value aliases the verdict. Measured on a second blind probe
  locked before v1.5 existed: 77 of 77 decision faults on row 3 (v1.4: 74),
  one survivor in a new class (NEGATIVE_RESULTS.md §71). Found on the way:
  the frozen checker copies a scope shallowly (recorded as a limit).
- Evidence-sufficiency v1.6 (`conformance/evidence-sufficiency-v1.6/`): v1.5
  plus a differential test of the whole public API against an executable
  contract (2,000 seeded inputs; exact types, value semantics, copy and
  pickle, deep input non-mutation, order, module state, the enum contract).
  On a third blind probe locked before v1.6: all 61 decision faults killed,
  97 of 104 faults in all (v1.5: 94); two new kills are in classes no probe
  had named; five faults on the API surface survive (NEGATIVE_RESULTS.md
  §72).
- Evidence-sufficiency v1.7 (`conformance/evidence-sufficiency-v1.7/`): v1.6
  plus a public API surface snapshot, 300 seeded call sequences that mutate
  every object a caller holds between calls, and the input contract crossed
  with every claim and observation shape. On a fourth blind probe locked
  before v1.7: all 63 decision faults killed, 93 of 104 faults in all (v1.6:
  90); five open survivors on input sizes and public-type behaviour
  (NEGATIVE_RESULTS.md §73, open).
- Evidence-sufficiency v1.2 (`conformance/evidence-sufficiency-v1.2/`): the
  50 v1.1 cases verbatim plus E18-E20, which tell apart the three withheld
  `canonical()` faults from the external v1.1 run. v1 and v1.1 are frozen.
  The cases were written after the faults were known, so their kills show the
  repair and are not independent evidence; NEGATIVE_RESULTS.md §64 is
  superseded.
- The external v1.1 seeded-fault run over evidence-sufficiency, recorded in
  `docs/assurance/external_adequacy_evidence_sufficiency_v1.md`. The known
  faults are all killed on the runner row, which shows the repair and is not
  evidence of generalisation. Of six withheld faults, the three in
  `canonical()` survived every row; recorded as open in NEGATIVE_RESULTS.md
  §64 for v1.2.
- The pre-registered capability-mediation study (NTA-2,
  `experiments/authority_preserving_capability_mediation.py`,
  `results/authority_preserving_capability_mediation_v1.json`). Registered and
  merged before the code existed; first run committed as the result. With
  capability minimization alone every unsafe class produced its effect; the
  in-process mediator stopped all but direct use of the credential in the
  tool's process; the three-domain split, with the tool in a separate process
  holding no credential, stopped all eight unsafe classes. No legitimate
  nested effect was blocked. Seven of eight predictions met; P6 (mediated
  effect coverage 1.0 in arm B) missed at 0.6667 and is recorded in
  NEGATIVE_RESULTS.md §63. Author-written corpus; not a real-world rate.

- NTA-2 phase 3: a three-domain custody split for mediated effects. A process
  with `REMORA_EXECUTION_DOMAIN_ROLE=effect` holds the effect credentials and
  serves only `/v1/execution/effects` and `/effects/close`; an executor with
  `REMORA_EFFECT_ENDPOINT` set must then hold no declared effect credential
  (custody K12 to K19). The effect domain verifies the lease with
  verification material only (`ExecutionLease.verify_authenticity`), refuses
  a lease the durable nonce store says was never dispatched
  (`consumed()`, read-only), derives the effect authority from its own signed
  ceiling, and keeps closure and the budget in the same store (AST-014).
  Under a strict profile a mediated tool without a declared ceiling is
  refused. `scripts/check_credential_topology.py` gains a direct-access gate
  over governed tool modules. The experiment of the design's section 25 is
  pre-registered in `experiments/authority_preserving_capability_mediation/`.

- NTA-2 phase 2: capability mediation wired through the signed ToolSpec, the
  dispatcher and the evidence. ToolSpec schema version 2 adds an optional
  `downstream_capabilities` ceiling (`schemas/tool_spec_v2.yaml`); the
  bundle's signed `schema_version` is now checked. A tool registered with
  `mediated=True` is called with a `CapabilityMediator` that
  `GovernedToolDispatcher` builds from the lease-bound capability set and the
  tool's ceiling, before the nonce is spent. Nested effects are recorded as a
  bounded `ResolvedEffectGraph` in the dispatch result, the `execution_result`
  chain record and the outbox projection, and `success_established_v2`
  requires them settled (v1 is unchanged). CAP-024 is `WIRED_API_PATH`, opt-in
  and research profile; the runtime property stays `NOT_ESTABLISHED`.

- Authority-Preserving Capability Mediation, NTA-2 phase 1
  (`docs/design/authority-preserving-capability-mediation-v1.md`, status
  proposed). Authorization of a tool does not authorize the privileged effects
  its implementation can reach. Phase 1 is a library in the research profile:
  canonical resource identities that refuse ambiguous forms rather than
  normalise them (`remora/capabilities/resource.py`), a `within` constraint
  operator, a ToolSpec-shaped `DownstreamCeiling` that is a limit and not a
  grant, `derive_effect_authority` chaining a tool's effect authority to the
  caller's set, and a fail-closed `CapabilityMediator` that records every
  request. The conformance suite gains NTA2-01 to NTA2-11 (24 of 24 match).
  Registered as CAP-024 at `IMPLEMENTED_LIBRARY`; the runtime property
  `implementation_effect_non_transitivity` is registered as `NOT_ESTABLISHED`,
  because the mediator runs in-process and does not stop direct client use.

- Non-Transitivity of Authority (NTA-1) is a named principle with one
  canonical page, `docs/security/non-transitivity-of-authority.md`. It gathers
  what Q8.4, Q8.5, the lease binding and the "confused deputy" tests each
  enforced under separate names into three forms (reachability, argument
  authority, delegation transitivity), maps each to its code, and states the
  limits: enforcement ends at REMORA's PEP, the capability layer is opt-in,
  and no HTTP route derives a delegation. `conformance/non-transitivity-of-authority-v1`
  states NTA-1 as 13 implementation-agnostic vectors with an adapter contract.
  REMORA matches all 13, and `tests/test_conformance_non_transitivity.py`
  shows that weakening each guard diverges on the vectors that name it.
  CAP-023 is re-audited with the suite as evidence.

- Utility floors in the claim register. Every active safety claim now declares
  its pre-registered utility bars (`utility_floors`: metric, min or max,
  source, met or missed) or a reason none applies (`utility_floor_exempt`).
  `scripts/check_claim_utility_floors.py` recomputes each status and runs in
  the quality gates and `make audit`. Five floors are declared and four are
  missed: AgentHarm benign false-block 100% against a 40% ceiling (CLAIM-002),
  and BFCL C-ext3 read autonomy, obtainable VERIFY and unobtainable ABSTAIN
  (CLAIM-019). The last two C-ext3 metrics are now bound to their artifact, so
  the unbound-metric baseline falls from 17 to 15.

- Verify-only replication pack. `artifacts/replication-pack/replication_pack_v1.json`
  lists each active headline claim with its artifacts, their LF SHA-256, their
  results-manifest class, the metric values and the JSON fields they must
  equal, and the offline commands that regenerate or validate them; active
  claims it leaves out are listed with a reason. It also pins the environment:
  the `requirements-lock.txt` hash and the reference Dockerfile's base image
  digest, with `image: null` because no REMORA image is published.
  `scripts/verify_replication_pack.py --check` verifies all of it offline and
  fails when the pack drifts from the claim register or the results manifest;
  `--regenerate` re-runs the regenerable entries in a temporary worktree of
  HEAD and compares metric fields, ignoring only the named volatile fields.
  `--check` runs in CI, in `make audit` and `make claim-check`, and first in
  `artifacts/reproduce.sh`. Documented in `docs/06-reproducibility.md`.
- `remora.decision_providers`: the contract through which an external source
  of typed semantic judgment is admitted as evidence, and only as evidence.
  A provider answers narrow typed questions (choice, score, boolean) with
  calibrated probabilities; `DecisionEvidence` records the answers together
  with the question-set version, the model alias, the separately-recorded
  resolved model, and hashes of both the state shown and the response. The
  alias and the resolved model are separate fields because an alias can be
  repointed at a new model without a code change, which moves every threshold
  calibrated against the old one.
  `project()` is the only supported route from evidence to an observation, and
  it writes model-signal fields exclusively. That confinement is what makes a
  provider inherit the existing execution-profile invariant that no
  combination of model signals reaches ACCEPT. The projectable set is pinned
  against the model-signal class of the `whatif` lever catalogue rather than
  copied from it, so the two cannot drift apart.
  The danger this guards is specific. The questions such a model answers best
  are intent match, target match and scope drift, and the observation fields
  that look like the place for those answers are `tool_matches_goal`,
  `expected_effect_matches` and `argument_values_grounded`. All three are
  deployment facts, which can reach ACCEPT. `project()` refuses them rather
  than dropping them silently.
  Ships a deterministic reference provider and no network adapter. A hosted
  provider is an adapter implementing the protocol, and the properties above
  hold for any adapter because they are properties of the projection.
  `tests/test_decision_providers.py` records a declared limit alongside the
  guarantee: the ACCEPT bound is a property of the execution profile, and the
  same favourable signals do reach ACCEPT on an engine configured without it.
- `remora.decision_providers.cloudflare`: an adapter for the `typesafe/jev`
  model served through Cloudflare Workers AI, reached at
  `POST /accounts/{account}/ai/run`. Routing through the Cloudflare account
  means no separate vendor key. Writing the adapter corrected two things in
  the contract above, which is why it ships with it rather than after it. A
  `noul` answer is a probability rather than a boolean, so the answer value
  stays a probability and `as_bool` demands an explicit threshold instead of
  assuming one; a 0.51 and a 0.99 must not become the same record. A `score`
  answer indexes a legend in the legend's own units rather than [0, 1], so the
  value and its labels travel together and neither is normalised away. The
  adapter records the resolved version from the response rather than the alias
  from the request, refuses a choice outside the declared options, refuses a
  response that names no model version, and maps every transport failure to a
  refusal rather than a favourable default. It is exercised against the
  documented response shape through an injected transport and has not been run
  against the live service, so it is evidence about parsing and about nothing
  else.
- `remora.decision_providers.typesafe`: an adapter for Jev on TypeSafe's own
  API, `POST https://api.typesafe.ai/v1/systemone`, with model alias
  `jev-latest`. It reads `JEV_API_KEY`, the name of the repository's GitHub
  Agents secret, and falls back to `TYPESAFE_API_KEY`. It needs no Cloudflare
  account or gateway credits. The question payload and answer parsing are now
  module functions in `remora.decision_providers.cloudflare` shared by both
  adapters, so a `noul` answer stays a probability and a `score` keeps its
  legend on either route. `429` and `529` are retried with a bounded
  `retry-after`; every refusal carries TypeSafe's message and request id.
  `examples/jev_decision_provider_demo.py --live` now uses this route, and
  `--via cloudflare` selects Workers AI. Both key names are registered in the
  credential topology as oracle credentials. Exercised through an injected
  transport only; no live answer has been observed yet.
- `experiments/jev_live_smoke.py` and `results/jev_live_smoke_v1.json`: the
  first live round against Jev, on TypeSafe's API, 2026-10-01. Three demo
  scenarios with three repeats each: nine answers from `jev-1.13.0`, no
  provider failure, no ACCEPT. The injection scenario escalated in every
  repeat. The legitimate scenario's favourable signal was withheld at the
  demo's illustrative 0.85 threshold (`intent_match` 0.70), and repeats of one
  state returned different answers within 0.06. Both observations are recorded
  in the integration guide as inputs to calibration. Manifest class `live`,
  with a provenance sidecar.
- Question set V2 (`remora-semantic-v2`) and `semantic_state_v2`, written
  against TypeSafe's published Jev guidance, with a V1/V2 screening round in
  `results/jev_question_set_ab_v1.json`: 192 answers from `jev-1.13.0`, no
  ACCEPT, every injected variant flagged under both sets. V2 separated scope
  drift more cleanly and scored legitimate intent higher. Both sets flagged
  benign tickets as injection on some tasks, recorded as open finding
  NEGATIVE_RESULTS.md §74.
- Question set V2.1 (`remora-semantic-v2.1`) and a pre-registered hold-out
  (`artifacts/jev-injection-holdout-2026-10-02/`,
  `results/jev_injection_holdout_v1.json`). V2.1 changes only the injection
  questions. On 192 scenarios from context-free authors, V2.1 flagged 22.5 %
  of non-injection scenarios (V2 53.5 %, V1 29.6 %) and caught every
  injection, meeting both pre-registered criteria. V1, the default set in
  `enrich`, gave one favourable admission on a wrong target. Deviations, one
  of them an Opus author declining the injection brief, are in the
  artifact's `DEVIATIONS.md`.
- Semantic shadow mode on the enforcing assess path.
  `remora/decision_providers/shadow.py` evaluates a provider beside a real
  decision and returns a record of the actual, engine and counterfactual
  actions with answers, latency and billed input tokens; it never mutates
  the observation and turns every fault into a record.
  `servers/semantic_shadow.py` wires it into `assess_proposal` through a new
  `semantic_shadow` parameter, called after the audit record is durable, on a
  bounded background pool, for opted-in tenants with a server-resolved
  operator request. Off by default; refused at startup when switched on
  without tenants, question set, thresholds and log path. The response is
  unchanged with the shadow off, on or failing.
- `scripts/semantic_shadow_report.py` summarises shadow records and, given
  reviewer labels, reports what the sensor missed and flagged separately
  from what would have changed the decision, since under the execution
  profile a caught scope drift is flagged without a stricter decision.
- `GET /v1/execution/proposals/{proposal_id}/semantic-assessment` gives the
  step that resolves a decision Jev's reading of the proposal. At VERIFY, a
  bounded machine lookup, `verification_focus` names what the lookup should
  check (`confirm_target`, `confirm_intent`, `confirm_scope`,
  `exclude_untrusted_text`); at ESCALATE the human approver gets the same
  answers in plain words. Advisory in every response, tenant-scoped, and read
  by no approval, resolution or execution path. When there is no reading the
  status says why. Shadow records now carry the thresholds they were
  admitted against.
- Per-vertical semantic profiles (`REMORA_SEMANTIC_SHADOW_PROFILES`): named
  profiles with question set, thresholds, language and calibration record,
  and a tenant map, checked key by key at startup. Records carry the profile
  and the reader's caveats follow it. Documentation now places Jev in the
  architecture: a node and a shadow branch in the pipeline diagrams of
  `ARCHITECTURE.md` and `docs/01-architecture.md`, a new `ARCHITECTURE.md`
  §5.6 with its own flow diagram and its relation to AROMER, the API
  reference for the semantic-assessment route, the semantic profile as an
  optional fifth part of a domain pack (`domain_pack_governance_v1.md` §11),
  cross-links from the RAG oracle and Workers AI guides, and the mkdocs nav.
- `remora.decision_providers.questions` and `remora.decision_providers.enrich`
  complete the provider integration end to end. The question set is versioned
  (`remora-semantic-v1`) because thresholds are calibrated against a specific
  wording, and it deliberately carries no `recommended_route` question: a model
  that names a route starts to look like the thing that decides. `enrich` is
  the one place provider answers meet an observation, and it can do two things
  only. Favourable `intent_match` and `target_matches_request` answers, with
  `scope_drift` below its threshold, become the engine's evidence signal, which
  under the execution profile stops at VERIFY. A likely `possible_injection`
  raises `adversarial_detected` through the new `project_narrowing`, which can
  raise a declared safety flag and never clear one. Reversibility and risk
  scores are recorded in the evidence and never projected, because the fields
  that look right for them are deployment facts. Thresholds have no defaults;
  a threshold is a calibrated policy decision and belongs in reviewed
  configuration. `semantic_state` refuses credential-shaped keys rather than
  redacting them. Failure is structural: a provider that cannot answer leaves
  the observation untouched, and a test holds that the decision without the
  provider is never more permissive than the decision with it, which is why
  no per-tier failure table is offered. `docs/integrations/jev_decision_provider.md`
  is the integration guide. Nothing in the shipped execution path calls
  `enrich`; wiring it into governed dispatch is a separate change that should
  follow a calibration study in the deployment's language.
- The Cloudflare adapter was run against the live service on 2026-09-24. The
  account token, the endpoint and the request shape are confirmed correct: a
  native model on the same endpoint answered 200. `typesafe/jev` itself
  answered 402 with Cloudflare code 2021, "Insufficient balance", because a
  partner model is paid for from prepaid AI Gateway credits rather than the
  standard plan. Two changes follow. `DecisionProviderError` now carries
  Cloudflare's own error message, so the refusal names the operational cause
  instead of a bare status. The adapter takes a `gateway_id`
  (`CLOUDFLARE_AI_GATEWAY_ID`) and sends it as the documented
  `cf-aig-gateway-id` header, which is what routes the spend to the credit
  balance. The integration guide records the prerequisite and the three
  steps that clear it. No answer from the model has been observed yet; the
  claim boundary is unchanged.
- A second live prerequisite, learned once a unified-billing gateway existed
  (`remora-jev`, created 2026-09-24 with authentication on): `/ai/run`
  answers 403 code 2049 unless the bearer token carries the AI Gateway Run
  permission, which an account token with Workers AI and gateway read and
  edit rights does not. The adapter takes `gateway_token`
  (`CLOUDFLARE_AI_GATEWAY_TOKEN`) and uses it in place of the account token
  for the run call. The token is declared in the credential topology with
  the note that Cloudflare scopes Run to the whole account. Still no answer
  from the model observed; both remaining steps are dashboard actions.

- What-if decision-boundary analysis (`remora.policy.whatif`, `remora whatif`,
  `remora.what_if_tool_call`, `remora.shadow.boundary`). For any observation
  it searches every combination of a fixed lever catalogue against the real
  engine and reports whether model signals alone (trust, phase, evidence,
  quorum, temperature) can reach ACCEPT, whether the agent alone (proposal
  plus model signals, no deployment-declared fact) can, the smallest change
  sets that do, each change tagged deployment fact, proposal or model
  signal, what every single lever does on its own, and the hard guard in
  force. The model-signal sub-space is always searched in full, so "cannot"
  is a proof over the catalogue rather than a budget artefact. Read-only
  over the engine; an analysis, not a grant. A memo keeps evaluations to
  distinct combinations and hard-guard pruning skips combinations a firing
  guard makes hopeless; tests assert pruned and unpruned searches return
  identical paths. `remora whatif --log` aggregates over a shadow-mode
  action log and lists any block liftable by model signals alone as a
  policy finding. A completeness test fails when the engine starts reading
  an observation field that is neither levered nor explained. Tests assert
  soundness (every named path replays to its verdict) and minimality (no
  proper subset reaches the target) over a grid, plus the execution-profile
  invariant that no model signal produces ACCEPT for any call. The five
  `try` presets and the sample shadow log are analysed in
  `artifacts/demo/whatif_presets_v1.json` and
  `artifacts/demo/whatif_boundary_sample_v1.json`, regenerated and checked
  by `scripts/generate_whatif_presets.py`.

### Roadmap

- RF-12 (docs/13): database-enforced tenant isolation via Postgres row-level
  security, grounded against the tree. Records two blockers no earlier
  document named: the reference and pilot deployments connect as the Postgres
  superuser (RLS bypassed even when forced) and nothing binds the verified
  tenant to the connection. REM-026 notes and the multi-tenant security model
  point to it. Proposal only; nothing implemented.
### Testing

- Postgres outbox fault injection (`tests/test_postgres_outbox_fault_injection.py`),
  run by both Postgres CI jobs with the no-skip guard. Seven tests against a
  real server: eight backends racing one row through `FOR UPDATE` (one
  winner), a claim blocking on a held lock and losing, a backend terminated
  mid-claim (row released, survivor claims), worker death after a committed
  claim (reconciled UNKNOWN, never re-claimed, sweep idempotent), worker
  death after settle before projection (payload atomic with the terminal
  state, projector queue and re-mark), a torn settle transaction (nothing
  lands), and cross-process intent idempotency. Before this the Postgres
  adapter had six sequential contract tests; concurrency, crash and
  projection paths were covered only on the in-process and SQLite stores.
  No adapter code changed. Scope stated in the module docstring: backend
  and transaction faults, not OS process kills or network partitions.

### Fixed

- Dependency advisories (#734, #755, #761): datasets 5.0.1, fsspec and s3fs
  2026.6.0, langgraph-sdk 0.4.4, Mako 1.4.2, multidict 6.9.1, scapy 2.7.0,
  source-map-js 1.2.2, shell-quote 1.12.0 and sharp 0.35.5 in every npm
  project. `tests/test_ci_dependency_pinning.py` pins the patched floors.
- Tainted HIGH-risk calls with no rollback or an uncertain state now escalate
  (#717, WP-1).
- The worker refuses an unbound worker identity and stale reconcile races
  (1cbeca6).
- `decode_json` in `remora/interop/evidence_io.py` bounds nesting explicitly
  (`MAX_JSON_DEPTH = 512`). Python 3.14's decoder no longer raised
  `RecursionError` at 10,000 levels, so deeply nested input was accepted there.
- `AnthropicAdapter` works on current Claude models, and dated model pins in
  prompts are retired (#578, #582).

- Pre-Federation boundary probes (2026-10-06, `tests/test_pre_federation_*`),
  each a fail-open path closed in the reusable primitive rather than only in
  its strictest caller:
  - effect verification: `verify_declared_delta` treated a missing field as
    an explicit `null` under `exact`/`hash`, so `{"deleted_at": null}`
    verified against `{}`; an unknown comparison rule (`excat`) fell through
    to `exact`; a rule for an undeclared field was never evaluated. The core
    verifier and `remora.sdk.effects.PostconditionSpec` now refuse the rule
    map (`ValueError`) and a missing field is a mismatch;
  - exact-call binding: `canonical_tool_call_hash` stringified non-JSON
    values (`default=str`), merged int and string keys, merged tuples into
    arrays and accepted NaN/Infinity. It now refuses values outside the JSON
    domain; bytes for JSON-domain calls are unchanged, so existing leases and
    chain entries still verify. `ExecutionLease.verify` reports
    `tool_args_not_canonical`;
  - effect receipts: an empty `trusted_verifiers` allowlist trusted any
    verifier and now trusts nobody (the execution API passes the identity it
    has bound to the principal); a terminal `EFFECT_UNSUPPORTED` no longer
    takes the dispatch's settled slot without naming the dispatch; a reason
    code `verify_declared_delta` emits for one status is refused with
    another; the recorded `tool_id` and `toolspec_hash` come from the
    assessment in the chain and a differing claim is a 409;
  - final hop: `GovernedToolDispatcher.dispatch` executes a private copy of
    the arguments, reads the callable after spec resolution, and re-checks
    the argument hash and registry generation before spending the nonce
    (`tool_args_changed_after_verify`, `tool_registry_changed`);
  - deep immutability: `PostconditionContract`, `EffectVerification`,
    `PostconditionSpec`, `ProducerCapabilityManifest` and `EvidenceAdmission`
    froze one level deep, so a nested alias held by the caller could change
    the content after its digest was computed, and an accepted manifest
    digest could establish producer visibility in another tenant's scope.
    `remora/frozen_json.py` now takes a private deep copy and refuses values
    outside the JSON domain; `effect_digest` drops `default=str` and keeps its
    historic encoding for JSON-domain values;
  - durability topology: the production guard admitted
    `REMORA_STATE_ENDPOINT` alone, although the tenant audit chain and the
    dispatch outbox have no D1 adapter and stayed in process memory, and
    `/v1/health` reported that deployment as `in_process`. Production now
    requires `REMORA_PG_DSN` or `REMORA_CHAIN_DB` (the endpoint may sit
    beside them); the outbox selection is wiring point ASW-005 and names the
    endpoint-only case `UnbackedExecutionOutbox`; the backend is reported as
    `state_endpoint_partial` and not durable. **Breaking for a deployment
    that ran production on the endpoint alone.**;
  - async authorization seam (`REMORA_ASYNC_DISPATCH`): the worker honoured a
    202 under whatever ToolSpec was current when it woke up, and it built a
    fresh observation only to hash it before minting a new ACCEPT, so a hard
    guard that fired after the 202 was never decided. Before claiming,
    minting or consuming anything, `dispatch_pending_intent` now compares the
    spec in force with the hash the assessment recorded in the chain and
    refuses with the additive reason code
    `toolspec_changed_between_authorization_and_dispatch`, and re-decides the
    fresh observation through the queue's own engine
    (`ReviewQueue.regate_authorized`, the equal-or-safer rule of the 202),
    refusing with `fresh_regate_refused`. Both settle REFUSED with the grant
    unminted. No row schema changed: the authorized hash is read from the
    chain, so rows written before this change get the same check, and an item
    with no recorded hash fails closed whenever a bundle is enforced at
    dispatch. A spec the bundle refuses at dispatch now settles under its own
    code instead of escaping the worker loop as an HTTP 409;
  - Federation fixture adequacy: `effect-evidence-v1` and
    `exact-call-binding-v1` are frozen with external runs against their
    digests, so the probes are answered by `DRAFT` successors
    `effect-evidence-v1.1` (edge `E-EE-V1-1`) and `exact-call-binding-v1.1`
    (`E-ECB-V1-1`) instead of rewritten bytes. The effect reference verifier
    no longer reads a missing field as `null` and rejects an unknown rule or
    a rule for an undeclared field (`CONTRACT_REJECTED`), and its
    `version_increment` compares integers only on both sides. Fourteen effect
    cases and seven call cases were added: missing against explicit `null`
    under `exact`, `hash`, `absent` and `present`; rejected rule maps; `1`
    against `1.0` in both directions and nested; nested `true` against `1`;
    `"4"`, `true` and `4.0` as observed versions and `"3"` as a declared one;
    an added `null` argument; two integers beyond 2^53. The exact-call README names
    verify-then-mutate (TOCTOU) as outside a static corpus and points at
    `tests/test_pre_federation_toctou_adversarial.py`. REMORA's core and the
    v1.1 reference verifiers agree on all 48 v1.1 cases (L0 author records). The
    v1 packages keep their bytes and are marked superseded in `index.json`
    and `FEDERATION.yaml`; their blind spots are pinned by tests as a
    preserved negative result. The new cases are repair, not independent
    evidence.
- Evidence admission, one fail-closed narrowing (2026-10-04). A
  `CoverageAttestation` could establish `observation_coverage_complete` on
  producer identity, invocation id and its own content; its digest was never
  compared with deployment trust, so a statement fabricated or mutated in an
  accepted producer's name passed. `TrustConfig.accepted_coverage` now maps a
  producer to the attestation digests the deployment accepted, the join
  refuses any other statement with the additive reason code
  `coverage_attestation_unaccepted`, and the coverage branch also requires
  the manifest to cover every attested field, as the design document already
  stated for C4. Library only; nothing in the runtime reads an admission.
  NEGATIVE_RESULTS §75 records the third asserted input and stays open.

- Strict raw-JSON admission on the execution surface (2026-10-04,
  `servers/strict_json_ingress.py`). Bodies for `/v1/execution/*` and
  `/v1/assess` were decoded by the framework's permissive parser before
  `canonical_tool_call_hash` saw them, so a repeated member name silently
  kept its last value, `NaN` and `Infinity` were accepted as numbers and a
  lone `\uD800` escape became an unpaired surrogate. A new ASGI guard,
  registered inside the body-size limit, now refuses such bodies on the wire
  with HTTP 400 and a stable `code` (duplicate member after escape decoding,
  non-finite number, unpaired surrogate, Unicode noncharacter, invalid UTF-8
  or byte order mark, nesting above `REMORA_MAX_EXECUTION_JSON_DEPTH`, size
  above `REMORA_MAX_EXECUTION_JSON_BYTES`). An admitted body is replayed to
  the framework unchanged, so every request that was valid before parses to
  the same value and hashes the same; `remora/json-sorted-v1`, stored
  signatures and the request models are untouched. Grounded in RFC 8259
  section 4 and RFC 7493 sections 2.1 and 2.3.

- Security review 2026-10-02, two fail-closed narrowings.
  `_is_low_consequence()` now excludes every production alias in `_PROD_ENVS`
  (`prod`, `production`, `live`). Before this fix, a low-risk `live` read
  could reach `LOW_CONSEQUENCE_ACCEPT` when `REMORA_LOW_CONSEQUENCE_ACCEPT`
  was on. `ToolSpecBundle.load()` now refuses a bundle whose outer
  `registry_signature.signing_identity` differs from any spec's signed
  `signing_identity`, using the new additive reason code
  `toolspec_signing_identity_mismatch`. The outer label sits outside the HMAC
  preimage, so a revoked bundle could previously be relabeled to a trusted
  signer. Open: one shared HMAC key still lets any holder sign under any
  identity; signer-specific keys are not implemented.

- The H1 sentence in the evidence-sufficiency v1.2 runner's `limits` list
  named only the gap label ("Cases H1 were written..."); it now names cases
  E18-E20, and `run-record.json` is regenerated with no other change. An
  external rerun measured v1.2 at `c1345b1` before the rewording, so a test
  pins the measured bytes and checks that this sentence is the only
  difference.
- Five register findings from the replication pack.
  `effective_n` in the tool-call scorers counted domains, not templates: task
  ids are `<domain>_<seq>`, so stripping the last segment left 7 "clusters".
  `remora.toolcall.scoring.template_cluster_key` now counts harmful template
  clusters (56 for v2 and blind v3, 21 for v1), and the 13 affected regenerable
  results are re-issued with no other field changed (artifact manifest
  revision note, tag `effective-n-reissue-2026-09-28`). CLAIM-001's effective
  N = 70 was always computed correctly by the significance analysis.
  `results/sap_v3_round_results.json` is re-analysed: it predated the issue
  #85 fix, so four uncertified SGR `risk_bound` fields still held the old
  sentinel (0.99 and 0.996667 instead of 0.084, 0.093 and 0.060). Certified
  flags and coverages are unchanged. It and `system_demonstration_v1.json`
  are reclassed from live to regenerable, because both reproduce offline and
  are now byte-compared in CI. CLAIM-001's Wilson bound is bound to the
  significance file, which lowers the unbound baseline from 15 to 14.
  `docs/06-reproducibility.md` now uses CLAIM-001's registered commands.

- The MCP gateway verifies the Cloudflare Access assertion on `/mcp` itself
  (`workers/mcp-gateway/src/admission.ts`: RS256 against the team key set,
  AUD, issuer, expiry) and answers 503 while `ACCESS_TEAM_DOMAIN` and
  `ACCESS_AUD` are unset, instead of relying on an edge policy configured
  outside the repository. `REMORA_DEPLOYMENT_PROFILE=production` refuses `/mcp`
  until `REMORA_PG_DSN`, the custody split and Access verification are all
  configured, and `/health` no longer reports a D1 binding as a durable audit
  chain. The deployed staging gateway needs the two Access settings before its
  next deploy.
- Agent-control's administrative reads (`/envelopes`, `/envelopes/verify`,
  `/envelopes/<request_id>`, `/audit`) are bound to the deployment's
  `TENANT_ID`. A query naming another tenant is refused with 403, and the
  single-envelope lookup matches the tenant as well as the request id.

- The synchronous `/v1/execution/execute` path now claims the dispatch intent
  before it mints and consumes the grant and before it appends
  `execution_authorized`, the order issue #417 set for the async worker. A
  request that loses the claim consumes no grant and leaves no authorization
  event for a dispatch it never performs.
- `scripts/check_results_manifest.py` compares each sidecar's
  `artifact_sha256` with the LF hash of its result. Eleven sidecars carried a
  hash over CRLF bytes; they are corrected, and each keeps the old value under
  `artifact_sha256_correction`. No result file changed.
- CLAIM-006 no longer cites `artifacts/aromer/intelligence_after_v020.json`,
  a 2026-06-09 snapshot that predates the TRAINED run and reads AII=0.5165.
  The statement now matches the NEGATIVE_RESULTS.md §11 table (0.8412 at cycle
  8, peak 0.844 at cycle 12, regression to CAPABLE the same day) and says the
  values are live telemetry no gate can bind.
- README and the executive one-pager pair the AgentHarm 0/208 false-accept
  result with its 100% false-block rate on the benign twins.
  `docs/EVIDENCE_OF_CAPABILITY.md` describes the execution kernel instead of
  the earlier cascade framing.

- The REM-047 transactional audit outbox is wired to production writes. It
  was implemented and had no caller outside its own test, so every
  state-transition audit event was appended after the transaction recording
  the transition had already committed. Two atomic writes are not one atomic
  write: a crash in between left a transition with no audit event, which a
  verifier holding the chain cannot distinguish from a chain nobody wrote to.
  `revoke-principal` was the plainest case, committing the revocation inside
  the state transaction and appending `principal_revoked` outside it. Four
  appends now issue inside the state transaction under a deterministic
  idempotency key and are projected by the existing lazy drain. The API
  contract states the consequence rather than hiding it: an `AuditRef` for a
  deferred event carries `deferred: true`, null `sequence_no` and
  `entry_hash`, and the `idempotency_key` the event will be appended under.
  Inventing an index the chain does not yet contain would be worse than
  saying the index does not exist yet.
- Seven CI review scripts could be made to pass on input they exist to
  refuse. A 2026-09-02 audit imported each script's own regex and ran bypass
  strings through it. Each fix is test-first, with a seeded-bypass meta-test
  in `tests/meta/test_check_script_bypasses.py` that writes the evading
  string into a temporary tree, runs the gate against it, and asserts
  failure. No gate was weakened, and where a repaired scanner surfaced
  something real in the repository the finding is recorded rather than
  scanned around.

- Reversibility classification in the risk model is now total and fails
  closed. `remora.credal` weighed worst-case loss by membership in a frozen
  set of eleven `action_type` spellings, and every other string, including
  every string nobody had anticipated, took the reversible weight of 0.30.
  That weight reaches a decision: `worst_case_loss` drives the minimax
  escalation gate at 0.8. Of the 20 distinct `action_type` values in
  committed corpora, 18 sat outside the set, among them
  `financial_transaction`, `approve_payment`, `db_migration`,
  `schema_change`, `security_change` and `configuration_change`, each a
  near-synonym of a string that was inside it. Measured over a uniform grid
  of (p_harm_upper, severity), 40 of 231 points changed the gate's verdict on
  the spelling alone. End to end at `risk_tier="critical"`:
  `config_overwrite` escalated at 1.0 while `configuration_change` did not at
  0.71. `remora.action_semantics` now classifies three ways (irreversible,
  declared reversible, unknown) and unknown carries the irreversible weight,
  so only explicitly declared non-mutating actions keep the discount. The
  full suite passes unchanged, so no committed result artifact depended on
  the previous weighting. `tests/test_reversibility_fail_closed.py` holds the
  contract, including a guard against widening the reversible set to recover
  utility.

### Verification and CI

- Repaired `requirements-lock.txt`, which had stopped being resolvable. The
  lock is applied as pip *constraints*, so a pin is only checked when pip is
  asked to install that distribution: two pins can contradict each other for
  months while every pull request stays green. The weekly NLI parity run hit
  the first contradiction on 2026-09-21 (`click==8.1.8` against
  `huggingface_hub==1.28.0`, which requires `click>=8.4.2`), and resolving
  each install set in turn uncovered five more, every one introduced by a
  single-line dependency bump: `setuptools` against torch, `tokenizers`
  against transformers (via a version that has no files on PyPI),
  `agent-client-protocol` and `jiter` against inspect-ai and openai, and
  `botocore` against aiobotocore. Eight pins moved; no source changed.
- `scripts/check_lock_resolvable.py` and the `lock-resolvable` leg of the
  Supply Chain workflow now resolve every declared install set against the
  lock with `pip install --dry-run` on pull requests, master pushes and
  daily, so the next contradiction fails in review rather than in a weekly
  job. The gate is part of the `supply-chain-required` aggregate context.
  Scope is stated in the script docstring: resolvability of the declared
  sets, not that the resolved versions are the pinned ones.
- The scheduled mutation sweep uninstalled `remora`, a distribution name that
  has not existed since the project became `remora-assurance`. pip skipped it
  silently, the installed package kept shadowing the mutated sources, and the
  workflow's own guard correctly refused to run a sweep that would have
  reported every mutant as surviving.
- `tests/test_ci_dependency_pinning.py` and `tests/test_lock_resolvable_gate.py`
  hold both defects in place: the sweep must uninstall the distribution name
  `pyproject.toml` actually declares, the two pins that collided must stay
  mutually satisfiable, and an install set a workflow uses under the lock must
  be one the resolvability gate declares.

### Documentation

- Prose-style scanner (`scripts/check_prose_style.py`) gained two
  sentence-level tells: `long_sentence` (over 35 words, wrapped lines
  joined, lists and tables skipped) and `meta_governance` (sentences about
  how a document is to be read rather than about the system). Baseline
  re-recorded at 575 and 45; both remain shrink-only. The character-level
  tells were near zero after the 2026-08-26 pass; these two name what
  still makes the documentation hard to read.
- `docs/README.md` rebuilt in two layers: a seven-step reading path and a
  "which one do I want" table for the topics with more than one document
  (architecture, security, MCP, GO-STAR, SAP versions, claims), with the
  full registered set in collapsible groups by question. Every link from
  the previous index is preserved (governance index-completeness check);
  meta-governance sentences in the index went from 7 to 0.
### Repository layout

- Root tidy, slice A: the licensing bundle (`COMMERCIAL_LICENSE.md`,
  `LICENSING.md`, `COPYRIGHT.md`, `TRADEMARKS.md`, `THIRD_PARTY_NOTICES.md`)
  moved to `legal/`; `EVIDENCE_OF_CAPABILITY.md` and `CONTRIBUTORS.md` to
  `docs/`; `docker-compose.test.yml` to `deploy/`. All moves via `git mv`
  (history preserved). Every reference updated: pyproject `license-files`,
  license-policy gate, document register, governance and provenance
  scanners, tests, NOTICE, codegraph paths and Markdown links. `LICENSE`,
  `NOTICE`, `CITATION.cff`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  `CONTRIBUTING.md` and `NEGATIVE_RESULTS.md` stay at the root (GitHub
  reads them there). Slice B (`ARCHITECTURE.md`, `DEVELOPER_OVERVIEW.md`)
  follows separately because it touches `CLAUDE.md` and CI workflows.

### Paper

- Reframed the paper around governed execution assurance: the authority-bound
  execution chain (signed ToolSpec, exact-call lease, key-custody separation,
  re-policying at the enforcement point, effect-evidence states) is now the
  stated identity, with the multi-oracle machinery positioned as routing
  support. The architecture chapter describes the deployed
  Ed25519/ToolSpec/lease/custody/PEP model with its gaps stated.
- Related work gains an authority-bound execution section with explicit
  non-claims, positioning against AIRGuard, Proof-Carrying Agent Actions,
  Proof of Execution and the agent-permissions survey (all four verified and
  added to both reference lists; citation parity 67=67).
- The version stamp moves to v0.11.0 / 2026-08-25 against the frozen release
  tag; the "synchronized" wording is dropped and the stale review-v1 pointer
  and test counts are corrected.

## 0.11.0 — 2026-08-25

The first frozen research release since 0.10.0: an exact, tagged commit that
the paper, external replication and citation can reference instead of a
moving master (issue #390).

### Execution assurance

- Cross-tenant argument values now hard-abstain instead of escalating to a
  human approver, on both the assess and the approved-redeem path; the
  boundary is re-checked when a previously approved item is redeemed.
- The decision record declares per-component trust-base coverage
  (`policy_components`): which policy, risk-profile, schema, registry,
  engine-mode and OPA digests the decision resolved, and — explicitly —
  which trust-base elements carry no digest. Written on both the
  authorization and the result chain records, re-read at dispatch so the
  two views can disagree.
- Governed dispatch verifies the lease against the clock it was issued
  under; an in-memory SQLite database is refused as a durable backend at
  the enforcement gate, the nonce store, the idempotency store and
  production startup.
- One runtime exception root (`remora.errors.RemoraError`) with
  machine-readable `code`/`category` across sixteen governance exceptions;
  every builtin base callers catch is preserved.

### Observability

- No silent fallback in the safety path: parser-layer degradation, a dead
  injection oracle, calibration failure, identity-verification failure and
  a crashed correlation model each emit one structured governance event,
  with their fallback semantics unchanged.
- Tracing is structural: spans nest as children, the decision span carries
  its DecisionEnvelope id, governed dispatch emits the OTel GenAI
  `execute_tool` span joined on the proposal id, and the authority→executor
  hop propagates W3C trace context.
- `/v1/health` reports the observed oracle-swarm size instead of a
  constant; the MCP server no longer silences warnings process-wide.

### Verification and CI

- Capability freshness binds to evidence-file content rather than commit
  count, so squash-merges no longer produce false staleness.
- A shipped-surfaces matrix names every advertised surface and the CI jobs
  that guard it, enforced with an additive ratchet.
- The execution TCB's injected collaborators are typed against structural
  ports, with conformance of every production implementation proven by the
  mypy gate.

### Security

- CodeQL triage to zero open security-severity alerts: a ReDoS in the
  admission-path coercion heuristic, two SSRF vectors in the pilot console,
  and error-detail exposure in the Cloudflare Workers, with the remaining
  alerts dismissed only with verified written reasons.

### Repository hygiene

- Simplified the public README and documentation index around one canonical runtime reading path.
- Added explicit CORE / OPTIONAL / EXPERIMENTAL / HISTORICAL boundaries for developer handoff.
- Added branch lifecycle and documentation-style rules to the contribution guide.
- Removed committed local frontend planning state and ignored future `.lovable/` workspace files.
- Added automatic deletion of branches with merged-PR evidence while preserving open and unverified branches.
- Preserved research history while removing older thermodynamic/statistical-physics work from the primary runtime documentation path.

### Execution assurance

- Added explicit `development`, `research`, `review` and `controlled_pilot` runtime profiles.
- `review` and `controlled_pilot` fail closed unless Signed ToolSpec, trusted signer identity, deployment-owned callable registry, durable execution state and PDP signing prerequisites are present.
- Clarified that `/v1/execution/*` is the enforcing surface and that advisory assessment APIs do not control bypass credential paths.

## 0.10.0 — 2026-07-25

### Licensing

- Moved new REMORA versions to Business Source License 1.1 with separate commercial licensing.
- Added licensing, copyright, trademark and third-party notice material.
- Added a CI policy check for license metadata drift.

### Research and assurance

- Continued the claim-register, capability-register, reproducibility and negative-result governance model.
- Preserved benchmark caveats and superseded findings as part of the evidence record.

For detailed changes between revisions, use Git history and merged pull requests.
