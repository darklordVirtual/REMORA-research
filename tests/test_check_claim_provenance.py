from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_claim_provenance.py"
    )
    spec = importlib.util.spec_from_file_location("check_claim_provenance", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ccp = _load_module()

SYNTHETIC_REGISTER = """\
---
# comment line
schema_version: "1"
generated: "2026-07-02"

claims:

  - id: CLAIM-101
    title: "Example claim"
    statement: >
      Folded block scalar
      spanning two lines.
    evidence_level: internal_benchmark
    artifact:
      - "results/example.json"
      - "artifacts/example_locked.json"
    n: 700
    metrics:
      far_pct: 0.0
      accuracy_pct: 88.0
    caveat: "Simulator-scoped."
    reproduce: >
      python experiments/example.py

  - id: CLAIM-102
    title: "Second claim"
    evidence_level: regression_tested
    artifact:
      - "results/other.json"
    n: null
    caveat: "Internal corpus."
"""


# ---------------------------------------------------------------------------
# Register parser
# ---------------------------------------------------------------------------

def test_parse_register_synthetic() -> None:
    claims = ccp.parse_register(SYNTHETIC_REGISTER)
    assert len(claims) == 2
    c1, c2 = claims
    assert c1["id"] == "CLAIM-101"
    assert c1["evidence_level"] == "internal_benchmark"
    assert c1["artifact"] == ["results/example.json", "artifacts/example_locked.json"]
    assert c1["n"] == 700
    assert c1["metrics"] == {"far_pct": 0.0, "accuracy_pct": 88.0}
    assert "spanning two lines" in c1["statement"]
    assert c2["n"] is None
    assert c2["evidence_level"] == "regression_tested"


def test_parse_register_real_file() -> None:
    text = ccp.REGISTER_PATH.read_text(encoding="utf-8")
    claims = ccp.parse_register(text)
    ids = [c["id"] for c in claims]
    assert len(claims) == 11
    assert ids[0] == "CLAIM-001" and ids[-1] == "CLAIM-011"
    by_id = {c["id"]: c for c in claims}
    assert by_id["CLAIM-001"]["artifact"] == [
        "results/toolcall_benchmark_v2_results.json",
        "results/toolcall_blind_v3_results.json",
        "results/toolcall_m1_clean_signal.json",
    ]
    assert by_id["CLAIM-002"]["metrics"]["fbr_pct"] == 100.0
    assert by_id["CLAIM-004"]["metrics"]["accuracy_pct"] == 88.0
    assert by_id["CLAIM-006"]["n"] is None
    for claim in claims:
        assert claim["evidence_level"] in ccp.EVIDENCE_LEVELS


# ---------------------------------------------------------------------------
# Register integrity check
# ---------------------------------------------------------------------------

def test_check_register_flags_missing_field_and_bad_level() -> None:
    claims = [
        {"id": "CLAIM-201", "title": "x", "evidence_level": "vibes",
         "artifact": ["a.json"], "caveat": "c"},
        {"id": "CLAIM-202", "title": "y", "evidence_level": "theoretical",
         "artifact": [], "caveat": "c"},
    ]
    errors = ccp.check_register(claims)
    ids = [eid for eid, _ in errors]
    assert "register-bad-level:CLAIM-201" in ids
    assert "register-missing-field:CLAIM-202:artifact" in ids


# ---------------------------------------------------------------------------
# Artifact existence check
# ---------------------------------------------------------------------------

def test_check_artifacts_missing_and_present(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "present.json").write_text("{}", encoding="utf-8")
    claims = [
        {"id": "CLAIM-301", "artifact": ["results/present.json", "results/gone.json"]},
    ]
    errors = ccp.check_artifacts(claims, root=tmp_path)
    assert errors == [
        (
            "artifact-missing:CLAIM-301:results/gone.json",
            "CLAIM-301: cited artifact does not exist on disk: results/gone.json",
        )
    ]


# ---------------------------------------------------------------------------
# Manifest verification
# ---------------------------------------------------------------------------

def _manifest_row(rel: str, sha: str, size: int) -> str:
    return f"| `{rel}` | `{sha}` | {size} | 2026-07-02T00:00:00 | test |"


def test_check_manifest_lf_match_passes(tmp_path: Path) -> None:
    content = b'{"a": 1}\n{"b": 2}\n'
    (tmp_path / "r.json").write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    notes: list[str] = []
    errors = ccp.check_manifest(_manifest_row("r.json", sha, len(content)), notes, root=tmp_path)
    assert errors == []
    assert notes == []


def test_check_manifest_crlf_working_tree_passes_with_note(tmp_path: Path) -> None:
    lf = b'{"a": 1}\n{"b": 2}\n'
    (tmp_path / "r.json").write_bytes(lf.replace(b"\n", b"\r\n"))
    sha = hashlib.sha256(lf).hexdigest()
    notes: list[str] = []
    errors = ccp.check_manifest(_manifest_row("r.json", sha, len(lf)), notes, root=tmp_path)
    assert errors == []
    assert notes and "CRLF" in notes[0]


def test_check_manifest_content_mismatch_fails(tmp_path: Path) -> None:
    (tmp_path / "r.json").write_bytes(b'{"tampered": true}\n')
    sha = hashlib.sha256(b"original content\n").hexdigest()
    notes: list[str] = []
    errors = ccp.check_manifest(_manifest_row("r.json", sha, 17), notes, root=tmp_path)
    assert [eid for eid, _ in errors] == ["manifest-hash-mismatch:r.json"]


def test_check_manifest_noncanonical_casing_fails(tmp_path: Path) -> None:
    content = b"data\n"
    (tmp_path / "r.json").write_bytes(content)
    sha = hashlib.sha256(content).hexdigest().upper()
    notes: list[str] = []
    errors = ccp.check_manifest(_manifest_row("r.json", sha, len(content)), notes, root=tmp_path)
    assert [eid for eid, _ in errors] == ["manifest-hash-casing:r.json"]


def test_check_manifest_missing_file_fails(tmp_path: Path) -> None:
    sha = "0" * 64
    notes: list[str] = []
    errors = ccp.check_manifest(_manifest_row("gone.json", sha, 1), notes, root=tmp_path)
    assert [eid for eid, _ in errors] == ["manifest-file-missing:gone.json"]


# ---------------------------------------------------------------------------
# Doc anchors
# ---------------------------------------------------------------------------

CLAIMS_BY_ID = {
    "CLAIM-101": {
        "id": "CLAIM-101",
        "n": 208,
        "metrics": {"far_pct": 0.0, "ci_high_pct": 1.81},
    }
}


def test_anchor_matching_values_pass(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "<!-- claim:CLAIM-101 far_pct ci_high_pct n -->\n"
        "Result on 208 scenarios: FAR = 0.0%, Wilson 95% CI [0.00%, 1.81%].\n",
        encoding="utf-8",
    )
    errors = ccp.check_doc_anchors(doc, doc.read_text(encoding="utf-8"), CLAIMS_BY_ID)
    assert errors == []


def test_anchor_value_drift_fails(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "<!-- claim:CLAIM-101 ci_high_pct -->\n"
        "Wilson 95% CI [0.00%, 2.50%].\n",
        encoding="utf-8",
    )
    errors = ccp.check_doc_anchors(doc, doc.read_text(encoding="utf-8"), CLAIMS_BY_ID)
    assert [eid for eid, _ in errors] == ["anchor-value-drift:doc.md:CLAIM-101:ci_high_pct"]


def test_anchor_unknown_metric_and_claim_fail(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "<!-- claim:CLAIM-101 nonexistent_metric -->\nSome text 1.0.\n"
        "<!-- claim:CLAIM-999 far_pct -->\nOther text.\n",
        encoding="utf-8",
    )
    errors = ccp.check_doc_anchors(doc, doc.read_text(encoding="utf-8"), CLAIMS_BY_ID)
    ids = [eid for eid, _ in errors]
    assert "anchor-unknown-metric:doc.md:CLAIM-101:nonexistent_metric" in ids
    assert "anchor-unknown-claim:doc.md:CLAIM-999" in ids


def test_anchor_skips_blank_line_before_paragraph(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "<!-- claim:CLAIM-101 far_pct -->\n\nFAR = 0.0% on the benchmark.\n",
        encoding="utf-8",
    )
    errors = ccp.check_doc_anchors(doc, doc.read_text(encoding="utf-8"), CLAIMS_BY_ID)
    assert errors == []


# ---------------------------------------------------------------------------
# Evidence-level citations
# ---------------------------------------------------------------------------

def test_evidence_citation_drift_fails(tmp_path: Path) -> None:
    claims = {"CLAIM-101": {"id": "CLAIM-101", "evidence_level": "internal_benchmark"}}
    doc = tmp_path / "doc.md"
    doc.write_text(
        "| FAR=0% benchmark (CLAIM-101) | externally_benchmarked | notes |\n",
        encoding="utf-8",
    )
    errors = ccp.check_evidence_citations(doc, doc.read_text(encoding="utf-8"), claims)
    assert [eid for eid, _ in errors] == ["evidence-level-drift:doc.md:1:CLAIM-101"]


def test_evidence_citation_match_passes(tmp_path: Path) -> None:
    claims = {"CLAIM-101": {"id": "CLAIM-101", "evidence_level": "internal_benchmark"}}
    doc = tmp_path / "doc.md"
    doc.write_text(
        "CLAIM-101 is evidenced at internal_benchmark level.\n", encoding="utf-8"
    )
    errors = ccp.check_evidence_citations(doc, doc.read_text(encoding="utf-8"), claims)
    assert errors == []


# ---------------------------------------------------------------------------
# End-to-end against the real repository
# ---------------------------------------------------------------------------

def test_gate_passes_on_real_repo() -> None:
    assert ccp.run() == 0


def test_real_readme_anchors_are_wired() -> None:
    readme = (ccp.ROOT / "README.md").read_text(encoding="utf-8")
    anchored_claims = {m.group(1) for m in ccp.ANCHOR_RE.finditer(readme)}
    assert {"CLAIM-001", "CLAIM-002", "CLAIM-003", "CLAIM-004", "CLAIM-005",
            "CLAIM-008"} <= anchored_claims
