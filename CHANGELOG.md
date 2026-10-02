# Changelog

This file lists externally relevant changes by release. Fine-grained development history remains available in Git commits and pull requests; the pre-cleanup changelog remains recoverable from repository history rather than being duplicated as a current documentation artifact.

## Unreleased

### Added

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
