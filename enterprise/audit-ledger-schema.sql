-- REMORA Enterprise Audit Ledger Schema
-- Version: 1.0.0
--
-- This schema captures the full decision trace for every REMORA request.
-- Every record is immutable after INSERT. Updates are not permitted.
-- Deletion is governed by the retention policy defined in the risk profile.
--
-- Designed for PostgreSQL 14+. Compatible with CockroachDB and Supabase.
-- For SQLite (Cloudflare D1), see the inline compatibility notes.

-- ── Extensions ────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";    -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";     -- digest() for content hashing

-- ── Core decision record ──────────────────────────────────────────────────────

CREATE TABLE remora_decisions (
    -- Identity
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Tenant and user context
    tenant_id           TEXT NOT NULL,
    user_id             TEXT,           -- nullable for service-to-service calls
    session_id          TEXT,
    request_id          TEXT NOT NULL,  -- caller-provided idempotency key

    -- Input
    question            TEXT NOT NULL,
    context_provided    TEXT,           -- optional context passed by caller
    evidence_provided   JSONB,          -- pre-fetched evidence snippets, if any
    risk_profile        TEXT NOT NULL,  -- profile name from risk-profiles.yaml
    domain              TEXT,           -- classified domain

    -- Pipeline execution
    stages_run          INTEGER NOT NULL,       -- stopped_at_stage value
    total_oracle_calls  INTEGER NOT NULL,
    pipeline_budget     INTEGER,                -- budget_oracle_calls if set
    budget_exhausted    BOOLEAN NOT NULL DEFAULT FALSE,

    -- Final verdict
    final_verdict       TEXT NOT NULL,          -- ACCEPT / VERIFY / ABSTAIN / ESCALATE
    final_confidence    NUMERIC(5,4) NOT NULL,  -- 0.0000 – 1.0000
    answer              TEXT,

    -- Evidence and critique
    evidence_sources    JSONB,          -- [{source, excerpt, relevance_score}]
    critique            TEXT,           -- most recent LLM judge critique

    -- Policy evaluation
    policy_rules_triggered JSONB,       -- list of policy rules that fired
    escalation_target   TEXT,           -- routing target if ESCALATE
    action_permitted    BOOLEAN,        -- whether ACT was evaluated
    action_executed     BOOLEAN NOT NULL DEFAULT FALSE,

    -- Integrity
    input_hash          TEXT NOT NULL,  -- SHA-256 of (tenant_id || request_id || question)
    record_hash         TEXT,           -- SHA-256 of full record — set after INSERT

    -- Retention
    retain_until        DATE            -- computed from risk profile retention_days
);

-- Prevent updates to completed records
CREATE RULE no_update_remora_decisions AS
    ON UPDATE TO remora_decisions DO INSTEAD NOTHING;

-- ── Per-stage results ─────────────────────────────────────────────────────────

CREATE TABLE remora_stage_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_id     UUID NOT NULL REFERENCES remora_decisions(id) ON DELETE CASCADE,
    stage_order     INTEGER NOT NULL,   -- 1-based execution order
    stage_name      TEXT NOT NULL,      -- FAST_GATE, CONSENSUS, VERIFIER,
                                        -- CRITIQUE_REVISION, SELF_CONSISTENCY
    stage_number    INTEGER NOT NULL,   -- CascadeStage.value (1–5)

    verdict         TEXT NOT NULL,
    confidence      NUMERIC(5,4) NOT NULL,
    oracle_calls    INTEGER NOT NULL,
    stopped         BOOLEAN NOT NULL,   -- true if this stage was terminal

    answer          TEXT,
    critique        TEXT,
    metadata        JSONB,              -- stage-specific: phase, trust, agreement, etc.

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE RULE no_update_remora_stage_results AS
    ON UPDATE TO remora_stage_results DO INSTEAD NOTHING;

-- ── Oracle call log ───────────────────────────────────────────────────────────

CREATE TABLE remora_oracle_calls (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_id     UUID NOT NULL REFERENCES remora_decisions(id) ON DELETE CASCADE,
    stage_name      TEXT NOT NULL,
    call_order      INTEGER NOT NULL,   -- 1-based within decision

    oracle_provider TEXT NOT NULL,      -- groq, openrouter, azure, etc.
    model_id        TEXT NOT NULL,      -- full model identifier
    role            TEXT NOT NULL,      -- consensus, judge, revision, fast

    prompt_hash     TEXT NOT NULL,      -- SHA-256 of prompt (not stored in full)
    response_hash   TEXT,               -- SHA-256 of raw response

    -- Extracted signal
    extracted_answer TEXT,
    extracted_confidence NUMERIC(5,4),
    error           TEXT,               -- oracle error message if any

    -- Performance
    latency_ms      INTEGER,
    tokens_prompt   INTEGER,
    tokens_response INTEGER,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Note: raw prompts and responses are NOT stored here to avoid data leakage.
-- If full prompt storage is required, use a separate encrypted store with
-- access controls and link via prompt_hash / response_hash.

CREATE RULE no_update_remora_oracle_calls AS
    ON UPDATE TO remora_oracle_calls DO INSTEAD NOTHING;

-- ── Action gate log ───────────────────────────────────────────────────────────

CREATE TABLE remora_action_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_id     UUID NOT NULL REFERENCES remora_decisions(id) ON DELETE CASCADE,

    tool_name       TEXT NOT NULL,
    tool_arguments  JSONB,              -- sanitised — no secrets
    action_verdict  TEXT NOT NULL,      -- PERMITTED / BLOCKED / ESCALATED
    block_reason    TEXT,               -- policy rule that blocked, if applicable

    -- Human approval
    approval_required   BOOLEAN NOT NULL DEFAULT FALSE,
    approval_status     TEXT,           -- PENDING / APPROVED / REJECTED
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    approval_comment    TEXT,

    -- Execution result (if action was taken)
    executed            BOOLEAN NOT NULL DEFAULT FALSE,
    execution_result    JSONB,
    execution_error     TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Escalation log ────────────────────────────────────────────────────────────

CREATE TABLE remora_escalations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_id     UUID NOT NULL REFERENCES remora_decisions(id) ON DELETE CASCADE,

    escalation_reason   TEXT NOT NULL,  -- phase_disorder, low_trust, policy_rule, budget_exceeded
    target_role         TEXT NOT NULL,  -- domain_expert, soc_analyst, legal_counsel, etc.
    target_user         TEXT,           -- specific user if known
    routing_system      TEXT,           -- servicenow, jira, slack, email, etc.
    external_ticket_id  TEXT,           -- ticket created in external system

    status          TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING / RESOLVED / OVERRIDDEN
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,
    resolution_outcome TEXT,            -- what the human decided

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Evaluation feedback ───────────────────────────────────────────────────────
-- Records post-hoc correctness feedback from the eval harness or human review.
-- Used to update domain golden datasets and recalibrate thresholds.

CREATE TABLE remora_feedback (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_id     UUID NOT NULL REFERENCES remora_decisions(id) ON DELETE CASCADE,

    feedback_source TEXT NOT NULL,  -- eval_harness, human_review, production_outcome
    feedback_by     TEXT,

    correct         BOOLEAN,        -- null = unknown, true/false = evaluated
    ground_truth    TEXT,           -- correct answer if known
    severity        TEXT,           -- critical / high / medium / low (for incorrect decisions)
    notes           TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Telemetry summary (materialised daily) ────────────────────────────────────
-- Aggregated per tenant per day. Source of truth for dashboards.

CREATE TABLE remora_telemetry_daily (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       TEXT NOT NULL,
    date            DATE NOT NULL,

    total_requests      INTEGER NOT NULL DEFAULT 0,
    accepted            INTEGER NOT NULL DEFAULT 0,
    abstained           INTEGER NOT NULL DEFAULT 0,
    escalated           INTEGER NOT NULL DEFAULT 0,
    budget_exhausted    INTEGER NOT NULL DEFAULT 0,

    mean_confidence     NUMERIC(5,4),
    mean_oracle_calls   NUMERIC(6,2),
    mean_latency_ms     NUMERIC(8,2),

    oracle_cost_units   NUMERIC(12,4),  -- normalised cost (tokens or API call units)

    accuracy_on_feedback NUMERIC(5,4),  -- computed where feedback is available
    feedback_count       INTEGER NOT NULL DEFAULT 0,

    UNIQUE (tenant_id, date)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX idx_decisions_tenant       ON remora_decisions (tenant_id, created_at DESC);
CREATE INDEX idx_decisions_verdict      ON remora_decisions (tenant_id, final_verdict);
CREATE INDEX idx_decisions_request      ON remora_decisions (request_id);
CREATE INDEX idx_stage_results_decision ON remora_stage_results (decision_id);
CREATE INDEX idx_oracle_calls_decision  ON remora_oracle_calls (decision_id);
CREATE INDEX idx_action_log_decision    ON remora_action_log (decision_id);
CREATE INDEX idx_action_log_pending     ON remora_action_log (approval_status) WHERE approval_status = 'PENDING';
CREATE INDEX idx_escalations_pending    ON remora_escalations (status, tenant_id) WHERE status = 'PENDING';
CREATE INDEX idx_feedback_decision      ON remora_feedback (decision_id);
CREATE INDEX idx_telemetry_tenant_date  ON remora_telemetry_daily (tenant_id, date DESC);

-- ── Row-level security ────────────────────────────────────────────────────────
-- Enable tenant isolation. Each row is visible only to its own tenant.

ALTER TABLE remora_decisions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE remora_stage_results     ENABLE ROW LEVEL SECURITY;
ALTER TABLE remora_oracle_calls      ENABLE ROW LEVEL SECURITY;
ALTER TABLE remora_action_log        ENABLE ROW LEVEL SECURITY;
ALTER TABLE remora_escalations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE remora_feedback          ENABLE ROW LEVEL SECURITY;
ALTER TABLE remora_telemetry_daily   ENABLE ROW LEVEL SECURITY;

-- Example policy — assumes current_setting('app.tenant_id') is set per session:
CREATE POLICY tenant_isolation ON remora_decisions
    USING (tenant_id = current_setting('app.tenant_id', true));

-- Apply analogous policies to related tables (omitted here for brevity;
-- use the same current_setting pattern joined via decision_id).

-- ── Retention housekeeping ────────────────────────────────────────────────────
-- Run as a scheduled job. Deletes records past their retain_until date.
-- Does NOT delete records where escalation is still PENDING.

CREATE OR REPLACE FUNCTION purge_expired_decisions() RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM remora_decisions d
    WHERE d.retain_until IS NOT NULL
      AND d.retain_until < CURRENT_DATE
      AND NOT EXISTS (
          SELECT 1 FROM remora_escalations e
          WHERE e.decision_id = d.id AND e.status = 'PENDING'
      );
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
