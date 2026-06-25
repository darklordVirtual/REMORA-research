/**
 * remora-law-search — Norwegian Law Search Bridge
 *
 * Provides HTTP access to the DCE norges-lover-law-index (Cloudflare Vectorize,
 * 1024-dim bge-m3 multilingual embeddings containing Norwegian laws and legal decisions).
 *
 * Used by the REMORA MCP server to verify legal citations and principles
 * against authoritative Norwegian statute text.
 *
 * Endpoints
 * ---------
 *   POST /search   Search for Norwegian law by query string
 *   GET  /status   Index health check
 */

interface Env {
  AI: Ai;
  LAW_INDEX: VectorizeIndex;
  LAW_DB: D1Database;
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

async function embed(text: string, env: Env): Promise<number[]> {
  // bge-m3 (1024-dim, multilingual) — matches DCE's norges-lover-law-index embedding model
  const result = await env.AI.run("@cf/baai/bge-m3" as BaseAiTextEmbeddingsModels, {
    text: [text.slice(0, 2048)],
  });
  return (result as { data: number[][] }).data[0];
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (url.pathname === "/status") {
      return json({ ok: true, index: "norges-lover-law-index", dimensions: 1024 });
    }

    if (url.pathname === "/search" && request.method === "POST") {
      let body: { query?: string; top_k?: number; filter?: Record<string, string> };
      try {
        body = await request.json() as typeof body;
      } catch {
        return json({ error: "Invalid JSON" }, 400);
      }

      const query = body.query?.trim();
      if (!query) return json({ error: "query required" }, 400);
      const k = Math.min(body.top_k ?? 5, 10);

      // Embed the query
      const embedding = await embed(query, env);

      // Search the law index
      const opts: VectorizeQueryOptions = {
        topK: k,
        returnValues: false,
        returnMetadata: "all",
      };
      if (body.filter) {
        opts.filter = body.filter;
      }

      const results = await env.LAW_INDEX.query(embedding, opts);

      const matches = results.matches.map((m) => {
        const meta = (m.metadata ?? {}) as Record<string, string>;
        // Return all metadata so callers can discover the schema
        return {
          id: m.id,
          score: m.score,
          metadata: meta,
          // Common field aliases for convenience
          law_id: meta["law_id"] ?? meta["lovId"] ?? meta["source"] ?? meta["id"] ?? "",
          title: meta["title"] ?? meta["lovNavn"] ?? meta["name"] ?? meta["tittel"] ?? "",
          section: meta["section"] ?? meta["paragraph"] ?? meta["paragraf"] ?? meta["sectionId"] ?? "",
          content: meta["excerpt"] ?? meta["content"] ?? meta["text"] ?? "",
          heading: meta["heading"] ?? "",
          paragraph_ref: meta["paragraph_ref"] ?? meta["paragraph"] ?? "",
          law_ref: meta["law_ref"] ?? "",
          legal_areas: meta["legal_areas"] ?? "",
          url: meta["url"] ?? meta["lovUrl"] ?? "",
        };
      });

        return json({ query, matches, total: matches.length });
    }

    // ── POST /verify-citation ─────────────────────────────────────────────────
    // Check if a specific Norwegian court citation exists in the DCE database.
    // Returns: found (bool), matching text (if found), source namespace.
    if (url.pathname === "/verify-citation" && request.method === "POST") {
      let body: { citation?: string };
      try { body = await request.json() as typeof body; } catch { return json({ error: "Invalid JSON" }, 400); }

      const citation = body.citation?.trim() ?? "";
      if (!citation) return json({ error: "citation required" }, 400);

      // Normalise: HR-2021-2847-A → hr-2021-2847-a and hr-2021-2847
      const normCit = citation.toLowerCase().replace(/\s+/g, "-");
      const searchPat = normCit.replace(/-[aup]$/, ""); // strip suffix for broader match

      // Query D1 for this citation in chunk_text or vector_id
      const result = await env.LAW_DB.prepare(
        `SELECT vector_id, vector_namespace, substr(chunk_text, 1, 500) AS snippet
         FROM legal_document_fragments
         WHERE LOWER(vector_id) LIKE ? OR LOWER(chunk_text) LIKE ?
         LIMIT 5`
      ).bind(`%${searchPat}%`, `%${normCit}%`).all();

      const found = (result.results ?? []).length > 0;
      const rows  = (result.results ?? []).map((r: Record<string, unknown>) => ({
        vector_id:  r["vector_id"],
        namespace:  r["vector_namespace"],
        snippet:    r["snippet"],
      }));

      // Also search Vectorize for semantic match
      let vectorMatches: unknown[] = [];
      try {
        const emb = await embed(citation, env);
        const vres = await env.LAW_INDEX.query(emb, { topK: 3, returnValues: false, returnMetadata: "all" });
        vectorMatches = (vres.matches ?? []).filter(m => m.score > 0.30).map(m => ({
          id: m.id, score: m.score,
          law_id: ((m.metadata ?? {}) as Record<string, string>)["law_id"] ?? m.id,
        }));
      } catch {}

      return json({
        citation,
        found_in_d1: found,
        d1_matches: rows,
        vector_matches: vectorMatches,
        verdict: found
          ? "FOUND_IN_DATABASE"
          : vectorMatches.length > 0
          ? "POSSIBLE_MATCH_VECTOR"
          : "NOT_FOUND",
        note: found
          ? "Citation exists in DCE legal database"
          : "Citation not found in DCE database — may be hallucinated or not yet indexed",
      });
    }

    return json({ error: "Not found", endpoints: ["/search", "/verify-citation", "/status"] }, 404);
  },
};
