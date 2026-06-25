#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Build a vector-store payload from cyber_evidence_v1.

The output is deterministic JSONL with separate text and metadata fields.
It is suitable for Cloudflare Vectorize, Qdrant, Chroma, pgvector, or another
vector backend. The script does not call external APIs and does not compute
embeddings by itself.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "datasets" / "cyber_evidence_v1" / "evidence" / "cyber_evidence_objects.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "cyber_evidence_v1" / "vector_payload.jsonl"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            records.append(json.loads(line))
    return records


def build_text(record: dict[str, Any]) -> str:
    fields = [
        record.get("title", ""),
        record.get("content", ""),
        " ".join(record.get("risk_tags", [])),
        " ".join(record.get("cve_ids", [])),
        " ".join(record.get("cwe_ids", [])),
        " ".join(record.get("attack_ids", [])),
        " ".join(record.get("packages", [])),
        record.get("remediation", ""),
    ]
    return " ".join(str(field) for field in fields if field).strip()


def vector_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["evidence_id"],
        "text": build_text(record),
        "metadata": {
            "source": record.get("source"),
            "source_url": record.get("source_url"),
            "domain": record.get("domain"),
            "risk_tags": record.get("risk_tags", []),
            "cve_ids": record.get("cve_ids", []),
            "cwe_ids": record.get("cwe_ids", []),
            "attack_ids": record.get("attack_ids", []),
            "packages": record.get("packages", []),
            "kev": record.get("kev", False),
            "epss_score": record.get("epss_score"),
            "cvss_score": record.get("cvss_score"),
            "license_note": record.get("license_note", ""),
        },
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cyber evidence vector payload")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = load_jsonl(args.input)
    payload = [vector_record(row) for row in rows]
    payload.sort(key=lambda row: row["id"])
    write_jsonl(args.out, payload)
    print(f"Wrote {len(payload)} vector records to {args.out}")


if __name__ == "__main__":
    main()
