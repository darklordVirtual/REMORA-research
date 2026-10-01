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
| Concepts | for twelve distinctive concepts (DecisionEnvelope, ToolSpec, exact-call binding, fresh re-gate, PolicyDecisionToken, ExecutionLease, GovernedToolDispatcher, the ToolSpec-change refusal, runtime capability surface completeness, non-transitivity of authority, evidence sufficiency, authority/effect separation), the first commit that introduced each identifying term, with author date, committer date and signature status |
| Fingerprints | for ten core modules, winnowing fingerprints of the normalised token stream at one pinned commit (Schleimer, Wilkerson and Aiken, 2003, the method behind MOSS) |
| Digest | `register_sha256`, a digest of the whole register |

Identifiers become `V`, strings `S` and numbers `N` before hashing. Renaming classes and variables, rewording comments or reformatting therefore does not change the fingerprints.
The register is taken from a pinned snapshot commit, so it reproduces byte for byte and does not drift as the code changes. A test rebuilds it from git history.

## Comparing other code

```bash
git clone <other repository> /tmp/other
python scripts/provenance_register.py --compare /tmp/other
```

For each REMORA module the output gives the share of its fingerprints found in the most similar file there. A share of 25 % or more is flagged.
The threshold is calibrated, not guessed:

| Compared with | Highest share in one file |
|---|---|
| a copy of `remora/enforcement/lease.py` with every identifier renamed and every comment and string rewritten | above 90 % |
| unrelated code from this repository (same author, same idioms) | 14 % |
| six third-party packages (fastapi, pydantic, starlette, httpx, PyJWT, cryptography) | 15.8 % at most |

The "anywhere" share pools every file in the other codebase and grows with its size (42 % against pydantic). Read the per-file share, not that one.

## What a match does and does not show

A flagged share shows that two pieces of code share structure. It does not show who wrote first or whether one was derived from the other.
The dated records settle priority, and the other side's own history has to be read as well.
Shared ideas are not code. Independent work on the same problem often converges on similar architecture, and an architectural resemblance is not, by itself, a copy.
The register names no other project or person. A suspected infringement is a matter for legal advice, not for a public accusation.

## Interoperability

Nothing in the register changes code, identifiers, schemas, test vectors or conformance artifacts. Partners integrating with REMORA see no difference, and no test depends on anything but the register itself.

## Not done yet

These would strengthen the record further. Each is a deliberate, separate step:

- Third-party timestamps: a Zenodo DOI per release (issue #390), and an OpenTimestamps proof of each `register_sha256`.
- Signed commits everywhere: branch protection that requires signed commits, so all future history is Verified.
- A new register snapshot at each release tag, appended to the record rather than replacing it.
