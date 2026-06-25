#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""Ingest EPSS (Exploit Prediction Scoring System) data into REMORA evidence JSONL.

Usage:
  python scripts/ingest_epss.py --cve CVE-2021-44228 --out live_feeds/epss/epss.normalized.jsonl
  python scripts/ingest_epss.py --epss-gt 0.95 --max-records 50 --out live_feeds/epss/epss.normalized.jsonl
  python scripts/ingest_epss.py --date 2024-01-15 --epss-gt 0.90 --dry-run

EPSS scores are probability estimates (0-1) that a CVE will be exploited in the wild within 30 days.
No API key required. Source: FIRST EPSS API (https://api.first.org/data/v1/epss).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EPSS_API_BASE = "https://api.first.org/data/v1/epss"
DEFAULT_OUT = "datasets/remora_knowledge_v1/live_feeds/epss/epss.normalized.jsonl"


def _fetch(params: dict) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{EPSS_API_BASE}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "remora-knowledge-ingestor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"EPSS API unreachable: {e}") from e


def _normalize(item: dict, retrieved_at: str) -> dict | None:
    try:
        cve_id = item["cve"]
        epss_score = float(item["epss"])
        percentile = float(item.get("percentile", 0.0)) * 100

        risk_tags = ["epss", "exploit_probability"]
        if epss_score >= 0.95:
            risk_tags.append("critical_epss")
        elif epss_score >= 0.7:
            risk_tags.append("high_epss")
        elif epss_score >= 0.4:
            risk_tags.append("medium_epss")

        return {
            "evidence_id": f"ev_epss_{cve_id.replace('-','_').lower()}",
            "source": "epss",
            "source_url": f"https://api.first.org/data/v1/epss?cve={cve_id}",
            "source_type": "api",
            "title": f"EPSS: {cve_id} exploit probability={epss_score:.4f}",
            "content": (
                f"EPSS score {epss_score:.4f} ({percentile:.1f}th percentile). "
                f"Estimated probability of exploitation in the wild within 30 days."
            ),
            "domain": "cyber",
            "risk_tags": risk_tags,
            "authority_score": 0.88,
            "freshness_score": 0.95,
            "coverage_score": 0.80,
            "contradiction_score": 0.0,
            "retrieved_at": retrieved_at,
            "license_note": "cc0",
            "version": "1.0.0",
            "metadata": {
                "cve_id": cve_id,
                "epss_score": epss_score,
                "percentile": percentile,
                "date": item.get("date"),
            },
        }
    except (KeyError, ValueError, TypeError) as e:
        print(f"  Skipping malformed EPSS record: {e}", file=sys.stderr)
        return None


def ingest(
    *,
    cve_id: str | None = None,
    epss_gt: float | None = None,
    date: str | None = None,
    max_records: int = 100,
    out: str = DEFAULT_OUT,
    dry_run: bool = False,
) -> list[dict]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    params: dict = {"limit": min(max_records, 10000)}

    if cve_id:
        params["cve"] = cve_id
    if epss_gt is not None:
        params["epss-gt"] = epss_gt
    if date:
        params["date"] = date

    print(f"Fetching EPSS scores (cve={cve_id!r}, epss_gt={epss_gt!r}, date={date!r})…")

    try:
        data = _fetch(params)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return []

    items = data.get("data", [])
    print(f"  Received {len(items)} EPSS records (total: {data.get('total', '?')})")

    records = []
    for item in items[:max_records]:
        rec = _normalize(item, retrieved_at)
        if rec:
            records.append(rec)

    if dry_run:
        print(f"[DRY RUN] Would write {len(records)} records to {out}")
        for r in records[:3]:
            print(f"  {r['evidence_id']}: {r['metadata']['epss_score']:.4f}")
        return records

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"  Written {len(records)} records → {out}")
    return records


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest EPSS exploit probability scores")
    p.add_argument("--cve", help="Specific CVE ID")
    p.add_argument("--epss-gt", type=float, help="Minimum EPSS score (e.g. 0.95)")
    p.add_argument("--date", help="Score date YYYY-MM-DD (default: current)")
    p.add_argument("--max-records", type=int, default=100)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not any([args.cve, args.epss_gt]):
        p.error("Provide at least one of --cve or --epss-gt")

    ingest(cve_id=args.cve, epss_gt=args.epss_gt, date=args.date,
           max_records=args.max_records, out=args.out, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
