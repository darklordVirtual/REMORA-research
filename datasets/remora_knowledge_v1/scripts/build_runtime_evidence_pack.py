#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Build runtime evidence pack by merging base pack and normalized live feeds.

This script is intended for scheduled daily ingestion workflows:
1. Run feed ingestors (NVD/EPSS/KEV/MITRE) into datasets/.../live_feeds/*/*.normalized.jsonl
2. Run this builder to produce runtime_evidence_objects.jsonl
3. Point REMORA runtime to the built file via REMORA_RUNTIME_EVIDENCE_JSONL
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_BASE = Path("datasets/remora_knowledge_v1/evidence_packs/evidence_objects.jsonl")
DEFAULT_LIVE_FEEDS = Path("datasets/remora_knowledge_v1/live_feeds")
DEFAULT_OUT = Path("datasets/remora_knowledge_v1/evidence_packs/runtime_evidence_objects.jsonl")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _all_normalized_live_feed_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.normalized.jsonl"))


def _dedupe_by_evidence_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    fallback_counter = 0
    for row in rows:
        evidence_id = row.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            fallback_counter += 1
            evidence_id = f"missing_evidence_id_{fallback_counter}"
        merged[evidence_id] = row
    return sorted(merged.values(), key=lambda r: str(r.get("evidence_id", "")))


def build_runtime_pack(*, base_path: Path, live_feeds_root: Path, out_path: Path) -> dict[str, int]:
    base_rows = _read_jsonl(base_path)

    feed_files = _all_normalized_live_feed_files(live_feeds_root)
    feed_rows: list[dict[str, Any]] = []
    for file_path in feed_files:
        feed_rows.extend(_read_jsonl(file_path))

    merged_rows = _dedupe_by_evidence_id([*base_rows, *feed_rows])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in merged_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    return {
        "base_rows": len(base_rows),
        "feed_files": len(feed_files),
        "feed_rows": len(feed_rows),
        "merged_rows": len(merged_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build runtime evidence JSONL from base + live feeds")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--live-feeds", type=Path, default=DEFAULT_LIVE_FEEDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    stats = build_runtime_pack(
        base_path=args.base,
        live_feeds_root=args.live_feeds,
        out_path=args.out,
    )
    print(json.dumps({"status": "ok", **stats, "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
