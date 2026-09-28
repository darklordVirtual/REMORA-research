#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A single-model baseline built from replay seeds may not pass as a model (Q1.4).

The tool-call benchmark's ``single_model_gpt/claude/gemini`` baselines are
heuristic stand-ins unless a live run answered them. Result files record this
per baseline under ``decision_sources`` (``replay_seed``, ``live:<model>`` or
``mixed``). Until 2026-09-28 nothing did: all 700 decisions per "model" in the
committed files are seeds.

This gate reads every scope that names one of those baselines (an entry of
``docs/thermodynamics/claim_ledger.yaml``, a statement of
``docs/assurance/claim_register_v1.yaml``, a ``##`` section of a Markdown file
under ``docs/``) and cites a result file whose ``decision_sources`` says a
named baseline is not fully live. Such a scope must say ``replay`` or
``seed``, so no reader takes a seed for a model's answer.

    python scripts/check_decision_sources.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterator

import yaml

ROOT = Path(__file__).resolve().parent.parent
_BASELINE = re.compile(r"single_model_(?:gpt|claude|gemini)")
_RESULT = re.compile(r"results/[\w./-]+\.json")
_DISCLOSED = re.compile(r"\breplay|\bseed", re.IGNORECASE)


def _scopes(root: Path) -> Iterator[tuple[str, str]]:
    ledger = root / "docs/thermodynamics/claim_ledger.yaml"
    if ledger.exists():
        for cid, claim in (yaml.safe_load(ledger.read_text(encoding="utf-8")) or {}).get("claims", {}).items():
            yield f"claim_ledger.yaml:{cid}", yaml.safe_dump(claim)
    register = root / "docs/assurance/claim_register_v1.yaml"
    if register.exists():
        for claim in (yaml.safe_load(register.read_text(encoding="utf-8")) or {}).get("claims", []):
            yield f"claim_register_v1.yaml:{claim.get('id')}", yaml.safe_dump(claim)
    for md in sorted((root / "docs").rglob("*.md")):
        rel = md.relative_to(root).as_posix()
        if rel.startswith("docs/archive/"):
            continue
        for i, section in enumerate(re.split(r"\n(?=##\s)", md.read_text(encoding="utf-8"))):
            yield f"{rel}#section{i}", section


def _not_live(root: Path, rel: str, cache: dict[str, dict]) -> set[str]:
    if rel not in cache:
        path = root / rel
        try:
            cache[rel] = json.loads(path.read_text(encoding="utf-8")).get("decision_sources") or {}
        except (OSError, json.JSONDecodeError, AttributeError):
            cache[rel] = {}
    return {name for name, info in cache[rel].items() if not str(info.get("source", "")).startswith("live:")}


def find_violations(root: Path) -> list[str]:
    cache: dict[str, dict] = {}
    out = []
    for where, text in _scopes(root):
        named = set(_BASELINE.findall(text))
        if not named or _DISCLOSED.search(text):
            continue
        for rel in sorted(set(_RESULT.findall(text))):
            seeded = named & _not_live(root, rel, cache)
            if seeded:
                out.append(f"{where}: cites {', '.join(sorted(seeded))} from {rel}, which are replay seeds, "
                           f"without saying so")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="replay-seed disclosure gate")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    violations = find_violations(args.root)
    if violations:
        print("[FAIL] single-model baselines cited as if a model answered them:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("[PASS] every citation of a seeded single-model baseline says it is a replay seed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
