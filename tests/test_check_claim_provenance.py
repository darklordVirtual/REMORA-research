from __future__ import annotations

import hashlib
import importlib.util
import json
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
    assert len(claims) == 16
    assert ids[0] == "CLAIM-001" and ids[-1] == "CLAIM-016"
    by_id = {c["id"]: c for c in claims}
    assert by_id["CLAIM-001"]["artifact"] == [
        "results/toolcall_benchmark_v2_results.json",
        "results/toolcall_benchmark_v2_significance.json",
        "results/toolcall_blind_v3_results.json",
        "results/toolcall_m1_clean_signal.json",
    ]
    # REM-038: effective-N and cluster-level CI must be in the register.
    assert by_id["CLAIM-001"]["metrics"]["n_effective"] == 70
    assert by_id["CLAIM-001"]["metrics"]["far_ci_high_pct"] == 5.2
    assert by_id["CLAIM-002"]["metrics"]["fbr_pct"] == 100.0
    # SAP v2 clean-round re-issue 2026-07-27 (18/18 accepted, directional).
    assert by_id["CLAIM-004"]["metrics"]["accuracy_pct"] == 100.0
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
# Promotion provenance (issue #88): v3 sidecars must be clean or carry a
# hashed diff; legacy v2 sidecars are exempt.
# ---------------------------------------------------------------------------

def _write_artifact_with_sidecar(
    tmp_path: Path, rel: str, sidecar: dict | str | None
) -> Path:
    artifact = tmp_path / rel
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    if sidecar is not None:
        sidecar_path = artifact.with_name(
            artifact.name.rsplit(".", 1)[0] + ".provenance.json"
        )
        text = sidecar if isinstance(sidecar, str) else json.dumps(sidecar)
        sidecar_path.write_text(text, encoding="utf-8")
    return artifact


V3_CLEAN_SIDECAR = {
    "schema": "result_provenance_v3",
    "pre_run_worktree_clean": True,
    "allowed_generated_outputs": ["results/r.json"],
    "post_run_worktree_clean": True,
    "worktree_dirty_beyond_outputs": [],
}


def test_promotion_gate_skips_v2_sidecar(tmp_path: Path) -> None:
    _write_artifact_with_sidecar(
        tmp_path,
        "results/r.json",
        {"schema": "result_provenance_v2", "worktree_clean": False},
    )
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    assert ccp.check_promotion_provenance(claims, notes, root=tmp_path) == []


def test_promotion_gate_skips_missing_sidecar(tmp_path: Path) -> None:
    _write_artifact_with_sidecar(tmp_path, "results/r.json", None)
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    assert ccp.check_promotion_provenance(claims, notes, root=tmp_path) == []


def test_promotion_gate_passes_clean_v3(tmp_path: Path) -> None:
    _write_artifact_with_sidecar(tmp_path, "results/r.json", V3_CLEAN_SIDECAR)
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    assert ccp.check_promotion_provenance(claims, notes, root=tmp_path) == []
    assert notes == []


def test_promotion_gate_fails_dirty_v3(tmp_path: Path) -> None:
    sidecar = dict(V3_CLEAN_SIDECAR)
    sidecar["post_run_worktree_clean"] = False
    sidecar["worktree_dirty_beyond_outputs"] = ["scripts/hack.py"]
    _write_artifact_with_sidecar(tmp_path, "results/r.json", sidecar)
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    errors = ccp.check_promotion_provenance(claims, notes, root=tmp_path)
    assert [eid for eid, _ in errors] == ["promotion-dirty-worktree:results/r.json"]
    assert "scripts/hack.py" in errors[0][1]
    assert "rebenchmark_protocol_v1.md" in errors[0][1]


def test_promotion_gate_requires_both_flags(tmp_path: Path) -> None:
    # pre=false/post=true also fails: a run started on a dirty tree cannot
    # pass without the manual hashed-diff route.
    sidecar = dict(V3_CLEAN_SIDECAR)
    sidecar["pre_run_worktree_clean"] = False
    _write_artifact_with_sidecar(tmp_path, "results/r.json", sidecar)
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    errors = ccp.check_promotion_provenance(claims, notes, root=tmp_path)
    assert [eid for eid, _ in errors] == ["promotion-dirty-worktree:results/r.json"]


def test_promotion_gate_dedupes_across_claims(tmp_path: Path) -> None:
    sidecar = dict(V3_CLEAN_SIDECAR)
    sidecar["post_run_worktree_clean"] = False
    _write_artifact_with_sidecar(tmp_path, "results/r.json", sidecar)
    claims = [
        {"id": "CLAIM-401", "artifact": ["results/r.json"]},
        {"id": "CLAIM-402", "artifact": ["results/r.json"]},
    ]
    notes: list[str] = []
    errors = ccp.check_promotion_provenance(claims, notes, root=tmp_path)
    assert [eid for eid, _ in errors] == ["promotion-dirty-worktree:results/r.json"]


def test_promotion_gate_accepts_hashed_diff(tmp_path: Path) -> None:
    diff_lf = b"--- a/scripts/hack.py\n+++ b/scripts/hack.py\n+x = 1\n"
    sidecar = dict(V3_CLEAN_SIDECAR)
    sidecar["post_run_worktree_clean"] = False
    sidecar["worktree_diff_sha256"] = hashlib.sha256(diff_lf).hexdigest()
    artifact = _write_artifact_with_sidecar(tmp_path, "results/r.json", sidecar)
    diff_file = artifact.with_name("r.worktree.diff")
    diff_file.write_bytes(diff_lf)
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    assert ccp.check_promotion_provenance(claims, notes, root=tmp_path) == []
    assert notes and "hashed diff" in notes[0]

    # CRLF-on-disk variant of the same diff also passes (LF normalization).
    diff_file.write_bytes(diff_lf.replace(b"\n", b"\r\n"))
    notes = []
    assert ccp.check_promotion_provenance(claims, notes, root=tmp_path) == []
    assert notes


def test_promotion_gate_fails_diff_hash_mismatch(tmp_path: Path) -> None:
    sidecar = dict(V3_CLEAN_SIDECAR)
    sidecar["post_run_worktree_clean"] = False
    sidecar["worktree_diff_sha256"] = "0" * 64
    artifact = _write_artifact_with_sidecar(tmp_path, "results/r.json", sidecar)
    artifact.with_name("r.worktree.diff").write_bytes(b"+x = 1\n")
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    errors = ccp.check_promotion_provenance(claims, notes, root=tmp_path)
    assert [eid for eid, _ in errors] == [
        "promotion-diff-hash-mismatch:results/r.json"
    ]


def test_promotion_gate_flags_unreadable_sidecar(tmp_path: Path) -> None:
    _write_artifact_with_sidecar(tmp_path, "results/r.json", "{not json")
    claims = [{"id": "CLAIM-401", "artifact": ["results/r.json"]}]
    notes: list[str] = []
    errors = ccp.check_promotion_provenance(claims, notes, root=tmp_path)
    assert [eid for eid, _ in errors] == [
        "promotion-sidecar-unreadable:results/r.json"
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
# Stale-string denylist
# ---------------------------------------------------------------------------

def test_stale_string_detected(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "The gate is REM-020 (eligible close 2026-07-07) as planned.\n",
        encoding="utf-8",
    )
    errors = ccp.check_stale_strings(doc, doc.read_text(encoding="utf-8"))
    assert [eid for eid, _ in errors] == [
        "stale-string:doc.md:eligible close 2026-07-07"
    ]
    assert "2026-07-05" in errors[0][1]


def test_clean_text_passes_stale_check(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("REM-020 closes no earlier than 2026-07-05.\n", encoding="utf-8")
    assert ccp.check_stale_strings(doc, doc.read_text(encoding="utf-8")) == []


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


def _readme_anchored_claims() -> set[str]:
    readme = (ccp.ROOT / "README.md").read_text(encoding="utf-8")
    return {m.group(1) for m in ccp.ANCHOR_RE.finditer(readme)}


def test_real_readme_anchors_are_wired() -> None:
    # Active positive headline claims stay anchored on the README front page.
    # CLAIM-008 was dropped from this set on 2026-07-31: it was superseded by
    # CLAIM-013, and guardrail 5 now forbids anchoring a superseded claim here.
    # Its numbers moved to docs/03-experiments.md, anchored there. The sealed
    # BFCL track is CLAIM-016: master had already claimed 014/015 for the
    # system-demonstration and value-grounding claims, and master's numbering
    # wins because it merged first and is what other documents cite.
    assert {"CLAIM-001", "CLAIM-002", "CLAIM-003", "CLAIM-013",
            "CLAIM-016"} <= _readme_anchored_claims()


def test_readme_front_page_carries_no_superseded_claim() -> None:
    # The other half of the archive contract: an archived result may not creep
    # back onto the front page. Asserted here as well as in the gate, so the
    # rule is visible where the anchor set is maintained.
    claims = ccp.parse_register(ccp.REGISTER_PATH.read_text(encoding="utf-8"))
    superseded = {c["id"] for c in claims if c.get("status") == "superseded"}
    assert superseded, "register declares no superseded claim — did the field vanish?"
    assert not (superseded & _readme_anchored_claims())


def test_real_negative_results_anchors_are_wired() -> None:
    # Negative headline claims moved to NEGATIVE_RESULTS.md (2026-07-28) and
    # must stay anchored there — moved, never dropped.
    negative = (ccp.ROOT / "NEGATIVE_RESULTS.md").read_text(encoding="utf-8")
    anchored_claims = {m.group(1) for m in ccp.ANCHOR_RE.finditer(negative)}
    assert {"CLAIM-004", "CLAIM-005", "CLAIM-012"} <= anchored_claims


# ---------------------------------------------------------------------------
# Guardrail 5b: a superseded claim may be cited, but never silently.
# ---------------------------------------------------------------------------

_SUPERSEDED = {"CLAIM-004"}
_BY_ID = {"CLAIM-004": {"superseded_by": "CLAIM-012"}}


def _cite_errors(tmp_path: Path, body: str, name: str = "doc.md"):
    doc = tmp_path / name
    doc.write_text(body, encoding="utf-8")
    return ccp.check_superseded_citations(doc, body, _SUPERSEDED, _BY_ID)


def test_silent_citation_of_superseded_claim_is_flagged(tmp_path: Path) -> None:
    errors = _cite_errors(tmp_path, "| CLAIM-004 | 88% at 23.2% coverage |\n")
    assert [eid for eid, _ in errors] == ["cites-superseded-claim-silently:doc.md:CLAIM-004"]
    assert "CLAIM-012" in errors[0][1]


def test_citation_with_a_supersession_note_passes(tmp_path: Path) -> None:
    body = (
        "CLAIM-004 is retained for the record only. It was **superseded** by\n"
        "CLAIM-012 when the fresh-data round falsified the signal.\n"
    )
    assert _cite_errors(tmp_path, body) == []


def test_the_note_must_be_in_the_same_paragraph(tmp_path: Path) -> None:
    # A disclaimer three paragraphs away does not reach the reader who is
    # looking at the table row.
    body = (
        "Some of the results on this page are superseded.\n"
        "\n"
        "Unrelated prose about something else entirely.\n"
        "\n"
        "| CLAIM-004 | 88% at 23.2% coverage |\n"
    )
    assert len(_cite_errors(tmp_path, body)) == 1


def test_anchor_comments_are_exempt(tmp_path: Path) -> None:
    # An anchor is a machine binding, already value-checked against the
    # register; it is not prose a reader could mistake for a current result.
    body = "<!-- claim:CLAIM-004 accuracy_pct n -->\nSome numbers: 100.0 and 18.\n"
    assert _cite_errors(tmp_path, body) == []


def test_the_archive_page_itself_is_exempt(tmp_path: Path) -> None:
    doc = ccp.ROOT / "docs" / "assurance" / "superseded_claims.md"
    body = "## CLAIM-004 stands here with no disclaimer, because the page is one.\n"
    assert ccp.check_superseded_citations(doc, body, _SUPERSEDED, _BY_ID) == []


def test_active_claims_are_never_flagged(tmp_path: Path) -> None:
    assert _cite_errors(tmp_path, "| CLAIM-001 | 0% unsafe execution |\n") == []


# ---------------------------------------------------------------------------
# Guardrail 5c: a number an artifact re-issue replaced may not survive.
#
# This is the gate the 2026-07-27 re-issue needed and did not have. Anchors are
# opt-in, so unanchored prose drifted silently for four days across twelve
# documents. retired_values inverts it: the re-issue declares what the old
# strings were, and CI enumerates every place still carrying one.
# ---------------------------------------------------------------------------

_RETIRING_CLAIM = [{
    "id": "CLAIM-004",
    "retired_values": ["N_accepted=25", "[70.0%, 95.8%]"],
}]


def _retired_errors(tmp_path: Path, body: str, name: str = "doc.md"):
    doc = tmp_path / name
    doc.write_text(body, encoding="utf-8")
    return ccp.check_retired_values(doc, body, _RETIRING_CLAIM)


def test_a_retired_value_in_live_prose_is_flagged(tmp_path: Path) -> None:
    errors = _retired_errors(tmp_path, "The holdout gives N_accepted=25 items.\n")
    assert len(errors) == 1
    assert "N_accepted=25" in errors[0][1]
    assert "CLAIM-004" in errors[0][0]


def test_every_occurrence_is_reported_so_the_blast_radius_is_the_output(
    tmp_path: Path,
) -> None:
    # The point of the gate is enumeration: one failure per site, not a single
    # "something is stale" message that leaves the search to a human.
    body = "N_accepted=25 here.\n\nAnd [70.0%, 95.8%] there.\n\nN_accepted=25 again.\n"
    assert len(_retired_errors(tmp_path, body)) == 3


def test_an_explicitly_historical_paragraph_keeps_its_old_numbers(
    tmp_path: Path,
) -> None:
    body = (
        "*Superseded record of the retired round.* The holdout gave\n"
        "N_accepted=25 with CI [70.0%, 95.8%].\n"
    )
    assert _retired_errors(tmp_path, body) == []


def test_the_marker_must_be_in_the_same_paragraph(tmp_path: Path) -> None:
    body = "This page contains superseded material.\n\nN_accepted=25 stands here.\n"
    assert len(_retired_errors(tmp_path, body)) == 1


def test_a_claim_with_no_retired_values_flags_nothing(tmp_path: Path) -> None:
    assert ccp.check_retired_values(
        tmp_path / "d.md", "N_accepted=25\n", [{"id": "CLAIM-001"}]
    ) == []


def test_the_live_register_declares_the_2026_07_27_reissue() -> None:
    # Pins the protocol itself: the re-issue that caused the drift must stay
    # declared, or the gate silently stops protecting anything.
    claims = ccp.parse_register(ccp.REGISTER_PATH.read_text(encoding="utf-8"))
    c4 = next(c for c in claims if c["id"] == "CLAIM-004")
    retired = c4.get("retired_values") or []
    assert "N_accepted=25" in retired and "[70.0%, 95.8%]" in retired
