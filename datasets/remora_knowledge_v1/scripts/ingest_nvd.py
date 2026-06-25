#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""Ingest CVE data from NVD CVE API 2.0 and normalize to REMORA evidence JSONL.

Usage:
  python scripts/ingest_nvd.py --keyword kubernetes --max-records 50 --out live_feeds/nvd/cves.normalized.jsonl
  python scripts/ingest_nvd.py --cve CVE-2021-44228 --out live_feeds/nvd/cves.normalized.jsonl
  python scripts/ingest_nvd.py --kev --max-records 100 --out live_feeds/nvd/cves.normalized.jsonl
  python scripts/ingest_nvd.py --keyword log4j --dry-run

No API key required for low-volume requests. NVD enforces rate limiting: 5 req/30s without key,
50 req/30s with NVDAPIKEY env var.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
DEFAULT_OUT = "datasets/remora_knowledge_v1/live_feeds/nvd/cves.normalized.jsonl"
CACHE_DIR = Path("datasets/remora_knowledge_v1/.cache/nvd")


def _api_key() -> str | None:
    return os.environ.get("NVDAPIKEY")


def _fetch(params: dict, *, retries: int = 3) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{NVD_API_BASE}?{query}"
    headers = {"User-Agent": "remora-knowledge-ingestor/1.0"}
    api_key = _api_key()
    if api_key:
        headers["apiKey"] = api_key

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 35 if not api_key else 7
                print(f"  Rate limited (429). Waiting {wait}s…", file=sys.stderr)
                time.sleep(wait)
            elif e.code in (500, 503) and attempt < retries - 1:
                time.sleep(5)
            else:
                raise
        except (urllib.error.URLError, OSError) as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                raise RuntimeError(f"NVD API unreachable: {e}") from e
    raise RuntimeError(f"NVD fetch failed after {retries} attempts")


def _normalize(cve_item: dict, retrieved_at: str) -> dict | None:
    try:
        cve_id = cve_item["cve"]["id"]
        descriptions = cve_item["cve"].get("descriptions", [])
        desc_en = next((d["value"] for d in descriptions if d.get("lang") == "en"), "No description")

        metrics = cve_item["cve"].get("metrics", {})
        cvss_score = None
        cvss_severity = None
        for version_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV40", "cvssMetricV2"):
            if version_key in metrics and metrics[version_key]:
                m = metrics[version_key][0].get("cvssData", {})
                cvss_score = m.get("baseScore")
                cvss_severity = m.get("baseSeverity") or m.get("vectorString", "").split("/")[0]
                break

        risk_tags = []
        if cvss_score:
            if cvss_score >= 9.0:
                risk_tags.append("critical")
            elif cvss_score >= 7.0:
                risk_tags.append("high")
            elif cvss_score >= 4.0:
                risk_tags.append("medium")
            else:
                risk_tags.append("low")
        risk_tags.append("cve")
        if cve_item["cve"].get("cisaExploitAdd"):
            risk_tags.extend(["kev", "known_exploited"])

        authority_score = 0.97 if cvss_score and cvss_score >= 9.0 else 0.90
        freshness_score = 0.97 if cve_item["cve"].get("cisaExploitAdd") else 0.80
        published = cve_item["cve"].get("published", "")

        return {
            "evidence_id": f"ev_nvd_{cve_id.replace('-','_').lower()}",
            "source": "nvd",
            "source_url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            "source_type": "api",
            "title": f"NVD: {cve_id}",
            "content": desc_en[:500],
            "domain": "cyber",
            "risk_tags": risk_tags,
            "authority_score": authority_score,
            "freshness_score": freshness_score,
            "coverage_score": 0.90,
            "contradiction_score": 0.0,
            "retrieved_at": retrieved_at,
            "license_note": "public_domain",
            "version": "1.0.0",
            "metadata": {
                "cve_id": cve_id,
                "cvss_score": cvss_score,
                "cvss_severity": cvss_severity,
                "published": published,
                "kev": bool(cve_item["cve"].get("cisaExploitAdd")),
            },
        }
    except (KeyError, TypeError) as e:
        print(f"  Skipping malformed CVE record: {e}", file=sys.stderr)
        return None


def ingest(
    *,
    keyword: str | None = None,
    cve_id: str | None = None,
    kev_only: bool = False,
    max_records: int = 100,
    out: str = DEFAULT_OUT,
    dry_run: bool = False,
) -> list[dict]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    params: dict = {"resultsPerPage": min(max_records, 2000), "startIndex": 0}

    if cve_id:
        params["cveId"] = cve_id
    elif keyword:
        params["keywordSearch"] = keyword
    if kev_only:
        params["hasKev"] = ""

    print(f"Fetching NVD CVEs (keyword={keyword!r}, cve={cve_id!r}, kev={kev_only})…")

    try:
        data = _fetch(params)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return []

    vulnerabilities = data.get("vulnerabilities", [])
    print(f"  Received {len(vulnerabilities)} CVEs (total: {data.get('totalResults', '?')})")

    records = []
    for item in vulnerabilities[:max_records]:
        rec = _normalize(item, retrieved_at)
        if rec:
            records.append(rec)

    if dry_run:
        print(f"[DRY RUN] Would write {len(records)} records to {out}")
        for r in records[:3]:
            print(f"  {r['evidence_id']}: {r['title']} {r.get('metadata',{}).get('cvss_score','')}")
        return records

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"  Written {len(records)} records → {out}")
    return records


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest NVD CVE data into REMORA evidence JSONL")
    p.add_argument("--keyword", help="Keyword search (e.g. 'kubernetes')")
    p.add_argument("--cve", help="Specific CVE ID (e.g. CVE-2021-44228)")
    p.add_argument("--kev", action="store_true", help="Only KEV (Known Exploited Vulnerabilities)")
    p.add_argument("--max-records", type=int, default=100)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--dry-run", action="store_true", help="Print preview without writing")
    args = p.parse_args()

    if not any([args.keyword, args.cve, args.kev]):
        p.error("Provide at least one of --keyword, --cve, or --kev")

    ingest(keyword=args.keyword, cve_id=args.cve, kev_only=args.kev,
           max_records=args.max_records, out=args.out, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
