# Implementation note — evidence admission layer (EA, CoSAI §7.4)

**Date:** 2026-10-02 · **Status:** implemented library surface; not runtime-wired

This note summarizes the evidence-admission implementation and its authority
boundary. The canonical design is `docs/design/evidence-admission-v1.md`.

## Existing primitives to reuse

| Need | Existing primitive | File |
|---|---|---|
| Property verdict vocabulary | `EvidenceStatus` (ESTABLISHED / VIOLATED / NOT_ESTABLISHED) with `missing_evidence` + `decisive_if` | [conformance/evidence-sufficiency-v1/checker.py](conformance/evidence-sufficiency-v1/checker.py) |
| Processing/property separation | `ProcessingStatus` (COMPLETED / REJECTED_EVIDENCE / ACQUISITION_FAILED / VERIFIER_FAILED) + `PropertyVerdict` | [experiments/bounded_readback.py](experiments/bounded_readback.py) |
| Bounded JSON canonicalisation (no floats, no `default=str`, duplicate-key rejection, size/nesting bounds) | `_json_value`, `_canonical`, `_unique_object`, `_decode` | [experiments/bounded_readback.py](experiments/bounded_readback.py) |
| Deployment-owned scope/contract types | `SourcePolicy`, `ReadbackContract` (tenant/target/operation/attempt/request_id binding) | [experiments/bounded_readback.py](experiments/bounded_readback.py) |
| Postcondition comparison + reason codes | `PostconditionContract`, `verify_declared_delta`, `EffectVerification`, `EffectStatus` | [remora/governance/effect_verification.py](remora/governance/effect_verification.py) |
| Lineage vocabulary | `proposal_id`, `execution_id`, `dispatch_id`, `tool_call_hash`, `toolspec_hash` | [remora/governance/effect_receipt.py](remora/governance/effect_receipt.py), [remora/governance/effect_verification.py](remora/governance/effect_verification.py) |
| Plan-state binding + digest | `PlanBinding.digest()` | [remora/governance/plan_binding.py](remora/governance/plan_binding.py) |
| Reason-code discipline | frozen published reason-code sets pinned by tests | [schemas/postcondition_contract_v1.yaml](schemas/postcondition_contract_v1.yaml), [schemas/tool_spec_v1.yaml](schemas/tool_spec_v1.yaml) |
| Federation claim ceiling | `external-evidence-ref-v1`, "foreign evidence creates no authority" | [docs/interop/FEDERATION.md](docs/interop/FEDERATION.md) |
| Diversity vs independence separation | `INDEPENDENT` only for second implementations, run by external operators | [docs/interop/FEDERATION.md](docs/interop/FEDERATION.md) |

## New primitives genuinely required

None of the above answer *why* a premise is true. The five new types each cover
one hole:

| New type | Hole it covers |
|---|---|
| `ProducerCapabilityManifest` | no existing record of what a producer could see, over which scope, when |
| `CoverageAttestation` | the frozen checker takes `admission_coverage_complete` as a boolean premise; nothing represents the denominator (fields, interval, known gaps) |
| `ObservationVantage` | nothing distinguishes observer identity/control domain from independence; Federation separates diversity from independence but has no vantage record |
| `InvocationBindingProof` | nothing binds evidence to an action beyond identifier equality (CoSAI C5) |
| `PriorCommitment` | nothing records that an expected postcondition existed *before* execution; `PostconditionContract` is timeless configuration |

The admission result is `EvidenceAdmission`; public operations are
`process_evidence_payload()`, `admit_evidence()`, and `processing_failure()`.

## Placement

New subpackage `remora/evidence/admission/` (inside the existing `remora/evidence/`
package, not a new top-level package). Rationale: the task names
`remora/evidence/` as the preferred location. The existing package is the
research/evidence surface, and the admission layer must not
leak into `remora/enforcement` or `remora/execution` (authority boundary).

```
remora/evidence/admission/
   __init__.py        # public surface: evidence types and admission operations
    models.py          # frozen dataclasses + enums
    canonical.py       # bounded JSON helpers, lifted from bounded_readback
    admission.py       # admit_evidence()
```

`experiments/bounded_readback.py` keeps its own copies for now (it is an
opt-in experiment); `canonical.py` duplicates that small, tested surface into a
production module rather than importing the experiment. If the two drift, the
experiment's disclaimers are not inherited by production code. This separation
is deliberate.

## Authority boundary

The admission layer:

- never imports `remora.enforcement`, `remora.execution`, `remora.policy`;
- never returns anything the policy engine reads (no `PolicyObservation` fields);
- returns only an `EvidenceAdmission` report, not a verdict input;
- is guarded by an AST test (`tests/test_evidence_admission_isolation.py`)
  asserting none of those imports exist, same pattern as
  `tests/test_cascade_not_authorization.py`.

## Compatibility risks

1. **`remora/evidence/__init__.py` re-exports.** Adding five names to the public
   `__all__` changes the package surface. The SDK snapshot gate does not cover
   `remora.evidence` (it covers `remora.sdk`), so this is safe; still, the new
   names go in a submodule import (`from remora.evidence.admission import ...`)
   and are re-exported lazily, not eagerly. This avoids import cost on the hot
   path.
2. **Frozen checkers.** v1, v1.3, v1.4, v1.5 checkers are untouched. The new
   layer produces inputs those checkers *could* consume, but no adapter is wired
   in this task; the synthetic-fixture boundary (`premise_source`) stays.
3. **Claim governance.** The capability register records `IMPLEMENTED_LIBRARY`.
   No runtime adapter feeds admission results into a property checker.
4. **Reason-code vocabulary.** New codes are additive and live in
   `remora/evidence/admission/reasons.py` as a frozen tuple, pinned by a test.
   This follows the frozen schema reason-code pattern, but is not yet a published wire
   contract (that is a later versioning decision).

## Implemented files and governance

- new: `remora/evidence/admission/{__init__,models,canonical,admission,reasons}.py`
- new: `tests/test_evidence_admission_models.py` (type-level invariants)
- new: `tests/test_evidence_admission_adversarial.py` (the section-6 matrix)
- new: `tests/test_evidence_admission_isolation.py` (AST authority guard)
- new: `docs/design/evidence-admission-v1.md` + register entry
- edit: `remora/evidence/__init__.py` (lazy re-export)
- edit: `docs/assurance/capability_register_v1.yaml` (CAP-025 and claim ceiling)
- edit: `docs/README.md` (index link for the design doc)

Nothing in `conformance/`, `remora/enforcement/`, `remora/execution/`,
`remora/policy/`, `servers/`, or `workers/`.
