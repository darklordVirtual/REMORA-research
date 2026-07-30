# Audit Anchoring Guide: Merkle Checkpoints over REMORA Audit Chains

**Status:** Supporting guide for the in-repo checkpoint layer
(`remora/audit/checkpoint.py`). Describes what is implemented today and,
explicitly, what is not. External publication of checkpoint roots is NOT
implemented (see "Not implemented" below; tracked as REM-025 in
`docs/assurance/remediation_register.yaml` — still open).

## What checkpointing covers

The checkpoint layer in `remora/audit/checkpoint.py` reuses the Merkle
primitives in `remora/audit/merkle.py` and adapts them to the hash chains
REMORA actually produces:

- **Per-tenant envelope chain** — `remora/governance/tenant_chain.py`
  (`ChainEntry.entry_hash`; the REST path finalises these entries in
  `servers/api.py`). Adapter: `tenant_chain_leaves()`.
- **Shadow/replay DecisionEnvelope chain** — `remora/shadow/replay.py`
  (`envelope.audit.hash`, the field `verify_envelope_hash_chain()`
  recomputes). Adapter: `envelope_chain_leaves()`.
- **Plain hex-hash lists** — any ordered list of 64-char hex SHA-256
  digests, which covers `remora/audit/hash_chain.py` entry hashes and any
  future chain. No adapter needed; pass the list directly.

A checkpoint commits to a contiguous span `[seq_start, seq_end]` of a
chain's entry-hash sequence (0-based positions) and links to the previous
checkpoint's root, so the checkpoints form their own chain.

## Checkpoint interval and root format

- **Interval:** the sample generator emits one checkpoint per span of N=8
  entry hashes; the final span may be shorter. The interval is a
  deployment choice (`--interval`), not a protocol constant.
- **Root:** Merkle root over the span's entry hashes using the same
  pairing rule as `remora/audit/merkle.py` — leaves are the entry hashes
  themselves (already SHA-256 digests), pairs combine as
  SHA-256(left + right) over the concatenated hex strings, and odd trees
  duplicate the last node. 64-char lowercase hex.
- **Record fields:** `seq_start`, `seq_end`, `root`,
  `prev_checkpoint_root` (`null` for the first checkpoint of a chain).
- **Signing payload:** `remora-ckpt-v1|<seq_start>|<seq_end>|<root>|<prev>`
  (bytes; `<prev>` is empty for the first checkpoint). This is the stable
  byte string a future external anchor would sign or publish. Local
  HMAC-SHA256 signing is available via `sign_checkpoint()` /
  `verify_checkpoint_signature()`, with the same symmetric-key caveat as
  `remora/audit/merkle.py`: anyone holding the key can forge.

## How to verify

- **Inclusion (span verification):** recompute over the span. Fetch the
  entry hashes for positions `seq_start..seq_end` from the chain, then
  `verify_span(hashes, checkpoint)` — it returns `False` on any length
  mismatch or any tampered hash (a single flipped bit changes the root).
- **Consistency (checkpoint chain):** `verify_checkpoint_chain(checkpoints)`
  checks that each checkpoint's `prev_checkpoint_root` equals the previous
  checkpoint's `root` and that spans are contiguous
  (`seq_start == previous.seq_end + 1`). It reports every break, in the
  same `(ok, problems)` style as the tenant-chain verifier.
- **Chain integrity itself** stays with the existing verifiers:
  `verify_envelope_hash_chain()` in `remora/shadow/replay.py`,
  `TenantAuditChain.verify()` in `remora/governance/tenant_chain.py`, and
  `scripts/verify_audit_anchor.py` for JSONL audit files. Checkpoints add
  a compact commitment on top; they do not replace chain verification.

## Regenerating the sample artifact

The committed sample `artifacts/audit_anchoring/sample_checkpoints.jsonl`
is generated from the demo shadow log
`artifacts/demo/shadow_mode_sample_agent_action_log.jsonl`:

```bash
PYTHONPATH="$(pwd)" python scripts/generate_audit_checkpoints.py
```

The generator is deterministic — no timestamps, no randomness, sorted JSON
keys, LF line endings — so re-running it produces a byte-identical file.
It exits non-zero if the input log is missing or the envelope hash chain
does not verify.

## Threat-model delta (stated honestly)

- The underlying hash chains are **tamper-evident**: an edit to a
  historical entry breaks recomputation from that point on, provided the
  verifier holds trustworthy chain state. An adversary with write access
  to the audit store can still rewrite the whole chain and recompute
  valid hashes.
- Checkpointing with **external publication** of roots upgrades this to
  **tamper-resistant for post-checkpoint history only**: once a root is
  held by an independent, append-only store, rewriting any covered entry
  requires changing the externally held root, which the adversary does
  not control. History written *after* the last published checkpoint has
  no such protection until the next root is published.
- Anchoring does **not** make the writer honest at write time. A
  compromised or lying producer can log a false record, checkpoint it,
  and anchor it; the anchor then faithfully preserves the lie. Anchoring
  constrains retroactive rewriting, nothing else.
- Checkpoints stored on the same system as the chain (as the sample
  artifact is) add **no** protection beyond tamper-evidence — the same
  caveat `remora/audit/merkle.py` states for `export_daily_root()`.
- Do not describe any of this as "tamper-proof"; that property is not
  provided by this system in any configuration.

## Not implemented (slice 2 — REM-025 remains open)

External transparency-log / WORM publishing of checkpoint roots is **not
implemented** in this repository. The following are deployment options a
future slice would integrate, listed here as roadmap only:

- AWS S3 with Object Lock (WORM)
- Azure Blob Storage with Immutability Policy
- Google Cloud Storage with retention policies
- Transparency Logs (Trillian / Sigstore)
- RFC 3161 Trusted Timestamp Authority

Until one of these receives the roots, the checkpoint layer is
preparation for anchoring, not anchoring. REM-025 in
`docs/assurance/remediation_register.yaml` (durable audit integrity with
external anchoring) is NOT closed by this layer.
