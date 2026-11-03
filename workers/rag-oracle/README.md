# REMORA RAG Oracle Worker

Cloudflare Worker providing retrieval-augmented generation (RAG) over the REMORA knowledge base.

**Live endpoint:** `https://remora-rag-oracle.razorsharp.workers.dev`

## What it does

Accepts a natural-language query, retrieves the most relevant document chunks from Vectorize, reranks them with a cross-encoder, and synthesises a grounded answer using an LLM.

```
POST /query
  └── Embed query (bge-base-en-v1.5 or bge-m3 for multilingual)
  └── ANN search in Vectorize (top-20 candidates)
  └── Rerank via bge-reranker-base (→ top-5)
  └── Synthesise answer (LLaMA-3.1-8B or 3.3-70B, routed by complexity)
  └── Return: { answer, sources, confidence, use_case }
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/query` | Full RAG pipeline: retrieve → rerank → synthesise |
| `GET` | `/search` | Raw vector search only (no synthesis) |
| `POST` | `/ingest` | Add document chunks to the knowledge base |
| `GET` | `/status` | Health check and index statistics (unauthenticated) |

Every route except `GET /status` requires `Authorization: Bearer <ORACLE_SECRET>`. With the secret unset the worker refuses them with 503 rather than serving them unauthenticated (SR-02/SR-04).

Retrieval sees only the part of a chunk that fits the embedding model's input window: about 380 estimated tokens for `bge-base-en-v1.5` (512 real tokens), and far more for `bge-m3`. The `/ingest` response reports `embedding.truncated`, `embedded_chars` and `content_chars`. When `truncated` is true, split the chunk, because text past `embedded_chars` is stored and returned as context but cannot be found by search. Before W-08 every input was cut at 512 characters, with no signal.

A chunk's vector id is its slot: `tenant_id`, `source` and `chunk_index`. Re-ingesting the same slot replaces it, and an ingest that names its own tenant cannot reach another tenant's slot (RMR-SEC-0006). Because `tenant_id` is whatever the caller sends, any holder of `ORACLE_SECRET` can name another tenant, or the shared empty tenant, and replace that slot's vector and D1 row, including its clearance and ACL fields. Only binding the tenant to the credential closes that (RMR-SEC-0004, open). Vectors ingested before 2026-11-02 carry ids in the old format (source, chunk index and the first 64 characters of content), so re-ingesting them adds a new vector next to the old one. Delete the old ids, or rebuild the index, when you re-ingest a corpus. `tenant_id` and clearance are still asserted by the caller, not bound to the credential (RMR-SEC-0004), so this index is not a multi-tenant boundary.

### POST /query

```json
{
  "query": "What is the minimum notice period under Norwegian debt collection law?",
  "use_case": "legal",
  "top_k": 5,
  "complexity": "auto"
}
```

`use_case` routes the query to the correct vector index and synthesis model:
- `"general"`, English knowledge base (bge-base-en-v1.5, 768d)
- `"legal"` / `"norwegian"`, Multilingual index (bge-m3, 1024d)
- `"science"`, English knowledge base, strong model preferred
- `"auto"`, inferred from query language

## Bindings

| Binding | Type | Purpose |
|---------|------|---------|
| `AI` | Workers AI | Embedding, reranking, synthesis, translation |
| `VECTORIZE` | Vectorize | English knowledge index (768d, bge-base-en-v1.5) |
| `VECTORIZE_MULTI` | Vectorize | Multilingual index (1024d, bge-m3) |
| `DB` | D1 | Document metadata and source URLs |
| `CACHE` | KV | Response cache (24 h TTL) |

## Deploy

```bash
cd workers/rag-oracle
npm install
npx wrangler deploy
```

## Ingest corpus

```bash
# From repo root — ingest a URL into the knowledge base
python scripts/ingest_corpus.py --url <URL> --domain legal
```

## Configuration

Key environment variables (set in `wrangler.toml`):

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBED_MODEL` | `@cf/baai/bge-base-en-v1.5` | English embedding model (768d) |
| `EMBED_MODEL_MULTI` | `@cf/baai/bge-m3` | Multilingual embedding model (1024d) |
| `SYNTH_MODEL` | `@cf/meta/llama-3.1-8b-instruct` | Fast synthesis (low complexity) |
| `SYNTH_MODEL_STRONG` | `@cf/meta/llama-3.3-70b-instruct` | Accurate synthesis (high complexity) |
| `RERANKER_MODEL` | `@cf/baai/bge-reranker-base` | Cross-encoder reranker |
| `ENABLE_RERANK` | `"true"` | Enable reranking pass |
| `DEFAULT_TOP_K` | `"5"` | Final results after reranking |

## Secret

```bash
npx wrangler secret put ORACLE_SECRET   # Bearer token for every route except GET /status
```
