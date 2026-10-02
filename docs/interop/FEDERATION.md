# Federation interoperability in REMORA

REMORA participates as a producer/runtime node, not as a Federation coordinator.

The stable entry point is `artifacts/interop/index.json`.

## Producer contract

For each public interop contract REMORA publishes:

1. immutable producer/source revisions;
2. pinned artifact digests;
3. native claim ids and result vocabulary;
4. assumptions;
5. explicit non-claims and a claim ceiling;
6. a verifier request when independent reproduction is sought.

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

1. Pin the inputs. Take the `published_revision`, the fixture path and the
   `sha256` from the contract's `verifier-request.json`. Record them in your
   own run report before anything runs.
2. Implement separately. The implementation lives in a codebase REMORA does
   not maintain and imports neither REMORA runtime code nor
   `reference_verifier.py`. A fresh clone that runs REMORA's own verifier is a
   reproduction, not an independent implementation.
3. Classify the run as `AUTHOR_RUN`, `REPRODUCTION`, `SECOND_IMPLEMENTATION`
   or `INDEPENDENT_IMPLEMENTATION`. Only the last two can close an
   `external_verification: PENDING` entry in `index.json`.
4. Report one result per native claim and case, using only `ESTABLISHED`,
   `CONTRADICTED` and `NOT_ESTABLISHED`. A layer the public material cannot
   support stays `NOT_ESTABLISHED`; it is not rounded up.
5. Record the exact implementation revision, command, environment and input
   digests next to the results.
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

