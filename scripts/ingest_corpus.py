#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Corpus ingest script for the REMORA RAG oracle.

Populates Cloudflare Vectorize + D1 with authoritative knowledge across
the three evaluation domains. Documents are chunked with 64-token overlap
and assigned confidence weights reflecting source authority.

Domain taxonomy
---------------
    specialised  - regulatory statutes, technical standards, legal precedent
    science      - peer-reviewed consensus, scientific databases
    general      - authoritative reference works (encyclopaedias, fact databases)

Usage
-----
    # Ingest the bundled seed corpus
    python scripts/ingest_corpus.py --seed

    # Ingest a custom text file
    python scripts/ingest_corpus.py \\
        --file path/to/document.txt \\
        --source "REGULATION (EU) 2016/679" \\
        --domain specialised \\
        --confidence 2.0

    # Ingest from a URL (fetches HTML, strips tags)
    python scripts/ingest_corpus.py \\
        --url https://en.wikipedia.org/wiki/CRISPR \\
        --source "Wikipedia: CRISPR" \\
        --domain science \\
        --confidence 1.5

Environment
-----------
    REMORA_RAG_WORKER_URL  - defaults to https://remora-rag-oracle.razorsharp.workers.dev
    ORACLE_SECRET          - required for ingest authentication
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.oracles.cloudflare_rag import CloudflareRAGOracle, DEFAULT_WORKER_URL

# -- Chunking ------------------------------------------------------------------

def chunk_text(text: str, max_tokens: int = 400, overlap_tokens: int = 64) -> list[str]:
    """
    Split text into overlapping chunks.

    Approximates token count as word_count / 0.75 (English average).
    Splits on sentence boundaries where possible to preserve coherence.
    """
    # Normalise whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    max_words = int(max_tokens * 0.75)
    overlap_words = int(overlap_tokens * 0.75)

    for sentence in sentences:
        swords = len(sentence.split())
        if current_words + swords > max_words and current:
            chunks.append(' '.join(current))
            # Keep overlap sentences
            overlap: list[str] = []
            ow = 0
            for s in reversed(current):
                w = len(s.split())
                if ow + w > overlap_words:
                    break
                overlap.insert(0, s)
                ow += w
            current = overlap
            current_words = ow
        current.append(sentence)
        current_words += swords

    if current:
        chunks.append(' '.join(current))

    return [c for c in chunks if len(c.strip()) > 40]


# -- URL fetcher ---------------------------------------------------------------

def fetch_url(url: str) -> str:
    """Fetch URL and return plain text (strips HTML tags)."""
    req = urllib.request.Request(url, headers={'User-Agent': 'REMORA-corpus-ingest/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode('utf-8', errors='replace')
    # Strip HTML
    text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


# -- Seed corpus ---------------------------------------------------------------
# Authoritative passages addressing the three REMORA evaluation domains.
# Each entry: (source_id, domain, confidence_weight, text)
# confidence_weight: 2.0 = primary source, 1.5 = authoritative reference, 1.0 = general

SEED_CORPUS: list[tuple[str, str, float, str]] = [

    # -- SCIENCE domain ---------------------------------------------------------
    (
        "NCBI: CRISPR-Cas9 mechanism review",
        "science", 2.0,
        """CRISPR-Cas9 is a bacterial adaptive immune system that has been repurposed as a
        precise genome-editing tool. The system uses a guide RNA (gRNA) to direct the Cas9
        endonuclease to a complementary genomic sequence, where it introduces a double-strand
        break (DSB). Researchers have demonstrated targeted gene disruption, gene correction,
        and gene insertion in a wide range of organisms including human cells. CRISPR-Cas9 is
        now considered the most widely adopted platform for targeted gene editing."""
    ),
    (
        "WHO: Vaccine safety and efficacy - overview",
        "science", 2.0,
        """Vaccines undergo rigorous clinical trials across three phases before regulatory
        approval. Phase III trials typically enrol tens of thousands of participants to
        assess efficacy and detect rare adverse events. Post-marketing surveillance continues
        after approval. Systematic reviews and meta-analyses consistently demonstrate that
        vaccines do not cause autism. The original 1998 Wakefield paper claiming a link was
        retracted in 2010 following findings of data manipulation and ethical violations.
        Scientific consensus from organisations including WHO, CDC, and EMA affirms vaccine
        safety."""
    ),
    (
        "NIST: Speed of light - physical constants",
        "science", 2.0,
        """The speed of light in vacuum is defined as exactly 299,792,458 metres per second
        (approximately 3 × 10^8 m/s) as of the 1983 redefinition of the metre. This value
        is a defined constant in the International System of Units (SI) and is not subject
        to experimental uncertainty. The speed of light is the maximum speed at which
        information or matter can travel through space, a cornerstone of special relativity
        first formulated by Albert Einstein in 1905."""
    ),
    (
        "IUPAC: Water boiling point - standard conditions",
        "science", 2.0,
        """Water (H2O) boils at 100 degrees Celsius (373.15 K, 212 degrees Fahrenheit) at
        standard atmospheric pressure (101.325 kPa, 1 atm). At higher altitudes, where
        atmospheric pressure is lower, the boiling point decreases. At the top of Mount
        Everest (approximately 8,849 m), water boils at approximately 70 degrees Celsius.
        Dissolved solutes (e.g., salt) elevate the boiling point through boiling-point
        elevation, a colligative property."""
    ),
    (
        "DNA: Structure and function - molecular biology reference",
        "science", 2.0,
        """Deoxyribonucleic acid (DNA) forms a double helix, a structure elucidated by
        James Watson and Francis Crick in 1953 based on X-ray diffraction data from
        Rosalind Franklin and Raymond Gosling. The double helix consists of two
        antiparallel polynucleotide strands wound around a common axis, with the
        nitrogenous bases (adenine, thymine, guanine, cytosine) facing inward and
        paired via hydrogen bonds (A-T and G-C). This complementary base pairing is
        the molecular basis for DNA replication and transcription."""
    ),

    # -- GENERAL KNOWLEDGE domain -----------------------------------------------
    (
        "World Atlas: Capital cities - authoritative geographic reference",
        "general", 1.5,
        """Canberra is the capital city of Australia, not Sydney. Canberra was purpose-built
        as the national capital and has served in that role since 1913 (Federal Parliament
        relocated from Melbourne to Canberra in 1927). Sydney is Australia's largest city
        by population and serves as the capital of New South Wales, but it has never been
        the national capital. The Australian Capital Territory (ACT), in which Canberra is
        located, was established as a federal district to avoid rivalry between Sydney and
        Melbourne."""
    ),
    (
        "Encyclopaedia Britannica: Great Wall of China - visibility from space",
        "general", 1.5,
        """The claim that the Great Wall of China is visible from space with the naked eye
        is a popular myth. NASA and multiple astronauts, including Chinese astronaut Yang
        Liwei, have confirmed it cannot be seen from low Earth orbit (approximately
        400 km altitude) without optical aids. The wall is typically 4-9 metres wide,
        far narrower than the minimum width resolvable by the human eye at that distance.
        Under exceptional atmospheric conditions it may be discernible in photographs
        taken with zoom lenses, but not with the naked eye."""
    ),
    (
        "ISO 8601: Calendar and date standards",
        "general", 2.0,
        """The Gregorian calendar year 2000 was a leap year. The Gregorian calendar rule
        is: a year is a leap year if it is divisible by 4, except for century years
        (divisible by 100), which must also be divisible by 400. Year 2000 is divisible
        by 400, so it is a leap year. Year 1900 was not a leap year (divisible by 100
        but not 400). This correction was introduced to keep the calendar aligned with
        the solar year over centuries."""
    ),

    # -- SPECIALISED / REGULATORY domain ----------------------------------------
    (
        "GDPR Article 4: Definitions - Regulation (EU) 2016/679",
        "specialised", 2.0,
        """Under the General Data Protection Regulation (GDPR), Article 4 defines
        'personal data' as any information relating to an identified or identifiable
        natural person ('data subject'). An identifiable natural person is one who can
        be identified, directly or indirectly, in particular by reference to an
        identifier such as a name, an identification number, location data, an online
        identifier, or to one or more factors specific to the physical, physiological,
        genetic, mental, economic, cultural or social identity of that natural person."""
    ),
    (
        "GDPR Article 5: Principles for processing personal data",
        "specialised", 2.0,
        """GDPR Article 5 establishes the following principles for processing personal
        data: (a) lawfulness, fairness and transparency; (b) purpose limitation -
        data collected for specified, explicit and legitimate purposes and not further
        processed in a manner incompatible with those purposes; (c) data minimisation -
        data adequate, relevant and limited to what is necessary; (d) accuracy;
        (e) storage limitation - kept no longer than necessary for the purpose;
        (f) integrity and confidentiality. The controller is responsible for and must
        demonstrate compliance with these principles (accountability)."""
    ),
    (
        "ISO/IEC 27001:2022 - Information security management",
        "specialised", 1.5,
        """ISO/IEC 27001:2022 is the international standard for information security
        management systems (ISMS). It specifies requirements for establishing,
        implementing, maintaining and continually improving an ISMS within the context
        of the organisation's risk. Certification demonstrates that an organisation
        manages information security risks systematically. Clause 6.1.2 requires
        organisations to perform an information security risk assessment with defined
        criteria for risk acceptance."""
    ),
]


# -- Main ingest logic ---------------------------------------------------------

def ingest_document(
    oracle: CloudflareRAGOracle,
    text: str,
    source: str,
    domain: str,
    confidence: float,
    chunk_size: int = 400,
    overlap: int = 64,
    rate_limit_s: float = 0.5,
) -> int:
    """Chunk and ingest a document. Returns number of chunks ingested."""
    chunks = chunk_text(text, max_tokens=chunk_size, overlap_tokens=overlap)
    for i, chunk in enumerate(chunks):
        try:
            result = oracle.ingest(
                content=chunk,
                source=source,
                domain=domain,
                chunk_index=i,
                confidence_weight=confidence,
            )
            print(f"  [{domain}] chunk {i}/{len(chunks)-1} -> {result.get('vector_id','?')[:12]}...")
            time.sleep(rate_limit_s)
        except Exception as exc:
            print(f"  ERROR chunk {i}: {exc}")
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest corpus into REMORA RAG oracle")
    parser.add_argument("--seed",       action="store_true",   help="Ingest the bundled seed corpus")
    parser.add_argument("--file",       type=str,              help="Path to a text file to ingest")
    parser.add_argument("--url",        type=str,              help="URL to fetch and ingest")
    parser.add_argument("--source",     type=str,              help="Source identifier string")
    parser.add_argument("--domain",     type=str, default="general",
                        choices=["specialised", "science", "general"],
                        help="Knowledge domain")
    parser.add_argument("--confidence", type=float, default=1.0,
                        help="Source confidence weight [0.5-2.0]")
    parser.add_argument("--worker",     type=str,
                        default=os.environ.get("REMORA_RAG_WORKER_URL", DEFAULT_WORKER_URL))
    parser.add_argument("--secret",     type=str,
                        default=os.environ.get("ORACLE_SECRET"))
    args = parser.parse_args()

    if not args.secret:
        print("ERROR: ORACLE_SECRET not set. Export it or pass --secret.")
        sys.exit(1)

    oracle = CloudflareRAGOracle(worker_url=args.worker, secret=args.secret)

    # Status check
    status = oracle.status()
    print(f"RAG oracle: {status.get('total_chunks', 0)} chunks in corpus")

    total_chunks = 0

    if args.seed:
        print(f"\nIngesting seed corpus ({len(SEED_CORPUS)} documents)...")
        for source, domain, confidence, text in SEED_CORPUS:
            print(f"\n>> {source}")
            n = ingest_document(oracle, text, source, domain, confidence)
            total_chunks += n
        print(f"\nSeed corpus complete: {total_chunks} chunks ingested")

    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        source = args.source or Path(args.file).name
        print(f"\nIngesting {args.file} as '{source}'...")
        n = ingest_document(oracle, text, source, args.domain, args.confidence)
        print(f"Done: {n} chunks")

    elif args.url:
        print(f"\nFetching {args.url}...")
        text = fetch_url(args.url)
        source = args.source or args.url
        print(f"Fetched {len(text)} characters. Ingesting as '{source}'...")
        n = ingest_document(oracle, text, source, args.domain, args.confidence)
        print(f"Done: {n} chunks")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
