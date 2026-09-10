# REMORA x APS profile v0.2 pre-run mapping

Status: mapping frozen before execution. This file is not a conformance result.

Date: 2026-09-09

## Why v0.2 exists

The last recorded REMORA x APS profile v0.1 run used APS corpus
`cd5cce183fa3a5c58c00723f61383b1e1ea6ac40` and reported 25/25 APS vectors
with zero divergences, plus 5/5 REMORA-to-APS mapping checks. That record stays
unchanged.

Since that run, APS materially changed the evidence machinery around the corpus:

1. `accountability-record` now declares `crypto` and Draft 2020-12 `schema` as
   separate required layers. Schema-owned negatives are decisive only when the
   declared instance-path and keyword binding is observed.
2. Cross-stack families now have a registry-driven `verify:cross-stack` gate.
3. `token-exchange-attenuation-v0` was added. It separates the attenuation
   invariant into P1 scope monotonicity, P2 claim locality, and P3 transcription
   creates no authority.

The v0.1 adapter and mappings are not rewritten to fit these changes.

## Baseline-equivalence check

Before defining v0.2, the current repository state was compared with the code
and APS fixture inputs used by the v0.1 run.

- `remora/interop/aps/adapter.py` is byte-identical to the committed adapter at
  REMORA commit `98e9f6fd9d5fc4a4dd041780044a7be874d3bfd3` (Git blob
  `66b8e1c50924d2a545b11f9cf90bc896819a94d0`).
- `remora/interop/aps/mappings.py` is byte-identical at the same baseline (Git
  blob `882fa7af758d958a432f678f9f2afdf256a3c539`).
- The APS `actionref-canonical` fixture is unchanged from the v0.1 corpus.
- The APS `accountability-record` fixture has the same Git blob at the v0.1
  corpus and current APS tip: `4acca9d88ca1da9c348bcd06b49498b4ca4230b1`.
- All seven files in `receipt-decision-relation-v1` have the same Git blobs at
  the v0.1 corpus and current APS tip.
- `remora/interop/jcs.py` changed after the v0.1 run to make additional
  unrepresentable values fail as `NotCanonicalisable` (very large integers and
  unpaired surrogates). The change explicitly leaves RFC 8785 output unchanged
  for values the module accepts. None of the three v0.1 families changed their
  input bytes.

This is deterministic input/code equivalence, not a new runtime observation.
A new runtime record must still be produced before claiming a fresh run.

## v0.2 standing rules

1. Profile v0.1 is inherited as-is. Its mappings are not amended.
2. APS schema validation is adapter evidence. REMORA does not gain an APS JSON
   Schema validator in its runtime architecture.
3. `token-exchange-attenuation-v0` P1 maps to REMORA's existing delegation-chain
   attenuation. The adapter does not implement subset semantics itself.
4. P2 and P3 are `NOT_RUN`. REMORA has no RFC 8693 `upstream_claims` / `act`
   attribute-policy evaluator. Implementing those rules in the adapter would
   test the adapter, not REMORA.
5. Any future attempt to map P2/P3 requires a new profile version unless REMORA
   independently gains a real corresponding runtime property first.

## Accountability schema layer

The APS manifest is the source of truth for the layer declaration. v0.2:

- requires the `schema` layer to be present in `required_layers`;
- requires Draft 2020-12;
- verifies the schema file bytes against `schema_sha256` before validation;
- meta-validates the schema;
- requires positives to be schema-valid;
- for schema-owned negatives, requires the exact manifest error binding;
- reports crypto/digest negatives as non-decisive for the schema layer.

At the current APS tip the decisive bindings are:

- `DECISION_NOT_IN_ENUM` -> `/decision` + `enum`
- `SIG_ALG_NOT_CANONICAL` -> `/sig_alg` + `const`

This reproduces APS' declared schema-layer semantics with Python `jsonschema`.
It is explicitly labelled adapter evidence.

## token-exchange-attenuation-v0 mapping

### P1: RUN

APS P1 states that T2 scope must be a subset of T1 scope and that a widening
exchange is invalid before request evaluation.

The adapter maps the two opaque scope sets to two consecutive REMORA
`DelegationLink.scope` values and invokes the existing REMORA delegation-chain
verifier. The measured predicate is whether REMORA reports
`scope_widened_at_link:1`. It also records REMORA's `effective_scope()`, which
is the intersection of every link.

No REMORA core code is changed to support this mapping.

### P2: NOT_RUN

APS P2 requires evaluation of T2 to read only attributes present on T2. REMORA's
A2A governance envelope carries no `upstream_claims` attribute namespace and
has no corresponding attribute evaluator. There is therefore no REMORA property
to execute for this vector axis.

### P3: NOT_RUN

APS P3 combines transcribed attributes with T2 scope, audience and actor
conditions. REMORA verifies delegation scope and envelope audience, but does not
implement the RFC 8693 `act`/`upstream_claims` policy procedure described by this
family. Recreating it in the adapter is forbidden because it would be adapter
self-evidence.

## Runner

```sh
PYTHONPATH=REMORA-research \
python -m remora.interop.aps.adapter_v0_2 \
  --aps-suite aps-conformance-suite \
  --output /tmp/remora-aps-profile-v0.2.json
```

The runner exits non-zero if:

- any inherited v0.1 vector or mapping diverges;
- the APS schema layer is missing, unpinned, malformed or disagrees on a
  decisive vector;
- no P1 cases are present; or
- REMORA's P1 observation diverges from the APS vector validity.

No expected v0.2 result count is written here. The mapping is deliberately
committed before the first run so the result cannot shape the mapping.
