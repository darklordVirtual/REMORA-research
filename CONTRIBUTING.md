# Contributing

The canonical contributor guide is [docs/10-contributing.md](docs/10-contributing.md). This file defines repository-level expectations.

## Change workflow

- Changes land through pull requests with green CI.
- `master` is the integration branch; do not use long-lived feature branches.
- Create one branch per coherent change. Delete it after merge.
- Do not keep a branch solely as historical evidence; Git commits, tags, PRs and archived artifacts already preserve history.
- Freeze reproducibility milestones with tags or committed manifests, not permanent experiment branches.
- Keep unrelated documentation, dependency and runtime changes in separate PRs when they have different review risks.

Security-critical paths are listed in [.github/CODEOWNERS](.github/CODEOWNERS). Changes to those paths require maintainer review before merge.

## Documentation

Documentation is part of the governed surface. Keep it concise and assign one source of truth per topic.

- `README.md` explains scope and status.
- `DEVELOPER_OVERVIEW.md` is the developer handoff.
- `ARCHITECTURE.md` is the canonical runtime architecture.
- `docs/README.md` is navigation, not a second architecture document.
- `docs/assurance/` owns claim, capability and release-state records.
- `docs/research/` contains active research material.
- `docs/archive/` contains superseded or historical material.

Prefer direct statements over promotional language. Avoid unsupported adjectives such as “world-class”, “production-grade”, “safe”, “proven” or “enterprise-ready”. State the measured property, evidence source, status and limitation instead.

Do not create a new overview, roadmap or architecture document when an existing canonical file can be updated. If a document becomes obsolete, mark or archive it rather than leaving two apparently current explanations.

AI-assisted development is allowed and disclosed in `docs/AI_USE.md`; generated prose or code is not evidence by itself.

## Claim hygiene

No claim without an artifact; no artifact without a reproduce command. Numerical claims in README, paper or assurance documentation must resolve to committed evidence with sample size, denominator, uncertainty where applicable and a scope caveat.

Negative results and limitations are part of the research record and must not be removed to improve presentation. See [docs/05-claim-hygiene.md](docs/05-claim-hygiene.md).

## Before opening a PR

Run the relevant focused tests, then the repository quality gates required by the changed surface. At minimum, behavioral changes require tests and documentation changes must pass the documentation/claim consistency checks.

Do not commit secrets, private review notes, local agent state, generated IDE/AI-tool plans or local build output.

### Typing and coverage floors for the trusted computing base

`remora/policy`, `remora/enforcement`, `remora/execution`, `remora/governance`
and `servers/` are the code that decides and enforces. Two gates apply to them
that do not apply to the research modules:

- **`disallow_untyped_defs`** (pyproject `[[tool.mypy.overrides]]`). Default
  mypy does not check the bodies of unannotated functions at all, so an
  untyped function on the ACCEPT path is invisible no matter how wide the
  gate's scope. Annotate; do not add a blanket ignore to get through.
- **Per-package coverage floors** (`scripts/check_coverage_thresholds.py`,
  branch coverage on). A single global number lets a well-covered research
  module pay for a thinly covered enforcement module. Raise a floor when the
  real number rises; never lower one to make a failing build pass — cover the
  code instead.

### Test structure

- **Shared fixtures live in `tests/conftest.py`**: `repo_root`, `engine`,
  `observation` (a factory, so which fields a test sets stays visible at the
  call site), `signing_key`. Do not re-derive the repo root with `parents[N]`.
- **`@pytest.mark.docgate`** marks a test that asserts on repository documents
  and registers rather than runtime behaviour. Those run as their own CI step
  so a documentation drift and a governance regression do not fail the same
  way, and so the headline test count means what it says.
- **Assert invariants, not counts.** `assert len(sections) == 39` is
  documented to break every time the work goes as planned, which teaches
  people to bump the number without reading what changed. Assert that IDs are
  unique and contiguous, that sets stay balanced, that the aggregate equals
  the sum of its parts. Exact values are correct when they guard a specific
  published correction from being reverted — say so in a comment when they do.

## Contribution licensing

REMORA is dual-licensed under the Business Source License 1.1 and separate commercial licenses issued by the Licensor. See [LICENSING.md](LICENSING.md).

By submitting a contribution, you confirm that you have the legal right to submit it and that it contains no undisclosed third-party material. Contributions are not accepted into the dual-licensed codebase until the applicable REMORA Contributor License Agreement has been accepted. A `Signed-off-by` line alone does not grant the relicensing rights required by this model.
