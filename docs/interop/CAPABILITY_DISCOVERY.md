# REMORA capability discovery

[remora-capabilities-v1.yaml](remora-capabilities-v1.yaml) is a machine-readable
declaration of bounded workflow capabilities and self-service fixture
procedures, including a separate bounded runtime-primitive procedure. Its
evidence points to current repository records. The
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
replay is self-service. Full workflow reproduction remains `NOT_READY`; the
separate primitive runner below does exercise REMORA code. An independent implementation or
external run must be recorded under the Federation result contract before
external reproduction can be claimed.

## Runtime self-service

[`interop_self_service.py`](../../scripts/interop_self_service.py) evaluates
the frozen v1 exact-call, fresh-authority and effect-evidence cases using
REMORA's actual lease, grant, dispatcher and declared-delta primitives. The
tools and observer inputs are synthetic. This does not run the execution API
or contact a deployment, and v1 retains the coverage gaps described in
[FEDERATION.md](FEDERATION.md#execution-boundary-fixtures). Draft v1.1 and
E7/E8 packages are deliberately outside this runner's allowlist.

Start in a clean checkout of a full commit containing the runner. Use Python
3.12, Git and a separately prepared virtual environment. Dependency preparation
is explicit; the runner never installs packages. The small `interop` extra
provides report validation without installing API or model clients:

```bash
python -m venv /tmp/remora-verification-venv
source /tmp/remora-verification-venv/bin/activate
grep -vE '^-e|^#|file://' requirements-lock.txt > /tmp/remora-verification-constraints.txt
python -m pip install -e ".[interop]" -c /tmp/remora-verification-constraints.txt
python scripts/interop_self_service.py --list
REVISION=$(git rev-parse HEAD)
python scripts/interop_self_service.py --revision "$REVISION" \
  --operator "your own attributed operator identity" \
  --host "your own host attribution" \
  --output /tmp/remora-runtime-observation.json
sha256sum /tmp/remora-runtime-observation.json
```

Choose unused environment, constraints and result paths if those names already
exist. Verify the selected commit through your usual source review before
running it. `--contract exact-call-binding-v1` limits the evaluation;
repeat `--contract` to select several. `--timeout` accepts 1 through 300
seconds for the runtime subprocess, defaulting to 120.

The runner checks HEAD against the explicit revision, refuses changed tracked
runtime/evidence inputs, checks package files and their folded digest, and
extracts only committed inputs into a fresh temporary directory. Untracked
modules and checkout bytecode are not used. The isolated child receives
temporary home directories and public test-only HMAC signing material, rather than
the caller's environment or deployment credentials. This is process and
input isolation, not an OS sandbox or hardware attestation. Installed Python
dependencies remain trusted; their versions are recorded, not attested.
The report fixes `host_isolation = NOT_ESTABLISHED`: this code does not prevent
a trusted worker from reading host files, networking or spawning processes.
A hostile host or interpreter can subvert software checks.

Every snapshot file is checked before execution and after the worker returns.
The parent sends its digest manifest through stdin, not through a mutable
sidecar. The worker verifies it before importing the evaluator and after
evaluation. Package bytes are read once, checked against both source and
package digests, and parsed from those same bytes. Snapshot inputs refuse
absolute paths, parent traversal, symlinks at any path component, archive
links and multiply linked files. These controls detect the tested
verify-then-change attacks; they do not attest a tamper-proof host.

The output validates against
[`runtime-self-service-v1`](../../schemas/runtime-self-service-v1.schema.json).
It records the executed revision separately from the historical fixture
source revision, package and source-file digests, loaded runtime-module
digests, dependency versions, operator and host declarations, timestamps, per-case
expected and observed values, claim ceilings and non-claims. Operator identity
is self-declared, host ownership is not authenticated, and independence stays
`NOT_CLASSIFIED`. No aggregate safety verdict or measured `runner_contract`
booleans are inferred from a successful run. The boundary register and summary
digests identify the exact boundary version, separate from the executed code.

| Exit | Result file | Meaning |
|---|---|---|
| 0 | Complete observation | All per-case `claim_status` values are `ESTABLISHED` within the fixture ceiling. |
| 1 | Complete observation | At least one case is `CONTRADICTED`; retain this negative result. |
| 2 | No new result | Runner failure, missing dependency, invalid input/output, timeout, killed verifier or malformed observation. |
| 3 | Complete observation | No contradiction, but at least one case is `NOT_ESTABLISHED`. |

Completed reports have `execution_status: COMPLETED`, separate from each
case's `claim_status`. Runtime failures report `execution_status: FAILED` on
stderr with `claim_status: NOT_EVALUATED` and publish no observation. The full
default run includes negative controls with `NOT_ESTABLISHED` ceilings, so its expected exit is 3. CI may
explicitly accept 0 or 3 as execution completion, but must not relabel 3 as
all claims established. Exit 1 preserves a completed negative observation;
exit 2 is not a conformance result.

Existing output is never overwritten, including during a competing
publication. A complete file is published atomically after validation. Child
stdout is not forwarded; no `PASS` is printed. Interruption before publication
leaves no result; missing output must not be reported as passing. Runner failure
dimensions are measured separately in
[`test_interop_self_service.py`](../../tests/test_interop_self_service.py);
completed contradictions are not confused with verifier failure.
The same pinned revision is also run twice: observations must be identical
after removing execution timestamps and operator attribution, in the same
dependency environment and on the same host. Neither a detached signature
nor its issuance timestamp is part of that deterministic observation.

Publish your own observation and its digest under the
[standing offer](FEDERATION.md#self-service-and-publication), without seeking
permission for each public research run. Review/admission into REMORA's shared
records is separate. This report is not an `interop-result-v1` record: that
schema's L1 currently means reference replay, not externally operated REMORA
runtime. Neither schema nor external status is silently redefined here.

### Process custody reproduction

[`reproduce_custody.py`](../../scripts/reproduce_custody.py) runs an authority
process and executor processes separately, with an Ed25519 lease and a durable
SQLite nonce store:

```bash
python scripts/reproduce_custody.py --output /tmp/remora-custody.json
```

The output file must not exist; it is created exclusively and never
overwritten. The run checks exact-call, tenant, principal and runtime binding,
expiry, tampering, forbidden self-minting and declared custody violations.
Two concurrent dispatches must produce exactly one local effect. After a lost
response the outcome stays unknown, and a replay after a process restart is
refused as an already-consumed nonce. It uses ephemeral signing keys, a synthetic
credential and temporary state; no private key or credential value is
exported.

The processes run as the same OS user. This does not establish host
isolation, HTTP transport authentication, an exhaustive credential inventory
or the absence of undeclared external effect routes, and the record says so in
its `claim_boundary`. It is producer-authored evidence and advances no package
lifecycle or capability maturity.

## Operator statements

An operator can attach an offline Ed25519 statement using
[`interop_operator_statement.py`](../../scripts/interop_operator_statement.py).
Prepare the `security` extra explicitly under the same constraints:

```bash
python -m pip install -e ".[interop,security]" -c /tmp/remora-verification-constraints.txt
python scripts/interop_operator_statement.py sign \
  --observation /tmp/remora-runtime-observation.json \
  --operator "your own attributed operator identity" \
  --private-key /secure/operator-private.pem \
  --output /tmp/remora-operator-statement.json
python scripts/interop_operator_statement.py verify \
  --observation /tmp/remora-runtime-observation.json \
  --statement /tmp/remora-operator-statement.json \
  --operator "your own attributed operator identity" \
  --trusted-key /trusted/operator-public.pem
```

The key files are operator-owned Ed25519 PEM files; provision them separately,
keep private material outside the checkout and do not reuse execution-lease
or deployment keys. The signer accepts unencrypted PEM only. Local key custody
is the operator's responsibility; the tool neither creates identities nor
fetches keys or contacts a remote signer.

The closed
[statement schema](../../schemas/interop-operator-statement-v1.schema.json)
binds the exact observation bytes, runtime revision, source-manifest digest,
runner digest, sorted package and fixture digests, operator and host
attribution, execution timestamps, issuance time and public-key fingerprint.
`revision_digest` is SHA-256 of the existing REMORA JCS-v0 encoding of
`{runtime_revision, source_files}`. It is not a weight digest or a replacement
Git hash. `key_id` is SHA-256 of the raw Ed25519 public-key bytes.

Signatures cover the fixed byte prefix `REMORA-operator-statement-v1`
followed by a NUL byte and the statement's
`remora/jcs-rfc8785-v0` canonical bytes. Signature and public-key values use
canonical unpadded base64url. The signature's embedded OKP JWK supplies
verification material only; the verifier requires a separately selected
trusted public key and expected operator name. It checks that both match the
statement and re-derives every observation binding. Changed whitespace in the
observation therefore invalidates its binding even if the JSON values agree.
Verification exits 0 only for a valid signature and matching binding;
signing or verification errors exit 2 explicitly.

A valid statement establishes possession of that signing key and a signed
assertion about those bytes. It does not prove that the operator ran the
code, identify the model or build that executed in a deployment, authenticate
the host, establish clock trust or independently validate the claims.
`host_isolation`, independence, admission and authority remain
`NOT_ESTABLISHED`, `NOT_CLASSIFIED`, `UNADMITTED` and `NONE`, respectively.
This is not TRACE signing, hardware attestation or automatic Federation
admission. Reviewers remain responsible for the identity-to-key mapping,
key validity/revocation and the admissibility of the evidence.

## Hash-locked producer and admission tooling

Producer CI pins Python 3.12.15, then installs pip 26.2.1 from its
[hashed bootstrap lock](../../requirements-federation-bootstrap.lock).
The [Federation tooling lock](../../requirements-federation.lock) contains
exact versions and SHA-256 hashes for the selected tests, validators and
build tools. Installation uses wheels only, without transitive dependency
resolution or an isolated build environment; REMORA source is installed
separately from the pinned checkout.

To use the same preparation in a fresh Python 3.12.15 environment:

```bash
python -m pip install --no-deps --only-binary=:all: --require-hashes -r requirements-federation-bootstrap.lock
python -m pip install --no-deps --only-binary=:all: --require-hashes -r requirements-federation.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
```

This is stricter than the small constraints-based `interop` install above,
which does not hash-lock every downloaded artifact. Neither procedure
attests the OS, package publisher, interpreter or host. Dependency versions
and the runtime platform remain recorded evidence, not hardware proof.

Lock updates are reviewed source changes. Regenerate using pip-tools 7.6.1
on Python 3.12, retaining the repository's version constraints:

```bash
python -m piptools compile --allow-unsafe --generate-hashes --no-emit-index-url --no-emit-trusted-host --strip-extras -o requirements-federation-bootstrap.lock requirements-federation-bootstrap.in
python -m piptools compile --allow-unsafe --generate-hashes --no-emit-index-url --no-emit-trusted-host --strip-extras -o requirements-federation.lock requirements-federation.in
```

The base-reviewed admission procedure and submission layout are defined in
[FEDERATION.md](FEDERATION.md#external-admission). Key review and signature
binding are available separately from runtime execution; the operator
registry starts without approved operators.

## Audit and gaps

`capability_audit.investigated` records candidates included and rejected.
`runtime_self_service_procedures` describes the bounded primitive runner.
`self_service_gaps` keeps the remaining API/deployment and outside-run gaps
separate from that procedure and reference replay. The declaration does not
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
