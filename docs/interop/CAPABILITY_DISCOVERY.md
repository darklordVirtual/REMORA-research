# REMORA capability discovery

[remora-capabilities-v1.yaml](remora-capabilities-v1.yaml) is a machine-readable
declaration of bounded workflow capabilities and self-service fixture
procedures. Its evidence points to current repository records. The
[capability register](../assurance/capability_register_v1.yaml) remains the
source of truth for wiring depth, and the [claim register](../assurance/claim_register_v1.yaml)
remains the source of truth for research claims.

## Workflow discovery

A workflow designer can ask, “I require exact-call binding immediately before
dispatch.” Resolve `exact_call_binding` in the declaration, then inspect its
stage, inputs, outputs, trust assumptions, maturity and limitations. It is a
candidate provider, not a decision that the workflow needs REMORA. The
declaration describes REMORA only. A neutral resolver may compare this
property with other providers without treating similarly named properties as
equivalent.

The maturity fields describe separate evidence states. `TESTED` means
repository tests exist. `REPRODUCIBLE` means an outside procedure tests the
REMORA runtime property. `EXTERNALLY_REPRODUCED` and `OPERATOR_OBSERVED`
require their own run or operator records. None of the declared workflow
capabilities currently claims those higher states or production establishment.

## Self-service discovery

An outside operator can run the reference verifier for the exact-call binding,
fresh-authority and effect-evidence frozen fixture packages. The commands,
source revision, freeze revision, package digest, file digests, result
vocabulary, negative controls and claim ceilings are recorded in the
declaration and in each package README.

These commands replay publisher-authored reference verifiers. They do not
execute REMORA, validate that the current runtime implements the fixture
contract, or create an external reproduction record. Therefore the package
replay is self-service, while runtime-level self-service reproduction remains
`NOT_READY` for all three capabilities. An independent implementation or
external run must be recorded under the Federation result contract before
external reproduction can be claimed.

For a separate check of the **local REMORA reference runtime**, run:

```bash
python scripts/reproduce_runtime_surface.py --output /tmp/remora-runtime-run
python scripts/reproduce_runtime_surface.py --verify /tmp/remora-runtime-run
```

Use a fresh output directory. The run executes `SignedSurfaceRuntime` against
a temporary local record, checks the verified effect and negative controls,
and writes `environment.json`, `inputs.json`, `results.json`,
`negative-controls.json`, `evidence.json`, `claim-boundary.json`, and
`hashes.json`. `environment.json` records the Git revision, working-tree
status and hashes of selected executed source files, so a dirty checkout is
visible. The verifier checks the output bytes against the manifest;
an operator must pin that manifest separately before treating it as an
integrity record. This exercises REMORA code, unlike fixture replay, but it
does not run the strict HTTP deployment, inventory an external host, establish
credential custody, or constitute independent external reproduction. It does
not change the three capability declarations' `runtime_reproduction_status`
or the global surface-completeness claim.

## Audit and gaps

### Combined local handoff reproduction

From a pinned checkout with the development and security dependencies installed:

```bash
python -m pip install -e ".[dev,security]"
python scripts/reproduce_federation_readiness.py --output /tmp/remora-handoff-run
python scripts/reproduce_federation_readiness.py --verify /tmp/remora-handoff-run --manifest-sha256 DIGEST_PRINTED_BY_RUN
```

Use a new output directory outside the checkout. Retain the printed manifest
digest through a separate trusted channel. Verification checks the complete
file set against that pin, including additions and removals; it does not
authenticate an operator or establish correctness merely from matching bytes.
For shared results, use a clean pinned checkout and retain its environment
record. A dirty checkout is recorded and must not be described as the named
commit's unmodified behavior.

The runner executes the local runtime, separate authority/executor processes,
the listed UNKNOWN/reconciliation, receipt-lineage and interop tests, and six
publication gates. It retains logs and JUnit output and refuses zero tests,
failures, errors or skips. Failure exits nonzero and leaves diagnostic output;
only a completed run receives a final manifest. Test plugin auto-discovery is
disabled so unrelated host plugins cannot change the run.

The process reproduction uses ephemeral signing keys, a synthetic credential,
a temporary local file and SQLite nonce storage. It checks exact-call, tenant,
principal and runtime binding, expiry, tampering, forbidden self-minting,
declared custody violations, concurrent dispatch, response loss after an
effect, and replay after process restart. No private keys or credential values
are exported. Separate processes run as the same OS user: this does not prove
host isolation, HTTP transport authentication, exhaustive credential inventory
or the absence of undeclared external effect routes.

The combined package is producer-authored evidence. Full authority-to-audit
digest lineage, independent reproduction, E7 external execution, E8 format
confirmation and Federation owner acceptance remain separate open obligations.
No package lifecycle or capability maturity is advanced by this command.

`capability_audit.investigated` records candidates included and rejected.
`self_service_gaps` separates an available package replay from the missing
runtime-level procedure and evidence. In particular, the declaration does not
claim enforcement completeness: the capability register keeps
`runtime_capability_surface_completeness` at `NOT_ESTABLISHED`. It does not
claim that `EFFECT_VERIFIED` proves causation or observes every side effect.

## Boundary discovery

[remora-boundaries-v1.yaml](remora-boundaries-v1.yaml) keeps workflow
capabilities, internal trust boundaries, external interfaces, Federation
edges, role mappings, observation roles and claim ceilings as separate
records. Each boundary names its supporting workflow capabilities and cannot
claim higher maturity than those capabilities. Its audit revision,
implementation sources, capability freshness and artifact digests are checked
before the declaration can pass.

The Federation-facing
[boundary summary](../../artifacts/interop/remora-boundary-summary-v1.json)
is generated from that register and listed by the stable interop index. Pin
confirmation, execution records, independence, claim results, production
evidence and Federation adoption remain separate statuses. E7 has pinned
fixtures but no external run record. It does not establish
`runtime_capability_surface_completeness`; no independent observation,
production status or Federation adoption is implied.

The AGV role mappings are candidates for exact-call authorization and tool
enforcement. Pre-action decision and revocation mappings remain partial.
Effect verification and reconciliation are candidate observation roles. They
do not establish causation, detection of undeclared effects, observer
independence or a successful outcome for an unresolved dispatch.

## Non-goals

The declaration provides no automatic trust, endorsement, ranking or
certification. It does not require REMORA to participate, imply Federation
membership, install dependencies, execute anything remotely, or assert
semantic equivalence between projects. Workflow owners decide whether a
capability is required and whether another provider is acceptable. Evidence
from one capability does not transfer to another capability.

Validate the committed declaration with:

```bash
python scripts/check_remora_capabilities.py
python -m pytest tests/test_remora_capability_declaration.py -q
python scripts/check_remora_boundaries.py
python scripts/build_remora_boundary_summary.py --check
```
