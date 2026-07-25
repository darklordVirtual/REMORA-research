# Contributing

The canonical contributor guide is
[docs/10-contributing.md](docs/10-contributing.md). It covers how to add a
result, an oracle, or a negative finding, the language rules, and the pull
request checklist. Read it first; this file only states the repository-level
expectations.

## How changes land

All changes land via pull request with green CI. Direct pushes to `master` are
not the workflow, even for the maintainer where avoidable. Changes touching
the security-critical paths listed in [.github/CODEOWNERS](.github/CODEOWNERS)
(`remora/policy/`, `remora/enforcement/`, `remora/governance/`, `servers/`,
`schemas/`, `.github/`, `docs/assurance/`) require maintainer review before
merge.

## Claim hygiene

No claim without an artifact, no artifact without a reproduce command. Every
number added to the README, the paper, or any claim document must be backed by
a committed result artifact on disk, quoted with its sample size, confidence
interval, and scope caveat; negative results and caveats must never be
removed. The decision rule is in
[docs/05-claim-hygiene.md](docs/05-claim-hygiene.md) (canonical), and the
working agreement is in [CLAUDE.md](CLAUDE.md).

## Contribution licensing

REMORA is dual-licensed: Business Source License 1.1 publicly, with
separate commercial licenses issued by the Licensor (Stian Skogbrott).
See [LICENSING.md](LICENSING.md).

By submitting a contribution, you confirm that you have the legal right
to submit it and that it contains no undisclosed third-party material.

Contributions are not accepted for inclusion in the dual-licensed
REMORA codebase until the contributor has accepted the applicable
REMORA Contributor License Agreement. The CLA grants the REMORA
Licensor the right to distribute the contribution under:

- the Business Source License;
- future Change Licenses;
- separate commercial licenses.

A `Signed-off-by` line alone does not grant the relicensing rights
required by the REMORA licensing model.
