# Changelog

This file lists externally relevant changes by release. Fine-grained development history remains available in Git commits and pull requests; the pre-cleanup changelog remains recoverable from repository history rather than being duplicated as a current documentation artifact.

## Unreleased

### Added

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
