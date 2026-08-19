# Changelog

This file lists externally relevant changes by release. Fine-grained development history remains available in Git commits and pull requests.

The pre-cleanup development log is preserved at `docs/archive/CHANGELOG_PRE_HYGIENE_2026-08-19.md`.

## Unreleased

### Repository hygiene

- Simplified the public README and documentation index around one canonical runtime reading path.
- Added explicit CORE / OPTIONAL / EXPERIMENTAL / HISTORICAL boundaries for developer handoff.
- Added branch lifecycle and documentation-style rules to the contribution guide.
- Removed committed local frontend planning state and ignored future `.lovable/` workspace files.
- Added automatic deletion of merged branches and a safe sweep for branches already merged into the default branch.
- Preserved research history while removing older thermodynamic/statistical-physics work from the primary runtime documentation path.

### Execution assurance

- Added explicit `development`, `research`, `review` and `controlled_pilot` runtime profiles.
- `review` and `controlled_pilot` fail closed unless Signed ToolSpec, trusted signer identity, deployment-owned callable registry, durable execution state and PDP signing prerequisites are present.
- Clarified that `/v1/execution/*` is the enforcing surface and that advisory assessment APIs do not control bypass credential paths.

## 0.10.0 — 2026-07-25

### Licensing

- Moved new REMORA versions to Business Source License 1.1 with separate commercial licensing.
- Added licensing, copyright, trademark and third-party notice material.
- Added a CI policy check for license metadata drift.

### Research and assurance

- Continued the claim-register, capability-register, reproducibility and negative-result governance model.
- Preserved benchmark caveats and superseded findings as part of the evidence record.

For detailed changes between tagged revisions, use Git history, merged pull requests and the archived pre-cleanup changelog.
