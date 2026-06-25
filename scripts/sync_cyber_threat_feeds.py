#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Synchronize public cyber threat metadata feeds for REMORA.

This script ingests metadata only. It deliberately does not download exploit
payloads, weaponized proof-of-concept code, or proprietary scanner output.
In other words: no exploit payload or exploit steps are collected.

Supported first-pass sources:
- CISA KEV JSON feed
- NVD CVE API 2.0
- FIRST EPSS API
- GitHub Advisory Database REST API

The output is normalized JSONL suitable for enrichment and later conversion to
REMORA cyber evidence objects.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "datasets" / "cyber_evidence_v1" / "live_feeds"

UA = "REMORA-CyberEvidence/1.0 metadata-only"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    req_headers = {"User-Agent": UA, "Accept": "application/json"}
    req_headers.update(headers or {})
    with urlopen(Request(url, headers=req_headers), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def sync_cisa_kev(*, max_records: int) -> list[dict[str, Any]]:
    url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    data = fetch_json(url)
    vulns = data.get("vulnerabilities", [])
    records = []
    for row in vulns[:max_records]:
        cve = row.get("cveID")
        if not cve:
            continue
        records.append({
            "feed": "cisa_kev",
            "record_type": "known_exploited_vulnerability",
            "cve_id": cve,
            "title": row.get("vulnerabilityName", ""),
            "vendor_project": row.get("vendorProject", ""),
            "product": row.get("product", ""),
            "date_added": row.get("dateAdded", ""),
            "due_date": row.get("dueDate", ""),
            "known_ransomware_use": row.get("knownRansomwareCampaignUse", ""),
            "required_action": row.get("requiredAction", ""),
            "source_url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            "retrieved_at": utc_now(),
            "safe_metadata_only": True,
        })
    return records


def sync_nvd_recent(*, max_records: int, days: int) -> list[dict[str, Any]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    params = {
        "pubStartDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "pubEndDate": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "resultsPerPage": str(min(max_records, 2000)),
    }
    url = "https://services.nvd.nist.gov/rest/json/cves/2.0?" + urlencode(params)
    headers = {}
    api_key = os.getenv("NVD_API_KEY") or os.getenv("NVDAPIKEY")
    if api_key:
        headers["apiKey"] = api_key
    data = fetch_json(url, headers=headers)
    records = []
    for item in data.get("vulnerabilities", [])[:max_records]:
        cve = item.get("cve", {})
        cve_id = cve.get("id")
        descriptions = cve.get("descriptions", [])
        description = next((d.get("value", "") for d in descriptions if d.get("lang") == "en"), "")
        metrics = cve.get("metrics", {})
        cvss = _extract_cvss(metrics)
        weaknesses = [
            desc.get("value")
            for w in cve.get("weaknesses", [])
            for desc in w.get("description", [])
            if desc.get("lang") == "en" and desc.get("value")
        ]
        if not cve_id:
            continue
        records.append({
            "feed": "nvd_cve",
            "record_type": "cve_metadata",
            "cve_id": cve_id,
            "published": cve.get("published", ""),
            "last_modified": cve.get("lastModified", ""),
            "description": description[:1200],
            "cvss_score": cvss.get("score"),
            "cvss_severity": cvss.get("severity"),
            "cwe_ids": sorted(set(weaknesses)),
            "source_url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            "retrieved_at": utc_now(),
            "safe_metadata_only": True,
        })
    return records


def sync_epss(*, max_records: int, epss_gt: float) -> list[dict[str, Any]]:
    params = {"epss-gt": f"{epss_gt:.3f}", "limit": str(max_records)}
    url = "https://api.first.org/data/v1/epss?" + urlencode(params)
    data = fetch_json(url)
    records = []
    for row in data.get("data", [])[:max_records]:
        records.append({
            "feed": "first_epss",
            "record_type": "exploit_probability",
            "cve_id": row.get("cve", ""),
            "epss": _float_or_none(row.get("epss")),
            "percentile": _float_or_none(row.get("percentile")),
            "date": row.get("date", ""),
            "source_url": "https://www.first.org/epss/",
            "retrieved_at": utc_now(),
            "safe_metadata_only": True,
        })
    return [r for r in records if r["cve_id"]]


def sync_github_advisories(*, max_records: int) -> list[dict[str, Any]]:
    params = {"per_page": str(min(max_records, 100)), "sort": "updated", "direction": "desc"}
    url = "https://api.github.com/advisories?" + urlencode(params)
    headers = {}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = fetch_json(url, headers=headers)
    records = []
    for row in data[:max_records]:
        vulnerabilities = row.get("vulnerabilities") or []
        records.append({
            "feed": "github_advisory",
            "record_type": "package_advisory",
            "ghsa_id": row.get("ghsa_id", ""),
            "cve_id": row.get("cve_id", ""),
            "severity": row.get("severity", ""),
            "summary": row.get("summary", ""),
            "cwe_ids": row.get("cwes", []),
            "ecosystems": sorted({v.get("package", {}).get("ecosystem", "") for v in vulnerabilities if v.get("package")}),
            "packages": sorted({v.get("package", {}).get("name", "") for v in vulnerabilities if v.get("package")}),
            "published_at": row.get("published_at", ""),
            "updated_at": row.get("updated_at", ""),
            "source_url": row.get("html_url", "https://github.com/advisories"),
            "retrieved_at": utc_now(),
            "safe_metadata_only": True,
        })
    return records


def _extract_cvss(metrics: dict[str, Any]) -> dict[str, Any]:
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        rows = metrics.get(key) or []
        if rows:
            metric = rows[0].get("cvssData", {})
            return {
                "score": metric.get("baseScore"),
                "severity": rows[0].get("baseSeverity") or metric.get("baseSeverity"),
            }
    return {"score": None, "severity": None}


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync public cyber threat metadata feeds")
    parser.add_argument("--source", choices=["cisa_kev", "nvd_recent", "epss", "github_advisory", "all"], default="all")
    parser.add_argument("--max-records", type=int, default=50)
    parser.add_argument("--days", type=int, default=7, help="NVD recent lookback window")
    parser.add_argument("--epss-gt", type=float, default=0.90)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing files")
    args = parser.parse_args()

    jobs = {
        "cisa_kev": lambda: sync_cisa_kev(max_records=args.max_records),
        "nvd_recent": lambda: sync_nvd_recent(max_records=args.max_records, days=args.days),
        "epss": lambda: sync_epss(max_records=args.max_records, epss_gt=args.epss_gt),
        "github_advisory": lambda: sync_github_advisories(max_records=args.max_records),
    }
    selected = list(jobs) if args.source == "all" else [args.source]
    summary = {}
    for source in selected:
        try:
            records = jobs[source]()
        except Exception as exc:
            print(f"ERROR syncing {source}: {exc}", file=sys.stderr)
            records = []
        summary[source] = len(records)
        if not args.dry_run:
            write_jsonl(args.out_dir / source / f"{source}.normalized.jsonl", records)

    print(json.dumps({"retrieved_at": utc_now(), "summary": summary, "dry_run": args.dry_run}, indent=2))


if __name__ == "__main__":
    main()
