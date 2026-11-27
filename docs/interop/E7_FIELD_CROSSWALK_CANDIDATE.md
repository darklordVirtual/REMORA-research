# E7 field crosswalk: REMORA fixture to Probity reader

Status: **producer-side candidate mapping**, not bilateral confirmation. This document describes the frozen `runtime-surface-e7-v0.1` input contract; it does not assert that Probity has confirmed every field mapping or that the Federation boundary-map editors have adopted it.

## Source pins

- Producer fixture: `artifacts/interop/runtime-surface-e7-v0.1/fixtures.json`, SHA-256 `b09b937ad263169682fd0d6175564d084b4a61f5c996adb1237fd2eac31aaccf`.
- Producer claim packet: `artifacts/interop/runtime-surface-e7-v0.1/claim-packet.json`, SHA-256 `6c140d12f66e06aa3ae60e6aec62e38836509a91a32056649520f2bbb8aa2833`.
- Contract: `runtime-surface-e7-v0.1`; frozen package digest `sha256:01dfdb7885bdbb18c025bc013edc28b482b0631ae282aca877bd0953b865e4bf`.
- Consumer run records: [self-service](https://github.com/probityai/agent-evidence-atlas/blob/0e0a986f24dd2994446051db42a3e40692d7fa41/experiments/remora-e7-selfservice-2026-10-08/external-run-record-v1.json), [pip](https://github.com/probityai/agent-evidence-atlas/blob/80f2679f56d4509d4e3b76f8997d633f6d537fe7/experiments/remora-e7-pip-2026-10-09/external-run-record-v1.json), [pip, reader 0.25.0](https://github.com/probityai/probityai.github.io/blob/090d58c8f7ab2bbcb555d9ee8d5ccc8abaa2d7a7/atlas/experiments/remora-e7-pip-0.25.0-2026-10-23/external-run-record-v1.json).
- Where the records live: `probityai/agent-evidence-atlas` is archived and its content moved to `probityai/probityai.github.io` under `atlas/`. The first two links pin commits in the archived repository and are the bytes `artifacts/interop/index.json` records. The copies in the new location differ from them in the `command` field only, where Probity replaced the runner's absolute paths.
- Third run: on 2026-10-23 Probity reran the pip reader from `agent-evidence-vectors==0.25.0` against the same frozen package. The record has SHA-256 `9a04f0a678f96da3970cd17ebe2ad297552e6dcef1f0375003400b4c8c41063d`. It names the same consumed revision, package digest and five input digests as the 0.17.6 record, and the same five case results: one `ESTABLISHED`, two `CONTRADICTED`, two `NOT_ESTABLISHED`. It is a rerun by the same verifier project, not a second verifier. REMORA compared the published records and did not rerun the reader at 0.25.0.

## Candidate field relationships

| REMORA fixture field | Meaning within frozen fixture | Required consumer treatment | Limit |
| --- | --- | --- | --- |
| `runtime_identity` / `expected_runtime_identity` | Identity asserted for the observed runtime and expected subject | Compare exact supplied identities | Does not authenticate an actual runtime |
| `observation_source` | Declared source of observation | Preserve source label in evaluation | Does not prove observer independence |
| `complete` | Bounded fixture premise for observation completeness | `false` cannot establish full observed-set match | Does not prove host-wide capability completeness |
| `governed_tools` | Map of declared tool IDs to ToolSpec hashes | Compare with eligible observed tools | Does not prove that all callable paths are governed |
| `tools[].tool_id` / `tools[].toolspec_hash` | Observed tool identity and declared definition hash | Match ID and hash, preserving null/missing distinction | No equivalence with AgentAvow's aggregate digest is asserted |
| `tools[].registered`, `offered_to_agent`, `callable_at_dispatch` | Observed per-tool reachability predicates | Interpret using the frozen E7 fixture contract | Not an observation of an external production host |
| `path_inventory_complete` / `alternative_effect_paths` | Premises and observations about effect-path exclusivity | An observed alternative path contradicts exclusivity; incomplete inventory cannot establish exclusivity | Does not establish effect custody |
| `expected.claim_result` | Frozen oracle outcome | Compare result without converting verdict vocabularies | Expected answers were available to consumer author |
| `expected.surface_verdict`, `reasons`, `unexpected_tools` | Diagnostic expectations | Keep distinct from claim result | Diagnostics are not additional established claims |
| `expected.claim_id` for effect-path case | Claim identity override for a different proposition | Do not collapse `exclusive_effect_path` into observed-surface matching | Claims are non-transitive |

## Required five-case invariants

1. `valid_reference_surface`: `bounded_observed_surface_matches_governed_set = ESTABLISHED` under supplied complete observation premises.
2. `undeclared_tool_invocation_surface`: `CONTRADICTED`; the extra `shell` tool must not be silently ignored.
3. `runtime_identity_changed`: `NOT_ESTABLISHED`; matching tool sets cannot rescue a mismatched runtime identity.
4. `observation_coverage_incomplete`: `NOT_ESTABLISHED`; incomplete observation must not be treated as proof of absence.
5. `alternative_effect_path_observed`: `exclusive_effect_path = CONTRADICTED`; do not transfer this result to the distinct observed-surface claim.

## Remaining bilateral work

Probity should confirm which consumer fields and code paths implement these relationships. A producer-side mapping is **not** a verified cross-project field mapping. The Federation map's stronger independent-record requirement remains unsatisfied, despite three external reproductions from one verifier project meeting REMORA's narrower independence rule. Neither the fixture nor its reproduction establishes live runtime completeness, execution occurrence, production enforcement, or effect verification.

E8 (AgentAvow static `scan.toolManifestDigest` vs REMORA runtime declared tool set) is a **separate proposed edge**. Do not infer tool-set equivalence, digest equivalence or temporal alignment from E7.
