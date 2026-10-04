# Provenance ledger

A machine-readable chain from each original REMORA concept to the documents,
code and tests that express it, to the commit where it first appeared, to the
conformance suites and interop contracts that test it, and to what external
sources document about using it. `legal/PROVENANCE.md` is the canonical
explanation of what such a record does and does not show; this directory is
the record.

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
recorded with the same care as one that does not; the point of the register
is to know what REMORA does not claim before anyone else says so.

## Gates

`python scripts/build_provenance_manifest.py --check` runs in CI. It
validates every record against its schema, checks that the first-recorded
data matches the register, that every path, capability, claim, suite,
contract, source and event a record names exists, and that the committed
manifest reproduces byte for byte from its recorded snapshot commit. A new
snapshot is written with `--write` after records or registers change, and
with `--release TAG` by the release workflow.

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
4. Prior-art review. Record the first `PA-REV-xxx` entries, starting from
   the sources listed in `PRIOR_ART.yaml`.
5. Legal review. Have the BUSL Additional Use Grant, the licensor identity,
   contributor ownership and the handling of Federation contributions
   checked by counsel before commercial use grows (`legal/LICENSING.md`).
