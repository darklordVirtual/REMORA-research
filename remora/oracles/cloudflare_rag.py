# Author: Stian Skogbrott
# License: Apache-2.0
"""
CloudflareRAGOracle — evidence-grounded oracle node for REMORA.

Retrieval-Augmented Generation oracle backed by the Cloudflare platform:
    Vectorize  — approximate nearest-neighbour vector search (768-dim cosine)
    Workers AI — embedding generation (bge-base-en-v1.5) and LLM synthesis
    D1         — document metadata and provenance store
    KV         — 24-hour response cache (keyed by SHA-256 of query+domain)
    AI Gateway — observability, rate limiting, cost tracking (account-level)

Orthogonality guarantee
-----------------------
Parametric LLM oracles (Groq, OpenRouter) encode knowledge in model weights
trained on web-scale corpora. They fail systematically when:
  (a) training data is biased or incomplete for a domain, or
  (b) multiple providers share the same base model or dataset.

The RAG oracle retrieves from a curated, authoritative corpus at inference time.
Its failure mode is a *retrieval gap* (document not in the corpus), which is
largely orthogonal to training-data bias. In REMORA's correlation matrix,
expected inter-oracle correlation ρ(RAG, LLM) ≈ 0.1–0.2, giving the RAG
oracle high diversity weight and strong influence on contested verdicts.

Usage
-----
    from remora.oracles.cloudflare_rag import CloudflareRAGOracle

    oracle = CloudflareRAGOracle(
        worker_url="https://remora-rag-oracle.razorsharp.workers.dev",
        domain="science",   # None = search all domains
        top_k=5,
    )
    response = oracle.ask("Is CRISPR-Cas9 capable of targeted gene editing?")
    print(response.extracted)  # {"answer": true, "claim": "...", "confidence": 0.91}
"""
from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

import os

from remora.adapters.identity import AccessContext
from remora.core import Oracle

logger = logging.getLogger(__name__)

# Default Worker endpoint — override with REMORA_RAG_WORKER_URL env variable.
# The built-in default points to the reference deployment; replace with your own
# Cloudflare Worker URL before deploying to production.
DEFAULT_WORKER_URL = os.environ.get(
    "REMORA_RAG_WORKER_URL",
    "https://remora-rag-oracle.razorsharp.workers.dev",
)


class CloudflareRAGOracle(Oracle):
    """
    Evidence-grounded oracle node that retrieves authoritative documents
    from Cloudflare Vectorize and synthesises a REMORA-compatible verdict
    via Workers AI.

    Parameters
    ----------
    worker_url : str
        URL of the deployed remora-rag-oracle Cloudflare Worker.
    domain : str or None
        Restrict retrieval to a specific knowledge domain:
        ``'specialised'`` | ``'science'`` | ``'general'`` | custom tag.
        ``None`` searches across all domains.
    top_k : int
        Number of nearest-neighbour document chunks to retrieve (default 5).
    use_cache : bool
        Whether to read/write the 24-hour KV response cache (default True).
    secret : str or None
        Bearer token for authenticated Worker endpoints (ingest, admin).
    timeout_s : int
        HTTP request timeout in seconds (default 45 — Workers AI can be slow).
    """

    def __init__(
        self,
        worker_url: str = DEFAULT_WORKER_URL,
        domain: Optional[str] = None,
        top_k: int = 5,
        use_cache: bool = True,
        secret: Optional[str] = None,
        timeout_s: int = 45,
        # ── V2 routing parameters ──────────────────────────────────────────
        # complexity: 'auto' | 'low' (8B fast-path) | 'high' (70B accurate)
        complexity: str = "auto",
        # multilingual: None = auto-detect from query text; True = bge-m3 + multi index
        multilingual: Optional[bool] = None,
        # rerank: True = fetch 20 ANN candidates, rerank via cross-encoder to top_k
        rerank: bool = True,
        # dual_consensus: True = run 8B + 70B in parallel, boost confidence when they agree
        dual_consensus: bool = False,
        # access_context: optional ABAC context — when set, Vectorize queries are filtered
        # by clearance level + tenant_id and the KV cache is partitioned per identity.
        access_context: Optional["AccessContext"] = None,
    ) -> None:
        self._worker_url = worker_url.rstrip("/")
        self._domain = domain
        self._top_k = max(1, min(top_k, 10))
        self._use_cache = use_cache
        self._secret = secret
        self._timeout = timeout_s
        self._complexity = complexity
        self._multilingual = multilingual
        self._rerank = rerank
        self._dual_consensus = dual_consensus
        self._access_context = access_context
        self._ssl_ctx = ssl.create_default_context()

    def with_access(self, access_context: "AccessContext") -> "CloudflareRAGOracle":
        """Return a new oracle instance scoped to *access_context*.

        The original instance is unchanged (immutable pattern, thread-safe).
        The returned oracle enforces clearance-level and tenant-id filtering
        on every query and partitions the KV cache by identity.

        Example::

            base_oracle = CloudflareRAGOracle(domain="specialised")
            user_oracle = base_oracle.with_access(
                AccessContext.from_identity(jwt_adapter.validate(token))
            )
            response = user_oracle.ask(prompt)
        """
        return CloudflareRAGOracle(
            worker_url=self._worker_url,
            domain=self._domain,
            top_k=self._top_k,
            use_cache=self._use_cache,
            secret=self._secret,
            timeout_s=self._timeout,
            complexity=self._complexity,
            multilingual=self._multilingual,
            rerank=self._rerank,
            dual_consensus=self._dual_consensus,
            access_context=access_context,
        )

    @property
    def domain(self) -> Optional[str]:
        """Return the active retrieval domain (None means search all domains)."""
        return self._domain

    def set_domain(self, domain: Optional[str]) -> None:
        """Set retrieval domain for subsequent queries."""
        self._domain = domain

    def set_complexity(self, complexity: str) -> None:
        """'auto' | 'low' | 'high' — controls which synthesis model the Worker uses."""
        if complexity not in ("auto", "low", "high"):
            raise ValueError(f"complexity must be 'auto', 'low', or 'high', got {complexity!r}")
        self._complexity = complexity

    # ── Oracle interface ───────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        domain_tag = self._domain or "all"
        suffix = []
        if self._rerank:          suffix.append("rerank")
        if self._dual_consensus:  suffix.append("dual")
        if self._multilingual:    suffix.append("multi")
        if self._complexity != "auto": suffix.append(self._complexity)
        tag = "+".join(suffix) if suffix else "std"
        return f"cloudflare_rag/{domain_tag}:{tag}"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        """
        Retrieve evidence and synthesise a verdict.

        Returns (raw_json_string, cost_usd, tokens_used).
        cost_usd is 0.0 because Workers AI is billed at account level;
        tokens_used is estimated from response length.
        """
        payload: dict = {
            "query":          prompt,
            "domain":         self._domain,
            "top_k":          self._top_k,
            "use_cache":      self._use_cache,
            "complexity":     self._complexity,
            "dual_consensus": self._dual_consensus,
        }
        if self._multilingual is not None:
            payload["multilingual"] = self._multilingual
        # ── Access control (optional) ────────────────────────────────────
        if self._access_context is not None:
            ctx = self._access_context
            payload["access"] = {
                "clearance_levels": ctx.allowed_clearances(),
                "acl_groups":       list(ctx.acl_groups),
                "tenant_id":        ctx.tenant_id,
            }
            # Partition cache key by identity to prevent cross-user leakage.
            # The Worker appends this to its own SHA-256 cache key.
            payload["cache_partition"] = (
                f"{ctx.clearance_level}"
                f":{':'.join(sorted(ctx.acl_groups))}"
                f":{ctx.tenant_id or ''}"
            )
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._worker_url}/query",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "REMORA-RAGOracle/1.0"},
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=self._timeout) as r:
                data: dict = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            logger.warning("RAG oracle HTTP %d: %s", exc.code, exc.read().decode("utf-8", "replace")[:200])
            return json.dumps({"answer": None, "claim": f"HTTP {exc.code}", "confidence": 0.0}), 0.0, 0.0
        except Exception as exc:
            logger.error("RAG oracle error: %s", exc)
            return json.dumps({"answer": None, "claim": str(exc), "confidence": 0.0}), 0.0, 0.0

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "RAG oracle: answer=%s conf=%.2f chunks=%d cache=%s latency=%.0fms",
            data.get("answer"),
            data.get("confidence", 0),
            data.get("retrieved_chunks", 0),
            data.get("cache_hit", False),
            latency_ms,
        )

        # Return a REMORA-compatible JSON string
        verdict_str = json.dumps({
            "answer":           data.get("answer"),
            "claim":            data.get("claim", ""),
            "confidence":       data.get("confidence", 0.0),
            "reranked":         data.get("reranked", False),
            "multilingual":     data.get("multilingual", False),
            "models_agreed":    data.get("models_agreed"),
            "retrieved_chunks": data.get("retrieved_chunks", 0),
        })
        token_estimate = len(verdict_str) // 4
        return verdict_str, 0.0, float(token_estimate)

    # ── Ingest helpers (not part of Oracle ABC) ────────────────────────────────

    def ingest(
        self,
        content: str,
        source: str,
        domain: str,
        title: Optional[str] = None,
        chunk_index: int = 0,
        confidence_weight: float = 1.0,
        multilingual: Optional[bool] = None,
        # ── Access control metadata ─────────────────────────────────────
        # These values are stored as Vectorize metadata and used to filter
        # retrieval results at query time.
        clearance_level: str = "public",        # "public"|"internal"|"restricted"|"secret"
        acl_groups: Optional[list[str]] = None,  # e.g. ["finance", "legal"]
        tenant_id: Optional[str] = None,         # multi-tenant org boundary
    ) -> dict:
        """
        Ingest a document chunk into the knowledge base.

        confidence_weight should reflect source authority:
            2.0 — primary legal statute or peer-reviewed paper
            1.5 — authoritative reference (e.g., Wikipedia FA, textbook)
            1.0 — neutral (default)
            0.5 — uncertain provenance

        Returns the Worker's response including the assigned vector_id.
        """
        if not self._secret:
            raise ValueError("CloudflareRAGOracle.ingest() requires secret= to be set")

        payload: dict = {
            "content":           content,
            "source":            source,
            "domain":            domain,
            "title":             title,
            "chunk_index":       chunk_index,
            "confidence_weight": confidence_weight,
            "clearance_level":   clearance_level,
        }
        if acl_groups is not None:
            payload["acl_groups"] = acl_groups
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        if multilingual is not None:
            payload["multilingual"] = multilingual
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._worker_url}/ingest",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._secret}",
                "User-Agent": "REMORA-RAGOracle/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=60) as r:
            return json.loads(r.read())

    def _get(self, path: str, timeout: int = 15) -> dict:
        """Authenticated GET helper with proper headers."""
        headers = {"User-Agent": "REMORA-RAGOracle/1.0", "Accept": "application/json"}
        if self._secret:
            headers["Authorization"] = f"Bearer {self._secret}"
        req = urllib.request.Request(f"{self._worker_url}{path}", headers=headers, method="GET")
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=timeout) as r:
            return json.loads(r.read())

    def status(self) -> dict:
        """Return Worker health and corpus statistics."""
        return self._get("/status")

    def search(self, query: str, k: int = 5, multilingual: Optional[bool] = None) -> list[dict]:
        """
        Debug: raw vector search without LLM synthesis.
        Returns the top-k nearest chunks with similarity scores.
        """
        use_multi = multilingual if multilingual is not None else self._multilingual
        path = f"/search?q={urllib.parse.quote(query)}&k={k}"
        if self._domain:
            path += f"&domain={urllib.parse.quote(self._domain)}"
        if use_multi:
            path += "&multi=true"
        data = self._get(path)
        return data.get("matches", [])

    def rerank(self, query: str, texts: list[str]) -> list[dict]:
        """
        Debug: rerank a list of texts against a query via the cross-encoder.
        Returns texts sorted by reranker score (descending).
        """
        payload = json.dumps({"query": query, "texts": texts}).encode()
        req = urllib.request.Request(
            f"{self._worker_url}/rerank",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "REMORA-RAGOracle/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=self._timeout) as r:
            return json.loads(r.read()).get("results", [])

    def translate(self, text: str, source_lang: str = "no", target_lang: str = "en") -> str:
        """
        Translate text via Cloudflare Workers AI m2m100.
        Useful for normalising Norwegian queries before English-index retrieval.
        """
        payload = json.dumps({
            "text": text,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }).encode()
        req = urllib.request.Request(
            f"{self._worker_url}/translate",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "REMORA-RAGOracle/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=self._timeout) as r:
            return json.loads(r.read()).get("translated_text", text)
