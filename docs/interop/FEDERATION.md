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
