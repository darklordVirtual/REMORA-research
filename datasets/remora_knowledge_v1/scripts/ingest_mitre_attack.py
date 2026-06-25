#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""Ingest MITRE ATT&CK techniques from the public STIX bundle.

Usage:
  python scripts/ingest_mitre_attack.py --domain enterprise --out live_feeds/mitre_attack/attack_techniques.normalized.jsonl
  python scripts/ingest_mitre_attack.py --domain ics --out live_feeds/mitre_attack/ics_techniques.normalized.jsonl
  python scripts/ingest_mitre_attack.py --domain enterprise --dry-run

No API key required. Uses MITRE ATT&CK public STIX JSON bundles.
Source: https://github.com/mitre-attack/attack-stix-data
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STIX_URLS = {
    "enterprise": "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack.json",
    "ics": "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/ics-attack/ics-attack.json",
    "mobile": "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/mobile-attack/mobile-attack.json",
}
DEFAULT_OUT = "datasets/remora_knowledge_v1/live_feeds/mitre_attack/attack_techniques.normalized.jsonl"

# High-relevance tactic tags for REMORA
_RELEVANT_TACTICS = {
    "initial-access", "execution", "persistence", "privilege-escalation",
    "defense-evasion", "credential-access", "lateral-movement", "exfiltration",
    "impact", "inhibit-response-function", "impair-process-control",
}


def _fetch(domain: str) -> dict:
    url = STIX_URLS.get(domain)
    if not url:
        raise ValueError(f"Unknown domain: {domain!r}. Choose from: {list(STIX_URLS)}")
    print(f"  Downloading ATT&CK STIX bundle ({domain})… this may take a moment.")
    req = urllib.request.Request(url, headers={"User-Agent": "remora-knowledge-ingestor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"ATT&CK STIX bundle unreachable: {e}") from e


def _normalize(obj: dict, domain: str, retrieved_at: str) -> dict | None:
    try:
        if obj.get("type") != "attack-pattern":
            return None
        if obj.get("x_mitre_deprecated") or obj.get("revoked"):
            return None

        technique_id = next(
            (ref["external_id"] for ref in obj.get("external_references", [])
             if ref.get("source_name") in ("mitre-attack", "mitre-ics-attack")),
            None
        )
        if not technique_id:
            return None

        name = obj.get("name", "")
        description = obj.get("description", "")[:400]
        tactics = [p["phase_name"] for p in obj.get("kill_chain_phases", [])]
        platforms = obj.get("x_mitre_platforms", [])

        risk_tags = ["mitre_attack", domain]
        for tactic in tactics:
            if tactic in _RELEVANT_TACTICS:
                risk_tags.append(tactic.replace("-", "_"))
        if "execution" in tactics or "impact" in tactics:
            risk_tags.append("high_risk_tactic")

        technique_url = next(
            (ref["url"] for ref in obj.get("external_references", [])
             if ref.get("source_name") in ("mitre-attack", "mitre-ics-attack") and "url" in ref),
            f"https://attack.mitre.org/techniques/{technique_id}/"
        )

        return {
            "evidence_id": f"ev_attack_{technique_id.replace('.', '_').lower()}",
            "source": "mitre_attack",
            "source_url": technique_url,
            "source_type": "static_rag",
            "title": f"MITRE ATT&CK {technique_id}: {name}",
            "content": description,
            "domain": "cyber",
            "risk_tags": list(set(risk_tags)),
            "authority_score": 0.93,
            "freshness_score": 0.85,
            "coverage_score": 0.88,
            "contradiction_score": 0.0,
            "retrieved_at": retrieved_at,
            "license_note": "cc_by_4.0",
            "version": "1.0.0",
            "metadata": {
                "technique_id": technique_id,
                "tactics": tactics,
                "platforms": platforms,
                "domain": domain,
            },
        }
    except (KeyError, TypeError, StopIteration):
        return None


def ingest(
    *,
    domain: str = "enterprise",
    out: str = DEFAULT_OUT,
    dry_run: bool = False,
    max_records: int = 0,
    relevant_only: bool = True,
) -> list[dict]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    print(f"Fetching MITRE ATT&CK ({domain})…")

    try:
        bundle = _fetch(domain)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return []

    objects = bundle.get("objects", [])
    print(f"  Bundle contains {len(objects)} STIX objects")

    records = []
    for obj in objects:
        rec = _normalize(obj, domain, retrieved_at)
        if rec is None:
            continue
        if relevant_only:
            tactics = rec.get("metadata", {}).get("tactics", [])
            if not any(t in _RELEVANT_TACTICS for t in tactics):
                continue
        records.append(rec)
        if max_records > 0 and len(records) >= max_records:
            break

    print(f"  Normalized {len(records)} techniques")

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
    p = argparse.ArgumentParser(description="Ingest MITRE ATT&CK techniques")
    p.add_argument("--domain", choices=["enterprise", "ics", "mobile"], default="enterprise")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-records", type=int, default=0, help="0 = all relevant techniques")
    p.add_argument("--all-tactics", action="store_true", help="Include all tactics, not just high-relevance")
    args = p.parse_args()
    ingest(domain=args.domain, out=args.out, dry_run=args.dry_run,
           max_records=args.max_records, relevant_only=not args.all_tactics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
