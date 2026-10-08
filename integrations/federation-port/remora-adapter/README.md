# REMORA authorization-evidence component for federation-port/v0

A [federation-port](https://github.com/aeoess/federation-port) `authority_evidence`
component, written and maintained by REMORA-research against the published
contract (`spec/CONTRACT.md`) with no change to federation-port's `src/`. Design:
[docs/interop/FEDERATION_BRIDGE.md](../../../docs/interop/FEDERATION_BRIDGE.md).

## What it checks

It receives REMORA evidence bytes (`remora-federation-evidence-v1`) for one
operation and reports three claims:

| Claim | Established when |
|---|---|
| `remora.authorization_integrity` | the Ed25519 signature in `REMORA/FEDERATION-ACTION/v1` verifies under a key the customer pinned |
| `remora.port_v0.bound_action` | the signed V0 projection names this workflow, operation id, tenant label, approval id and action |
| `remora.authorization_unexpired` | the evaluation instant is at or before the signed `valid_until`, which is also returned as the admission deadline |

Each claim's limits are in `manifest.json`. In short: the action is compared as
JavaScript values (`1` equals `1.0`), the tenant is a label, no principal is
carried, and expiry is not revocation. It never reports REMORA's full exact-call
binding, principal binding, custody isolation or an effect.

It requests no privilege, no secret and no data destination.

## Policy

```json
"remora-research/authorization-evidence": {
  "path": "<this directory>",
  "version": "0.1.0",
  "manifest_digest": "<digestJson(manifest)>",
  "artifact_digest": "<manifest.artifact.digest>",
  "privileges_granted": [],
  "destinations_allowed": [],
  "config": { "trusted_keys": ["<REMORA federation signer public key, 64 hex>"] }
}
```

Require all three claims on a workflow to admit only actions REMORA signed for
that exact operation.

## Reproduce

```console
$ integrations/federation-port/remora-adapter/reproduce.sh
```

It needs git, Node 24 and a Python with REMORA's dev dependencies (`PYTHON` selects it;
`--skip-python` leaves the REMORA-side suites out and records them as `not_evaluated`). It runs
the same procedure as the other outside adapters on #177:

1. clone `aeoess/federation-port` and check out `3a2f6ce405d1c4f86ac8f2591e136deb5dfbb333`
   (the merge of aeoess/federation-port#1; the components were first reproduced at `92d5078`);
2. install this component and the
   [report-result component](../remora-report-result/README.md) under `adapters/` and their
   tests under `test/`, changing nothing under `src/`;
3. seal both with federation-port's `scripts/seal.ts`, which must reproduce the digests pinned
   in their `manifest.json`;
4. check that `src/` is unmodified;
5. run federation-port's suite with both components and the
   [contract probes](../contract-probes/README.md): `node --test test/*.test.ts`, then the
   upstream and each REMORA file alone for the split;
6. run `tsc` with federation-port's `tsconfig.json` over the component and its tests;
7. separately, check REMORA's fixtures against the code and run REMORA's acceptance suites
   (`tests/test_federation_report_selection.py`, `tests/test_federation_bridge.py`);
8. unless `--skip-mutation`, run [`../mutation_check.py`](../mutation_check.py): single-edit
   faults in each component's `adapter.ts` (comparison flips, guard removal, status flips,
   index and constant shifts), each resealed and re-signed into the fixtures, run against that
   component's tests. A fault that survives without an entry in the component's
   `mutation-equivalents.json` fails the run, and so does a listed entry that no longer
   survives.

It writes `remora-federation-port-reproduction.json` (`remora-federation-port-reproduction-v1`)
and exits non-zero on any failure. CI runs the same script on every change.

At `3a2f6ce` the result is 193 of 193 federation-port tests: 54 upstream, 50 for this component,
60 for the report-result component and 29 contract probes. `src/` is unmodified, both seals match and `tsc`
passes. The mutation check kills 102 of 107 faults here and 122 of 131 in the report-result
component; every survivor is listed as equivalent with its reason. The REMORA acceptance
suites are reported beside it, not inside that count. These are the producer's own tests, so
a reproduction is not an independent check.

The `held-out` tests in `tests/remora-adapter.test.ts` were written after the first mutation
run, which found 34 of 107 faults surviving the 17 fixture-driven tests
(`NEGATIVE_RESULTS.md` §78). They sign their own envelopes with the published test seed and
cover:

- each refusal before and after the signature, and a correctly sized wrong signature;
- a sweep over every bit of the envelope and every byte of the signature;
- evidence addressed to another transport or component;
- the empty tenant label, malformed instants on both sides, and the inclusive deadline;
- null, nested and array-typed arguments, and an array against an object with index keys.

To run only this component's tests against a federation-port checkout:

```console
$ FEDERATION_PORT_DIR=<federation-port> node --test --test-concurrency=1 tests/remora-adapter.test.ts
```

The fixtures come from `scripts/build_federation_port_v0_fixtures.py` in REMORA-research and are
signed with published test keys. After editing `adapter.ts`, reseal the manifest with
`--seal --write`.
