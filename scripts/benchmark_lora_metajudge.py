#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Benchmark AROMER MetaJudge base vs LoRA on heldout prompt/completion JSONL."""
from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_HELDOUT = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "lora"
    / "aromer-metajudge-v1"
    / "heldout.jsonl"
)
DEFAULT_MODEL = "@cf/mistralai/mistral-7b-instruct-v0.2-lora"
_SSL = ssl.create_default_context()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        expected = json.loads(row["completion"])
        cases.append({"prompt": row["prompt"], "expected": expected})
    return cases


def parse_response(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        if isinstance(raw.get("response"), dict):
            return raw["response"]
        text = str(raw.get("response", raw))
    else:
        text = str(raw)
    text = text.replace("<think>", "").replace("</think>", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    return {}


def score_prediction(predicted: dict[str, Any], expected: dict[str, Any]) -> float:
    fields = ("safety_score", "truth_score", "calibration_score")
    if not predicted:
        return 0.0
    gaps = []
    for field in fields:
        try:
            p = max(0.0, min(1.0, float(predicted[field])))
            e = max(0.0, min(1.0, float(expected[field])))
        except (KeyError, TypeError, ValueError):
            return 0.0
        gaps.append(abs(p - e))
    return max(0.0, 1.0 - (sum(gaps) / len(gaps)))


def call_workers_ai(
    prompt: str,
    *,
    account_id: str,
    api_token: str,
    model: str,
    lora: str | None = None,
) -> dict[str, Any]:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.1,
    }
    if lora:
        payload["raw"] = True
        payload["lora"] = lora
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "User-Agent": "AROMER-LoRA-benchmark/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60, context=_SSL) as response:
        data = json.loads(response.read().decode("utf-8"))
    return parse_response(data.get("result", data))


def benchmark(
    cases: list[dict[str, Any]],
    *,
    account_id: str,
    api_token: str,
    model: str,
    lora: str | None,
    limit: int,
) -> dict[str, Any]:
    selected = cases[:limit] if limit > 0 else cases
    scores = []
    for case in selected:
        pred = call_workers_ai(
            case["prompt"],
            account_id=account_id,
            api_token=api_token,
            model=model,
            lora=lora,
        )
        scores.append(score_prediction(pred, case["expected"]))
    accuracy = sum(1 for score in scores if score >= 0.90) / len(scores) if scores else 0.0
    mean_score = sum(scores) / len(scores) if scores else 0.0
    return {
        "n": len(scores),
        "accuracy_at_0_90": round(accuracy, 4),
        "mean_score": round(mean_score, 4),
        "lora": lora or "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heldout", type=Path, default=DEFAULT_HELDOUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--lora", default=os.getenv("CF_LORA_ID", ""))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if not account_id or not api_token:
        raise SystemExit("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required")

    cases = load_cases(args.heldout)
    base = benchmark(
        cases,
        account_id=account_id,
        api_token=api_token,
        model=args.model,
        lora=None,
        limit=args.limit,
    )
    lora = benchmark(
        cases,
        account_id=account_id,
        api_token=api_token,
        model=args.model,
        lora=args.lora or None,
        limit=args.limit,
    )
    result = {"base": base, "lora": lora, "success": lora["accuracy_at_0_90"] > 0.90}
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
