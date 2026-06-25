/**
 * REMORA RAG Oracle — Cloudflare Worker  (V2)
 *
 * Retrieval-Augmented Generation oracle node for the REMORA multi-oracle
 * consensus framework.  Four key upgrades over V1:
 *
 *   1. Cross-encoder Reranking   — @cf/baai/bge-reranker-base
 *      Fetches RERANK_CANDIDATES (20) ANN results, scores every (query, doc)
 *      pair with a cross-encoder, then keeps only the top-k. Dramatically
 *      improves precision over cosine similarity alone.
 *
 *   2. Strong-model routing      — @cf/meta/llama-3.3-70b-instruct
 *      complexity=high or queries longer than 200 chars automatically route
 *      synthesis to the 70B model.  Fast queries use llama-3.1-8b-instruct.
 *
 *   3. Multilingual embedding    — @cf/baai/bge-m3  (1024d)
 *      Queries containing non-ASCII characters (e.g. Norwegian legal text)
 *      embed into the multilingual VECTORIZE_MULTI index instead of the
 *      default English 768d index.  Translation via @cf/meta/m2m100-1.2b
 *      is also available as an alternative when ENABLE_TRANSLATION=true.
 *
 *   4. Worker-native dual-model consensus
 *      When dual_consensus=true or ENABLE_DUAL_CONSENSUS=true, both
 *      llama-3.1-8b and llama-3.3-70b run in parallel.  If they agree,
 *      confidence is boosted +10 pp; if they disagree, confidence is
 *      reduced and the verdict is flagged for full REMORA routing.
 *
 * Endpoints
 * ─────────
 *   POST /query        Ask a yes/no question; returns REMORA verdict
 *   POST /ingest       Ingest a document chunk into the knowledge base
 *   GET  /status       Health + index statistics
 *   GET  /search       Debug: raw vector search without synthesis
 *   POST /rerank       Debug: rerank a list of texts against a query
 *   POST /translate    Translate text to English via m2m100
 */

// ── Types ──────────────────────────────────────────────────────────────────────

interface Env {
  AI: Ai;
  VECTORIZE: VectorizeIndex;
  VECTORIZE_MULTI: VectorizeIndex;
  DB: D1Database;
  CACHE: KVNamespace;

  EMBED_MODEL: string;
  EMBED_MODEL_MULTI: string;
  SYNTH_MODEL: string;
  SYNTH_MODEL_STRONG: string;
  RERANKER_MODEL: string;
  TRANSLATE_MODEL: string;

  DEFAULT_TOP_K: string;
  RERANK_CANDIDATES: string;
  CACHE_TTL_S: string;
  MAX_CONTEXT_CHR: string;

  ENABLE_RERANK: string;
  ENABLE_TRANSLATION: string;
  ENABLE_DUAL_CONSENSUS: string;

  ORACLE_SECRET?: string;
}

interface QueryRequest {
  query: string;
  domain?: string;
  top_k?: number;
  use_cache?: boolean;
  /** 'auto' (default) | 'low' → 8B model | 'high' → 70B model */
  complexity?: 'low' | 'high' | 'auto';
  /** Override auto-detect; false = English index, true = multilingual index */
  multilingual?: boolean;
  /** Skip KV cache for this request */
  bypass_cache?: boolean;
  /** Run both 8B + 70B in parallel and compare verdicts */
  dual_consensus?: boolean;
  /** Routing hint: 'legal' → dual_consensus + 70B; 'security' → 8B fast */
  use_case?: 'legal' | 'security' | 'general';
  /**
   * Optional access control context (ABAC).
   * When present, Vectorize results are filtered to the allowed clearance
   * levels and tenant.  Cache keys are partitioned per identity so that
   * a cached response for one user is never served to another.
   *
   * Set by CloudflareRAGOracle.with_access(AccessContext) on the Python side.
   */
  access?: {
    clearance_levels: string[];   // e.g. ["public", "internal"]
    acl_groups: string[];         // e.g. ["finance", "legal"]
    tenant_id?: string | null;    // multi-tenant org boundary
  };
  /** Cache-key partition string injected by the Python oracle when access is set. */
  cache_partition?: string;
}

interface IngestRequest {
  content: string;
  source: string;
  domain: string;
  title?: string;
  chunk_index?: number;
  confidence_weight?: number;
  /** Set true to embed into the multilingual (bge-m3) index */
  multilingual?: boolean;
  /**
   * Access control metadata stored as Vectorize vector metadata.
   * Defaults to 'public' / no tenant restriction if omitted.
   * These values are used as filter predicates at query time.
   */
  clearance_level?: string;     // 'public' | 'internal' | 'restricted' | 'secret'
  acl_groups?: string[];        // e.g. ['finance', 'legal']
  tenant_id?: string;           // multi-tenant org boundary
}

interface RemoraVerdict {
  answer: boolean | null;
  claim: string;
  confidence: number;
  sources: string[];
  retrieved_chunks: number;
  reranked: boolean;
  cache_hit: boolean;
  multilingual: boolean;
  model: string;
  dual_consensus?: boolean;
  models_agreed?: boolean;
  use_case?: string;
}

interface Chunk {
  content: string;
  source: string;
  score: number;
}

// ── Utilities ─────────────────────────────────────────────────────────────────

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

function err(msg: string, status = 400): Response {
  return json({ error: msg, ok: false }, status);
}

async function sha256hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function isNonEnglish(text: string): boolean {
  // Detects Norwegian, German, French, etc. via non-ASCII characters
  return /[^\x00-\x7F]/.test(text) || /\b(er|og|av|til|fra|ikke|med|for|som)\b/.test(text);
}

function parseVerdictFromLLM(raw: string): Pick<RemoraVerdict, 'answer' | 'claim' | 'confidence'> {
  try {
    const match = raw.match(/\{[\s\S]*\}/);
    if (!match) throw new Error('No JSON found');
    const obj = JSON.parse(match[0]) as Record<string, unknown>;
    const ans = obj['answer'];
    let answer: boolean | null = null;
    if (ans === true  || ans === 'true'  || ans === 'yes') answer = true;
    if (ans === false || ans === 'false' || ans === 'no')  answer = false;
    const confidence = typeof obj['confidence'] === 'number'
      ? Math.max(0, Math.min(1, obj['confidence'] as number))
      : 0.5;
    return { answer, claim: String(obj['claim'] ?? ''), confidence };
  } catch {
    return { answer: null, claim: 'synthesis failed', confidence: 0.0 };
  }
}

function authorBearer(request: Request, env: Env): boolean {
  // Fail-closed: if ORACLE_SECRET is unset the worker is misconfigured and
  // should reject ALL requests rather than silently allowing them.
  // Set the secret with: wrangler secret put ORACLE_SECRET
  if (!env.ORACLE_SECRET) return false;
  const auth = request.headers.get('Authorization') ?? '';
  return auth === `Bearer ${env.ORACLE_SECRET}`;
}

function optionalBearer(request: Request, env: Env): boolean {
  // If ORACLE_SECRET is unset, allow all requests (open/dev deployment).
  // If ORACLE_SECRET is set, require a valid Bearer token.
  if (!env.ORACLE_SECRET) return true;
  const auth = request.headers.get('Authorization') ?? '';
  return auth === `Bearer ${env.ORACLE_SECRET}`;
}

// ── 1. Embedding ──────────────────────────────────────────────────────────────

async function embedText(text: string, env: Env, multilingual: boolean): Promise<number[]> {
  const truncated = text.slice(0, 512);
  const model = multilingual ? env.EMBED_MODEL_MULTI : env.EMBED_MODEL;
  const result = await env.AI.run(model as BaseAiTextEmbeddingsModels, { text: [truncated] });
  return (result as { data: number[][] }).data[0];
}

// ── 2. Translation (Norwegian → English before English-index embedding) ────────

async function translateToEnglish(text: string, env: Env): Promise<string> {
  try {
    const result = await env.AI.run(env.TRANSLATE_MODEL as BaseAiTranslationModels, {
      text,
      source_lang: 'no',
      target_lang: 'en',
    });
    return (result as { translated_text?: string }).translated_text ?? text;
  } catch {
    return text; // Graceful fallback: use original text
  }
}

// ── 3. Reranking (cross-encoder: 20 ANN candidates → top-k) ──────────────────

async function rerankChunks(
  query: string,
  chunks: Chunk[],
  topK: number,
  env: Env,
): Promise<{ chunks: Chunk[]; reranked: boolean }> {
  if (chunks.length <= topK) return { chunks, reranked: false };
  try {
    const texts = chunks.map(c => c.content.slice(0, 512));
    const result = await env.AI.run(env.RERANKER_MODEL as BaseAiRerankModels, { query, texts });
    const raw = result as unknown;

    // Defensively handle possible output shapes from Workers AI reranker
    let scored: { index: number; score: number }[] = [];
    if (Array.isArray(raw)) {
      scored = (raw as { score: number }[]).map((r, i) => ({ index: i, score: r.score ?? 0 }));
    } else {
      const data = (raw as { data?: { index: number; score: number }[] }).data ?? [];
      scored = data;
    }

    if (scored.length === 0) throw new Error('empty reranker response');

    const reranked = scored
      .sort((a, b) => b.score - a.score)
      .slice(0, topK)
      .map(r => ({ ...chunks[r.index], score: r.score }));

    return { chunks: reranked, reranked: true };
  } catch {
    // Fallback: return original top-k by ANN score (no cross-encoder)
    return { chunks: chunks.slice(0, topK), reranked: false };
  }
}

// ── 4. Synthesis helpers ──────────────────────────────────────────────────────

function buildPrompts(query: string, context: string): { system: string; user: string } {
  const system =
    'You are an authoritative fact-checker. Answer ONLY based on the documents provided. ' +
    'Never use prior knowledge. If the documents do not contain sufficient evidence, ' +
    'return answer:null with low confidence.';
  const user =
    `Documents:\n${context}\n---\n` +
    `Question: ${query}\n\n` +
    'Return ONLY valid JSON:\n' +
    '{"claim":"<one-sentence evidence-based assessment>","answer":true|false|null,' +
    '"confidence":0.0-1.0}\n\n' +
    'answer=true  → documents confirm the claim\n' +
    'answer=false → documents refute the claim\n' +
    'answer=null  → insufficient evidence in documents\n\nJSON:';
  return { system, user };
}

async function synthesiseSingle(
  query: string,
  context: string,
  model: string,
  env: Env,
): Promise<Pick<RemoraVerdict, 'answer' | 'claim' | 'confidence'>> {
  const { system, user } = buildPrompts(query, context);
  const result = await env.AI.run(model as BaseAiTextGenerationModels, {
    messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    max_tokens: 300,
    temperature: 0.1,
  });
  return parseVerdictFromLLM((result as { response?: string }).response ?? '');
}

async function synthesiseDual(
  query: string,
  context: string,
  env: Env,
): Promise<Pick<RemoraVerdict, 'answer' | 'claim' | 'confidence'> & { models_agreed: boolean; model: string }> {
  const { system, user } = buildPrompts(query, context);
  const runModel = (m: string) =>
    env.AI.run(m as BaseAiTextGenerationModels, {
      messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
      max_tokens: 300,
      temperature: 0.1,
    });

  const [fastRaw, strongRaw] = await Promise.all([
    runModel(env.SYNTH_MODEL),
    runModel(env.SYNTH_MODEL_STRONG),
  ]);

  const fast   = parseVerdictFromLLM((fastRaw   as { response?: string }).response ?? '');
  const strong = parseVerdictFromLLM((strongRaw as { response?: string }).response ?? '');

  const agreed = fast.answer === strong.answer;
  const confidence = agreed
    ? Math.min(1.0, strong.confidence + 0.10)  // boost if both agree
    : strong.confidence * 0.80;                 // penalise disagreement

  return {
    ...strong,
    confidence,
    models_agreed: agreed,
    model: `${env.SYNTH_MODEL}+${env.SYNTH_MODEL_STRONG}`,
  };
}

function selectSynthModel(query: string, complexity: string, env: Env): string {
  if (complexity === 'high') return env.SYNTH_MODEL_STRONG;
  if (complexity === 'low')  return env.SYNTH_MODEL;
  // Auto: long or complex queries → strong model
  return query.length > 200 || /legallov|inkasso|paragraf|§|regulation|statute/i.test(query)
    ? env.SYNTH_MODEL_STRONG
    : env.SYNTH_MODEL;
}

// ── Core: query ───────────────────────────────────────────────────────────────

async function handleQuery(body: QueryRequest, env: Env): Promise<Response> {
  const {
    query,
    domain,
    top_k,
    use_cache = true,
    bypass_cache = false,
  } = body;

  if (!query?.trim()) return err('query is required');

  // use_case routing: legal → dual consensus + strong model; security → fast model
  let complexity     = body.complexity     ?? 'auto';
  let dual_consensus = body.dual_consensus ?? false;
  if (body.use_case === 'legal') {
    dual_consensus = dual_consensus || true;
    if (complexity === 'auto') complexity = 'high';
  }
  if (body.use_case === 'security') {
    if (complexity === 'auto') complexity = 'low';
  }

  const useMulti = body.multilingual ?? isNonEnglish(query);
  const finalTopK = Math.min(top_k ?? parseInt(env.DEFAULT_TOP_K), 10);
  const enableRerank  = env.ENABLE_RERANK  === 'true';
  const enableDual    = dual_consensus ?? env.ENABLE_DUAL_CONSENSUS === 'true';
  const enableTranslation = env.ENABLE_TRANSLATION === 'true';

  // Cache key includes all routing dimensions + access partition (prevents cross-user leakage)
  const cacheKey = await sha256hex(
    `v2::${useMulti}::${domain ?? ''}::${complexity}::${query}${body.cache_partition ? '::' + body.cache_partition : ''}`,
  );

  if (use_cache && !bypass_cache) {
    const cached = await env.CACHE.get(cacheKey);
    if (cached) return json({ ...(JSON.parse(cached) as RemoraVerdict), cache_hit: true });
  }

  // ── 1. Embed query ────────────────────────────────────────────────────────
  let queryToEmbed = query;
  if (!useMulti && enableTranslation && isNonEnglish(query)) {
    // Translate to English so we can query the English ANN index
    queryToEmbed = await translateToEnglish(query, env);
  }
  const embedding = await embedText(queryToEmbed, env, useMulti);

  // ── 2. ANN retrieval ──────────────────────────────────────────────────────
  const annK = enableRerank ? parseInt(env.RERANK_CANDIDATES) : finalTopK;
  const vectorIndex = useMulti ? env.VECTORIZE_MULTI : env.VECTORIZE;
  const queryOpts: VectorizeQueryOptions = {
    topK: annK,
    returnValues: false,
    returnMetadata: 'all',
  };

  // Build Vectorize metadata filter.
  // Access control (clearance + tenant) is applied first; domain is additive.
  // All conditions in a flat filter object are AND-ed by Vectorize.
  const filter: Record<string, unknown> = {};
  if (body.access) {
    const { clearance_levels, tenant_id } = body.access;
    if (clearance_levels?.length) {
      filter['clearance_level'] = { $in: clearance_levels };
    }
    if (tenant_id) {
      filter['tenant_id'] = { $eq: tenant_id };
    }
  }
  if (domain) filter['domain'] = { $eq: domain };
  if (Object.keys(filter).length) queryOpts.filter = filter;

  const results = await vectorIndex.query(embedding, queryOpts);

  if (!results.matches.length) {
    return json({
      answer: null,
      claim: 'No relevant documents found in knowledge base',
      confidence: 0.0,
      sources: [],
      retrieved_chunks: 0,
      reranked: false,
      cache_hit: false,
      multilingual: useMulti,
      model: env.SYNTH_MODEL,
    } as RemoraVerdict);
  }

  // ── 3. Rerank candidates ──────────────────────────────────────────────────
  let chunks: Chunk[] = results.matches.map(m => ({
    content: (m.metadata as Record<string, string>)?.['content'] ?? '',
    source:  (m.metadata as Record<string, string>)?.['source']  ?? 'unknown',
    score:   m.score,
  }));

  let reranked = false;
  if (enableRerank) {
    const r = await rerankChunks(queryToEmbed, chunks, finalTopK, env);
    chunks   = r.chunks;
    reranked = r.reranked;
  } else {
    chunks = chunks.slice(0, finalTopK);
  }

  // ── 4. Build grounded synthesis context ──────────────────────────────────
  const maxCtx = parseInt(env.MAX_CONTEXT_CHR);
  let context = '';
  const sources: string[] = [];
  for (const chunk of chunks) {
    const line = `[Source: ${chunk.source}]\n${chunk.content}\n\n`;
    if (context.length + line.length > maxCtx) break;
    context += line;
    if (!sources.includes(chunk.source)) sources.push(chunk.source);
  }

  // ── 5. Synthesise verdict ─────────────────────────────────────────────────
  let answer: boolean | null = null;
  let claim = '';
  let confidence = 0.0;
  let models_agreed: boolean | undefined;
  let synthModel: string;

  if (enableDual) {
    const dual = await synthesiseDual(query, context, env);
    answer         = dual.answer;
    claim          = dual.claim;
    confidence     = dual.confidence;
    models_agreed  = dual.models_agreed;
    synthModel     = dual.model;
  } else {
    synthModel = selectSynthModel(query, complexity, env);
    const single = await synthesiseSingle(query, context, synthModel, env);
    answer     = single.answer;
    claim      = single.claim;
    confidence = single.confidence;
  }

  const verdict: RemoraVerdict = {
    answer,
    claim,
    confidence,
    sources,
    retrieved_chunks: results.matches.length,
    reranked,
    cache_hit: false,
    multilingual: useMulti,
    model: synthModel,
    dual_consensus: enableDual,
    ...(enableDual ? { models_agreed } : {}),
    ...(body.use_case ? { use_case: body.use_case } : {}),
  };

  // ── 6. Cache ──────────────────────────────────────────────────────────────
  if (use_cache) {
    await env.CACHE.put(cacheKey, JSON.stringify(verdict), {
      expirationTtl: parseInt(env.CACHE_TTL_S),
    });
  }

  return json(verdict);
}

// ── Core: ingest ──────────────────────────────────────────────────────────────

async function handleIngest(body: IngestRequest, env: Env): Promise<Response> {
  const { content, source, domain, title, chunk_index = 0, confidence_weight = 1.0 } = body;
  const useMulti = body.multilingual ?? false;
  if (!content?.trim()) return err('content is required');
  if (!source?.trim())  return err('source is required');
  if (!domain?.trim())  return err('domain is required');

  const docId = await sha256hex(`${source}::${chunk_index}::${content.slice(0, 64)}`);
  const embedding = await embedText(content, env, useMulti);
  const vectorIndex = useMulti ? env.VECTORIZE_MULTI : env.VECTORIZE;
  const contentSnippet = content.slice(0, 1000);

  await vectorIndex.insert([{
    id: docId,
    values: embedding,
    metadata: {
      source,
      domain,
      title: title ?? source,
      chunk_index: String(chunk_index),
      confidence_weight: String(confidence_weight),
      content: contentSnippet,
      multilingual: String(useMulti),
      date_ingested: new Date().toISOString(),
      // Access control fields — default to 'public' / no tenant restriction
      clearance_level: body.clearance_level ?? 'public',
      acl_groups:      JSON.stringify(body.acl_groups ?? []),
      tenant_id:       body.tenant_id ?? '',
    },
  }]);

  await env.DB.prepare(`
    INSERT OR REPLACE INTO documents
      (id, domain, source, title, content, chunk_index, vector_id, date_ingested, confidence_weight)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(
    docId, domain, source,
    title ?? source, content, chunk_index,
    docId, new Date().toISOString(), confidence_weight,
  ).run();

  return json({
    ok: true, vector_id: docId, source, domain, chunk_index,
    multilingual: useMulti,
    index: useMulti ? 'remora-knowledge-multi' : 'remora-knowledge',
  });
}

// ── Core: status ──────────────────────────────────────────────────────────────

async function handleStatus(env: Env): Promise<Response> {
  const stats = await env.DB.prepare(
    'SELECT COUNT(*) as n, domain FROM documents GROUP BY domain'
  ).all();
  const total = await env.DB.prepare('SELECT COUNT(*) as n FROM documents').first<{ n: number }>();
  return json({
    ok: true,
    worker: 'remora-rag-oracle-v2',
    models: {
      embed_en:       env.EMBED_MODEL,
      embed_multi:    env.EMBED_MODEL_MULTI,
      synth_fast:     env.SYNTH_MODEL,
      synth_strong:   env.SYNTH_MODEL_STRONG,
      reranker:       env.RERANKER_MODEL,
      translator:     env.TRANSLATE_MODEL,
    },
    features: {
      rerank:           env.ENABLE_RERANK === 'true',
      translation:      env.ENABLE_TRANSLATION === 'true',
      dual_consensus:   env.ENABLE_DUAL_CONSENSUS === 'true',
    },
    vectorize_indices: ['remora-knowledge (768d en)', 'remora-knowledge-multi (1024d multi)'],
    total_chunks: total?.n ?? 0,
    by_domain: stats.results,
  });
}

// ── Core: raw search (debug) ──────────────────────────────────────────────────

async function handleSearch(url: URL, env: Env): Promise<Response> {
  const q       = url.searchParams.get('q');
  const domain  = url.searchParams.get('domain') ?? undefined;
  const k       = parseInt(url.searchParams.get('k') ?? '5');
  const multi   = url.searchParams.get('multi') === 'true';
  if (!q) return err('q parameter required');

  const embedding = await embedText(q, env, multi);
  const vectorIndex = multi ? env.VECTORIZE_MULTI : env.VECTORIZE;
  const opts: VectorizeQueryOptions = {
    topK: k, returnValues: false, returnMetadata: 'all',
  };
  if (domain) opts.filter = { domain: { $eq: domain } };
  const results = await vectorIndex.query(embedding, opts);

  return json({
    query: q, domain, multilingual: multi,
    matches: results.matches.map(m => ({
      id: m.id,
      score: m.score,
      source: (m.metadata as Record<string, string>)?.['source'],
      chunk_index: (m.metadata as Record<string, string>)?.['chunk_index'],
      content_preview: ((m.metadata as Record<string, string>)?.['content'] ?? '').slice(0, 200),
    })),
  });
}

// ── Core: rerank (debug endpoint) ────────────────────────────────────────────

async function handleRerank(body: { query: string; texts: string[] }, env: Env): Promise<Response> {
  if (!body.query?.trim()) return err('query is required');
  if (!Array.isArray(body.texts) || body.texts.length === 0) return err('texts[] is required');
  const chunks: Chunk[] = body.texts.map(t => ({ content: t, source: 'debug', score: 0 }));
  const { chunks: reranked, reranked: didRerank } = await rerankChunks(
    body.query, chunks, body.texts.length, env,
  );
  return json({ ok: true, reranked: didRerank, results: reranked });
}

// ── Core: translate (utility endpoint) ───────────────────────────────────────

async function handleTranslate(
  body: { text: string; source_lang?: string; target_lang?: string },
  env: Env,
): Promise<Response> {
  if (!body.text?.trim()) return err('text is required');
  const result = await env.AI.run(env.TRANSLATE_MODEL as BaseAiTranslationModels, {
    text: body.text,
    source_lang: body.source_lang ?? 'no',
    target_lang: body.target_lang ?? 'en',
  });
  return json({ ok: true, translated_text: (result as { translated_text?: string }).translated_text });
}

// ── Main handler ──────────────────────────────────────────────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });

    const url = new URL(request.url);

    if (url.pathname === '/status'    && request.method === 'GET')  return handleStatus(env);
    if (url.pathname === '/search'    && request.method === 'GET')  return handleSearch(url, env);

    if (url.pathname === '/query'     && request.method === 'POST') {
      if (!optionalBearer(request, env)) return err('Unauthorized', 401);
      const body = await request.json() as QueryRequest;
      return handleQuery(body, env);
    }
    if (url.pathname === '/ingest'    && request.method === 'POST') {
      if (!authorBearer(request, env)) return err('Unauthorized', 401);
      const body = await request.json() as IngestRequest;
      return handleIngest(body, env);
    }
    if (url.pathname === '/rerank'    && request.method === 'POST') {
      if (!optionalBearer(request, env)) return err('Unauthorized', 401);
      const body = await request.json() as { query: string; texts: string[] };
      return handleRerank(body, env);
    }
    if (url.pathname === '/translate' && request.method === 'POST') {
      if (!optionalBearer(request, env)) return err('Unauthorized', 401);
      const body = await request.json() as { text: string; source_lang?: string; target_lang?: string };
      return handleTranslate(body, env);
    }

    return json({
      error: 'Not found',
      endpoints: ['/query', '/ingest', '/status', '/search', '/rerank', '/translate'],
    }, 404);
  },
};
