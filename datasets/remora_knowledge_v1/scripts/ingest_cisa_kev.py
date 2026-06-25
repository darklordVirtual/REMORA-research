#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""Ingest CISA Known Exploited Vulnerabilities (KEV) catalog.

Usage:
  python scripts/ingest_cisa_kev.py --out live_feeds/cisa_kev/kev.normalized.jsonl
  python scripts/ingest_cisa_kev.py --dry-run

No API key required. Public JSON feed from CISA.
Source: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
DEFAULT_OUT = "datasets/remora_knowledge_v1/live_feeds/cisa_kev/kev.normalized.jsonl"


def _fetch() -> dict:
    req = urllib.request.Request(
        CISA_KEV_URL,
        headers={"User-Agent": "remora-knowledge-ingestor/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"CISA KEV feed unreachable: {e}") from e


def _normalize(vuln: dict, retrieved_at: str) -> dict | None:
    try:
        cve_id = vuln["cveID"]
        product = vuln.get("product", "")
        vendor = vuln.get("vendorProject", "")
        vuln_name = vuln.get("vulnerabilityName", "")
        description = vuln.get("shortDescription", "")
        due_date = vuln.get("dueDate", "")
        date_added = vuln.get("dateAdded", "")
        required_action = vuln.get("requiredAction", "")

        return {
            "evidence_id": f"ev_kev_{cve_id.replace('-','_').lower()}",
            "source": "cisa_kev",
            "source_url": CISA_KEV_URL,
            "source_type": "api",
            "title": f"CISA KEV: {cve_id} — {vendor} {product}",
            "content": (
                f"{vuln_name}. {description} "
                f"Required action: {required_action} Due: {due_date}."
            )[:500],
            "domain": "cyber",
            "risk_tags": ["kev", "known_exploited", "critical", "active_exploitation"],
            "authority_score": 0.97,
            "freshness_score": 0.99,
            "coverage_score": 0.92,
            "contradiction_score": 0.0,
            "retrieved_at": retrieved_at,
            "license_note": "public_domain",
            "version": "1.0.0",
            "metadata": {
                "cve_id": cve_id,
                "vendor": vendor,
                "product": product,
                "vulnerability_name": vuln_name,
                "date_added": date_added,
                "due_date": due_date,
                "required_action": required_action,
            },
        }
    except (KeyError, TypeError) as e:
        print(f"  Skipping malformed KEV record: {e}", file=sys.stderr)
        return None


def ingest(*, out: str = DEFAULT_OUT, dry_run: bool = False, max_records: int = 0) -> list[dict]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    print("Fetching CISA KEV catalog…")

    try:
        data = _fetch()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return []

    vulns = data.get("vulnerabilities", [])
    catalog_version = data.get("catalogVersion", "unknown")
    date_released = data.get("dateReleased", "unknown")
    print(f"  Catalog version: {catalog_version}, released: {date_released}")
    print(f"  Total KEV entries: {len(vulns)}")

    if max_records > 0:
        vulns = vulns[:max_records]

    records = []
    for v in vulns:
        rec = _normalize(v, retrieved_at)
        if rec:
            records.append(rec)

    if dry_run:
        print(f"[DRY RUN] Would write {len(records)} records to {out}")
        for r in records[:5]:
            print(f"  {r['evidence_id']}: {r['title'][:60]}")
        return records

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"  Written {len(records)} records → {out}")
    return records


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest CISA Known Exploited Vulnerabilities catalog")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-records", type=int, default=0, help="0 = all records")
    args = p.parse_args()
    ingest(out=args.out, dry_run=args.dry_run, max_records=args.max_records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
