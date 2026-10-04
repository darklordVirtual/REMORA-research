# Provenance

How this repository records when its ideas and code first appeared, and how to check whether code elsewhere shares its structure.
It complements [COPYRIGHT.md](COPYRIGHT.md), [LICENSING.md](LICENSING.md) and [TRADEMARKS.md](TRADEMARKS.md).

## What already records priority

- Every commit and pull request on GitHub carries a server-side timestamp that the author cannot backdate.
- Most recent commits are signed and show as Verified on GitHub. Older history is unsigned, so its dates rest on GitHub's records alone.
- Releases and tags freeze named states, for example `v0.11.0` (2026-08-25).
- The code is source-available under BUSL-1.1 with a separate commercial license. Copying it outside those terms is a license question, whatever the copy looks like.

## The provenance register

`docs/assurance/provenance_register_v1.json` is built by `scripts/provenance_register.py` from `docs/assurance/provenance_concepts_v1.yaml` and git history alone.

| Part | What it records |
|---|---|
| Concepts | seventeen concepts, each with the invariant it stands for and the first commit that introduced each identifying term as its own token, with author date, committer date, signature status and up to eight paths |
| Markers | twelve coined identifiers (`PolicyDecisionToken`, `ExecutionLease`, `GovernedToolDispatcher`, `canonical_tool_call_hash`, `NonceLedger`, `CustodyViolation`, `assert_custody_split`, `REMORA_EXECUTION_DOMAIN_ROLE`, `toolspec_changed_between_assess_and_dispatch`, `task_identity_required`, `authority_effect_separation`, `runtime_capability_surface_completeness`) |
| Fingerprints | twelve modules, winnowing fingerprints of the normalised token stream at one pinned commit (Schleimer, Wilkerson and Aiken, 2003, the method behind MOSS) |
| Digest | `register_sha256`, a digest of the whole register |

A term counts only as its own token. The earlier string `regate` matched inside `aggregate` and is not a term. Fresh re-gate is dated from `fresh re-gate` alone.
Identifiers become `V`, strings `S` and numbers `N` before hashing. Renaming classes and variables, rewording comments or reformatting therefore does not change the fingerprints.
The register is taken from a pinned snapshot commit, so it reproduces byte for byte and does not drift as the code changes. A test rebuilds it from git history. Code added after that snapshot is not in the fingerprints until a new snapshot is appended.

## The ledger

`provenance/` joins each concept in the register to the rest of the record.
That record names the documents, code and tests that express the concept
and the conformance suites and interop contracts that test it. It also names
the claims and capabilities it relates to and what external sources document
about using it. Each record keeps the
register's `PROV-xx` id and first-recorded commit, starts as
`claimed_original_contribution` with classification `UNKNOWN`, and can move
off `UNKNOWN` only through a dated prior-art review in
`provenance/PRIOR_ART.yaml`. `provenance/manifests/provenance-manifest-v1.json`
digests every expressing file and register from one snapshot commit, and CI
refuses a manifest that no longer reproduces. `provenance/README.md` lists
the files and the operator steps that remain outside the repository.

## Comparing other code

```bash
git clone <other repository> /tmp/other
python scripts/provenance_register.py --compare /tmp/other
```

The command exits 1 if it flags an overlap, and 0 otherwise. A flag is a reason to read both histories. It is not a finding that anyone copied anything, and it does not replace the license. Commercial use of REMORA requires a written commercial license from the Licensor. See [LICENSING.md](LICENSING.md). Nothing in this register stops a person from copying the files.

Three signals are reported:

| Signal | Flag |
|---|---|
| Share of one module's fingerprints in the single most similar Python file | 25 % or more |
| Share covered by the eight Python files that match that module best | 50 % or more |
| Coined identifiers found as their own tokens | two or more |

The thresholds are calibrated, not guessed. Measured on 2026-10-02 against the register at snapshot `0b595b8`:

| Compared with | Result |
|---|---|
| a copy of `remora/enforcement/lease.py` with every identifier renamed and every comment and string rewritten | above 90 % in one file |
| that same module split into one renamed file per method | under 25 % in one file, and at least 50 % across eight files |
| unrelated code from this repository (same author, same idioms) | 14 % in one file |
| six third-party packages (fastapi, pydantic, starlette, httpx, PyJWT, cryptography) | 11.2 % in one file, 34.4 % across eight files, no coined identifier |

The conformance adapter contracts are not fingerprinted. One of them shared 27 % of its fingerprints with a single pydantic file, which is above the one-file flag, so including it would accuse ordinary Python. The "anywhere" share pools every file and grows with the size of the other tree (42 % against pydantic on the earlier ten-module register). Read the one-file share and the eight-file share, not that pool.

## What a match does and does not show

A flagged share shows that two pieces of code share structure, or that coined identifiers survived. It does not show who wrote first or whether one was derived from the other.
The dated records settle priority, and the other side's own history has to be read as well.
Shared ideas are not code. Independent work on the same problem often converges on similar architecture, and an architectural resemblance is not, by itself, a copy. The distinctive REMORA property is the chain recorded as PROV-17. An intention is not an effect. The grant is bound to one call and consumed once. A changed ToolSpec is refused. The signer does not perform the effect, and delegated authority does not widen.
The register names no other project or person. A suspected infringement is a matter for legal advice, not for a public accusation.

## Interoperability

Nothing in the register changes code, identifiers, schemas, test vectors or conformance artifacts. Partners integrating with REMORA see no difference, and no test depends on anything but the register itself.

## Not done yet

These would strengthen the record further. Each is a deliberate, separate step:

- Third-party timestamps: a Zenodo DOI per release (issue #390), and an OpenTimestamps proof of each `register_sha256`.
- Signed commits everywhere: branch protection that requires signed commits, so all future history is Verified. `provenance/POLICY.yaml` carries the gate; it is armed by recording the first signed commit in `signatures.enforced_from`.
- A new register snapshot at each release tag, appended to the record rather than replacing it. The release workflow now writes a provenance manifest per tag; the register snapshot itself is still appended by hand.
- A prior-art review per concept, recorded in `provenance/PRIOR_ART.yaml`. Until one exists every concept is classified `UNKNOWN`.
