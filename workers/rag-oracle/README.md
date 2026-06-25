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
| `POST` | `/ingest` | Add document chunks to the knowledge base (requires `ORACLE_SECRET`) |
| `GET` | `/status` | Health check and index statistics |

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
- `"general"` — English knowledge base (bge-base-en-v1.5, 768d)
- `"legal"` / `"norwegian"` — Multilingual index (bge-m3, 1024d)
- `"science"` — English knowledge base, strong model preferred
- `"auto"` — inferred from query language

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
npx wrangler secret put ORACLE_SECRET   # Bearer token for /ingest endpoint
```
