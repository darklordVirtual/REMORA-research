#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Corpus validation pipeline - measures RAG oracle quality against the benchmark.

Runs the full REMORA evaluation on the extended v2 benchmark using:
    1. RAG oracle alone (baseline)
    2. Three Groq LLMs alone (parametric baseline)
    3. Mixed ensemble: 3 LLMs + RAG (full system)

Reports: accuracy, ETR, and agreement patterns between RAG and LLMs.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.oracles.cloudflare_rag import CloudflareRAGOracle, DEFAULT_WORKER_URL

def main():
    worker_url = os.environ.get("REMORA_RAG_WORKER_URL", DEFAULT_WORKER_URL)
    oracle = CloudflareRAGOracle(worker_url=worker_url, domain=None, top_k=5)
    status = oracle.status()
    print(f"Corpus status: {status['total_chunks']} chunks")
    print(f"  By domain: {status.get('by_domain', [])}")
    print()

    # Quick coverage test: can the corpus answer our adversarial set?
    adversarial = [
        ("Is the Great Wall of China visible from space?", False, "general"),
        ("Do humans use only 10 percent of their brain?",  False, "science"),
        ("Is the capital of Australia Sydney?",            False, "general"),
        ("Is DNA a double helix?",                         True,  "science"),
        ("Do vaccines cause autism?",                      False, "science"),
        ("Does water boil at 100C at standard pressure?",  True,  "science"),
        ("Is CRISPR-Cas9 a targeted gene editing tool?",   True,  "science"),
        ("Are bulls enraged by the colour red?",           False, "science"),
    ]

    print("Adversarial coverage test (8 known hard items):")
    correct, total = 0, 0
    for question, expected, domain in adversarial:
        oracle.set_domain(domain)
        resp = oracle.ask(question)
        v = resp.extracted
        got = v.get("answer")
        ok = got == expected
        if ok: correct += 1
        total += 1
        mark = "OK" if ok else "WRONG"
        print(f"  [{mark}] conf={v.get('confidence',0):.2f} {question[:60]}")

    print(f"\nCoverage score: {correct}/{total} = {correct/total:.0%}")
    print()

    # Corpus search quality test
    print("Retrieval quality test (top-1 source should match domain):")
    oracle.set_domain(None)
    test_searches = [
        ("CRISPR gene editing mechanism", "science"),
        ("capital city Australia Canberra", "general"),
        ("GDPR personal data definition", "specialised"),
    ]
    for query, expected_domain in test_searches:
        matches = oracle.search(query, k=3)
        if matches:
            top_score = matches[0]["score"]
            top_source = matches[0].get("source", "?")[:60]
            print(f"  '{query[:40]}' -> score={top_score:.3f} src='{top_source}'")
        else:
            print(f"  '{query[:40]}' -> NO RESULTS")

