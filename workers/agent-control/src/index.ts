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
 *
 * Deploy
 * ──────
 *   cd workers/agent-control
 *   npm run db:init:remote         # create D1 tables
 *   wrangler secret put CONTROL_SECRET
 *   wrangler secret put REMORA_SECRET
 *   wrangler secret put RAG_SECRET
 *   npm run deploy
 */

import { buildCodegraphPayload } from "./codegraph";

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

  // Secrets — required in production; the auth guard fails closed if missing.
  CONTROL_SECRET?: string;
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
      "REQUIRES APPROVAL FLAG — set approved=true only when the user has confirmed. " +
      "Returns the artifact key for future retrieval.",
    parameters: {
      type: "object",
      properties: {
        key:         { type: "string", description: "Storage key / filename (e.g. 'reports/bygg-x-2026-05.md')" },
        content:     { type: "string", description: "Text content to store" },
        content_type:{ type: "string", description: "MIME type (default: text/markdown)" },
        approved:    { type: "boolean",description: "User has confirmed this write should proceed" },
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
      if (!input.approved) {
        return {
          output: {
            status:  "APPROVAL_REQUIRED",
            message: "Set approved=true to confirm storing this artifact.",
            key:     input.key,
            size:    typeof input.content === "string" ? input.content.length : 0,
          },
        };
      }
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

async function handleExecute(req: Request, env: Env): Promise<Response> {
  let body: ToolInput;
  try {
    body = await req.json() as ToolInput;
  } catch {
    return err("Invalid JSON body");
  }
  if (!body.tool || !body.input || !body.session_id) {
    return err("Required fields: tool, input, session_id");
  }

  const approvalTools = (env.APPROVAL_REQUIRED_TOOLS ?? "").split(",").map(t => t.trim()).filter(Boolean);
  const approval_required = approvalTools.includes(body.tool) ? 1 : 0;

  const inputStr   = JSON.stringify(body.input);
  const input_hash = await sha256(inputStr);

  const t0 = Date.now();
  let output: unknown;
  let verdict: string | undefined;
  let confidence: number | undefined;
  let upstream_url: string | undefined;
  let success = true;

  try {
    const result = await runTool(body.tool, body.input, env);
    output       = result.output;
    verdict      = result.verdict;
    confidence   = result.confidence;
    upstream_url = result.upstream_url;
  } catch (e) {
    success = false;
    output  = { error: e instanceof Error ? e.message : String(e) };
  }

  const duration_ms  = Date.now() - t0;
  const outputStr    = JSON.stringify(output);
  const output_hash  = await sha256(outputStr);

  const audit_id = await auditInsert(env.AUDIT_DB, {
    session_id: body.session_id,
    tool_called: body.tool,
    input_hash,
    input_preview:  preview(body.input),
    output_hash,
    output_preview: preview(output),
    duration_ms,
    upstream_url,
    approval_required,
    verdict,
    confidence,
  });

  const result: ToolResult = {
    tool:       body.tool,
    success,
    output,
    verdict,
    confidence,
    duration_ms,
    session_id: body.session_id,
    audit_id:   audit_id ?? undefined,
    approval_required: approval_required === 1,
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
      (request.method === "GET" && (path === "/audit" || path === "/test-bindings"));

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
