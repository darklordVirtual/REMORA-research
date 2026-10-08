# REMORA report-result component for federation-port/v0

A [federation-port](https://github.com/aeoess/federation-port) `action_evaluation`
component, written and maintained by REMORA-research against the published contract
(`spec/CONTRACT.md`) with no change to federation-port's `src/`. Design:
[docs/interop/FEDERATION_BRIDGE.md](../../../docs/interop/FEDERATION_BRIDGE.md).

It gates a new action on REMORA's native result for one earlier report. V0 checks run before
dispatch, so it can never describe the result of the action being dispatched.

## What it checks

It receives a `remora-report-check-v1` document: the requested report and REMORA's signed
results (`remora-federation-result-evidence-v1`), one per report.

```json
{ "format": "remora-report-check-v1",
  "requested": { "operation_id": "op-late", "report_id": "report-2",
                 "report_digest": "<optional sha256>" },
  "results": ["<base64 result evidence>", "..."] }
```

It reports one claim, `remora.report_result`. The claim is established only when all of the
following hold:

- a result verifies in `REMORA/FEDERATION-RESULT/v1` under a key the customer pinned;
- it is for the configured native claim and names a report subject with its digest;
- it is exactly the requested report;
- REMORA's native status for that report is `ESTABLISHED`.

Otherwise the claim is not established, with the reason. A native `CONTRADICTED` is reported
as `native_contradicted:<reason_code>`, so the native reason survives.

Selection is the adapter's own. A request names the report by id or digest. With no request,
one eligible result is selected as `single_available`; several are refused as
`report_selection_ambiguous`. It never takes the first, the last or an established one.
Results for two operations, or one report id naming two digests, are refused too. So are two
signed results for the selected report that are not the same statement
(`conflicting_results_for_report`): the order results were supplied in never decides the verdict.

The output evidence (`remora-report-check-result-v1`) keeps the request and the selected
report's identity and digest. It also keeps both selection rules (the adapter's and the one
REMORA signed) and REMORA's native result and reason beside the claim status. Results that did
not verify are listed by reason.

Each limit is in `manifest.json`. It requests no privilege, no secret and no data destination.

## Policy

```json
"remora-research/report-result": {
  "path": "<this directory>",
  "version": "0.1.0",
  "manifest_digest": "<digestJson(manifest)>",
  "artifact_digest": "<manifest.artifact.digest>",
  "privileges_granted": [],
  "destinations_allowed": [],
  "config": { "trusted_keys": ["<REMORA result signer public key, 64 hex>"],
              "native_claim": "definite_support" }
}
```

## Acceptance

`tests/remora-report-result.test.ts` evaluates each report of the LATE and LATE-CONFLICT cases
on its own submission, so all four expectations are checked. These cases are local synthetic
reproductions of the semantics of Rul1an's public fixtures on #177. Each submission checks the
admission or refusal and the stored evidence. The tests also cover the refusals before dispatch
and a workflow that also requires REMORA's authorization component. The fixtures
(`artifacts/interop/federation-port-v0/report-results.json`) come from
`scripts/build_federation_port_v0_fixtures.py` and are signed with published test keys.
`tests/test_federation_report_selection.py` checks them against REMORA's own verifier.

The `held-out` tests in the same file were written after the component shipped and sign their
own results with the published test seed. They cover:

- one report id naming two digests, and selection by digest alone;
- two differing signed results for one report, in both orders;
- every reason a submitted result is set aside for, each recorded under `unverified`;
- every native status other than ESTABLISHED;
- a sweep that flips each bit of the signed payload and each byte of the signature;
- every order and subset of the LATE results, with and without a request;
- canonical output evidence, so key order in the request is not visible in its bytes.

Each held-out selection case runs the component alone first and then through the unmodified
runtime. The first run discriminates on behaviour, not on the artifact pin. The maintainer's
mutation check of this suite found the conflicting-results gap (`NEGATIVE_RESULTS.md` §77).
The tests remain the producer's own.

[`../remora-adapter/reproduce.sh`](../remora-adapter/reproduce.sh) installs and seals this
component beside the authorization component and reports its tests separately. To run only
these tests against a federation-port checkout:

```console
$ FEDERATION_PORT_DIR=<federation-port> node --test --test-concurrency=1 tests/remora-report-result.test.ts
```

These are the producer's own tests, so a reproduction is not an independent check.
