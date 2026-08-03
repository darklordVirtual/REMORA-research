/**
 * REMORA Agent Control Plane — Cloudflare Worker
 *
 * This Worker acts as the secure execution layer between Claude (the reasoning
 * engine) and REMORA infrastructure (D1, R2, Worker upstreams). Claude calls
 * tools via HTTP — this Worker enforces egress policy, injects secrets, logs
 * every action to D1, and routes to approved upstreams only.
 *
 * Architecture
 * ────────────
 *   Claude Desktop / Claude API
 *     │  (MCP or HTTP tool calls)
 *     ▼
 *   [agent-control Worker]  ← YOU ARE HERE
 *     │  Egress policy enforced
 *     │  Secrets injected (never exposed to Claude)
 *     │  Every call logged to D1 audit_log
 *     ├──► REMORA Worker       (multi-oracle consensus)
 *     ├──► RAG Oracle Worker   (knowledge retrieval)
 *     ├──► Law Search Worker   (DCE / Norwegian law)
 *     └──► R2 / D1             (artifacts, audit)
 *
 * Endpoints
 * ─────────
 *   GET  /tools              Tool catalog (for Claude discovery)
 *   POST /execute            Execute a tool by name
 *   POST /sessions           Start a new agent session
 *   DELETE /sessions/:id     End a session
 *   GET  /audit              Query audit log (admin only)
 *   GET  /envelopes          List stored DecisionEnvelopes (admin only)
 *   GET  /envelopes/verify   Recompute the tenant envelope hash chain (admin only)
 *   GET  /envelopes/:id      Fetch one DecisionEnvelope by request_id (admin only)
 *   GET  /status             Health check
 *   GET  /search             Repo search + snippets
 *
 * Security model
 * ──────────────
 *   - Bearer token required on all write endpoints (CONTROL_SECRET)
 *   - Claude never sees API keys — they are injected by this Worker
 *   - All outbound requests checked against EGRESS_ALLOWLIST
 *   - Writes to R2 require explicit approval flag from caller
 *   - Sensitive tool calls marked approval_required in audit_log
 *   - Every /execute writes a hash-chained DecisionEnvelope v2 (see
 *     src/envelope.ts); a failed envelope write fails the request rather than
 *     returning a clean 200 on an unrecorded action
 *
 * Deploy
 * ──────
 *   cd workers/agent-control
 *   npm run db:init:remote         # create D1 tables (incl. envelope chain)
 *   wrangler secret put CONTROL_SECRET
 *   wrangler secret put ENVELOPE_SIGNING_KEY   # optional; signs the chain
 *   wrangler secret put REMORA_SECRET
 *   wrangler secret put RAG_SECRET
 *   npm run deploy
 *
 * Upgrading an existing deployment: schema.sql is idempotent
 * (CREATE TABLE IF NOT EXISTS), so re-running db:init:remote adds the
 * decision_envelopes and envelope_chain_head tables without touching
 * existing audit_log rows. Envelopes begin at sequence 0 from that point;
 * calls made before the upgrade have no envelope and must not be presented
 * as if they did.
 */

import { buildCodegraphPayload } from "./codegraph";
import {
  appendEnvelope,
  buildEnvelope,
  canonicalToolCallHash,
  verifyChain,
  type ChainRow,
} from "./envelope";

// ── Types ──────────────────────────────────────────────────────────────────────

interface Env {
  // Bindings
  AUDIT_DB:       D1Database;
  ARTIFACTS:      R2Bucket;
  SESSIONS:       KVNamespace;
  REMORA_SERVICE: Fetcher;   // Service binding: go-star-remora
  LAW_SERVICE:    Fetcher;   // Service binding: remora-law-search

  // Vars (display URLs in /status; approval routing list)
  REMORA_WORKER_URL:        string;
  RAG_ORACLE_URL:           string;
  LAW_SEARCH_URL:           string;
  APPROVAL_REQUIRED_TOOLS:  string;

  // Governance record context. TENANT_ID scopes the envelope hash chain;
  // TARGET_ENVIRONMENT is recorded verbatim in every envelope.
  TENANT_ID?:          string;
  TARGET_ENVIRONMENT?: string;

  // Secrets — required in production; the auth guard fails closed if missing.
  CONTROL_SECRET?: string;
  // Optional HMAC key over each envelope entry_hash. Unset means unsigned:
  // the chain still detects edits, but not an attacker who can rewrite whole
  // rows including their hashes. /envelopes/verify reports which case applies.
  ENVELOPE_SIGNING_KEY?: string;
}

interface ToolInput {
  tool:       string;
  input:      Record<string, unknown>;
  session_id: string;
  user_id?:   string;
}

interface ToolResult {
  tool:         string;
  success:      boolean;
  output:       unknown;
  verdict?:     string;
  confidence?:  number;
  duration_ms:  number;
  session_id:   string;
  audit_id?:    number;
  approval_required?: boolean;
  /** Envelope identity: lets the caller fetch and verify its own governance record. */
  request_id?:        string;
  envelope_hash?:     string;
  envelope_sequence?: number;
}

// ── Tool catalog ───────────────────────────────────────────────────────────────

const TOOL_CATALOG = [
  {
    name: "remora_verify_claim",
    description:
      "Verify a factual claim using REMORA multi-oracle consensus. " +
      "Returns a calibrated verdict (VERIFIED / SUSPICIOUS / LIKELY_HALLUCINATED / UNCERTAIN) " +
      "with confidence score. Best for: legal claims, technical assertions, citation checks.",
    parameters: {
      type: "object",
      properties: {
        claim:   { type: "string",  description: "The specific claim to verify" },
        context: { type: "string",  description: "Supporting context text (optional)" },
        domain:  { type: "string",  description: "Domain hint: law | medical | technical | general" },
      },
      required: ["claim"],
    },
  },
  {
    name: "dce_search_law",
    description:
      "Search the Norwegian law knowledge base (DCE / Document Compliance Engine). " +
      "Returns authoritative statutory text and case law relevant to the query. " +
      "Use for: Norwegian regulation lookups, compliance checks, GDPR/AML/AVL questions.",
    parameters: {
      type: "object",
      properties: {
        query:    { type: "string",  description: "Natural language legal query in Norwegian or English" },
        top_k:    { type: "number",  description: "Number of passages to return (default: 5, max: 10)" },
        domain:   { type: "string",  description: "Law domain filter: aml | gdpr | husleie | forvaltning | strafferett" },
      },
      required: ["query"],
    },
  },
  {
    name: "store_artifact",
    description:
      "Store a document, report, or evidence artifact to R2. " +
      "REQUIRES APPROVAL — first submit with no audit_id to get one, then approve via audit_decision. " +
      "Returns the artifact key for future retrieval.",
    parameters: {
      type: "object",
      properties: {
        key:         { type: "string", description: "Storage key / filename (e.g. 'reports/bygg-x-2026-05.md')" },
        content:     { type: "string", description: "Text content to store" },
        content_type:{ type: "string", description: "MIME type (default: text/markdown)" },
        audit_id:    { type: "number",description: "The approved audit_id from the human review" },
      },
      required: ["key", "content"],
    },
  },
  {
    name: "audit_decision",
    description:
      "Record a human decision or approval in the audit log. Use to mark that " +
      "a specific action was reviewed, approved, or rejected by a human operator. " +
      "Creates an immutable audit record.",
    parameters: {
      type: "object",
      properties: {
        audit_id:  { type: "number",  description: "The audit_log row ID to update" },
        approved:  { type: "boolean", description: "True = approved, False = rejected" },
        approved_by:{ type: "string", description: "Name or ID of the approving person" },
        note:      { type: "string",  description: "Optional justification note" },
      },
      required: ["audit_id", "approved", "approved_by"],
    },
  },
] as const;

type ToolName = (typeof TOOL_CATALOG)[number]["name"];

/**
 * Risk tier per tool, recorded in the envelope's request block.
 *
 * Derived from what the tool can do, not from a model's opinion: tools that
 * write persistent state or record an approval are "high", read-only lookups
 * are "low". Anything not listed is "unspecified" — the governance record
 * must never invent a tier it does not know.
 */
const TOOL_RISK_TIER: Record<string, string> = {
  remora_verify_claim: "low",
  dce_search_law:      "low",
  store_artifact:      "high",
  audit_decision:      "high",
};

const TOOL_DOMAIN: Record<string, string> = {
  remora_verify_claim: "verification",
  dce_search_law:      "legal_research",
  store_artifact:      "artifact_storage",
  audit_decision:      "governance",
};

// ── Utilities ──────────────────────────────────────────────────────────────────

const CORS_HEADERS = {
  "Access-Control-Allow-Origin":  "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

function err(message: string, status = 400): Response {
  return json({ error: message }, status);
}

async function sha256(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

function preview(value: unknown, maxLen = 120): string {
  const s = typeof value === "string" ? value : JSON.stringify(value);
  return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
}



// ── Audit helpers ──────────────────────────────────────────────────────────────

async function auditInsert(
  db: D1Database,
  row: {
    session_id: string;
    tool_called: string;
    input_hash: string;
    input_preview: string;
    output_hash?: string;
    output_preview?: string;
    duration_ms?: number;
    upstream_url?: string;
    approval_required?: number;
    verdict?: string;
    confidence?: number;
  },
): Promise<number | null> {
  try {
    const result = await db
      .prepare(
        `INSERT INTO audit_log
           (session_id, tool_called, input_hash, input_preview,
            output_hash, output_preview, duration_ms, upstream_url,
            approval_required, verdict, confidence)
         VALUES (?,?,?,?,?,?,?,?,?,?,?)
         RETURNING id`,
      )
      .bind(
        row.session_id,
        row.tool_called,
        row.input_hash,
        row.input_preview,
        row.output_hash ?? null,
        row.output_preview ?? null,
        row.duration_ms ?? null,
        row.upstream_url ?? null,
        row.approval_required ?? 0,
        row.verdict ?? null,
        row.confidence ?? null,
      )
      .first<{ id: number }>();
    return result?.id ?? null;
  } catch (e) {
    // Audit write is the load-bearing guarantee of this control plane.
    // Surface the failure so an operator sees it in `wrangler tail`.
    console.error("audit_log insert failed:", e instanceof Error ? e.message : String(e));
    return null;
  }
}

// ── Tool implementations ───────────────────────────────────────────────────────

async function runTool(
  name: ToolName | string,
  input: Record<string, unknown>,
  env: Env,
): Promise<{ output: unknown; verdict?: string; confidence?: number; upstream_url?: string }> {
  switch (name) {
    // ── remora_verify_claim ──────────────────────────────────────────────────
    case "remora_verify_claim": {
      const body = JSON.stringify({
        question:  input.claim,
        context:   input.context ?? "",
        use_case:  input.domain ?? "general",
      });
      const resp = await env.REMORA_SERVICE.fetch("https://remora/assess", {
        method: "POST",
        body,
        headers: { "Content-Type": "application/json" },
      });
      if (!resp.ok) {
        const errBody = await resp.text().catch(() => "");
        throw new Error(`REMORA Worker error: ${resp.status} — ${errBody.slice(0, 200)}`);
      }
      const data = await resp.json() as Record<string, unknown>;

      const confidence = (data.confidence as number) ?? 0;
      const polarity   = data.verdict;
      let verdict: string;
      if      (polarity === true  && confidence >= 0.75) verdict = "VERIFIED";
      else if (polarity === false && confidence >= 0.75) verdict = "CONTRADICTED";
      else if (confidence < 0.45)                        verdict = "UNCERTAIN";
      else                                               verdict = "SUSPICIOUS";

      return {
        verdict,
        confidence,
        output: {
          claim:      input.claim,
          verdict,
          confidence,
          consensus:  data.consensus,
          iterations: data.iterations,
          detail:     data.claim,
        },
      };
    }

    // ── dce_search_law ───────────────────────────────────────────────────────
    case "dce_search_law": {
      const top_k = Math.min(Number(input.top_k ?? 5), 10);
      const body  = JSON.stringify({ query: input.query, top_k, domain: input.domain });
      const resp  = await env.LAW_SERVICE.fetch("https://law/search", {
        method: "POST",
        body,
        headers: { "Content-Type": "application/json" },
      });
      if (!resp.ok) throw new Error(`Law search error: ${resp.status}`);
      const data  = await resp.json();
      return { output: data };
    }

    // ── store_artifact ───────────────────────────────────────────────────────
    case "store_artifact": {
      const content_type = String(input.content_type ?? "text/markdown");
      await env.ARTIFACTS.put(String(input.key), String(input.content), {
        httpMetadata: { contentType: content_type },
      });
      return {
        output: {
          status:       "STORED",
          key:          input.key,
          size:         typeof input.content === "string" ? input.content.length : 0,
          content_type,
        },
      };
    }

    // ── audit_decision ───────────────────────────────────────────────────────
    case "audit_decision": {
      await env.AUDIT_DB
        .prepare(
          `UPDATE audit_log
           SET approved = ?, approved_by = ?
           WHERE id = ?`,
        )
        .bind(input.approved ? 1 : 0, input.approved_by, input.audit_id)
        .run();

      return {
        output: {
          status:     "RECORDED",
          audit_id:   input.audit_id,
          decision:   input.approved ? "APPROVED" : "REJECTED",
          approved_by:input.approved_by,
        },
      };
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

// ── Request handlers ───────────────────────────────────────────────────────────

async function auditUpdateFinal(
  db: D1Database,
  id: number,
  row: {
    output_hash?: string;
    output_preview?: string;
    duration_ms?: number;
    upstream_url?: string;
    verdict?: string;
    confidence?: number;
  }
): Promise<void> {
  await db.prepare(
    `UPDATE audit_log SET output_hash=?, output_preview=?, duration_ms=?, upstream_url=?, verdict=?, confidence=? WHERE id=?`
  ).bind(
    row.output_hash ?? null,
    row.output_preview ?? null,
    row.duration_ms ?? null,
    row.upstream_url ?? null,
    row.verdict ?? null,
    row.confidence ?? null,
    id
  ).run();
}

/**
 * Write the governance record for one tool call.
 *
 * Separated from the audit_log write because the two answer different
 * questions: audit_log says a call happened, the envelope says what was
 * decided and links to the decision before it. Callers must treat a thrown
 * error as a failed request — an action with no governance record is exactly
 * the state this control plane exists to prevent.
 */
async function recordEnvelope(
  env: Env,
  args: {
    requestId: string;
    tenantId: string;
    sessionId: string;
    actorIdentity: string;
    toolName: string;
    toolArgs: Record<string, unknown>;
    outcome: "accept" | "escalate" | "abstain";
    policyTriggers: string[];
    approvalRequired: boolean;
    executed: boolean;
    effectOutcome: string;
    verdict?: string;
    confidence?: number;
    auditId: number | null;
  },
): Promise<{ entry_hash: string; sequence_no: number }> {
  const targetEnvironment = env.TARGET_ENVIRONMENT ?? "cloudflare_worker";
  const toolArgsHash = await canonicalToolCallHash(
    args.toolName,
    args.toolArgs,
    args.tenantId,
    targetEnvironment,
  );

  const envelope = buildEnvelope({
    requestId:         args.requestId,
    tenantId:          args.tenantId,
    sessionId:         args.sessionId,
    actorIdentity:     args.actorIdentity,
    toolName:          args.toolName,
    toolArgs:          args.toolArgs,
    toolArgsHash,
    riskTier:          TOOL_RISK_TIER[args.toolName] ?? "unspecified",
    domain:            TOOL_DOMAIN[args.toolName] ?? "unspecified",
    targetEnvironment,
    outcome:           args.outcome,
    policyTriggers:    args.policyTriggers,
    approvalRequired:  args.approvalRequired,
    executed:          args.executed,
    effectOutcome:     args.effectOutcome,
    verdict:           args.verdict,
    confidence:        args.confidence,
    auditId:           args.auditId,
    timestampUtc:      new Date().toISOString(),
  });

  const result = await appendEnvelope(env.AUDIT_DB, {
    tenantId:   args.tenantId,
    sessionId:  args.sessionId,
    requestId:  args.requestId,
    envelope,
    auditId:    args.auditId,
    signingKey: env.ENVELOPE_SIGNING_KEY,
  });

  return { entry_hash: result.entryHash, sequence_no: result.sequenceNo };
}

function envelopeFailureResponse(sessionId: string, tool: string, executed: boolean, e: unknown): Response {
  console.error("decision envelope write failed:", e instanceof Error ? e.message : String(e));
  return json(
    {
      tool,
      success: false,
      session_id: sessionId,
      executed,
      output: {
        status: "ENVELOPE_WRITE_FAILED",
        message:
          "The DecisionEnvelope for this action could not be persisted; the " +
          "governance record is incomplete and this action must not be " +
          "treated as governed.",
      },
    },
    500,
  );
}

async function handleExecute(req: Request, env: Env): Promise<Response> {
  let body: ToolInput;
  try {
    body = (await req.json()) as ToolInput;
  } catch {
    return err("Invalid JSON body");
  }
  if (!body.tool || !body.input || !body.session_id) {
    return err("Required fields: tool, input, session_id");
  }

  const tenantId = env.TENANT_ID ?? "default";
  const requestId = crypto.randomUUID();
  // Credential-derived identity only (REM-039). This deployment authenticates
  // with one shared bearer, so the principal IS that credential; a
  // client-declared user_id is kept as an explicitly unverified annotation
  // and never becomes the identity.
  const actorIdentity =
    "control_secret_bearer" +
    (body.user_id ? ` (on_behalf_of=${body.user_id}, unverified)` : "");

  const approvalTools = (env.APPROVAL_REQUIRED_TOOLS ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  const approval_required = approvalTools.includes(body.tool) ? 1 : 0;

  // Hash the input WITHOUT the audit_id field (issue #55): the approval flow
  // resubmits the same input plus audit_id, so hashing the raw input made the
  // approved-call hash differ from the pre-approval hash and the HITL check
  // ALWAYS 403'd — the only human-in-the-loop control never worked. Stripping
  // audit_id makes both calls hash identically.
  const { audit_id: _hashExcludedAuditId, ...hashableInput } =
    (body.input ?? {}) as Record<string, unknown>;
  const inputStr = JSON.stringify(hashableInput);
  const input_hash = await sha256(inputStr);

  const pre_audit_id = await auditInsert(env.AUDIT_DB, {
    session_id: body.session_id,
    tool_called: body.tool,
    input_hash,
    input_preview: preview(body.input),
    approval_required,
  });

  if (!pre_audit_id) {
    return json({ error: "Audit infrastructure failed" }, 502);
  }

  if (approval_required === 1) {
    if (!body.input.audit_id) {
      // Gate held the action pending human review: that IS a decision, and it
      // gets a governance record like any other.
      try {
        await recordEnvelope(env, {
          requestId, tenantId, sessionId: body.session_id, actorIdentity,
          toolName: body.tool, toolArgs: hashableInput,
          outcome: "escalate",
          policyTriggers: ["approval_required"],
          approvalRequired: true,
          executed: false,
          effectOutcome: "awaiting_human_approval",
          auditId: pre_audit_id,
        });
      } catch (e) {
        return envelopeFailureResponse(body.session_id, body.tool, false, e);
      }
      return json(
        {
          tool: body.tool,
          success: false,
          output: {
            status: "APPROVAL_REQUIRED",
            message: "Human approval needed via audit_decision.",
            audit_id: pre_audit_id,
          },
          approval_required: true,
          session_id: body.session_id,
          audit_id: pre_audit_id,
          request_id: requestId,
        },
        402
      );
    }

    const row = await env.AUDIT_DB.prepare("SELECT approved, input_hash FROM audit_log WHERE id = ?")
      .bind(body.input.audit_id)
      .first<{ approved: number; input_hash: string }>();

    if (!row || row.approved !== 1 || row.input_hash !== input_hash) {
      // A refused call is the outcome most worth recording: it is the evidence
      // that the gate actually held.
      try {
        await recordEnvelope(env, {
          requestId, tenantId, sessionId: body.session_id, actorIdentity,
          toolName: body.tool, toolArgs: hashableInput,
          outcome: "abstain",
          policyTriggers: [
            "approval_required",
            !row ? "approval_record_missing"
              : row.approved !== 1 ? "approval_not_granted"
              : "input_modified_after_approval",
          ],
          approvalRequired: true,
          executed: false,
          effectOutcome: "refused",
          auditId: pre_audit_id,
        });
      } catch (e) {
        return envelopeFailureResponse(body.session_id, body.tool, false, e);
      }
      return json(
        {
          error: "UNAUTHORIZED: audit_id not approved or input modified",
          audit_id: body.input.audit_id,
          request_id: requestId,
        },
        403
      );
    }
  }

  const t0 = Date.now();
  let output: unknown;
  let verdict: string | undefined;
  let confidence: number | undefined;
  let upstream_url: string | undefined;
  let success = true;

  try {
    const result = await runTool(body.tool, body.input, env);
    output = result.output;
    verdict = result.verdict;
    confidence = result.confidence;
    upstream_url = result.upstream_url;
  } catch (e) {
    success = false;
    output = { error: e instanceof Error ? e.message : String(e) };
  }

  const duration_ms = Date.now() - t0;
  const outputStr = JSON.stringify(output);
  const output_hash = await sha256(outputStr);

  try {
    await auditUpdateFinal(env.AUDIT_DB, pre_audit_id, {
      output_hash,
      output_preview: preview(output),
      duration_ms,
      upstream_url,
      verdict,
      confidence,
    });
  } catch (e) {
    // Fail-closed on the audit write (issue #55): the tool already executed,
    // so we cannot undo the side effect — but we must NOT report a clean 200.
    // Signal that the governance record is incomplete so the caller treats
    // the audit trail as broken for this action.
    console.error("Failed to update final audit state!", e);
    return json(
      {
        tool: body.tool,
        success: false,
        session_id: body.session_id,
        audit_id: pre_audit_id,
        executed: true,
        output: {
          status: "AUDIT_WRITE_FAILED",
          message:
            "Tool executed but the final audit record could not be written; " +
            "the audit trail for this action is incomplete.",
        },
      },
      500,
    );
  }

  let envelopeRef: { entry_hash: string; sequence_no: number };
  try {
    envelopeRef = await recordEnvelope(env, {
      requestId, tenantId, sessionId: body.session_id, actorIdentity,
      toolName: body.tool, toolArgs: hashableInput,
      // The gate let this through; success/failure is the effect, recorded
      // separately in the effect block rather than restated as a verdict.
      outcome: "accept",
      policyTriggers: approval_required === 1 ? ["approval_required", "approval_granted"] : [],
      approvalRequired: approval_required === 1,
      executed: true,
      effectOutcome: success ? "succeeded" : "failed",
      verdict,
      confidence,
      auditId: pre_audit_id,
    });
  } catch (e) {
    return envelopeFailureResponse(body.session_id, body.tool, true, e);
  }

  const result: ToolResult = {
    tool: body.tool,
    success,
    output,
    verdict,
    confidence,
    duration_ms,
    session_id: body.session_id,
    audit_id: pre_audit_id,
    approval_required: approval_required === 1,
    request_id: requestId,
    envelope_hash: envelopeRef.entry_hash,
    envelope_sequence: envelopeRef.sequence_no,
  };

  return json(result, success ? 200 : 502);
}


async function handleCreateSession(req: Request, env: Env): Promise<Response> {
  const body = await req.json().catch(() => ({})) as Record<string, unknown>;
  const id   = crypto.randomUUID();
  await env.AUDIT_DB
    .prepare("INSERT INTO sessions (id, user_id, user_label) VALUES (?,?,?)")
    .bind(id, body.user_id ?? null, body.user_label ?? null)
    .run();

  await env.SESSIONS.put(id, JSON.stringify({ id, created_at: new Date().toISOString(), status: "active" }), {
    expirationTtl: 86400, // 24 h
  });

  return json({ session_id: id, status: "active" }, 201);
}

async function handleEndSession(id: string, env: Env): Promise<Response> {
  await env.AUDIT_DB
    .prepare("UPDATE sessions SET status='completed', ended_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?")
    .bind(id)
    .run();
  await env.SESSIONS.delete(id);
  return json({ session_id: id, status: "completed" });
}

async function handleAudit(url: URL, env: Env): Promise<Response> {
  const session_id = url.searchParams.get("session_id");
  const limit      = Math.min(Number(url.searchParams.get("limit") ?? 50), 200);
  const offset     = Number(url.searchParams.get("offset") ?? 0);

  let stmt: D1PreparedStatement;
  if (session_id) {
    stmt = env.AUDIT_DB
      .prepare("SELECT * FROM audit_log WHERE session_id=? ORDER BY ts DESC LIMIT ? OFFSET ?")
      .bind(session_id, limit, offset);
  } else {
    stmt = env.AUDIT_DB
      .prepare("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ? OFFSET ?")
      .bind(limit, offset);
  }

  const { results } = await stmt.all();
  return json({ rows: results, count: results.length });
}

// ── DecisionEnvelope read + verify ─────────────────────────────────────────────

async function handleEnvelopeList(url: URL, env: Env): Promise<Response> {
  const tenantId   = url.searchParams.get("tenant_id") ?? env.TENANT_ID ?? "default";
  const sessionId  = url.searchParams.get("session_id");
  const limit      = Math.min(Number(url.searchParams.get("limit") ?? 50), 200);
  const offset     = Number(url.searchParams.get("offset") ?? 0);

  const stmt = sessionId
    ? env.AUDIT_DB.prepare(
        "SELECT request_id, tenant_id, session_id, sequence_no, created_at, " +
          "envelope_canonical, previous_hash, entry_hash, signature, audit_id " +
          "FROM decision_envelopes WHERE tenant_id=? AND session_id=? " +
          "ORDER BY sequence_no ASC LIMIT ? OFFSET ?",
      ).bind(tenantId, sessionId, limit, offset)
    : env.AUDIT_DB.prepare(
        "SELECT request_id, tenant_id, session_id, sequence_no, created_at, " +
          "envelope_canonical, previous_hash, entry_hash, signature, audit_id " +
          "FROM decision_envelopes WHERE tenant_id=? " +
          "ORDER BY sequence_no ASC LIMIT ? OFFSET ?",
      ).bind(tenantId, limit, offset);

  const { results } = await stmt.all<Record<string, unknown>>();
  const rows = (results ?? []).map((r) => ({
    ...r,
    envelope: JSON.parse(String(r.envelope_canonical)),
  }));
  return json({ tenant_id: tenantId, rows, count: rows.length });
}

async function handleEnvelopeGet(requestId: string, env: Env): Promise<Response> {
  const row = await env.AUDIT_DB.prepare(
    "SELECT request_id, tenant_id, session_id, sequence_no, created_at, " +
      "envelope_canonical, previous_hash, entry_hash, signature, audit_id " +
      "FROM decision_envelopes WHERE request_id = ?",
  )
    .bind(requestId)
    .first<Record<string, unknown>>();

  if (!row) return err("Envelope not found", 404);
  return json({ ...row, envelope: JSON.parse(String(row.envelope_canonical)) });
}

async function handleEnvelopeVerify(url: URL, env: Env): Promise<Response> {
  const tenantId = url.searchParams.get("tenant_id") ?? env.TENANT_ID ?? "default";

  // Verification must read the WHOLE chain: a paged subset cannot prove that
  // nothing was removed outside the page.
  const { results } = await env.AUDIT_DB.prepare(
    "SELECT sequence_no, created_at, envelope_canonical, previous_hash, " +
      "entry_hash, signature FROM decision_envelopes WHERE tenant_id=? " +
      "ORDER BY sequence_no ASC",
  )
    .bind(tenantId)
    .all<ChainRow>();

  const rows = results ?? [];
  const verdict = await verifyChain(rows, env.ENVELOPE_SIGNING_KEY);
  return json({
    tenant_id: tenantId,
    ...verdict,
    signed: Boolean(env.ENVELOPE_SIGNING_KEY),
    note:
      rows.length === 0
        ? "No envelopes stored for this tenant. An empty chain verifies trivially and proves nothing."
        : env.ENVELOPE_SIGNING_KEY
          ? "Chain recomputed and HMAC signatures checked."
          : "Chain recomputed. ENVELOPE_SIGNING_KEY is unset, so rows rewritten wholesale (hash included) are not detectable.",
  });
}

// ── Main fetch handler ─────────────────────────────────────────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url  = new URL(request.url);
    const path = url.pathname;

    // ── Auth guard (fail closed) ─────────────────────────────────────────────
    // Writes (POST/DELETE/PATCH) always require auth.
    // Sensitive GETs (/audit reads PII-adjacent session data;
    //  /test-bindings probes upstream connectivity) also require auth.
    // /tools, /status, /sessions GET are intentionally public.
    const needsAuth =
      ["POST", "DELETE", "PATCH"].includes(request.method) ||
      (request.method === "GET" &&
        (path === "/audit" ||
          path === "/test-bindings" ||
          // Envelopes carry full request context and decision rationale;
          // they are strictly more sensitive than /audit and are never public.
          path === "/envelopes" ||
          path.startsWith("/envelopes/")));

    if (needsAuth) {
      if (!env.CONTROL_SECRET) {
        // Misconfigured deploy: refuse requests rather than accepting them
        // unauthenticated. CONTROL_SECRET must be set with `wrangler secret put`.
        return err("Control plane misconfigured: CONTROL_SECRET unset", 503);
      }
      const auth = request.headers.get("Authorization") ?? "";
      if (auth !== `Bearer ${env.CONTROL_SECRET}`) {
        return err("Unauthorized", 401);
      }
    }

    // ── Routing ──────────────────────────────────────────────────────────────

    // GET /tools — tool catalog for Claude discovery
    if (path === "/tools" && request.method === "GET") {
      return json({ tools: TOOL_CATALOG, count: TOOL_CATALOG.length });
    }

    // GET /codegraph — codegraph scope and lightweight repository entrypoint index
    if (path === "/codegraph" && request.method === "GET") {
      const query = url.searchParams.get("q") ?? "";
      const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 8), 1), 25);
      return json(buildCodegraphPayload(query, limit));
    }

    // GET /search — repo search alias for Claude Code and MCP clients
    if (path === "/search" && request.method === "GET") {
      const query = url.searchParams.get("q") ?? "";
      const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 8), 1), 25);
      return json({
        ...buildCodegraphPayload(query, limit),
        mode: "repo_search",
      });
    }

    // POST /execute — run a tool
    if (path === "/execute" && request.method === "POST") {
      return handleExecute(request, env);
    }

    // POST /sessions — create a session
    if (path === "/sessions" && request.method === "POST") {
      return handleCreateSession(request, env);
    }

    // DELETE /sessions/:id — end a session
    const sessionMatch = path.match(/^\/sessions\/([^/]+)$/);
    if (sessionMatch && request.method === "DELETE") {
      return handleEndSession(sessionMatch[1], env);
    }

    // GET /audit — query audit log (admin)
    if (path === "/audit" && request.method === "GET") {
      return handleAudit(url, env);
    }

    // GET /envelopes/verify — recompute the tenant envelope chain (admin).
    // Checked before the :request_id route so "verify" is never read as an id.
    if (path === "/envelopes/verify" && request.method === "GET") {
      return handleEnvelopeVerify(url, env);
    }

    // GET /envelopes — list stored DecisionEnvelopes (admin)
    if (path === "/envelopes" && request.method === "GET") {
      return handleEnvelopeList(url, env);
    }

    // GET /envelopes/:request_id — one DecisionEnvelope (admin)
    const envelopeMatch = path.match(/^\/envelopes\/([A-Za-z0-9._-]+)$/);
    if (envelopeMatch && request.method === "GET") {
      return handleEnvelopeGet(envelopeMatch[1], env);
    }

    // GET /status — public health check (no upstream URLs in response)
    if (path === "/status" && request.method === "GET") {
      return json({
        status:  "ok",
        service: "remora-agent-control",
        tools:   TOOL_CATALOG.length,
      });
    }

    // GET /papers — list the public PDF downloads available in R2.
    if (path === "/papers" && request.method === "GET") {
      const listed = await env.ARTIFACTS.list({ prefix: "papers/" });
      const files = listed.objects
        .filter((o) => o.key.endsWith(".pdf"))
        .map((o) => ({
          name: o.key.replace(/^papers\//, ""),
          url: `${url.origin}/${o.key}`,
          size_bytes: o.size,
          uploaded: o.uploaded,
        }));
      return json({ papers: files, count: files.length });
    }

    // GET /papers/:name.pdf — public PDF download streamed from R2. Kept in sync
    // with the repo by .github/workflows/sync-papers-to-r2.yml. Serves a single
    // whitelisted key shape so the route can never enumerate the bucket; GET is
    // public (the auth guard above only gates /audit and /test-bindings).
    const paperMatch = path.match(/^\/papers\/([A-Za-z0-9._-]+\.pdf)$/);
    if (paperMatch && request.method === "GET") {
      const obj = await env.ARTIFACTS.get(`papers/${paperMatch[1]}`);
      if (!obj) return err("Paper not found", 404);
      const headers = new Headers(CORS_HEADERS);
      headers.set("Content-Type", "application/pdf");
      headers.set("Content-Disposition", `inline; filename="${paperMatch[1]}"`);
      headers.set("Cache-Control", "public, max-age=3600");
      if (obj.httpEtag) headers.set("ETag", obj.httpEtag);
      return new Response(obj.body, { headers });
    }

    // GET /test-bindings — diagnose service binding connectivity
    if (path === "/test-bindings" && request.method === "GET") {
      const results: Record<string, unknown> = {};

      try {
        const r = await env.REMORA_SERVICE.fetch("https://remora/status");
        const body = await r.text();
        results.remora_status = { http: r.status, body: body.slice(0, 300) };
      } catch (e) {
        results.remora_status = { error: String(e) };
      }

      try {
        const r = await env.LAW_SERVICE.fetch("https://law/status");
        const body = await r.text();
        results.law_status = { http: r.status, body: body.slice(0, 300) };
      } catch (e) {
        results.law_status = { error: String(e) };
      }

      return json(results);
    }

    return err("Not found", 404);
  },
};
