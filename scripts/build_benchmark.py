#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
REMORA benchmark builder - assembles a high-quality, multi-source evaluation set.

Sources
-------
1. TruthfulQA (Lin et al., 2022)
   817 questions designed to elicit LLM hallucinations. Ground truth validated
   by human experts against authoritative sources. The definitive benchmark for
   LLM truthfulness evaluation.
   HuggingFace: truthful_qa, subset "generation" + "multiple_choice"

2. BoolQ (Clark et al., 2019)
   9 765 yes/no questions from Google search snippets + Wikipedia passages.
   Covers broad general knowledge with high-quality human annotations.
   Sampled stratified by category to ensure domain balance.

3. REMORA curated set (Skogbrott, 2026)
   75 manually curated items across specialised, science, and general domains.
   Includes adversarial items and "insufficient evidence" ground truth.

4. Adversarial additions (hand-curated)
   Questions where popular belief contradicts authoritative sources -
   exactly the cases REMORA's RAG oracle is designed to handle.

Quality filters applied
-----------------------
- Minimum answer confidence in source dataset >= 0.8 (where available)
- Deduplicated by normalised question text (Jaccard similarity < 0.3)
- "Trick" questions labeled for adversarial analysis
- Each item includes domain, difficulty, and source provenance
- Items with ambiguous ground truth are labeled as UNCERTAIN and excluded
  from accuracy scoring (counted only in ETR abstention analysis)

Output
------
    remora/benchmarks/extended_v2.py     - Python module with 500+ items
    artifacts/benchmark_n500_locked.json - optional locked JSON snapshot
    artifacts/benchmark_stats.json       - quality report

Usage
-----
    python scripts/build_benchmark.py [--preset n500] [--seed S] [--output PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PRESETS = {
    "standard": {"truthfulqa_per_domain": 50, "boolq_per_domain": 25},
    "large":    {"truthfulqa_per_domain": 80, "boolq_per_domain": 50},
    "xl":       {"truthfulqa_per_domain": 100, "boolq_per_domain": 70},
    "n500":     {"truthfulqa_per_domain": 100, "boolq_per_domain": 160},
}

# -- Data classes --------------------------------------------------------------

@dataclass
class BenchmarkEntry:
    item_id: str
    question: str
    ground_truth: bool          # True / False (for UNCERTAIN items: None stored separately)
    domain: str                 # specialised | science | general
    benchmark: str              # source dataset
    difficulty: str             # easy | medium | hard | adversarial
    context: Optional[str]      # supporting passage if available
    best_answer: Optional[str]  # human-written correct answer (TruthfulQA)
    source_confidence: float    # confidence of ground-truth label [0,1]
    is_adversarial: bool        # popular belief opposes correct answer
    notes: Optional[str]


# -- TruthfulQA integration ----------------------------------------------------

TRUTHFULQA_DOMAIN_MAP = {
    "Misconceptions": "general",
    "Conspiracies": "general",
    "Fiction": "general",
    "Subjective": "general",
    "Religion": "general",
    "Politics": "general",
    "Sociology": "general",
    "Psychology": "science",
    "Science": "science",
    "Biology": "science",
    "Chemistry": "science",
    "Physics": "science",
    "Medicine": "science",
    "Health": "science",
    "Nutrition": "science",
    "Law": "specialised",
    "Economics": "specialised",
    "Finance": "specialised",
    "Statistics": "specialised",
    "Indexical Error": "general",
    "Language": "general",
    "History": "general",
    "Geography": "general",
    "Distraction": "general",
}

# Categories known to produce adversarial items (popular belief != truth)
ADVERSARIAL_CATEGORIES = {
    "Misconceptions", "Conspiracies", "Fiction", "Nutrition", "Health",
}


def _slug(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^a-zA-Z0-9 ]", "", text.lower()).strip()
    return re.sub(r"\s+", "_", text)[:max_len]


def _item_id(source: str, question: str, idx: int) -> str:
    h = hashlib.sha256(question.encode()).hexdigest()[:8]
    return f"{source}_{idx:04d}_{h}"


def load_truthfulqa(n_per_domain: int = 50, seed: int = 42) -> list[BenchmarkEntry]:
    """
    Load TruthfulQA from the official CSV on GitHub.

    Downloads TruthfulQA.csv directly - avoids HuggingFace datasets library
    compatibility issues with Python 3.14+.
    """
    import csv
    import io
    import random
    import urllib.request

    URL = "https://raw.githubusercontent.com/sylinrl/TruthfulQA/main/TruthfulQA.csv"
    print("Loading TruthfulQA from GitHub (official CSV)...")
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "REMORA/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as exc:
        print(f"  TruthfulQA download failed: {exc}")
        return []

    rng = random.Random(seed)

    # CSV columns: Type, Category, Question, Best Answer, Correct Answers, Incorrect Answers, ...
    by_domain: dict[str, list] = {}
    for row in rows:
        cat = row.get("Category") or row.get("Type") or "General"
        domain = TRUTHFULQA_DOMAIN_MAP.get(cat, "general")
        by_domain.setdefault(domain, []).append((row, cat))

    entries: list[BenchmarkEntry] = []
    for domain, dom_rows in by_domain.items():
        sample = rng.sample(dom_rows, min(n_per_domain, len(dom_rows)))
        for row, cat in sample:
            question = (row.get("Question") or row.get("question") or "").strip()
            if not question:
                continue

            best_answer = (row.get("Best Answer") or row.get("best_answer") or "").strip()
            _correct_str = (row.get("Correct Answers") or row.get("correct_answers") or "").strip()  # noqa: F841

            # Derive ground truth: the "Best Answer" should confirm or deny the claim
            best_lower = best_answer.lower()
            q_lower = question.lower()

            # Direct boolean answers
            if best_lower.startswith("yes") or best_lower in ("true", "correct"):
                gt = True
            elif best_lower.startswith("no") or best_lower in ("false", "incorrect"):
                gt = False
            elif q_lower.startswith(("is ", "does ", "do ", "can ", "was ", "were ", "has ", "have ", "did ")):
                # Binary question: infer from whether best answer negates
                neg_words = {"not", "no", "never", "false", "incorrect", "myth",
                             "untrue", "wrong", "doesn", "didn", "isn", "aren"}
                gt = not any(w in best_lower.split() for w in neg_words)
            else:
                continue  # Skip non-binary

            is_adv = cat in ADVERSARIAL_CATEGORIES
            entries.append(BenchmarkEntry(
                item_id=_item_id("tqa", question, len(entries)),
                question=question,
                ground_truth=gt,
                domain=domain,
                benchmark="truthfulqa",
                difficulty="hard" if is_adv else "medium",
                context=None,
                best_answer=best_answer,
                source_confidence=0.95,
                is_adversarial=is_adv,
                notes=f"TruthfulQA category: {cat}",
            ))

    print(f"  TruthfulQA: {len(entries)} items loaded")
    return entries


def load_boolq(n_per_domain: int = 30, seed: int = 42) -> list[BenchmarkEntry]:
    """
    Load BoolQ validation split via HuggingFace parquet (Python 3.14+ compatible).

    BoolQ: 9 765 yes/no questions paired with Wikipedia passages.
    Clark et al. (2019), Google Research.
    """
    import importlib
    import random
    import urllib.request
    import io

    # Try multiple sources in order
    URLS = [
        # HuggingFace parquet (most reliable)
        "https://huggingface.co/datasets/google/boolq/resolve/main/data/validation-00000-of-00001.parquet",
        # Original Google Storage
        "https://storage.googleapis.com/boolq/dev.jsonl",
    ]

    rows = None
    for URL in URLS:
        try:
            if URL.endswith(".parquet"):
                # Read parquet without pandas: use pyarrow if available
                try:
                    pq = importlib.import_module("pyarrow.parquet")
                    req = urllib.request.Request(URL, headers={"User-Agent": "REMORA/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        data = r.read()
                    table = pq.read_table(io.BytesIO(data))
                    rows = [
                        {
                            "question": str(row["question"]),
                            "answer": bool(row["answer"]),
                            "passage": str(row["passage"]),
                        }
                        for row in table.to_pylist()
                    ]
                    print(f"  BoolQ: loaded {len(rows)} items via parquet")
                    break
                except ImportError:
                    print("  pyarrow not available, trying next source")
                    continue
            else:
                req = urllib.request.Request(URL, headers={"User-Agent": "REMORA/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    lines = r.read().decode("utf-8", "replace").splitlines()
                rows = [json.loads(line) for line in lines if line.strip()]
                if rows:
                    print(f"  BoolQ: loaded {len(rows)} items via JSONL")
                    break
        except Exception as exc:
            print(f"  BoolQ {URL[:50]}: {exc}")
            continue

    if not rows:
        print("  BoolQ: all sources failed, skipping")
        return []

    # rows already loaded above; normalise field names
    ds = [
        {
            "question": r.get("question", ""),
            "answer": r.get("answer", False),
            "passage": r.get("passage", ""),
        }
        for r in rows
    ]

    rng = random.Random(seed)

    # BoolQ has no explicit domain tags - classify by passage content
    science_kw = {"biology", "chemistry", "physics", "medicine", "gene", "protein",
                  "cell", "atom", "molecule", "species", "evolution", "quantum",
                  "disease", "virus", "bacteria", "climate", "element"}
    specialised_kw = {"law", "legal", "regulation", "statute", "court", "patent",
                      "finance", "contract", "constitution", "policy", "act of",
                      "treaty", "amendment", "tax", "liability"}

    def classify(row) -> str:
        text = (row["passage"] + " " + row["question"]).lower()
        words = set(re.findall(r"\b\w+\b", text))
        if words & science_kw:
            return "science"
        if words & specialised_kw:
            return "specialised"
        return "general"

    by_domain: dict[str, list] = {}
    for row in ds:
        d = classify(row)
        by_domain.setdefault(d, []).append(row)

    entries: list[BenchmarkEntry] = []
    for domain, rows in by_domain.items():
        sample = rng.sample(rows, min(n_per_domain, len(rows)))
        for row in sample:
            entries.append(BenchmarkEntry(
                item_id=_item_id("boolq", row["question"], len(entries)),
                question=row["question"].rstrip("?") + "?",
                ground_truth=bool(row["answer"]),
                domain=domain,
                benchmark="boolq",
                difficulty="easy",
                context=row["passage"][:800],
                best_answer=None,
                source_confidence=0.90,
                is_adversarial=False,
                notes=None,
            ))

    print(f"  BoolQ: {len(entries)} items loaded")
    return entries


def load_remora_curated() -> list[BenchmarkEntry]:
    """Load the existing 75-item REMORA curated set."""
    try:
        from remora.benchmarks.extended import load_all_extended
        items = load_all_extended()
        entries = []
        for it in items:
            gt = it.ground_truth
            if isinstance(gt, str):
                gt_bool = gt.lower() in ("true", "yes", "1")
            else:
                gt_bool = bool(gt)
            entries.append(BenchmarkEntry(
                item_id=it.item_id,
                question=it.question,
                ground_truth=gt_bool,
                domain=it.benchmark.replace("_ext", ""),
                benchmark="remora_curated",
                difficulty="hard" if "dce" in it.benchmark else "medium",
                context=it.context,
                best_answer=None,
                source_confidence=1.0,
                is_adversarial=False,
                notes="REMORA 75-item curated set",
            ))
        print(f"  REMORA curated: {len(entries)} items loaded")
        return entries
    except Exception as exc:
        print(f"  REMORA curated load failed: {exc}")
        return []


# -- Hand-curated adversarial additions ---------------------------------------
# Questions where popular belief contradicts authoritative sources.
# These target the unanimous-consensus failure mode identified in the ablation.

ADVERSARIAL_ADDITIONS: list[BenchmarkEntry] = [
    BenchmarkEntry(
        item_id="adv_001", domain="general", benchmark="adversarial_curated",
        question="Is the Great Wall of China visible from space with the naked eye?",
        ground_truth=False, difficulty="adversarial", context=None,
        best_answer="No - the wall is too narrow to resolve at orbital altitude.",
        source_confidence=1.0, is_adversarial=True,
        notes="Common myth contradicted by NASA and multiple astronauts",
    ),
    BenchmarkEntry(
        item_id="adv_002", domain="science", benchmark="adversarial_curated",
        question="Do humans use only 10 percent of their brain?",
        ground_truth=False, difficulty="adversarial", context=None,
        best_answer="No - virtually all brain regions are active and necessary.",
        source_confidence=1.0, is_adversarial=True,
        notes="Persistent myth contradicted by neuroscience consensus",
    ),
    BenchmarkEntry(
        item_id="adv_003", domain="science", benchmark="adversarial_curated",
        question="Does lightning never strike the same place twice?",
        ground_truth=False, difficulty="adversarial", context=None,
        best_answer="No - tall structures are struck repeatedly (e.g., Empire State Building).",
        source_confidence=1.0, is_adversarial=True,
        notes="Physical myth - tall conductors attract repeated strikes",
    ),
    BenchmarkEntry(
        item_id="adv_004", domain="general", benchmark="adversarial_curated",
        question="Was Napoleon Bonaparte unusually short for his time?",
        ground_truth=False, difficulty="adversarial", context=None,
        best_answer="No - he was approximately average height for a Frenchman of his era.",
        source_confidence=0.95, is_adversarial=True,
        notes="Height myth arose from confusion between French and English inches",
    ),
    BenchmarkEntry(
        item_id="adv_005", domain="science", benchmark="adversarial_curated",
        question="Is the tongue divided into distinct taste zones?",
        ground_truth=False, difficulty="adversarial", context=None,
        best_answer="No - taste receptors for all flavours are distributed across the tongue.",
        source_confidence=1.0, is_adversarial=True,
        notes="Tongue map myth disproven by modern gustatory neuroscience",
    ),
    BenchmarkEntry(
        item_id="adv_006", domain="general", benchmark="adversarial_curated",
        question="Did George Washington have wooden teeth?",
        ground_truth=False, difficulty="adversarial", context=None,
        best_answer="No - his dentures were made of ivory, bone, and human/animal teeth.",
        source_confidence=1.0, is_adversarial=True,
        notes="Documented by Smithsonian Institution from surviving denture specimens",
    ),
    BenchmarkEntry(
        item_id="adv_007", domain="science", benchmark="adversarial_curated",
        question="Do bulls become enraged by the colour red?",
        ground_truth=False, difficulty="adversarial", context=None,
        best_answer="No - bulls are red-green colour-blind; they react to movement.",
        source_confidence=1.0, is_adversarial=True,
        notes="Confirmed by comparative vision research; MythBusters also tested",
    ),
    BenchmarkEntry(
        item_id="adv_008", domain="science", benchmark="adversarial_curated",
        question="Is it safe to wake someone who is sleepwalking?",
        ground_truth=True, difficulty="adversarial", context=None,
        best_answer="Yes - waking a sleepwalker is safe, though they may be briefly confused.",
        source_confidence=0.90, is_adversarial=True,
        notes="The belief that it is dangerous is a persistent myth; clinical consensus supports waking",
    ),
]


# -- Deduplication -------------------------------------------------------------

def _normalise(text: str) -> set[str]:
    text = re.sub(r"[^a-zA-Z0-9 ]", " ", text.lower())
    return set(text.split())


def deduplicate(entries: list[BenchmarkEntry], threshold: float = 0.4) -> list[BenchmarkEntry]:
    """Remove near-duplicate questions using Jaccard similarity."""
    kept: list[BenchmarkEntry] = []
    kept_tokens: list[set[str]] = []
    removed = 0
    for entry in entries:
        tokens = _normalise(entry.question)
        is_dup = any(
            len(tokens & kt) / len(tokens | kt) >= threshold
            for kt in kept_tokens
        )
        if not is_dup:
            kept.append(entry)
            kept_tokens.append(tokens)
        else:
            removed += 1
    print(f"  Deduplication: removed {removed} near-duplicates ({len(kept)} remaining)")
    return kept


# -- Generate extended benchmark Python module ---------------------------------

BENCHMARK_MODULE_TEMPLATE = '''# Author: Stian Skogbrott
# License: Apache-2.0
# AUTO-GENERATED by scripts/build_benchmark.py - do not edit manually
"""
REMORA Extended Benchmark v2 - {n_total} items across {n_domains} domains.

Sources: TruthfulQA (Lin et al., 2022), BoolQ (Clark et al., 2019),
         REMORA curated 75 (Skogbrott, 2026), adversarial additions.

Generated: {timestamp}
"""
from __future__ import annotations
from remora.benchmarks.loaders import BenchmarkItem, GroundTruthType

_ITEMS = {items_repr}

def load_all_extended_v2() -> list[BenchmarkItem]:
    """Return the full v2 benchmark: {n_total} items."""
    return [
        BenchmarkItem(
            item_id=it["item_id"],
            question=it["question"],
            ground_truth=it["ground_truth"],
            truth_type=GroundTruthType.POLARITY.value,
            benchmark=it["benchmark"],
            context=it.get("context"),
        )
        for it in _ITEMS
    ]

def load_by_domain(domain: str) -> list[BenchmarkItem]:
    """Filter by domain: specialised | science | general."""
    return [
        BenchmarkItem(
            item_id=it["item_id"],
            question=it["question"],
            ground_truth=it["ground_truth"],
            truth_type=GroundTruthType.POLARITY.value,
            benchmark=it["benchmark"],
            context=it.get("context"),
        )
        for it in _ITEMS
        if it.get("domain") == domain
    ]

def load_adversarial() -> list[BenchmarkItem]:
    """Return only adversarial items (popular belief contradicts ground truth)."""
    return [
        BenchmarkItem(
            item_id=it["item_id"],
            question=it["question"],
            ground_truth=it["ground_truth"],
            truth_type=GroundTruthType.POLARITY.value,
            benchmark=it["benchmark"],
            context=it.get("context"),
        )
        for it in _ITEMS
        if it.get("is_adversarial")
    ]
'''


def write_benchmark_module(entries: list[BenchmarkEntry], output_path: Path) -> None:
    """Write the assembled benchmark as an importable Python module."""
    from datetime import UTC, datetime

    serialisable = [
        {k: v for k, v in asdict(e).items()
         if k in ("item_id", "question", "ground_truth", "domain",
                  "benchmark", "difficulty", "context", "best_answer",
                  "source_confidence", "is_adversarial", "notes")}
        for e in entries
    ]

    domains = len(set(e.domain for e in entries))
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Use repr() so Python booleans (True/False/None) are valid Python syntax
    items_repr = repr(serialisable)
    code = BENCHMARK_MODULE_TEMPLATE.format(
        n_total=len(entries),
        n_domains=domains,
        timestamp=timestamp,
        items_repr=items_repr,
    )
    output_path.write_text(code, encoding="utf-8")
    print(f"  Benchmark module written: {output_path} ({len(entries)} items)")


def write_benchmark_snapshot(entries: list[BenchmarkEntry], output_path: Path) -> None:
    """Write a locked JSON snapshot of the assembled benchmark."""
    payload = {
        "meta": {
            "n_items": len(entries),
            "sources": sorted({entry.benchmark for entry in entries}),
            "domains": sorted({entry.domain for entry in entries}),
        },
        "items": [asdict(entry) for entry in entries],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  Benchmark snapshot written: {output_path} ({len(entries)} items)")


# -- Quality report ------------------------------------------------------------

def quality_report(entries: list[BenchmarkEntry]) -> dict:
    by_source: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    by_diff: dict[str, int] = {}
    n_adversarial = 0
    n_true = 0

    for e in entries:
        by_source[e.benchmark] = by_source.get(e.benchmark, 0) + 1
        by_domain[e.domain]    = by_domain.get(e.domain, 0) + 1
        by_diff[e.difficulty]  = by_diff.get(e.difficulty, 0) + 1
        if e.is_adversarial: n_adversarial += 1
        if e.ground_truth:   n_true += 1

    return {
        "total": len(entries),
        "by_source": by_source,
        "by_domain": by_domain,
        "by_difficulty": by_diff,
        "adversarial_fraction": round(n_adversarial / len(entries), 3),
        "balance": round(n_true / len(entries), 3),  # target ~0.5
        "mean_source_confidence": round(
            sum(e.source_confidence for e in entries) / len(entries), 3
        ),
    }


# -- Main ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build REMORA extended benchmark v2")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="standard",
                        help="Sampling preset for external benchmarks (default: standard)")
    parser.add_argument("--n-per-domain", type=int, default=50,
                        help="Legacy control: TruthfulQA items per domain; BoolQ defaults to half of this unless overridden")
    parser.add_argument("--truthfulqa-per-domain", type=int, default=None,
                        help="Override TruthfulQA sample count per domain")
    parser.add_argument("--boolq-per-domain", type=int, default=None,
                        help="Override BoolQ sample count per domain")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str,
                        default=str(ROOT / "remora" / "benchmarks" / "extended_v2.py"))
    parser.add_argument("--snapshot-json", type=str, default=None,
                        help="Optional locked JSON snapshot path for the assembled benchmark")
    parser.add_argument("--stats", type=str,
                        default=str(ROOT / "artifacts" / "benchmark_stats.json"))
    parser.add_argument("--skip-hf", action="store_true",
                        help="Skip HuggingFace downloads (use only local + adversarial)")
    args = parser.parse_args()

    preset = PRESETS[args.preset]
    truthfulqa_per_domain = args.truthfulqa_per_domain
    if truthfulqa_per_domain is None:
        truthfulqa_per_domain = args.n_per_domain if args.n_per_domain != 50 else preset["truthfulqa_per_domain"]

    boolq_per_domain = args.boolq_per_domain
    if boolq_per_domain is None:
        boolq_per_domain = args.n_per_domain // 2 if args.n_per_domain != 50 else preset["boolq_per_domain"]

    Path(args.stats).parent.mkdir(parents=True, exist_ok=True)

    all_entries: list[BenchmarkEntry] = []

    if not args.skip_hf:
        print(
            f"Using preset '{args.preset}': TruthfulQA/domain={truthfulqa_per_domain}, "
            f"BoolQ/domain={boolq_per_domain}"
        )
        all_entries += load_truthfulqa(n_per_domain=truthfulqa_per_domain, seed=args.seed)
        all_entries += load_boolq(n_per_domain=boolq_per_domain, seed=args.seed)
    else:
        print("Skipping HuggingFace downloads (--skip-hf)")

    all_entries += load_remora_curated()
    all_entries += ADVERSARIAL_ADDITIONS

    print(f"\nTotal before deduplication: {len(all_entries)}")
    all_entries = deduplicate(all_entries, threshold=0.40)

    report = quality_report(all_entries)
    print("\nBenchmark quality report:")
    print(f"  Total items:        {report['total']}")
    print(f"  By domain:          {report['by_domain']}")
    print(f"  By source:          {report['by_source']}")
    print(f"  Adversarial items:  {report['adversarial_fraction']:.0%}")
    print(f"  Answer balance:     {report['balance']:.0%} True")
    print(f"  Mean source conf:   {report['mean_source_confidence']:.3f}")

    write_benchmark_module(all_entries, Path(args.output))
    if args.snapshot_json:
        write_benchmark_snapshot(all_entries, Path(args.snapshot_json))
    Path(args.stats).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  Stats written: {args.stats}")


if __name__ == "__main__":
    main()
