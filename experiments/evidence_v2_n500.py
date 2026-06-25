# Author: Stian Skogbrott
# License: Apache-2.0
"""Replay N500 backfill items through EvidenceOracleV2 and report accuracy.

The existing backfill JSON is expected to contain per-item: question (string),
gold answer (string or bool), and a list of evidence snippets with url + text.
The script auto-detects field names defensively across many candidate schemas.

If no per-item evidence blob can be located in the source JSON, the script
records skipped_no_evidence in the output and still emits a payload with
zero answered / zero abstained — it does NOT fabricate evidence. The
downstream pipeline should re-emit the N500 backfill with evidence text
attached if a full EvidenceOracleV2 evaluation is wanted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from remora.oracles.evidence_v2 import EvidenceOracleV2
from remora.oracles.sources import Source, SourceCorpus


_QUESTION_KEYS = (
    "question", "sub_q", "query", "prompt", "claim", "input", "item_text",
)

_EVIDENCE_KEYS = (
    "evidence", "sources", "snippets", "passages", "documents",
    "evidence_v1", "retrieved", "rag_retrieved_chunks", "retrieved_chunks",
    "context", "supporting_documents",
)

_GOLD_KEYS = (
    "gold", "answer", "label", "ground_truth", "gold_answer", "target",
)

_URL_KEYS = ("url", "link", "source", "uri", "href")
_TEXT_KEYS = ("text", "snippet", "content", "passage", "body", "chunk")


def _get_question(item: dict) -> str | None:
    for key in _QUESTION_KEYS:
        v = item.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _coerce_source(snip: dict) -> Source | None:
    if not isinstance(snip, dict):
        return None
    url = None
    for k in _URL_KEYS:
        v = snip.get(k)
        if isinstance(v, str) and v:
            url = v
            break
    text = None
    for k in _TEXT_KEYS:
        v = snip.get(k)
        if isinstance(v, str) and v:
            text = v
            break
    if not url or not text:
        return None
    try:
        return Source(url=url, text=text)
    except ValueError:
        return None


def _get_evidence(item: dict) -> list[Source]:
    """Defensively locate evidence snippets across many candidate schemas."""
    out: list[Source] = []
    for key in _EVIDENCE_KEYS:
        raw = item.get(key)
        if isinstance(raw, list) and raw:
            for snip in raw:
                src = _coerce_source(snip)
                if src is not None:
                    out.append(src)
            if out:
                return out
    return out


def _get_gold(item: dict):
    for key in _GOLD_KEYS:
        if key in item:
            return item[key]
    return None


def _is_correct(verdict_answer: str | None, gold) -> bool:
    if verdict_answer is None or gold is None:
        return False
    return str(gold).lower() in (verdict_answer or "").lower()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default="results/evidence_v2_n500.json", type=Path)
    parser.add_argument("--min-reliability", type=float, default=0.5)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--max-contradictions", type=int, default=0)
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    items = raw.get("items") or raw.get("results") or raw.get("details") or raw
    if not isinstance(items, list):
        raise SystemExit(f"Unrecognised structure in {args.input}")

    oracle = EvidenceOracleV2(
        min_reliability=args.min_reliability,
        min_support=args.min_support,
        max_contradictions=args.max_contradictions,
    )

    answered = abstained = correct = 0
    skipped_no_question = 0
    skipped_no_evidence = 0
    per_item = []
    for it in items:
        if not isinstance(it, dict):
            continue
        q = _get_question(it)
        srcs = _get_evidence(it)
        if not q:
            skipped_no_question += 1
            continue
        if not srcs:
            skipped_no_evidence += 1
            continue
        verdict = oracle.answer(q, SourceCorpus(sources=tuple(srcs)))
        gold = _get_gold(it)
        if verdict.action == "answer":
            answered += 1
            if _is_correct(verdict.answer, gold):
                correct += 1
        else:
            abstained += 1
        per_item.append({
            "question": q,
            "action": verdict.action,
            "answer": verdict.answer,
            "supporters": verdict.supporters,
            "contradictions": verdict.contradictions,
            "cited_sources": list(verdict.cited_sources),
            "gold": gold,
        })

    coverage = answered / (answered + abstained) if (answered + abstained) else 0.0
    accuracy_answered = correct / answered if answered else 0.0
    payload = {
        "input": args.input.as_posix(),
        "n_items_total": len(items) if isinstance(items, list) else 0,
        "n_evaluated": len(per_item),
        "skipped_no_question": skipped_no_question,
        "skipped_no_evidence": skipped_no_evidence,
        "answered": answered,
        "abstained": abstained,
        "correct_when_answered": correct,
        "coverage": coverage,
        "accuracy_on_answered": accuracy_answered,
        "config": {
            "min_reliability": args.min_reliability,
            "min_support": args.min_support,
            "max_contradictions": args.max_contradictions,
        },
        "items": per_item,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"wrote {args.output}: "
        f"evaluated={len(per_item)}/{len(items) if isinstance(items, list) else 0} "
        f"coverage={coverage:.3f} accuracy_answered={accuracy_answered:.3f} "
        f"skipped_no_question={skipped_no_question} "
        f"skipped_no_evidence={skipped_no_evidence}"
    )


if __name__ == "__main__":
    main()
