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

[`contract-probes.test.ts`](contract-probes.test.ts) holds 27 probes and two
checks: the pinned revision with `src/` unmodified, and the coverage map
against the test files actually present. A probe titled `CP-<section><letter>`
asserts that a rule holds; a failure is a contract violation at the pinned
revision. A probe titled `CP-F<n>` is a finding: it asserts the behaviour
observed at the pinned revision, so a change upstream fails it and the finding
is looked at again.

Probe components are generated into temporary directories and sealed with the
runtime's own `artifactDigest`. Nothing under federation-port's tree changes.

## Findings

Four behaviours at `92d5078` that a reader of the contract would not expect.
None produces a second side effect; the idempotency key holds in all four.
CP-F1 and CP-F4 are one fault reached two ways, found as such by the TLA+
model in [`formal/tla`](../../../formal/tla/README.md): a later attempt's
failed-and-retriable outcome overrides an earlier attempt that may have
reached the provider.

| Probe | Rule | Observed |
|---|---|---|
| CP-F1 | 7, lease | A confirmation from an attempt whose lease another worker already took over is stored on the attempt but not on the operation. If the later attempt failed retriably, the operation stays `failed`, the first caller is told `failed`, and after the deadline the operation is closed with `approval_expired_before_retry`. The provider performed the refund. It needs clock skew between workers, which section 10 lists as unhandled. |
| CP-F2 | 5.5 and 7 | An attempt that ends `unknown` without having sent anything is retried after `valid_until`. The provider's first request arrives an hour after the deadline. The deadline bounds admission, not the first provider contact. |
| CP-F3 | 9 | A claim's `reason` is stored verbatim and unbounded. An adapter that writes the action arguments into it puts them into provenance; a 100 kB reason is accepted. |
| CP-F4 | 4 and 7 | One worker, no skew, no crash. Attempt 1 reaches the provider and its response is lost: `unknown`. The retry cannot reach the provider: `failed`, retriable. Past the deadline the operation is closed with `approval_expired_before_retry` while the refund exists. The TLA+ model found it before the probe was written. |

The coverage map gives each finding's conditions, consequence and a suggested
change. A patch for CP-F1, CP-F3 and CP-F4 and a wording change for CP-F2 are
proposed upstream as aeoess/federation-port#1, with six regression tests; the
maintainer has not reviewed it yet.

## How strong the probes are

Each probe was checked against a fault in the runtime it is meant to catch.
The fault was one single-edit change to `src/runtime` per probe, run in a
scratch checkout and reverted. Examples: remove the version check, take the
latest deadline instead of the earliest, drop the lease test, make a late
confirmation final. Every probe failed on its fault. CP-F4 was added later
and was checked the other way: it fails on a runtime patched with the
uncertainty-sticky rule the model proposes. One fault was equivalent (a looser
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
