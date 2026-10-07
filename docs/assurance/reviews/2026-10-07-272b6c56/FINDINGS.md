> **Historical snapshot (2026-10-07): producer-owned review, not an external security certification.**
> Review tool: Claude Code (AI-assisted, directed by the maintainer).
> Reviewed revision: `272b6c56fc1d1a6a41640fe4b5e0195fcc155b51`.
> Revalidated at: `b9ade2ba40cc59f1b8849e1e14b655b491a30789` (v0.12.0).
> Independence: NOT_ESTABLISHED. The reviewer and the fixer are the same
> producer; tool output is not evidence by itself (docs/AI_USE.md).
> This file is a frozen snapshot of the review as written. Current status per
> finding: [FINDING_DISPOSITION.md](FINDING_DISPOSITION.md).

# Phase 44–45 — Findings

Revision `272b6c56fc1d1a6a41640fe4b5e0195fcc155b51`. Severity per prompt Phase 44. Exploitability/impact/confidence given separately where they differ.


## RMR-CR-001 · HIGH · ToolSpec trust root is an HMAC key the authority runtime must hold; signing identities are labels

- Confidence: HIGH · Status: CONFIRMED · Category: AUTHORITY / CRYPTO
- Claim/property affected: PROV-02 ToolSpec; 'the deployment, not the agent, defines tool meaning' (DEVELOPER_OVERVIEW Q1)
- Evidence: `remora/toolcall/toolspec.py:83 (sign_bundle)`; `remora/toolcall/toolspec.py:273 (ToolSpecBundle.load HMAC)`; `remora/execution/authorization.py:46`; `remora/toolcall/runtime_profile.py:106`

Bundle authenticity is HMAC-SHA256 under REMORA_TOOLSPEC_SIGNING_KEY. Strict profiles require that key in the authority process. With HMAC, the verifier can produce valid signatures. signing_identity is checked against a trusted/revoked allowlist, but all identities share one key, so revoking an identity does not stop a key holder from signing as another trusted identity. REMORA_TOOLSPEC_PINNED_DIGEST is optional and not a strict-profile prerequisite.

**Attack/failure scenario.** Compromise of (or code execution in) the authority process yields the key; attacker re-signs a bundle that lowers risk_tier / changes action_type / widens targets for a destructive tool; PDP then ACCEPTs what it would have ESCALATEd. Every downstream binding faithfully binds the forged spec hash.

**Current mitigation.** Strict profile, identity allowlist, optional pinned digest, lease binds toolspec_hash. **Why insufficient.** All mitigations trust the same key holder; pin is optional.

**Minimal fix.** Make REMORA_TOOLSPEC_PINNED_DIGEST mandatory under review/controlled_pilot and record it in the audit chain at startup.

**Preferred architectural fix.** Ed25519 (or Sigstore) for bundles, signing offline/hardware; runtime holds only public keys per identity, so revocation of an identity revokes its key.

**Regression test.** A process holding only ToolSpec verification material cannot produce a bundle that loads; revoked identity's key is refused even when label is changed.

**Could this contradict an existing REMORA claim?** YES


## RMR-CR-002 · MEDIUM · PolicyDecisionToken is minted and consumed in the same function with a shared HMAC key

- Confidence: HIGH · Status: CONFIRMED · Category: AUTHORITY / ARCHITECTURE
- Claim/property affected: PROV-05 PDP→PEP grant; README 'consumed once, at the policy-enforcement point'
- Evidence: `remora/execution/service.py:620-643`; `remora/enforcement/token.py (issue/verify)`; `servers/execution_api.py:357`

service.py issues the token and calls gate.check(..., consume=True) on the next lines in the same process; the gate verifies with the same REMORA_PDP_SIGNING_KEY. issuer is signed but never compared.

**Attack/failure scenario.** Not an exploit by itself. The signature adds no separation: any code able to reach the gate can also mint tokens. Assurance readers may infer a PDP/PEP trust boundary that does not exist.

**Current mitigation.** jti one-time ledger, context hash, audience, expiry are real and tested. **Why insufficient.** Separation of decision authority from enforcement is not established on this path.

**Minimal fix.** Document the token as an in-process one-time grant record; compare issuer when configured.

**Preferred architectural fix.** Drop the token where PDP and PEP are co-located (the lease already carries grant_jti); keep a token only when it crosses a trust boundary, signed asymmetrically.

**Regression test.** Grant issued by a non-PDP key holder is refused by a PEP that holds only verification material.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-003 · MEDIUM · Tenant chosen by X-Remora-Tenant header in single-token mode outside development; review profile does not forbid it

- Confidence: HIGH · Status: CONFIRMED · Category: TENANT ISOLATION / AUTH
- Claim/property affected: tenant isolation; tenant-scoped ledgers and chains
- Evidence: `servers/api.py:1997 (_authenticate)`; `servers/api.py:67-79 (_get_env_mode, _DEV_ENV_VALUES)`; `servers/api.py:507 (_is_production_mode)`; `servers/api.py:627 (REMORA_API_TOKENS production-only)`; `remora/toolcall/runtime_profile.py (review prerequisites)`

In single-token mode the role header is ignored outside dev, but tenant is always taken from X-Remora-Tenant. The production guard requiring REMORA_API_TOKENS runs only for REMORA_ENV in {prod, production}. Any other value (staging, typo) is neither dev nor production. The strict 'review' profile requires neither the token table nor REMORA_ENV=production.

**Attack/failure scenario.** A review deployment with REMORA_ENV=staging and one bearer token: any token holder reads/assesses/executes in any tenant by changing a header.

**Current mitigation.** Documentation describes single-token as a dev/single-operator mode; controlled_pilot requires production env. **Why insufficient.** Mode is reachable under a strict profile; env value semantics are tri-state and inconsistent with the _get_env_mode docstring.

**Minimal fix.** Under any non-dev env, single-token mode pins tenant to a configured value and refuses the header; review profile requires REMORA_API_TOKENS.

**Preferred architectural fix.** Single source of env truth (dev | production, refuse anything else); tenant always derived from credential.

**Regression test.** REMORA_ENV=staging + single token + X-Remora-Tenant=other → 403/refusal.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-004 · MEDIUM · Separation of duties is role-only; admin can propose, approve and execute the same item

- Confidence: MEDIUM · Status: CONFIRMED_BY_CODE_READING · Category: APPROVAL / SoD
- Claim/property affected: human-in-the-loop for VERIFY/ESCALATE
- Evidence: `servers/api.py:488 (_BUILTIN_ROLE_PERMISSIONS: admin = all)`; `servers/api.py:1689 (_enforce_review_approval_role accepts admin for any approval_role)`; `remora/governance/review_queue.py:351-400 (no proposer/approver comparison)`

Approval checks role membership only; no comparison of approver principal with the proposing principal was found. admin holds assess, execute and review.

**Attack/failure scenario.** One admin credential (or an agent operating with it) proposes a call, approves its own ESCALATE and executes it; the audit chain records a 'human' approval.

**Current mitigation.** Operator role cannot review; tenant reviewer_roles can exclude admin if configured. **Why insufficient.** Default configuration permits self-approval by admin; not exploit-tested here.

**Minimal fix.** Refuse approval when approver principal == proposer principal (record both in the item).

**Preferred architectural fix.** Two-person rule as a profile parameter; hardware-bound transaction approval (Phase 28).

**Regression test.** Same principal assess→approve → refused; distinct principals → allowed.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-005 · MEDIUM · Downstream-effect mediation is per-tool opt-in (mediated=False default), also under strict profiles

- Confidence: HIGH · Status: CONFIRMED · Category: EFFECT
- Claim/property affected: PROV-10 non-transitivity of authority; implementation_effect_non_transitivity
- Evidence: `remora/enforcement/lease.py (GovernedToolDispatcher.register, _prepare_mediation)`; `remora/enforcement/custody.py (effect domain split optional)`

register(tool, fn, mediated=False) by default; _prepare_mediation returns no mediator for unmediated tools; require_downstream_declaration applies only to mediated tools; effect-domain split is enabled only when REMORA_EFFECT_ENDPOINT is set.

**Attack/failure scenario.** Authorized low-risk call on an unmediated tool reaches webhook/trigger/second-API effects with executor credentials; declared-delta verification ignores undeclared fields and can report EFFECT_VERIFIED.

**Current mitigation.** DispatchResult reports mediated=False honestly; NTA-2 machinery exists. **Why insufficient.** Property is per-tool and per-deployment; no profile compels it.

**Minimal fix.** Strict profiles refuse registration of unmediated tools unless the ToolSpec declares 'no downstream effects' and the executor holds no effect credentials.

**Preferred architectural fix.** Make the three-domain split (authority / tool code / effect) the strict-profile default.

**Regression test.** Strict profile + unmediated tool registration → refused; executor env without effect credentials asserted.

**Could this contradict an existing REMORA claim?** YES


## RMR-CR-006 · MEDIUM · Most lease bindings are configuration-conditional; outside strict profiles absence is logged, not refused

- Confidence: HIGH · Status: CONFIRMED · Category: ASSURANCE / CLAIM SCOPE
- Claim/property affected: DEVELOPER_OVERVIEW Q3 'Is authorization bound to the exact action? Yes'; PROV-03/04/16
- Evidence: `remora/enforcement/lease.py (verify, dispatch, _runtime_refusal, _effect_refusal, _surface_refusal)`; `remora/enforcement/gate.py (enforce)`

toolspec_hash checked only if bind_toolspec_identity; task identity only if supplied (require_task_identity default False); capability digest only if require_capability_set; resolved effect / runtime identity refused only under strict; surface in shadow by default; actor skipped if lease.actor_identity empty; audience skipped if gate has none. EnforcementGate.enforce() calls check without context and has no production caller.

**Attack/failure scenario.** A library/reference deployment believes it has task/ToolSpec/capability binding because the lease signs those fields, while nothing compares them.

**Current mitigation.** Strict profiles compel several; events are emitted; unbound-vs-mismatch reasons are distinct. **Why insufficient.** Claim text does not carry the conditions.

**Minimal fix.** State bindings as a matrix of (binding × profile × resolver configured); remove or deprecate enforce().

**Preferred architectural fix.** Dispatcher construction takes a declared binding policy object and refuses to start if a required comparator is not bound.

**Regression test.** Per binding: strict profile without comparator → startup refusal.

**Could this contradict an existing REMORA claim?** YES


## RMR-CR-007 · LOW · Audit chain signatures are HMAC and skipped when the verifier has no key; ≥6 chain implementations

- Confidence: HIGH · Status: CONFIRMED · Category: EVIDENCE
- Claim/property affected: tamper-evident audit (correctly not claimed tamper-proof)
- Evidence: `remora/governance/tenant_chain.py:178-228`; `remora/audit/hash_chain.py`; `remora/governance/audit_chain.py`; `remora/audit/recorder.py`

verify() only compares signatures when a key is present; key holders can forge; tail truncation needs an external head.

**Attack/failure scenario.** An auditor without the key runs verify and reads 'intact' for a re-chained history.

**Current mitigation.** Head row / expected_head; documentation says tamper-evident. **Why insufficient.** Verification result does not say 'signatures not checked'.

**Minimal fix.** verify() returns signature_status: CHECKED | NOT_CHECKED_NO_KEY | UNSIGNED.

**Preferred architectural fix.** One chain implementation; asymmetric entry or checkpoint signatures; external anchoring of heads.

**Regression test.** Verifier without key reports NOT_CHECKED rather than intact.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-008 · LOW · EFFECT_VERIFIED means 'accepted attestation of declared delta'; observer usually = executing deployment

- Confidence: HIGH · Status: CONFIRMED · Category: EFFECT / CLAIM
- Claim/property affected: effect verification / observer independence
- Evidence: `remora/governance/effect_verification.py:243-342`; `remora/governance/effect_receipt.py:259+`; `servers/execution_api.py:2657-2720`

Module text is accurate. Undeclared fields are ignored by design; verifier is an allowlisted principal of the same deployment; verified_at and digests are verifier-supplied.

**Attack/failure scenario.** External readers equate EFFECT_VERIFIED with independent confirmation that nothing else happened.

**Current mitigation.** Honest docstrings; observation must postdate dispatch; uniqueness. **Why insufficient.** Status name is stronger than the claim.

**Minimal fix.** Expose vantage (same_deployment | independent) and scope (declared_delta_only) on every receipt and report.

**Preferred architectural fix.** EvidenceEnvelope with observer/vantage fields.

**Regression test.** Report generation cannot emit 'verified' without vantage and scope fields.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-009 · INFORMATIONAL · Custody guard inspects declared environment-variable names only

- Confidence: HIGH · Status: CONFIRMED · Category: CREDENTIALS
- Claim/property affected: PROV-15 custody split as a hard guard; credential_non_bypassability
- Evidence: `remora/enforcement/custody.py`

Checks presence of names listed in REMORA_EFFECT_CREDENTIAL_ENV_NAMES and signing variables.

**Attack/failure scenario.** IMDS/IAM role, workload identity, mounted secrets or undeclared env names give the authority process effect capability without tripping the guard.

**Current mitigation.** README states REMORA cannot enforce against bypass credential paths. **Why insufficient.** Guard name implies more than it checks.

**Minimal fix.** Rename/describe as 'declared credential custody'.

**Preferred architectural fix.** Deployment attestation of egress and identity (network policy, IAM deny) recorded as evidence.

**Regression test.** n/a (documentation)

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-010 · LOW · Paper TEE sentence equates attestation with 'correct model under the correct policy'

- Confidence: HIGH · Status: CONFIRMED · Category: CLAIM
- Claim/property affected: hardware_attestation (NOT_ESTABLISHED, TEE excluded in roadmap §11)
- Evidence: `paper/remora_paper.md:1491`

'the recorded decision is shown to have been produced by the correct model under the correct policy inside an isolated enclave'.

**Attack/failure scenario.** Readers infer correctness from measurement.

**Current mitigation.** Framed as future work. **Why insufficient.** Attestation establishes workload identity/measurement, not correctness.

**Minimal fix.** Replace with 'produced by a workload whose measurement matches the approved build and policy digest'.

**Preferred architectural fix.** AttestationEvidence as an EvidenceEnvelope subtype with does_not_establish: application_correctness.

**Regression test.** Prose gate term for 'correct model'.

**Could this contradict an existing REMORA claim?** YES


## RMR-CR-011 · LOW · No signature domain separation; one HMAC key may sign both grants and leases

- Confidence: HIGH · Status: CONFIRMED · Category: CRYPTO
- Claim/property affected: defence in depth
- Evidence: `remora/enforcement/lease.py:73`; `remora/enforcement/lease_signing.py:77`; `remora/enforcement/token.py (_canonical_payload)`

Lease HMAC falls back to REMORA_PDP_SIGNING_KEY; both sign sorted compact JSON without a context prefix. Payload key sets are currently disjoint, so no concrete cross-type forgery was found.

**Attack/failure scenario.** A future schema change makes a token payload parse as another object's preimage.

**Current mitigation.** Typed reconstruction of payloads; disjoint fields. **Why insufficient.** Safety depends on schema accident.

**Minimal fix.** Prefix every preimage with 'REMORA/<TYPE>/v<n>\0'; remove the key fallback.

**Preferred architectural fix.** Single signing service with mandatory domain tags.

**Regression test.** Signature over type A never verifies as type B with the same key.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-012 · LOW · Concurrency test deadlocks on its failure path; full suite hangs on 1 vCPU

- Confidence: HIGH · Status: REPRODUCED · Category: TEST QUALITY
- Claim/property affected: CI signal reliability
- Evidence: `tests/test_concurrency_rem036.py:90-133`

If a writer future times out, stop.set() is never reached; 50 spinning readers keep the executor's shutdown(wait=True) blocked forever. Reproduced twice.

**Attack/failure scenario.** On constrained runners the suite hangs instead of failing; a hang is easy to misread as infrastructure noise.

**Current mitigation.** CI runners have more cores. **Why insufficient.** Liveness depends on hardware.

**Minimal fix.** try/finally: stop.set(); bounded reader loop.

**Preferred architectural fix.** pytest-timeout in dev extras with a global ceiling.

**Regression test.** Test fails (not hangs) when writers are starved.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-013 · LOW · Binding path is Python json.dumps, not RFC 8785; cross-language executors may diverge

- Confidence: LOW · Status: SPECULATIVE · Category: CANONICALISATION
- Claim/property affected: exact-call binding across implementations
- Evidence: `remora/policy/observation.py:40-103`; `remora/interop/jcs.py (outside binding path)`

Float/large-int formatting differs between Python and JS; whether the TS mcp-gateway recomputes or re-serialises arguments was NOT_EVALUATED.

**Attack/failure scenario.** authorize(Python value) then a JS executor sends a rounded integer or reformatted float.

**Current mitigation.** Dispatcher rehash happens in Python before the call. **Why insufficient.** Downstream re-serialisation after rehash is unbound.

**Minimal fix.** Restrict numeric arguments to safe-integer range and decimal strings in ToolSpec schemas.

**Preferred architectural fix.** exact-call-binding-v2 over RFC 8785 with golden vectors shared with foreign implementations.

**Regression test.** Golden vectors: Python and JS produce identical digests for the same JSON text.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-014 · INFORMATIONAL · 963 KB benchmark dataset shipped as a Python module inside the production package

- Confidence: HIGH · Status: CONFIRMED · Category: PACKAGING
- Claim/property affected: package hygiene / TCB size
- Evidence: `remora/benchmarks/sap_v3_n1200.py`

Inline BoolQ-style data in a module under remora/.

**Attack/failure scenario.** Increases wheel size and the surface reviewers must treat as code.

**Current mitigation.** — **Why insufficient.** —

**Minimal fix.** Move to data/ and load lazily.

**Preferred architectural fix.** Separate research distribution.

**Regression test.** Release manifest excludes datasets from the runtime wheel.

**Could this contradict an existing REMORA claim?** NO


## RMR-CR-015 · LOW · Grant ledger backends have different failure semantics

- Confidence: MEDIUM · Status: CONFIRMED_BY_CODE_READING · Category: FAILURE SEMANTICS
- Claim/property affected: fail-closed consistency
- Evidence: `remora/enforcement/gate.py (_check_unlogged)`

D1 path converts outages into reason 'consumed_ledger_unavailable'; Postgres/SQLite catch only IntegrityError, so other DB errors propagate as exceptions (fail closed via 500, without a named reason in the chain).

**Attack/failure scenario.** Operators cannot distinguish ledger outage from code fault on PG/SQLite.

**Current mitigation.** Exception prevents execution. **Why insufficient.** Undiagnosed.

**Minimal fix.** Map OperationalError to a named refusal on all backends.

**Preferred architectural fix.** One ledger port with a typed Unavailable error.

**Regression test.** Simulated DB outage → refusal reason identical across backends.

**Could this contradict an existing REMORA claim?** NO
