# REMORA decision-to-effect execution trace

One governed call, from invocation to independently verified effect. Repository
`darklordVirtual/REMORA-research` at `52ef4af`. Detail, crosswalk and limits are
in `EXECUTION-TRACE.md`; the runnable vectors are in this directory.

## The path

```
INVOCATION            {name, full arguments, tenant, target}
  |  exact canonical binding: SHA-256 over the complete argument object
AUTHORIZATION         signed decision + context_hash over tenant, principal,
  |                   target, policy bundle, ToolSpec identity, intent authority
  |  bounded lifetime, single-use jti, named audience
PEP REDEMPTION        signature, audience, expiry, call hash, context recomputed
  |                   revocation checked; unavailable store refuses
  |  grant spent exactly once
EXECUTION LEASE       narrower authority: exact call, executing runtime,
  |                   originating grant, own lifetime, own one-use nonce
  |  nonce consumed atomically at the boundary
DISPATCH              the dispatcher holds the callable and the credential
  |
ATTEMPTED             the boundary was crossed under a spent authority
  |  downstream evidence
ACCEPTED / UNKNOWN    UNKNOWN asserts nothing about occurrence
  |  independent read-back against a system of record
EFFECT_VERIFIED / EFFECT_MISMATCH / EFFECT_UNOBSERVABLE
```

Three separate single-use boundaries: the review queue authorizes an approved
item once, the PEP spends the grant once, the dispatcher spends the lease nonce
once.

## Five negative cases

| case | required behaviour | vector |
|---|---|---|
| arguments mutated after evaluation | refuse before invocation | V-02 |
| wrong audience | refuse | V-07 |
| duplicate use | refuse, authority already spent | V-04, V-08 |
| stale authorization | refuse | V-06 |
| mismatched effect evidence | mismatch, never verified | V-13 |

Ten further vectors cover argument addition, concurrent dispatch, tool-contract
and policy-bundle change before dispatch, revocation between evaluation and
dispatch, execution on an unbound runtime, indeterminate dispatch, and effect
evidence with no dispatch to belong to. Author-run: 15 of 15 match.

## Where each property already has a name

| property | ACS | cMCP | TRACE |
|---|---|---|---|
| exact invocation identity | `enforced_identity` | | |
| revalidation before the action | §17.1 rederivation | | |
| enforcement point | `pre_tool_call` | gateway per-call evaluation | |
| policy bundle identity | | `trace.policy.bundle_hash` | `policy.bundle_hash` |
| audit chain | | `gateway.audit_chain` | |
| dispatch record | | | `tool_transcript` |
| effect verification | | | `appraisal` |
| single-use authority | not identified | | |
| bounded execution authority | not identified | not identified | |
| revocation before dispatch | not identified | | |
| indeterminate dispatch state | | | not identified |

The four rows with nothing named are candidates, and all four are about the
lifetime of authority rather than about policy or evidence content. Everything
above them should use the existing name.

## What this is not

REMORA's capability register claims neither `ENFORCED_PRODUCTION` nor
`EXTERNALLY_VERIFIED`. The 15 of 15 is author-run and the record says so. cMCP's
hardware-measured boundary is stronger than REMORA's software custody split, so
that is not a boundary being claimed here. Where a specification is called
silent above, that is a reading of the public documents as of 1 September 2026
and an invitation to correct it.
