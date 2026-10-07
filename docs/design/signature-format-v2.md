# Signature format v2 (CR-011)

Status: implemented 2026-10-07 for ExecutionLease, PolicyDecisionToken and the
tenant audit chain. Finding: RMR-CR-011
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
| Tenant audit entry | HMAC-SHA256 over the entry hash | `v2:` + HMAC-SHA256 over `REMORA/AUDIT/v2 \|\| 0x00 \|\| entry_hash`, from the `AUDIT_VERSION_TRANSITION` record on |

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

### The audit chain crosses once, and is never re-signed

Audit history is evidence of what was signed when; re-signing it would replace
that evidence with a later claim about it. So a chain is never re-signed. The
first append under v2 (in the same transaction) writes:

```text
v1 entries ... -> AUDIT_VERSION_TRANSITION -> v2 entries ...
                  {from: v1 | none, to: v2,
                   previous_chain_head: <final v1 entry hash>,
                   new_domain: REMORA/AUDIT/v2}
```

The transition record is the first v2 entry, and a chain never goes back: a
v1 process appending to a v2 chain signs v2. The verifier
(`remora/governance/audit_signing.py`) reads each entry's era from the chain's
structure, not from what its signature claims. A v1 signature after the
transition (`audit_v1_after_transition_at`), a `v2:` signature before any
transition (`audit_v2_before_transition_at`), a second transition and a
malformed one are findings, and these structural checks need no key. With the
key, every signature is checked in its own era. `verification_statuses`
reports `signature_format` (`none`, `v1`, `v2`, `v1+v2`). An unsigned chain
has no signature format and gets no transition record.

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
- envelope and checkpoint signatures, and the Workers' chains, including
  `verify_exported_chain` for the Worker envelope trail (outside this change);
- the lease HMAC fallback to `REMORA_PDP_SIGNING_KEY` outside strict v2, which
  is part of frozen v1.
