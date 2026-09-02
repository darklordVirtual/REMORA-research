# REMORA APS Interop Profile v0.1

Status: proposal, normative for the next APS run, not a conformance claim.
Written 2026-08-30, before any of the four families below was executed against
REMORA.

This document fixes the mapping between APS conformance vocabulary and REMORA
vocabulary in advance. It exists because a mapping drawn to fit the answers is
not evidence. The corpus maintainer made that point against the `aae-envelope`
families in the
[`remora-edd8a4e` record](https://github.com/Agent-Authority-Conformance/aps-conformance-suite/blob/main/interop/remora-edd8a4e/SOURCE.md).
This profile takes it as a rule.

The canonicalisation rationale that precedes this profile is
[docs/design/aps-authority-profile-v0.md](../design/aps-authority-profile-v0.md).
That document settles the byte layer. This one settles the semantic layer for
four families and declines the rest.

## Standing rules

These bind every run performed under this profile.

1. APS is an external conformance engine. It does not shape REMORA's
   architecture, its data model or its wire formats. Where APS and REMORA
   disagree about meaning, the profile records the disagreement; it does not
   resolve it by changing REMORA.
2. The mapping is frozen before the run. Any change to a mapping in section 3
   after a result for that family is known requires a new profile version and a
   new interop record. The old record stays as written.
3. Mode B only. REMORA's own functions compute every value that is compared.
   No APS SDK function computes a value on REMORA's behalf. An adapter that
   cannot compute a value from REMORA code declares the family not run.
4. A family is claimed only when the property under test is a property of
   REMORA. A property that the adapter implements on its own is adapter
   evidence, and the record says so in those words.
5. Fail closed on missing material. Where a family requires key material or a
   REMORA artifact the deployment has not configured, the adapter refuses and
   records a refusal with its reason. It never substitutes a weaker mechanism.
6. `remora/json-sorted-v1` never changes. Every internal binding already
   written under it stays verifiable. APS-facing bytes are produced by
   `remora/jcs-rfc8785-v0` (`remora.interop.jcs`) and by nothing else.

## 1. The frozen baseline

The `remora-edd8a4e` record is historical evidence and is not rewritten. It
documents the canonical-bytes family at 16 of 18 vectors from
`remora.interop.jcs`, 10 of 18 from the legacy `_canonical_bytes`, and two
declared refusals on the number model. It also classifies fourteen other fixture
families, and the six under `cross-stack/`, as having no REMORA counterpart. Its
adapter hash, its pins and its author-produced label stay as recorded.

Work under this profile adds records. It does not amend that one.

## 2. Term mapping, normative

The five terms the rest of this document builds on.

| APS term | REMORA counterpart | binding artifact |
|---|---|---|
| ActionRef | exact-call identity | `canonical_tool_call_hash(name, arguments, tenant, target)` in `remora/policy/observation.py` |
| delegation | authority grant, then dispatch binding | `PolicyDecisionToken` (grant, HMAC, single-use `jti`), then `ExecutionLease` (dispatch, Ed25519 with `kid`) |
| receipt | execution and effect evidence | `ToolResultEnvelope` in `remora/enforcement/result_envelope.py` and `EffectBlock` |
| accountability record | decision plus audit entry | `DecisionEnvelope` in `remora/governance/envelope.py` and the tenant audit chain entry |
| provenance | authority provenance | `toolspec_hash`, `toolspec_version`, `tool_contract_bundle_hash`, `intent_authority_hash`, `policy_bundle_hash`, all carried on the lease |

Two asymmetries follow from that table and are load-bearing for section 3.

An APS `action_ref` is a correlation key. The suite's own accountability
vectors 10 and 11 are a pair sharing one `action_ref` in the same second with
distinct `action_digest` values, which proves it is not a unique identifier. A
REMORA tool-call hash covers the full argument set and is recomputed
immediately before dispatch, so it is an identity. The profile therefore
forbids using an APS `action_ref` anywhere REMORA requires exact-call identity,
in either direction.

APS delegation is one relation. REMORA splits it in two, and the split is the
security property. The grant is issued by the authority domain and consumed once
at the enforcement point. The lease binds the consumed grant to a concrete call
in the execution domain. A mapping that collapses the two loses the single-use
consumption, so each family below names which of the two it maps.

## 3. The four families

Priority order for implementation. Each subsection fixes the mapping, names
what the family cannot test, and states the refusal conditions.

### 3.1 actionref-canonical

APS computes `action_ref` as SHA-256 over the RFC 8785 canonicalisation of
`{agentId, actionType, scopeRequired, timestamp}`, with each scope string
normalised to NFC and `scopeRequired` sorted by Unicode code point.

REMORA has no ActionRef type and gains none. The adapter constructs the APS
structure from deployment-owned REMORA fields:

| APS field | REMORA source | note |
|---|---|---|
| `agentId` | lease `actor_identity` | not a DID; a REMORA principal identity string, recorded as such |
| `actionType` | `ToolSpec.action_type` | the deployment-owned category, never `tool_id` and never an agent-supplied value |
| `scopeRequired` | `ToolSpec.credential_scope` | the deployment-owned credential scope tuple |
| `timestamp` | lease `issued_at` | UTC, second precision, `Z` designator, as the fixtures carry; REMORA's own string is ISO-8601 UTC and the adapter reduces it |

NFC normalisation and code-point ordering are performed by the adapter over
those inputs, and the JCS bytes come from `remora.interop.jcs`.

What this tests is whether REMORA's canonicalisation and ordering agree with
the reference on a structure REMORA does not otherwise emit. That result covers
the byte layer and the ordering rule, and stops there. The record says:
agreement on the canonical form of an adapter-constructed ActionRef, computed
with REMORA's canonicaliser.

Refuse when: `credential_scope` is empty, `action_type` is absent, or the
ToolSpec bundle is unverified. An ActionRef over agent-supplied values would
invert the authority direction the whole system is built on.

Declined: any use of the resulting `action_ref` as a REMORA identifier.

### 3.2 accountability-record

APS attests two facts about one action: the boundary decision, one of `allow`,
`deny` or `halt`, and whether it executed. The signing preimage is the JCS of
the record without `sig`; `sig` is Ed25519 and `sig_alg` is the constant
`Ed25519`. `action_digest` is SHA-256 of the JCS of the inline `action` object.

REMORA's verdict space has four values and does not fit the three-valued enum.
The mapping is lossy in one direction and is fixed here:

| REMORA state | `decision` | `executed` |
|---|---|---|
| ACCEPT, grant consumed, dispatch completed | `allow` | `true` |
| ACCEPT, grant issued, not consumed before expiry | `allow` | `false` |
| VERIFY or ESCALATE, unresolved when the record is written | `halt` | `false` |
| VERIFY or ESCALATE, resolved as refused | `deny` | `false` |
| ABSTAIN | `deny` | `false` |

`executed` comes from `EffectBlock.executed`, not from the verdict. The suite's
vector 9 (`deny` with `executed: true`) exists precisely because the two fields
are independent, and REMORA must be able to emit that combination when its own
records show a boundary violation.

The mapping is not invertible: `deny` covers both ABSTAIN and a refused review,
and `halt` covers both VERIFY and ESCALATE. The adapter therefore carries the
REMORA verdict verbatim in a namespaced extension member, `remora_verdict`. A
consumer reading only the APS enum has lost the distinction between missing
information and a required higher authority, and the record says so.

`action_digest` is computed by the adapter over the APS `action` object
(`type`, `scope`, `timestamp`). It is not REMORA's `tool_args_hash` and does not
substitute for it: the two cover different preimages, and only
`tool_args_hash` covers the full arguments.

Signing. The record is signed with the Ed25519 lease key material
(`REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE`), and `signer_did` is that public
key rendered as `did:key`. REMORA does not resolve DIDs and does not claim to;
the rendering is a serialisation of a key REMORA already holds.

Refuse when: only HMAC lease material is configured. HMAC is not Ed25519, the
family's negatives turn on signature verification, and emitting a record signed
by a shared registry key under a field named `signer_did` would misrepresent
what a verifier can check.

Split within the family. The two signature negatives, `negative-tampered-payload`
and `negative-wrong-key`, are REMORA evidence: the verification runs through the
Ed25519 path in `remora/enforcement/lease_signing.py`. The three that turn on
record shape, `negative-schema-decision`, `negative-type-relabel` and
`negative-sig-alg-lowercase`, are adapter evidence, because REMORA has no APS
schema validator and the adapter would be testing itself. The record labels
each group separately and does not merge them into one count.

### 3.3 receipt-decision-relation

The family tests one cross-document property in two failure classes.
`DECISION_REF_MISMATCH` requires that the reference recomputed from the full
decision evidence and the receipt's `action_ref` equals `receipt.decision_ref`.
`VALID_UNTIL_NOT_LATER` requires that the decision's `valid_until` falls
strictly after the receipt's `issued_at`, with equality rejected. Binding is
settled before the temporal comparison, and the ordering is part of the
property.

This is the closest of the four to something REMORA already does, so the
boundary needs care.

| APS field | REMORA source |
|---|---|
| receipt | `ToolResultEnvelope` for the dispatch, plus its tenant audit-chain entry |
| `receipt.issued_at` | lease `issued_at` |
| decision evidence | the `DecisionEnvelope` fields covered by `envelope_hash()`, plus `policy_bundle_hash` and the grant `jti` |
| `decision.valid_until` | the grant's `expires_at`, from `PolicyDecisionToken`, not the lease's |
| `decision_ref` | SHA-256 over the `remora.interop.jcs` bytes of `{action_ref, decision_evidence}` |

`valid_until` maps to the grant rather than the lease because the grant is the
authority the dispatch rests on. The lease is the binding of that authority to
a call, and its window is a dispatch bound.

REMORA's runtime does more than this family tests. It consumes the grant `jti`
exactly once, recomputes the tool-call hash against the live arguments, and
rechecks expiry at consumption. The family explicitly does not exercise
dispatch-time enforcement, so none of that is evidence here and the record must
not present it as such. What is tested is whether REMORA's evidence, projected
into the family's shape, reaches the same classification on the seven vectors.

The adapter reports the family's classification names, `PASS`,
`DECISION_REF_MISMATCH` and `VALID_UNTIL_NOT_LATER`, and does not alter
REMORA's own comparison. If REMORA's runtime rule and the family's rule
disagree on a boundary case, the disagreement is the result and is recorded as
a divergence rather than reconciled in the adapter.

Refuse when: the decision evidence for a receipt cannot be assembled from
committed records, which is the case where a mismatch would be indistinguishable
from a missing artifact.

### 3.4 instruction-provenance

InstructionProvenanceReceipt v0.2 covers a declared set of instruction files
discovered under a `working_root`, nine path-canonicalisation rules,
exhaustiveness over the declared discovery patterns, and recomputation at
action time.

REMORA reads no filesystem to derive authority, and it should not start. The
family therefore splits, and the split is declared here rather than discovered
during the run.

Mapped. The envelope-level properties have a genuine counterpart, because
REMORA's authority set is exactly a declared, digested, deployment-owned set of
artifacts that is recomputed immediately before the action:

| APS concept | REMORA counterpart |
|---|---|
| declared instruction set | the verified `ToolSpecBundle` entries, each with `toolspec_hash` and `version` |
| per-entry digest | `toolspec_hash`, and `callable_digest` for the implementation |
| `delegation_chain_root` | `intent_authority_hash` |
| exhaustiveness over the declared set | `tool_contract_bundle_hash` over the bundle |
| recompute at action time | the enforcement point recomputing the binding before dispatch |
| `bound_to` | the grant `jti` and `proposal_id` |

Declined, with the reason. The nine path-canonicalisation rules have no REMORA
counterpart and the profile does not create one. Implementing them inside the
adapter would produce a passing family that tests the adapter's path handling
and says nothing about REMORA, which rule 4 forbids. They are recorded as no
counterpart.

Consequence: this family will yield the thinnest record of the four, and it is
listed last for that reason. If the mapped subset turns out not to be separable
from the path rules in the fixture, the correct outcome is to record the family
as not run rather than to widen the adapter.

## 4. Where the adapter lives

APS is a boundary. Its data model does not enter the core.

```text
remora/
  policy/
  enforcement/
  execution/
  governance/
  interop/
    jcs.py                 # existing, RFC 8785 bytes
    aps/
      profile_v0_1.py      # the constants and identifiers this document fixes
      mappings.py          # section 3, one function per family, pure
      adapter.py           # fixture in, result out; no REMORA state
      tests/
```

Constraints on that package.

No module under `remora/policy`, `remora/enforcement`, `remora/execution` or
`remora/governance` imports from `remora.interop.aps`. The dependency runs one
way, and a test asserts it, in the manner of the existing evaluation-leakage
import guard.

`mappings.py` holds pure functions from REMORA artifacts to APS structures. No
network, no clock, no environment reads. The clock and the environment belong
to the adapter, so that a mapping is testable against a fixture without a
running deployment.

The adapter never writes to a tracked result file. It writes to a path given to
it, and the check is a diff against the committed record, following the
sequence the `remora-edd8a4e` record established after the earlier
regenerate-in-place command was found unable to fail.

## 5. CI

A family record is only worth what a third party can re-run. The gate runs on
every change to `remora/interop/` and on a schedule:

| requirement | reason |
|---|---|
| Linux and Windows | the two defects found in the last run were Windows-only |
| clone with `core.autocrlf=false` | a default Git for Windows clone rewrites every fixture and reports the suite as broken |
| pinned APS suite commit | `APS_SUITE` accepts whatever it is pointed at, so an unpinned pass proves nothing about a named revision |
| pinned REMORA commit, asserted before the run | same reason, on the other side |
| adapter SHA-256 over the bytes git stores | a checkout that converts line endings hashes differently |
| diff against the committed results, fail on difference | a run that regenerates its own expected output cannot fail |

Windows note for whoever writes the job: `spawnSync` on the extensionless
`node_modules/.bin` shim returns ENOENT there, and needs `shell: true`. That
defect is in the suite's own meta-test, not in the adapter, and is reported
upstream in the `remora-edd8a4e` record.

## 6. Independent reproduction

Every REMORA interop record so far is author-produced. One record reproduced by
someone who is not the maintainer is worth more than a further family, and it
is the next research step this profile is written to enable.

What that requires from us: two pinned revisions, one command, an adapter whose
hash is published, and expected output committed as bytes. Sections 4 and 5
exist to make the reproduction a single command against a clean clone.

## 7. Claim language

Permitted, when the evidence supports it:

> REMORA has independently reproducible interoperability evidence against
> selected APS conformance families.

Permitted for an author-produced run, which is what all current records are:

> Author-produced interoperability evidence against the named families at the
> named revisions.

Forbidden, and not conditionally:

> REMORA is APS compliant.

Also forbidden: aggregating families into a score, citing a family the adapter
computed on REMORA's behalf, and citing any result whose adapter is not
committed. The last one is why the 2026-08-28 report is not carried forward: its
adapter could not be located, so its 51 of 60 does not exist as evidence.

## 8. Order of work

1. This document, reviewed and merged, before any adapter code.
2. `remora/interop/aps/` skeleton with the import-direction test.
3. `actionref-canonical`, the smallest surface and the one that reuses
   `remora.interop.jcs` directly.
4. `accountability-record`, which needs the Ed25519 lease path and the verdict
   extension.
5. `receipt-decision-relation`, which needs decision evidence assembled from
   committed records.
6. `instruction-provenance`, mapped subset only, or recorded as not run.

Each family is a separate record with its own adapter hash and its own pins.
