from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "datasets" / "cyber_evidence_v1"


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def test_cyber_dataset_validator_passes() -> None:
    script = DATASET / "scripts" / "validate_cyber_evidence.py"
    result = subprocess.run(
        [sys.executable, str(script), "--summary"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "OK: cyber_evidence_v1 is valid" in result.stdout


def test_cyber_dataset_has_expected_public_shape() -> None:
    evidence = _load_jsonl(DATASET / "evidence" / "cyber_evidence_objects.jsonl")
    cases = _load_jsonl(DATASET / "cases" / "security_cases.jsonl")
    expected = _load_jsonl(DATASET / "expected_decisions" / "cyber_expected_decisions.jsonl")
    assert len(evidence) >= 15
    assert len(cases) >= 10
    assert len(expected) == len(cases)
    assert {row["expected_verdict"] for row in expected} >= {
        "REPORT_READY",
        "NEEDS_REVIEW",
        "ESCALATE",
    }


def test_cyber_dataset_keeps_proprietary_extension_boundary() -> None:
    manifest = (DATASET / "manifest.yaml").read_text(encoding="utf-8")
    assert "contains_proprietary_scanner_data: false" in manifest
    assert "contains_private_findings: false" in manifest
    evidence_text = (DATASET / "evidence" / "cyber_evidence_objects.jsonl").read_text(encoding="utf-8").lower()
    assert "gostar_private" not in evidence_text
    assert "private_customer" not in evidence_text


def test_vector_payload_builder_outputs_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "vector_payload.jsonl"
    script = ROOT / "scripts" / "build_cyber_vector_payload.py"
    result = subprocess.run(
        [sys.executable, str(script), "--out", str(out)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    rows = _load_jsonl(out)
    assert rows
    assert {"id", "text", "metadata"} <= rows[0].keys()
    assert rows[0]["metadata"]["source_url"].startswith("https://")
