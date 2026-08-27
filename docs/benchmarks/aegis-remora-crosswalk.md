# AEGIS Core 3.4.0 × REMORA — Agent Authority Conformance crosswalk

**Status:** first application of `docs/benchmarks/agent-authority-conformance-v0.1.md`.
Conformance clarity exercise, not an integration, not a product comparison, not
a validation of either system.

**Assessed:** 2026-08-20. REMORA at `master` (this working tree). AEGIS Core
3.4.0 from the developer's own description of a same-ID replay fixture, as
relayed in the REMORA/AEGIS dialogue.

---

## 0. Read this first

**This is not a ranking.** AEGIS is not assessed against REMORA as the
reference, and REMORA is not assumed to be better. Both are assessed against
the same seven property definitions in the v0.1 specification. OUT OF SCOPE and
UNTESTED are legitimate outcomes; per §6 of the specification, the rows must not
be added up, scored, or summarised as "secure".

**The two systems make claims of different width, and that is the point.**
AEGIS Core 3.4.0 currently demonstrates a deliberately narrow execution
property: a process-local execution disposition evaluated immediately before
tool dispatch. REMORA attempts to model a wider authority and execution
assurance chain. A wider attempt is not stronger evidence. It is a wider
surface on which to owe evidence, and several REMORA rows below are UNTESTED
precisely because of that.

**Why this exercise exists.** The strategically interesting question is not who
scores better. It is whether the A–G properties can be stated precisely enough
that they apply to a system they were not derived from. AEGIS is the first
external case. If the properties turn out to be vague or REMORA-shaped when
pointed at someone else's fixture, that is a finding about the model, and it
belongs in this document rather than being smoothed away.

### Evidence-access asymmetry (load-bearing)

At first assessment the assessor had the REMORA repository and did **not**
have the AEGIS Core 3.4.0 source, test suite, commit history or result
artifacts. Under §3 of the specification, PASS requires evidence tier
RESOLVED, so no AEGIS row could carry PASS, regardless of merit.

**That asymmetry is now removed.** The developer supplied the repository and a
pinned revision, the assessor read the fixtures, and three AEGIS rows moved to
PASS (§1). The mechanism worked exactly as §7 step 5 intends: the assessment
named the single reference that would convert each row, and the reference
arrived.

One asymmetry cannot be fixed by an artifact. REMORA is assessed by a party
with full access to REMORA and an interest in the outcome, and AEGIS is not.
Both assessments record that fact instead of resolving it.

Treating this asymmetry as a defect of AEGIS would be the exact failure mode
the specification is trying to prevent, and would also be self-serving: REMORA
is being assessed by a party with full access to REMORA.

---

## 1. Task 1 — locating the canonical AEGIS evidence (CLOSED 2026-08-27)

The specification requires a resolvable reference: repository, revision, test
path and test name, or a committed result artifact.

**Result: resolved.** The developer supplied option 1, and the assessor read
the artifacts at the pinned revision:

- `https://github.com/LortuArte/aegis-sdk` at `1bcdec1b10c2`
- `test_same_tool_call_execution.py`: the same-ID contention fixture, 100
  concurrent attempts, one fresh grant, 99 cached replays, one simulated
  external execution. Run with `python test_same_tool_call_execution.py`.
- `test_financial_loss_matrix.py` lines 75-158: same ID with a changed
  `operation` or a changed `amount_usd` is denied with an
  `idempotency_conflict` attenuation and the balance is unchanged.

This closes the item and converts the AEGIS rows in §2 from **REPORTED** to
**RESOLVED**. Three statuses change as a result, and they change in AEGIS's
favour.

**The second fixture answers the question this document raised.** The original
assessment said that a same-ID replay with *mutated arguments* was the
discriminating case between ID-keyed memoisation and argument-bound
authorization, and that its absence was why C could not be read as
exact-call integrity. `test_financial_loss_matrix.py` is that case, within the
fields the AEGIS authorization interface represents. The earlier reading was
correct about what the first fixture showed and wrong to imply the property
was untested; the evidence existed and had not been located.

The rows below now match the assessment published at
`https://github.com/darklordVirtual/agent-authority-conformance`
(`examples/aegis-core-3.4.0.json`). Where the two ever disagree, that file
wins and this one is stale.

## 2. AEGIS Core 3.4.0 — A to G

Scope declared by the implementer: process-local execution disposition,
evaluated immediately before tool dispatch, external execution simulated.
Explicit non-claims, quoted from the developer: delegation-chain validity,
credential-path non-bypassability, multiprocess protection, post-dispatch
recovery, semantic correctness, external-effect verification.

| Dim | Property | AEGIS evidence | Tier | Claimed | Status | Reasoning | Caveat |
|---|---|---|---|---|---|---|---|
| A | Receipt Integrity | [`test_same_tool_call_execution.py`](https://github.com/LortuArte/aegis-sdk/blob/1bcdec1b10c294ca55bc0018fc0de00fc98a09c8/test_same_tool_call_execution.py) at `1bcdec1b10c2`: 1 grant / 99 cached replays / 1 simulated execution across 100 concurrent attempts | RESOLVED | PASS (single-use, process-local) | **PASS** (scope: single-use replay bounding under same-ID contention, process-local) | The counts directly exercise single-use semantics under real contention, and the fixture is now runnable by a third party at a pinned revision. | Partial by scope, not by doubt: the fixture says nothing about signature or MAC verification, expiry, not-before, or binding to an identity. Those parts of A remain UNTESTED. |
| B | Authority Provenance | none offered | NONE | not claimed | **OUT OF SCOPE** | The developer explicitly does not claim delegation-chain validity. | Recorded as a scope decision, not a deficiency. A disposition evaluator does not have to answer where authority came from. |
| C | Exact-Call Integrity | [`test_financial_loss_matrix.py` L75-158](https://github.com/LortuArte/aegis-sdk/blob/1bcdec1b10c294ca55bc0018fc0de00fc98a09c8/test_financial_loss_matrix.py#L75-L158) at `1bcdec1b10c2`: same ID with changed `operation` or changed `amount_usd` is denied as `idempotency_conflict`, balance unchanged | RESOLVED | partial | **PASS** (scope: binding of the `operation` and `amount_usd` fields the authorization interface represents) | This is the discriminating case §1 asked for, and it separates ID-keyed memoisation from binding of the represented fields. The conflict is refused *and* the balance is left untouched, so the refusal is not merely a returned error. | Bounded by the interface: AEGIS 3.4.0 does not accept or claim integrity over an arbitrary normalized tool-arguments object comparable to a full argument hash, and its own assessment says so. Mutation outside the represented fields is UNTESTED. |
| D | Semantic Authority | none offered | NONE | not claimed | **OUT OF SCOPE** | The developer explicitly does not claim semantic correctness. | Correct, and unusually clear. Most systems leave this property implicitly claimed by describing an authorization check without saying whether it reasons about purpose. |
| E | Execution-Boundary Integrity | none offered | NONE | not claimed | **OUT OF SCOPE** | The developer explicitly does not claim credential-path non-bypassability, and agrees with the REMORA position that a pre-tool hook is an enforcement boundary only where the protected side effect is unreachable by an alternative credential path. | The position is shared; the evidence is no longer symmetric. REMORA has since applied the §12 measurement procedure and holds a scoped PASS on E together with two demonstrated bypasses, which is a stronger row than an undemonstrated agreement. AEGIS's non-claim stays a legitimate scope decision and is not a deficit. |
| F | TOCTOU Resistance | [`test_same_tool_call_execution.py`](https://github.com/LortuArte/aegis-sdk/blob/1bcdec1b10c294ca55bc0018fc0de00fc98a09c8/test_same_tool_call_execution.py) at `1bcdec1b10c2`: 100 threads released from a common barrier, evaluated immediately before dispatch | RESOLVED | PASS (process-local) | **PASS** (scope: the in-process race at one call ID) | Concurrency at one call ID inside one process is genuine evidence for the in-process race, and evaluating immediately before dispatch narrows the check-to-use window. The barrier makes the contention real rather than incidental. | Multiprocess protection is an explicit non-claim. The fixture speaks to duplicate attempts, not to state that changes between authorization and dispatch. REMORA's own F row has the same process-model ceiling. |
| G | Effect Verification | 1 *simulated* external execution | REPORTED | not claimed | **OUT OF SCOPE** | The developer explicitly does not claim external-effect verification, and the fixture's external execution is simulated by construction. | Simulation is the correct choice for a replay fixture. It does mean the fixture cannot distinguish "dispatched once" from "took effect once", which is exactly the A-versus-G gap both projects agree on. |

**Reading of the AEGIS column.** Four of seven rows are OUT OF SCOPE by the
implementer's own explicit statement. That is a well-formed narrow claim, and
under this model it is a good outcome rather than a poor one. The three
remaining rows are all blocked on the same single missing artifact.

---

## 3. REMORA — A to G, same standard

Scope: REMORA-research at `master` (this working tree). Evidence is the
deterministic test suite (no API keys, no network). Process model: tests run
in-process; where a property depends on multiprocess or distributed behaviour,
the row says so. External effects in tests are simulated against in-memory or
SQLite/Postgres fakes; **no row below is evidence from a production
deployment**. Explicit REMORA non-claim, from `README.md` "Current boundaries":
REMORA cannot enforce against a credential path that bypasses its dispatcher.

| Dim | Property | REMORA evidence | Tier | Status | Reasoning | Caveat |
|---|---|---|---|---|---|---|
| A | Receipt Integrity | `tests/test_token_hardening.py` (signed expiry + jti, TTL bounds, not-before, max-age, audience binding, single consumption); `tests/test_execution_lease.py::test_tampered_fields_invalidate_signature`, `::test_unsigned_lease_refused`, `::test_expired_lease_refused`, `::test_nonce_ledger_is_atomic_single_use`; `tests/test_enforcement_properties.py::test_expired_token_never_verifies`; `tests/test_grant_ledger_tamper_evidence.py`; CAP-003 | RESOLVED | **PASS** (scope: single process by default; cross-instance replay only over a shared durable ledger) | Signature, tamper detection over the full field set, expiry, not-before, maximum age, audience binding and one-time consumption are each exercised by a named refusal test rather than inferred. | `test_in_process_ledger_does_not_survive_a_restart` and `test_in_process_ledger_reports_its_own_limitation` are the honest half: the default jti ledger is in-process. Durable replay refusal is shown by `test_durable_ledger_refuses_the_replay_from_a_second_gate`, which uses a second gate over a shared ledger, **not** a second interpreter; behaviour across a real process restart is inferred, not observed (CAP-003 caveat). The lease nonce ledger remains in-process (REM-025). |
| B | Authority Provenance | `tests/test_execution_api.py::test_profile_approval_role_is_enforced`, `::test_cross_tenant_item_access_is_refused`; `tests/test_execution_lease.py::test_stolen_lease_refused_for_different_actor`, `::test_actor_bound_lease_requires_an_actor_identity`; `tests/test_token_key_lifecycle.py::test_revoked_kid_refuses_even_with_key_present`, `tests/test_toolspec_runtime.py::test_revoked_identity_is_refused_even_with_a_valid_signature`, `tests/test_a2a_envelope.py::test_revoked_kid_invalidates_chain`; CAP-009 (RBAC), CAP-006 (A2A delegation envelope) | RESOLVED | **PASS (partial)** — approver role, tenant scope and actor binding; delegation chain **UNTESTED** in the enforcing path | Approval requires the role the profile demands, tenants cannot see each other's items, and a lease presented by a different actor is refused. That is real provenance evidence for the local principal. | Two gaps stated plainly. (1) CAP-013's caveat lists "transport-anchored actor identity" as remaining: the actor is bound into the lease, but the binding of that identity to the transport is deployment-supplied. (2) The delegation chain (CAP-006) is `WIRED_REFERENCE_PATH`, a symmetric-HMAC reference implementation whose own caveat says production needs JWS/COSE and trust anchors; it is not on the enforcing `/v1/execution/*` path. `test_actorless_lease_dispatches_without_actor_context` shows the actorless configuration is permitted, so actor binding is a deployment choice rather than a runtime invariant. (3) Revocation is tested at the level of *signing identity* — a revoked kid is refused even when the key is present, and a revoked ToolSpec signer is refused despite a valid signature — but not at the level of *principal authority*: no test revokes an approver's or an actor's authority after approval and requires the pending execution to be refused for that reason. |
| C | Exact-Call Integrity | `tests/test_execution_lease.py::test_mutated_arguments_refused`, `::test_context_mismatch_refused`, `::test_unknown_tool_refused`, `::test_policy_bundle_mismatch_refused`; `tests/test_enforcement_properties.py::test_lease_refuses_any_argument_mutation`; `tests/test_toolspec_binding_chain.py` (spec hash/version bound into the lease and covered by the signature); `tests/test_toolspec_execution_wiring.py::test_a_redeployed_spec_refuses_a_prior_approval`; CAP-004 | RESOLVED | **PASS** (scope: `/v1/execution/*`) | The dispatcher recomputes the canonical hash over the *full* argument set immediately before execution, and the binding set covers tenant, actor, tool, args, target environment, policy bundle hash, nonce and expiry. `test_lease_refuses_any_argument_mutation` is property-based, so the refusal is not tied to one hand-picked mutation. This is the row the AEGIS fixture is missing, and it is the one worth comparing. | CAP-004's caveat: the legacy `/v1/assess` surface still binds a summary, not full arguments, so exact-call integrity holds on the execution API and not uniformly across every HTTP surface. The property test is also narrower than "any mutation" sounds: its search domain is flat dictionaries with `str`/`int`/`bool` values and the mutation is an added top-level key, so nested structures, value-level edits, key removal and type changes are covered by the hash construction rather than by the generator. |
| D | Semantic Authority | `tests/test_semantic_authority_floor.py` (UNKNOWN goal fit or UNKNOWN expected effect can never reach ACCEPT; FALSE stops rather than verifies; capability/resource grounding); `tests/test_goal_match.py` (`test_the_wrong_resource_is_unsupported_even_with_a_wellformed_call`, `test_a_mutating_tool_never_reaches_supported_from_a_read_intent`, `test_negation_prevents_effect_grounding`); `tests/test_toolspec_runtime.py::test_target_outside_the_allowlist_is_refused`, `::test_credential_scope_drift_is_refused`, `::test_description_rug_pull_is_refused`; `docs/research/task_intent_authority_v1.md`; CAP-014 | RESOLVED | **PASS (partial)** — a wrong-resource or wrong-effect call cannot reach ACCEPT, and a model cannot assert its own semantic authority; **UNTESTED** for intent provenance | The semantic-authority floor is in the decision engine, not a library: a well-formed call against the wrong resource is UNSUPPORTED, a mutating tool never reaches SUPPORTED from a read intent, and `tool_matches_goal` is computed by `match_tool_to_intent` rather than supplied by the intent producer. Tool meaning comes from a deployment-signed ToolSpec. | The gap is provenance, in the repo's own words: `task_intent_authority_v1.md` §2 defines where an authoritative intent should come from (signed work order, operator form, version-locked template) but is `pre-registered`, and nothing in the enforcing path *requires* a primary-source intent. A model-proposed intent with valid spans is still accepted as input, so "was this the right user, in the right time window, under a valid business intent" is bounded by span grounding rather than by deployment authority. CAP-014 is `IMPLEMENTED_LIBRARY` and its discrimination is unmeasured, so no accuracy number may be quoted for it. |
| E | Execution-Boundary Integrity | `docs/assurance/credential_topology.yaml` (23 declared credentials, declared agent zone, limits L1-L6); `scripts/check_credential_topology.py` (CI gate); `tests/test_check_credential_topology.py` (12 falsification cases, incl. `test_agent_zone_breach_is_reported`); `tests/conformance/test_execution_boundary.py` (B1-B8); `tests/conformance/test_execution_boundary_process_split.py` (P1-P6, three processes, real credential, authoritative read-back); `remora/enforcement/custody.py` + `tests/conformance/test_custody_guard.py` (K1-K11, the split as a startup prerequisite); `README.md` "Current boundaries"; CAP-013 caveat; REM-030 (`NOT_STARTED`) | RESOLVED | **PASS** (scope: strict runtime profiles `review` and `controlled_pilot`, where the custody split is a startup prerequisite); **OUT OF SCOPE** for single-process enforcement, which those profiles refuse to start; **OUT OF SCOPE** for deployment network segmentation, which no in-process guard can observe | Applying the §9 procedure moved this row off "documented non-claim", first to a partial pass with a real FAIL beside it, and then to a pass once the FAIL was answered the way §9 allows: by refusing the configuration rather than by weakening the attempt. The static half is real evidence: every secret-bearing environment credential is declared, the register cannot go stale, and no credential declared unreachable is read by any module the agent zone transitively imports. The bypass half is equally real and less flattering. B3 shows the guarded callable can be pulled straight off the dispatcher in-process, and B4 shows a co-resident process reads the environment without importing anything. REMORA's execution boundary is therefore a process boundary (ADR-A), not a call boundary, and the P-series tests that claim rather than restating it. Three processes hold three different sets of secrets: the agent process has no effect credential, the execution domain has the credential and only the Ed25519 public key, and an execution domain handed the private seed exits rather than serve (P6). P2 shows the agent is refused when it reaches the effect service directly; P3 shows an authorised call succeeds; P4 and P5 show argument substitution and replay refused with pinned reasons (`tool_args_hash_mismatch`, `nonce_already_consumed`). Every one of those outcomes is confirmed against the effect service's own mailbox rather than against the dispatch response, which is property G doing work inside an E test. | The in-process bypasses have not been fixed and cannot be; B3 and B4 still pass, demonstrating that a single interpreter offers no custody. What changed is that a strict profile refuses to be that deployment: the authority domain cannot register a tool callable (K7), the execution domain cannot mint a lease (K8), an unset domain role is refused (K1), and an empty effect-credential declaration is refused as vacuous (K6). The research profile keeps the weaker configuration and labels it. What the guard cannot observe is stated rather than assumed: a process can check its own environment and not the network it sits on, so deployment segmentation and container boundaries are OUT OF SCOPE for a software claim rather than a pass. The fixture also provisions its own credential over loopback HTTP. P5 is also scoped to a single execution process, because the dispatcher uses the default in-process nonce ledger (REM-025). The zone choice is load-bearing: with `remora/toolcall` treated as agent-controlled, nine credentials fall inside the zone, and `test_agent_zone_breach_is_reported` pins that consequence. REM-030 stays `NOT_STARTED`; independent tool-interception validation is a different question from credential topology, and nothing here closes it. Both projects previously stood in the same place on E; REMORA now has evidence on part of it, including evidence of where it does not hold. |
| F | TOCTOU Resistance | `remora/governance/review_queue.py` (TTL expiry + approval freshness + REM-033 execution re-gate); `remora/execution/service.py` re-gate refusal path; `tests/test_execution_api.py::test_full_verify_approve_execute_flow_with_one_time_grant`; `tests/test_toolspec_execution_wiring.py::test_a_redeployed_spec_refuses_a_prior_approval`; `tests/test_toolspec_runtime.py::test_spec_changing_between_assessment_and_dispatch_is_refused`; `tests/test_execution_outbox.py::test_concurrent_claims_have_exactly_one_winner` and `::test_postgres_claim_is_exclusive`; `tests/test_enforcement_gate_timestamps.py` (fail-closed on unparseable/future timestamps); CAP-007 | RESOLVED | **PASS (partial)** — approval freshness, re-gate before dispatch and exclusive claim; **UNTESTED** for multiprocess single-use of the lease nonce | The approved thing changing under the approval is directly tested: a redeployed ToolSpec refuses a prior approval, and a spec that changes between assessment and dispatch is refused. Execution re-gates rather than trusting the earlier decision, and the outbox claim has exactly one winner under concurrency including on Postgres. | Concurrency evidence is in-process threads plus a shared database, not separate hosts. The lease nonce ledger is in-process (REM-025, `NOT_STARTED`), so distributed single-use of a lease is not demonstrated. This row is the closest analogue to the AEGIS fixture, and REMORA's evidence has the same process-model ceiling. |
| G | Effect Verification | `remora/governance/effect_verification.py` + `schemas/postcondition_contract_v1.yaml`; `tests/test_effect_verification.py`, `tests/test_postcondition_contract_v1.py`, `tests/test_effect_verification_wiring.py`, `tests/test_effect_record_endpoint.py`, `tests/test_github_postcondition.py`; `tests/test_execution_fault_injection.py`; `tests/test_execution_outbox.py::test_stale_dispatching_reconciles_to_unknown_not_retry` | RESOLVED | **PASS (partial)** — the verification contract, its vocabulary and one concrete verifier; **UNTESTED** against a live external system | The five statuses are frozen and enforced (`test_statuses_are_exactly_the_published_five`), the comparison rule is declared-delta rather than global unchangedness, "not observed" is structurally prevented from collapsing into "mismatch", verification never re-executes, and a crash after dispatch reconciles to *unknown* rather than to success or to a blind retry. `test_realization_does_not_overclaim` gates the claim itself. | REMORA records a verification reported by a verifier and refuses a record without a verifier identity; the authoritative read-back is performed by the deployment's verifier, not by REMORA. `test_github_postcondition.py` exercises a real verifier's logic against fixtures, not against GitHub. So the contract is tested; the loop against a live system of record is not, in this repository. |

---

## 4. Deliverable 3 — REMORA tests supporting each dimension

Short list, one line per dimension, all runnable with `python -m pytest <path> -q`:

- A: `tests/test_token_hardening.py`, `tests/test_execution_lease.py`, `tests/test_grant_ledger_tamper_evidence.py`, `tests/test_enforcement_properties.py`, `tests/test_enforcement_ledger_sqlite.py`
- B: `tests/test_execution_api.py` (`test_profile_approval_role_is_enforced`, `test_cross_tenant_item_access_is_refused`), `tests/test_execution_lease.py` (actor-binding block), `tests/test_a2a_envelope.py` (reference path only)
- C: `tests/test_execution_lease.py`, `tests/test_enforcement_properties.py`, `tests/test_toolspec_binding_chain.py`, `tests/test_toolspec_execution_wiring.py`
- D: `tests/test_semantic_authority_floor.py`, `tests/test_goal_match.py`, `tests/test_toolspec_runtime.py`, `tests/test_execution_semantic_wiring.py`; scope-limited, see §3 row D
- E: partly tested since the §9 procedure was applied. Static topology gate plus a
  seven-case bypass suite; two cases demonstrate the boundary does NOT hold
  in-process, and deployment-supplied downstream credentials stay untested (L5)
- F: `tests/test_execution_api.py`, `tests/test_toolspec_execution_wiring.py`, `tests/test_toolspec_runtime.py`, `tests/test_execution_outbox.py`, `tests/test_enforcement_gate_timestamps.py`, `tests/test_gate_replay_properties.py`
- G: `tests/test_effect_verification.py`, `tests/test_postcondition_contract_v1.py`, `tests/test_effect_verification_wiring.py`, `tests/test_effect_record_endpoint.py`, `tests/test_github_postcondition.py`, `tests/test_execution_fault_injection.py`

## 5. Deliverable 4 — REMORA dimensions still UNTESTED or scope-limited

Stated without softening:

1. **E, non-bypassability: evidenced for the strict profiles, with the weak
   configuration refused rather than fixed.** The §9 procedure supplies a
   topology gate, a bypass suite and a startup guard. The in-process bypasses
   still succeed and still ship as passing tests, because a single interpreter
   cannot offer custody. The strict profiles refuse that configuration
   instead: an unset domain role, an authority process holding an effect
   credential, an executor holding signing material, and an empty
   effect-credential declaration are each refused before the process serves.
   Two things stay outside the claim, and neither is a missing test. Deployment
   network segmentation cannot be observed by a process checking its own
   environment. REM-030 (independent tool-interception validation) remains
   `NOT_STARTED` and asks a different question. The gap between what a reader
   assumes "enforcement" means and what is demonstrated is now a gap about
   deployment topology rather than about the code.

## 6. Deliverable 5 — tests that would strengthen the model

Proposed, not implemented, and none of them is claimed here as existing:

1. **Cross-interpreter replay (A, F).** Consume a token in one process, attempt
   the replay from a second `subprocess`, over the same durable ledger. Closes
   the "inferred, not observed" caveat in CAP-003.
2. **Same-ID mutated-argument replay (C).** The direct analogue of the AEGIS
   fixture and the test it appears to be missing: N concurrent attempts on one
   call ID where a subset carries mutated arguments; require exactly one
   dispatch and a refusal (not a cached success) for every mutated attempt.
   Running this against both systems would be the first genuinely comparable
   measurement in this document.
3. **Bypass-path assertion (E).** A deployment-shaped test asserting the tool
   credential is unreachable from the agent process: no credential in the
   agent's environment, dispatcher-only egress, and an explicit failing attempt
   at the direct SDK path. This converts E from prose into something
   falsifiable, and it is the highest-value item on this list for both
   projects.
4. **Deployment-owned intent requirement (D).** A profile flag under which a
   `TaskIntent` whose `proposed_by` is a model identity cannot reach ACCEPT,
   with the refusal tested.
5. **State-change-under-approval (F).** Approve, mutate the target's
   authoritative state, then execute, and require the re-gate to refuse. The
   current tests mutate the *spec*; this mutates the *world*.
6. **Live effect loop (G).** One end-to-end run against a real system of record
   in a sandbox tenant, recording `EFFECT_VERIFIED` from an authoritative
   read-back rather than from a fixture.
7. **Authority revocation between approval and execution (B, F).** Approve,
   revoke the approver's or the actor's authority, then execute, and require a
   refusal that names revocation rather than expiry. Key-level revocation is
   covered today; principal-level revocation is not, and the two fail in
   different places.

## 7. Relationship between the two systems

AEGIS Core 3.4.0 demonstrates, so far, a narrow execution property: a
process-local same-ID replay disposition evaluated immediately before dispatch.
It explicitly does not claim delegation validity, credential-path
non-bypassability, multiprocess protection, post-dispatch recovery, semantic
correctness or external-effect verification.

REMORA attempts to model a wider authority and execution assurance chain. That
does not make its evidence better. On the two properties where the projects
actually overlap, the honest reading is:

- On **C**, the AEGIS fixture as described demonstrates duplicate suppression
  under an identical call ID; REMORA additionally refuses a lease whose
  arguments changed, with reason `tool_args_hash_mismatch`. That is the one
  substantive difference the available evidence supports, and it is a
  difference in what has been *tested*, not a claim about what either system
  would do.
- On **F**, both are ceilinged at the same place: single-process concurrency.
  REMORA's ceiling is written down as REM-025, AEGIS's as an explicit
  non-claim. Different bookkeeping, same gap.
- On **E**, both have zero evidence and both say so. Agreement between two
  projects that a property is unproven is not evidence that it holds.
- On **G**, AEGIS simulates the external effect and does not claim
  verification; REMORA has a tested contract and vocabulary but no live loop.
  Neither has verified a real external effect in a repository artifact.

Both projects independently converged on two statements that this model now
encodes as rules:

1. A pre-tool hook is an enforcement boundary only if the protected side effect
   is unreachable through an alternative credential path (property E).
2. An authentic authorization receipt is not evidence that the authorized
   effect occurred (the A-to-G separation).

**What this exercise was actually testing.** Not AEGIS. The A–G model. The
result is mixed and worth recording: the properties applied cleanly enough to
produce four defensible OUT OF SCOPE rows and to locate one specific missing
test (§6.2) in a system the model was not derived from, which is the outcome
that would justify developing it further. But three AEGIS rows are blocked on
evidence access rather than on the model, so **reusability across an
organisational boundary is still unproven**. The model has not yet been shown
to work where the assessor cannot read the code, which is the case it most
needs to handle.

## 8. What this document does not say

- It does not say AEGIS is weak, incomplete, or worse than REMORA. Four of its
  rows are OUT OF SCOPE because its author drew a narrow boundary and stated it
  clearly, which this model treats as good practice.
- It does not say REMORA is production certified, externally validated, or
  secure. It is neither externally replicated nor deployed
  (`NEGATIVE_RESULTS.md` §1, REM-021).
- It does not establish A–G as an industry standard. It is a v0.1 draft applied
  twice, once by its own authors to their own system.
- It does not produce a score. Per specification §6, the rows must not be
  aggregated, and this document deliberately contains no total.
- It is not an integration. No AEGIS code was read, written, run or modified.
