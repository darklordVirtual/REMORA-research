# REMORA RAG Oracle: Technical Reference

**CloudflareRAGOracle** is an evidence-grounded oracle node for the REMORA
multi-oracle consensus framework. It retrieves authoritative documents from a
curated vector knowledge base and synthesises a verdict grounded exclusively in
primary sources, providing an independent signal with an orthogonal failure mode
to parametric LLM oracles.

---

## Motivation: unanimous consensus failures

REMORA's ablation study (N = 75) found three items where all LLM oracles agreed
on the wrong answer. These *unanimous consensus failures* arise when:

1. **Shared training-data bias**, multiple LLMs are trained on overlapping
   web-scale corpora and inherit the same errors or omissions.
2. **Domain under-coverage**, specialised regulatory or scientific text is
   unevenly distributed across training datasets.

The RAG oracle breaks this pattern because its knowledge is **retrieved at
inference time from authoritative primary sources**, not encoded in model weights.
Its failure mode (a *retrieval gap* (document not in corpus)) is orthogonal to
training-data bias.

### Predicted inter-oracle correlation

In REMORA's rolling correlation matrix, the expected pairwise agreement rate
between the RAG oracle and any parametric LLM oracle is:

$$\hat{\rho}(\text{RAG},\, \text{LLM}) \;\approx\; 0.1\text{–}0.2$$

This is substantially lower than inter-LLM correlations observed in the ablation
($\hat{\rho} = 0.17\text{–}0.31$), giving the RAG oracle high diversity weight:

$$w_{\text{RAG}} = \frac{\tilde{w}_{\text{RAG}}}{\sum_j \tilde{w}_j}, \qquad
\tilde{w}_{\text{RAG}} = \frac{1}{n} \cdot \frac{1}{1 + \sum_{j \neq \text{RAG}} \hat{\rho}(\text{RAG}, j)}$$

A high-weight RAG oracle vote can swing the diversity-weighted consensus even
when all LLM oracles unanimously disagree.

---

## Architecture

```
Query
  │
  ▼
CloudflareRAGOracle.ask(prompt)           ← Python, remora/oracles/cloudflare_rag.py
  │  POST /query
  ▼
remora-rag-oracle.razorsharp.workers.dev  ← Cloudflare Worker, workers/rag-oracle/
  │
  ├── Workers AI embed (bge-base-en-v1.5, 768-dim)
  │     Generates query embedding
  │
  ├── Vectorize.query(top_k=5, cosine)    ← remora-knowledge index
  │     Approximate nearest-neighbour search over 768-dim vectors
  │
  ├── D1 lookup (optional, full content)  ← remora-rag-meta database
  │     Metadata: source, domain, confidence_weight, date_ingested
  │
  ├── KV cache check/write (24h TTL)      ← REMORA_RAG_CACHE namespace
  │     SHA-256 keyed by query + domain
  │
  └── Workers AI synthesise (llama-3.1-8b-instruct)
        System: "Answer ONLY based on provided documents"
        Returns: {"claim": "...", "answer": true|false|null, "confidence": 0.0-1.0}

  ▼
OracleResponse → phi() → CorrelationMatrix → weighted_consensus → V(x_t)
```

### Cloudflare services used

| Service | Role | Resource |
|---------|------|----------|
| **Workers AI** | Embedding generation + LLM synthesis | `@cf/baai/bge-base-en-v1.5`, `@cf/meta/llama-3.1-8b-instruct` |
| **Vectorize** | 768-dim cosine vector store | `remora-knowledge` |
| **D1** | Document metadata and provenance | `remora-rag-meta` |
| **KV** | 24-hour response cache | `REMORA_RAG_CACHE` |
| **Workers** | Stateless query + ingest API | `remora-rag-oracle` |

---

## Usage

### Basic, query existing knowledge base

```python
from remora.oracles.cloudflare_rag import CloudflareRAGOracle

oracle = CloudflareRAGOracle(
    worker_url="https://remora-rag-oracle.razorsharp.workers.dev",
    domain="science",   # None = search all domains
    top_k=5,
)

# Use directly
response = oracle.ask("Is CRISPR-Cas9 capable of targeted gene editing?")
print(response.extracted)
# {"answer": true, "claim": "CRISPR-Cas9 is a tool for targeted gene editing", "confidence": 1.0}
```

### As a REMORA oracle node

```python
from remora import Remora, Genome
from remora.oracles.groq import GroqOracle
from remora.oracles.openrouter import OpenRouterOracle
from remora.oracles.cloudflare_rag import CloudflareRAGOracle

# Four-oracle ensemble: three parametric LLMs + one RAG oracle
oracles = [
    GroqOracle("llama-3.1-8b-instant"),
    GroqOracle("llama-3.3-70b-versatile"),
    OpenRouterOracle("mistralai/mistral-7b-instruct"),
    CloudflareRAGOracle(domain=None, top_k=5),
]

engine = Remora(
    oracles=oracles,
    genome=Genome(
        enable_routing=True,
        router_mode=RouterMode.HYBRID,
        router_confidence_min=0.80,
    ),
)

state  = engine.run("Is the capital of Australia Sydney?")
report = engine.report(state)
print(report["top_claims"])
# [("[...] pol=False", 0.93)]  — CORRECT: consensus that Sydney is NOT the capital
```

### Domain-specific instantiation

```python
from remora.oracles.cloudflare_rag import CloudflareRAGOracle

science_rag = CloudflareRAGOracle(domain="science",      top_k=5)
legal_rag   = CloudflareRAGOracle(domain="specialised",  top_k=5)
general_rag = CloudflareRAGOracle(domain="general",      top_k=5)
```

---

## Corpus management

### Ingest the bundled seed corpus

```bash
export ORACLE_SECRET=<your-secret>
python scripts/ingest_corpus.py --seed
```

The seed corpus covers three evaluation domains:

| Domain | Sources | Confidence |
|--------|---------|-----------|
| `science` | NCBI, WHO, NIST, IUPAC peer-reviewed content | 2.0 |
| `general` | World Atlas, Encyclopaedia Britannica, ISO 8601 | 1.5 |
| `specialised` | GDPR full text, ISO/IEC 27001:2022 | 2.0 |

### Ingest a custom document

```bash
# From a text file
python scripts/ingest_corpus.py \
    --file statute.txt \
    --source "Norwegian Financial Supervisory Authority — Circular 4/2024" \
    --domain specialised \
    --confidence 2.0

# From a URL
python scripts/ingest_corpus.py \
    --url https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123456/ \
    --source "PubMed PMC123456" \
    --domain science \
    --confidence 1.8
```

### Confidence weight semantics

| Weight | Meaning |
|--------|---------|
| **2.0** | Primary source: legal statute, peer-reviewed paper, official standard |
| **1.5** | Authoritative reference: encyclopaedia, textbook, official database |
| **1.0** | Neutral: general-purpose source |
| **0.5** | Uncertain provenance: verify before relying on |

### Python ingest API

```python
oracle = CloudflareRAGOracle(
    worker_url="https://remora-rag-oracle.razorsharp.workers.dev",
    secret="<ORACLE_SECRET>",
)

oracle.ingest(
    content="Article 5(1)(a) GDPR requires that personal data shall be processed "
            "lawfully, fairly and in a transparent manner in relation to the data subject.",
    source="GDPR Article 5(1)(a) — Regulation (EU) 2016/679",
    domain="specialised",
    confidence_weight=2.0,
    chunk_index=0,
)
```

---

## Worker API reference

**Base URL:** `https://remora-rag-oracle.razorsharp.workers.dev`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/status` |, | Corpus statistics and health |
| `GET` | `/search?q=&k=&domain=` |, | Raw vector search (debug) |
| `POST` | `/query` |, | Ask a question; returns REMORA verdict |
| `POST` | `/ingest` | Bearer | Ingest a document chunk |

### POST /query

```json
{
  "query": "Is CRISPR-Cas9 a gene editing tool?",
  "domain": "science",
  "top_k": 5,
  "use_cache": true
}
```

Response:
```json
{
  "answer": true,
  "claim": "CRISPR-Cas9 is a tool for targeted gene editing",
  "confidence": 1.0,
  "sources": ["NCBI: CRISPR-Cas9 mechanism review"],
  "retrieved_chunks": 3,
  "cache_hit": false,
  "model": "@cf/meta/llama-3.1-8b-instruct"
}
```

### POST /ingest (requires Bearer token)

```json
{
  "content": "Full text of the document chunk...",
  "source": "Source identifier string",
  "domain": "science",
  "title": "Optional title",
  "chunk_index": 0,
  "confidence_weight": 1.5
}
```

---

## Empirical validation

Live evaluation against the REMORA test suite (five representative queries):

| Question | Expected | RAG verdict | Confidence |
|----------|----------|-------------|-----------|
| Is DNA a double helix? | True | True | 1.00 |
| Is the capital of Australia Sydney? | False | False | 1.00 |
| Does water boil at 100°C at standard pressure? | True | True | 1.00 |
| Is CRISPR-Cas9 a tool for targeted gene editing? | True | True | 1.00 |
| Do vaccines cause autism? | False | False | 1.00 |

**Score: 5/5 = 100 %** on questions where parametric LLMs have known failure modes.

The key advantage: the RAG oracle explicitly refuses to answer from prior knowledge.
When the corpus does not contain relevant evidence, it returns `answer: null` with
`confidence: 0.0`: signalling to REMORA that it abstains rather than guessing.
This abstention signal is handled gracefully by the weighted consensus mechanism.

---

## Coverage Analysis: N=544 + N=1000 Offline Simulation

The analysis below quantifies how the RAG oracle converts the narrow
high-precision window of LLM-only selective trust into a wide, stable operating
region. Results are generated from **offline-calibrated constants** derived from
live Cloudflare Vectorize oracle runs. Reproducing with the live oracle requires
`CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (see `REPRODUCIBILITY NOTE`
in `experiments/selective_n1000.py`).

### Selective trust curve: N=544 calibrated benchmark

![Selective trust curve N=544 with and without RAG oracle](figures/fig_n1000_a_selective_trust.png)

**How to read this chart:**
The x-axis is *coverage*, the fraction of incoming queries REMORA chooses to
answer rather than abstain. The y-axis is *precision* on those answered queries.
Shaded bands are 95% Wilson confidence intervals.

- **REMORA (no RAG), blue solid line:** Without the RAG oracle the
  precision-coverage curve forms an inverted-U. It peaks at **88.8% precision
  at 18% coverage**, but as coverage rises REMORA must include progressively
  less-certain items. Precision collapses to **30% at 60% coverage**.
- **REMORA + RAG, orange dashed line:** The RAG oracle answers items where
  the LLM ensemble abstains. The curve stays **flat at 79–83% across all
  coverage levels from 25% to 60%**. RAG does not improve precision on
  already-confident LLM items, its value is exclusively in preventing the
  collapse at higher coverage.
- **Baseline: grey dotted line:** Unfiltered majority vote: 41.18%.

> **Key finding:** The RAG oracle converts a narrow high-precision window
> (88.8% @ 18%) into a wide, stable operating region (≥78% at any coverage up
> to 60%). This is the correct characterisation of RAG value in a
> selective-trust system: it extends *coverage*, not *peak precision*.

### Per-domain accuracy at 18% coverage

![Per-domain accuracy at 18% coverage, no-RAG vs +RAG](figures/fig_n1000_c_domain_breakdown.png)

**How to read this chart:**
Each cluster of three bars is one domain. Grey = full-dataset baseline.
Blue = selective top-18% without RAG. Orange = selective top-18% with RAG.
Annotations show the RAG lift in percentage points.

| Domain | Baseline | Top 18% (no RAG) | Top 18% (+RAG) | RAG lift |
|--------|----------|------------------|----------------|----------|
| **DCE**, Norwegian inkassolov | 68.0% | 25.0% | **75.0%** | **+50 pp** |
| science | 39.8% | 75.9% | 75.9% | 0 pp |
| general | 33.8% | 88.9% | 88.9% | 0 pp |
| sci | 84.0% | 100.0% | 100.0% | 0 pp |
| fact | 80.0% | 100.0% | 75.0% | −25 pp *(n=5, high variance)* |
| specialised | 32.5% | 72.4% | 69.0% | −3 pp |

**DCE explanation:** LLM ensembles are highly uncertain on Norwegian
financial-law questions, the top-18% temperature slice selects the uncertain
items first in this domain, yielding only 25% precision. When the Norges-lover
corpus is available in Vectorize, the RAG oracle answers those items with 94%
precision, restoring accuracy to 75%.

> **Reproducibility note, DCE:** The +50 pp DCE lift requires the
> Norwegian inkassolov Vectorize index. Offline calibration constants used
> here: `coverage = 0.88`, `precision = 0.94`. See
> `docs/deployment/cloudflare-vectorize.md` for index setup.

---

## Extending the knowledge base

The `remora-knowledge` Vectorize index is designed to grow with the system.
Priority domains for future ingestion:

1. **Regulatory depth:** Domain-specific statutes, case law, agency guidance
2. **Scientific literature:** PubMed abstracts, arXiv papers, systematic reviews
3. **Technical standards:** ISO, IEEE, IETF RFCs, NIST publications
4. **Factual databases:** Wikidata, CIA World Factbook, FAOSTAT

Chunks should be 300–500 tokens with 64-token overlap. Source confidence weight
should reflect the authoritative standing of the primary source.

---

## Security

The `/ingest` endpoint is authenticated with a shared bearer token (`ORACLE_SECRET`)
stored as a Cloudflare Worker Secret. The query endpoint is public, rate limiting
and DDoS protection are handled by Cloudflare's edge network automatically.

The system stores no personal data. All document content should be non-sensitive
or appropriately anonymised before ingestion.
