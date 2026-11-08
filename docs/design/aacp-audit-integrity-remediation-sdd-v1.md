# AACP audit-integrity remediation (X-01, X-02, X-04) - SDD v1

| Metadata | Value |
| --- | --- |
| Document ID | SDD-RMR-AACP-X-2026-11-08 |
| Status | IMPLEMENTED on branch `fix/aacp-x01-x02-x04`; not merged, no independent review |
| Date | 2026-11-08 |
| Baseline | dev `06c2f8f038d9d24668158ce24cbd444e89fd306a` (the revision AACP assessed) |
| Source of findings | agent-authority-conformance PR #28: `reports/remora-06c2f8f/REPORT.md`, `docs/REMORA-CONTROL-INSPECTION.md` |
| Change class | Audit and evidence integrity; no decision, token, lease or dispatch path changes |

## 1. Scope

AACP's control run against the baseline reproduced three defects outside its
A-G properties, each with a repair that made its probe stop observing:

| Control | Where | Defect |
| :--- | :--- | :--- |
| AACP-X-04 | `remora/adapters/audit/jsonl.py` | every reloaded JSONL audit log fails `verify()` |
| AACP-X-01 | `remora/governance/tenant_chain.py` | deleting the newest SQLite chain entries leaves a chain that verifies |
| AACP-X-02 | `remora/assurance/merkle.py` | `[a,b,c]` and `[a,b,c,c]` share a root; an internal node verifies as a leaf |

This SDD fixes the three in REMORA and adds Sigstore provenance to the test
attestation, which AACP recorded as an observation, not a finding. It does
not touch `PostgresTenantChain`, `remora/audit/merkle.py` or the AACP
historical binding, report and results, which stay as published.

## 2. F1: JSONL audit log after reload (AACP-X-04)

### 2.1 Root cause

`append()` hashed the caller's metadata with `oracle_count`, `verdict` and
`policy_version` merged over it, and wrote the caller's metadata with those
three fields as separate top-level keys. `_load_existing_chain()` rebuilt
each `HashChainEntry` from the written `metadata` alone, so the recomputed
hash never matched. The format has not changed since the initial code tree
(`13147691`), so every log on disk has the same layout.

Because every reloaded log failed, a failed check said nothing: tampering and
a restart looked the same. Until this fix, a failed JSONL verification is not
evidence of tampering.

### 2.2 Invariants

- J1. One rule builds the hashed metadata, for writing and for reloading:
  `hashed_metadata(caller_metadata, oracle_count, verdict, policy_version)`,
  caller keys first and the three decision fields over them.
- J2. The on-disk record format is unchanged. A log written before the fix
  verifies without being rewritten (fixture `tests/security/fixtures/jsonl_audit_06c2f8f.jsonl`, written by the baseline code).
- J3. An edited, reordered or removed record (middle or first) fails
  `verify()`. The first record must have `previous_hash` null.
- J4. A record that is not JSON, not an object, lacks a required field or has
  non-object metadata is listed in `load_problems` with its line number. The
  log then never verifies, and `append()` raises `JSONLAuditIntegrityError`
  instead of extending it. Nothing repairs or rewrites the file.
- J5. A hash chain cannot see its own tail removed. `verify()` is local
  consistency; `verify(expected_head=...)` with a head from `head()` held
  elsewhere detects truncation.

### 2.3 Acceptance

`tests/security/test_aacp_x04_jsonl_reload.py`: three appends verify after
reload; the baseline fixture verifies; each edited field, a swap, a removed
middle or first record fails; a removed last record verifies locally and fails
against the saved head; truncated JSON, each missing field, a non-object
record and non-object metadata fail without rewriting the file.

## 3. F2: SQLite tenant chain head (AACP-X-01)

### 3.1 Root cause

`PostgresTenantChain` keeps `tenant_chain_head` and exposes `stored_head()`;
`_verify_generic` compares it with the last entry. `SQLiteTenantChain`, the
single-node durable backend selected by `REMORA_CHAIN_DB`, had no head table,
so a prefix of the chain was a valid chain.

### 3.2 Invariants

- S1. `tenant_chain_head(tenant_id, head_hash, head_sequence, head_origin, baseline_sequence)` is written in the same `BEGIN IMMEDIATE` transaction
  as the entry it names. A failure between the two rolls both back.
- S2. `verify()` reports `stored_head_mismatch` when the head is not the last
  entry, `stored_head_missing` when a tenant has entries and no head row, and
  `stored_head_malformed` when the row fails its type checks.
- S3. The next entry links to the stored head, as in Postgres. After a
  truncation the new entry leaves a `sequence_gap_at` and `chain_break_at`
  instead of moving the head over the cut. A missing or malformed head, or
  entries past the head, refuse the append (`ChainHeadInconsistent`); the
  head is never rebuilt from entries.
- S4. Concurrent appends from several connections serialise on the write
  lock and leave one head equal to the last entry.
- S5. `verify_report()` returns `integrity_scope`: `EXTERNALLY_ANCHORED`
  only when an `expected_head` from outside the database was compared, else
  `LOCAL_DATABASE_CONSISTENCY`.

### 3.3 Migration and baseline

The first open of a database without head tracking, in one `BEGIN IMMEDIATE`:

1. creates `tenant_chain_head` and `tenant_chain_schema`;
2. for each tenant with entries, writes a head at its last entry with
   `head_origin = legacy_unanchored_baseline` and `baseline_sequence` = that
   entry's sequence number;
3. records `head_tracking` in `tenant_chain_schema`, so the step never runs
   again (a head deleted later is reported missing, not re-baselined).

The baseline records the history as found. It is not a trusted head and does
not verify that history: entries up to `baseline_sequence` were never
head-tracked, and a truncation before the upgrade cannot be detected from
the file. Hash and link checks still run over them, so an edited legacy entry
still fails. To establish more than local consistency for legacy history, an
operator compares the baselined head with an anchor recorded before the
upgrade (an exported signed root, `remora/audit/merkle.py`
`export_daily_root`) and passes it as `expected_head`. Without that anchor the
history is reported as a legacy baseline, never as verified.

### 3.4 Limit

Anyone who can rewrite the database can delete entries and rewind the head
together; the store then verifies locally. The test
`test_head_and_entries_rewritten_together_needs_an_external_anchor` asserts
that limit and that an external `expected_head` detects it. Postgres has the
same limit.

### 3.5 Acceptance

`tests/security/test_aacp_x01_sqlite_chain_head.py`: one and several deleted
newest entries, all entries deleted, restart persistence, per-tenant heads,
append after truncation, missing, malformed and outdated heads, an
interrupted append and `append_once`, 6 threads x 15 appends, the
rewritten-together limit, migration of a pre-fix database (baseline origin,
history unchanged, truncation after migration detected, migration once,
concurrent first open). `tests/test_governance_review_round2.py` asserted
the defect as a "known limit"; it now asserts the stored head detects it.

## 4. F3: assurance Merkle tree (AACP-X-02)

### 4.1 Root cause

`remora/assurance/merkle.py` paired an odd node with a copy of itself and
hashed leaves (`SHA-256(leaf)`) and nodes (`SHA-256(hex(L) || hex(R))`) in one
domain. Different leaf sets could then share a root without a SHA-256
collision. `remora/audit/merkle.py` was already correct by default (its v2,
AACP P-X-02c not observed) and is left unchanged.

### 4.2 Construction v2

- Leaf: `SHA-256(0x00 || leaf_bytes)`. Node: `SHA-256(0x01 || L || R)` over
  raw 32-byte digests. An odd node is promoted unchanged.
- Hex strings remain the external representation.
- A v2 `MerkleProof` carries `version` and `leaf_count`. The verifier derives
  the sibling sides from `(leaf_index, leaf_count)` and rejects a proof whose
  sides differ, so the index is bound.

### 4.3 Versioning and migration

| Item | Rule |
| :--- | :--- |
| `build_merkle_tree(items, version=...)` | default `MERKLE_V2`; `MERKLE_V1` only when named |
| `MerkleProof(..., version=..., leaf_count=...)` | new fields with defaults; positional construction still works |
| `verify_inclusion(leaf, proof, root, version=None)` | uses the proof's version; rejects unknown versions, a `version` argument that differs, malformed root, index or siblings, a v2 proof without `leaf_count`, and a path mismatch |
| `AssuranceTrace.signature_standard` | new traces `REMORA-Assurance-Trace-v2`; `REMORA-Assurance-Trace-v1` means the v1 tree |
| `verify_assurance_trace(trace)` | picks the construction from the standard via `merkle_version_for`; unknown standard rejected |

A v1 proof read without a version is checked as v2 and fails: an old root is
never reinterpreted. Historical traces verify when the caller states v1
(fixture `tests/security/fixtures/assurance_merkle_v1_06c2f8f.json`, from the
baseline code). v1 stays ambiguous by construction; a test asserts that, so
nobody mistakes v1 verification for the v2 guarantee. The deprecated
`research_attic/zkp.py` shim now copies the trace's standard instead of
hard-coding v1.

### 4.4 Acceptance

`tests/security/test_aacp_x02_assurance_merkle_v2.py`: `[a,b,c]` vs
`[a,b,c,c]` and the duplicate-last case for 1-11 leaves; node-as-leaf in three
encodings; proofs for 1-17 leaves; tampered leaf, wrong index, wrong count,
extra or missing siblings, eight malformed sibling shapes, non-integer index,
malformed root, unsupported versions, version mismatch; the baseline v1
fixture verifies under v1 only; v1 and v2 traces are told apart, and an
unknown standard is rejected. `tests/test_assurance_merkle.py` asserted the
v1 node rule against the default tree; it now names v1.

## 5. Test attestation provenance

`attestation.yml` uploaded an unsigned `test-attestation.json`. A new `sign`
job, which installs nothing and alone holds `id-token: write`, downloads the
attestation, checks both files against digests the `attest` job emitted
after its commit and `gate: PASS` checks, and signs them with
`actions/attest-build-provenance` (same pin as `release.yml`). A FAIL run
never reaches it. The signature shows which workflow, ref and commit
produced the files. It is the producer's signature, not an independent
review, and it does not show the suite tests the right things.

## 6. Regression sensitivity

Each protection was removed alone and the named tests re-run; every removal
made them fail (exit 1). The script and output are in the PR.

| Mutation | Removes |
| :--- | :--- |
| M-X04-load | metadata reconstruction on reload |
| M-X04-genesis | first-record genesis check |
| M-X04-loadproblems | refusal to verify a log with unreadable records |
| M-X01-headwrite | head update in the append transaction |
| M-X01-nocompare | `stored_head()` (verify has nothing to compare) |
| M-X01-missing | `stored_head_missing` report |
| M-X01-linklast | linking to the stored head after truncation |
| M-X01-rebaseline | run-once migration marker |
| M-X02-default | v2 as default construction |
| M-X02-domain | 0x00 / 0x01 prefixes |
| M-X02-dup | odd-node promotion |
| M-X02-count | path check from `(leaf_index, leaf_count)` |
| M-X02-expectedversion | rejecting a proof of another version |
| M-X02-tracestd | v2 as default trace standard |

## 7. Remaining risks

- R1. Local heads (SQLite and Postgres) do not resist an attacker with write
  access to the whole store. Only an `expected_head` kept elsewhere does, and
  no caller in the execution path supplies one yet.
- R2. Legacy SQLite history before migration is baselined as found;
  truncation before the upgrade is undetectable without a prior anchor.
- R3. JSONL logs have no stored head; tail truncation is detected only with
  an external `expected_head`.
- R4. A JSONL log with an unreadable record refuses appends until an operator
  sets it aside. That is fail-closed by design and can stop a shadow replay
  writing to the same file.
- R5. v1 assurance traces remain ambiguous when verified; their root and
  `leaf_count` must be compared together, as `reporting.py` already records.
- R6. The AACP result for this fix is an author run (`AUTHOR_RUN`), not an
  independent review. NOT_OBSERVED is not PASS.
