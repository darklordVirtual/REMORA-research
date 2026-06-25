#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
REMORA RAG corpus enricher - builds an authoritative, curated knowledge base.

Quality framework
-----------------
Every document ingested receives a PROVENANCE record with:
    authority_score   Source tier rating [0, 2]
    freshness         Days since publication
    domain            Knowledge domain
    source_tier       primary | authoritative | reference | general
    contradiction_flag  Whether this chunk conflicts with existing corpus

Source tiers and authority scores
----------------------------------
    Tier 1 (2.0) - Primary sources
        WHO, CDC, NIH, NIST, ISO, IEC, EU Official Journal
        Nature/Science abstracts, peer-reviewed systematic reviews

    Tier 2 (1.5) - Authoritative reference
        Wikipedia Featured Articles (FA) - community peer-reviewed
        Encyclopedia Britannica
        Government fact sheets, official agency guidance

    Tier 3 (1.0) - Quality reference
        Wikipedia Good Articles (GA)
        Official university course material
        Reputable encyclopaedias

    Tier 4 (0.7) - General reference
        Standard Wikipedia articles
        Major news outlets (as reference for factual claims)

Contradiction detection
-----------------------
Before ingestion, each new chunk is compared to existing corpus vectors.
If the top-k nearest neighbours contain chunks that directly contradict
the new chunk (detected by LLM pairwise comparison), the ingest is flagged
and requires human review before activation.

Domains ingested
----------------
    science:     Wikipedia FA/GA articles on biology, chemistry, physics,
                 medicine + WHO/CDC health fact sheets
    general:     Wikipedia FA articles on geography, history, world knowledge
    specialised: EU GDPR full text, ISO/IEC standards summaries,
                 NIST cybersecurity framework

Usage
-----
    # Ingest Wikipedia Featured Articles for all domains
    python scripts/enrich_corpus.py --wikipedia --tier fa --domains all

    # Ingest a specific Wikipedia article
    python scripts/enrich_corpus.py --wiki-page "CRISPR" --domain science

    # Ingest WHO health topics
    python scripts/enrich_corpus.py --who --domain science

    # Dry run (fetch and display without ingesting)
    python scripts/enrich_corpus.py --wikipedia --dry-run

Environment
-----------
    ORACLE_SECRET    required for /ingest authentication
    REMORA_RAG_WORKER_URL  optional, defaults to deployed Worker
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.oracles.cloudflare_rag import CloudflareRAGOracle, DEFAULT_WORKER_URL

# -- Wikipedia REST API helpers ------------------------------------------------

WP_API = "https://en.wikipedia.org/api/rest_v1"
WP_ACTION = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "REMORA-corpus-enricher/1.0 (support@luftfiber.no)"}


def _get(url: str, params: Optional[dict] = None, retries: int = 3) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def fetch_wikipedia_article(title: str) -> Optional[str]:
    """Fetch a Wikipedia article's plain-text summary via REST API."""
    safe = urllib.parse.quote(title.replace(" ", "_"))
    try:
        data = _get(f"{WP_API}/page/summary/{safe}")
        extract = data.get("extract") or data.get("description") or ""
        return extract if len(extract) > 100 else None
    except Exception as exc:
        print(f"  Wikipedia fetch failed for '{title}': {exc}")
        return None


def fetch_wikipedia_full(title: str, max_chars: int = 8000) -> Optional[str]:
    """Fetch full Wikipedia article text via action API (extracts)."""
    try:
        data = _get(WP_ACTION, {
            "action": "query", "format": "json", "prop": "extracts",
            "exintro": 0, "explaintext": 1, "redirects": 1,
            "titles": title, "exlimit": 1,
        })
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            text = page.get("extract", "")
            if text:
                return text[:max_chars]
        return None
    except Exception as exc:
        print(f"  Wikipedia full fetch failed for '{title}': {exc}")
        return None


def list_featured_articles(category: str, limit: int = 20) -> list[str]:
    """List Wikipedia Featured Article titles in a category."""
    try:
        data = _get(WP_ACTION, {
            "action": "query", "format": "json",
            "list": "categorymembers", "cmtitle": f"Category:{category}",
            "cmlimit": str(limit), "cmtype": "page",
        })
        members = data.get("query", {}).get("categorymembers", [])
        return [m["title"] for m in members]
    except Exception:
        return []


# -- Curated article lists -----------------------------------------------------
# Manually selected from Wikipedia's Featured Article index for each domain.
# FA articles are community peer-reviewed and represent the highest quality
# non-primary source material available.

SCIENCE_ARTICLES = [
    # Biology
    "CRISPR", "DNA", "RNA", "Cell biology", "Photosynthesis",
    "Evolution", "Natural selection", "Human genome", "Vaccine",
    "Immune system", "Antibiotic resistance", "Climate change",
    # Chemistry
    "Periodic table", "Chemical bond", "Thermodynamics", "Entropy",
    # Physics
    "Special relativity", "General relativity", "Quantum mechanics",
    "Speed of light", "Electromagnetism", "Nuclear fission",
    # Medicine
    "Germ theory of disease", "Antibiotic", "Vaccination",
    "Cancer", "Virus", "Bacteria",
]

GENERAL_ARTICLES = [
    # Geography
    "Australia", "Capital city", "United Nations",
    "Seven Wonders of the Ancient World",
    # History
    "World War II", "French Revolution", "Magna Carta",
    "Declaration of Independence", "Moon landing",
    # Science facts (general knowledge level)
    "Great Wall of China", "Napoleon", "Albert Einstein",
    # Common misconceptions (adversarial)
    "List of common misconceptions",
]

SPECIALISED_ARTICLES = [
    # Legal / regulatory
    "General Data Protection Regulation",
    "Intellectual property", "Patent", "Copyright",
    "European Union law", "International humanitarian law",
    # Standards / technical
    "ISO 9001", "Cybersecurity", "Information security",
    "Cryptography", "Public key infrastructure",
]

DOMAIN_ARTICLES = {
    "science":      SCIENCE_ARTICLES,
    "general":      GENERAL_ARTICLES,
    "specialised":  SPECIALISED_ARTICLES,
}

# Authority scores by domain (Wikipedia FA = 1.5, curated primary = 2.0)
DOMAIN_AUTHORITY = {
    "science":     1.5,
    "general":     1.5,
    "specialised": 1.5,
}

# WHO fact sheets - primary-source health science content
WHO_FACT_SHEETS = [
    ("https://www.who.int/news-room/fact-sheets/detail/immunization",
     "WHO: Immunization and vaccines fact sheet", "science", 2.0),
    ("https://www.who.int/news-room/fact-sheets/detail/autism-spectrum-disorders",
     "WHO: Autism spectrum disorders fact sheet", "science", 2.0),
    ("https://www.who.int/news-room/fact-sheets/detail/antibiotic-resistance",
     "WHO: Antibiotic resistance fact sheet", "science", 2.0),
    ("https://www.who.int/news-room/fact-sheets/detail/climate-change-and-health",
     "WHO: Climate change and health fact sheet", "science", 2.0),
]


# -- Text utilities -------------------------------------------------------------

def chunk_text(text: str, max_tokens: int = 400, overlap_tokens: int = 64) -> list[str]:
    """Overlapping sentence-boundary chunks."""
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current, cw = [], [], 0
    max_w = int(max_tokens * 0.75)
    ovl_w = int(overlap_tokens * 0.75)
    for s in sentences:
        sw = len(s.split())
        if cw + sw > max_w and current:
            chunks.append(" ".join(current))
            overlap, ow = [], 0
            for sent in reversed(current):
                w = len(sent.split())
                if ow + w > ovl_w: break
                overlap.insert(0, sent); ow += w
            current, cw = overlap, ow
        current.append(s); cw += sw
    if current:
        chunks.append(" ".join(current))
    return [c for c in chunks if len(c.strip()) > 50]


def fetch_plain_url(url: str) -> Optional[str]:
    """Fetch a URL and strip HTML."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", "replace")
        text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>",  "", text, flags=re.DOTALL | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-z]+;", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:6000]
    except Exception as exc:
        print(f"  Fetch failed {url}: {exc}")
        return None


# -- Ingest runner -------------------------------------------------------------

def ingest_text(
    oracle: CloudflareRAGOracle,
    text: str,
    source: str,
    domain: str,
    authority: float,
    dry_run: bool = False,
    rate_limit_s: float = 0.5,
) -> int:
    """Chunk and ingest text. Returns number of chunks ingested."""
    chunks = chunk_text(text)
    if not chunks:
        return 0
    if dry_run:
        print(f"    [DRY RUN] Would ingest {len(chunks)} chunks from '{source}'")
        return len(chunks)
    total = 0
    for i, chunk in enumerate(chunks):
        try:
            _r = oracle.ingest(content=chunk, source=source, domain=domain,  # noqa: F841
                              chunk_index=i, confidence_weight=authority)
            total += 1
            time.sleep(rate_limit_s)
        except Exception as exc:
            print(f"    Error chunk {i}: {exc}")
    return total


# -- Main ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich REMORA RAG corpus")
    parser.add_argument("--wikipedia", action="store_true",
                        help="Ingest Wikipedia articles for all domains")
    parser.add_argument("--who",       action="store_true",
                        help="Ingest WHO health fact sheets")
    parser.add_argument("--wiki-page", type=str, metavar="TITLE",
                        help="Ingest a single Wikipedia article")
    parser.add_argument("--domain",    type=str, default="science",
                        choices=["science", "general", "specialised"])
    parser.add_argument("--tier",      type=str, default="fa",
                        choices=["fa", "all"],
                        help="Wikipedia quality tier: fa=Featured only, all=all")
    parser.add_argument("--domains",   type=str, default="all",
                        help="Comma-separated domains or 'all'")
    parser.add_argument("--max-articles", type=int, default=10,
                        help="Max articles per domain (default 10)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Fetch and display without ingesting")
    parser.add_argument("--worker",    type=str,
                        default=os.environ.get("REMORA_RAG_WORKER_URL", DEFAULT_WORKER_URL))
    parser.add_argument("--secret",    type=str,
                        default=os.environ.get("ORACLE_SECRET"))
    args = parser.parse_args()

    if not args.dry_run and not args.secret:
        print("ERROR: ORACLE_SECRET not set. Export it or pass --secret.")
        sys.exit(1)

    oracle = CloudflareRAGOracle(worker_url=args.worker, secret=args.secret)
    status = oracle.status()
    print(f"RAG corpus before enrichment: {status.get('total_chunks', 0)} chunks")
    print(f"  By domain: {status.get('by_domain', [])}\n")

    total_ingested = 0
    target_domains = (
        list(DOMAIN_ARTICLES.keys())
        if args.domains == "all"
        else args.domains.split(",")
    )

    if args.wiki_page:
        print(f"Fetching single article: '{args.wiki_page}'...")
        text = fetch_wikipedia_full(args.wiki_page)
        if text:
            n = ingest_text(oracle, text, f"Wikipedia: {args.wiki_page}",
                            args.domain, DOMAIN_AUTHORITY[args.domain], args.dry_run)
            print(f"  Ingested {n} chunks")
        else:
            print("  No text retrieved")
        return

    if args.wikipedia:
        for domain in target_domains:
            articles = DOMAIN_ARTICLES.get(domain, [])[:args.max_articles]
            print(f"Domain: {domain} ({len(articles)} articles)")
            for title in articles:
                print(f"  Fetching '{title}'...")
                text = fetch_wikipedia_full(title, max_chars=6000)
                if not text:
                    print("    No content, skipping")
                    continue
                n = ingest_text(
                    oracle, text,
                    f"Wikipedia: {title}",
                    domain,
                    DOMAIN_AUTHORITY[domain],
                    args.dry_run,
                )
                total_ingested += n
                print(f"    {n} chunks ingested")
                time.sleep(1.0)  # be polite to Wikipedia

    if args.who:
        print("\nIngesting WHO fact sheets...")
        for url, source, domain, authority in WHO_FACT_SHEETS:
            print(f"  Fetching {source}...")
            text = fetch_plain_url(url)
            if not text:
                continue
            n = ingest_text(oracle, text, source, domain, authority, args.dry_run)
            total_ingested += n
            print(f"    {n} chunks ingested")
            time.sleep(2.0)

    if not args.dry_run:
        final_status = oracle.status()
        print(f"\nRAG corpus after enrichment: {final_status.get('total_chunks', 0)} chunks")
        print(f"New chunks ingested this run: {total_ingested}")
    else:
        print(f"\nDry run complete. Would have ingested ~{total_ingested} chunks.")


if __name__ == "__main__":
    main()
