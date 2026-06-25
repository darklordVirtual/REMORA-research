from __future__ import annotations

import json
import re
from pathlib import Path

from scripts import sync_cyber_threat_feeds as sync


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "datasets" / "cyber_evidence_v1" / "live_sources" / "threat_source_registry.yaml"


def _registry_text() -> str:
    return REGISTRY.read_text(encoding="utf-8")


def _source_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^  - id: ([a-z0-9_]+)\n", text))
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        blocks[match.group(1)] = text[start:end]
    return blocks


def test_threat_source_registry_is_metadata_only() -> None:
    text = _registry_text()
    assert re.search(r"(?m)^  metadata_only: true$", text)
    assert re.search(r"(?m)^  exploit_payload_collection: false$", text)
    assert re.search(r"(?m)^  weaponizable_poc_collection: false$", text)
    assert re.search(r"(?m)^  proprietary_scanner_data: false$", text)


def test_threat_source_registry_contains_cutting_edge_sources() -> None:
    source_ids = set(_source_blocks(_registry_text()))
    assert {
        "cisa_kev",
        "nvd_cve",
        "first_epss",
        "osv",
        "github_advisory",
        "mitre_attack",
        "cwe",
        "cisa_ics_advisories",
    } <= source_ids


def test_registry_blocks_payload_fields_for_every_source() -> None:
    for source_id, block in _source_blocks(_registry_text()).items():
        assert "- exploit_payload" in block or source_id in {"cwe"}
        assert "- exploit_steps" in block or source_id in {"cwe"}


def test_cisa_kev_normalization_with_mocked_fetch(monkeypatch) -> None:
    def fake_fetch_json(url: str, *, headers=None, timeout=30):
        assert "known_exploited_vulnerabilities" in url
        return {
            "vulnerabilities": [
                {
                    "cveID": "CVE-2026-0001",
                    "vulnerabilityName": "Example Product RCE",
                    "vendorProject": "Example",
                    "product": "Product",
                    "dateAdded": "2026-06-03",
                    "dueDate": "2026-06-24",
                    "knownRansomwareCampaignUse": "Known",
                    "requiredAction": "Apply updates",
                }
            ]
        }

    monkeypatch.setattr(sync, "fetch_json", fake_fetch_json)
    records = sync.sync_cisa_kev(max_records=10)
    assert records == [
        {
            "feed": "cisa_kev",
            "record_type": "known_exploited_vulnerability",
            "cve_id": "CVE-2026-0001",
            "title": "Example Product RCE",
            "vendor_project": "Example",
            "product": "Product",
            "date_added": "2026-06-03",
            "due_date": "2026-06-24",
            "known_ransomware_use": "Known",
            "required_action": "Apply updates",
            "source_url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            "retrieved_at": records[0]["retrieved_at"],
            "safe_metadata_only": True,
        }
    ]


def test_feed_writer_outputs_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "feed.jsonl"
    sync.write_jsonl(out, [{"feed": "unit", "safe_metadata_only": True}])
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"feed": "unit", "safe_metadata_only": True}]


def test_sync_script_source_does_not_collect_payloads() -> None:
    text = (ROOT / "scripts" / "sync_cyber_threat_feeds.py").read_text(encoding="utf-8").lower()
    assert "metadata only" in text or "metadata-only" in text
    assert "weaponized proof-of-concept" in text
    assert "exploit payload" in text
    assert "exploit-db" not in text
