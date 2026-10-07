# Hostile security review 2026-10-08: disposition

> Review text supplied by the maintainer on 2026-10-08, reviewing HEAD
> `322541c7`; its author and method are not stated here. This disposition is
> producer-owned and AI-assisted (Claude Code). Every finding was checked
> against the code at `322541c7` before any change. Independence:
> NOT_ESTABLISHED.

The review treats each assurance claim as possibly overstated and asks where a
malicious agent, concurrent worker or operator can produce an effect REMORA
would record as governed. Most of its points restate boundaries REMORA already
records as NOT_ESTABLISHED or configuration-dependent. Three were concrete
defects and are fixed here; two statements are incorrect against the code.

| | Finding (review rank) | Disposition |
|---|---|---|
| H-01 | 1. Single-use is process-local by default | **FIXED for strict profiles.** See below. |
| H-02 | 2. Federation projection weakens exact-call binding | By design and stated |
| H-03 | 3. Revocation and freshness at the final hop | **Partly FIXED** (lease-key revocation); rest a stated boundary |
| H-04 | 4. Effects outside the mediated graph | Known boundary (NOT_ESTABLISHED) |
| H-05 | 5. Custody is environmental, not hardware | Known boundary (stated, CR-009) |
| H-06 | 6. Canonicalization gaps | **Partly FIXED** (nesting bound); one claim incorrect |
| H-07 | 7. Runtime capability surface completeness | Known boundary (NOT_ESTABLISHED) |
| H-08 | 8. Wall-clock trust | Confirmed boundary, not closed |
| H-09 | 9. Report-specific selection | Verified closed (#790) |
| H-10 | 10. Claims bounded by shadow and simulator evidence | Register discipline; no change |
| H-11 | Outbox workers can both own a job | Incorrect for both durable backends |
| H-12 | Old signed ToolSpecs accepted | Closed under strict profiles by the pinned bundle digest |

## H-01: durable single-use under strict profiles (fixed)

At `322541c7` a `GovernedToolDispatcher` constructed without a durable nonce
store used the in-process `NonceLedger` under every profile. The API path was
not affected: strict profiles require `REMORA_PG_DSN` or `REMORA_CHAIN_DB`, and
`servers/execution_api.py` builds the dispatcher's store from them. A library
or misconfigured strict deployment, however, could get single-use per process
only.

Now `_durability_refusal` refuses dispatch under a strict profile without a
durable store (`nonce_store_not_durable`). It runs first in the pre-consumption
chain, before anything is recorded or consumed. Research and library use keep
the in-process ledger, which stays documented as single-use per process.

## H-03: lease-key revocation (fixed); other freshness (stated)

A revoked lease signing key kept verifying v2 leases until they expired.
`REMORA_LEASE_REVOKED_KIDS` now names derived key ids whose leases no longer
authorize (`lease_key_revoked`). Historical verification still reads them.

Already re-checked at dispatch before this change:

- The ToolSpec: on the API path, `bind_toolspec_identity` resolves the spec in
  force at dispatch against the hash signed into the lease (RMR-004). Under
  strict profiles the bundle is pinned (`REMORA_TOOLSPEC_PINNED_DIGEST`).
- Capability revocation epochs, when an epoch source is configured.
- PDP token key revocation (`REMORA_PDP_REVOKED_KIDS`) at the gate.

Not re-checked: whether the requesting principal's API credential was revoked
after the lease was minted. The lease lifetime bounds that window (default 120
s, cap 3600 s).

## H-06: canonicalization (nesting fixed; one claim incorrect)

- Fixed: argument nesting had no bound, so a deep enough payload raised
  `RecursionError` instead of a refusal. `_require_json_domain` now refuses
  nesting deeper than `MAX_ARGUMENT_DEPTH` (64) as a value error, so dispatch
  refuses with `tool_args_not_canonical`. No canonical form changes.
- Incorrect: "any object that reaches the encoder after a schema gap still
  stringifies". `canonical_tool_call_hash` calls `_require_json_domain` before
  encoding, so a non-JSON value is refused and `default=str` is unreachable on
  the binding path.
- Size: request bodies are bounded at the API (`REMORA_MAX_REQUEST_BYTES`, 413).
- Unicode normalization: the binding covers the exact bytes approved, and the
  dispatcher executes exactly those bytes. Two normalization forms bind as two
  different calls; neither can stand in for the other. Whether a tool treats
  them as one effect is the tool's semantics, not a binding bypass. No change:
  normalizing before hashing would change the exact-call digest of existing
  leases, which needs its own versioned decision.
- Array order and extra keys are part of the bound bytes, and arguments are
  validated against the signed ToolSpec schema at assessment. A tool that
  treats an array as a set is outside what the binding can know.

## H-02, H-04, H-05, H-07, H-10: stated boundaries

- H-02: over federation-port/v0, exact-call binding projects NARROWED to
  `remora.port_v0.bound_action`, and the manifest lists each limit. The claim
  names carry `port_v0` and never `exact_call_binding`.
- H-04: `implementation_effect_non_transitivity` is NOT_ESTABLISHED in the
  capability register. Under the strict v2 contract, effect mediation is
  REQUIRED for declared tools (CR-005). Code that uses a credential directly is
  still not stopped.
- H-05: the custody guard enforces declared credential custody only
  (`remora/enforcement/custody.py`, ADR-A, CR-009).
- H-07: `runtime_capability_surface_completeness` is NOT_ESTABLISHED.
- H-10: the capability register binds each status to the evidence and
  revision that support it. Nothing is ENFORCED_PRODUCTION or
  EXTERNALLY_VERIFIED.

## H-08: wall-clock trust (open)

Lease and token expiry, not-before checks and the federation `valid_until` use
each process's wall clock. A rolled-back or skewed clock widens or narrows the
window. No monotonic or attested time source is required. This stays an open
boundary.

## H-09: report-specific selection (verified)

`remora/federation/subjects.select_report` has no first, last or
any-established mode. Several eligible reports with no declared selector raise
`report_selection_ambiguous`, and no result is produced
(`tests/test_federation_report_selection.py`).

## H-11, H-12: verified against the code

- H-11: `ExecutionOutbox.claim` takes the write lock with
  `BEGIN IMMEDIATE` (SQLite) or `SELECT ... FOR UPDATE` (Postgres) before
  checking that the row is still `DISPATCH_PENDING`. Two workers cannot both
  claim one row, and the durable nonce remains the final gate.
- H-12: strict profiles accept only the bundle whose digest is pinned, so
  an older signed bundle is refused even if correctly signed. Outside strict
  profiles the pin is optional.

## Tests

`tests/test_hostile_review_2026_10_08.py` (8) covers H-01, H-03 and H-06; its
module docstring states what each closes. Four existing tests stub the new
refusal where durable single-use is not their subject, following their existing
convention for strict-only refusals.
