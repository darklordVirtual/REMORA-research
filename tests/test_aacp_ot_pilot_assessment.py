# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The AACP v0.2 self-assessment of the OT pilot stays tied to its evidence.

The record is checked against the AACP schema in the agent-authority-conformance
repository, which this repository does not depend on. These tests pin what can
drift here: every cited path exists, the seven properties appear once each in
canonical form, every bounded PASS states its scope and remainder, nothing
aggregates, and the demonstrated D violation stays recorded as one.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "artifacts/ot-pilot/execution-path-reproduction-2026-11-05/aacp-assessment-v0.2.json"
NAMES = {"A": "Receipt Integrity", "B": "Authority Provenance", "C": "Exact-Call Integrity",
         "D": "Semantic Authority", "E": "Execution-Boundary Integrity",
         "F": "TOCTOU Resistance", "G": "Effect Verification"}
FORBIDDEN = {"overall", "score", "total", "aggregate", "grade"}


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_each_property_appears_once_under_its_canonical_name() -> None:
    rows = _record()["properties"]
    assert [(r["id"], r["property"]) for r in rows] == list(NAMES.items())


def test_every_cited_path_exists() -> None:
    record = _record()
    refs = [e for r in record["properties"] for e in r["evidence"]]
    refs += [r["procedure"] for r in record["properties"] if "procedure" in r]
    missing = sorted({e["reference"].split("::")[0] for e in refs
                      if not (ROOT / e["reference"].split("::")[0]).exists()})
    assert missing == []


def test_a_bounded_pass_states_its_scope_and_remainder() -> None:
    for row in _record()["properties"]:
        if row["status"] == "PASS":
            assert row["evidence_tier"] == "RESOLVED" and row["evidence"], row["id"]
            assert row["supported_scope"].strip() and row["untested_remainder"].strip(), row["id"]
            assert row["unresolved_obligations"] == [], row["id"]


def test_nothing_aggregates() -> None:
    assert FORBIDDEN.isdisjoint(_keys(_record()))


def test_the_semantic_authority_violation_stays_recorded() -> None:
    """S06 and S09 executed should-block calls; the record keeps that as FAIL,
    and E and G are not upgraded without the evidence they lack."""
    by_id = {r["id"]: r for r in _record()["properties"]}
    assert by_id["D"]["status"] == "FAIL"
    assert "S06" in by_id["D"]["reasoning"] and "S09" in by_id["D"]["reasoning"]
    assert (by_id["E"]["status"], by_id["E"]["verification_status"]) == ("UNTESTED", "NOT_RUN")
    assert by_id["G"]["status"] == "NOT_ESTABLISHED" and by_id["G"]["unresolved_obligations"]


def test_the_record_says_it_is_a_self_assessment() -> None:
    record = _record()
    assert "BCR-0, SELF" in record["assessor"]
    assert "an independent assessment or reproduction" in record["scope"]["explicit_non_claims"]
