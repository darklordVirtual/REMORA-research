# Contributing to REMORA

This is the canonical contribution guide for results, runtime changes, integrations and documentation.

## Repository workflow

1. Branch from `master` for one coherent change.
2. Keep the branch short-lived.
3. Add or update tests for behavioral changes.
4. Run the relevant focused checks and required repository gates.
5. Open a pull request with scope, rationale, validation and known limitations.
6. Delete the branch after merge.

Do not keep merged feature, fix, documentation or experiment branches as permanent history. Use commits, PRs, tags and committed artifacts for traceability.

## Documentation structure

One topic should have one canonical source:

- `README.md`: public project scope and current status.
- `DEVELOPER_OVERVIEW.md`: developer/reviewer handoff.
- `ARCHITECTURE.md`: canonical runtime architecture.
- `docs/README.md`: navigation and document precedence.
- `docs/assurance/`: machine-governed claims, capabilities and release state.
- `docs/research/`: active research material.
- `docs/archive/`: historical and superseded material.

Do not add another overview or architecture narrative to avoid editing an existing canonical document.

### Documentation style

Use precise, testable language. Prefer:

- `status: experimental`
- `wired to /v1/execution`
- `not externally validated`
- `0/208 observed; 95% upper bound 1.81%`
- `library implementation; not on the enforcing path`

Avoid promotional or self-evaluative language such as:

- `world-class`
- `production-grade`
- `revolutionary`
- `proven safe`
- `enterprise-ready`
- `formal guarantee` unless a narrowly scoped formal proof actually exists

Avoid filler such as “the key insight”, “what this really means”, “the honest part” or repeated restatements of the same caveat. State the evidence and boundary once, close to the claim.

AI-assisted development is disclosed in `docs/AI_USE.md`. AI-generated output is not evidence without an independently verifiable artifact, test result or source.

## Adding or changing a result

1. Run the experiment using the applicable reproduction protocol.
2. Commit the result artifact to `results/` or `artifacts/`.
3. Update `docs/assurance/claim_register_v1.yaml` when the governed claim changes.
4. Update `docs/02-evidence-and-claims.md` with the result and scope caveat.
5. If the finding is negative, falsifies a hypothesis or reveals a limitation, update `NEGATIVE_RESULTS.md`.
6. Do not add a numerical result to README, the paper or claim documentation without the underlying artifact.

Every quantitative claim must identify the denominator/sample size, relevant uncertainty, scope and exact evidence artifact.

## Claim hygiene

See `docs/05-claim-hygiene.md`. The short rule is:

> No claim without an artifact. No artifact without a reproduce command.

A benchmark result is not field validation. An implemented library component is not automatically part of the enforcing API path. A passing internal test is not external verification.

## Runtime and integration changes

For changes to `remora/policy/`, `remora/toolcall/`, `remora/enforcement/`, `remora/governance/`, `servers/` or `schemas/`:

- identify the affected trust boundary;
- add positive and negative tests;
- preserve fail-closed behavior for strict profiles;
- update API/schema contracts when the public contract changes;
- update the capability register if wiring depth changes;
- document any new degradation mode explicitly.

Do not infer tool risk, target or authority from agent-provided prose when a deployment-owned contract exists.

## Adding an oracle or research backend

Research backends belong behind the existing research interfaces. Add tests, identify the stability class, and do not present a new research signal as part of the execution kernel unless it is deliberately wired and reflected in the capability register.

## Negative results

Negative results are retained as first-class research evidence. Do not delete a failed experiment because a later design supersedes it. Mark the current status and link the successor instead.

## External review

External review should identify:

- the exact claim or capability under review;
- the commit/release being reviewed;
- the reproduce command;
- the artifact or expected contract;
- the observed result, including disagreements and failures.

See `docs/validation/external-review.md` and `docs/assurance/independent_review_protocol_v1.md`.

## Pull request checklist

- [ ] Scope is coherent and unrelated changes are excluded.
- [ ] Relevant focused tests pass.
- [ ] Required CI/quality gates pass.
- [ ] New or changed claims resolve to committed evidence.
- [ ] Limitations and negative findings are preserved.
- [ ] Canonical documentation was updated instead of creating a parallel explanation.
- [ ] No secrets, local agent state, AI-tool planning files or generated scratch output are committed.
- [ ] Branch can be deleted after merge.

## Contribution licensing

REMORA is dual-licensed under the Business Source License 1.1 and separate commercial licenses; see `legal/LICENSING.md`.

By submitting a contribution, you confirm that you have the legal right to submit it and that it contains no undisclosed third-party material. Contributions are not accepted for inclusion until the applicable REMORA Contributor License Agreement has been accepted. A `Signed-off-by` line alone does not grant the relicensing rights required by the REMORA licensing model.
