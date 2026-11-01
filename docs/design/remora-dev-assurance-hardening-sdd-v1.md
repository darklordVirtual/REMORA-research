# REMORA DEV Assurance and Execution Hardening - SDD v1

**Document ID:** SDD-RMR-DEV-2026-11-01
**Status:** PROPOSED / design only; not a shipped-capability claim
**Date:** 2026-11-01
**Target:** topic branches -> dev -> reviewed dev-to-master promotion
**Baseline:** dev 15f8bdfcfa7900a0f3c359f7e81e234569f398c6
**Change class:** security architecture, conformance, runtime reliability and controlled-pilot readiness
**Rule:** no deployment activation, customer writes or production policy relaxation from this SDD

## 1. Decision and intended outcome

Extend the existing REMORA authorization-to-effect path into an independently testable, operationally usable control system. The target is not another agent runtime or a parallel decision engine. The target is a single defensible chain:

agent proposal -> normalized invocation -> trusted authority facts -> policy decision -> independent review where required -> single-use execution authority -> isolated dispatcher -> bounded effect -> observed outcome -> independently checkable evidence.

The document is a prioritized backlog and implementation contract. It does not assert that its proposed improvements are already implemented. Every delivery slice must reuse existing components first, prove a missing behavior with a failing test, and update evidence and provenance in the same change.

### 1.1 Acceptance principles

1. Security authority must come from deployment-controlled facts, not agent descriptions.
2. No alternate path may reach a protected external effect without canonical admission and dispatch.
3. A checked policy, observed intent, logged attempt, successful response and verified effect are distinct facts.
4. Lack of observation, inability to verify, a timeout and failure must never be silently converted into success or no-effect.
5. A reviewer must be independently authenticated and must not be able to approve a modified payload under the earlier grant.
6. Developer experience and automation are subordinate to the enforcement boundary.
7. Any new mechanism must be accompanied by counterexamples, failure-path tests and exact claim limitations.
8. No implementation is borrowed from external repositories. Original code is developed from REMORA invariants and direct inspection of its own interfaces. Interoperability follows published protocol specifications where appropriate.
9. The default for undecidable protected effects is non-execution, with a named, auditable reason.
10. No new policy interpreter, lease type, audit ledger or second dispatcher unless the existing canonical component demonstrably cannot express an accepted requirement.

## 2. Baseline, reuse and exclusions

Existing mechanisms to preserve and extend, not reimplement:

- Canonical execution API: servers/execution_api.py.
- Enforcement tokens, leases and dispatcher: remora/enforcement/.
- DecisionEnvelope and verification: remora/governance/.
- Governed MCP ingress: workers/mcp-gateway/ and docs/integrations/mcp-gateway.md.
- ToolSpec and trusted capability constraints: remora/toolcall/ and docs/design/toolspec-signed-registry-v1.md.
- Capability minimization and task binding: docs/design/capability-minimized-execution-v1.md.
- Evidence admission and sufficiency: remora/evidence/admission/ and docs/design/evidence-admission-v1.md.
- Effect observer slice 1: remora/toolcall/effect_observation.py and docs/design/effect-contract-verification-v1.md.
- Decision-to-effect conformance: conformance/decision-to-effect-v1/.
- Credential topology and bypass tests: docs/assurance/credential_topology.yaml and tests/conformance/test_execution_boundary.py.
- Audit Merkle v2 and checkpoint helpers in dev: remora/audit/merkle.py and remora/audit/checkpoint.py.
- Claim, capability, remediation and full-code provenance registers in docs/assurance/ and provenance/.
- Branch promotion procedure: docs/assurance/branch_promotion_policy.md.

Do not reset, weaken or duplicate these mechanisms. Existing design documents with unimplemented slices are the source of implementation detail; this document coordinates and adds explicit cross-component acceptance criteria.

Explicit non-goals: training a new decision model; autonomous modification of security policy; a general-purpose multi-agent scheduler; unreviewed live OT writes; claiming all filesystem, network or subprocess effects are mediated by library-level Python hooks; claiming third-party certification; claiming a portable receipt is trustworthy merely because its verifying key is embedded.

## 3. Protected invariants

| ID | Executable property |
| --- | --- |
| INV-01 | Every registered protected-effect sink is reachable only through one approved execution path. Unknown sinks fail admission in strict profiles. |
| INV-02 | Agent-controlled code and subprocesses cannot read effect credentials, mint authority, extract tool callables or obtain preauthenticated downstream clients in the protected deployment topology. |
| INV-03 | Risk, action class, tenant, environment, tool identity, target and effect ceiling are derived from trusted signed or deployment-owned records. Unknown or conflicting facts cannot lower protection. |
| INV-04 | Decision, approval, lease, tool specification, callable identity, capability scope, target and complete argument object remain bound at dispatch. |
| INV-05 | A grant is one-time, short-lived and non-transferable across tenants, tasks, targets, policy revisions or environments. Revocation is effective before dispatch. |
| INV-06 | The protected dispatcher does not run if evidence preparation, authorization validation or durable dispatch-intent recording fails. |
| INV-07 | An ambiguous downstream completion is UNKNOWN and requires reconciliation; a retry cannot create a second external effect by assumption. |
| INV-08 | A verified effect requires admitted evidence about the actual target postcondition; a tool response alone cannot provide that level. |
| INV-09 | Absence of an effect may be asserted only when the observer's scope, visibility and completeness for that invocation are established. |
| INV-10 | Every decision and execution stage has a stable identity and can be linked without losing the complete binding context. |
| INV-11 | A deployed adapter or ingress that cannot prove mediation is reported as uncovered and cannot be represented as fully enforced. |
| INV-12 | An external reviewer can verify an exported evidence range without running the REMORA service; public-key trust and root anchoring remain separately established. |
| INV-13 | Administrative safety stops and scope revocations dominate previously granted but unconsumed authority. |
| INV-14 | CI, provenance and claim registers reject undocumented, stale or broadened guarantees. |

Each implementation PR identifies the INV identifiers it establishes, the actual protected runtime profile, at least one bypass attempt and the remaining limitations. Requirements not proved in a deployment stay at their existing capability level.

## 4. Reference architecture - one authoritative path

1. Ingress receives an invocation without effect credentials.
2. TrustedMetadataResolver resolves the target and action properties against the signed tool registry and deployment identity and scope maps.
3. The existing policy engine returns accept, verify, escalate or abstain; review outcomes are kept separate from decisions.
4. The existing review service authenticates the decider, binds the approved exact call and records expiry.
5. The existing token and lease mechanisms bind decision and execution context.
6. An isolated executor owns downstream effect credentials and validates the fresh authorization before any I/O.
7. An atomic dispatch-intent transition precedes a protected side effect.
8. The effect observer and read-back path record the actual observed outcome, including blinding and unknown conditions.
9. An evidence projector derives a bounded claim from admitted source events, rather than adding new authority.
10. A verifier independently reconstructs the binding chain and rejects missing or contradictory stages.

Suggested internal, nonauthoritative design records:

- **Authority Route Map:** a generated inventory of all effect entry points, process boundaries, credentials and enforcement checkpoints.
- **Effect Boundary Record:** the protected runtime's declared and observed effect reachability for a specific version and environment.
- **Evidence Closure Vector:** per-invocation status of request binding, authorization, dispatch, effect observation and external anchoring. Values are ESTABLISHED, NOT_ESTABLISHED or FAILED, with explicit reasons and provenance.
- **Recovery State Vector:** durable reconciliation facts about whether an effect was refused, pending, dispatched, observed, committed or left unknown.

These are proposed views over existing data. They must not introduce competing sources of truth, parallel authorizers or new grants.

## 5. Delivery workstreams

### D00 - Establish a fixed development evidence baseline (P0)

**Problem:** Changes to dev can outrun code-review and claim evidence. A broad hardening program must start with one reproducible snapshot.

**Implementation:** Pin a baseline commit, dependency locks, test selection, hardware/runtime assumptions, expected environment flags, documented skipped tests and a manifest of the existing authoritative paths. Compare master with dev before accepting each security PR. Keep branch protection and release behavior separate from CI documentation.

**Acceptance:**
- A clean checkout can reproduce the selected deterministic test suites and output machine-readable run metadata.
- Every required job is explicitly PASSED, FAILED, SKIPPED or NOT_RUN; missing results never read as passed.
- No automatic dev deployment, publication, production synchronization or customer-side mutation.
- Every change is traceable to its branch head and the dev integration commit.

**Likely home:** docs/assurance/, scripts/, tests/meta/, existing workflows.
**Dependencies:** none.

### D01 - Prove effect-route completeness (P0)

**Problem:** A policy gate is ineffective if an agent can reach the same external effect via another function, host tool, import, subprocess or preauthenticated client.

**Implementation:** Generate an Authority Route Map from API routes, worker entry points, tool registrations, direct network and filesystem call sites, credential readers, subprocess delegates and runtime adapter edges. Build it from AST/static inventory plus an executable bypass suite. A deployment-owned mapping classifies each route as PROTECTED, READ_ONLY, UNREACHABLE or UNPROVED. Changes to that mapping require review; unmapped new effect paths fail strict CI. Keep the original static credential-topology and bypass-suite tests as separate sources.

**Acceptance:**
- Every declared write-effect route in the shipped reference topology has exactly one canonical enforcement handoff.
- Direct callable extraction, ambient-secret access and delegated credential paths are denied by the protected process/container separation, not by Python attribute naming.
- Intentionally failing reference-profile bypasses remain visible as negative evidence, not rewritten into artificial passes.
- Adding a new unclassified API route, registered effect tool or credential reader fails a focused test.
- A runtime inability to inspect a path yields UNPROVED, not PROTECTED.

**Likely home:** servers/, remora/enforcement/, scripts/check_credential_topology.py, tests/conformance/.
**Dependencies:** D00.

### D02 - Trusted action-fact resolution (P0)

**Problem:** Caller-declared risk, action type, target environment or authority can be false.

**Implementation:** Add or finish a narrow TrustedMetadataResolver in front of the existing policy observation factory. It joins the signed ToolSpec and deployment identity, asset and tenant records; the agent supplies only a proposed invocation. Preserve uncertainty as explicit reasons. Resolve disagreements conservatively, never by trusting the lower-risk assertion. Bind the resolved facts and their version digests into the existing authorization context.

**Acceptance:**
- An input saying read_only for a registered write-capable tool does not reduce its risk or change its effect ceiling.
- Unknown action class, conflicting target ownership, stale registry digest and wrong tenant cannot produce an executable grant.
- A valid call continues through the existing policy implementation with the same decision semantics.
- Property-based tests vary all untrusted metadata fields independently.

**Likely home:** remora/toolcall/, remora/policy/, servers/execution_api.py.
**Dependencies:** D00, D01.

### D03 - Enforced runtime isolation and effect footprint (P0)

**Problem:** Application-level hooks can observe some operations but do not prove that native code, raw sockets, subprocesses or inherited credentials are unreachable.

**Implementation:** Complete the existing effect-contract-verification design in bounded slices. Use a separate effect executor with least-privilege filesystem, process and egress controls. A deployment-owned effect profile defines reachable network destinations, writable paths, permitted subprocess behavior and target adapters. The existing in-process observer is advisory coverage evidence; the isolated runtime boundary is authoritative. Instrument both declared and undeclared effects where technically observable.

**Acceptance:**
- Each attempted prohibited file, process, network or direct target effect is denied by the protected runtime or accurately labeled outside its coverage.
- A successful signed ToolSpec cannot override a runtime effect-ceiling violation.
- Observer interruption and lost trace events never establish clean behavior.
- Tests cover native and delegated paths, fork/spawn, path traversal, symlink resolution, inherited environment and direct-socket attempts.
- Report which syscall or effect classes are not observed in every tested runtime.

**Likely home:** remora/toolcall/effect_observation.py, remora/enforcement/, deploy/ot-pilot/, tests/security/.
**Dependencies:** D01, D02.
**Limit:** no universal claim about effects outside the deployed isolation scope.

### D04 - Transactional dispatch and ambiguity-safe recovery (P0)

**Problem:** A crash between authorization, outbox persistence, dispatch and read-back can otherwise cause missing evidence or duplicated effects.

**Implementation:** Finish the existing execution-lifecycle/outbox work. Transactionally record the single-use authority consumption and dispatch intent where the backend supports that boundary. Assign a durable idempotency identity over exact call, tenant, task, target and operation epoch. Use a Recovery State Vector for reconciler decisions. Reconciliation checks downstream evidence before a safe retry; on a non-idempotent or unverifiable action it requires human intervention.

**Acceptance:**
- Injected crashes at each pre-dispatch, in-dispatch and post-dispatch transition cannot produce silent double dispatch.
- Repeated concurrent redemption of one lease allows at most one protected invocation.
- Unknown downstream state remains UNKNOWN after restart until independent evidence resolves it.
- Restart with an unchanged journal reconstructs the same durable state; corrupted or missing records prevent automatic effect replay.
- Multi-process and real-database tests accompany in-memory unit tests.

**Likely home:** remora/enforcement/outbox.py, servers/execution_api.py, tests/.
**Dependencies:** D01, D02, D03.

### D05 - Evidence closure and effect verification (P0)

**Problem:** A signed decision or successful API response can be mistaken for a verified effect.

**Implementation:** Introduce the Evidence Closure Vector as a read-only projection from existing DecisionEnvelope, approval, lease, dispatch, observer and postcondition records. Extend evidence admission so each decisive fact requires a source, scope, producer capability, exact-call binding and freshness. Keep effect causation distinct from mere temporal agreement. Do not widen authorized behavior based on higher confidence scores.

**Acceptance:**
- The verifier separates refused, approved-but-not-dispatched, dispatched, effect-observed, postcondition-verified and UNKNOWN.
- Missing evidence, invalid signatures, mismatched tenant, missing precommitment or blind observer cannot become VERIFIED.
- An observed side effect outside the signed declaration produces a named MISMATCH.
- A read-back of the wrong resource or stale state does not prove success.
- A customer evidence export makes unresolved facts and the specific missing evidence visible.

**Likely home:** remora/evidence/admission/, remora/governance/, remora/enforcement/, conformance/.
**Dependencies:** D04.

### D06 - Independent portable evidence verification (P1)

**Problem:** Evidence is less useful to external reviewers if verifying it requires the same service or trusting a self-declared signer.

**Implementation:** Add an export projection over an existing immutable decision-to-effect range. Use a versioned canonical encoding with detached signature support and a verification bundle containing evidence digests, signing-key identifier, policy and ToolSpec versions, coverage declaration, verifier profile and chain head. Prefer published standards for the transport envelope, but design REMORA's claim mapping independently. The verifier must accept explicitly pinned trust roots and distinguish cryptographic consistency from independent authenticity.

**Acceptance:**
- Offline verification from a clean environment uses no private keys and does not import the running policy service.
- Byte changes, omission, reordering, key substitution, tenant mixing, duplicate dispatch and incompatible versions fail verification.
- A self-embedded public key alone never upgrades provenance to trusted.
- An unsigned, unanchored or incompletely observed export explicitly reports its assurance ceiling.
- Historical Merkle v1 remains verifiable only under its legacy version rules; new material uses the checked v2 algorithm.

**Likely home:** remora/audit/, remora/governance/envelope_verify.py, scripts/, tests/security/.
**Dependencies:** D05.
**Limit:** an export is a view, never a new source of execution evidence.

### D07 - External anchor and key-custody integration (P1)

**Problem:** Locally held hashes and HMAC chains detect internal edits but cannot establish independent retention or publication timing.

**Implementation:** Extend the existing checkpoint abstraction with a separately configured, append-only anchor adapter, externally pinned receipt identity and publication status. Keep signing and verification custody in separate domains. Start with a no-network development sink and deliberately corrupted fixtures; later test one independently administered pilot sink. Key rotation and revocation have an explicit transition record.

**Acceptance:**
- A verifier detects a missing, delayed, duplicated, forked or contradictory checkpoint.
- A failed publish never reports ANCHORED; local-only material remains LOCAL_TAMPER_EVIDENT.
- A removed or revoked signing key cannot issue new accepted authority.
- Rollback to an older head after a later externally anchored checkpoint fails validation.
- No production trust promotion until an operator independently verifies the root and retention settings.

**Likely home:** remora/audit/checkpoint.py, docs/enterprise/audit-anchoring-guide.md, tests/security/.
**Dependencies:** D06.

### D08 - Adapter control-surface conformance (P1)

**Problem:** Different agent clients expose different pre-use hooks and transport semantics.

**Implementation:** Create an adapter-neutral conformance fixture with one canonical action corpus. For each supported client path, test read, protected write, modified arguments, error, cancellation, timeout, duplicate request, approval-pending and interleaved calls. Declare whether the enforcement is host hook, gateway, isolated dispatcher or observe-only. Do not mark a client as protected because one hook fired.

**Acceptance:**
- The same exact-call binding and review requirements hold for every claimed protected adapter.
- A client lacking reliable hook interception is classified as requiring the guarded gateway/dispatcher.
- New tools and protocol versions are rejected or explicitly negotiated when unsupported.
- Adapter capability changes trigger tests and a truthful downgrade of unproven coverage.

**Likely home:** workers/mcp-gateway/, remora/sdk/, tests/conformance/.
**Dependencies:** D01, D04.

### D09 - Operational review and authority lifecycle (P1)

**Problem:** Cryptographic approval is insufficient without reliable human workflow, expiry, separation of duties and outage handling.

**Implementation:** Extend the current review queue with status, principal identity, authentication strength, reasons, signed decision context, timer policy and an immutable approval linkage. Add independent operator views for queue state and incident stops; both use the canonical API. A stale review must re-evaluate before dispatch. Critical actions may require stronger review requirements but never an autonomous downgrade.

**Acceptance:**
- No requester or execution principal can self-approve under the protected profile.
- Expired, revoked, reused, modified or wrong-tenant approvals never execute.
- Reviewer timeout results in a non-executing, explainable terminal or pending state, not an invisible retry.
- Reviewer race and two-approver scenarios are covered by deterministic concurrency tests.
- A pilot report measures queue age, false alarms, human response time and decisions without treating those measurements as authorization.

**Likely home:** remora/governance/, servers/, frontend/, tests/security/.
**Dependencies:** D02, D04.

### D10 - Task-scoped capabilities and delegated reachability (P1)

**Problem:** Agents may see more tools than needed, or indirectly reach a stronger tool through an allowed one.

**Implementation:** Reuse the current capability-minimized execution work. Compute a per-task and per-principal tool exposure set from the intersection of identity, tenant, task, environment, signed ToolSpec and current revocation epochs. Add nested-call tests to ensure delegation never amplifies scope. Log the exposure denominator and reasons for withheld tools.

**Acceptance:**
- Listing a forbidden tool or invoking it directly results in no effect.
- A task, tenant or role switch invalidates a stale exposure set.
- A delegated call cannot exceed its parent's action, target or lifetime.
- Read-only scope cannot authorize an indirect write via a nested tool.
- Disabling surface projection cannot disable the dispatcher hard floor.

**Likely home:** remora/toolcall/, remora/enforcement/, workers/mcp-gateway/.
**Dependencies:** D02, D08.

### D11 - Untrusted-input containment and egress limits (P1)

**Problem:** A permitted tool can combine untrusted instructions, sensitive data and an external destination into an unauthorized transfer.

**Implementation:** Track input origin and trust boundaries as metadata, never as an instruction to the authority layer. Before a protected data transfer or state-changing call, check purpose, destination, permitted data class and task scope. Enforce the destination at the isolated executor. Treat agent-derived classification as advisory until supported by deployment-owned rules.

**Acceptance:**
- A permitted read followed by an out-of-scope external send is refused.
- Embedded instructions in retrieved documents cannot change the registered action class or destination allowlist.
- Logs redact protected values without erasing the existence and outcome of the check.
- Tool output cannot silently promote its own provenance or a new capability.

**Likely home:** remora/evidence/, remora/policy/, remora/enforcement/, tests/security/.
**Dependencies:** D02, D03, D10.

### D12 - Emergency stop and bounded recovery (P1)

**Problem:** Revocations and safety stops must remain effective during queues, restarts and partial outages.

**Implementation:** Use a monotonic, deployment-controlled authority epoch per tenant and protected effect class. Bind the epoch to grants and recheck it immediately before dispatch. Add an emergency-stop state that forbids new protected dispatch and a separate, reviewed recovery operation. The stop is durable and cannot be canceled by agent input.

**Acceptance:**
- A stop after authorization but before dispatch prevents the effect.
- Multiple executor replicas observe the stop before acting; simulated propagation failure yields non-execution.
- Restart preserves the stop and revoked epochs.
- A resume cannot silently redeem approvals issued before the stop.
- The stop path is independently operable from the agent UI.

**Likely home:** remora/enforcement/, servers/, deploy/, tests/.
**Dependencies:** D04, D09.

### D13 - Adversarial validation, mutation and negative evidence (P1)

**Problem:** Passing authored tests does not establish effectiveness against unseen failures or configuration bypasses.

**Implementation:** Build a declared test matrix covering each invariant with positive, negative, mutation, crash, concurrency and cross-adapter cases. Keep known survivors. Separate authored regression fixtures from held-out evaluation. Compare safety and utility in the same run with fixed sampling and a stated uncertainty model. Require external reproduction for any externally verified promotion.

**Acceptance:**
- Every INV maps to one or more executable assertions and an identified coverage limit.
- Every fixed bypass regression demonstrates the vulnerable behavior first in a controlled fixture.
- Test selection and skipped paths are recorded, not hidden.
- Claims cannot be promoted by rerunning a spent development set.
- The gate reports prevented unsafe effects, correct legitimate effects, inconclusive outcomes and added latency separately.

**Likely home:** tests/security/, tests/conformance/, experiments/, docs/assurance/.
**Dependencies:** D01-D12 as slices become available.

### D14 - Runtime health and diagnostic evidence (P2)

**Problem:** Operators need to distinguish policy denial, adapter failure, evidence loss, backend outage and unknown execution.

**Implementation:** Project read-only operational metrics from existing durable events: decision counts by class, pending approval age, stale grants, blocked bypass attempts, outbox backlog, reconciliation lag, effect-observation gaps, audit-chain defects and per-adapter overhead. Use bounded queues and safe sampling for nonsecurity telemetry; never sample away mandatory security evidence.

**Acceptance:**
- Telemetry failure cannot turn a denied call into an executed call.
- Private tool arguments, credentials and raw sensitive observations are absent from ordinary metrics.
- A controlled load test establishes baseline p50/p95/p99 overhead and a review-approved regression budget; no unmeasured performance claims.
- The dashboard can distinguish unavailable data from zero incidents.

**Likely home:** servers/, remora/audit/, frontend/, deploy/.
**Dependencies:** D04, D05, D09.

### D15 - OT digital-twin safety pilot (P1)

**Problem:** A live pilot must demonstrate practical effect governance before permitting any customer-impacting write.

**Implementation:** Use a dedicated pilot runtime and repository boundary separate from the research environment. Stage A consumes read-only points and historical records. Stage B sends proposed writes to a disconnected digital twin with realistic limits, physical units, asset identities, safety interlocks and timing. Stage C records counterfactual outcomes and operator adjudication. Any real actuator integration is a separate human-authorized release decision, not a consequence of dev CI passing.

**Acceptance:**
- No dev test can reach a live actuator credential or endpoint.
- Proposed writes carry exact target identity, units, safe range, precondition and freshness constraints.
- Incorrect units, stale readings, wrong object identity, unsupported points and out-of-bound values are refused.
- The twin demonstrates a full review, authorization, dispatch, read-back and evidence export chain.
- A customer-facing report identifies observed behavior, simulator limits, nonvalidated assumptions and unresolved safety cases.

**Likely home:** deploy/ot-pilot/, examples/, tests/conformance/; new pilot-specific repository only after owner approval.
**Dependencies:** D01-D13 critical gates.

### D16 - Narrow, versioned integration API (P2)

**Problem:** A generic client needs a stable way to request authorization without learning REMORA's internal implementation.

**Implementation:** Expose a versioned compatibility facade over the canonical assessment and grant flows, not a new PDP. Define typed subject, resource, action, context and obligations, plus nonexecuting review responses. Map an external boolean-authorization vocabulary only where no security information is lost; otherwise require a richer response and fail on incompatible semantics. Maintain deterministic contract vectors.

**Acceptance:**
- No facade route executes directly or bypasses the canonical dispatcher.
- Incompatible or incomplete request context is refused with a reason.
- Pending review, escalation, abstention and executable acceptance remain distinguishable.
- Contract versions reject unsupported required fields rather than silently ignoring them.

**Likely home:** servers/, schemas/, remora/sdk/, tests/conformance/.
**Dependencies:** D02, D04, D08.

### D17 - Evidence-backed release and operator documentation (P2)

**Problem:** A technically correct feature is not deployable if its security scope is ambiguous or undocumented.

**Implementation:** Each delivered slice updates the shipped-surface matrix, architecture diagram, operational failure playbook, negative-results register, capability level, relevant claim and linked test artifacts. Separate research, controlled-pilot, limited-enforcement and externally verified requirements.

**Acceptance:**
- New or expanded claims cannot reach README or release summaries without a matching artifact and scope.
- The documented deployment defaults and configuration tests agree.
- Security regression blocks dev-to-master promotion even if unrelated jobs pass.
- An operator can independently verify how to stop execution, find unknown outcomes, restore audit state and inspect a failed approval.

**Likely home:** docs/assurance/, docs/deployment/, .github/workflows/, provenance/.
**Dependencies:** all workstreams.

## 6. Sequenced PR plan

Each numbered PR below targets dev from its own short-lived branch. The ordering is a dependency plan, not permission to combine unsafe changes into a single PR.

| Slice | Work | Depends on | Merge evidence |
| --- | --- | --- | --- |
| S0 | Baseline and requirement-to-test matrix | none | Reproducible test report; no security-code change |
| S1 | Authority Route Map and negative sink inventory | S0 | New effect route without classification fails |
| S2 | Trusted metadata resolution | S1 | Forged and conflicting metadata cannot execute |
| S3 | Protected executor and effect-footprint probes | S1-S2 | Raw-path bypass trials and visibility report |
| S4 | Crash-consistent dispatch reconciliation | S3 | Fault-injection and concurrent-grant results |
| S5 | Evidence Closure Vector and effect read-back | S4 | Missing/forged/stale effects cannot verify |
| S6 | Portable offline verifier | S5 | Independent verifier and tamper fixtures |
| S7 | External checkpoint anchoring, opt-in | S6 | No false ANCHORED status |
| S8 | Adapter coverage and version conformance | S3-S5 | Same negative corpus across adapters |
| S9 | Human review and incident stop lifecycle | S4, S8 | Authenticated actor, expiry, stop-race tests |
| S10 | Delegation/egress restrictions | S3, S8-S9 | No scope amplification or out-of-scope transfer |
| S11 | OT twin rehearsal and operators' evidence pack | S1-S10 | Zero live writes; bounded simulator report |
| S12 | Independent reproduction and release review | S1-S11 | Signed review disposition and gated promotion |

D13 and D17 test/documentation updates are required inside every relevant PR, not deferred to S12. D14 and D16 can proceed after their dependencies but cannot block P0 remediation unless the owner explicitly changes priorities.

## 7. Required per-PR SDD execution template

Each implementation PR must include:

- **Requirement IDs:** specific D and INV identifiers; no unbounded implementation brief.
- **Precondition:** relevant code path and exact baseline commit inspected.
- **Existing mechanism reused:** filename/function and reason no duplicate is needed.
- **Threat/failure model:** actor, authority held, attempted bypass, protected effect.
- **Proposed delta:** narrow changed interfaces and the one source of truth.
- **Negative test first:** which failure or bypass should be observable before the fix.
- **Positive and compatibility tests:** valid behavior preserved; legacy receipts verified where required.
- **Evidence:** exact commands, fixture and artifact digests, runtime topology, status.
- **Rollout:** feature flag/default, migration, downgrade and rollback conditions.
- **Claim ceiling:** what the test does not establish; capabilities and defect register updated.
- **Provenance:** changed files registered, original authorship history retained, dependencies and externally standardized inputs properly identified in the appropriate existing registers.

Any change to an authoritative policy, grant, lease, dispatcher, effect adapter or audit verifier requires an explicit security-review section; normal code review alone is insufficient.

## 8. Test matrix required for release claims

| Class | Minimum case | Expected safe result |
| --- | --- | --- |
| Bypass | Direct effect callable or inherited credential | Unreachable in protected runtime |
| Identity | Wrong tenant, task, actor, environment or target | No dispatch |
| Metadata | Forged read-only/risk flags or unknown action | No protection downgrade |
| Binding | Changed args, ToolSpec, policy or callable digest | Refuse |
| Grant | Replay, expiry, concurrent redemption or revoked epoch | At most one authorized dispatch |
| Human review | Self-approval, stale approval, wrong reviewer, timeout | No effect |
| Storage | Commit loss, partial append, restart, stale outbox | Durable UNKNOWN or safe recovery |
| Observer | Disabled instrumentation, blind spots, lost events | NOT_ESTABLISHED, not MATCH |
| Effect | Wrong target, stale read-back, mismatch, partial effect | Not VERIFIED |
| Evidence | Truncation, reordering, forged signer, wrong trust root | Verification failure |
| Adapter | No pre-use hook, duplicate request, protocol version drift | Canonical dispatcher still governs |
| OT | Unsafe unit, point, bound, time window or live endpoint | Simulator-only or refused |

For each test report, record (a) whether the action was attempted, (b) whether actual downstream I/O occurred, (c) whether the protected effect occurred, (d) whether its outcome was observed, and (e) whether independent verification succeeded. Never infer one from another.

## 9. Metrics and promotion gates

### 9.1 Mandatory safety gates

- G1: Zero successful unauthorized effects among the explicitly enumerated reference bypass tests. Report the tested denominator, runtime and scope; zero is a local test outcome, not a universal promise.
- G2: Zero uncovered registered protected routes in the selected protected deployment inventory. Any unobservable route is a blocker or a declared exclusion from the claim.
- G3: Zero unapproved or stale-grant protected dispatches in the tested concurrent/crash corpus.
- G4: All mandatory evidence components are verified or explicitly NOT_ESTABLISHED; no unsupported completeness upgrades.
- G5: Independent offline verifier rejects every registered tamper fixture.
- G6: All current CI, code-provenance, claim, supply-chain and negative-security gates pass on the integrated dev revision.

### 9.2 Utility and operations

Measure legitimate-action completion, time to review, mean and tail control latency, incident-stop propagation, outbox reconciliation age, false alarm rate and operator interventions. Set thresholds before a held-out evaluation, with owner-approved costs and safety bounds; do not invent target benchmarks from a single exploratory run.

### 9.3 Promotion rule

The work may enter dev in individually reviewed slices when tests pass. Promotion to master requires a reviewed dev-to-master PR and the complete required checks at the merge head. It does not authorize deployment. Deployment beyond a controlled pilot requires separately satisfied capability and assurance gates; external replication and operational sign-off remain independent prerequisites.

## 10. Originality and provenance control

This SDD is a fresh requirements synthesis over REMORA's own threat model, code, conformance results and documented gaps. Requirements are not evidence of exclusive invention. The implementation process is:

1. Derive each design change from one named REMORA invariant and a minimal counterexample.
2. Write an independent interface contract and failing test before implementation.
3. Reuse only REMORA's existing approved modules and independently authored code.
4. Use external technical standards only through their published normative specifications, with appropriate references in the repository's existing provenance process.
5. Do not transplant or adapt third-party source files, algorithms expressed as distinctive implementation code, fixture collections, prose, file layouts or internal naming.
6. Register each new tracked file and its exact hash in provenance/code-register-v1.json in the same PR. Update concept links only when they genuinely apply.
7. Preserve negative findings and historical claims; never backfill independent validation from self-generated fixtures.
8. Do not merge a change whose origin, license obligations or implementation provenance cannot be explained from the repository history.

## 11. Owner decisions required before high-impact work

- OD-01: Select the exact protected runtime/process isolation topology for the pilot and its supported operating environments.
- OD-02: Identify the first downstream effect class with a reversible or independently observable result.
- OD-03: Approve external anchor operator/key custody and retention policy; local testing is not external anchoring.
- OD-04: Approve any expansion from read-only to simulated writes and separately from simulation to real equipment.
- OD-05: Set the review quorum, timeout, incident-stop authority and escalation rota for the pilot.
- OD-06: Choose latency, cost and legitimate-action utility floors before final evaluation.
- OD-07: Approve an independent review plan and release claim boundaries.

No open decision may be silently replaced by a default inferred from an agent prompt.

## 12. Definition of done

The SDD is implemented only when every P0 slice is closed by traceable evidence, required P1 slices for the chosen protected pilot are closed, the actual protected runtime passes attempted bypass and recovery tests, and the integrated dev branch retains clean provenance and required CI. P2 improvements are optional for the pilot and must be scheduled explicitly.

The final assurance statement must distinguish: code implemented, reference path wired, API path wired, durable state established, protected production path observed, and independently validated. No status follows automatically from a passing unit test.

**This document is an engineering plan, not a warranty, deployment authorization or assertion of proven real-world security.**
