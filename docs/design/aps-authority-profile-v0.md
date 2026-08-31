# REMORA APS Authority Profile v0

Status: draft, not claimed conformant. Written 2026-08-29 in response to the
REMORA x APS conformance feedback of 2026-08-28.

This document settles the byte layer. The semantic mapping for the four
conformance families selected for the next run is
[docs/interop/REMORA-APS-PROFILE-v0.1.md](../interop/REMORA-APS-PROFILE-v0.1.md),
which builds on this one and does not replace it.

## What this profile is for

The Agent Authority Conformance lab does not issue a project-level verdict. It
records an interop family: an adapter, its hash, the pinned revisions of every
side, and per-family results labelled author-run or independent. A record can
carry a passing family and eight unsupported families at once, and neither
number is aggregated.

This document exists so that a REMORA family can be recorded honestly. It states
what REMORA does at the wire level, what it declines to do, and why.

The honest summary today is the one the run report already gives: semantic
alignment on authority and signatures, **no wire-level interoperability**.
Nothing here upgrades that. It closes three of the four things standing in the
way and states the fourth as a deliberate refusal.

## Scope

The profile claims four things and nothing else: JCS canonicalisation, Ed25519
signatures, an ActionRef type, and monotonic delegation. Everything outside that
list is unsupported, and the record should say so by name rather than leaving
it to be inferred.

## The load-bearing constraint: format versioning

Recommendation 2 of the feedback is that the signing format is versioned and
historical bytes are never rewritten. That is not housekeeping here, it is the
reason the rest of this document is structured the way it is.

`remora.policy.observation._canonical_json` feeds `canonical_tool_call_hash`,
which is bound into every execution token, every lease, every receipt and every
tenant audit-chain entry this deployment has written. `_canonical_bytes` in
`remora/enforcement/result_envelope.py` produces the retained result bytes on
the same terms. Those bytes are not an
implementation detail that can be improved: they are what the verifier
recomputes. Changing the function would leave the historical record
unverifiable against the code that verifies it, which is a worse outcome than
never having interoperated at all.

So there are two formats, named, and no migration between them:

| identifier | where it is used | changes |
|---|---|---|
| `remora/json-sorted-v1` | every internal binding: tool-call hashes, tokens, leases, receipts, audit chain | never |
| `remora/jcs-rfc8785-v0` | wire interoperability only | this profile |

An implementation reading a REMORA signature must know which identifier it was
produced under. A signature is not portable between them and must never be
re-derived across them.

## The four divergence classes

All four were confirmed on REMORA 5576670 before any code was written. Two
functions in this repository produce canonical JSON:
`remora/policy/observation.py::_canonical_json`, which the binding path uses,
and `remora/enforcement/result_envelope.py::_canonical_bytes`, which is the one
the Mode B adapter imported. Both diverge. They share the same
`json.dumps(sort_keys=True, separators=(",", ":"), default=str)` call and so
diverge identically.

### Class 1: exponent formatting — closed

Python's `repr` and ECMAScript's `Number.prototype.toString` produce the same
shortest round-trip digits and then place the decimal point differently.

| value | both existing functions | `remora.interop.jcs` |
|---|---|---|
| `1e-6` | `1e-06` | `0.000001` |
| `1e-7` | `1e-07` | `1e-7` |
| `1e20` | `1e+20` | `100000000000000000000` |

Closed by implementing the ECMAScript algorithm rather than patching `repr`
output: take the shortest digit string and the decimal-point position, then
choose fixed or exponential notation by where that position falls.

### Class 2: non-ASCII escaping — closed

`json.dumps` escapes every non-ASCII character by default, so `café` becomes
`café`. RFC 8785 requires the character itself. Closed by emitting raw
UTF-8 and escaping only what JSON requires: the quote, the backslash, and the
control characters below `0x20`.

### Class 3: key ordering for astral characters — closed

Object member names sort by UTF-16 code unit, not by code point. The difference
is invisible below the basic multilingual plane and inverts above it. An astral
character's leading surrogate sits below BMP characters above `0xE000`, so
code-point ordering puts it last where UTF-16 ordering puts it first.

### Class 4: number model — declined, with the reason

RFC 8785 serialises every number as IEEE 754 binary64. The feedback calls
adopting it "a deliberate decision, not a bug fix", and allows a class to be
"closed or explicitly declined". This is declined.

The APS vectors show the cost directly. For this input the suite's own expected
canonical form writes a different integer:

```
input     {"value": 1152921504606846976}
expected  {"value":1152921504606847000}
```

Every integer that rounds to the same double produces those same bytes, so the
canonical form no longer identifies which integer produced it.

RFC 8785 section 3.2.1 makes number data binary64 and recommends strings for
integers outside that range. Appendix B lists `~2**68` as
`295147905179352830000` and notes that extended precision is not considered. The
integer is adapted to binary64, and its image there is not unique: other
integers map to the same double and therefore to the same canonical bytes.

REMORA binds a decision to the exact arguments it was made about and recomputes
that binding immediately before execution. It therefore emits no canonical bytes
for an integer whose binary64 image it cannot tell apart from a neighbour's.

**The enforced property, stated exactly.** Integers whose binary64 image is not
unique are refused. That is narrower than "REMORA prevents two argument sets
from sharing canonical bytes", which this module does not do and which the first
version of this document claimed. Distinct float literals collapse in
`json.loads` before `canonicalise` runs, so `0.1000000000000000055511151231257827`
and `0.1` reach it as one value and share bytes, and `-0.0` normalises to `0`.
The integer rule is what the vectors test and what mutation confirms. The
overclaim was caught in review of the interop record by the corpus maintainer.

So `remora.interop.jcs` does not round. It refuses exactly the integers whose
binary64 form is shared with a neighbour, and serialises every other integer
exactly.

That test is finer than a magnitude bound, and running against the real vectors
is what showed the difference. `9007199254740994` sits above 2^53 and is still
the only integer mapping to its double. The suite serialises it exactly. An
implementation that refused everything above 2^53 would have failed a vector
with no ambiguity in it, and the first version of this module did exactly that.

**Consequence for the record.** A verifier that follows RFC 8785 exactly will
accept every document this profile can produce. A document containing an integer
that aliases a neighbour cannot be produced under this profile at all. Against
the 18 canonical-bytes vectors at suite revision 2c3bdef, that is two of them,
and both are cases where the suite's expected output writes a different integer
than the input. This is a real interoperability limit and belongs in the family
record as one.

### A fifth difference the feedback did not name

Both existing functions pass `default=str`, so a value JSON cannot represent is
coerced to its `repr` rather than refused. That is deliberate in
`_canonical_bytes`, where the side effect has already happened and losing the
audit record would be worse than recording a degraded projection. It is not
acceptable on a wire format, where the receiving side has no way to tell a
coerced value from a real one, so `remora.interop.jcs` raises instead.

## What is still missing for a citable record

The feedback lists three requirements for "REMORA APS Authority Profile v0" to
be citable. Their status:

| requirement | status |
|---|---|
| literal RFC 8785 bytes, classes 1-4 closed or explicitly declined | classes 1-3 closed in `remora.interop.jcs`; class 4 declined above |
| DID or key-id bound Ed25519 at the link level, not HMAC registry keys | **not done.** `PolicyDecisionToken` signs with HMAC-SHA256 against a registry key. `ExecutionLease` uses Ed25519 with a key id, so the material exists, but the token layer does not |
| an ActionRef type bound to the published schema | **not done.** No ActionRef type exists |

Two of three are open. The profile is therefore not citable yet, and the record
should say semantic alignment only.

## What cannot be verified from this repository

The 2026-08-28 run report, the adapter `remora_aps_mode_b.py` and its SHA-256
`700593e5...` are not in this repository and do not appear in its history. The
nine reported byte divergences, the adapter hash and the claim that the REMORA
side was exercised as described therefore cannot be checked here.

This repository's first invariant is that claims resolve to committed evidence.
Until the adapter is committed, no result attributed to it should be cited from
the REMORA side, including by us. Committing it is the precondition for a family
record that a maintainer can re-run from a clean clone, which is what the lab's
review process requires.

## Re-running the canonicalisation side

```bash
python -m pytest tests/test_jcs_canonicalisation.py -q
```

Fifty-one cases: the ECMAScript number forms, the escape set, UTF-16 member
ordering, the class 4 refusal and the collision that motivates it, and a guard
that the legacy format is unchanged.
