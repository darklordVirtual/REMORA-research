-- AROMER D1 database schema
-- Created: 2026-06-04

CREATE TABLE IF NOT EXISTS episodes (
  id              TEXT PRIMARY KEY,
  timestamp       TEXT NOT NULL,
  domain          TEXT NOT NULL DEFAULT 'unknown',
  risk_tier       TEXT NOT NULL DEFAULT 'medium',
  action_type     TEXT NOT NULL DEFAULT 'execution',
  phase           TEXT NOT NULL DEFAULT 'critical',
  trust_score     REAL NOT NULL DEFAULT 0.5,
  entropy_h       REAL NOT NULL DEFAULT 0.5,
  dissensus_d     REAL NOT NULL DEFAULT 0.5,
  verdict         TEXT NOT NULL,
  confidence      REAL NOT NULL DEFAULT 0.5,
  rules_triggered TEXT NOT NULL DEFAULT '[]',   -- JSON array
  outcome         TEXT NOT NULL DEFAULT 'pending',
  ground_truth    TEXT NOT NULL DEFAULT 'unknown',
  decision_quality TEXT,
  executed        INTEGER NOT NULL DEFAULT 0,
  hard_block      INTEGER NOT NULL DEFAULT 0,
  review_required INTEGER NOT NULL DEFAULT 0,
  world_update_weight REAL NOT NULL DEFAULT 0.0,
  outcome_severity REAL DEFAULT 0.0,
  outcome_ts      TEXT DEFAULT '',
  critique_score  REAL,
  critique_text   TEXT DEFAULT '',
  meta            TEXT NOT NULL DEFAULT '{}',   -- JSON object
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_episodes_domain     ON episodes(domain);
CREATE INDEX IF NOT EXISTS idx_episodes_outcome    ON episodes(outcome);
CREATE INDEX IF NOT EXISTS idx_episodes_ground_truth ON episodes(ground_truth);
CREATE INDEX IF NOT EXISTS idx_episodes_decision_quality ON episodes(decision_quality);
CREATE INDEX IF NOT EXISTS idx_episodes_timestamp  ON episodes(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_verdict    ON episodes(verdict);

CREATE TABLE IF NOT EXISTS adaptation_cycles (
  id              TEXT PRIMARY KEY,
  timestamp       TEXT NOT NULL,
  domain          TEXT,
  episodes_processed INTEGER NOT NULL DEFAULT 0,
  false_accept_rate  REAL,
  false_block_rate   REAL,
  review_friction    REAL,
  correct_intercept_rate REAL,
  safety_violations  INTEGER DEFAULT 0,
  lambda_before      REAL,
  lambda_after       REAL,
  meta_judge_count   INTEGER DEFAULT 0,
  mean_critique_score REAL,
  replay_score      REAL,
  replay_accuracy   REAL,
  replay_transfer_score REAL,
  replay_cases      INTEGER DEFAULT 0,
  summary            TEXT DEFAULT '{}',
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS world_model_priors (
  domain          TEXT NOT NULL,
  action_type     TEXT NOT NULL,
  risk_tier       TEXT NOT NULL,
  alpha           REAL NOT NULL DEFAULT 1.0,
  beta            REAL NOT NULL DEFAULT 1.0,
  n_observations  REAL NOT NULL DEFAULT 0,
  p_harm          REAL GENERATED ALWAYS AS (alpha / (alpha + beta)) VIRTUAL,
  updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  PRIMARY KEY (domain, action_type, risk_tier)
);

CREATE TABLE IF NOT EXISTS oracle_bandit_state (
  oracle_id       TEXT PRIMARY KEY,
  alpha           REAL NOT NULL DEFAULT 1.0,
  beta            REAL NOT NULL DEFAULT 1.0,
  n_observations  INTEGER NOT NULL DEFAULT 0,
  updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO oracle_bandit_state (oracle_id) VALUES
  ('cf_fast'),
  ('cf_strong'),
  ('cf_diverse');

-- Sprint 1: AII Intelligence Index tracking
CREATE TABLE IF NOT EXISTS intelligence_scores (
  id              TEXT PRIMARY KEY,
  timestamp       TEXT NOT NULL,
  aii             REAL NOT NULL,
  calibration_score REAL,
  friction_score    REAL,
  metajudge_quality REAL,
  transfer_score    REAL,
  stability_score   REAL,
  ece               REAL,
  benign_review_rate REAL,
  false_accept_rate  REAL,
  world_model_active INTEGER DEFAULT 0,
  lora_active        INTEGER DEFAULT 0,
  n_episodes         INTEGER,
  n_high_confidence  INTEGER,
  notes              TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_intelligence_timestamp
  ON intelligence_scores(timestamp DESC);
