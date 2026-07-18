# REMORA Law Search Worker

Cloudflare Worker providing full-text and semantic search over Norwegian statutes and court decisions.

**Live endpoint:** `https://remora-law-search.razorsharp.workers.dev`

## What it does

Exposes the `norges-lover-legal-intel` database (D1 + Vectorize) to the REMORA MCP server. Handles two tasks:

1. **Citation verification**: checks whether a specific court decision (e.g. `HR-2015-2386-A`) exists in the database.
2. **Statute search**: retrieves relevant sections from Norwegian law given a free-text query.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Semantic search over Norwegian statutes |
| `POST` | `/verify-citation` | Look up a court decision reference in D1 |
| `GET` | `/status` | Health check and index statistics |

### POST /search

```json
{
  "query": "maksimalt inkassosalær ved krav under 500 kr",
  "top_k": 5
}
```

Returns ranked statute excerpts with section references and relevance scores.

### POST /verify-citation

```json
{
  "citation": "HR-2015-2386-A"
}
```

Returns:

```json
{
  "citation": "HR-2015-2386-A",
  "found_in_d1": false,
  "verdict": "NOT_FOUND",
  "oracle_verdict": "LIKELY_HALLUCINATED"
}
```

## Bindings

| Binding | Type | Purpose |
|---------|------|---------|
| `AI` | Workers AI | Embedding via bge-m3 (1024d multilingual) |
| `LAW_INDEX` | Vectorize | Norwegian statute vector index (1024d) |
| `LAW_DB` | D1 | Court decisions and statute metadata |

## Deploy

```bash
cd workers/law-search
npm install
npx wrangler deploy
```

## Used by

- `remora_norwegian_law_search` MCP tool, semantic statute search
- `remora_verify_legal_citations` MCP tool, hallucination detection for court references
- `scripts/demo_norwegian_law.py`, live citation verification demo
- `tests/test_norwegian_law.py`, offline test suite (uses cached responses)
