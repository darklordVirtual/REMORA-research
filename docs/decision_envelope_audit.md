# DecisionEnvelope Audit Semantics

REMORA emits a `DecisionEnvelope` for every governed decision. The envelope is
the machine-readable audit contract used by the API, adapters, Shadow Mode, and
replay tooling.

## Contract Location

- Runtime dataclasses: `remora/governance/envelope.py`
- Schema contract: `schemas/decision_envelope_schema.yaml`
- Hash-chain replay: `remora/shadow/replay.py`
- Tests: `tests/test_decision_envelope_v2.py`, `tests/test_envelope_hash.py`,
  `tests/test_shadow_replay.py`

## Two Hash Levels

REMORA intentionally uses two related but different hash semantics.

### 1. Compact safety hash

`DecisionEnvelope.envelope_hash()` computes a deterministic SHA-256 hash over
the fields most relevant to the gate decision:

- request id,
- domain,
- action type,
- risk tier,
- proposed action,
- gate outcome,
- policy triggers.

This hash is useful for stable comparisons, compact audit summaries, and tests
that verify deterministic decision identity. It is not a full forensic hash of
every envelope field.

### 2. Full replay hash-chain

Shadow Mode uses a stronger full-payload hash-chain in `remora/shadow/replay.py`.
For every replayed action, REMORA serializes the full envelope payload with the
current hash field set to `null`, prepends the previous envelope hash, and hashes
the result with SHA-256.

That means edits to request metadata, evidence summaries, policy triggers,
follow-up state, reviewer context, or envelope order invalidate the replay
chain. The chain is verified by `verify_envelope_hash_chain()`.

## What This Proves

The current implementation proves deterministic local replay and tamper evidence
for Shadow Mode JSONL outputs. It does not yet provide cryptographic signing,
KMS-backed non-repudiation, timestamp authority, or external notarization.

## Implemented Enterprise Fields (AuditBlock)

The following enterprise fields are present in `AuditBlock` as of schema version 2
and are populated by the API layer via `_finalize_envelope_audit`:

| Field | Type | Populated by | Description |
|---|---|---|---|
| `schema_version` | `str` | API (`"2"`) | explicit envelope schema version for long-term audit compatibility |
| `timestamp_utc` | `str \| None` | API (UTC ISO-8601) | Decision timestamp |
| `tenant_id` | `str \| None` | API (from auth) | Tenant the decision belongs to |
| `actor_identity` | `str \| None` | API (`X-Remora-Actor` header) | Caller/service principal identity |
| `policy_bundle_hash` | `str \| None` | API (`_policy_component_hashes()`) | Composite SHA-256 of active policy bundle |
| `policy_version` | `str` | Policy engine | Semver string from `RemoraDecisionEngine` |
| `hash` | `str \| None` | API (`_finalize_envelope_audit`) | SHA-256 of the compact safety-relevant fields |
| `previous_hash` | `str \| None` | API (tenant hash-chain) | Hash of the previous envelope for this tenant |
| `signature` | `str \| None` | API (HMAC, if `REMORA_ENVELOPE_SIGNING_KEY` set) | HMAC-SHA256 signature of `hash` |

The following fields are present in `AuditBlock` with `None` defaults and must
be set by the deploying organisation's integration layer:

| Field | Type | Description |
|---|---|---|
| `data_classification` | `str \| None` | Data classification of the governed action (e.g. `"confidential"`, `"restricted"`) |
| `retention_policy` | `str \| None` | Retention period for this audit record (e.g. `"7y"`, `"legal_hold"`) |

These fields are present in the schema (non-required, nullable) and survive
`to_dict()` / `from_dict()` roundtrips.

## Remaining Gaps (not yet implemented)

The following are documented as future work and are **not** yet provided by the
reference implementation:

- **Approver identity binding:** human approval records do not yet carry an
  OIDC-bound approver identity. Implementing this requires IdP integration
  in the review workflow (see `enterprise/human-approval-workflow.md`).
- **Tool argument hash / redaction state:** the arguments passed to the tool
  being governed are not hashed or redacted in the current envelope. This is
  needed for environments where tool arguments may contain sensitive data.
- **Detached signature / KMS integration:** the optional HMAC signature via
  `REMORA_ENVELOPE_SIGNING_KEY` is software-only. A production deployment
  requiring non-repudiation at the hardware level should integrate an HSM or
  KMS for signing.
- **External notarization / timestamp authority:** the `timestamp_utc` field
  is set by the API server clock. It does not carry a trusted timestamp from
  an external time-stamp authority (RFC 3161).
