# Federation interoperability in REMORA

REMORA participates as a producer/runtime node, not as a Federation coordinator.

The stable entry point is `artifacts/interop/index.json`. The participation
manifest is `artifacts/interop/FEDERATION.yaml`; the generated status table
is [INTEROP_MATRIX.md](INTEROP_MATRIX.md). The bounded boundary declaration
summary is generated at
[remora-boundary-summary-v1.json](../../artifacts/interop/remora-boundary-summary-v1.json).

The boundary summary keeps internal trust boundaries, external interfaces,
Federation edges, role mappings and claim ceilings distinct. Its statuses do
not imply production evidence, owner confirmation, independent observation or
Federation adoption. E7 remains externally unrun, and
`runtime_capability_surface_completeness` remains `NOT_ESTABLISHED`.

## Names

Three names appear in this surface, and a fourth is deliberately absent. The
table is the only place REMORA explains them; other documents link here.

| Name | What it is | Where |
|---|---|---|
| REMORA | the implementation under test: the runtime, its primitives and this evidence surface | this repository |
| Agent Authority Conformance Profiles (AACP) | portable, implementation-neutral profiles and falsification fixtures; a profile is cited with its repository and its revision | `darklordVirtual/agent-authority-conformance` at `4d2eee1`; the repository has not yet been renamed to match the project |
| Bounded Claim Reproduction (BCR) | the profiles project's documented evidence method, still under development: the chain from claim to ceiling and levels BCR-0 to BCR-4 | `METHOD.md` in the same repository and revision |
| Agent Authority Conformance (LF Decentralized Trust lab) | a separate external venue; neither REMORA nor the profiles project is part of it, and no participation or acceptance is recorded | not referenced by any REMORA record |

Two short forms collide with established names in neighbouring fields. "AACP"
is also used for the Agent Action Compression Protocol, an individual
Internet-Draft, and for the Agent Autonomous Commerce Protocol. "BCR" is
Binding Corporate Rules in data-protection law. REMORA therefore writes the
full names at first mention in every document and in every record field, and
never cites a profile or a level by the short form alone.

REMORA's own `docs/benchmarks/agent-authority-conformance-v0.1.md` is the A to
G property model as it was published, under the name the profiles project
used until 2026-10. It is byte-pinned by the profiles repository's v0.1 test,
so it keeps its title and text. Later records call the model "the A to G
property model" and the project "Agent Authority Conformance Profiles". The
AEGIS crosswalk and the APS authority profile were written under the earlier
name and keep it, with the resolution above.

Implementation neutrality is a governance rule of the profiles project, not
organisational independence: both repositories have the same maintainer.
Independence is therefore documented per evaluator and per run, in the run
record's independence level and in the external run record's operator and
import fields. It is never inferred from a project name, from the maintainer
split, or from a lab affiliation.

## Participation manifest

`artifacts/interop/FEDERATION.yaml` is the machine-readable statement of what
REMORA produces, consumes and bounds. Produced: decision envelope, policy
decision, execution authorization, execution evidence, effect verification.
Consumed: identity attestation, delegation evidence, tool manifest, external
authority evidence. The claim ceiling is stated in the same file: not
production certified, external validation partial. It validates against
`federation-manifest-v1.schema.json` and is checked by
`scripts/interop_package.py --check`.

Counterpart projects appear in the manifest only as data on an edge. A test
refuses a project name used as a condition in policy, enforcement, execution,
governance, toolcall or server code: REMORA understands foreign artifacts
through adapters and profiles, never by knowing who sent them.

## Invariants

The manifest names five invariants and, for each, the test or gate that
enforces it.

| Id | Statement |
|---|---|
| FED-INV-001 | Federation membership MUST NOT confer execution authority. |
| FED-INV-002 | External project claims MUST be evaluated only within their declared claim ceiling. |
| FED-INV-003 | Interop artifacts MUST bind producer revision, artifact digest and schema version. |
| FED-INV-004 | A cross-project PASS MUST NOT imply endorsement, production safety or broader project validity. |
| FED-INV-005 | External evidence MUST NOT transitively acquire authority merely because REMORA consumed it. |

Membership, trust and authority stay three different things. A Federation
registry can say where an artifact came from. Only cryptographic verification
under keys the deployment holds, followed by local REMORA policy, can say what
it is allowed to do, and the answer is never derived from the registry.

## Bounded results

A cross-project result is never a bare PASS. `interop-result-v1`
(`artifacts/interop/schemas/interop-result-v1.schema.json`) requires more
than a status. It names the claim and the subject, the producer and consumer
revisions, and the fixture digest and package digest the result was computed
over. It names the evaluator and its revision, the operator, the host, the
environment and the timestamps. It carries one record per case, what the
result establishes and what it does not. Four ceiling booleans (`implies_endorsement`,
`implies_production_safety`, `implies_broader_validity`,
`confers_authority`) are schema constants fixed at false, so a record that
claims otherwise does not validate. The optional `runner_contract` block
holds nine separate booleans for the runner properties E030 found collapsed
into one flag; a single `runner_safe` is rejected.

### Independence levels

Every result states one of five levels, and the schema refuses a level whose
conditions the record does not meet.

| Level | Means |
|---|---|
| `L0_SELF_TEST` | the producer's own evaluator, run by the producer |
| `L1_REPRODUCTION` | the producer's reference evaluator, run by an external operator |
| `L2_SECOND_IMPLEMENTATION` | a separately written evaluator that still fails one independence condition |
| `L3_INDEPENDENT_RECOMPUTATION` | a second implementation, maintained and run outside the producer, importing no producer code |
| `L4_INDEPENDENT_HOST_RUN` | L3, executed on a host the producer does not control, with the environment recorded |

`L3` and `L4` are what `external-run-record-v1` calls `INDEPENDENT`; the two
schemas describe the same boundary from two sides. A second implementation
is implementation diversity. It becomes independence only when every
condition holds, and the schema, not the author, decides.

### Correspondence to Bounded Claim Reproduction levels

The five levels were written to correspond to BCR-0 to BCR-4 in the profiles
project's `METHOD.md`. The correspondence is intended, not one to one: the
method requires conditions the REMORA schema does not check.

| REMORA level | Intended BCR level | Conditions the method adds |
|---|---|---|
| `L0_SELF_TEST` | BCR-0 | none |
| `L1_REPRODUCTION` | BCR-1 | none |
| `L2_SECOND_IMPLEMENTATION` | BCR-2 | none |
| `L3_INDEPENDENT_RECOMPUTATION` | BCR-3 | the negative and mutation cases of the pinned public specification were run; no producer maintainer took part in the run |
| `L4_INDEPENDENT_HOST_RUN` | BCR-4 | BCR-3, and the external party controlled the environment, the runner, the execution and the evidence capture, and published the retained evidence |

A run record therefore carries a REMORA level and nothing else. It receives
a BCR level only through a linkage record that lists each added condition
with the evidence that it held, and the level given can never exceed the
REMORA level of the record. The level describes who ran what. It says nothing
about the safety of the implementation, and a contract's lifecycle state is
not a level.

### Linkage records

`bcr-linkage-v1` (`artifacts/interop/schemas/bcr-linkage-v1.schema.json`) is
the versioned join between one committed run record and one profile revision.
It names the profile with its repository, identifier and revision, the method
with its document and revision, and the source record by path, digest and
claim. It copies the record's independence level and status verbatim: the
gate in `scripts/interop_package.py --check` resolves the source record and
refuses a linkage whose level, status, claim or package digest differs. A
profile-side result, if a reviewer assigns one, is a separate field with the
reviewer's name, date and rationale. Nothing computes it from the REMORA
status, and the six-valued profile vocabulary is never written into a REMORA
record. Linkage records live under `artifacts/interop/linkages/`. None exists
yet: the author runs are `L0_SELF_TEST`, and no profile revision has been
published for them.

## Execution-boundary fixtures

Six packages under `artifacts/interop/` follow the producer contract above.
Each has pinned fixtures, a reference verifier that imports no REMORA code, a
claim packet, a verifier request and a manifest. Five export a REMORA
boundary; one consumes a foreign artifact.

| Package | Claim | What REMORA runs |
|---|---|---|
| `exact-call-binding-v1` | `exact_call_binding`, `single_use_authorization` | `ExecutionLease` and `GovernedToolDispatcher` |
| `fresh-authority-v1` | `fresh_authority_at_dispatch` | `PolicyDecisionToken` with `EnforcementGate`, and the lease with the dispatcher |
| `effect-evidence-v1` | `effect_state_distinction` | `verify_declared_delta` over the fixture's state ladder |
| `exact-call-binding-v1.1` | as v1 | as v1; adds scalar-type cases and names the temporal boundary |
| `effect-evidence-v1.1` | as v1 | as v1; a rejected rule map is `CONTRACT_REJECTED` and versions compare as integers only |
| `agentavow-tool-manifest-e8-v0.1` | `attested_definition_binding` | `remora.interop.agentavow` against `toolspec_hash` inside a signed lease |

`remora/interop/boundary_fixtures.py` runs the first three through the real
primitives; `scripts/interop_author_run.py` writes the result of that run,
and of the reference verifier, as `L0_SELF_TEST` records under
`artifacts/interop/runs/`. The two evaluators are kept as two records per
claim so their agreement is visible rather than asserted. The author records
advance nothing. The three boundary packages were frozen at master
revision `fe324dd7`. Probity confirmed those pins and ran them with a second
implementation, so their lifecycle is now `REPRODUCED`, with each external
record classed `NOT_INDEPENDENT` (`artifacts/interop/index.json`). The E8
package stays `DRAFT` until AgentAvow confirms the profile.

The v1.1 packages are `DRAFT` successors on their own edges (`E-ECB-V1-1`,
`E-EE-V1-1`). The pre-Federation probes of 2026-10-06 found two gaps. A
verifier could pass `effect-evidence-v1` while reading a missing field as
`null` and treating an unknown comparison rule as `exact`. A verifier could
pass `exact-call-binding-v1` without telling `1` from `1.0`, and that package
never named the verify-then-mutate boundary a static corpus cannot test. The
v1 packages keep their bytes, their freeze and the external runs against
them, and the index marks them `superseded_by` with that note. The new cases
were written with the faults known and are labelled as repair.

The fixtures are the invitation. A project that wants to attack a claim
implements the contract without REMORA code, adds its own mutation, replay,
malformed, stale and wrong-subject cases, and publishes an
`interop-result-v1` record. A `CONTRADICTED` record is a result REMORA wants.
It is recorded and it wins in the matrix over every other record on the
edge. The fixture is then corrected in a new version and the old record is
kept.

### The foreign edge

`agentavow-tool-manifest-e8-v0.1` is the first edge REMORA consumes. The
adapter verifies a signed tool manifest under a key the deployment supplies
and normalizes it into an observed tool definition with an `UNADMITTED`
evidence reference. It then compares the definition's digest with the
`toolspec_hash` signed into an authentic `ExecutionLease`. It establishes
that the attested definition is the one the authorization was granted under.
It does not establish that the signer is trustworthy, that the definition is
safe, that the runtime exposed it (E7), or that the call ran. The wire format
is REMORA's profile v0 assumption and is marked `experimental` in the
manifest until AgentAvow confirms or corrects it.

## Interop matrix

[INTEROP_MATRIX.md](INTEROP_MATRIX.md) is generated by
`scripts/build_interop_matrix.py` from the manifest's edges, the index's
lifecycle states and the run records. Status is derived: a declared stage
when no record exists, `AUTHOR_RUN` for L0, `REPRODUCED` for L1,
`SECOND_IMPLEMENTATION` for L2, `INDEPENDENTLY_ESTABLISHED` for L3 or L4, and
`CONTRADICTED` as soon as one record says so. CI refuses a committed matrix
that differs from the records, so proposed, specified, self-tested and
independently reproduced cannot be confused by editing a table.

## Maturity of a claim

The progression a boundary claim can make, and where the three exported
claims stand on 2026-10-04:

```text
DESIGNED -> IMPLEMENTED -> SELF_TESTED -> MUTATION_TESTED
   -> SECOND_IMPLEMENTATION -> INDEPENDENTLY_REPRODUCED -> HOST_OPERATED -> FIELD_OBSERVED
```

`exact_call_binding` and `single_use_authorization` are at `MUTATION_TESTED`:
the grant and lease consumption paths are inside the mutation baseline in
`docs/assurance/mutation_testing_v1.md`, and the L0 records exist.
`fresh_authority_at_dispatch` shares that baseline for expiry and single use;
revocation and the policy-bundle and tool-definition staleness checks are at
`SELF_TESTED`. `effect_state_distinction` is at `SELF_TESTED`. Nothing is
beyond `MUTATION_TESTED`, which is the point of publishing the fixtures. The
next step for each is one second implementation and one externally operated
reproduction, with a neutral evaluator recording the level; the claim
register is upgraded only when such records exist, never before.

## Producer contract

### Self-service and publication

Public artifacts have a standing offer for research evaluation under the
existing [license](../../LICENSE) and [licensing explanation](../../legal/LICENSING.md).
An operator need not ask permission for each run or for publishing their own
attributed favorable or negative result. Public visibility does not grant
production, commercial or relicensing rights beyond those terms. Federation
participation and open reuse proposals do not change REMORA's license.

The stable index links the
[runtime procedure](CAPABILITY_DISCOVERY.md#runtime-self-service), its
machine-readable declaration and report schema. Fetch a pinned commit,
prepare dependencies, run without maintainer guidance, and keep the original
output, its digest, command and any setup failures. Record where assistance
was necessary rather than describing an assisted run as unaided self-service.
Changes in package files, missing published files and sidecar/hash
disagreements are publication defects to report, not exceptions to suppress.

Your own publication and admission into REMORA's shared records are separate.
Admission needs the operator's attribution, consumed and evaluator revisions,
package digest, complete case coverage, scope and non-claims. Implementation
ownership, operator control and host control must be reviewed separately.
Outside operation of REMORA code does not become independent verification;
the primitive report leaves independence unclassified and advances no edge.
An optional [detached operator statement](CAPABILITY_DISCOVERY.md#operator-statements)
binds the observation, source, runner and package digests under an
operator-owned Ed25519 key. A reviewer selects the trusted key and operator
identity explicitly; the embedded key cannot admit itself. Valid signatures
leave host isolation unestablished and admission `UNADMITTED`. The chain is
producer artifact, reproducible runner, completed observation, signed
operator statement, then a separate Federation admission decision.
The existing seven-day producer review proposal applies to requested shared
admission, not as permission to publish your own findings. Preserve unresolved
disagreement, unknown outcomes and negative records alongside later repairs.
Claims made on behalf of another project, private artifacts and unreleased
material require coordination with their owner.

Runner failure checks retain separate assertions for nonzero exit, no report
and no `PASS`, as requested by @imokokok in
[aeoess/agent-governance-vocabulary#177](https://github.com/aeoess/agent-governance-vocabulary/issues/177#issuecomment-5974100278).
This is finder attribution for the failure pattern, not a claim of coauthorship,
endorsement or external evaluation of REMORA's runner. REMORA owns and tests
its implementation. The public self-service default and separate admission
step follow @aeoess's
[proposal](https://github.com/aeoess/agent-governance-vocabulary/issues/177#issuecomment-5986386137).

E7 still needs its external result. E8 still needs counterpart agreement on
the signed field and digest semantics: an aggregate
`scan.toolManifestDigest` is not assumed equivalent to a per-tool
`toolspec_hash`. Identity continuity, downstream idempotency and hardware
attestation are not established by this runner.
`runtime_capability_surface_completeness` and
`implementation_effect_non_transitivity` remain `NOT_ESTABLISHED`.

### External admission

[`external-interop-admission.yml`](../../.github/workflows/external-interop-admission.yml)
is separate from producer CI. Its `pull_request_target` job executes the
base-owned workflow, validator, tooling lock and schemas. The incoming
checkout supplies Git objects only; its code, build configuration, lockfiles
and tests are never installed or executed. Both checkouts discard credentials,
and job permissions are read-only.

The [operator registry](../../artifacts/interop/operators-v1.json) starts
empty. Key ownership, operator attribution, relationship to REMORA and scope
need maintainer review in a separate registry PR. Merge that review before
submitting an observation: a key introduced by the observation PR cannot
approve itself. A revoked or absent key in the base revision is refused even
if the incoming revision restores it. The trusted workflow becomes active
only after its code and locks have landed on the base branch.

An observation PR adds one directory under `artifacts/interop/submissions/`
with `observation.json`, `operator-statement.json` and a descriptor validating
against [interop-submission-v1](../../schemas/interop-submission-v1.schema.json):

```json
{
  "schema_version": "remora-interop-submission-v1",
  "operator_identity": "the identity reviewed for this public key",
  "observation": "observation.json",
  "operator_statement": "operator-statement.json",
  "boundary_digest": "sha256:replace-with-the-observation-boundary-digest",
  "independence": "NOT_CLASSIFIED",
  "requested_admission": "REVIEW_ONLY"
}
```

[`interop_external_admission.py`](../../scripts/interop_external_admission.py)
checks regular Git blobs, schemas, the base-reviewed signing key, exact
observation binding and a consumed revision reachable from the base revision.
It compares source, runner, package and fixture digests with that committed
tree, pins the boundary register and summary, and requires every selected
fixture case. Altered expectations, ceilings, non-claims or promoted claim
statuses are refused. It reads source as data and never
reruns REMORA or the reference verifier.

`VALIDATED_FOR_REVIEW` means those bindings passed. A signed `CONTRADICTED`
observation can pass this validation and must remain negative evidence.
Validation does not establish that the observed execution occurred or that
the operator's statement is factually correct. Producer and external
operator roles remain distinct registry facts; neither role establishes
independence. Admission stays `UNADMITTED`, no contract lifecycle advances,
and a maintainer must separately decide whether to record the result in the
shared index.

### Optional attested execution

[`attested-execution-v1`](../../artifacts/interop/attested-execution-v1/contract.json)
is a provider-neutral `DRAFT` interface, outside the frozen fixture packages
and the self-service runner's allowlist. It requires native attestation
verification, an approved workload measurement, a verifier-issued one-use
challenge with a deployment/verifier-profile-bound appraisal window, an
affirming appraisal and binding to the same observation and
pre-dispatch execution context. Providers and verifier profiles are data;
no Nitro, SEV-SNP or TDX adapter is implemented or claimed.

Its [candidate schema](../../schemas/attested-execution-v1.schema.json)
preserves provider-reported claims while fixing local verification at
`NOT_EVALUATED`. Schema validation and an operator signature do not verify a
hardware quote. REMORA's attestation claims remain `NOT_ESTABLISHED`, and
application correctness, complete mediation and effect correctness are
explicit non-claims.

The [contract graph](../../artifacts/interop/contract-dependencies-v1.json)
declares proposed exact-call and fresh-authority prerequisites for that
optional interface. `strengthens` names a property the interface could
support; it does not establish that property. Empty lists mean no
relationship is declared here, not that native claim ceilings disappear.
Dependency links never inherit status, endorsement or authority.
[`interop_contract_graph.py`](../../scripts/interop_contract_graph.py) checks
indexed IDs, definition and candidate-schema digests, known properties and cycles. Hardware
attestation is not a prerequisite for the Federation base contracts.

For each public interop contract REMORA publishes:

1. the immutable source revision the contract was derived from
   (`source_revision`);
2. a manifest pinning every package file by SHA-256, and a content-addressed
   `package_digest` over those lines;
3. native claim ids and result vocabulary;
4. assumptions;
5. explicit non-claims and a claim ceiling;
6. a verifier request when independent reproduction is sought.

### Identity

A package cannot carry the Git revision that published it: the revision
would have to contain the bytes that name it. So three facts are kept apart.
`source_revision` is provenance and predates the package. `package_digest`
identifies the exact bytes a verifier evaluates; it is derived from the
manifest's file lines, and the manifest is never hashed into itself. The
revision a verifier actually consumed is recorded by the verifier in its run
record, and the reachable master revision carrying the frozen bytes is
recorded in the index's `freeze_record`, outside the package.

### Lifecycle

| State | Means | Advanced by |
|---|---|---|
| `DRAFT` | bytes may still change | nothing yet |
| `FROZEN` | `freeze_record` names a reachable master revision carrying exactly `package_digest` | the producer, after merge |
| `EXTERNAL_RUN_PENDING` | frozen, and the final pin has been given to a named verifier | the producer |
| `REPRODUCED` | a run record with `REPRODUCTION` or `SECOND_IMPLEMENTATION` over this `package_digest` | an external run record |
| `EXTERNALLY_VERIFIED` | a run record that meets the independence contract and covers every claim | an independent run record |

The state is written once, in `artifacts/interop/index.json`, and repeated in
the contract's manifest. The package files carry no state label, so a freeze
changes no bytes. An author run advances nothing. A test
refuses an index whose state exceeds its records, so a contract cannot be
marked verified before the record exists.

### Freezing a package and giving the pin

Freezing is a producer step after merge, done with
`scripts/interop_package.py` so the pin is checked rather than typed.

1. `python scripts/interop_package.py --check` recomputes every digest. It
   refuses a package whose manifest, index, claim packet or verifier request
   disagree, and one whose files name a revision other than `source_revision`.
2. After the package has merged, `python scripts/interop_package.py --freeze
   <contract-id> <master-revision>` reads every package file out of that
   revision's tree and checks the bytes hash to the manifest. It then writes
   `freeze_record` (revision, `package_digest`, date) and sets the lifecycle
   to `FROZEN` in the index and the manifest. The commit that records the
   freeze is a later commit than the one it names, so nothing pins itself.
3. The pin given to a verifier is the contract id, the `package_digest`, the
   frozen revision and the manifest path. Posting it on the control board and
   recording the verifier with `--confirm-pin` moves the contract to
   `EXTERNAL_RUN_PENDING`.

### After an external run

The verifier publishes its run record. The producer reviews it within the
window in the verifier request and records it under `external_runs`. That
moves the contract to `REPRODUCED`, or to `EXTERNALLY_VERIFIED` if the record
meets the independence contract. Only then is the edge status outside this
repository updated. REMORA may afterwards run the verifier's reader in its own
CI, pinned to the reader revision named in the run record, and retain the
output as a CI artifact. That rerun is a `REPRODUCTION` of the external
record, kept as evidence; it adds no state, creates no REMORA authority and
never feeds a policy decision. For the three execution-boundary packages the
rerun is `.github/workflows/probity-boundary-reproduction.yml`, pinned to the
reader revision named on the control board.

### Diversity and independence

A run record states two facts. Implementation diversity says what ran:
`AUTHOR_IMPLEMENTATION`, `REPRODUCTION` (REMORA's reference verifier run by
someone else) or `SECOND_IMPLEMENTATION`. Independence says whether the
record counts as an independent verification: `INDEPENDENT` or
`NOT_INDEPENDENT`. `INDEPENDENT` is allowed only for a second implementation
maintained outside REMORA, run by an external operator, importing neither
REMORA runtime code nor the reference verifier, with the claim ceiling and
non-claims repeated. The schema (`external-run-record-v1`) rejects any other
combination. A second implementation that misses one condition is real
evidence and is recorded; it moves the contract to `REPRODUCED`, not to
`EXTERNALLY_VERIFIED`. This is the claim and provenance discipline of
aeoess/agent-governance-vocabulary#179.

## Foreign evidence

`external-evidence-ref-v1` preserves the producer's native claim and result.
The record is opaque to authority semantics. Merely attaching a foreign
attestation, verifier result or receipt does not authorize a tool call and
cannot promote a REMORA gate outcome.

## Action lineage and attribution

`action-lineage-v1` provides join references across the existing REMORA action
lifecycle. `consumed-artifact-v1` records that an external artifact was
referenced in a named role. Neither format claims causal importance, payment
entitlement or that an external effect occurred.

Runtime wiring is deliberately separate from these contracts. Any future code
that lets an external artifact influence policy must define a deployment-owned
admission policy and receive its own threat model, tests and capability-register
entry.

## Running a verification round

The steps below are what the verifier request asks for, written as a
checklist for a project that wants to verify a REMORA artifact.

1. Pin the inputs. Take `package_digest` and every file digest from the
   contract's `manifest.json`, and the input paths and digests from
   `verifier-request.json`. Record them, with the Git revision you fetched
   them from, in your own run report before anything runs.
2. Implement separately. The implementation lives in a codebase REMORA does
   not maintain and imports neither REMORA runtime code nor
   `reference_verifier.py`. A fresh clone that runs REMORA's own verifier is a
   reproduction, not an independent implementation.
3. Classify two things separately: implementation diversity
   (`AUTHOR_IMPLEMENTATION`, `REPRODUCTION`, `SECOND_IMPLEMENTATION`) and
   independence (`INDEPENDENT`, `NOT_INDEPENDENT`). Only `INDEPENDENT` closes
   `external_verification: PENDING`; a second implementation on its own moves
   the contract to `REPRODUCED`.
4. Report one result per native claim and case, using only `ESTABLISHED`,
   `CONTRADICTED` and `NOT_ESTABLISHED`. A layer the public material cannot
   support stays `NOT_ESTABLISHED`; it is not rounded up.
5. Record the exact implementation revision, command, environment, input
   digests, the `package_digest` and the REMORA Git revision you consumed next
   to the results, in the shape of `external-run-record-v1`.
6. Repeat the producer's claim ceiling and non-claims from the claim packet
   in your report, so a reader of your report alone cannot read more into the
   result than the producer claimed.
7. Review and publish. The request proposes a seven-day producer review, then
   publication; an unresolved disagreement is published as a disagreement, not
   withheld.

The round is complete when the report is public and the producer has
recorded the outcome against the contract in `index.json`. Verification of the
artifact is exactly that: it is not endorsement of REMORA, and it creates no
dependency, membership or authority in either direction.

### A round that has been run

The pattern above has been exercised once from outside, on a conformance
corpus rather than an interop contract. In darklordVirtual/REMORA-research#629,
Rul1an ran corpus-adequacy against `conformance/evidence-sufficiency-v1/`
with a separately maintained tool and an agreed seeded-fault list. The first
run found survivors the maintainer had not found. The report was published
unchanged and the survivors were kept as open gaps. v1.1 and v1.2 closed
them, and the external tool was run again on each. The record, with the pinned
digests and every count, is
[`docs/assurance/external_adequacy_evidence_sufficiency_v1.md`](../assurance/external_adequacy_evidence_sufficiency_v1.md).
Cases written after a fault was known are labelled as repair, not as
independent evidence, in that record and in NEGATIVE_RESULTS.md.

## Asking REMORA to reference your artifact

The consumer side is narrower. REMORA can record that an external artifact
was referenced in a named role (`consumed-artifact-v1`) and can carry your
native claim and result as an opaque reference (`external-evidence-ref-v1`).
Open an issue with the artifact's revision, digest and the role you intend.
The reference is admitted by a deployment-owned step and never alters a
decision. Attribution stays attached to the originating project.
