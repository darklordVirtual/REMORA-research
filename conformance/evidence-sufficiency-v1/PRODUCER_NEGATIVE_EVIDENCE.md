# Producer-side negative evidence profile

Status: synthetic REMORA research/conformance artifact.

This profile implements one narrow inference boundary:

> Declared capability, mandatory emission, and complete bounded observation are separate premises.

The supported property is `no_delegation_in_window`. It is intentionally a
historical, bounded claim. It is **not** architectural `non_bypassability`.

## Inference boundary

An absence-based establishment requires all of the following synthetic premises:

1. the bounded scope is accepted;
2. the producer declaration is present;
3. `read_delegation` is declared;
4. that capability was effectively available in the evaluated scope;
5. delegation evidence was mandatory to emit when present;
6. the collection window is closed;
7. required emitted evidence reached the evaluated collection;
8. no relevant sampling/filtering/suppression gap remains;
9. no delegation event is observed.

The implication being tested is therefore:

`delegation occurred in scope -> delegation evidence would be present in this evaluated collection`

A direct accepted delegation event is asymmetric: it can refute
`no_delegation_in_window` without first proving the negative-evidence coverage
needed to establish absence.

A known empty declaration (`PRESENT` with `declared_capabilities: []`) is
different from an unavailable declaration (`UNAVAILABLE`). The checker reports
distinct unresolved obligations for them.

## Harness isolation

`producer-cases.json` contains authored expectations and metadata, but
`run_producer_negative_evidence.py` constructs the checker request from an
explicit allowlist containing only:

- `property`
- `observations`
- `context`

The deterministic run artifact contains a regression witness showing that
mutating only `expect` and `metadata` leaves the checker input unchanged.

## Provenance and scope

This is additive to the commit
`f10ca2a493755f64df9225a8ccb5636aa344a43a`. It does not modify
`decision-to-effect-v1`, the original evidence-sufficiency fixtures, or their
run record.

The profile was motivated by the evidence-sufficiency review thread in CoSAI
WS4 issue #189 and by the REMORA Evidence Sufficiency SDD Addendum v0.2. The
fixtures are authored synthetic cases. `metadata.provenance` is deliberately
empty because they are not claimed to be executions of the external producer
implementation discussed in that thread.

## Non-claims

This artifact does not claim:

- production evidence or production enforcement;
- independent validation;
- OASIS or CoSAI conformance or adoption;
- completeness for arbitrary producer pipelines;
- architectural non-bypassability.

It is a bounded, executable regression artifact for negative-evidence inference.
