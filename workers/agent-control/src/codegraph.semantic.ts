// Semantic retrieval for the CodeGraph file catalog.
//
// The keyword ranker in codegraph.ts only sees file paths, generated
// summaries and tags. This module adds retrieval over file *content*:
// tracked files are chunked and embedded offline by
// scripts/build_codegraph_index.mjs into a Vectorize index, and a query is
// embedded here with the same model and matched against those chunks.
//
// Semantic search is an optional capability. When the AI or Vectorize
// binding is absent the caller gets an explicit "unavailable" status, never
// silently-empty results presented as a real answer.

import {
  CODEGRAPH_CATALOG,
  buildCodegraphPayload,
  inferKind,
  queryCodegraph,
  type CodegraphEntry,
} from "./codegraph";

export type CodegraphSearchMode = "keyword" | "semantic" | "hybrid";

export const CODEGRAPH_SEARCH_MODES: readonly CodegraphSearchMode[] = ["keyword", "semantic", "hybrid"];

/** Model used by the offline indexer; query and chunks must share it. */
export const DEFAULT_CODEGRAPH_EMBED_MODEL = "@cf/baai/bge-base-en-v1.5";

/** bge-*-v1.5 retrieval instruction for short queries (not applied to passages). */
export const BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: ";

/** Upper bound on a semantic query; each call costs one embedding inference. */
export const MAX_SEMANTIC_QUERY_CHARS = 512;

/** Vectorize caps topK at 50 when full metadata is returned (raised from 20 on 2026-03-16). */
const VECTORIZE_TOPK_WITH_METADATA = 50;

/** Reciprocal-rank-fusion constant (Cormack et al., 2009). */
const RRF_K = 60;

export interface EmbeddingRunner {
  run(model: string, input: { text: string[] }): Promise<unknown>;
}

export interface CodegraphSemanticEnv {
  AI?: EmbeddingRunner;
  CODEGRAPH_VECTORS?: VectorizeIndex;
  CODEGRAPH_EMBED_MODEL?: string;
  /** When set, only vectors written with this index_version are returned. */
  CODEGRAPH_INDEX_VERSION?: string;
}

export type SemanticStatus =
  | { status: "not_requested" }
  | { status: "ok"; model: string; index_version: string | null }
  // The index answered with nothing. Usually CODEGRAPH_INDEX_VERSION names a
  // version the index does not hold, so it is reported, never shown as "ok".
  | { status: "empty"; model: string; index_version: string | null; reason: string }
  | { status: "unavailable"; reason: string }
  | { status: "error"; reason: string };

export type SemanticMatch = {
  path: string;
  kind: CodegraphEntry["kind"];
  score: number;
  start_line: number | null;
  end_line: number | null;
  snippet: string | null;
  index_commit: string | null;
};

export type HybridMatch = {
  path: string;
  kind: CodegraphEntry["kind"];
  summary: string | null;
  score: number;
  sources: Array<"keyword" | "semantic">;
  start_line: number | null;
  end_line: number | null;
  snippet: string | null;
};

export class SemanticUnavailableError extends Error {}

export function parseSearchMode(raw: string | null): CodegraphSearchMode | null {
  const value = (raw ?? "keyword").trim().toLowerCase() || "keyword";
  return (CODEGRAPH_SEARCH_MODES as readonly string[]).includes(value)
    ? (value as CodegraphSearchMode)
    : null;
}

export function semanticUnavailableReason(env: CodegraphSemanticEnv): string | null {
  if (!env.AI) return "AI binding is not configured";
  if (!env.CODEGRAPH_VECTORS) return "CODEGRAPH_VECTORS Vectorize binding is not configured";
  return null;
}

function embedModel(env: CodegraphSemanticEnv): string {
  return env.CODEGRAPH_EMBED_MODEL?.trim() || DEFAULT_CODEGRAPH_EMBED_MODEL;
}

async function embedQuery(query: string, env: CodegraphSemanticEnv): Promise<number[]> {
  const result = (await env.AI!.run(embedModel(env), {
    text: [BGE_QUERY_INSTRUCTION + query],
  })) as { data?: unknown };
  const vector = Array.isArray(result?.data) ? result.data[0] : undefined;
  if (!Array.isArray(vector) || vector.length === 0 || !vector.every((v) => typeof v === "number")) {
    throw new Error("embedding model returned no vector");
  }
  return vector as number[];
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function int(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

/**
 * Embed the query and return the best-matching chunk per file, best first.
 * Throws SemanticUnavailableError when bindings are missing; any other
 * error comes from the embedding model or Vectorize.
 */
export async function semanticSearch(
  query: string,
  limit: number,
  env: CodegraphSemanticEnv,
): Promise<SemanticMatch[]> {
  const reason = semanticUnavailableReason(env);
  if (reason) throw new SemanticUnavailableError(reason);

  const vector = await embedQuery(query, env);
  const version = env.CODEGRAPH_INDEX_VERSION?.trim();
  const result = await env.CODEGRAPH_VECTORS!.query(vector, {
    topK: Math.min(VECTORIZE_TOPK_WITH_METADATA, Math.max(limit * 3, limit)),
    returnMetadata: "all",
    ...(version ? { filter: { index_version: version } } : {}),
  });

  const seen = new Set<string>();
  const matches: SemanticMatch[] = [];
  const ordered = [...(result.matches ?? [])].sort((a, b) => b.score - a.score);
  for (const match of ordered) {
    const meta = (match.metadata ?? {}) as Record<string, unknown>;
    const path = str(meta.path);
    if (!path || seen.has(path)) continue;
    // Defence in depth: never trust a vector that claims a different index version.
    if (version && meta.index_version !== version) continue;
    seen.add(path);
    matches.push({
      path,
      kind: inferKind(path),
      score: match.score,
      start_line: int(meta.start_line),
      end_line: int(meta.end_line),
      snippet: str(meta.snippet),
      index_commit: str(meta.commit),
    });
    if (matches.length >= limit) break;
  }
  return matches;
}

/** Fuse keyword and semantic rankings by reciprocal rank, keyed on path. */
export function fuseRankings(
  keyword: CodegraphEntry[],
  semantic: SemanticMatch[],
  limit: number,
): HybridMatch[] {
  const fused = new Map<string, HybridMatch>();

  keyword.forEach((entry, rank) => {
    fused.set(entry.path, {
      path: entry.path,
      kind: entry.kind,
      summary: entry.summary,
      score: 1 / (RRF_K + rank + 1),
      sources: ["keyword"],
      start_line: null,
      end_line: null,
      snippet: null,
    });
  });

  semantic.forEach((match, rank) => {
    const contribution = 1 / (RRF_K + rank + 1);
    const existing = fused.get(match.path);
    if (existing) {
      existing.score += contribution;
      existing.sources.push("semantic");
      existing.start_line = match.start_line;
      existing.end_line = match.end_line;
      existing.snippet = match.snippet;
    } else {
      const catalogEntry = CODEGRAPH_CATALOG.find((entry) => entry.path === match.path);
      fused.set(match.path, {
        path: match.path,
        kind: match.kind,
        summary: catalogEntry?.summary ?? null,
        score: contribution,
        sources: ["semantic"],
        start_line: match.start_line,
        end_line: match.end_line,
        snippet: match.snippet,
      });
    }
  });

  return [...fused.values()]
    .sort((a, b) => b.score - a.score || a.path.localeCompare(b.path))
    .slice(0, limit)
    .map((entry) => ({ ...entry, score: Number(entry.score.toFixed(6)) }));
}

export type CodegraphRequestResult =
  | { ok: true; body: Record<string, unknown> }
  | { ok: false; status: number; error: string };

/**
 * Build the /codegraph (and /search) response for one mode.
 *
 * - keyword: the unchanged path/summary/tag ranker; `matches` keeps its
 *   original shape so existing clients are unaffected.
 * - semantic: content retrieval only. Missing bindings is a 503, a model
 *   or index failure is a 502; neither is reported as an empty result.
 * - hybrid: reciprocal-rank fusion of both. If the semantic side is
 *   unavailable or fails, the keyword ranking is returned and `semantic`
 *   states why, so the degradation is visible to the caller.
 */
export async function buildCodegraphSearch(
  query: string,
  limit: number,
  mode: CodegraphSearchMode,
  env: CodegraphSemanticEnv,
): Promise<CodegraphRequestResult> {
  const base = buildCodegraphPayload(query, limit);
  if (mode === "keyword") {
    return { ok: true, body: { ...base, mode, semantic: { status: "not_requested" } satisfies SemanticStatus } };
  }

  if (!query) return { ok: false, status: 400, error: `mode=${mode} requires a non-empty q` };
  if (query.length > MAX_SEMANTIC_QUERY_CHARS) {
    return { ok: false, status: 400, error: `q exceeds ${MAX_SEMANTIC_QUERY_CHARS} characters` };
  }

  const okStatus: SemanticStatus = {
    status: "ok",
    model: embedModel(env),
    index_version: env.CODEGRAPH_INDEX_VERSION?.trim() || null,
  };

  const emptyStatus = (): SemanticStatus => ({
    status: "empty",
    model: embedModel(env),
    index_version: env.CODEGRAPH_INDEX_VERSION?.trim() || null,
    reason: "no indexed chunk matched; check that CODEGRAPH_INDEX_VERSION names an indexed version",
  });

  if (mode === "semantic") {
    try {
      const matches = await semanticSearch(query, limit, env);
      return {
        ok: true,
        body: { ...base, mode, semantic: matches.length ? okStatus : emptyStatus(), matches },
      };
    } catch (error) {
      if (error instanceof SemanticUnavailableError) {
        return { ok: false, status: 503, error: `semantic search unavailable: ${error.message}` };
      }
      return { ok: false, status: 502, error: "semantic search failed upstream" };
    }
  }

  // hybrid
  const keyword = queryCodegraph(query, Math.max(limit, 25));
  let semantic: SemanticMatch[] = [];
  let status: SemanticStatus = okStatus;
  try {
    semantic = await semanticSearch(query, Math.max(limit, 10), env);
    if (semantic.length === 0) status = emptyStatus();
  } catch (error) {
    status =
      error instanceof SemanticUnavailableError
        ? { status: "unavailable", reason: error.message }
        : { status: "error", reason: "semantic search failed upstream" };
  }
  return {
    ok: true,
    body: { ...base, mode, semantic: status, matches: fuseRankings(keyword, semantic, limit) },
  };
}
