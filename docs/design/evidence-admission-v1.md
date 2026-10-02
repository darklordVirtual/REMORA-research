# Evidence admission v1 — CoSAI §7.4 premises as typed evidence

- Status: proposal (2026-10-02)
- Code: `remora/evidence/admission/`
- Tests: `tests/test_evidence_admission_models.py`,
  `tests/test_evidence_admission_adversarial.py`,
  `tests/test_evidence_admission_isolation.py`
- Related: `conformance/evidence-sufficiency-v1/` (frozen; untouched),
  `experiments/bounded_readback.py`, `docs/interop/FEDERATION.md`,
  CoSAI WS4 containment §7.4 (evidence sufficiency for absence claims)

## What this is

A narrow admission layer between raw external observations and REMORA's
property-verdict logic. The frozen conformance checkers answer "given accepted
premises, what does the observation set establish?" and deliberately take those
premises (`scope_accepted`, `source_accepted`, `admission_coverage_complete`,
...) as trusted synthetic-fixture inputs. This layer answers the question those
checkers must not: *why* a premise holds, derived from typed evidence and
deployment-owned trust material — or records that it does not.

```
raw evidence → typed records → admit_evidence (this layer)
             → EvidenceAdmission report → downstream verdict logic
```

The report is a report. Nothing in this package can authorize a tool call,
upgrade a gate decision, mint a lease, bypass review, modify a ToolSpec or
policy, or cause or retry execution. The package imports none of
`remora.enforcement`, `remora.execution`, `remora.policy` — pinned by
`tests/test_evidence_admission_isolation.py` (AST guard, same pattern as the
cascade boundary test). A runtime test additionally proves that a fully
admitted record presented alongside a policy observation changes nothing the
engine decides.

## The five concepts

| Type | Question it answers | Key rule |
|---|---|---|
| `ProducerCapabilityManifest` | What could this producer see, over which scope, when? | A manifest is a claim until the deployment's accepted-producer map carries its digest. `DECLARED` is not evidence. |
| `CoverageAttestation` | What is the denominator — which fields, which interval, which named gaps? | `INCOMPLETE` and `UNKNOWN` never support absence. `COMPLETE` cannot carry known gaps (constructor refuses). |
| `ObservationVantage` | Who observed, relative to the observed system? | Independence is derived from control domains and forge/suppress facts. A self-declared `independent=true` is never read. |
| `InvocationBindingProof` | Is this evidence about *this* action? | Every declared axis must match; identifier equality on one axis is not binding (C5). |
| `PriorCommitment` | Did the expected effect exist as a commitment before execution? | `created_at` must predate the execution start; the commitment must bind to the exact proposal/call/target/operation. |

`admit_evidence()` joins the five against a `TrustConfig` (deployment-owned:
accepted producer digests, trusted vantage domains) and returns an
`EvidenceAdmission` with per-fact `EstablishmentStatus` and machine-readable
reason codes. No caller-supplied boolean with a premise name is read; the
facts are derived or absent.

## CoSAI §7.4 mapping

| Clause | Implementation |
|---|---|
| **C1** — NOT_ESTABLISHED is a conclusion after verification ran; missing obligations are named | `EvidenceAdmission.established_facts` is a full per-fact map (every fact is always present, at worst NOT_ESTABLISHED), and every failure carries a reason code from the frozen tuple in `reasons.py`. |
| **C2** — Malformed input / verifier failure is a processing failure, not NOT_ESTABLISHED | Two axes: `ProcessingStatus` (COMPLETED / REJECTED_EVIDENCE / UNSUPPORTED / ACQUISITION_FAILED / VERIFIER_FAILED) vs. per-fact `EstablishmentStatus`. `canonical.decode_bounded` raises before admission runs; `admit_evidence` takes typed records only, so a parse failure can never reach the property axis. |
| **C3** — Observation is asymmetric; self-report is not independent observation | `ObservationVantage.independence` derives from control domains and forge/suppress facts; `observer_id == observed_party` is NOT_INDEPENDENT regardless of any declared flag. Refutation needs an accepted observation, not a self-report. |
| **C4** — Absence needs producer visibility AND coverage for the same scope | `observation_coverage_complete` is ESTABLISHED only when the manifest is accepted *and* covers every evaluated field *and* the attestation covers the fields and interval with no gaps. An empty-but-present field follows the same rule as a missing field, because the layer never reads field *values* — only the coverage and visibility of the field set. |
| **C5** — Identifier equality alone is not binding | `InvocationBindingProof.matches()` requires every declared axis (proposal, execution, tool-call hash, dispatch, toolspec, tenant, target, operation, attempt) to agree; a proof naming a different tenant fails even when every identifier matches. |
| **C6** — Expected verdicts stay outside admission inputs | `admit_evidence` takes no expected-outcome parameter; `expected_invocation` is lineage (IDs, hashes, scope), and the adversarial suite proves that adding lookalike premise keys to it changes nothing. |

## Claim ceiling

Phase 1 does not establish, and this layer must not be read as establishing:

- global runtime capability completeness (an attestation covers one
  invocation's declared denominator, never "the runtime");
- global non-bypassability;
- truthfulness of a source because it is authenticated;
- independence because an observer claims it;
- absence outside the explicitly established coverage denominator;
- causation from temporal correlation;
- authorization from evidence;
- production certification.

Every decisive result is bounded to a property, an invocation/attempt, a
resource and field set, an observation interval, and the accepted evidence
sources named in the deployment's `TrustConfig`.

## Where REMORA is deliberately stricter than §7.4

- The layer refuses to read field *values* at all. §7.4 discusses absence of a
  field; REMORA's admission layer treats present-but-empty and absent as the
  same coverage question and leaves value comparison to `verify_declared_delta`
  downstream, unchanged.
- `PriorCommitment` requires `created_at <= execution_started_at` *and*
  binding to the exact action. A commitment that merely predates the evaluation
  (but not the execution) is refused.

## What is deliberately not wired

- No adapter feeds `EvidenceAdmission` into the frozen conformance checkers;
  their `premise_source="synthetic_fixture"` boundary stands.
- No wiring into `remora/governance/effect_verification.py`; how an admitted
  independent read-back could eventually support `EffectVerification` is a
  later task with its own threat model.
- No Federation schema change; `external-evidence-ref-v1` already carries
  foreign evidence opaquely, and admission of it is a deployment-owned step.
