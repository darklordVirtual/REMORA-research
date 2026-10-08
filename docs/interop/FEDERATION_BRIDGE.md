# REMORA Federation Bridge and loss-aware interoperability

Status: implemented 2026-10-07 for `federation-port/v0` (Mode A, portable
verifier). Context: [aeoess/agent-governance-vocabulary#177](https://github.com/aeoess/agent-governance-vocabulary/issues/177).
There, [federation-port](https://github.com/aeoess/federation-port) was
published as a V0 prototype. The next test it named was an adapter written by
another project, for a check it already performs, without changing the core.

## The problem

REMORA's native claims bind more than some federation transports carry. Its
exact-call binding covers the tool, the full argument content with scalar
types and array order, the tenant, the target and the principal.
The V0 transport carries the action as JavaScript values, a caller-supplied
tenant label, an approval id and per-component evidence bytes. A REMORA check
reported through V0 as "exact-call binding" would claim more than V0 can
carry.

The bridge does not weaken REMORA to fit a transport, and it never reports a
transport-level result as the native one.

## Two planes

```text
REMORA native assurance plane         authorization, exact-call binding, fresh authority,
        |                             lease, lifecycle, effect verification
        v
REMORA Federation Bridge              native envelope, capability declaration,
        |                             claim projection, projection records
        v
transport adapter (federation-port/v0, or a later transport)
        v
admission -> executor -> dispatch outcome -> (optional) REMORA effect verifier
```

The transport consumes a projection of the native model. It does not define it.

## Projection: a claim only gets weaker

| Result | Meaning |
|---|---|
| `PRESERVED` | the transport carries every dimension the native claim needs |
| `NARROWED` | a useful subset survives, exported as a separate, narrower claim |
| `NOT_ESTABLISHED` | the transport carries too little to establish it |
| `UNSUPPORTED` | the transport lacks the lifecycle or interface |

These describe projection strength, not the result of a check. The mapping is
data: [`projection-map.yaml`](../../artifacts/interop/federation-port-v0/projection-map.yaml)
names each native claim's dimensions and the capabilities each needs, and
[`capabilities.yaml`](../../artifacts/interop/federation-port-v0/capabilities.yaml)
states what V0 carries. `remora/federation/projection.py` derives the result
from both and from the action's own losses. `ProjectionMap.assert_export`
refuses an adapter claim the projection does not permit.

### federation-port/v0

| Native claim | Projection | Exported claim |
|---|---|---|
| authorization integrity | PRESERVED | `remora.authorization_integrity` |
| `exact_call_binding-v1.1` | NARROWED | `remora.port_v0.bound_action` |
| `fresh_authority_at_dispatch` | NARROWED | `remora.authorization_unexpired` |
| principal binding | NOT_ESTABLISHED | none |
| authority/executor custody isolation | NOT_ESTABLISHED | none |
| a native result for one report | NARROWED | `remora.report_result` |
| effect verification | UNSUPPORTED | none |

`remora.port_v0.bound_action` covers the tool, the argument values,
structure and array order as JavaScript values, the tenant label, the approval
id and the submitted evidence. Under V0 it does not cover the scalar type (`1`
and `1.0`), an authenticated tenant, the principal or an independently
authenticated target.

## The native envelope and its evidence

`remora/federation/models.py` describes one authorization once, before any
transport sees it (`remora-federation-action-v1`). It keeps REMORA's canonical
argument bytes, their canonicalization (`remora-canonical-json-v1`), their
digest and a typed scalar listing, so int and float stay distinct natively. A
field the workflow does not have is `null` and listed in `unavailable`.

The adapter receives the canonical envelope bytes, with the transport's
projection inside, signed with Ed25519 in `REMORA/FEDERATION-ACTION/v1`
(`remora-federation-evidence-v1`). The bytes travel base64-encoded and are
verified as sent, so no language's JSON encoding decides what was signed.

An action V0 would change is refused, not narrowed: an integer beyond 2^53 - 1
loses digits in JavaScript, so its argument values do not survive.

## The adapter (Mode A)

[`integrations/federation-port/remora-adapter`](../../integrations/federation-port/remora-adapter/README.md)
is a federation-port/v0 `authority_evidence` component. It verifies the
signature against a public key the customer pins, compares the signed V0
projection with the action the runtime will dispatch, and reports the three
exported claims. It holds no secret, reaches no network and does not run
REMORA.

[`reproduce.sh`](../../integrations/federation-port/remora-adapter/reproduce.sh)
installs it into federation-port's own tree at the pinned revision, seals it
with federation-port's `scripts/seal.ts`, checks that `src/` is unmodified and
runs federation-port's suite with it and with the report-result component
below. It reports 193 of 193 at `3a2f6ce`, the merge of
aeoess/federation-port#1: 54 upstream, 50 for this
component, 60 for the report-result component and 29 contract probes
(below). Of the component tests, 71 are held-out cases written after the
components shipped. It then runs
`integrations/federation-port/mutation_check.py`, which applies single-edit
faults to each `adapter.ts` and fails when one survives that component's
tests without a listed reason. Here it kills 102 of 107 faults, and 122 of
131 in the report-result component. Every survivor is listed as equivalent
in the component's `mutation-equivalents.json`. The first run of that check
found 34 survivors against the 17 fixture-driven tests
(NEGATIVE_RESULTS.md §78). REMORA's acceptance suites run
separately, and the result is written as JSON. CI runs the same script on
every change.

## Projection records

Every bridge result carries one `remora-federation-projection-v1` record per
native claim. It states the projection, what was preserved, what was not
established and the action's losses. It also carries the digests of the native
evidence, the transport evidence, the adapter, the map and the capability
declaration, with the REMORA and transport revisions.

## A result is about one subject

A claim result is always about a specific subject: an operation, or one
report, execution attempt or effect observation of that operation. Several
reports for one operation are not interchangeable:

```text
same operation + same claim id + different report  !=  same claim evaluation
```

This ambiguity was highlighted by Rul1an in the Federation #177 discussion
using the LATE and LATE-CONFLICT synthetic fixtures
([comment](https://github.com/aeoess/agent-governance-vocabulary/issues/177#issuecomment-6047105582)).
In LATE, a first report made before any result was delivered is CONTRADICTED
and a later one ESTABLISHED. In LATE-CONFLICT, the first is ESTABLISHED and a
second, made after a conflicting final result, is CONTRADICTED. Taking the
first, the last or any established report each gets at least one of these
wrong.

`remora/federation/subjects.py` and `remora/federation/results.py` make the
subject explicit:

- a `Report` digests its kind, operation id, report id, sequence and opaque
  native body together, so a report id cannot be moved to other bytes;
- `select_report` selects by a declared rule (`explicit_report_id`,
  `explicit_digest`, `single_available` or a named `declared_profile`). With
  several eligible reports and no selector it refuses
  (`report_selection_ambiguous`) and no result is produced;
- the native result (status and a bounded reason code, in a declared existing
  vocabulary) is signed with the claim, the subject and the selection in
  `REMORA/FEDERATION-RESULT/v1`. `verify_result` returns the native result
  only when the signed subject is the one asked about, and when the consumer
  holds the report, only when its bytes hash to the signed digest. Relabelling
  an ESTABLISHED result for report A as one for report B fails verification.

Claim ids stay claim ids (`definite_support`); the report is in the subject,
never in the claim name.

Projection records are now `remora-federation-projection-v2`. They add
`subject`, `evidence_selection` and `native_result` beside `projection`.
`projection` remains the transport-projection strength only, so a record can
say `native_result: CONTRADICTED` with `projection: PRESERVED`: the transport
faithfully carries a negative finding. `native_result` is `null` when the
record describes a projection at issuance, as the federation-port/v0 records
do. Their subject is the operation itself.

v1 records stay readable through `read_projection_record`. A v1 record has
no subject, so its `report_specific_binding` is `NOT_ESTABLISHED`, and the
reader never infers one from surrounding metadata. A v2 record alone does not
establish its binding either; the signed result does.

Over federation-port/v0 nothing changes for the runtime, and no core change
is needed. The adapter already binds each authorization to its operation id.
A report-specific result reaches V0 through the component below.

## The report-result component

aeoess placed the binding in the adapter, with the requested report explicit
in its input. V0 checks run before dispatch, so such a check gates a new
action on an earlier report's result.
[`integrations/federation-port/remora-report-result`](../../integrations/federation-port/remora-report-result/README.md)
is that `action_evaluation` component.

- Its input names the requested report and carries REMORA's signed results,
  one per report.
- It verifies each result against a pinned key and selects exactly the
  requested report. With several eligible reports and no request it refuses
  (`report_selection_ambiguous`). Two signed results for the selected report
  that are not the same statement are refused too
  (`conflicting_results_for_report`), so the order results were supplied in
  never decides the verdict (NEGATIVE_RESULTS.md §77).
- It reports `remora.report_result`, established only when REMORA's native
  status for that report is ESTABLISHED. A CONTRADICTED report is refused
  with its native reason.
- Its output evidence keeps the selected report's identity and digest, the
  selection rule, and the native result and reason next to the claim status.

The projection map exports this claim as NARROWED: the signature and the
report identity survive, but V0 has no check after dispatch
(`post_dispatch_check: false`). Its tests evaluate each LATE and
LATE-CONFLICT report on its own submission, so all four expectations are
checked inside an unmodified runtime.

The same subjects carry post-dispatch observations. An execution attempt
reported `provider_confirmed`, an effect observation `EFFECT_UNOBSERVABLE` and
a later one `EFFECT_VERIFIED` are three attributable results for one
operation, and none replaces another.

## Contract coverage and probes

[`artifacts/interop/federation-port-v0/contract-coverage.json`](../../artifacts/interop/federation-port-v0/contract-coverage.json)
maps 32 rules of federation-port's `spec/CONTRACT.md` (sections 2 to 10) to
the tests that exercise them: federation-port's own, REMORA's component
tests, and the contract probes in
[`integrations/federation-port/contract-probes`](../../integrations/federation-port/contract-probes/README.md).
Fourteen rules were exercised only in part or not at all before the map; 26
probes, run against the unmodified runtime, now cover them. Each probe was
checked once against a single-edit fault in `src/runtime` that breaks its
rule, and each failed on it. The probes test the runtime, not a REMORA
component, so other adapters on #177 can run them as they are.

Four probes recorded findings at `92d5078`. CP-F1: a provider confirmation
from an attempt whose lease another worker took over was not recorded on the
operation, which could then close as `failed` while the refund existed (it
needed clock skew between workers). CP-F2: an attempt that ended `unknown`
before sending was retried after `valid_until`, so the deadline bounded
admission and not the first provider contact. CP-F3: an adapter's reason text
reached provenance verbatim and unbounded. CP-F4: a lost response followed by
an outage closed the operation as `failed` past the deadline while the refund
existed, with one worker and no skew. The TLA+ model
`formal/tla/LeaseRetry.tla` found CP-F4 first and showed that CP-F1 is the
same fault. The fix, aeoess/federation-port#1, was reproduced and reviewed by
its maintainer and merged on 2026-10-08 as `3a2f6ce`. After review it also made
the deadline an authorization expiry. The four probes now assert the corrected
behaviour at the new pin. Read-only reconciliation of an operation still
`unknown` after the deadline is open upstream as aeoess/federation-port#2.

The map also records how the SDD testplan FED-01 to FED-10 overlapped the
existing suite. Of its 40 planned cases most were already covered: FED-01,
FED-04 and FED-05 entirely, FED-03 and FED-06 except for the forms the probes
add. FED-09 (adapter isolation) is not turned into tests, because section 10
of the contract already states what an in-process adapter can do. The new
REMORA-side tests are FED-02 (a retry with re-signed evidence), FED-08 (the
stored deadline and evidence digest) and FED-10 below.

## Lifecycle: an execution report is not an effect

`remora/federation/lifecycle.py` reads a transport outcome as an execution
report. `provider_confirmed` becomes `EXECUTION_REPORTED_SUCCESS` with the
effect `NOT_ESTABLISHED`. Only REMORA's effect verifier
(`remora.governance.effect_verification`), observing a system of record, can
establish `EFFECT_VERIFIED`; that stays a separate edge any transport can
compose with. The reading holds in both directions: a transport `failed`
with an observed refund is `EFFECT_VERIFIED`, which is the case CP-F1
produces, and a `provider_confirmed` the reader cannot see yet stays
`NOT_ESTABLISHED` (`test_the_effect_is_read_apart_from_the_transport_state`).

## Acceptance criteria

| | Criterion | Where |
|---|---|---|
| AC-01 | adapter runs against unmodified federation-port/v0 | adapter tests (revision and clean `src/` asserted) |
| AC-02 | valid supported actions are admitted | fixture `valid`, `provider_confirmed` |
| AC-03 | mutated tool, arguments, target, tenant, approval, operation or evidence refused | adapter tests, eight mutations |
| AC-04 | never full `exact_call_binding-v1.1` | manifest claims are a subset of the map's exports |
| AC-05 | `1` versus `1.0` is a stated loss, not a false pass | fixture `lossy_float`; Python projection tests |
| AC-06 | principal binding NOT_ESTABLISHED under V0 | fixture `other_principal`; projection records |
| AC-07 | expiry at admission is not full fresh authority | `remora.authorization_unexpired`; revocation not established |
| AC-08 | `provider_confirmed` never becomes `EFFECT_VERIFIED` | `tests/test_federation_bridge.py` |
| AC-09 | every result has projection records with digests | fixtures; adapter test AC-09 |
| AC-10 | the transport is replaceable without changing native primitives | `remora/federation/transports/`; nothing in `remora/enforcement` or `remora/execution` imports the bridge |
| AC-11 | a stronger transport preserves without changing the native claim | a capability declaration alone moves exact-call to PRESERVED |
| AC-12 | native, projected, runtime and effect layers stay distinct | projection records, lifecycle reading |
| AC-RS-01 to 14 | report-specific binding (above) | `tests/test_federation_report_selection.py` |
| AC-RS-V0 | each LATE and LATE-CONFLICT report evaluated separately in an unmodified V0 runtime | `integrations/federation-port/remora-report-result/tests` |
| AC-RS-V0-HO | held-out: conflicting results for one report refused in both orders; every set-aside reason recorded; signature sweep; order and subset independence; canonical output | the `held-out` tests in the same file; written by the producer after #793 |
| AC-HO | held-out for the authorization component: every refusal before and after the signature, a correctly sized wrong signature, envelope and signature sweep, evidence addressed elsewhere, empty tenant, malformed instants, inclusive deadline, null and nested arguments | the `held-out` tests in `remora-adapter/tests`; written after the first mutation run |
| AC-CP | every rule in `contract-coverage.json` names an existing test, every probe is mapped, and the probes pass against the unmodified runtime | `integrations/federation-port/contract-probes`, run by `reproduce.sh` and CI; `tests/test_federation_port_contract_coverage.py` |
| AC-MUT | no single-edit fault in either `adapter.ts` survives its tests without a listed reason; an inert edit survives and a status flip is killed (controls) | `integrations/federation-port/mutation_check.py`, run by `reproduce.sh` and CI; `tests/test_federation_port_mutation_check.py` |

## What this does not establish

- Anything about a deployment: the fixtures use published test keys.
- Independence: REMORA wrote the adapter, the fixtures and the tests. The
  interoperability question on #177 is answered only by a run someone else
  reproduces.
- Isolation: federation-port/v0 runs adapters in its own process (its
  section 10), so custody isolation over V0 stays NOT_ESTABLISHED.
- Revocation, trusted time, ToolSpec freshness or signing-key status over V0.
