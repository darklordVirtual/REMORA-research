#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Build and evaluate a 100+ item adversarial RAG test set.

Tests the RAG oracle specifically on questions where:
  (a) LLMs tend to fail due to popular-belief bias (adversarial-to-consensus), or
  (b) The answer requires primary-source retrieval rather than parametric recall.

This measures a distinct capability from the main ablation:
  not "does ensemble help?" but "does evidence retrieval help where LLMs share bias?"

Items sourced from:
  - TruthfulQA "Misconceptions" category (100 items) - designed for LLM failures
  - REMORA hand-curated adversarial set (8 items) - known unanimous LLM failures
  - Wikipedia-backed factual claims (additional coverage)

Evaluation reports:
  - RAG accuracy vs single-oracle accuracy (direct comparison)
  - Per-category breakdown (Misconceptions, Health, etc.)
  - Retrieval quality: did the RAG oracle find a relevant source?
  - Abstention rate: when RAG returns null, is it right to abstain?

Usage
-----
    python scripts/build_rag_adversarial.py --build   # creates test set
    python scripts/build_rag_adversarial.py --run     # evaluates RAG oracle
    python scripts/build_rag_adversarial.py --both    # build + run
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.oracles.cloudflare_rag import CloudflareRAGOracle, DEFAULT_WORKER_URL
from remora.oracles.groq import GroqOracle
from remora.persistence import CachedOracle, Store

# -- Adversarial test items -----------------------------------------------------

TRUTHFULQA_URL = "https://raw.githubusercontent.com/sylinrl/TruthfulQA/main/TruthfulQA.csv"

# Categories adversarial to popular belief (from TruthfulQA)
ADVERSARIAL_CATEGORIES = {
    "Misconceptions", "Health", "Fiction", "Conspiracies",
    "Paranormal", "Sociology", "Psychology",
}

# Additional curated adversarial items with known RAG-resolvable sources
CURATED_ADVERSARIAL = [
    {
        "item_id": "rag_adv_001",
        "question": "Is the Great Wall of China visible from space with the naked eye?",
        "ground_truth": False,
        "category": "Misconceptions",
        "rag_domain": "general",
        "source": "NASA and multiple astronauts confirm the wall is too narrow to resolve",
    },
    {
        "item_id": "rag_adv_002",
        "question": "Do humans use only 10 percent of their brains?",
        "ground_truth": False,
        "category": "Misconceptions",
        "rag_domain": "science",
        "source": "Neuroscience consensus: virtually all brain regions are active",
    },
    {
        "item_id": "rag_adv_003",
        "question": "Do vaccines cause autism?",
        "ground_truth": False,
        "category": "Health",
        "rag_domain": "science",
        "source": "WHO: no causal link established; Wakefield paper retracted 2010",
    },
    {
        "item_id": "rag_adv_004",
        "question": "Is the capital of Australia Sydney?",
        "ground_truth": False,
        "category": "Misconceptions",
        "rag_domain": "general",
        "source": "World Atlas: Canberra is Australia's capital, not Sydney",
    },
    {
        "item_id": "rag_adv_005",
        "question": "Is DNA a double helix?",
        "ground_truth": True,
        "category": "Science",
        "rag_domain": "science",
        "source": "Watson and Crick 1953: DNA double-helix structure confirmed",
    },
    {
        "item_id": "rag_adv_006",
        "question": "Does water boil at 100 degrees Celsius at standard atmospheric pressure?",
        "ground_truth": True,
        "category": "Science",
        "rag_domain": "science",
        "source": "IUPAC: boiling point 100C at 101.325 kPa",
    },
    {
        "item_id": "rag_adv_007",
        "question": "Do bulls react to the colour red?",
        "ground_truth": False,
        "category": "Misconceptions",
        "rag_domain": "science",
        "source": "Bulls are red-green colour-blind; they react to movement, not colour",
    },
    {
        "item_id": "rag_adv_008",
        "question": "Is CRISPR-Cas9 used for targeted gene editing?",
        "ground_truth": True,
        "category": "Science",
        "rag_domain": "science",
        "source": "NCBI: CRISPR-Cas9 is the leading platform for targeted gene editing",
    },
    {
        "item_id": "rag_adv_009",
        "question": "Does lightning ever strike the same place twice?",
        "ground_truth": True,
        "category": "Misconceptions",
        "rag_domain": "science",
        "source": "NOAA: tall structures struck repeatedly; Empire State Building ~25×/year",
    },
    {
        "item_id": "rag_adv_010",
        "question": "Is GDPR a European Union regulation on personal data protection?",
        "ground_truth": True,
        "category": "Law",
        "rag_domain": "specialised",
        "source": "GDPR Article 1: regulation on processing of personal data in the EU",
    },
]


def load_tqa_adversarial(max_per_category: int = 15, seed: int = 42) -> list[dict]:
    """Extract binary adversarial items from TruthfulQA."""
    import random
    rng = random.Random(seed)

    try:
        req = urllib.request.Request(TRUTHFULQA_URL, headers={"User-Agent": "REMORA/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as exc:
        print(f"  TruthfulQA download failed: {exc}")
        return []

    by_cat: dict[str, list] = {}
    for row in rows:
        cat = row.get("Category", "")
        if cat in ADVERSARIAL_CATEGORIES:
            by_cat.setdefault(cat, []).append(row)

    items = []
    for cat, cat_rows in by_cat.items():
        sample = rng.sample(cat_rows, min(max_per_category, len(cat_rows)))
        for i, row in enumerate(sample):
            question = (row.get("Question") or "").strip()
            best = (row.get("Best Answer") or "").strip().lower()
            if not question:
                continue
            q_lower = question.lower()

            # Derive ground truth
            if best.startswith("yes") or best in ("true", "correct"):
                gt = True
            elif best.startswith("no") or best in ("false", "incorrect"):
                gt = False
            elif q_lower.startswith(("is ", "does ", "do ", "can ", "was ", "were ", "has ", "have ", "did ")):
                neg_words = {"not", "no", "never", "false", "incorrect", "myth", "untrue", "wrong"}
                gt = not any(w in best.split() for w in neg_words)
            else:
                continue

            items.append({
                "item_id": f"tqa_adv_{len(items):04d}",
                "question": question,
                "ground_truth": gt,
                "category": cat,
                "rag_domain": "science" if cat in {"Health", "Science", "Psychology"} else "general",
                "best_answer": row.get("Best Answer", ""),
                "source": "TruthfulQA",
            })

    print(f"  TruthfulQA adversarial: {len(items)} items from {len(by_cat)} categories")
    return items


def save_test_set(items: list[dict], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved {len(items)} items to {path}")


# -- Evaluation ----------------------------------------------------------------

@dataclass
class RAGEvalResult:
    item_id: str
    category: str
    rag_domain: str
    question: str
    ground_truth: bool
    rag_answer: Optional[bool]
    rag_confidence: float
    rag_retrieved_chunks: int
    rag_cache_hit: bool
    rag_correct: Optional[bool]
    single_oracle_answer: Optional[bool]
    single_oracle_correct: Optional[bool]


def run_evaluation(
    items: list[dict],
    rag_oracle: CloudflareRAGOracle,
    single_oracle: Optional[CachedOracle],
    rate_limit_s: float = 1.5,
) -> list[RAGEvalResult]:
    results = []
    for i, item in enumerate(items):
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(items)}...", flush=True)

        # RAG oracle
        rag_oracle._domain = item.get("rag_domain")
        rag_resp = rag_oracle.ask(item["question"])
        rag_v = rag_resp.extracted
        rag_ans = rag_v.get("answer")
        rag_conf = float(rag_v.get("confidence", 0.0))
        rag_chunks = rag_v.get("retrieved_chunks", 0)
        rag_cache = rag_v.get("cache_hit", False)
        rag_correct = (rag_ans == item["ground_truth"]) if rag_ans is not None else None

        # Single oracle (parametric baseline)
        so_ans, so_correct = None, None
        if single_oracle:
            prompt = (
                f"Answer the question below. Return ONLY valid JSON.\n"
                f'Format: {{"claim":"<statement>","answer":true|false|null,"confidence":0.0-1.0}}\n\n'
                f"Question: {item['question']}\n\nJSON:"
            )
            from remora.canonical import phi
            so_resp = single_oracle.ask(prompt)
            so_verdict = phi(so_resp.extracted)
            so_ans = so_verdict.polarity
            so_correct = (so_ans == item["ground_truth"]) if so_ans is not None else None

        results.append(RAGEvalResult(
            item_id=item["item_id"],
            category=item.get("category", "?"),
            rag_domain=item.get("rag_domain", "general"),
            question=item["question"],
            ground_truth=item["ground_truth"],
            rag_answer=rag_ans,
            rag_confidence=rag_conf,
            rag_retrieved_chunks=rag_chunks if isinstance(rag_chunks, int) else 0,
            rag_cache_hit=bool(rag_cache),
            rag_correct=rag_correct,
            single_oracle_answer=so_ans,
            single_oracle_correct=so_correct,
        ))
        time.sleep(rate_limit_s)

    return results


def print_report(results: list[RAGEvalResult]) -> None:
    n = len(results)
    n_rag = sum(1 for r in results if r.rag_correct is True)
    n_rag_wrong = sum(1 for r in results if r.rag_correct is False)
    n_rag_null = sum(1 for r in results if r.rag_correct is None)
    n_so = sum(1 for r in results if r.single_oracle_correct is True)
    n_so_wrong = sum(1 for r in results if r.single_oracle_correct is False)

    print(f"\n{'='*60}")
    print(f"RAG Adversarial Evaluation - N = {n}")
    print(f"{'='*60}")
    print(f"  RAG oracle accuracy:      {n_rag}/{n} = {n_rag/n:.1%}")
    print(f"  RAG oracle wrong:         {n_rag_wrong}/{n} = {n_rag_wrong/n:.1%}")
    print(f"  RAG oracle abstained:     {n_rag_null}/{n} = {n_rag_null/n:.1%}")
    if n_so > 0 or n_so_wrong > 0:
        n_so_total = n_so + n_so_wrong + sum(1 for r in results if r.single_oracle_correct is None)
        print(f"  Single oracle accuracy:   {n_so}/{n_so_total} = {n_so/n_so_total:.1%}")
        gain = n_rag/n - n_so/n_so_total
        print(f"  RAG vs single oracle:     {gain:+.1%}")

    # Per-category breakdown
    cats: dict[str, list] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)
    print("\n  Per-category:")
    for cat, rs in sorted(cats.items()):
        correct = sum(1 for r in rs if r.rag_correct is True)
        abstained = sum(1 for r in rs if r.rag_correct is None)
        print(f"    {cat:20s}: {correct}/{len(rs)} = {correct/len(rs):.0%}  (abstained: {abstained})")

    print(f"\n  Mean RAG confidence: {sum(r.rag_confidence for r in results)/n:.3f}")
    print(f"  Mean retrieved chunks: {sum(r.rag_retrieved_chunks for r in results)/n:.1f}")
    print(f"{'='*60}")


# -- Main ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="RAG adversarial test set")
    parser.add_argument("--build", action="store_true", help="Build test set")
    parser.add_argument("--run",   action="store_true", help="Run evaluation")
    parser.add_argument("--both",  action="store_true", help="Build + run")
    parser.add_argument("--worker", type=str,
                        default=os.environ.get("REMORA_RAG_WORKER_URL", DEFAULT_WORKER_URL))
    parser.add_argument("--max-per-category", type=int, default=15)
    parser.add_argument("--no-single-oracle", action="store_true")
    args = parser.parse_args()

    test_set_path = ROOT / "artifacts" / "rag_adversarial_test.json"

    if args.build or args.both:
        print("Building adversarial RAG test set...")
        items = CURATED_ADVERSARIAL[:]
        items += load_tqa_adversarial(max_per_category=args.max_per_category)
        # Deduplicate by question
        seen: set[str] = set()
        unique = []
        for it in items:
            k = re.sub(r"[^a-z0-9 ]", " ", it["question"].lower()).strip()
            if k not in seen:
                seen.add(k); unique.append(it)
        print(f"  Total after dedup: {len(unique)} items")
        save_test_set(unique, test_set_path)

    if args.run or args.both:
        if not test_set_path.exists():
            print("Test set not found. Run with --build first.")
            sys.exit(1)
        items = json.loads(test_set_path.read_text(encoding="utf-8"))
        print(f"Evaluating {len(items)} items...")

        rag = CloudflareRAGOracle(worker_url=args.worker, domain=None, top_k=5)
        status = rag.status()
        print(f"  RAG corpus: {status.get('total_chunks', 0)} chunks")

        single = None
        if not args.no_single_oracle and os.environ.get("GROQ_API_KEY"):
            store = Store(".remora_cache.json")
            single = CachedOracle(GroqOracle("llama-3.3-70b-versatile"), store)

        results = run_evaluation(items, rag, single)
        print_report(results)

        # Save results
        out_path = ROOT / "results" / "rag_adversarial_results.json"
        out_path.write_text(
            json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n  Full results: {out_path}")


if __name__ == "__main__":
    main()
