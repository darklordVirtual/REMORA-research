#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA External Validation Harness.

Two-track measurement:
  1. DIRECT ORACLE ACCURACY  — calls Groq API directly (no REMORA wrapper)
     to measure LLM factual accuracy on recognised HF benchmarks.
  2. REMORA GOVERNANCE       — runs engine.run() and records action/latency/audit.

Datasets: arc-challenge, arc-easy, boolq, hotpotqa
Metrics:  accuracy + Wilson 95% CI, REMORA action distribution, latency percentiles.

Usage:
    export $(grep -v '^#' .env.vars | xargs)
    python3 scripts/run_external_validation.py --n 50
    python3 scripts/run_external_validation.py \
        --datasets arc-challenge arc-easy boolq hotpotqa --n 300
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from typing import Any

from datasets import load_dataset
from remora.engine import Remora
from remora.genome import Genome
from remora.oracles.mock import MockOracle

_LIVE = False
_remora_oracles: list = []

# ---------------------------------------------------------------------------
# Direct oracle: rotating pool of 5 Cloudflare Workers AI models.
# Each item is answered by a different model (round-robin by item index).
# With N=100 items/dataset the heaviest model only sees ~20 calls — well
# within CF Workers AI rate limits.  No Groq dependency, no sleep needed.
# ---------------------------------------------------------------------------
_CF_DIRECT_POOL = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-4-scout-17b-16e-instruct",
    "@cf/mistralai/mistral-small-3.1-24b-instruct",
    "@cf/meta/llama-3.2-3b-instruct",
    "@cf/meta/llama-3.1-8b-instruct-fp8",
]
_cf_account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
_cf_api_key    = (
    os.environ.get("CF_AIG_TOKEN")
    or os.environ.get("CLOUDFLARE_API_TOKEN")
    or os.environ.get("CF_AI_GATEWAY_KEY", "")
)

try:
    from remora.oracles.cloudflare import CloudflareOracle
    if _cf_account_id and _cf_api_key:
        # REMORA consensus: two strong CF models for governance oracle pool
        _remora_oracles = [
            CloudflareOracle(model="@cf/meta/llama-3.3-70b-instruct-fp8-fast",    temperature=0.1),
            CloudflareOracle(model="@cf/meta/llama-4-scout-17b-16e-instruct",      temperature=0.1),
        ]
        _LIVE = True
        print("[+] REMORA oracles: CF(llama-3.3-70b-fp8) + CF(llama-4-scout)")
        print(f"[+] Direct oracle: rotating CF pool ({len(_CF_DIRECT_POOL)} models, round-robin)")
        for m in _CF_DIRECT_POOL:
            print(f"      {m}")
    else:
        print("[!] No CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN — MockOracle mode")
except Exception as exc:
    print(f"[!] Oracle import failed ({exc})")

ORACLES = _remora_oracles if _remora_oracles else [MockOracle(), MockOracle()]
PROVIDER_META = (
    [o.name if hasattr(o, "name") else o.__class__.__name__ for o in ORACLES]
    if _LIVE else ["mock", "mock"]
)
RANDOM_SEED = 42
PROMPT_VERSION = "v1.1"

DATASETS: dict[str, dict] = {
    "arc-challenge":  {"hf_id": "allenai/ai2_arc",          "hf_config": "ARC-Challenge",        "split": "test",       "type": "mc"},
    "arc-easy":       {"hf_id": "allenai/ai2_arc",          "hf_config": "ARC-Easy",             "split": "test",       "type": "mc"},
    "boolq":          {"hf_id": "google/boolq",            "hf_config": None,                   "split": "validation", "type": "bool"},
    "hotpotqa":       {"hf_id": "hotpotqa/hotpot_qa",      "hf_config": "distractor",           "split": "validation", "type": "freetext"},
    # --- Governance-relevant datasets (better fit for REMORA) ---
    "truthfulqa":     {"hf_id": "truthfulqa/truthful_qa",  "hf_config": "generation",           "split": "validation", "type": "truthfulqa"},
    "mmlu-ethics":    {"hf_id": "cais/mmlu",               "hf_config": "business_ethics",       "split": "validation", "type": "mmlu"},
    "mmlu-clinical":  {"hf_id": "cais/mmlu",               "hf_config": "clinical_knowledge",    "split": "validation", "type": "mmlu"},
    # --- RAG track: evidence-augmented prompts, demonstrates coverage > 0% ---
    "squad-rag":      {"hf_id": "rajpurkar/squad_v2",      "hf_config": None,                   "split": "validation", "type": "rag_squad"},
}


def build_prompt(ds_type: str, item: dict) -> tuple[str, str | None]:
    if ds_type == "mc":
        labels = item["choices"]["label"]
        texts  = item["choices"]["text"]
        choices = "\n".join(
            f"  {label}: {text}" for label, text in zip(labels, texts)
        )
        prompt = (f"Question: {item['question']}\nChoices:\n{choices}\n\n"
                  "Answer with only the single letter of the correct choice (A, B, C, or D):")
        return prompt, item["answerKey"]
    if ds_type == "bool":
        prompt = (f"Passage: {item['passage'][:600]}\nQuestion: {item['question']}\n\n"
                  "Answer with only 'True' or 'False':")
        return prompt, str(item["answer"]).lower()
    if ds_type == "freetext":
        prompt = f"Question: {item['question']}\n\nAnswer concisely (1-5 words):"
        return prompt, item["answer"].strip().lower()
    if ds_type == "mmlu":
        idx_to_letter = {0: "A", 1: "B", 2: "C", 3: "D"}
        choices = "\n".join(f"  {idx_to_letter[i]}: {c}" for i, c in enumerate(item["choices"]))
        prompt = (f"Question: {item['question']}\nChoices:\n{choices}\n\n"
                  "Answer with only the single letter of the correct choice (A, B, C, or D):")
        return prompt, idx_to_letter.get(item["answer"], "A")
    if ds_type == "truthfulqa":
        prompt = (f"Question: {item['question']}\n\n"
                  "Answer concisely and truthfully (1-2 sentences):")
        return prompt, item["best_answer"].strip().lower()
    if ds_type == "rag_squad":
        context = item["context"][:800]
        answers = item["answers"]["text"]
        expected = answers[0].strip().lower() if answers else "unanswerable"
        prompt = (f"Evidence: {context}\n\n"
                  f"Question: {item['question']}\n\n"
                  "Based solely on the evidence above, answer concisely (1-5 words). "
                  "If the evidence does not contain the answer, respond with exactly: unanswerable")
        return prompt, expected
    raise ValueError(f"Unknown ds_type: {ds_type}")


def extract_answer(ds_type: str, raw: str) -> str | None:
    raw = (raw or "").strip()
    if ds_type == "mc":
        if len(raw) == 1 and raw.upper() in "ABCDE":
            return raw.upper()
        m = re.search(r"(?:answer(?:ing)?(?:\s+is)?|choice|option|correct)[:\s]+([A-E])\b",
                      raw[:150], re.IGNORECASE)
        if m: return m.group(1).upper()
        m = re.search(r"\b([A-E])\b", raw[:60], re.IGNORECASE)
        if m: return m.group(1).upper()
        return None
    if ds_type == "bool":
        try:
            parsed = json.loads(raw)
            val = parsed.get("answer")
            if val is True  or str(val).lower() == "true":  return "true"
            if val is False or str(val).lower() == "false": return "false"
        except Exception:
            pass
        r = raw.lower()
        if r.startswith("true"):  return "true"
        if r.startswith("false"): return "false"
        if "true"  in r[:60]: return "true"
        if "false" in r[:60]: return "false"
        return None
    if ds_type == "mmlu":
        if len(raw) == 1 and raw.upper() in "ABCDE":
            return raw.upper()
        m = re.search(r"(?:answer(?:ing)?(?:\s+is)?|choice|option|correct)[:\s]+([A-E])\b",
                      raw[:150], re.IGNORECASE)
        if m: return m.group(1).upper()
        m = re.search(r"\b([A-E])\b", raw[:60], re.IGNORECASE)
        if m: return m.group(1).upper()
        return None
    if ds_type in ("truthfulqa", "rag_squad"):
        return raw.lower()
    return raw.lower()


def score_item(ds_type: str, pred: str | None, expected: str | None) -> bool | None:
    if pred is None or expected is None: return None
    if ds_type in ("mc", "mmlu"):   return pred.upper() == expected.upper()
    if ds_type == "bool":           return pred.lower() == expected.lower()
    if ds_type == "rag_squad":
        exp, pre = expected.lower().strip(), pred.lower().strip()
        if exp == "unanswerable":
            return "unanswer" in pre
        return exp == pre or exp in pre or pre in exp
    exp, pre = expected.lower().strip(), pred.lower().strip()
    return exp == pre or exp in pre or pre in exp


def direct_oracle_answer(ds_type: str, prompt: str, item_idx: int = 0) -> tuple[str | None, str]:
    """Call a Cloudflare Workers AI model from the rotating pool.

    Rotates through _CF_DIRECT_POOL by item_idx so each model receives ~N/5
    calls per dataset run — well within CF rate limits.  No retries; returns
    (None, model_name) on any error so the item is excluded from accuracy but
    still logged.
    """
    if not (_cf_account_id and _cf_api_key):
        return None, "mock"
    model = _CF_DIRECT_POOL[item_idx % len(_CF_DIRECT_POOL)]
    url = (f"https://api.cloudflare.com/client/v4/accounts/{_cf_account_id}"
           f"/ai/v1/chat/completions")
    import json as _j
    import urllib.request as _ur
    try:
        # Use more tokens for freetext answer types; single letter/word suffices for MC/bool/rag
        max_tok = 32 if ds_type in ("truthfulqa",) else 8
        payload = _j.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0, "max_tokens": max_tok,
        }).encode()
        req = _ur.Request(url, data=payload,
            headers={"Authorization": f"Bearer {_cf_api_key}",
                     "Content-Type": "application/json"},
            method="POST")
        with _ur.urlopen(req, timeout=25) as resp:
            raw = _j.loads(resp.read())["choices"][0]["message"]["content"] or ""
        return extract_answer(ds_type, raw), model
    except Exception:
        return None, model


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0: return (float("nan"), float("nan"))
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n)
    m = z * math.sqrt((p*(1-p) + z*z/(4*n)) / n)
    return (max(0.0, (c-m)/d), min(1.0, (c+m)/d))


def pct(data: list[float], q: float) -> float:
    if not data: return float("nan")
    s = sorted(data); return s[min(int(q/100*len(s)), len(s)-1)]


def decision_hash(dataset: str, item_id: str, action: str) -> str:
    s = json.dumps({"ds": dataset, "id": item_id, "action": action}, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def run_dataset(engine: Remora, ds_key: str, n: int, out_f) -> dict[str, Any]:
    cfg = DATASETS[ds_key]; ds_type = cfg["type"]
    print(f"\n{'='*62}\n  {ds_key}  split={cfg['split']}  n={n}\n{'='*62}")
    ds = load_dataset(cfg["hf_id"], cfg["hf_config"], split=cfg["split"])
    n  = min(n, len(ds))
    ds = ds.shuffle(seed=RANDOM_SEED).select(range(n))

    action_counts: Counter = Counter()
    remora_lats: list[float] = []; direct_lats: list[float] = []
    rows: list[dict] = []

    for idx, item in enumerate(ds):
        prompt, expected = build_prompt(ds_type, item)
        item_id = str(item.get("id", f"{ds_key}-{idx}"))

        t0 = time.time()
        direct_ans, direct_model_used = direct_oracle_answer(ds_type, prompt, idx)
        direct_lats.append(time.time() - t0)

        try:
            t0 = time.time()
            state  = engine.run(question=prompt, risk_tier="medium")
            report = engine.report(state)
            remora_lats.append(time.time() - t0)
        except Exception as exc:
            print(f"  [WARN] REMORA error at item {idx} ({item_id}): {exc}")
            remora_lats.append(time.time() - t0)
            row = {
                "dataset": ds_key, "item_id": item_id,
                "question": prompt[:300], "expected_answer": expected,
                "direct_oracle_answer": direct_ans,
                "direct_model": direct_model_used,
                "correct_direct": score_item(ds_type, direct_ans, expected) if _LIVE else None,
                "direct_latency_s": round(direct_lats[-1], 3),
                "action": "error", "phase": None, "H": None, "D": None, "trust": None,
                "V_trajectory": [], "policy_reason": str(exc),
                "remora_latency_s": round(remora_lats[-1], 3),
                "decision_hash": decision_hash(ds_key, item_id, "error"),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "model_providers": PROVIDER_META,
                "prompt_template_version": PROMPT_VERSION, "live_oracles": _LIVE,
            }
            out_f.write(json.dumps(row) + "\n"); out_f.flush()
            rows.append(row)
            action_counts["error"] += 1
            continue

        action = report["policy_decision"]["action"]
        action_counts[action] += 1
        log = state.consensus_log or []
        last = log[-1] if log else {}
        H = last.get("H", 0.0); D = last.get("D", 0.0)
        phase = getattr(getattr(state, "last_thermo", None), "phase", None)

        row = {
            "dataset": ds_key, "item_id": item_id,
            "question": prompt[:300], "expected_answer": expected,
            "direct_oracle_answer": direct_ans,
            "direct_model": direct_model_used,
            "correct_direct": score_item(ds_type, direct_ans, expected) if _LIVE else None,
            "direct_latency_s": round(direct_lats[-1], 3),
            "action": action, "phase": phase, "H": H, "D": D,
            "trust": round(max(0.0, 1.0 - (H*0.5 + D*1.5)), 4),
            "V_trajectory": [
                entry.get("V") for entry in log if isinstance(entry, dict) and "V" in entry
            ],
            "policy_reason": report["policy_decision"].get("explanation", ""),
            "remora_latency_s": round(remora_lats[-1], 3),
            "decision_hash": decision_hash(ds_key, item_id, action),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model_providers": PROVIDER_META,
            "prompt_template_version": PROMPT_VERSION,
            "live_oracles": _LIVE,
        }
        out_f.write(json.dumps(row) + "\n"); out_f.flush()
        rows.append(row)

        if (idx+1) % 25 == 0 or idx+1 == n:
            d = f"direct={direct_ans}" if direct_ans else "direct=None"
            print(f"  [{idx+1}/{n}] REMORA={action:<10} {d}  rlat={remora_lats[-1]:.2f}s")

    total = len(rows)
    scored   = sum(1 for r in rows if r["correct_direct"] is not None)
    correct  = sum(1 for r in rows if r["correct_direct"] is True)
    parseable = sum(1 for r in rows if r["direct_oracle_answer"] is not None)
    dir_ci   = wilson_ci(correct, scored) if scored else None

    stats = {
        "dataset": ds_key, "n": total, "live": _LIVE,
        "accepted":  action_counts["accept"],  "verified":  action_counts["verify"],
        "escalated": action_counts["escalate"], "abstained": action_counts["abstain"],
        "coverage":  round(action_counts["accept"]/total, 4) if total else 0,
        "direct_accuracy":  round(correct/scored, 4) if scored else None,
        "direct_correct":   correct, "direct_scored": scored, "direct_parseable": parseable,
        "direct_wilson_ci": dir_ci,
        "remora_latency_p50": round(pct(remora_lats, 50), 3),
        "remora_latency_p95": round(pct(remora_lats, 95), 3),
        "remora_latency_p99": round(pct(remora_lats, 99), 3),
        "direct_latency_p50": round(pct(direct_lats, 50), 3),
        "direct_latency_p95": round(pct(direct_lats, 95), 3),
    }

    print(f"\n  REMORA: accept={action_counts['accept']} verify={action_counts['verify']} "
          f"escalate={action_counts['escalate']} abstain={action_counts['abstain']}")
    if _LIVE:
        ci_str = f"[{dir_ci[0]:.3f},{dir_ci[1]:.3f}]" if dir_ci else "N/A"
        print(f"  Direct accuracy: {correct}/{scored}  Wilson 95% CI {ci_str}  (parseable {parseable}/{total})")
    print(f"  Latency REMORA p50={stats['remora_latency_p50']}s p95={stats['remora_latency_p95']}s | "
          f"Direct p50={stats['direct_latency_p50']}s")
    return stats


def write_report(all_stats: list[dict], outfile: str):
    def ci_str(ci):
        return f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "N/A"

    direct_models = ", ".join(
        f"`{model.rsplit('/', 1)[-1]}`" for model in _CF_DIRECT_POOL
    )
    lines = [
        "# REMORA External Validation Report\n",
        f"**Date:** {time.strftime('%Y-%m-%d')}",
        f"**Prompt template:** {PROMPT_VERSION}",
        f"**Direct oracle:** Cloudflare Workers AI rotating pool — {direct_models}",
        f"**REMORA oracles:** {', '.join(set(PROVIDER_META)) if _LIVE else 'MockOracle'}",
        f"**Random seed:** {RANDOM_SEED}  **Live:** {_LIVE}\n",
        "> **Claim status:** `internally_supported` — live-oracle runs on public HF benchmarks.",
        "> Upgrade to `externally_validated` only after independent replication.\n",
        "## Direct Oracle Accuracy (Groq llama-3.3-70b, direct — no REMORA wrapper)\n",
        "| Dataset | Accuracy | Wilson 95% CI | Correct | Scored | Parseable/N |",
        "|---------|----------|--------------|---------|--------|-------------|",
    ]
    for s in all_stats:
        acc = f"{s['direct_accuracy']:.1%}" if s["direct_accuracy"] is not None else "N/A (mock)"
        lines.append(f"| {s['dataset']} | {acc} | {ci_str(s['direct_wilson_ci'])} "
                     f"| {s['direct_correct']} | {s['direct_scored']} "
                     f"| {s['direct_parseable']}/{s['n']} |")

    lines += [
        "\n## REMORA Governance Action Distribution\n",
        "> REMORA is a governance circuit breaker — `verify` means the action needs supporting evidence.",
        "> For factual Q&A benchmarks, routing all items to `verify` is **correct** governance behaviour.\n",
        "| Dataset | N | Accept | Verify | Escalate | Abstain | Coverage |",
        "|---------|---|--------|--------|----------|---------|----------|",
    ]
    for s in all_stats:
        lines.append(f"| {s['dataset']} | {s['n']} | {s['accepted']} | {s['verified']} "
                     f"| {s['escalated']} | {s['abstained']} | {s['coverage']:.1%} |")

    lines += [
        "\n## Latency (seconds)\n",
        "| Dataset | REMORA p50 | REMORA p95 | REMORA p99 | Direct p50 | Direct p95 |",
        "|---------|-----------|-----------|-----------|-----------|-----------|",
    ]
    for s in all_stats:
        lines.append(f"| {s['dataset']} | {s['remora_latency_p50']} | {s['remora_latency_p95']} "
                     f"| {s['remora_latency_p99']} | {s['direct_latency_p50']} | {s['direct_latency_p95']} |")

    lines += [
        "\n## Methodology\n",
        "**Direct oracle accuracy:** Groq `llama-3.3-70b-versatile` called at temperature=0.0 (greedy).",
        "Prompt requests a single letter (MC) / True|False (BoolQ) / short phrase (HotpotQA).",
        "Answer parsed by regex; unparseable items are excluded from accuracy but counted.",
        "Wilson 95% CI computed on parseable items; HotpotQA accuracy is a **substring match upper bound**.\n",
        "**REMORA governance:** `engine.run(question, risk_tier='medium')` — 2-3 oracle consensus + policy gate.",
        "Coverage = proportion of items issued `accept`.",
        "Latency = wall-clock per item.\n",
        "**Datasets:**",
        "| Key | HF ID | Split | Type |",
        "|-----|-------|-------|------|",
    ]
    for k, v in DATASETS.items():
        lines.append(f"| {k} | {v['hf_id']} | {v['split']} | {v['type']} |")

    lines += [
        "\n## Known Limitations\n",
        "- Direct accuracy reflects oracle LLM capability, not REMORA governance quality.",
        "- REMORA routes factual Q&A to `verify` by design (coverage=0%). "
        "  The meaningful REMORA metric is latency overhead and audit completeness.",
        "- HotpotQA uses substring match, not token F1.",
        "- TruthfulQA accuracy is a substring match; it measures surface overlap, not hallucination rate.",
        "- MMLU accuracy uses letter matching (A/B/C/D); subject coverage reflects the selected configs.",
        "- SQuAD-RAG coverage > 0% is **expected** (evidence supplied) — this is not inflated accuracy, "
        "  it is governance coverage demonstrating the evidence-augmented accept path.",
        "- Results are non-deterministic; slight variation expected on rerun.",
        "\n## RAG Track Note\n",
        "`squad-rag` injects the Wikipedia passage as evidence directly into the REMORA prompt. "
        "Unlike the knowledge-retrieval benchmarks (ARC, BoolQ, HotpotQA), REMORA is supplied "
        "with supporting context, so `accept` outcomes are the *correct* governance behavior for "
        "answerable items. Unanswerable SQuAD-v2 items (no gold answer) are scored against the "
        "string `\"unanswerable\"`. Coverage on `squad-rag` should be interpreted as: "
        "*what fraction of evidence-grounded queries does REMORA approve without human review?*\n",
        "\n## Reproduction\n",
        "```bash",
        "export $(grep -v '^#' .env.vars | xargs)",
        "# Original four datasets",
        "python3 scripts/run_external_validation.py \\",
        "    --datasets arc-challenge arc-easy boolq hotpotqa --n 300 --seed 42",
        "# Governance-relevant + RAG track",
        "python3 scripts/run_external_validation.py \\",
        "    --datasets truthfulqa mmlu-ethics mmlu-clinical squad-rag --n 100 --seed 42",
        "```",
    ]

    with open(outfile, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[+] Report written to {outfile}")


def main():
    global RANDOM_SEED
    p = argparse.ArgumentParser()
    p.add_argument("--datasets", nargs="+", default=["arc-challenge", "boolq"],
                   choices=list(DATASETS.keys()))
    p.add_argument("--n",      type=int, default=50)
    p.add_argument("--out",    default="results/external_validation_raw.jsonl")
    p.add_argument("--report", default="results/external_validation_summary.md")
    p.add_argument("--seed",   type=int, default=42)
    args = p.parse_args()
    RANDOM_SEED = args.seed

    genome = Genome(enable_thermodynamic_control=True, enable_routing=True)
    engine = Remora(oracles=ORACLES, genome=genome)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    all_stats = []
    with open(args.out, "w") as out_f:
        for ds_key in args.datasets:
            all_stats.append(run_dataset(engine, ds_key, args.n, out_f))

    write_report(all_stats, args.report)
    total = sum(s["n"] for s in all_stats)
    print(f"\n{'='*62}")
    print(f"  COMPLETE — {total} items / {len(all_stats)} datasets")
    print(f"  JSONL :  {args.out}")
    print(f"  Report:  {args.report}")
    if not _LIVE:
        print("  NOTE: Set GROQ_API_KEY + CLOUDFLARE_API_TOKEN for live accuracy.")
    print("="*62)


if __name__ == "__main__":
    main()
