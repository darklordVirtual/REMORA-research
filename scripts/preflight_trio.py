# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Preflight liveness + JSON-compliance check for the round's oracle trio.

Backend-aware generalization of preflight_groq_trio.py (SAP v2 §2
amendment 2026-07-27: the live segment runs on Cloudflare Workers AI).
Sends three fixed NON-benchmark prompts to each model in the selected
backend's cross-family trio and verifies every response passes the
pipeline's own JSON extraction with an 'answer' key. No benchmark items or
labels are used.

Exit codes: 0 = all models pass, 1 = at least one model failed
(fail-closed: run before any live round so a dead, quota-exhausted or
JSON-noncompliant model is caught before the first ablation pass).

Usage: python scripts/preflight_trio.py [--backend cloudflare|groq]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.oracles.families import (  # noqa: E402
    CROSS_FAMILY_CF_MODELS,
    validate_cross_family,
)
from remora.oracles.factory import build_benchmark_oracle  # noqa: E402
from remora.oracles.groq import GroqOracle  # noqa: E402

TRIOS: dict[str, list[str]] = {
    "cloudflare": list(CROSS_FAMILY_CF_MODELS),
    "groq": list(GroqOracle.DEFAULT_MODELS),
}

# Deliberately trivial, non-benchmark prompts: the point is transport +
# JSON compliance, not knowledge.
SMOKE_PROMPTS = [
    "Is the number four larger than the number two?",
    "Do triangles have three sides?",
    "Is the letter A a vowel in the English alphabet?",
]

PROMPT_TEMPLATE = (
    "Answer the question below. Return ONLY valid JSON.\n"
    'Format: {"claim": "<specific statement>", "answer": true|false|null, '
    '"confidence": 0.0-1.0}\n\n'
    "Question: %s\n\nJSON:"
)


def check_model(backend: str, model: str) -> list[str]:
    """Return a list of failure descriptions for one model (empty = pass)."""
    failures: list[str] = []
    oracle = build_benchmark_oracle(backend, model)
    for q in SMOKE_PROMPTS:
        resp = oracle.ask(PROMPT_TEMPLATE % q)
        if resp.error:
            failures.append(f"{q!r}: call failed: {resp.error}")
        elif "answer" not in resp.extracted:
            failures.append(
                f"{q!r}: no parseable verdict JSON "
                f"(raw starts {resp.raw_text[:80]!r})"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Round trio preflight")
    parser.add_argument("--backend", choices=sorted(TRIOS), default="cloudflare")
    args = parser.parse_args()

    models = TRIOS[args.backend]
    validate_cross_family(models)
    all_ok = True
    for model in models:
        failures = check_model(args.backend, model)
        if failures:
            all_ok = False
            print(f"FAIL {model}")
            for f in failures:
                print(f"     - {f}")
        else:
            print(f"OK   {model} ({len(SMOKE_PROMPTS)}/{len(SMOKE_PROMPTS)} JSON-compliant)")
    if not all_ok:
        print(f"preflight FAILED ({args.backend}) — do not start the live round")
        return 1
    print(f"preflight passed — {args.backend} trio live and JSON-compliant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
