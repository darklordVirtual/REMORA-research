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
