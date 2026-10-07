# Finding disposition (interim, 2026-10-07)

Rebased review: `review/FIX_REBASE_b9ade2ba40cc59f1b8849e1e14b655b491a30789.md`.
Every fix below was merged to master after green CI (Linux, Python 3.11 to 3.14,
all gates). Capability bindings and the boundary audit were re-audited per
change and stay reachable (merge commits).

| Finding | Disposition | PR | Merged as |
|---|---|---|---|
| RMR-CR-001 ToolSpec HMAC trust root | FIXED (strict profiles) | #768 | 2412d61 |
| RMR-CR-002 PDP token co-located | PARTIAL (minimal fix; architecture open) | #773 | 14a2fb5 |
| RMR-CR-003 tenant from header | FIXED | #769 | merge commit |
| RMR-CR-004 role-only SoD | FIXED (strict profiles; opt-in elsewhere) | #770 | merge commit |
| RMR-CR-005 mediation opt-in | FIXED under strict v2 (declared mediation); deployment non-bypassability NOT_ESTABLISHED | #777 | c8cc91d |
| RMR-CR-006 conditional bindings | FIXED under strict v2 (BindingPolicy, active surface binding) | #775, #776 | 6959fc2, 8dc3227 |
| RMR-CR-007 audit verify w/o key | FIXED (reporting); consolidation open | #772 | 88001b5 |
| RMR-CR-008 effect evidence scope | OPEN | none | - |
| RMR-CR-009 custody guard naming | OPEN (docs) | none | - |
| RMR-CR-010 paper TEE sentence | OPEN (docs) | none | - |
| RMR-CR-011 signature domain separation | IN REVIEW: v1 frozen, v2 for lease, token and audit under strict v2 | #768, #778, #779, #780 | 2412d61, pending |
| RMR-CR-012 concurrency test hang | FIXED | #767 | squash |
| RMR-CR-013 canonicalisation | CHANGED, then FIXED at the Worker edge (no v2 canonicalisation) | #783 | pending |
| RMR-CR-014 datasets in wheel | OPEN (packaging) | none | - |
| RMR-CR-015 ledger failure parity | FIXED | #771 | 517a904 |

## Per finding

### RMR-CR-001: FIXED under strict profiles
- Old: HMAC bundles; strict profiles required the runtime to hold the key that authors bundles; labels over one key; pin optional.
- New: Ed25519 in domain `REMORA/TOOLSPEC-BUNDLE/v1`; runtime holds public keys only; signer is its derived key id; strict profiles require verify keys + pinned digest, refuse HMAC and refuse a runtime holding `REMORA_TOOLSPEC_SIGNING_KEY`; `toolspec.bundle_accepted` startup event.
- Tests: `tests/test_domain_signing.py` (15), `tests/test_toolspec_ed25519_trust.py` (16), profile and scaffold tests.
- Remaining boundary: custody of the signing seed on the authoring side; correctness of signed meaning. Outside strict profiles the v1 HMAC model remains.

### RMR-CR-002: PARTIAL
- New: issuer compared when `REMORA_PDP_ISSUER` is set (`issuer_mismatch`); token documented as an in-process one-time grant record; gap audit graded Partial.
- Tests: `tests/test_token_issuer_and_topology.py` (5).
- Remaining: no decision/enforcement separation on the execution API. Migration to lease semantics or asymmetric cross-boundary signing needs a consumer analysis.

### RMR-CR-003: FIXED
- New: one parser (`remora.profiles.deployment_environment`), development|production, unknown and set-but-blank refused at startup and per request; single-token mode development only; token-table tenant cannot be widened by header (403); strict profiles require `REMORA_API_TOKENS`.
- Tests: `tests/test_tenant_credential_binding.py`, updated hardening/RBAC tests.
- CI found and the PR fixed one regression of the first version (blank read as development).

### RMR-CR-004: FIXED under strict profiles
- New: approver must differ from the proposer read from the `assessed` event; unknown proposer refused; both principals on the `approved` event; admin has no bypass.
- Tests: `tests/test_separation_of_duties.py` (9); security matrix row for the Python API.
- Remaining: N-of-M approvals, hardware-bound approval.

### RMR-CR-007: FIXED (reporting)
- New: `hash_chain_status` and `signature_status` (CHECKED / NOT_CHECKED_NO_KEY / UNSIGNED) on `/v1/execution/audit/verify`; `verification_scope: linkage_only` on `/v1/audit/chain/verify`.
- Tests: `tests/test_audit_verify_signature_status.py` (6).
- Remaining: at least nine chain implementations; HMAC-only signatures; no external anchoring by default.

### RMR-CR-011: IN REVIEW (v1 frozen, v2 migration)
- Decision (2026-10-07): freeze v1, add v2 domains, never change a preimage under an existing name, never re-sign audit history.
- New: `remora.crypto` domain-separated Ed25519 for ToolSpec (#768). `vectors/v1/` freezes the lease, token and audit v1 formats byte for byte; `vectors/v2/` holds v2.
- New: lease v2 `ed25519-domain-v2` in `REMORA/EXECUTION-LEASE/v2` with a derived kid and no symmetric form (#778); token v2 in `REMORA/POLICY-GRANT/v2` with `format` signed (#779); audit v2 in `REMORA/AUDIT/v2` from an `AUDIT_VERSION_TRANSITION` record naming the final v1 head (#780).
- A strict v2 contract issues only v2 and refuses v1 as live authority (`lease_format_legacy`, `token_format_legacy`) before the nonce is spent; v1 stays readable as historical evidence. Outside strict v2, v1 remains the default.
- Tests: `tests/test_crypto_v2_lease.py`, `tests/test_crypto_v2_token.py`, `tests/test_crypto_v2_audit.py` (memory, SQLite, Postgres), `tests/test_signature_vectors.py`.
- Remaining: the token stays symmetric (no decision/enforcement boundary, RMR-CR-002); envelope and checkpoint signatures and the Workers' chains still sign v1; outside strict v2 the lease HMAC fallback to `REMORA_PDP_SIGNING_KEY` remains.

### RMR-CR-005: FIXED under strict v2
- New: ToolSpec schema v3 `effect_mode` (MEDIATED | NONE) and `credential_policy`; `effect_mediation` is a core binding, checked at startup, registration and dispatch before the nonce; an executor holding effect credentials refuses; `remora init-review` writes three domains.
- Tests: `tests/test_effect_mediation_policy.py` (38), scaffold tests.
- Remaining: whether a deployment's effect credentials are unreachable outside the mediator is NOT_ESTABLISHED.

### RMR-CR-006: FIXED under strict v2
- New: the API path signs and compares the execution surface (#775); strict profiles are versioned contracts, and v2 requires a BindingPolicy stating every binding REQUIRED, NOT_APPLICABLE or UNVERIFIABLE, refused at startup without its comparator and compared at dispatch before the nonce (#776).
- Tests: `tests/test_api_execution_surface_binding.py`, `tests/test_binding_policy.py`, `tests/test_binding_policy_matrix.py`.
- Remaining: `runtime_capability_surface_completeness` stays NOT_ESTABLISHED; the v1 contract keeps configuration-conditional bindings.

### RMR-CR-012: FIXED
- New: bounded race helper; starved writers fail in ~2 s. Old shape reproduced as a hang (killed at 20 s).

### RMR-CR-015: FIXED
- New: every backend refuses with `consumed_ledger_unavailable` and emits `grant.ledger_unavailable`; uncommitted grants stay unspent; D1 names timeouts and malformed answers.
- Tests: `tests/test_ledger_failure_parity.py` (7, parametrised over SQLite, Postgres, D1); 6 of 7 fail on the old code.

### RMR-CR-013: CHANGED
Investigation (Stage 0): Workers re-serialise and can lose precision before binding; Python binds and executes the same value. No post-binding divergence exists, so an exact-call-binding v2 is not justified. Proportionate follow-up: refuse unsafe numerics at the Worker edge.
- Follow-up done: `workers/{mcp-gateway,agent-control}/src/json_numbers.ts` (identical) scans the raw body and refuses integers beyond 2^53−1, float literals JavaScript would write as integers and non-finite literals, on mcp-gateway's JSON-RPC endpoint and agent-control's execute endpoint. agent-control's comment claiming a downstream comparator was corrected.
- Tests: `workers/mcp-gateway/test/json_numbers.test.ts` (vitest); `tests/test_worker_unsafe_numbers.py` runs agent-control's module under node against what Python would bind and checks the copies are identical, in the CI job that must not skip.
- Remaining: other Worker endpoints and downstream Python adapters that re-serialise after the rehash are not covered.
