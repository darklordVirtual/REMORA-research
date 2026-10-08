# Contract probes for federation-port/v0

Tests of the federation-port runtime against its own contract
([`spec/CONTRACT.md`](https://github.com/aeoess/federation-port/blob/92d5078af3bbd3610ce4901378e913d5f370a68b/spec/CONTRACT.md)),
written by REMORA-research and run against the unmodified runtime at
`92d5078`. They test the runtime, not a REMORA component, so any project on
aeoess/agent-governance-vocabulary#177 can run them next to its own adapter.

## What is here

[`contract-coverage.json`](../../../artifacts/interop/federation-port-v0/contract-coverage.json)
lists 32 rules of the contract, from section 2 to section 10. Each rule names
the tests that exercise it: federation-port's own (by test id), REMORA's
component tests, and the probes in this directory. A rule that no test
exercised before got one or more probes. The map was written by reading each
test against the rule, not by matching reason codes.

| Status | Rules |
|---|---|
| covered before the map | 16 |
| partly covered, probes added | 8 |
| probed, nothing covered it before | 6 |
| stated limit (section 10 says it itself) | 2 |

[`contract-probes.test.ts`](contract-probes.test.ts) holds 26 probes and two
checks: the pinned revision with `src/` unmodified, and the coverage map
against the test files actually present. A probe titled `CP-<section><letter>`
asserts that a rule holds; a failure is a contract violation at the pinned
revision. A probe titled `CP-F<n>` is a finding: it asserts the behaviour
observed at the pinned revision, so a change upstream fails it and the finding
is looked at again.

Probe components are generated into temporary directories and sealed with the
runtime's own `artifactDigest`. Nothing under federation-port's tree changes.

## Findings

Three behaviours at `92d5078` that a reader of the contract would not expect.
None produces a second side effect; the idempotency key holds in all three.

| Probe | Rule | Observed |
|---|---|---|
| CP-F1 | 7, lease | A confirmation from an attempt whose lease another worker already took over is stored on the attempt but not on the operation. If the later attempt failed retriably, the operation stays `failed`, the first caller is told `failed`, and after the deadline the operation is closed with `approval_expired_before_retry`. The provider performed the refund. It needs clock skew between workers, which section 10 lists as unhandled. |
| CP-F2 | 5.5 and 7 | An attempt that ends `unknown` without having sent anything is retried after `valid_until`. The provider's first request arrives an hour after the deadline. The deadline bounds admission, not the first provider contact. |
| CP-F3 | 9 | A claim's `reason` is stored verbatim and unbounded. An adapter that writes the action arguments into it puts them into provenance; a 100 kB reason is accepted. |

The coverage map gives each finding's conditions, consequence and a suggested
change. They are reported here and not yet raised upstream.

## How strong the probes are

Each probe was checked against a fault in the runtime it is meant to catch.
The fault was one single-edit change to `src/runtime` per probe, run in a
scratch checkout and reverted. Examples: remove the version check, take the
latest deadline instead of the earliest, drop the lease test, make a late
confirmation final. Every probe failed on its fault. One fault was equivalent (a looser
`valid_until` pattern is still caught by the round-trip check) and was
replaced by one that is not. This check was run once by hand while the probes
were written; it is not part of `reproduce.sh`.

## Run

`../remora-adapter/reproduce.sh` installs the probes into federation-port's
`test/` beside the two REMORA components and runs them with the whole suite
and alone; the JSON result carries them as `remora_contract_probes`. To run
only the probes against a checkout at the pinned revision:

```console
$ FEDERATION_PORT_DIR=<federation-port> node --test --test-concurrency=1 contract-probes.test.ts
```

They use federation-port's own `test/helpers.ts` and simulator, need Node 24,
and run offline once its dependencies are installed.

## Limits

These are the producer's tests of someone else's runtime. A probe that passes
shows the rule holds for the case it builds, not in general. The findings rest
on test doubles that wrap a loaded component in the runtime's process, as the
upstream V0b tests do; CP-F1 also needs two runtimes with different clocks on
one store.
