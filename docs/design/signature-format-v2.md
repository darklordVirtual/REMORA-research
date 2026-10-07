# Signature format v2 (CR-011)

Status: in progress 2026-10-07. ExecutionLease v2 and PolicyDecisionToken v2
implemented; the audit chain v2 follows. Finding: RMR-CR-011
([security review](../assurance/reviews/2026-10-07-272b6c56/README.md)).

## Problem

PolicyDecisionTokens, ExecutionLeases and tenant audit entries are signed over
compact JSON (or an entry hash) with no statement of what the bytes are. The
lease HMAC falls back to the PDP key. No cross-type forgery is known, because
the payloads happen to have disjoint fields; that is safety by schema accident.

## Decision

Freeze the existing formats as v1, and add domain-separated v2 formats beside
them. Never change a preimage under an existing name.

| Artifact | v1 (frozen) | v2 |
|---|---|---|
| ExecutionLease | `ed25519` or `hmac-sha256` over canonical JSON | `ed25519-domain-v2`: Ed25519 over `REMORA/EXECUTION-LEASE/v2 \|\| 0x00 \|\| payload`, `kid` derived from the public key |
| PolicyDecisionToken | HMAC-SHA256 over canonical JSON | HMAC-SHA256 over `REMORA/POLICY-GRANT/v2 \|\| 0x00 \|\| payload`, with `format: v2` inside the payload |
| Tenant audit entry | HMAC-SHA256 over the entry hash | `REMORA/AUDIT/v2` after an `AUDIT_VERSION_TRANSITION` record (next) |

### Which format, where

`remora/crypto/formats.py` decides:

- A strict v2 contract (`review/v2`, `controlled_pilot/v2`) issues v2 only and
  accepts only v2 for live authority. A v1 lease presented for dispatch is
  refused as `lease_format_legacy` before the nonce is spent.
- v1 stays verifiable as historical evidence, for offline replay and for
  migration diagnostics (`ExecutionLease.verify_historical()`, which reports
  `historical_v1` and authorizes nothing).
- Everywhere else v1 remains the default, so research use and the frozen
  fixtures do not change. `REMORA_SIGNATURE_FORMAT=v2` opts in; a strict v2
  contract refuses `REMORA_SIGNATURE_FORMAT=v1`.

A v1 token presented as live authority is refused as `token_format_legacy`;
`PolicyDecisionToken.verify_historical()` reads it. Token v2 stays symmetric
(`REMORA_PDP_SIGNING_KEY`): it adds domain separation, and does not add the
decision/enforcement trust boundary RMR-CR-002 describes, which would need an
asymmetric issuer in a separate custody domain.

Lease v2 has no symmetric form. A strict v2 authority therefore requires
`REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE`, and the HMAC fallback to the PDP
key is unreachable under it.

### Cutover

Leases (at most `MAX_LEASE_TTL_SECONDS`) and tokens (at most
`MAX_TOKEN_TTL_SECONDS`) are short-lived. Moving a deployment from `review/v1`
to `review/v2` is a cutover: leases and tokens minted before it are refused as
live authority after it, so wait out the longest TTL in flight first.

### Golden vectors

`vectors/v1/` is immutable: the v1 formats, generated once from the code on
master before any v2 change, and pinned byte for byte by
`tests/test_signature_vectors.py`. `vectors/v2/` holds the v2 formats.
`scripts/generate_signature_vectors.py --check` recomputes both, and the
generator refuses to overwrite a v1 file. Every vector carries its (test-only)
key material, payload and expected signature, so an independent implementation
can check itself.

## Not changed

- the v1 preimages and their verification;
- `REMORA/TOOLSPEC-BUNDLE/v1`, which was domain-separated from the start;
- envelope and checkpoint signatures, and the Workers (outside this change).
