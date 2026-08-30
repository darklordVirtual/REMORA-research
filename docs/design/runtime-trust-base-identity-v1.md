# RuntimeTrustBaseIdentity bound into ExecutionLease (ADR-D)

Status: design approved 2026-08-30. Implements ADR-D from
`docs/research/adjacent-systems-crosswalk-v2.md` §4, recorded there as
confirmed and **not implemented**.

## The gap

`ExecutionLease` binds sixteen fields:

- who and where: tenant, actor, target environment;
- what: tool name, canonical argument hash;
- under what authority: policy bundle hash, ToolSpec hash and version, intent
  authority hash, tool contract bundle hash;
- joinable to what: proposal id, grant jti;
- single-use and time-bounded: nonce, issue and expiry times;
- how it is signed: signature algorithm, key id.

None of them names the runtime that executes the action.

The discriminating case, walked against HEAD in the crosswalk. Authorize under
ToolSpec T1, policy P1 and runtime R1, with no drift before authorization. Then
execute with arguments unchanged, target unchanged, policy still P1 and the
ToolSpec declaration still T1, but against runtime R2. Property C
(exact-call integrity) passes, F1 (internal authorization-state drift) passes,
E and E2 (boundary traversal) pass. Every property reports success while the
action ran against an implementation nobody authorized.

Candidate property **H** is therefore not reducible to A-G as REMORA implements
them, and the crosswalk requires an implemented binding before either H or F2
is claimed.

## Trust model, and what this does not buy

The executing process reads its own identity from the environment once, at
first use, and caches it. Dispatch compares the lease's binding against that
cached self-identity. The identity is never a dispatch parameter, so a caller
in the invocation path cannot present a different one.

This closes *executed by the wrong runtime*. It does not close *executed by a
compromised runtime that lies about itself*: a process that controls its own
environment controls its own declaration. Closing that requires an external
attestor (TPM, Sigstore, SPIFFE) signing the identity, which is a separate
trust anchor and a separate delivery. The limitation is stated in the module
docstring and in the register entry; it is not claimed away.

## Design

### Identity module

New `remora/enforcement/runtime_identity.py`.

`RuntimeTrustBaseIdentity` is a frozen dataclass with six fields:
`runtime_kind`, `deployment_id`, `image_digest`, `executor_instance_class`,
`tool_runtime_identity`, `generation`. All are strings; `generation` is a
string because deployment generations are not reliably integers across
orchestrators, and a lexical value that is only ever compared for equality
needs no numeric semantics.

`from_environment()` reads `REMORA_RUNTIME_KIND`, `REMORA_DEPLOYMENT_ID`,
`REMORA_IMAGE_DIGEST`, `REMORA_EXECUTOR_INSTANCE_CLASS`,
`REMORA_TOOL_RUNTIME_IDENTITY` and `REMORA_DEPLOYMENT_GENERATION`. Unset
fields stay empty. Nothing is inferred, defaulted to a plausible value, or
derived from the running process. An undeclared runtime is undeclared, and its
identity hash is the empty string rather than a hash over six empty strings.
Declaring *some* fields is a declaration and hashes normally.

`current_runtime_identity()` caches the result of `from_environment()` in a
module-level slot behind a lock, so the value compared at dispatch cannot be
changed by anything that happens after startup. `reset_runtime_identity()`
exists for tests and follows the reload-restore pattern already used across the
suite.

`identity_hash()` hashes SHA-256 over `_canonical_json` from
`remora.policy.observation`, the same canonicalisation that feeds
`canonical_tool_call_hash` and therefore every lease, token, receipt and audit
entry in the repository. RFC 8785 / `remora.interop.jcs` is deliberately *not*
used. That module's own docstring scopes it to wire interoperability and
forbids it replacing the internal canonicalisation, because the historical
record must stay verifiable against the code that verifies it.

### Lease binding

`ExecutionLease` gains `runtime_identity_hash: str = ""`, placed with the other
late defaulted fields and included in `_canonical_payload`, so it is covered by
the signature. An empty value canonicalises exactly as `toolspec_hash` does
today, so every existing lease, test and stored artifact is unaffected.

`issue()` accepts `runtime_identity_hash: str = ""` as a keyword argument.
Authority does not invent it. It is carried in from the authorized runtime the
same way `proposal_id` and `grant_jti` are carried.

### Enforcement

Enforcement lives in `GovernedToolDispatcher`, not in `verify()`. This is a
property of the place the action is performed, and `verify()` may legitimately
run anywhere. The check runs immediately before execution, after the argument
hash is recomputed, and **before the nonce is consumed**. A rejected runtime
must not burn a single-use nonce and turn an authorization failure into
`ToolExecutionStateUnknown`.

Three cases:

- lease carries a hash that differs from this process's own: refuse, under
  every profile.
- lease carries an empty hash under a strict profile: refuse. The test is on
  the lease, not on the process, so a strict deployment cannot satisfy the
  property while issuing unbound authorizations.
- lease carries an empty hash outside a strict profile: allow, and emit a
  `governance_event` recording that the binding was absent. Property H is
  claimable only under a strict profile, and the register says so.

## Tests

`tests/test_runtime_trust_base_binding.py`:

1. Authorize under R1, dispatch under R2, everything else identical: refuse.
   This is H's existence proof.
2. Authorize under R1, dispatch under R1: accept. No false positive.
3. Empty binding under a strict profile refuses; outside strict it is allowed
   and the event is emitted.
4. Mutating `runtime_identity_hash` on a signed lease fails `verify()`. Without
   this the field is bookkeeping rather than a binding.
5. The nonce is not consumed when dispatch refuses on runtime mismatch.
6. The same scenario passes exact-call integrity, so the test records in code
   that H is not reducible to the existing properties.

## Evidence bookkeeping

- `docs/research/adjacent-systems-crosswalk-v2.md` §4: ADR-D moves from
  **not implemented** to implemented, with the attestation limitation stated.
- The conformance vocabulary records F as F1 (internal authorization-state
  drift) and F2 (external implementation/runtime drift) without renumbering
  A-G, per the crosswalk's own proposal.
- H is admitted only because test 1 fails without the implementation.
- A capability entry is bound to the squash SHA in a follow-up PR after merge,
  per the established rebind protocol.

## Out of scope

External attestation, per-action effect-assurance classification, and the
split-custody adversarial battery. Separate deliveries, separate pull requests.
