-- REMORA Agent Control Plane — D1 audit schema
-- Deploy: wrangler d1 execute remora-audit --file=schema.sql --remote

CREATE TABLE IF NOT EXISTS sessions (
  id          TEXT    PRIMARY KEY,
  created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  ended_at    TEXT,
  user_id     TEXT,
  user_label  TEXT,
  status      TEXT    NOT NULL DEFAULT 'active'  -- active | completed | aborted
);

CREATE TABLE IF NOT EXISTS audit_log (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id        TEXT    NOT NULL,
  ts                TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  tool_called       TEXT    NOT NULL,
  input_hash        TEXT    NOT NULL,   -- SHA-256 of stringified input (privacy-safe)
  input_preview     TEXT,               -- First 120 chars of input for debugging
  output_hash       TEXT,               -- SHA-256 of stringified output
  output_preview    TEXT,               -- First 120 chars of output
  duration_ms       INTEGER,
  upstream_url      TEXT,               -- Which backend was called
  approval_required INTEGER NOT NULL DEFAULT 0,
  approved          INTEGER,            -- NULL = pending, 1 = approved, 0 = rejected
  approved_by       TEXT,
  verdict           TEXT,               -- VERIFIED / SUSPICIOUS / HALLUCINATED / UNKNOWN
  confidence        REAL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_session   ON audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_tool      ON audit_log(tool_called);
CREATE INDEX IF NOT EXISTS idx_audit_ts        ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_verdict   ON audit_log(verdict);

-- ── DecisionEnvelope chain ────────────────────────────────────────────────────
-- audit_log above is a call log: it records that a tool ran, not what was
-- decided or why, and a deleted row leaves no trace. These two tables hold the
-- canonical governance record instead: one DecisionEnvelope v2 per action,
-- hash-chained per tenant, so a removed, reordered or edited decision is
-- detectable by recomputation. Contract matches
-- remora.governance.tenant_chain.compute_entry_hash (REM-034).

CREATE TABLE IF NOT EXISTS decision_envelopes (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id         TEXT    NOT NULL UNIQUE,
  tenant_id          TEXT    NOT NULL,
  session_id         TEXT    NOT NULL,
  sequence_no        INTEGER NOT NULL,
  created_at         TEXT    NOT NULL,
  -- The exact canonical JSON string that was hashed. Stored verbatim so
  -- verifiers hash these bytes rather than a re-serialisation, which would
  -- otherwise drift between languages.
  envelope_canonical TEXT    NOT NULL,
  previous_hash      TEXT    NOT NULL,
  entry_hash         TEXT    NOT NULL,
  -- HMAC-SHA256 over entry_hash when ENVELOPE_SIGNING_KEY is set. An empty
  -- string means unsigned; verification reports it rather than passing it.
  signature          TEXT    NOT NULL DEFAULT '',
  audit_id           INTEGER,
  -- The fork guard: two writers racing on the same head compute the same
  -- sequence number, and the loser's whole batch rolls back on this constraint.
  UNIQUE (tenant_id, sequence_no)
);

CREATE INDEX IF NOT EXISTS idx_envelope_tenant_seq ON decision_envelopes(tenant_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_envelope_session    ON decision_envelopes(session_id);
CREATE INDEX IF NOT EXISTS idx_envelope_created    ON decision_envelopes(created_at);

-- ── First-class approvals (no self-approval) ─────────────────────────────────
-- Replaces approval-by-audit_log-flag. Every approval is an immutable record
-- bound to the exact proposal, tool-call hash, ToolSpec identity and policy
-- identity, with expiry and single-use consumption. audit_log.approved /
-- approved_by remain as display-only mirrors; authorization reads ONLY these
-- tables.

CREATE TABLE IF NOT EXISTS proposal_principals (
  audit_id   INTEGER PRIMARY KEY,          -- audit_log.id of the proposal
  tenant_id  TEXT    NOT NULL,
  principal  TEXT    NOT NULL,             -- credential-derived requester identity
  created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (audit_id) REFERENCES audit_log(id)
);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id         TEXT    PRIMARY KEY,
  tenant_id           TEXT    NOT NULL,
  proposal_id         INTEGER NOT NULL,
  requester_principal TEXT    NOT NULL,
  reviewer_principal  TEXT    NOT NULL,
  reviewer_roles      TEXT    NOT NULL,    -- JSON array
  tool_call_hash      TEXT    NOT NULL,
  toolspec_hash       TEXT    NOT NULL,
  toolspec_version    TEXT    NOT NULL,
  policy_bundle_hash  TEXT    NOT NULL,
  issued_at           TEXT    NOT NULL,
  expires_at          TEXT    NOT NULL,
  decision            TEXT    NOT NULL,    -- approved | rejected
  reason_code         TEXT    NOT NULL,
  signature           TEXT    NOT NULL DEFAULT '',
  consumed_at         TEXT,                -- NULL until single-use consumption
  FOREIGN KEY (proposal_id) REFERENCES audit_log(id)
);

CREATE INDEX IF NOT EXISTS idx_approvals_proposal ON approvals(proposal_id);
CREATE INDEX IF NOT EXISTS idx_approvals_tenant   ON approvals(tenant_id, issued_at);

CREATE TABLE IF NOT EXISTS envelope_chain_head (
  tenant_id     TEXT    PRIMARY KEY,
  head_hash     TEXT    NOT NULL,
  head_sequence INTEGER NOT NULL
);
