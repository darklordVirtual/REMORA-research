# Provenance ledger

A machine-readable chain from each original REMORA concept to the documents,
code and tests that express it. The chain continues to the commit where the
concept first appeared, to the conformance suites and interop contracts that
test it, and to what external sources document about using it.
`legal/PROVENANCE.md` explains what such a record does and does not show.

```text
concept record (PROV-xx)
    -> first recorded commit (docs/assurance/provenance_register_v1.json)
    -> canonical specification, implementation, tests (paths in the record)
    -> conformance suites and interop contracts (artifacts/interop/index.json)
    -> claims and capabilities (docs/assurance registers)
    -> snapshot manifest, digested from one commit's tree (manifests/)
    -> signed commit, immutable release, Sigstore attestation, Zenodo DOI
    -> external adoption events (EXTERNAL_ADOPTION.yaml)
```

## Files

| File | Holds |
|---|---|
| `concepts/PROV-xx.yaml` | one record per concept; the id is permanent and the file name is the id |
| `PRIOR_ART.yaml` | the sources a prior-art review starts from, and every dated review |
| `EXTERNAL_ADOPTION.yaml` | what an external source documents about its own use of a REMORA concept, with the source's revision |
| `AUTHORS.yaml` | scientific attribution; rights ownership is in `legal/COPYRIGHT.md` |
| `POLICY.yaml` | protected paths, the signature gate, the classification vocabulary, the manifest rule |
| `schemas/` | JSON Schemas for the records and the two registers |
| `manifests/provenance-manifest-v1.json` | digests of every expressing file, record and register, taken from one snapshot commit |
| `code-register-v1.json` | live coverage of every Git-tracked file: exact-byte SHA-256, Git blob id, mode and explicit concept links |
| `manifests/code-snapshot-2026-10-30.json` | complete file inventory frozen at `1684a2d83e0711fdb947b1a3a43f1c012a84a4e8` |
| `manifests/provenance-manifest-2026-10-30.json` | refreshed concept-file digests at the same commit; the earlier v1 manifest remains intact |

## Current code coverage

`code-register-v1.json` complements the historical concept register. It covers
all tracked files, including frontend, workers, scripts, tests, workflows,
fixtures and extensionless files. It excludes only itself to avoid a self-hash.
No directory, language or file-extension allowlist can silently omit new code.
Untracked local files are not evidence: new files must be added to Git first.
Submodules and unresolved index entries fail; external submodule code cannot be
claimed as locally covered. Symlinks record their target text, without following it.

After staging every intended addition, deletion, rename and mode change:

```bash
python scripts/check_code_provenance.py --write
git add provenance/code-register-v1.json
python scripts/check_code_provenance.py --check
```

Run this after the final edit and include the register in the same PR. The
check reads tracked working-tree bytes and index modes; CI uses a clean checkout.
It refuses added, changed, removed, renamed or mode-changed entries, changed
concept links, a changed root digest, or a missing register. It never writes or
commits from CI. The check runs in `documentation-governance`, which feeds
the required `deterministic-suite-required` status.

Each entry's `git_blob` identifies its exact Git payload. The commit containing
the register binds that inventory to a repository revision; use
`git log --follow -- <path>` for the path's contributor/history record. The live
register has `snapshot: null` to avoid referring to its own containing commit.
Frozen inventories instead carry a full commit SHA and can be reproduced with
`--check-snapshot PATH`, including the concept records from that commit's tree.
To append another inventory, use `--write --snapshot REV --out PATH`; do not
overwrite an earlier snapshot.

Concept links come only from explicit `canonical_spec`, `implementation` and
`tests` paths in `concepts/PROV-xx.yaml`. An empty `concepts` list means the file
is covered by the inventory but has no reviewed concept mapping. In particular,
the new Federation files are covered without inventing a new PROV concept or
extending a prior-art classification. New conceptual claims still require a
record and prior-art review; existing first-recorded dates and classifications
are unchanged. Inventory coverage is not proof of authorship, independent
creation, copyright ownership, or absence of third-party material. Preserve
source acknowledgements and licenses when recording derived work.


## Outbound contributions and attribution boundaries

`OUTBOUND_CONTRIBUTIONS.yaml` records the exact *PR-changed path scope* of
REMORA-associated submissions to other repositories, the observed PR status,
the target's declared licence and the boundary with REMORA Core. This is
different from `EXTERNAL_ADOPTION.yaml`, which records what *external sources*
say about their use of REMORA artifacts. An open PR is not a merged release.

For each contribution, pin the PR URL, changed paths, merge commit if merged,
licence evidence, source revision if actually recorded and relevant research
or external test-vector references. Run
`python scripts/check_outbound_provenance.py --check` in the PR. The offline
gate validates record shape, duplicate IDs/PRs, paths, local concept references
and whether the merge-commit claim matches the status. It **cannot** establish
current remote state, copyright title, independent authorship or whether a
downstream project uses the submission. Verify the remote PR diff and licence
notice manually when recording it. Record later remote status changes as new
reviewed revisions of this ledger, preserving Git history.

External test vectors can reveal an implementation defect without transferring
copyright in independently written REMORA fixes. Credit the test source and its
licence separately from any implemented code. Apache-2.0 in a target repository
does not relicense BUSL-1.1 REMORA Core; historical permissive releases retain
their grants under their own published terms. Empty `concepts` or
`research_sources` means there is *no reviewed direct mapping*, not that
there was no influence or research.

To investigate a specific copying claim: identify the exact files and versions,
compare their bytes/structure, inspect the first recorded commits and earlier
publications, and document the comparison's limitations. Exact hashes prove
content identity, not who authored it. Similarity or shared test outcomes alone
do not establish copying.

## What a record claims

Every record starts with `origin.status: claimed_original_contribution` and
`classification: UNKNOWN`. The ledger records priority and content; it does
not record invention. A classification moves off `UNKNOWN` only through a
review in `PRIOR_ART.yaml` that names the works compared, the overlap found,
the difference found, and the sentence REMORA's claimed contribution is
limited to. The builder refuses a record that upgrades itself without one.

The classification vocabulary is `ORIGINAL_CLAIM`, `PRIOR_ART_OVERLAP`,
`COMPOSITIONAL_CONTRIBUTION`, `IMPLEMENTATION_INNOVATION`, `TERMINOLOGY_ONLY`,
`DERIVED` and `UNKNOWN`. A review that finds the concept in earlier work is
recorded with the same care as one that does not. The register exists so
that REMORA knows what it does not claim before anyone else says so.

## Gates

`python scripts/build_provenance_manifest.py --check` runs in CI. It
validates every record against its schema and checks the first-recorded data
against the register. It checks that every path, capability, claim, suite,
contract, source and event a record names exists. It then rebuilds the
manifest from the recorded snapshot commit and refuses one that no longer
reproduces byte for byte. A new snapshot is written with `--write` after
records or registers change, and with `--release TAG` by the release
workflow.

`python scripts/check_provenance_signatures.py` lists every commit that
touches a protected path and whether GitHub verified its signature. It
fails only once `signatures.enforced_from` in `POLICY.yaml` names a commit;
until then it reports.

## Operator steps outside the repository

These cannot be done from a commit and are not done yet.

1. Sign commits. Enable signed commits for the maintainer account, require
   them on `master` through branch protection, then record the first signed
   commit's sha as `signatures.enforced_from`, in a signed commit.
2. Immutable releases. Turn on immutable releases in the repository
   settings before the next tag, so the tag, the assets and the release
   attestation are locked once published.
3. Zenodo. Enable archiving for the repository in Zenodo before the next
   release, publish the release, then put the concept DOI into
   `CITATION.cff` and the version DOI into the release notes. The ORCID goes
   into `CITATION.cff`, `.zenodo.json` and `AUTHORS.yaml` together.
4. Prior-art review. Maintain dated `PA-REV-xxx` entries in `PRIOR_ART.yaml`
   when a new concept or expanded contribution is claimed. The existing 17
   concepts already have reviews; file inventory does not extend those reviews.
5. Legal review. Have the BUSL Additional Use Grant, the licensor identity,
   contributor ownership and the handling of Federation contributions
   checked by counsel before commercial use grows (`legal/LICENSING.md`).
