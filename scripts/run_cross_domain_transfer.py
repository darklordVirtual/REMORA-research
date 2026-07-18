#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Produce the cross-domain transfer artifact (§16 — measure T4 for real).

Reuses the curated, deterministic episode templates from
``scripts/feed_aromer_episodes.py`` (the same labelled corpus fed to the live
worker), runs the leave-one-domain-out abstract-prior transfer harness, and
writes ``results/aromer_cross_domain_transfer_v1.json``.

The result is deterministic (no jitter — templates expanded at count=1 per
row) and reproducible offline; no live worker or API key is required.

    python scripts/run_cross_domain_transfer.py
    python scripts/run_cross_domain_transfer.py --threshold 0.5 --min-per-domain 3
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.aromer.evals.cross_domain_transfer import (  # noqa: E402
    TransferEpisode,
    run_cross_domain_transfer,
)

# Import the curated templates from the feeder (single source of truth).
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "feed_aromer_episodes", ROOT / "scripts" / "feed_aromer_episodes.py"
)
_feed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_feed)

_HARM_GT = {"harmful"}


def _episodes() -> list[TransferEpisode]:
    """One TransferEpisode per curated template row (deterministic).

    A 'harmful' ground_truth => harm label True; a VERIFY/benign_review
    partial signal gets weight 0.25 (matching the world model's own
    DecisionQuality weighting), strong signals weight 1.0.
    """
    out: list[TransferEpisode] = []
    for (domain, risk_tier, action_type, _phase, _trust, _h, _d,
         verdict, ground_truth, _conf, _sev, count) in _feed.TEMPLATES:
        harmful = ground_truth in _HARM_GT
        # Partial signal for VERIFY-tier labels (gray-zone), strong otherwise.
        weight = 0.25 if verdict == "VERIFY" else 1.0
        # Preserve the corpus's class balance by expanding to the row count.
        for _ in range(count):
            out.append(TransferEpisode(domain, action_type, risk_tier,
                                       harmful=harmful, weight=weight))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--min-per-domain", type=int, default=3,
                    help="drop domains with fewer labelled episodes (noise floor)")
    ap.add_argument("--output", type=Path,
                    default=ROOT / "results" / "aromer_cross_domain_transfer_v1.json")
    args = ap.parse_args(argv)

    episodes = _episodes()
    counts = Counter(e.domain for e in episodes)
    kept = [e for e in episodes if counts[e.domain] >= args.min_per_domain]
    dropped = sorted({e.domain for e in episodes} - {e.domain for e in kept})

    report = run_cross_domain_transfer(kept, threshold=args.threshold)
    payload = report.to_dict()
    payload["n_episodes"] = len(kept)
    payload["domains_evaluated"] = sorted({e.domain for e in kept})
    payload["domains_dropped_below_min"] = dropped
    payload["source"] = "scripts/feed_aromer_episodes.py TEMPLATES (deterministic)"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Cross-domain transfer (leave-one-domain-out, threshold={args.threshold})")
    print(f"  domains:  {report.n_target_domains}  ({', '.join(payload['domains_evaluated'])})")
    print(f"  episodes: {len(kept)}")
    print(f"  overall transfer accuracy: {report.overall_accuracy:.3f} "
          f"({report.n_correct}/{report.n_target_cases})")
    for f in sorted(report.folds, key=lambda x: x.accuracy):
        print(f"    {f.target_domain:16s} {f.accuracy:.3f}  ({f.correct}/{f.n_target})")
    print(f"  artifact: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
