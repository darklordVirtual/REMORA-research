# DEV integration and master promotion policy

Status: proposed CI enforcement; GitHub branch rulesets must be configured by an authorized repository administrator.

## Trust boundaries

- `master`: protected stable integration/release reference. Do not push directly.
- `dev`: protected long-lived integration branch. Its push triggers the **same full validation suite** as a push to `master`, including all Python 3.11–3.14 legs, deterministic tests, provenance, Quality Gates, CodeQL, supply-chain checks, shadow replay, and applicable interop checks.
- Topic branches: open reviewed PRs **into `dev`**; individual PRs use the documented selective test workflow, and the resulting `dev` push runs the full matrix against the *combined* integration state.
- Promotion: open a same-repository **`dev -> master` PR**, review the aggregate diff, and run the full four-version deterministic suite and other required checks on the proposed merge result. The existing required `deterministic-suite-required` CI aggregator rejects a `master` PR whose head is not the same-repository `dev`.

Do not confuse green CI with independent code review, runtime behavior evidence, security assurance, or deployment authorization. Security-sensitive changes require a documented adversarial review and explicit human promotion approval.

## One-time GitHub ruleset setup (administrator action)

The GitHub App connector used by the automation cannot change repository rulesets or branch protection. Configure **Settings -> Rules -> Rulesets** in the GitHub web UI (or use an administrator-authorized GitHub API client).

Create an active branch ruleset for `dev` and keep/enhance the existing `master` protection:

1. Require pull requests before merging; disallow force pushes and deletion; restrict bypass actors.
2. Require resolved conversations and at least one **independent** human reviewer for security-sensitive changes. Do not allow the code-producing agent alone to approve its own PR. Choose a practicable reviewer policy for a single-maintainer repository.
3. Require successful, up-to-date status checks: `deterministic-suite-required`, `quality-gates-required`, `codeql-required` and `supply-chain-required`. Use the exact check names as shown by GitHub for this repository; pin check sources to GitHub Actions where available.
4. Require the PR branch to be up to date with the target before merge (or use GitHub merge queue with equivalent merge-group workflow coverage). Do not enable merge queue until workflows support `merge_group`.
5. For `master`, allow only a reviewed `dev -> master` PR. The deterministic CI aggregator checks source branch and repository but **cannot block direct pushes**; ruleset enforcement is mandatory.
6. Keep production deploy, publication, external sync and telemetry workflows scoped to their existing master/tag/schedule/manual triggers. No production mutation is triggered by `dev` push.

## Integration procedure

1. Review the actual PR diff and dependencies; update `provenance/code-register-v1.json` for every change.
2. Merge approved PR to `dev` only after its required gates pass. Merge serially when there are overlapping changes to ensure fresh provenance.
3. Verify the `dev` push jobs completed and passed, including full Python matrix and negative security tests; examine failed or skipped jobs.
4. After the integrated build is stable, open `dev -> master`, inspect the accumulated change set and run the full PR suite. Require explicit human sign-off.
5. Merge to `master`; verify its push checks again. Tag or deploy only under the existing release policy.

## Non-promoting checks

The expensive scheduled/manual mutation sweep, NLI parity run, research publication, R2 sync, CodeGraph index, Cloudflare deployment and OSF mirror are not automatically turned into `dev` write workflows. Path-filtered interop checks retain their existing filters on both branches. Production credentials must never be broadened solely to obtain CI parity.

## Known limitations

- Branch ruleset enforcement cannot be completed with the available managed GitHub connector and requires a repository administrator.
- A green `dev` build is evidence that the configured tests passed for that revision, not proof of security or correctness.
