# Federation interoperability in REMORA

REMORA participates as a producer/runtime node, not as a Federation coordinator.

The stable entry point is `artifacts/interop/index.json`.

## Producer contract

For each public interop contract REMORA publishes:

1. the immutable source revision the contract was derived from
   (`source_revision`);
2. a manifest pinning every package file by SHA-256, and a content-addressed
   `package_digest` over those lines;
3. native claim ids and result vocabulary;
4. assumptions;
5. explicit non-claims and a claim ceiling;
6. a verifier request when independent reproduction is sought.

### Identity

A package cannot carry the Git revision that published it: the revision
would have to contain the bytes that name it. So three facts are kept apart.
`source_revision` is provenance and predates the package. `package_digest`
identifies the exact bytes a verifier evaluates; it is derived from the
manifest's file lines, and the manifest is never hashed into itself. The
revision a verifier actually consumed is recorded by the verifier in its run
record, and the reachable master revision carrying the frozen bytes is
recorded in the index's `freeze_record`, outside the package.

### Lifecycle

| State | Means | Advanced by |
|---|---|---|
| `DRAFT` | bytes may still change | nothing yet |
| `FROZEN` | `freeze_record` names a reachable master revision carrying exactly `package_digest` | the producer, after merge |
| `EXTERNAL_RUN_PENDING` | frozen, and the final pin has been given to a named verifier | the producer |
| `REPRODUCED` | a run record with `REPRODUCTION` or `SECOND_IMPLEMENTATION` over this `package_digest` | an external run record |
| `EXTERNALLY_VERIFIED` | a run record that meets the independence contract and covers every claim | an independent run record |

The state is written once, in `artifacts/interop/index.json`, and repeated in
the contract's manifest. The package files carry no state label, so a freeze
changes no bytes. An author run advances nothing. A test
refuses an index whose state exceeds its records, so a contract cannot be
marked verified before the record exists.

### Freezing a package and giving the pin

Freezing is a producer step after merge, done with
`scripts/interop_package.py` so the pin is checked rather than typed.

1. `python scripts/interop_package.py --check` recomputes every digest. It
   refuses a package whose manifest, index, claim packet or verifier request
   disagree, and one whose files name a revision other than `source_revision`.
2. After the package has merged, `python scripts/interop_package.py --freeze
   <contract-id> <master-revision>` reads every package file out of that
   revision's tree and checks the bytes hash to the manifest. It then writes
   `freeze_record` (revision, `package_digest`, date) and sets the lifecycle
   to `FROZEN` in the index and the manifest. The commit that records the
   freeze is a later commit than the one it names, so nothing pins itself.
3. The pin given to a verifier is the contract id, the `package_digest`, the
   frozen revision and the manifest path. Posting it on the control board and
   recording the verifier with `--confirm-pin` moves the contract to
   `EXTERNAL_RUN_PENDING`.

### After an external run

The verifier publishes its run record. The producer reviews it within the
window in the verifier request and records it under `external_runs`. That
moves the contract to `REPRODUCED`, or to `EXTERNALLY_VERIFIED` if the record
meets the independence contract. Only then is the edge status outside this
repository updated. REMORA may afterwards run the verifier's reader in its own
CI, pinned to the reader revision named in the run record, and retain the
output as a CI artifact. That rerun is a `REPRODUCTION` of the external
record, kept as evidence; it adds no state, creates no REMORA authority and
never feeds a policy decision.

### Diversity and independence

A run record states two facts. Implementation diversity says what ran:
`AUTHOR_IMPLEMENTATION`, `REPRODUCTION` (REMORA's reference verifier run by
someone else) or `SECOND_IMPLEMENTATION`. Independence says whether the
record counts as an independent verification: `INDEPENDENT` or
`NOT_INDEPENDENT`. `INDEPENDENT` is allowed only for a second implementation
maintained outside REMORA, run by an external operator, importing neither
REMORA runtime code nor the reference verifier, with the claim ceiling and
non-claims repeated. The schema (`external-run-record-v1`) rejects any other
combination. A second implementation that misses one condition is real
evidence and is recorded; it moves the contract to `REPRODUCED`, not to
`EXTERNALLY_VERIFIED`. This is the claim and provenance discipline of
aeoess/agent-governance-vocabulary#179.

## Foreign evidence

`external-evidence-ref-v1` preserves the producer's native claim and result.
The record is opaque to authority semantics. Merely attaching a foreign
attestation, verifier result or receipt does not authorize a tool call and
cannot promote a REMORA gate outcome.

## Action lineage and attribution

`action-lineage-v1` provides join references across the existing REMORA action
lifecycle. `consumed-artifact-v1` records that an external artifact was
referenced in a named role. Neither format claims causal importance, payment
entitlement or that an external effect occurred.

Runtime wiring is deliberately separate from these contracts. Any future code
that lets an external artifact influence policy must define a deployment-owned
admission policy and receive its own threat model, tests and capability-register
entry.

## Running a verification round

The steps below are what the verifier request asks for, written as a
checklist for a project that wants to verify a REMORA artifact.

1. Pin the inputs. Take `package_digest` and every file digest from the
   contract's `manifest.json`, and the input paths and digests from
   `verifier-request.json`. Record them, with the Git revision you fetched
   them from, in your own run report before anything runs.
2. Implement separately. The implementation lives in a codebase REMORA does
   not maintain and imports neither REMORA runtime code nor
   `reference_verifier.py`. A fresh clone that runs REMORA's own verifier is a
   reproduction, not an independent implementation.
3. Classify two things separately: implementation diversity
   (`AUTHOR_IMPLEMENTATION`, `REPRODUCTION`, `SECOND_IMPLEMENTATION`) and
   independence (`INDEPENDENT`, `NOT_INDEPENDENT`). Only `INDEPENDENT` closes
   `external_verification: PENDING`; a second implementation on its own moves
   the contract to `REPRODUCED`.
4. Report one result per native claim and case, using only `ESTABLISHED`,
   `CONTRADICTED` and `NOT_ESTABLISHED`. A layer the public material cannot
   support stays `NOT_ESTABLISHED`; it is not rounded up.
5. Record the exact implementation revision, command, environment, input
   digests, the `package_digest` and the REMORA Git revision you consumed next
   to the results, in the shape of `external-run-record-v1`.
6. Repeat the producer's claim ceiling and non-claims from the claim packet
   in your report, so a reader of your report alone cannot read more into the
   result than the producer claimed.
7. Review and publish. The request proposes a seven-day producer review, then
   publication; an unresolved disagreement is published as a disagreement, not
   withheld.

The round is complete when the report is public and the producer has
recorded the outcome against the contract in `index.json`. Verification of the
artifact is exactly that: it is not endorsement of REMORA, and it creates no
dependency, membership or authority in either direction.

### A round that has been run

The pattern above has been exercised once from outside, on a conformance
corpus rather than an interop contract. In darklordVirtual/REMORA-research#629,
Rul1an ran corpus-adequacy against `conformance/evidence-sufficiency-v1/`
with a separately maintained tool and an agreed seeded-fault list. The first
run found survivors the maintainer had not found. The report was published
unchanged and the survivors were kept as open gaps. v1.1 and v1.2 closed
them, and the external tool was run again on each. The record, with the pinned
digests and every count, is
[`docs/assurance/external_adequacy_evidence_sufficiency_v1.md`](../assurance/external_adequacy_evidence_sufficiency_v1.md).
Cases written after a fault was known are labelled as repair, not as
independent evidence, in that record and in NEGATIVE_RESULTS.md.

## Asking REMORA to reference your artifact

The consumer side is narrower. REMORA can record that an external artifact
was referenced in a named role (`consumed-artifact-v1`) and can carry your
native claim and result as an opaque reference (`external-evidence-ref-v1`).
Open an issue with the artifact's revision, digest and the role you intend.
The reference is admitted by a deployment-owned step and never alters a
decision. Attribution stays attached to the originating project.

