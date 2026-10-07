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

## Run the tests

```console
$ git clone https://github.com/aeoess/federation-port && cd federation-port
$ git checkout 92d5078af3bbd3610ce4901378e913d5f370a68b && npm ci
$ cd <REMORA-research>/integrations/federation-port/remora-adapter
$ FEDERATION_PORT_DIR=<federation-port> node --test --test-concurrency=1 tests/remora-adapter.test.ts
```

The fixtures come from `scripts/build_federation_port_v0_fixtures.py` in
REMORA-research and are signed with published test keys. After editing
`adapter.ts`, reseal the manifest with `--seal --write`.
