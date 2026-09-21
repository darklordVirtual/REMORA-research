# APS action-result-binding — REMORA review

Date: 2026-09-21. Scope: the new family only.

**TS: 9/9 MATCH. Python: 10/10 MATCH. REMORA: 19 targeted tests pass.**
Substituting deny evidence for permit evidence, with all receipts and vectors
unchanged, makes both upstream runners reject all six cases and exit 1.
These results establish bounded observations, not APS conformance or an
external effect.

## Provenance and scope

- APS: `b64cc8dfa889b493bbf285fbb115a988ac54566b`.
- APS baseline: `e604e7550ef95eed4b612aeccd28a6924f4450f5`.
- REMORA base: `824098bcf75efa07ac1f65aed44b98251f4973df`.
- TypeScript SDK: `agent-passport-system` 7.0.0, installed with `npm ci`.
- Python SDK: `agent-passport-system` 4.0.0, dedicated virtual environment.
- Runtime: Node v24.19.0; Python 3.12.14; pytest 9.1.1.
- [Pinned source](https://github.com/Agent-Authority-Conformance/aps-conformance-suite/tree/b64cc8dfa889b493bbf285fbb115a988ac54566b/fixtures/action-result-binding).
- [Baseline comparison](https://github.com/Agent-Authority-Conformance/aps-conformance-suite/compare/e604e7550ef95eed4b612aeccd28a6924f4450f5...b64cc8dfa889b493bbf285fbb115a988ac54566b).

The comparison confirms three commits and seven changed files: six added
family files and minimal package.json wiring. No old schema or fixture family
changed. `upstream-diff.json` preserves the comparison metadata.

The six cases include one positive control and five mutations. TS counts the
six cases plus three chain receipts (intent, permit, deny). Python additionally
checks the absence of a composite verifier using the upstream callable-name
probe. That probe's documented naming limitation remains applicable.

## Observed surfaces

All SDK cells below were checked by the unchanged pinned runners. Draft and
Replay columns retain upstream interpretations; they are not execution results.

| Case | Draft-03 interpretation | TS stage | TS composite | Python stage | Replay, derived only |
|---|---|---|---|---|---|
| ARB-01 positive | satisfies | valid | valid | valid | fully bound |
| ARB-02 subject absent | invalid | invalid: SCHEMA_INVALID | invalid: receipt_invalid | invalid: SCHEMA_INVALID | unresolved_until_run |
| ARB-03 wrong prev | stated_relation_not_met | valid | valid | valid | partially bound |
| ARB-04 wrong decision_ref | invalid | valid | invalid: decision_ref_mismatch | valid | partially bound |
| ARB-05 wrong action_ref | invalid | valid | invalid: decision_ref_mismatch | valid | unbound |
| ARB-06 changed subject | semantic_conflict_no_explicit_rule | valid | valid | valid | unresolved_until_run |

Python has **no composite verifier** in the pinned release. Its digest-builder
check is harness evidence, explicitly not a Python composite verdict.
SDK MATCH means agreement with recorded SDK behavior; it never becomes a
conformance PASS in this report. `review.json` preserves the four source blocks
and keeps runner agreement, REMORA digest observations and harness comparisons
under separate keys.

## Exact evidence and action binding

REMORA's existing `receipt_decision_ref` independently reproduces all six
pinned digests from each record's own `action_ref` and the supplied evidence.
It uses REMORA's JCS implementation and domain-separated hashes, without either
APS SDK.

| Input | Recomputed decision_ref |
|---|---|
| primary action + permit evidence | 12d285993f53a94783def52d3dd6ebc730781b7e04245d655ab7cd4acd958771 |
| primary action + deny evidence | 2fc67caf85daa5123a83f8e6b603c8c4f4374cac2159556f04dc27387d9012cf |
| case 5 action + permit evidence | 911ece7f7ed1dea3b8f1c8f9932c4caecb479f6612ec3ab87c64754ad6f6e703 |
| case 5 action + deny evidence | 9e4a781c62a60f269e484bfbd88b8914beb78d6b606078d7c2ff8ab5bff8acbf |

For the positive result, changing only decision evidence changes REMORA's
legacy relation result from `PASS` to `DECISION_REF_MISMATCH`. The record,
signature, action_ref, decision_ref and prev remain unchanged.

In case 5, both evidence inputs produce `DECISION_REF_MISMATCH`, but the
computed digest differs. The new tests require the exact permit digest and
reject a substituted evidence digest; equality of rejection codes cannot
establish which evidence was checked.

The upstream mutation experiment replaces only
`chain.decision_evidence.permit` with a deep copy of `deny`. Original receipts,
vectors, expected digests and runner source stay unchanged. Each runner exits
1 with six case failures. Case 5 fails specifically on its evidence digest pin
even though its SDK composite result is unchanged.

An additional observation in that experiment: case 4's TS composite changes
from invalid to valid when supplied the matching deny evidence. The harness
still rejects it because the expected permit evidence pin differs. A composite
binding result alone is therefore not evidence that a permit was consumed.
This is an observed surface limitation, not a new normative conformance claim.

## prev, actor and evidence isolation

The committed consumed decision receipt is
`fb46f47305d9d3c5bf296ed87081af534077f2f5e380211f3875f2e20966fc49`.
ARB-03 instead names the intent receipt. The TS harness detects that mismatch;
neither reference SDK resolves prev. Python validate.py does not implement the
prev comparison. Its MATCH must not be interpreted as establishing that relation.

Keep ARB-03 classified as `draft03_stated_relation_not_enforced`, not a normative
conformance failure. ARB-06 remains
`draft03_semantic_relation_not_explicitly_enforced`: the actor names disagree,
but no explicit equality verifier rule is asserted by the pinned draft mapping.

Permit and deny have identical authority_state and policy_input. They differ
in decision_context.evaluated_at and decision_output; the latter binds verdict,
effective authority and validity. No revoked delegation or authority lifecycle
was invented. The deny receipt is not used as approval. Both SDK runners also
recompute and check the deny receipt's signature and stage.

## Manual REMORA mapping review

The historical standalone `remora_aps_mode_b.py` has no action-result mapping.
The current repository uses `remora/interop/aps/adapter.py`, `adapter_v0_2.py`
and `mappings.py`. Invoking either aggregate profile would rerun families
outside the requested scope, so this review calls only the relevant primitives.

`receipt_decision_ref` is suitable for the bounded digest projection.
`classify_receipt_decision_relation` checks digest binding and then its frozen
temporal rule. It is **not** an action-result schema/stage/composite verifier:
with original permit evidence it returns its narrow `PASS` for cases 2, 3 and
6 as well as the positive control. Those cases demonstrate why this result
must never populate a general action-result PASS/FAIL field.

Its temporal check also differs from the action-result composite surface. When
case 4 is supplied matching deny evidence, it refuses the null valid_until
with MappingRefused, while the TS composite reports a valid binding. The
legacy helper is therefore not registered as an equivalent implementation of
the new family's composite verifier.

No production mapping or legacy runner was changed. The added test file calls
the shipped REMORA implementation using vendored, SHA-256-pinned upstream
inputs. It requires no network, sibling clone or APS SDK. The fail-closed
claim here is limited to the REMORA interoperability relation; it is not a
demonstration of an integrated production execution gate.

## Regression evidence

`tests/test_aps_action_result_binding.py` contains 19 tests:

- Six exact-evidence/action-ref digest checks.
- Six evidence-substitution checks with the record unchanged.
- One positive-control fail-closed relation test.
- One case-5 test retaining evidence provenance despite identical rejection.
- One permit/deny digest test with shared authority/policy input.
- Four missing-evidence-component refusal tests.

To prove the fail-closed test detects a real regression, the classifier's
digest-mismatch branch was temporarily changed to return PASS. The actual
test failed with `PASS != DECISION_REF_MISMATCH`. The original source bytes
were restored; the full targeted file then passed 19/19. No production diff
remains. Ruff also passes for the added test file.

A separate read-only reviewer reran the 19 targeted tests, checked fixture
hashes, source hashes, logs, and claim boundaries, and found no critical or
important issues. Its packaging finding was resolved by explicitly including
all seven run logs despite the repository's generic log ignore rule. The
logs preserve raw output, including pytest's whitespace-only error line.

## Reproduction

From an APS checkout at the exact pin:

```bash
npm ci --include=dev --ignore-scripts --no-audit --no-fund
node --import tsx fixtures/action-result-binding/verify.ts
/path/to/aps-py-4/bin/python fixtures/action-result-binding/validate.py
```

The normal `npm run verify:action-result-binding` launcher was attempted first.
Its tsx CLI failed before executing the runner because this environment denies
its IPC socket (`listen EPERM`). The Node import loader executed the same
unmodified verify.ts with the same pinned SDK successfully.

From the REMORA checkout with pytest installed:

```bash
python -m pytest -q tests/test_aps_action_result_binding.py
```

Logs: `typescript.log`, `python.log`, both `*-evidence-substitution.log` files,
`remora-mutation-red.log`, and `remora-regression.log`. `review.json` carries
source SHA-256 values and separate machine-readable observations.

## Limits

No claim is established about external effect occurrence or settlement,
single-use consumption, dispatch freshness, a resolved real delegation chain,
or Agent Replay runtime behavior. A recorded effect_ref does not establish an
external effect.

**Not rerun:** 25/25, schema 9/9, P1 7/7, oracle 13/13, C19, or the complete
REMORA/APS suites. The targeted runs above are the entire verification claim.

Delivery is on branch `review/aps-action-result-binding-b64cc8df`. No PR is
opened: this repository starts the aggregate APS and broader CI workflows on
PR creation, which would exceed the requested test scope. Workflow definitions
and required checks are unchanged; this branch is not merged.
