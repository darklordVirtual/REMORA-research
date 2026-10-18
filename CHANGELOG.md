# Changelog

This file lists externally relevant changes by release. Fine-grained development history remains available in Git commits and pull requests; the pre-cleanup changelog remains recoverable from repository history rather than being duplicated as a current documentation artifact.

## Unreleased

### Peer-review remainder: approver role, threat model, timestamp proof (PRF-015, PRF-026, PRF-041, PRF-042)

- `scripts/execution_chain_attack_eval.py` adds an `approver_role` class that
  runs the real `_enforce_review_approval_role`. REMORA ran none of its 6
  attacks and the policy-only gateway ran 2. All 4 controls ran. Over all
  chain classes REMORA ran 0 of 43 attacks and the gateway 33
  (NEGATIVE_RESULTS.md §87).
- Paper §3.1 now states that the decision reads neither argument content nor
  destinations, and that the injection pattern list is a routing hint. The
  abstract, contribution 1 and §13.13 cite the post-hoc evaluation instead
  of saying the chain is unevaluated, in both the .md and the .tex.
- The OpenTimestamps proof of `seal_manifest_2026-10-18.json` is upgraded
  with Bitcoin attestations in blocks 972029 to 972057.
- Register: PRF-015 is RESOLVED, with its limits stated, and PRF-042 moves
  to IN_PROGRESS. PRF-026 and PRF-041 stay IN_PROGRESS: the SAP v7 stamp and
  a decision path that reads the flow verdict (IFC-05b) remain.

### Interop: effect-evidence-v2 carries call binding, decision and observer (#918)

- New DRAFT package `artifacts/interop/effect-evidence-v2` on edge `E-EE-V2`.
  Each case adds the invocation, the captured decision bound to a call, the
  call the bundle is bound to, the executor and the observer.
  `EFFECT_VERIFIED` now needs all three facts. The v1.1 comparison is
  unchanged. The 32 v1.1 cases are carried with a bound lineage and keep
  their outcomes, and 22 repair cases are new.
- `remora/interop/boundary_fixtures.py` evaluates v2 through
  `verify_receipt` and an `ObservationVantage` built as the signed-receipt
  endpoint builds it. Eight new L0 author records agree on all 54 cases.
- The invocation axes reproduction job also pairs Probity's 22 bundles with
  the v2 verifier. `bundle_for_other_call`, `dispatched_after_deny` and
  `observation_from_the_tool` are refused, and 19 of 22 agree. v2 is
  stricter than the reader on `decision_absent`,
  `decision_bound_to_other_request` and `member_missing`, and
  `EXPECTED_V2_SPLIT` pins that split.
- `effect-evidence-v1` and `v1.1` keep their bytes and records. v1.1 is
  marked `superseded_by` v2, and the v1 limit stays recorded as a preserved
  negative result.

### Review path binds the intent authority (RMR-AUD-006, part 3)

- An item approved under one intent authority executed under another, and the
  new `intent_authority_hash` was signed into the grant, the lease and the
  audit record. The review path now compares it with the `assessed` record,
  as ACCEPT-token redemption does. A difference is 409 `context_mismatch`
  with `intent_authority_hash` in `mismatched`, and the approval is not
  consumed.

### Review path binds the whole proposal (RMR-AUD-001, binding part)

- The proposal fields outside `canonical_tool_call_hash` (`schema_valid`,
  `rollback_available`, `untrusted_context`, `intent_ref`, `derivations`, task,
  `plan`, `task_type`, `request_ref`, `delegated_executor`) could differ
  between assess and execute. A call assessed as ESCALATE because of one downgrade could be
  approved and then executed as a VERIFY by dropping it and adding another.
  The `assessed` record now carries `proposal_envelope_hash`, and
  `POST /v1/execution/execute` refuses a different proposal with 409
  `binding_refused` before the approval is touched. Items assessed before this
  change carry no hash and are refused, so they must be proposed again.
  `tests/test_execution_api.py::test_riskier_world_invalidates_approval_at_execution`
  simulated a riskier world by re-presenting `rollback_available=false`. That
  is now a refused proposal, so the test makes the world change on the server
  side, and a new test pins the refusal.

### Approved escalations execute (RMR-AUD-002)

- An approved ESCALATE re-decided on the observation the reviewer saw was
  ESCALATE again, and the re-gate voided every fresh ESCALATE, so no approved
  escalation could execute. The review queue now records each item's decision
  reasons (`requested_reasons`), and the approval records them as
  `approved_reasons` (also on the `approved` event). An approved ESCALATE
  survives a fresh ACCEPT, VERIFY or ESCALATE whose reasons are all among the
  approved ones. A new reason or a fresh ABSTAIN still voids it. Items
  enqueued without reasons keep the earlier rule.

### Delegated execution and approval policy binding

Follow-ups to the review-path binding below. The default stays fail-closed.

- Opt-in delegated execution. A proposal may name `delegated_executor`. It is
  admitted at `POST /v1/execution/assess` only when
  `tenant_access.<tenant>.delegated_executors` in the risk-profile config
  declares that service identity for the proposing agent. Otherwise the
  assessment is refused with 409 `delegate_not_declared`,
  `delegate_cross_tenant` or `delegate_is_proposer`. The shipped config
  declares none. The delegate is recorded in the `assessed` record, bound into
  the `AuthorizationContext` hash, shown by `GET /proposals/{id}` and
  `POST /approve` and recorded on the `approved` event. It may execute on the
  review path and redeem the ACCEPT token. A delegate added, swapped or stripped
  after assessment, or any other principal, is `context_mismatch`. The delegate
  cannot approve the item (403 `approver_is_delegated_executor`).
  `execution_authorized` records `acting_for`. Without a delegation, behaviour
  is unchanged.
- Approvals are bound to the requirement that admitted the approver. The
  approval and the `approved` event record `approver_role`, `required_role`
  and `approval_policy_hash`. At execution, and at the async worker's
  dispatch re-gate, a requirement that changed (for example an edited
  `schemas/risk-profiles.yaml` and a restart with the item in a durable queue)
  voids the approval as `approval_invalidated` (`approval_policy_changed`) and
  returns the item for approval under the current rule. An approval without
  the record, including one persisted before this change, is voided the same
  way (`approval_policy_unbound`). Durable approvals pending at upgrade
  therefore need approving again.
- `AuthorizationContext` gains `delegated_executor`, which enters the hash
  only when set, so existing tokens and golden vectors are unchanged.

### Review path binds actor, task and reviewed risk tier (behaviour change)

Fixes the two review-path defects measured by the execution-chain attack
evaluation (PR #932, `scripts/execution_chain_attack_eval.py`).

- `POST /v1/execution/execute` refuses an approved item presented by a
  principal other than the proposer, or under a task other than the
  proposal's (including a task stripped or added), with 409
  `context_mismatch` and an `execution_context_refused` chain record naming
  the mismatched fields. The comparison is the ACCEPT token's
  `AuthorizationContext` hash, with the approved side read from the
  `assessed` record. It runs before the queue is touched, so the approval
  stays usable by its proposer. A proposal whose assessment cannot be read
  back is refused as `context_unbound`.
- `ReviewQueue.execute` and `ReviewQueue.regate_authorized` void an approval
  when the observation's risk tier differs from the one the approval was
  reviewed at (`reviewed_risk_tier_changed`), even when the fresh decision is
  still VERIFY. The item re-enters the queue with the fresh observation, so
  re-approval is checked against the role the current tier requires
  (`domain_expert` at high, `senior_authority` at critical).
- Callers that executed another principal's approved item, or relied on an
  approval surviving a relabel, now get a refusal. ACCEPT-token and lease
  semantics are unchanged.

### Breaking: `/v1/assess` and the adapters need registry labels to reach ACCEPT (RMR-AUD-011)

- Before this change, with a confident oracle ensemble, `POST /v1/assess`
  for `xfer` labelled `risk_tier=low`, `action_type=read` returned ACCEPT,
  and so did an action-gate adapter given the same labels
  (`should_execute=True`). Both now return VERIFY.
- `/v1/assess` with a `tool_call` takes the labels from the server's
  registry (`resolve_tool_metadata`, as `/v1/execution/*` does). The
  request's `risk_tier` may only raise the tier, an `action_type` that
  differs caps ACCEPT (`registry_label_conflict`), and an unclassified tool
  is critical/unknown.
- `/v1/assess` without a `tool_call`: the labels are the caller's, and an
  engine ACCEPT becomes VERIFY with `caller_labels_untrusted`, in the
  response and in the stored envelope. Clients that relied on ACCEPT from
  `/v1/assess` must send a `tool_call` for a tool the server classifies.
- The response and the audit record gain `label_source`; the response
  also gains `label_cap`. `/v1/rerun` keeps ACCEPT only for a record whose
  labels came from the registry.
- `remora/adapters/`: every action-gate adapter takes `registry=`.
  Without it an ACCEPT becomes VERIFY, and `ActionGateResult` gains
  `label_source`/`label_cap`. `HttpGateway` sends the `tool_call`, and
  `GatewayResult` gains `label_source`/`label_cap`. The four framework
  examples declare a deployment registry. Their outcomes are unchanged.
- No committed benchmark or published result runs through `/v1/assess`
  or the adapters, so no published number changes.

### Breaking: library labels need a registry to reach ACCEPT (PRF-040)

- `assess_tool_call` and `what_if_tool_call` take `registry=`, a mapping
  from tool name to `risk_tier`/`action_type` (the
  `REMORA_TOOL_METADATA_FILE` entry shape; `remora.assess.load_tool_registry`
  reads that file). Before this change
  `assess_tool_call("xfer", {"to": "attacker", "amt": 1e6}, risk_tier="low",
  action_type="read", trust_score=0.95, phase="ordered")` returned ACCEPT
  with `should_execute == True`. It now returns VERIFY.
- Labels passed as `risk_tier=`/`action_type=`, or filled by `infer=True`,
  can no longer produce ACCEPT. The engine still runs; an ACCEPT is lowered
  to VERIFY with the added reason `caller_labels_untrusted`, which also
  appears in the envelope's `policy_triggers`. Code that passed labels as
  keyword arguments and acted on `should_execute` must pass `registry=`.
- Next to a registry, a caller `risk_tier` may raise the tier, and a caller
  `action_type` that differs from the registry caps ACCEPT
  (`registry_label_conflict`). A tool the registry does not name is assessed
  as critical/unknown (`tool_not_in_registry`).
- `ToolCallAssessment` gains `label_source` (`registry`, `caller`,
  `inferred`, `unregistered`, `none`) and `label_cap`; `to_dict()` carries
  both. `should_execute` is True only for ACCEPT with
  `label_source == "registry"`.
- CLI: `assess`, `explain` and `whatif` take `--registry PATH` and report
  `label_source`/`label_cap` in `--json`. Without it, an engine ACCEPT is
  shown as VERIFY, so `assess --exit-code` returns 10 instead of 0 for such
  calls. `assess --live` applies the same cap to the decision and envelope.
  The `try` presets take their labels from a demo registry fixed in
  `remora/cli.py`, so their verdicts are unchanged
  (`artifacts/demo/whatif_presets_v1.json` regenerates identically).
- Not changed: the `/v1/execution` path, the engine, hard guards, and the
  action-gate adapters in `remora/adapters/`, which forward caller labels to
  a gateway and do not call `assess_tool_call`.

### Security (Worker effect receipts and agent-control review path, RMR-AUD-004 and RMR-AUD-010)

- **MCP gateway effect read-back checked the tool against itself.** The
  expected values came from the tool's own result, so a tool that wrote other
  values and reported them faithfully came out `EFFECT_VERIFIED`. The
  expected values now come from the approved arguments; the result only
  locates the row, and the row must be created after the dispatch began and
  sit in the approved graph. The read-back also runs on the ACCEPT path.
- **No gateway receipt was ever recorded.** Receipts went to the review item
  id instead of the proposal, without `tool_call_hash`, `grant_jti` or
  `verified_at`, under an identity no principal was bound to; REMORA refused
  every one, the refusal was dropped in an empty `catch`, and the model was
  told `EFFECT_VERIFIED`. The receipt now carries the binding from REMORA's own
  assess and execute responses and goes out under a separate verifier
  credential (`REMORA_EFFECT_VERIFIER_TOKEN`, `REMORA_EFFECT_VERIFIER_IDENTITY`),
  never the agent's. `effect` is REMORA's recorded verdict only;
  otherwise the model gets `effect_observation` and `effect_record` with the
  reason nothing was recorded. `tests/test_mcp_gateway_effect_receipt_contract.py`
  runs the real gateway code against the real recorder.
- **A lapsed approval read as an unknown dispatch.** `approval_invalidated`
  and `approval_expired` come back as 200 with no `tool_execution`; the
  gateway reported "outcome unknown, may have run, do not retry" and deleted
  the proposal, so a re-approved item could not be redeemed. Both now report
  `pending_approval` and keep the proposal; `binding_refused` reports a
  refusal.
- **agent-control accepted Access tokens from other teams.** Its own Access
  verifier never checked `iss` and did not normalise the team domain. Both
  Workers now use one verifier, `workers/shared/access_jwt.ts`, and a parity
  test runs the same tokens through both.
- **agent-control approvals hashed insertion order.** The approval hash was
  `sha256(JSON.stringify(input))`, so the same call with its keys in another
  order was refused after approval. It is now the canonical tool-call hash
  over tool, tenant, target and arguments. Approvals pending at deploy time
  were made under the old hash and will be refused; re-approve them.
- **agent-control could not run an approved canonical review item.** With
  `EXECUTION_SERVICE` bound every retry assessed again, opened a new review
  item and answered 402. A request with `input.review_item_id` now redeems that
  item through `/v1/execution/execute`.

### SAP v7 addenda: InjecAgent and external routing baselines (pre-registration only)

- SAP v7 §12 to §15 pre-register two studies before any data exists (owner
  decision 2026-10-18). Q6 runs InjecAgent (`f19c9f2c`, MIT) through
  `/v1/execution/assess` against allow-all and a policy-only gateway, with
  benign twin controls (PRF-042). Q7 compares REMORA with an LLM judge and
  Invariant Guardrails on BFCL v4 multi-turn (gorilla `6ea57973`), with
  model-generated wrong calls and no constructed producers (PRF-010, PRF-011,
  PRF-013). Nothing has been run; the plan stays a draft until the owner
  approves and seals it.

### Routing: semantic bundle v3 keeps qualifiers (RMR-AUD-009)

- Bundle v2's intent extractor grounded a mutation in a conditional or a
  question: "Inspect booking B-104 before cancel.", "Tell me if I can cancel
  booking B-104." and "Review the policy before we cancel booking B-104." each
  supported `cancel_booking`. v2 checks negation only and passes goal
  matching the bare keyword, so `goal_match`'s conditional check never sees
  the qualifier.
- `remora/toolcall/routing/bfcl_semantic_bundle_v3.py` changes intent
  extraction only. A mutation keyword with a conditional word in the four
  words before it, or framed as a question ("tell me if", "can I", "is it
  possible to"), grounds nothing. Action spans quote up to three preceding
  words of the clause. Contract authoring is v2's, re-exported.
- v2, `goal_match.py` and `bfcl_arms.py` are unchanged: the C-ext4 manifest
  pins their hashes. v3 is wired into no runner and supports no claim.
- `scripts/bfcl_v3_extractor_dev_compare.py` routes the three spent
  development sets under V2D with each extractor
  (`artifacts/posthoc/bfcl_v3_extractor_dev_compare.json`, development only).
  v3 accepts the same gold calls as v2 on all three sets and no wrong call.
  Four routes change, all on one task where v2 read "if I set the capture
  percentage" as an update request and refuted the correct read tool; v3
  sends them to VERIFY instead.

### Security (effect evidence follows an authorized dispatch; audit keeps every approval, RMR-AUD-004/005)

An external audit on 2026-10-18 reproduced these on the Python runtime.

- **Effect after a deny.** `resolve_lineage` read only the last
  `execution_result`. A trail that also held an ABSTAIN assessment or a
  rejection accepted an effect receipt, and the proposal read
  `EFFECT_VERIFIED`. The lineage now requires an assessment that may
  dispatch, no rejection, an approval for a VERIFY or ESCALATE decision, and
  an `execution_authorized` record with `pep_allowed: true` for the same
  grant and call. Refusals: `dispatched_after_deny`,
  `assessment_decision_unknown`, `dispatched_without_approval`,
  `dispatch_not_authorized`. The surface runtime, whose chain has no decision
  records, opts out explicitly (`require_decision_path=False`).
- **The executor as its own verifier.** Recording an effect needed the
  `execute` capability, and with `REMORA_EFFECT_VERIFIER_BINDINGS` unset the
  verifier identity only had to equal the principal, so the agent that ran a
  call could attest to it. There is now a `verify_effect` capability and an
  `effect_verifier` role. In production and under the strict profiles:
  - `verify_effect` is required;
  - the bindings must be set (503 `effect_verifier_bindings_required`);
  - a principal that proposed or executed the call is refused (403
    `verifier_is_executor`).

  A development deployment outside the strict profiles still accepts
  `execute` and the executor's own receipt. The record and the projection
  then carry `self_attested: true`.
- **Evidence about another object.** `verify_declared_delta` never read
  `PostconditionContract.target_selector`. An observed selector field that
  differs now returns `EFFECT_UNOBSERVABLE` with
  `postcondition_target_mismatch`. A selector field the reader does not
  return is still not compared. The surface runtime refuses a contract whose
  selector names another object than the call's arguments
  (`postcondition_target_not_call_argument`).
- **Dropped audit events.** The outbox key for `approved` named only the
  item, so an approval after an expired or invalidated one was dropped from
  the chain. The same held for a second re-gate refusal on one item. The key
  now carries the approval's issue time, or a per-attempt id for refusals.
  The key of a first approval changes bytes; the event does not.
- **State stuck at REFUSED.** `current_state` returned `REFUSED` once any
  refusal had been recorded. It is now a fold in chain order. A binding or
  context refusal leaves the approval standing (`AUTHORIZED`). An expired or
  invalidated approval returns to `REVIEW_PENDING` until it is approved
  again. An effect counts only when its lineage holds.
- Not changed: the frozen `effect-evidence-v1` schema and its reference
  verifier, the Worker gateway's effect submission, and the review-queue
  re-gate.

### Security (Worker edge refuses repeated JSON members, NEGATIVE_RESULTS §86)

- Both Workers parsed request bodies with `JSON.parse`, which keeps the last
  value of a repeated member, and re-serialised the call without the
  duplicate. The API's strict ingress (`json_duplicate_member`) therefore
  never saw it, and a first-value reader of the same bytes would read another
  call. `parseJsonStrict` (byte-identical in `mcp-gateway` and
  `agent-control`) now refuses a repeated member name after decoding, and
  both edges answer it as they answer an unsafe number.
- `NEGATIVE_RESULTS.md` §85 (open) records that `EFFECT_VERIFIED` does not
  attribute the observed delta to the dispatch; §86 (accepted) records this
  finding and its fix.
- Three adversarial probes hold, each pinned by a test:
  - P1: a batch member's grant does not redeem for its sibling, although
    both share a body digest.
  - P2: a grant issued before a policy revision is refused unspent, and
    redeems once the policy is back.
  - P3: an advisory `assess_tool_call()` ACCEPT carries no grant, nothing on
    the enforcing path imports it, and the strict gate refuses it.
    PRF-040 stays OPEN, because the advisory result is still called ACCEPT.

### Interop (effect-evidence-v1 limits found by the invocation axes corpus, #918)

- Probity's `invocation_axes` corpus at `d2bdacc7` (23 cases, 22 bundles)
  was reproduced locally against the frozen `effect-evidence-v1` verifier: 19
  bundles agree on the binary observed-effect result. On
  `bundle_for_other_call`, `dispatched_after_deny` and
  `observation_from_the_tool` the verifier returns `EFFECT_VERIFIED` and
  Probity's reader does not.
- `docs/interop/FEDERATION.md` records why. The v1 input has no field for the
  call binding, the observer or the captured decision. The first two were
  already v1 non-claims. Decision correspondence was not, and is now stated as
  a limit of v1 and v1.1. The frozen package and its records are unchanged,
  and none of this is a REMORA runtime result.
- `tests/test_effect_evidence_v1_projection_limits.py` pins the limit: bundles
  that differ only in one of those facts project to identical v1 input and get
  identical verdicts.

### Interop (per-invocation evidence export and request binding)

- New `remora/execution/request_ref.py`: a call may carry the request it
  arrived in, as the transport, the JSON-RPC id's canonical JSON text and the SHA-256 of
  the body bytes as received. At ACCEPT its digest enters the
  `AuthorizationContext` and so the signed grant. Redemption under another
  reference, or with it stripped, is refused as `context_mismatch` before the
  grant is spent. A context without one hashes exactly as before.
- The MCP gateway digests the body bytes before decoding and sends the
  reference on every `tools/call`.
- On the direct-ACCEPT path the chain now keeps the grant, in
  `execution_authorized` after the gate has consumed it, and the lease, in
  `execution_result` after dispatch. The assessed record keeps the
  authorization context fields the grant's `context_hash` covers.
- New `GET /v1/execution/proposals/{id}/invocation-evidence`
  (`remora/execution/invocation_evidence.py`). It returns the three chain
  entries with the strings their hashes cover, the grant and lease with the
  bytes their signatures cover, and one Ed25519 signature over the whole under
  `REMORA/EVIDENCE/v1`. The new key `REMORA_EVIDENCE_SIGNING_KEY_ED25519_PRIVATE`
  is declared in the credential topology register.
- New `integrations/invocation-evidence/`: a verifier that imports no REMORA
  code and needs public keys only, seven fixture cases made through the server
  path, and a README. Two requests with the same call are told apart:
  `request_corresponds` is CONTRADICTED for the other request while
  `call_corresponds` stays ESTABLISHED.
- `tests/test_invocation_evidence_export.py` (24 tests) and three gateway
  tests. Four of them attack the chain end to end: a grant presented with
  another call is refused before dispatch, a denied call gets no grant and
  no export, an export rewritten to hide a deny is CONTRADICTED, and the
  tool's own result never becomes an observed effect (`effect_observed` is
  always NOT_ESTABLISHED). The verifier, the export and the cases are REMORA's own, so nothing
  here is an independent result.
- Two findings of an external design review of this PR are fixed. F-10: the
  JSON-RPC id is recorded in canonical form (a string without lone surrogates
  or a safe integer, as `JSON.stringify` writes it), not as wire bytes, and the
  docs no longer say otherwise. `fixtures/jsonrpc-id-vectors.json` (18
  vectors) is checked by the gateway, the server and the verifier. F-11: the
  verifier hashes the call over the same JSON domain enforcement accepts
  (no `default=str`), and it refuses duplicate keys and NaN/Infinity in every
  JSON it reads, signed or not.
- The twelve capabilities whose sources this touched (CAP-003, 004, 005,
  007, 013, 018 to 024) are re-audited and rebound to the code commit, with
  their evidence tests passing. Their mechanism, status, scope and caveats are
  unchanged. The boundary declaration and its summary are repinned.

### SAP v7 addenda: InjecAgent and external routing baselines (pre-registration only)

- SAP v7 §12 to §15 pre-register two studies before any data exists (owner
  decision 2026-10-18). Q6 runs InjecAgent (`f19c9f2c`, MIT) through
  `/v1/execution/assess` against allow-all and a policy-only gateway, with
  benign twin controls (PRF-042). Q7 compares REMORA with an LLM judge and
  Invariant Guardrails on BFCL v4 multi-turn (gorilla `6ea57973`), with
  model-generated wrong calls and no constructed producers (PRF-010, PRF-011,
  PRF-013). Nothing has been run; the plan stays a draft until the owner
  approves and seals it.

### Flow control (RMR-AUD-007, RMR-AUD-008: recipients, FL-01, FL-14, handle references)

- `flow_check` passed a secret payload as clean when the recipient argument
  of a derived sink (`from_args`, `url_host_of`, `iban_of`, `resource_of`)
  was `[]`, `null` or missing. Such a rule now reports each argument it
  reads as `unresolved:<argument>`. An absent `cc` beside a resolved `to`
  is still allowed.
- FL-01 refuses a `url` argument that is not the `url_host_of` argument, and,
  on a tool that writes, an `email` or `iban` argument the recipients rule
  does not name. Before, it caught only `url` under `recipients: none`.
- New lint rule FL-14 refuses a BY_VALUE field rule under a container with
  no BY_VALUE rule. The container is rendered as one handle (SDD §3.2.1), so
  the field was never shown. The SDD's §5.1 `get_inbox` excerpt fails it as
  written; the status document records the inconsistency.
- `HandleStore.resolve` resolves the unchanged `{"$handle", "$type"}`
  reference the model is shown as a whole handle. Before, the tool received
  the wrapper object.
- Not changed: a container without a rule is still one handle, and result
  labels still join the call's argument labels. Both follow SDD §3.2.1 and
  §3.3; the reasons are in
  `docs/design/derived-information-flow-control-v1-status.md`.
- No committed ToolSpec bundle carries a `flow` block, so no signed bundle
  changes. `remora/flow/spec.py` is in the policy bundle hash, which
  changes.
### Policy (signal monotonicity, RMR-AUD-003)

- A refusal no review can lift now outranks an ESCALATE. A cross-tenant
  argument or an unresolved intent provenance stays ABSTAIN, with no review
  item, when `schema_valid=False`, `adversarial_detected` or
  `tool_forbidden` also fires. Before, those guards came first and turned
  the refusal into a review item. `NON_APPROVABLE_REASONS` in
  `remora/policy/composition.py` names the set, which the OPA adapter
  already used.
- The conditional gates compose by meet. An early VERIFY gate
  (`distribution_shift`, `high_risk_no_evidence`, `oracle_quorum_gate`) no
  longer hides a later ESCALATE gate such as `rollback_unavailable` or
  `env_mismatch_escalate`. The trap and minimax gates still yield to the
  explicit risk matrix, so high-risk production writes stay VERIFY.
- `ADVERSARIAL_ALWAYS_ESCALATED` accepts ABSTAIN when a non-approvable
  refusal also applies.
- Decisions change only toward stricter: 17,166 of 60,000 generated
  decisions, none looser. C-ext3 (0 of 8,397 episode-arm decisions) and
  every published count are unchanged.
- Still open: a risk signal on a call that abstains for lack of evidence
  opens a review route, and raising a production write from medium to high
  risk lowers ESCALATE to VERIFY. Both need an owner decision
  ([ADR](docs/architecture/ADR-flow-meet-composition.md#amendment-2026-10-18-rmr-aud-003)).

### Security (MCP gateway readiness fails closed)

- The `/mcp` route acted on readiness problems only when the profile was
  exactly `production`. An unset or misspelt profile (`prod`) served calls
  with every problem reported and none acted on. It now refuses on any
  readiness problem in any profile.
- `REMORA_API_URL` (the local direct transport) skipped Cloudflare Access
  verification in any deployment that set it. Admission now allows it only
  under the `development` profile, and readiness names it as a problem
  everywhere else. Found by an internal code review on 2026-10-18.

### Federation interop (invocation axes reproduction)

- `.github/workflows/probity-invocation-axes-reproduction.yml` runs Probity's
  `invocation_axes` reader from agent-evidence-vectors at a pinned commit, then
  hands each of its execution bundles to the effect-evidence-v1 reference
  verifier at the frozen revision. It records where the two agree on the
  observed effect and fails if the split changes. It is a `REPRODUCTION` and
  advances nothing.
- The job also asserts the corpus shape at the pinned reader: 23 unique
  cases, 22 paired bundles, and `no_execution_bundle` as the only case
  without one. The split alone stayed green if bundles went missing. The
  agreement it reports is named `observed_effect_binary_agree`, because it
  compares only REMORA's `EFFECT_VERIFIED` with the reader's `ESTABLISHED`.
### Interop (E6 consumer for Veritas Acta receipts, author run)

- New `remora/interop/acta_e6/` (EXPERIMENTAL): a paying-side consumer for
  edge E6, written from the `VeritasActa/e6-fixture` `v1.1.0` README alone.
  It uses its own Ed25519 (`cryptography`) and JCS (`remora.interop.jcs`)
  and does not call `@veritasacta/verify`. Results stay in Acta's
  vocabulary and are not admitted as REMORA evidence.
- `scripts/run_acta_e6.py` checks the `SHA256SUMS` pin and every file, runs
  the cases and a signature-blind control, and writes
  `integrations/acta-e6/records/remora-e6-consumer-v1.1.0.json`. From a
  fresh clone at `8d8fc50a` (`SHA256SUMS` `08731bb7…`), the consumer agrees
  with 12 of 12 cases on the verdict, all eight claims, every code and
  `payment_ready`. The control agrees with 9 of 12. It returns `PASS` on case
  12 and differs on 07 and 08 in codes only, with the verdict still `FAIL`.
- REMORA wrote and ran the consumer, so this is a second implementation's
  author run, not an independent record under the boundary map's rule.
- `tests/test_acta_e6_consumer.py`: 12 tests over the vendored subset, the
  committed record, pin refusals and the failure paths no case reaches.
### Evidence COMP-01 (AgentHarm re-score, post hoc)

- `scripts/comp01_agentharm_rescore.py` writes
  `artifacts/posthoc/comp01_agentharm_rescore_v1.json`, recorded as
  NEGATIVE_RESULTS §84. CLAIM-002 is unchanged.
- **Composition set** (88 trimode tasks), at the hard-block point:

  | Arm | Harmful stopped | Twin pairs told apart | AUROC |
  |---|---|---|---|
  | Old composition | 6/44 | 4 | 0.545 |
  | Meet composition (oracle as a monitor cap) | 44/44 | 37 | 0.920 |
  | Oracle alone | 44/44 | 38 | 0.932 |

  The meet blocks 7 of 44 benign tasks. H6 holds.
- **Threshold set** (CLAIM-002's 416 rows): the threshold calibrated on a
  development half split by behaviour blocks nothing at a 10 % false-block
  budget. Blocking starts only at a 50 % budget.

### README for a first-time visitor

- The README now opens with one sentence on what REMORA is, the four
  decisions, and a two-minute "Try it" block. The block shows real
  `whatif` output: no model signal reaches ACCEPT for a production
  `drop_database`.
- A short section explains why REMORA is built this way.
- The findings are stated in plain language: blocking is the easy half,
  usefulness is open, a floor is not a judge, we publish what fails, and
  the adversarial test is next.
- The detailed evidence table, the reading path and the step-by-step
  dispatch path are unchanged but collapsed below. Next steps are grouped
  by reader: research, code, or another project.

### Research control matrix (RES-023, RES-024)

- RES-023 covers semantic authority for tool routing: declared contracts,
  a re-derived intent, the UNKNOWN floor and derivation receipts, evaluated
  on the sealed C-ext3 and C-ext4 BFCL tracks. Its scope limits come from
  §39, §81, §82 and §83.
- RES-024 covers authority-preserving effect mediation (NTA-2: mediator,
  effect domain, custody split). It builds on the confused deputy (Hardy,
  1988) and object capabilities (Miller, 2006).
- Both rows are internal designs (`in_code_citation: false`).
  docs/09-related-work.md gains §15 and §16 to anchor them.
- The register's `updated` field moves to 2026-10-17.
- PRF-043 records that the paper does not cite BFCL.


### Policy COMP-01 (meet composition, P-MONO)

- `RemoraDecisionEngine.decide` now returns the least executable of its
  component groups (`ABSTAIN ≡ ESCALATE < VERIFY < ACCEPT`). The groups are
  the cascade, the hard-guard floor, the conditional-gate group, and any
  external `caps` (new reason codes `monitor_cap` and `protocol_cap`).
  Before, a first-match VERIFY from the taint floor masked a conditional
  gate's ESCALATE or ABSTAIN, so an ordinary approver could redeem a call
  another component had sent to a higher authority.
- Decisions change only in the stricter direction. On a 30,000-observation
  search in two engine configurations, 1,784 masked decisions were found.
  The OPA golden cases, the tool-call benchmark, C-ext4 and the AROMER arena
  are unchanged. One C-ext3 episode moves from VERIFY to ABSTAIN, and no
  published count changes.
- §3.9 composes groups, so the order inside `_CONDITIONAL_GATES` is kept. A
  per-gate meet would have turned 13 benign AROMER arena VERIFYs into false
  ESCALATEs. `docs/architecture/ADR-flow-meet-composition.md` records this
  finding.
- `composition.py` joins the policy bundle hash. `explain()` takes the same
  caps and shows a `meet_composition` row. P-MONO is checked as a Hypothesis
  property in `tests/policy/test_meet_composition.py`, and the never-weakens
  tests cover monitor and protocol caps. The version label stays
  `RemoraDecisionEngine-v5`; the SDD reserves v6 for the flow rungs.

### Flow control IFC-03b (ToolSpec v4 at bundle load)

- The ToolSpec bundle loader accepts `schema_version: 4`. A `flow` block in
  an older bundle is refused (`toolspec_flow_requires_v4`). Every block is
  parsed and linted at load, so a correctly signed block that breaks a rule
  does not load (`toolspec_flow_invalid`, `toolspec_flow_lint_failed`).
  `ToolSpec.flow` carries the parsed block.
- Under a strict runtime profile with `REMORA_FLOW_CONTROL=1`, startup
  refuses a bundle in which any spec has no block (FL-13).
- `remora/flow/label.py` and `remora/flow/spec.py` join the policy bundle
  hash, which now covers ten files including COMP-01 composition. Every envelope's `policy_bundle_hash`
  changes value with this release.
- Contracts touched: three additive reason codes in
  `schemas/tool_spec_v1.yaml`; `schemas/tool_spec_v4.yaml` is now
  implemented. Nothing reads `ToolSpec.flow` to decide yet (IFC-05).
### Flow control IFC-05a (recipients and the flow check)

- `remora/flow/check.py`: `recipients` computes who receives a resolved
  call's payload from the ToolSpec sink (email, principal, URL host, IBAN,
  resource ACL, static), plus the provider of a tool outside the TCB. An
  argument that cannot be mapped to one canonical principal (a display-name
  address, a URL with user information or a non-http scheme) is unresolved,
  and the check counts it as a confidentiality violation.
- `flow_check` returns a `FlowVerdict` with the confidentiality, integrity
  (including parameter role binding) and control violations of SDD §3.5,
  and a digest over the violations and the payload label for the lease to
  bind (§3.8).
- The four invariant tests the SDD makes mandatory for IFC-05 pass at the
  level of the check: a TRUSTED parameter handle satisfies
  `integrity_required` after an untrusted read; the same value retyped does
  not; a parameter in a field that does not accept its role is refused; and
  the payload label includes the context label when only handles are passed.
- Not yet wired: no decision reads the verdict. Rungs F1 to F6 in the
  decision engine are IFC-05b (protected path).

### Flow control IFC-04a (result labelling and handles)

- `remora/flow/labeler.py`: `FlowLabeler.label_result` gives every node of
  a JSON tool result a label from the ToolSpec `flow.sources` rules and
  decides what the model sees. A node is shown by value only when its rule
  says BY_VALUE and its label flows to the model principal; otherwise it and
  everything under it becomes one handle labelled with the join of the
  subtree. Every label is joined with the call's argument labels. The
  labeler is pure: it returns the rendered result, the label to raise the
  context by and the handle records to store.
- `remora/flow/handles.py`: fixed-width `⟦h:…⟧` tokens (80 random bits),
  records valid only in the minting context and its descendants, and
  `HandleStore.resolve`, which substitutes handles anywhere in a call's
  arguments and returns a value label per field (`L_h` for a whole-handle
  field, `L_ctx ⊔ …` otherwise). A foreign, unknown or expired handle is
  refused with `flow_handle_invalid`.
- `remora/flow/render.py`: the agent-facing handle reference, with a type
  tag taken only from a declared field `type` (new optional key in the
  ToolSpec v4 block).
- Two readings of the SDD are stated in the module docstrings. Rules match
  exact paths and are not inherited. A container's structure carries the
  container's own label.
- Not yet wired: no dispatcher calls the labeler (IFC-04b), and handles are
  held in process only; the durable, encrypted backend follows separately.

### Flow control IFC-03a (ToolSpec v4 `flow` block, parser and linter)

- `schemas/tool_spec_v4.yaml` defines the signed `flow` block: `sources`
  (how each result field is labelled and whether the model sees it by value
  or as a handle) and `sink` (who receives the arguments).
- `remora/flow/spec.py` parses a block into frozen data and refuses any key
  it does not define (`toolspec_flow_invalid`). Defaults fail closed: an
  undeclared field is UNTRUSTED, a handle, and readable by the user alone.
- Thirteen lint rules, FL-01 to FL-13, each with a test. They include the
  four the SDD names for IFC-03 (a url argument under `recipients: none`, an
  unknown argument in `integrity_required`, BY_VALUE on undeclared fields, a
  missing block under the strict profile) and the ones §3.3 and §3.5 assign
  to the linter.
- Three fields go beyond the SDD's §5.1 excerpt, because a rule could not be
  checked without them: `provider` (where the tool runs), `arguments` (the
  kind of every argument, since the argument schema refuses `format`) and a
  `disclosure` per source metadata entry. The schema file states why.
- `scripts/check_toolspec_flow.py [--strict] BUNDLE...` lints a bundle
  before signing.
- Not yet wired: the bundle loader does not accept schema version 4 until
  IFC-03b, so no deployment can carry a block yet.
### Flow control IFC-02b (`POST /v1/contexts`)

- `POST /v1/contexts` mints a flow context for the authenticated principal
  and returns `context_id` and `label_epoch`. The caller cannot choose the
  id, the label or the epoch (extra fields are a 422). A child named by
  `parent_context_id` starts at its parent's label.
- **Refusals:** 409 `flow_control_disabled` unless `REMORA_FLOW_CONTROL=1`;
  403 `principal_mismatch` for a user principal outside the caller's tenant;
  403 `processing_not_authorized` for a processor the processing policy
  (`REMORA_FLOW_PROCESSING_POLICY`) does not authorize; 404
  `flow_context_unknown`; 503 `flow_state_unavailable`. Without a
  processing policy nothing is authorized.
- Each mint is recorded on the tenant chain as `flow_context_minted`.
- The store uses the same three durable switches as the loop-safety store,
  declared as wiring point ASW-006 for AST-016, and the Postgres cases now
  run in the CI Postgres job.
- Contracts touched: `schemas/openapi.json` and the generated TypeScript
  client gain the route. No existing route changes. Labels are not yet
  raised by any tool result; that is IFC-03.

### Flow control IFC-02a (context store)

- `remora/flow/context.py` adds `FlowContextStore`, which provides `mint`,
  `fork`, `load`, `raise_label` and `charge_budget`.
- **Contexts:** ids are minted server-side (`ctx_` + 128 random bits). A
  fork inherits its parent's label and shares the root context's budget
  ledger.
- **The label:** it only rises, and there is no lowering or reset API. Every
  raise keeps `flows_to(label, model_principal)`.
- **Minting:** refused with `processing_not_authorized` unless the
  deployment's processing policy authorizes each processor.
- **Event store:** the flow event stream is separate from the loop-safety
  stream, so a loop reset cannot lower a label. `append_if(expected_seq)`
  gives exactly one winner per sequence on the in-process, SQLite, Postgres
  and D1 backends. Concurrency is tested with eight threads on each,
  Postgres in the CI Postgres job. An unreachable store raises
  `FlowStoreUnavailable` and never reads as empty.
- The HTTP route `POST /v1/contexts` follows in IFC-02b (protected path).

### Flow control IFC-01 (label lattice)

- New package `remora/flow/` (EXPERIMENTAL, not wired into any decision).
  `label.py` implements the SDD §3.1 lattice: `Label(readers, integrity)`,
  `join`, `leq`, `flows_to`, `BOTTOM`, `canonical_bytes`, and
  `field_value_label` for §3.4's split between value integrity and context.
  Reader sets are kept as minimal antichains of
  `remora.capabilities.resource` patterns. Patterns form a tree, so the
  pairwise intersection is exact.
- `schemas/value_label_schema.yaml` documents the label contract and its
  pinned serialisation.
- `tests/flow/test_label_lattice.py`: Hypothesis properties for every
  IFC-01 acceptance law, plus exactness of join for flows. Run with three
  seeds. Mutation testing with mutmut kills every mutant except five
  equivalent ones, which the test module names.

### Research (SAP v7 draft and control-evaluation harness, no model call)

- `docs/assurance/statistical_analysis_plan_v7_control_eval.md` (draft, not
  registered) pre-registers seven defences against an untrusted Claude
  agent on AgentDojo v1.2.2: no gate, refuse-all, a per-task allowlist, an
  LLM monitor, REMORA (strict and observed-state) and two floor/monitor
  compositions. It has three confirmatory hypotheses, a split rule, a
  budget rule capped at 50 USD and a disclosure of prior exposure. The
  owner fixes model IDs, prices and the monitor prompt, then registers it
  on OSF.
- `experiments/control_eval/` holds the defences, a REMORA adapter with
  value-level provenance, and the statistics: attack-call labels, McNemar,
  cluster bootstrap, clustered AUROC difference, split and budget guard.
  It also holds the AgentDojo glue, a gated executor that asks a defence
  before each call. `scripts/run_control_eval.py` runs a development dry run
  with a scripted ground-truth agent; the pilot and the test run are
  refused until SAP v7 §9 is settled. 22 tests run without AgentDojo.
- The development dry run is the first finding
  (`artifacts/control_eval/dev_dry_run_v1.json`). On legitimate calls,
  REMORA blocked 90 of 91 and solved 11 of 29 tasks; refuse-all solved 10.
  Bundle v2 grounds no intent in AgentDojo's phrasing.
- `local.env`, which holds the experiment API key, is now in the committed
  `.gitignore`.

### Evidence (execution-chain attack evaluation, PRF-015 and PRF-041)

- `scripts/execution_chain_attack_eval.py` writes
  `artifacts/posthoc/execution_chain_attack_eval_v1.json` (status
  `post_hoc_descriptive`): 52 attacks and 16 benign controls against
  `/v1/execution`, a policy-only gateway with the same proposal-time
  decision, the library flow check (library_only) and the advisory library
  path at master before the PRF-040 fix. Scoring is by the tool body's side
  effect, not the API verdict.
- REMORA ran 4 of 37 chain attacks (replay, substitution, ToolSpec change,
  cross-context reuse, forgery, expiry) and the gateway 31. The secret
  reached the sink in all 11 exfiltration attacks on both. NEGATIVE_RESULTS
  §87 has the table and the four chain attacks REMORA did not stop.

### Evidence (peer-review level 2: post-hoc re-analysis, no sealed number changed)

- `scripts/peer_review_posthoc.py` writes
  `artifacts/posthoc/peer_review_level2_v1.json` (status
  `post_hoc_descriptive`). It first re-routes C-ext3 and C-ext4 and refuses
  unless every published count reproduces. Two C-ext3 argument counts are
  excepted; commit `edd9d144` changed them after the seal without moving any
  ACCEPT. Nine tests pin the statistics and the artifact.
- **Zero-count bounds clustered by tool:**
  - C-ext3: 3.5 %, against 0.76 % by row.
  - C-ext4: 5.42 %, against 1.29 % by row.
  - CLAIM-001 over its harmful templates: 6.42 %.
  - CLAIM-002 over its base behaviours: 7.56 %.
- **What the BFCL wrong calls test:** only 4 of the 295 C-ext4 wrong calls
  name a tool the task offered.
- **Naive name-overlap rules** reach part of the gold-call signal. They also
  accept wrong calls and calls missing required arguments; V2D accepts none
  of those.
- **Tool-clustered paired test for C-ext4:** 19 tools against 2,
  p = 1.1×10⁻⁴.
- **C-ext3 McNemar tests:** the pre-registered arm tests are now run.
- **Paper and records:** the paper (.md and .tex), NEGATIVE_RESULTS.md §83
  (new), docs/06 and the review register carry the results. Nine findings
  changed status.

### Paper (peer-review level 1: corrections without new numbers)

- New `docs/review/PEER_REVIEW_FINDINGS.md` lists 39 objections from an
  adversarial review of the paper at `f66c4f7b`. It gives each one's
  evidence, affected claims, action, owning PR, verification and status. The
  review used four AI reviewer agents, so it is not an independent review.
  At the end of this PR, 18 objections are resolved, 3 accepted as
  limitations, 8 in progress and 10 open. `tests/test_peer_review_findings.py`
  refuses a RESOLVED entry without a verification.
- The .md and .tex now state what the evidence supports:
  - The .tex oracle-count result was reversed against the .md and the
    artifact. It is now corrected.
  - The zero-unsafe result is no longer attributed to the deterministic
    floor.
  - The C-ext3 joint hypothesis is reported as not supported.
  - The BFCL tracks are described as routing annotated proposals, and their
    wrong calls as cross-task substitutions.
  - C-ext4's targets are called floors, and the refuse-all control and the
    V2 arm are reported beside them.
  - AgentHarm Mode 3 cites the twin-pair result (§80). The C-ext3 intents
    cite the negation limit (§81).
  - CLAIM-014 gives 60/60 against 0/60.
  - A new §13.13 states that the execution chain is not evaluated against
    attacks and that per-call authorization does not stop composed attacks.
- The .tex gains the limitations the .md already had, and its stale
  "32-case" cross-domain mention is replaced with the 36-case benchmark.
- Wording and consistency: "theoretically optimal", "provably", "proves",
  "immutable" and "non-overlapping CIs" are corrected. Appendix F and the
  AII regression now match the claim register, and a wrong cross-reference
  is fixed.
- The roadmap records that the owner put the paper revision ahead of the
  remaining roadmap items. Its wrong-call constraint was stated as a Wilson
  bound; it now reads as SAP v6's point-estimate target.
- No result file, claim register entry or sealed artifact changed.
  Re-analyses (clustered bounds, naive baselines, pre-registered pairwise
  tests) are level 2 and will be separate post-hoc artifacts.

### CI (sealed replay and replication pack from a clean clone)

- New `sealed-replay` job in `ci.yml`, aggregated into
  `deterministic-suite-required`. On a fresh full-history clone with only
  the documented `pip install -e ".[dev]"`, it replays C-ext4 at its locked
  commit and on the tested commit. It also runs
  `verify_replication_pack.py --regenerate`, which no CI job ran before.
  The replay tests must not skip there. Until now the locked-commit replay
  only skipped in CI because the pytest job clones at depth 1.

### Paper (C-ext4 in the .md and .tex, reproducible §82 split)

- The paper reports C-ext4 (CLAIM-021) beside C-ext3 in the abstract,
  introduction, contributions, headline table, §10.9, conclusion and
  summary, with the §82 limit stated where the gain is. Revision
  2026-10-17.
- The .tex §10.9 still said the semantic bundle's isolated effect was
  unmeasured, which C-ext3 had already measured. It now carries the same
  C-ext3 and C-ext4 text as the .md.
- `scripts/bfcl_cext4_seen_split_posthoc.py` recomputes the post-hoc
  seen/unseen split behind §82 and writes
  `artifacts/posthoc/bfcl_cext4_seen_split.json`. A test recomputes it and
  checks the artifact, §82 and the paper against each other.
- `scripts/replay_sealed_cext4.py` replays the sealed C-ext4 track at its
  locked commit in a temporary worktree, after checking the frozen code and
  data against the seal hashes, and compares all 36 arm-metric counts with
  the published result. `--at working-tree` checks today's code for drift.
  Both pass. Tests cover the comparison and run both replays; the
  locked-commit one skips on a shallow clone (new skip-reason entry).
  Documented in docs/06-reproducibility.md.
- The reproduction section's test count is refreshed (10,850 tests in 706
  files on master `17db5502`).

### Evidence (C-ext4: sealed BFCL utility result, CLAIM-021)

- C-ext4 was sealed from the whole remaining BFCL v4 reserve (295 positive,
  68 irrelevance rows; 1,562 episodes), locked, and run once under SAP v6.
- All eight pre-registered targets were met. Bundle v2 with deterministic
  receipts accepted 87/291 = 29.9 % of gold calls; the frozen v1 bundle
  accepted 20/291 = 6.9 %. Exact one-sided McNemar p is about 1e-18.
- Native wrong-call ACCEPT stayed 0/295, constructed wrong-tool 0/119, and
  irrelevance ABSTAIN 68/68. Obtainable VERIFY rose from 45/119 to 100/119.
- NEGATIVE_RESULTS §82 records the limit. The gain sits on tools also seen
  in development (76 against 12); on 36 gold calls with unseen tools it was
  11 against 8. Generalisation to new tool families is not shown.
- README gains row 5; the result, manifest and provenance sidecars are
  committed.

### Routing (semantic bundle v2 and deterministic derivation receipts, development only)

- `remora/toolcall/routing/bfcl_semantic_bundle_v2.py` succeeds the frozen
  v1 bundle (ADR D1). It authors contracts from the name after the domain
  prefix and from the declared description. A writing description
  overrides a reading name. Its lexicon is built per episode and keeps a
  phrase only if it names exactly one tool in scope. It handles negation.
- `remora/toolcall/routing/derivation_search.py` proposes derivation
  receipts by search over the existing transforms. The verifier is
  unchanged and still decides.
- `scripts/bfcl_dev_replay.py` replays the three spent BFCL sets under a
  chosen bundle and writes `artifacts/posthoc/bfcl_dev_replay.json`. On
  those spent sets, gold calls accepted moved from 58/994 to 255/994 and
  obtainable VERIFY from 192/431 to 353/431. No safety count rose.
  These are development numbers and may not be cited as results.
- SAP v6 (`docs/assurance/statistical_analysis_plan_v6_bfcl_utility.md`)
  pre-registers the C-ext4 track before its set is built. Its co-primary
  targets are wrong-call ACCEPT at or below 1 %, gold-call ACCEPT of at
  least 12 %, and a paired gain over the frozen v1 bundle.
- `scripts/build_bfcl_v4_cext4.py` seals the whole reserve once, and
  `scripts/run_bfcl_cext4.py` runs it once. Both use
  `remora/toolcall/routing/bfcl_arms.py`, the module the development replay
  uses, so the sealed run measures the system that was developed. A
  reject-all control arm runs beside F1, V2 and V2D (ADR D5).
- Nothing in production uses the v2 bundle.

### Policy (VerificationPlan v2 S1 and S2: plan types and the evidence check)

- `remora/policy/verification_plan_v2.py` defines the v2 plan, its binding,
  the task budget and typed source evidence (SDD-AS-v1 AS-007, AS-008).
  Construction refuses empty, duplicate or overlapping targets, bools as
  ints, budgets over the ADR D8 ceiling and plans that outlive their
  deadline.
- `assess_evidence` turns SUPPORTED evidence into UNKNOWN on any mismatch:
  tenant, value, source contract, predicate, source call, task, authority
  epoch, plan, time window, or a contract outside the accepted registry.
  `plan_outcome` re-enters only when every target is SUPPORTED.
- Pure library code. No decision path emits or consumes v2 plans yet; the
  durable task budget (S3) and engine wiring (S4) remain.

### Dependencies (Python batch 2: starlette, agent SDKs, dev tools)

- `starlette` 1.8.0; `langchain` 1.4.5, `langchain-core` 1.6.10, `langsmith`
  0.14.8, `openai` 3.29.0; `hypothesis` 6.169.0, `mypy` 2.4.0, `ruff` 0.17.0,
  `sqlglot` 30.22.0, `types-requests` 2.33.0.20261006; `charset-normalizer`
  3.5.2, `black` 26.10.1, `fpdf2` 2.8.9.
- On Linux, Python 3.12: all 11 install sets resolve, and `ruff check .`,
  the core rule set and `mypy remora servers` pass with the new versions.
  The replication pack's lock pin is refreshed.

### Dependencies (Python batch: mcp security fix, runtime framework, HF stack)

- `mcp` 1.28.1 to 1.30.0 fixes GHSA-84m7-p3x7-pcfv (CVE-2026-59951), unbounded
  session accumulation in the StreamableHTTP transport. REMORA does not
  import `mcp`; it arrives transitively.
- `fastapi` 0.143.0 and `pydantic` 2.14.1 move with `pydantic_core` 2.50.1 and
  `typing-inspection` 0.4.4. The Dependabot PR moved `pydantic` alone, which
  left the lock unresolvable.
- `hf-xet` 1.7.0, `tokenizers` 0.23.3, `transformers` 5.19.0.
- All 11 declared install sets resolve on Linux (Python 3.12). The
  replication pack's lock pin is refreshed with the reason recorded.

### Evidence (scoped evidence obligations over the outbox, REAS G1)

- New read-only package `remora/evidence/obligations/`. A manifest, locked
  before a dispatch window opens, fixes two obligations per intent: terminal
  settlement and downstream projection, each with a deadline. `assess()`
  compares a closed, digest-bound outbox snapshot against it and reports per
  intent SATISFIED, PENDING, MISSING (late or never), INVALID, CONFLICTED or
  NOT_APPLICABLE. Absence counts only once the snapshot has closed past the
  due time. UNKNOWN stays PENDING and unobservable.
- Coverage is established only for an inventory source the deployment
  accepts, the manifest's tenant, a matching records digest and a close past
  every deadline. Each result carries a fixed list of what it does not
  establish, including execution authority and the effect itself.
- Pure and deterministic: no clock, store or environment reads, and a later
  snapshot gives a new assessment id. The package imports nothing from
  enforcement, execution, policy or capabilities (AST test).
- Searched validation against a hand-written oracle: no false "complete" and
  no false "incomplete" found in 400 generated examples per seed (three seeds
  run locally), over the domain declared in the test module.
- Snapshots are built from the outbox's read-only `rows_created_in` query,
  tested on the in-process and SQLite adapters.
- Not built: a scheduled reader that decides `closed_at` in a deployment,
  read-back for UNKNOWN, receipt intake, issuer policy, delegation
  narrowing, external inventories, and JCS.
  Design note: `docs/design/scoped-evidence-obligations-v1.md`.

### Quality (CodeQL notes cleared, 2026-10-16)

- `signed_surface_runtime` declares `__all__`, so its re-exported digest
  helpers are explicit rather than hidden behind a lint suppression; a test
  drops imports it repeated. CAP-022 re-anchored, no behaviour change.
- Four notes dismissed with reasons: two deliberate function-local imports
  that break an import cycle in `servers/api.py`, a compatibility re-export
  in `servers/execution_api.py`, and a type used only in string annotations.

### AS-010 (the intent proposer's provider input is allowlisted and tested on every path)

- `intent_proposer` declares `INTENT_PROMPT_FIELDS` and
  `DERIVATION_PROMPT_FIELDS`, pinned against the templates. A recording
  provider captures the exact prompt on each path (answer, unusable answer,
  provider error, record-mode miss and hit, replay miss, derivations) and
  the test compares it with the allowlisted rendering and checks that
  sentinels for policy, trust, grants, secrets, evidence and prior decisions
  are absent. No leak found; no behaviour change.

### Decisions (owner decisions for SDD-AS-v1, REAS and VerificationPlan v2)

- `docs/architecture/ADR-sdd-as-v1-owner-decisions.md` records ten
  decisions that blocked work: the frozen BFCL extractor stays frozen, who
  issues obligation manifests and how a window closes, the isolation runtime,
  no paid model runs before the locked-evaluation harness, the
  pilot/research split, the VerificationPlan v2 registry, budget and cutover,
  and deferring `mcp` 2.
- `NEGATIVE_RESULTS.md` §81: the BFCL intent extractor ignores negation and
  conditionals. Benchmark-only, kept frozen because the sealed C-ext3
  manifest pins it; recorded as a validity limit of the semantic arm.
- Dependabot ignores semver-major `mcp` updates (D10).

### Execution (read-only window inventory on the outbox, REAS G1 reader)

- `rows_created_in(tenant_id, start=, end=)` on the in-process, SQLite and
  Postgres outboxes lists every intent a tenant recorded in `[start, end)`,
  whatever its state, so a row a crash left in DISPATCHING appears next to
  the settled ones. This is the inventory that evidence-obligation
  assessment reads.
- The window is compared on parsed datetimes, so bounds in another UTC
  offset select the same rows. Naive or empty windows are refused.
- Read-only: no state transition, lock or schema change. The boundary
  register is re-anchored to the commit that adds it.

### Quality (the mediator's in-flight state is visible, SDD-AS-v1 AS-004/AS-006)

- `CapabilityMediator.pending` counts admitted requests whose executor has
  not returned. They have no record until then, so a reader can tell
  "still running, may already have had its effect" from "did not run".
- New tests: an executor that calls back into the mediator spends the same
  budget without deadlock; `close()` during a running effect refuses new
  requests at once and leaves the running one to settle as what it was.

### Design (VerificationPlan v2 proposal, SDD-AS-v1 AS-007)

- New design note `docs/design/verification-plan-v2.md`. It records four
  weaknesses of today's resolution plan, read from the code: positional
  source choice with a last-source fallback, no expiry or task budget, a
  validator that never sees the value, and no binding to tenant, task, call
  or policy.
- It proposes one explicit source binding per argument, a durable budget per
  task reserved before any lookup, and typed source evidence checked against
  the plan before re-entry. Five slices; the strict-profile cutover waits for
  the owner's pilot/research decision. No code changes.

### CI (every collected test is accounted for, SDD-AS-v1 AS-002)

- The pytest matrix writes JUnit XML, and `scripts/check_test_accounting.py`
  reconciles it with pytest's summary line. Each testcase must have exactly
  one outcome (ok, failure, error, skipped, xfailed), and the counts must
  agree, so a truncated or partial report cannot pass as a clean run. The
  check allows for pytest 8's xpass-as-plain-testcase and its double-counted
  teardown errors, pinned by a real fixture. It refuses a JUnit file that
  declares a DTD.
- Each matrix job uploads `pytest-report.txt`, `pytest-junit.xml` and
  `test-accounting.json` as `pytest-results-py<version>`, also when it fails.
- Not done: the test-inventory hash compared across two clean jobs and the
  environment manifest (AS-003), and a network-isolated unit job (AS-001).

### CI (the test inventory is hashed and compared across two jobs, SDD-AS-v1 AS-003)

- `scripts/test_inventory.py collect` writes the sorted node ids of
  `pytest --collect-only` with a SHA-256 over the list, and an environment
  manifest: Python version and implementation, platform, installed
  distributions with versions, the hash of each lock file and the git SHA. It
  holds no environment values, host or user names, or paths.
- Each pytest matrix job uploads both files with `pytest-results-py<version>`.
- A new job, `test-inventory-reproducibility`, collects the suite again on
  Python 3.12 and fails if its hash differs from the matrix leg's, printing
  the node ids found in only one. Other Python versions are not compared with
  each other, because they may collect different parameter sets. The job
  feeds `deterministic-suite-required`; no job was renamed.
- Not done: a network-isolated unit job (AS-001). The comparison shows that
  collection is stable, not that every test passes the same way twice.

### Quality (both Clopper-Pearson bounds held to one grid, SDD-AS-v1 AS-016)

- `tests/test_binomial_bound_grid.py` pins both `clopper_pearson_upper`
  implementations (`risk_control` and the guardrail's `binomial_bounds`) to
  SciPy's beta quantile at 1e-10 for n = 1, 10, 500, 5000 and 100000 and
  delta = .05 and .05/7, plus the k = 0 closed form, k = n, monotonicity
  and the delta ordering. Both already met it; no bound value changed (old
  and new `binomial_bounds` agree exactly for n < 300).
- `binomial_bounds.clopper_pearson_upper` sums P(X <= k) on the shorter
  side of the distribution, so one evaluation costs O(min(k, n - k))
  instead of O(n). Its docstring no longer claims accuracy only up to
  n = 500. `binomial_tail_prob` is unchanged.

### Quality (intent and claim cases beyond the first tests, SDD-AS-v1 AS-011)

- New `tests/test_intent_claim_boundaries.py` covers rephrased requests that
  must be supported, requests the extractor declines on purpose, a claim made
  for another tenant, tasks with two goals, and refutations that later
  unknown evidence must not soften.
- `combine_goal_match` in `remora/toolcall/routing/intent_proposer.py` keeps a
  deterministic UNSUPPORTED verdict when a model proposes a different reading.
  Before, the veto turned it into UNKNOWN. A contested SUPPORTED still falls
  back to UNKNOWN. The function is library code and is not wired into a run.
- Defect found, not fixed: `extract_intent` loses "do not" and "before" in
  front of an action word, so "Please do not cancel booking B-104" reads as a
  cancel request. The file is frozen by the sealed C-ext3 manifest. Five tests
  are marked `xfail(strict=True)` and name the owner decision.

### Quality (BFCL holdout disjointness and C-ext3 denominators are tested, SDD-AS-v1 AS-025)

- `tests/test_bfcl_holdout_disjointness_and_denominators.py` checks the
  committed v3, C-ext2 and C-ext3 holdouts: no shared episode ID or cluster
  ID between any two (0 found). It ties the sealed C-ext3 result to its
  holdout by sha256 and checks that every one of its 2799 episodes lands in
  a family count. Every metric's denominator equals its full family in all
  three arms. Before this, disjointness was a build-time refusal plus a
  manifest string. No result changed.

### Quality (re-entry after a lookup is counted at the executor, SDD-AS-v1 AS-009)

- A new end-to-end test runs a proposal with a missing argument through
  `resolve_and_reenter` and `validate_and_reenter` with a fake lookup source,
  then hands the re-entered call to the real execution API with a recording
  tool as the only executor. It counts executor calls at every step.
- A hard guard that already blocks the call means the lookup is never run
  and the executor is reached zero times. A lookup that errors, returns
  nothing or confirms the value absent ends in ABSTAIN with zero calls.
- A call that still needs approval after the lookup reaches the executor
  zero times before approval, once after it, and still once after two
  replays. Approval of the pre-lookup call does not cover the re-entered one.
- A token minted before the lookup is refused for the re-entered call with
  zero calls. A new token bound to the re-entered call dispatches once.
- No defect was found. The HTTP execution API never builds a resolution plan
  itself, so re-entry stays a library step that the test composes with it.

### Paper (revision 2026-10-16)

- The preprint's abstract is cut to about 300 words and leads with the three
  measured results; the introduction gains a contributions list and a
  headline-results table bound to the claim register. The text follows the
  code again: the decision grant is described as the Ed25519 v3 format
  (RMR-CR-002), E7 is recorded as `EXTERNALLY_VERIFIED` with its two
  independent Probity run records and the exposure disclosure, and the
  federation-port contract probes, the TLA+ finding and the upstream fix
  (aeoess/federation-port#1) are described in a new subsection together
  with the CoSAI WS4 evidence-sufficiency mapping. The Markdown source's
  stale one-page summary is rewritten, a dead benchmark script path is
  corrected, the test count is refreshed, the `.tex` loses its byte-order
  mark and gains PDF metadata, and the Markdown prose baseline falls from 78
  to 70 long sentences. Version stays v0.12.0; only the revision date moves.

### Fixed (the mediator's effect budget holds under concurrency, SDD-AS-v1 B03)

- `CapabilityMediator.invoke` spends the budget when it admits a request,
  under the lock, instead of comparing it with the records already written.
  A record is written only after the executor returns, so with
  `max_effects=1` concurrent requests all reached the executor (nine of nine
  in the new barrier test). A failed or interrupted effect does not return
  its budget, and an interrupt still leaves an `UNKNOWN` record.
- The arguments are frozen once at admission (`remora.frozen_json`): the
  authority check, the recorded hash and the executor all see one private
  deep copy, so a caller mutating a nested value afterwards changes none of
  them. The executor used to get a one-level `dict()` copy. Arguments
  outside JSON (NaN, infinities, non-string keys, arbitrary objects) are
  refused as `capability_argument_mismatch` rather than hashed through
  `str()`. Hashes of JSON-domain arguments are unchanged.
- `max_effects` must be an int of at least 1, not a bool.
- Not changed: refusals still count against the same budget, which bounds
  the evidence one execution can produce. Across processes the effect domain
  already claims each slot in the durable ledger before its executor runs;
  this fix is for the in-process mediator.
### Quality (hard guards hold at maximum trust, SDD-AS-v1 AS-013/AS-014)

- `tests/test_hard_guards_dominate_max_trust.py` starts from one
  observation that ACCEPTs on the probabilistic path with trust and
  evidence at their maximum. It flips each of the eleven hard-guard signals
  in `hard_guard_floor` one at a time, in the default engine and with both
  opt-in accept paths on. Each must remove the ACCEPT with the floor's own
  action and reason. NaN, +inf and -inf in every finite-gate field never
  ACCEPT. NaN and -inf on a risk field are stopped by
  `NON_FINITE_INPUT_VERIFY`, the only gate they cannot pass. That path had
  no test before. No engine code changed.

### Fixed (a ResolutionPlan refuses a malformed binding, SDD-AS-v1 B02)

- `ResolutionPlan` now validates itself at construction: at least one target
  argument and one source tool, no empty or duplicate names, and
  `max_attempts` an int of at least 1 (not a bool). Before this an empty
  source list crashed re-entry with an uncaught `IndexError`, an empty
  target list let `validate_and_reenter` report every target confirmed and
  ground the call, and `max_attempts` accepted `0`, `-1` and `True`. The
  decision engine never built such a plan; a caller constructing one did.
- The engine drops duplicate argument names before building a plan.
- Not changed: sources are still matched to arguments by position, with the
  last source as fallback. Explicit per-argument binding is SDD-AS-v1 WP-02
  (VerificationPlanV2) and is not implemented here.

### Security (decision grants a redeemer cannot mint, RMR-CR-002)

- `PolicyDecisionToken` format v3: Ed25519 over `REMORA/POLICY-GRANT/v3`,
  `kid` derived from the public key. The PDP holds
  `REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE`; a redeemer holds only
  `REMORA_PDP_VERIFY_KEYS_ED25519`. It verifies every grant it is shown and
  mints none, not even an unsigned one (`GrantMintingRefused`, HTTP 503
  `grant_minting_refused`). Before this, the grant was HMAC under a key the
  PEP shared with the PDP, so verifying and minting were the same capability.
- Once a process holds Ed25519 grant material, a live v1 or v2 (HMAC) grant is
  refused as `token_hmac_refused` unless `REMORA_PDP_ACCEPT_HMAC` is set for a
  migration window. Derived kids are revocable through
  `REMORA_PDP_REVOKED_KIDS`. The executor domain may not hold the seed.
- Golden vector: `vectors/v3/policy_grant.json`.
- Not changed: a deployment that runs `/assess` and `/execute-accepted` in one
  process is still one custody domain, and the review path still mints and
  consumes in-process. RMR-CR-002 stays PARTIAL.

### Quality (mutation sweep over the enforcement modules)

- The weekly mutation sweep failed on 528 survivors absent from its baseline,
  mostly in code written since the baseline (the dispatcher's refusal hooks,
  lease authenticity, token signature refusals). Three new contract modules
  pin every refusal as a whole result and every governance event by name,
  level and payload. Survivors went from 704 of 3,115 mutants to 101 of 3,358.
  Each of the 101 has a written argument in
  `tests/data/mutation_equivalent_*.txt`. Three entries first merged as "open"
  were a verification error (wrong mutant bodies applied by hand); with the
  right bodies they are killed, and the correction is recorded in
  `docs/assurance/mutation_testing_v1.md`.
- The first runner sweep after that failed on 13 survivors that were already
  argued but missing from the baseline: the local sandbox had recorded them
  as segfault or timeout, and `--update` keeps survivors only. The baseline
  now holds 114, and a test requires it to equal the argued set.
- Argued is not resolved: 114 argued survivors became 38 equivalent by
  construction, of which 17 to 25 survive in any one sweep. The ledger and
  nonce store now run against a real Postgres (`tests/test_enforcement_ledgers_postgres.py`, in
  CI's postgres-contract job and in the scheduled sweep, which gained a
  Postgres service). Dead code (`"Z"` replacement on Python 3.11+) and
  unreachable defaults are gone, and the gate's three per-backend copies of
  every ledger statement are one helper and one schema. The 38 are listed
  with reasons; the details are in
  `docs/assurance/mutation_testing_v1.md`.
- Fixed on the way: `EnforcementGate.reset_ledger_watermark` had no D1 branch,
  so a Cloudflare deployment could not re-baseline its ledger watermark; the
  non-strict unsigned-token warning now names `check()`'s caller.
- Follow-up: `DurableNonceStore.consumed_count` no longer carries a dict
  branch no backend can reach (sqlite3, psycopg and `D1Connection` all
  hand the row back positionally) nor the column alias that branch read.
  A test pins the positional read and the alias-free query on SQLite and
  D1; the two case-only mutants of the statement keep their baseline ids.

### CI (a skipped test must name a listed reason)

- The CI pytest job skipped 126 tests on master without saying why: the
  job ran without `-rs`, and the same shape had kept the TLA+ checks
  silently skipped for weeks before #834. The job now runs with `-rs` and
  `scripts/check_skip_reasons.py` fails it on a skip reason that matches no
  entry of `docs/assurance/skip_reason_allowlist_v1.yaml`. Each entry names
  what the skip depends on and why that is acceptable in the job; the gate
  prints how many tests each listed reason kept from running. Deliberately
  unlisted: imports the job installs (fastapi, cryptography, httpx, yaml,
  jsonschema, uvicorn) and the TLA `BLOCKED` path. A test checks that every
  literal skip reason in `tests/` is listed or deliberately not.
- Made visible by the list, not changed: numpy, the OpenTelemetry SDK and
  Hugging Face datasets are outside the job's install set, so the tests
  behind them do not run in this job; several results-artifact tests skip
  because their artifacts are not committed.
- PyJWT had no install path: the identity adapters (JWT, Entra ID,
  Keycloak) import it lazily and no extra declared it, so the adapter tests
  never ran in the pytest job. New `identity` extra (`PyJWT[crypto]`); the
  pytest job installs it, the lock-resolvability sets include it, and a
  missing `jwt` now fails the job instead of skipping.
- The same for OpenTelemetry: `remora/observability/otel.py` documented a
  manual `pip install` and no extra declared the packages, so the structural
  tracing tests (issue #45 gap 6) never ran in the job. New `otel` extra
  (API, SDK, OTLP/HTTP exporter, all already pinned in the lock); the pytest
  job installs it, and a missing `opentelemetry.sdk` fails the job.

### Quality (style rule sets gate the trusted core, REM-037)

- `quality-gates.yml` runs ruff over `remora/policy`, `enforcement`,
  `governance`, `execution` and `servers` with the isort, pyupgrade and
  Ruff-specific rule sets next to the bandit and bugbear ones. One
  mechanical commit applied the fixes (sorted imports, unquoted
  annotations, dropped unused noqa, two unpacking rewrites, two ClassVar
  annotations); no behaviour changed and every capability the touched
  files evidence is rebound. Excluded with reasons: `UP042`, because
  `StrEnum` changes what `str()` returns for members that reach audit
  records; `RUF001` to `RUF003`, because prose characters belong to the
  prose ratchet; `UP037` on the four mutation-tested files, because mutant
  ids are positional. Remaining REM-037 item: hash-locked Python installs.

### Interop (the effect hash rule's preimage)

- `effect-evidence-v1.1` (DRAFT) now defines what the `hash` comparison rule
  hashes, so an outside reader can recompute it instead of leaving the rule
  unsupported. It is compact JSON with code-point key order, `\uXXXX`
  escapes and shortest round-trip floats (Python's `json.dumps` with
  `sort_keys` and compact separators), not RFC 8785. Eleven vectors pin the
  canonical text and digest, and six new cases tell the defined encoding from
  RFC 8785, raw UTF-8 and UTF-16 key order. The frozen `effect-evidence-v1` is
  unchanged.

### Formal models (reconciliation, TLC pin)

- `formal/tla/LeaseReconcile.tla` models the v1 reconciliation candidate for
  aeoess/federation-port#2. The candidate rule holds under outages, crashes,
  restarts and concurrent lookups (`reconcile_final`, including the liveness
  property `EventuallySettled` under a stated scheduling assumption). Each
  weakening of the rule is violated: closing on any authoritative absence,
  unbounded retries, a budget a restart resets, no scheduling assumption, and
  a provider that misreports finality. The model also exposed an unstated
  delivery assumption in the retry bound, which is now named (`BoundedDelivery`).
- The TLA+ check had not run on CI. The pinned `tla2tools.jar` was the v1.8.0
  pre-release, which upstream rebuilds in place. Its SHA-256 stopped matching,
  and all four test jobs skipped the models. The pin is now the stable v1.7.4
  release, and a blocked checker fails on CI instead of skipping. Traces are
  read from each model's `lastAction` label, so they no longer depend on how a
  TLC version prints actions. All eight `LeaseRetry` traces reproduce
  unchanged.

### Security (callable measurement on the API path)

- `/v1/execution/*` now measures each callable the deployment's registry
  module registers against its signed spec (`verify_callable`) before the
  dispatcher is built. A mismatch refuses with
  `toolspec_callable_digest_mismatch`. Until now only the opt-in
  `SignedSurfaceRuntime` measured, so the spec identity bound every lease but
  nothing showed the code behind it was the code the spec names. A tool with
  no spec is registered unmeasured; assessment already refuses it.
- `remora init-review` signed a SHA-256 of the whole registry module as the
  demo tool's `callable_digest`. No runtime measures that value. It now signs
  the source span of the function, which is what the v1 contract attests and
  what the runtime measures. Bundles from older scaffolds must be
  regenerated (`init-review --force`) before an executor will start.
- The digest functions moved to `remora.toolcall.callable_digest` (CORE) and
  are re-exported from `signed_surface_runtime`.

### Security (idempotency takeover fencing)

- An assess request slower than the 300 s stale window could have its
  idempotency reservation taken over by a retry, and still return its own
  answer when it finished. `complete()` reported the lost reservation, but
  both routes ignored it. On `/v1/execution/assess` that meant two
  executable ACCEPT tokens under one key. The late request now answers 409
  (`idempotency_key reservation_lost`) and withholds its answer and token.
  The execution route records `idempotency_reservation_lost` with the
  withheld jti. A retry receives the new owner's stored answer.

### Security (ToolSpec argument schema profile)

- `ToolSpecBundle.validate_arguments` enforced `required`,
  `additionalProperties` and top-level scalar types and skipped every other
  keyword without saying so. `True` also passed a `number` declaration,
  because `bool` is an `int` in Python. The validator now enforces a closed
  profile (`remora.toolcall.argument_schema`): types in the JSON domain,
  `enum`, `const`, numeric bounds, string lengths, nested `properties`,
  `required`, `additionalProperties`, `dependentRequired`, `items`, item
  counts, `anyOf` and `oneOf`.
- A signed spec whose schema uses a keyword outside the profile no longer
  loads (`toolspec_argument_schema_unsupported`, additive). `pattern`,
  `format` and `$ref` are outside it on purpose. This is a stricter load: a
  bundle that relied on an unenforced keyword now refuses instead of
  under-validating. Found while reviewing an external MCP adapter; no bypass
  of the authorization chain is shown, the gap was in argument validation.

### Interop (E7 external verification)

- `runtime-surface-e7-v0.1` records two Probity run records (self-service
  and pip, 5/5 fixture cases each) and moves to `EXTERNALLY_VERIFIED`, with
  independence as Probity confirmed it on #707. Independence here means the
  definition in `docs/interop/FEDERATION.md`, not a blind study: the
  exposure disclosure (expected answers read before implementation, partial
  exposure of the reference verifier through a lint diagnostic) is kept
  there and in the boundary register.
  `runtime_capability_surface_completeness` stays `NOT_ESTABLISHED`.
- `.github/workflows/probity-e7-reproduction.yml` reruns the reader from
  `agent-evidence-vectors==0.17.6` (wheel hash-pinned) as `AUTHOR`. It checks
  that the wheel ships REMORA's frozen bytes and that the results match the
  recorded pip run. It is a `REPRODUCTION` and advances nothing.

### Research (QV2-06 utility recovery, slice 1)

- `remora.toolcall.routing.intent_proposer` lets a model propose a task
  intent from the task text and the contract lexicon, never from the call
  under review. `combine_intents` uses the proposal to fill a task the
  deterministic extractor cannot ground, or to veto one it grounded
  differently. The proposal never overrules the extractor, so the goal-match
  verdict on a grounded task stays the extractor's or becomes UNKNOWN.
  Record-and-replay caching pins model and prompt for a sealed run. No model
  is chosen and nothing is measured.
- Post-hoc bounds on the spent C-ext3 set
  (`scripts/bfcl_cext3_proposer_ceiling_posthoc.py`) answer the §39
  gate-ordering question: the order stays. They also show that read autonomy
  needs levers other than a proposer (NEGATIVE_RESULTS §39,
  `docs/13-research-frontier-roadmap.md` QV2-06 sequence).

### Interop (AgenTrust TRACE, experimental)

- `remora.interop.trace.map_result` maps one verified REMORA federation
  result into TRACE v0.2 record shape as an `external-evidence-source`
  (agentrust-io/integrations#170). It is not a Trust Record and claims no
  TRACE level: `subject`, `runtime`, `policy`, `data_class`,
  `build_provenance` and `cnf` are left out with reasons, `model` only from
  a digest-bound execution context. 12 fixture cases and the pinned
  trace-spec schema in `integrations/agentrust-trace/`.

### Security (code review of 898758f)

- An effect execution has one deadline, recorded in the ledger by its first
  opener; a second worker, a restart or a cache miss can no longer give the
  same lease a fresh effect authority. A `close()` on any worker stops the
  next effect on every worker (CR898-1, CR898-2).
- An assess idempotency key is reserved before anything is assessed, so
  concurrent retries share one decision and at most one grant. The key is
  scoped to the authenticated principal, bound to the request (a changed
  request is a 409), and checked after the assess permission (CR898-3,
  CR898-4). Stored answers from before the upgrade are not read again.
- Disposition:
  `docs/assurance/reviews/2026-10-08-code-review-898758f/DISPOSITION.md`.

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

### Assurance

- Evidence-sufficiency v1.8 is specified before it is built
  (`docs/design/evidence-sufficiency-v1.8.md`, D-17 to D-25, R-29 to R-43).
  It records what survives at `cd8976c`: five open held-out faults of probe 4
  (NEGATIVE_RESULTS.md §73), 31 code-level survivors labelled equivalent by
  argument, a scorer default stuck at v1.4, and probe locks that squash-merge
  made unverifiable from `master`. It fixes probe 5's protocol, with a
  suite-aware selector arm, before any v1.8 file exists.
- `scripts/score_heldout_faults.py` scores every suite from v1.2 to the
  newest on disk by default and takes `--newest`; every table carries a row-2
  applicability count (faults rule R-6 hides by contract, reported beside the
  raw row-2 count, never in place of it); an `out_of_scope` label leaves the
  criterion's denominator only as `{"label": ..., "contract_ref": ...}`. Bare
  labels score as before, so probe 4 reproduces unchanged: 93 of 104 on row 3
  of v1.7, the same eleven survivors.

### Interoperability

- federation-port is now pinned at `3a2f6ce`, the merge of
  aeoess/federation-port#1. That pull request, from REMORA-research, fixes the
  four contract-probe findings (CP-F1 to CP-F4); its maintainer reproduced CP-F4
  and asked in review that the deadline become an authorization expiry, which
  it now is. The four `CP-F` probes now assert the corrected behaviour, and fail
  on the pre-fix runtime; `contract-coverage.json` keeps what each found at
  `92d5078` (`observed_at`) and records the fix (`fixed_upstream`, `fixed_in`).
  The map gains three rules the fix introduced. `reproduce.sh` reports 193 of
  193 (54 upstream, 50 and 60 REMORA components, 29 contract probes).
  Read-only reconciliation is open upstream as aeoess/federation-port#2.

- A TLA+ model of federation-port's operation lifecycle
  (`formal/tla/LeaseRetry.tla`, checked by `scripts/check_tla_models.py`,
  RF-16). Written counterexample first, it reproduces the known contract
  finding CP-F1 and found a new one, CP-F4: a lost response followed by a
  provider outage closes the operation as `failed` past the deadline while
  the refund exists, with one worker, no clock skew and no crash. Contract
  probe CP-F4 replays the model's trace on the unmodified runtime. Making a
  confirmation final does not fix it; an "uncertainty sticky" rule holds under
  outages, crashes and skew in the model. `reproduce.sh` now reports 183 of
  183 (29 contract probes).

- Contract probes for federation-port/v0
  (`integrations/federation-port/contract-probes`). `contract-coverage.json`
  maps 32 rules of federation-port's `spec/CONTRACT.md` to the upstream,
  REMORA and probe tests that exercise them, and records how the SDD testplan
  FED-01 to FED-10 overlapped the existing suite. 26 probes test the
  unmodified runtime on the rules no test reached (load refusals, secret
  scoping, frozen check input, duplicate claims, every malformed
  `valid_until` form, which deadline binds admission, concurrent retries
  under the dispatch lease, retry refusal order, provenance content). Three
  record findings at `92d5078`: a late provider confirmation is lost from
  the operation state under clock skew (CP-F1), the deadline does not bound
  the first provider contact (CP-F2), and adapter reason text enters
  provenance unbounded (CP-F3). REMORA-side tests add a retry with re-signed
  evidence, the recorded deadline and evidence digest, and the effect read
  apart from the transport state. `reproduce.sh` now reports 182 of 182
  (44 upstream, 50 and 60 REMORA components, 28 contract probes).

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
