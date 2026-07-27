# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Preflight liveness + JSON-compliance check for the SAP v2 Groq trio.

Codifies the 3-prompt smoke test referenced by
docs/assurance/statistical_analysis_plan_v2.md §2 (previously it existed
only as prose). Sends three fixed NON-benchmark prompts to each of the
pre-registered cross-family models and verifies that every response passes
the pipeline's own JSON extraction (remora.core._extract_json) with an
'answer' key present. No benchmark items or labels are used, so running
this any number of times cannot contaminate model selection.

Exit codes: 0 = all models pass, 1 = at least one model failed (fail-closed;
run before any live round so a dead/misbehaving model is caught before the
first ablation pass, not after it).

Usage: python scripts/preflight_groq_trio.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.oracles.families import validate_cross_family  # noqa: E402
from remora.oracles.groq import GroqOracle  # noqa: E402

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


def check_model(model: str) -> list[str]:
    """Return a list of failure descriptions for one model (empty = pass)."""
    failures: list[str] = []
    oracle = GroqOracle(model)
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
    models = list(GroqOracle.DEFAULT_MODELS)
    validate_cross_family(models)
    all_ok = True
    for model in models:
        failures = check_model(model)
        if failures:
            all_ok = False
            print(f"FAIL {model}")
            for f in failures:
                print(f"     - {f}")
        else:
            print(f"OK   {model} ({len(SMOKE_PROMPTS)}/{len(SMOKE_PROMPTS)} JSON-compliant)")
    if not all_ok:
        print("preflight FAILED — do not start the live round")
        return 1
    print("preflight passed — trio live and JSON-compliant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
