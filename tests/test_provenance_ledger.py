# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The provenance ledger: records, registers, manifest and the gates over them.

Asserts on committed records rather than runtime behaviour, so ``docgate``.
The ledger records priority and content; these tests make sure it cannot
quietly record more than that: no classification without a review, no
record outside the register's concept set, no manifest that does not
reproduce from its snapshot, and a signature gate that reports every commit
touching the protected paths.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "provenance"


def _module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot() -> str:
    return json.loads((LEDGER / "manifests" / "provenance-manifest-v1.json").read_text(encoding="utf-8"))["snapshot"]


#: The reproduction test reads the snapshot commit's tree, which a shallow CI
#: checkout does not hold. The documentation-governance job checks out full
#: history and runs scripts/build_provenance_manifest.py --check, so the gate
#: is enforced there on every push.
needs_history = pytest.mark.skipif(
    subprocess.run(["git", "cat-file", "-e", f"{_snapshot()}^{{commit}}"], cwd=ROOT,
                   capture_output=True, check=False).returncode != 0,
    reason="the manifest's snapshot commit is not in this (shallow) clone",
)


@pytest.fixture(scope="module")
def records() -> dict[str, dict[str, Any]]:
    return {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((LEDGER / "concepts").glob("PROV-*.yaml"))}


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads((LEDGER / "manifests" / "provenance-manifest-v1.json").read_text(encoding="utf-8"))


def test_every_register_concept_has_exactly_one_record(records: dict[str, dict[str, Any]]) -> None:
    concepts = {c["id"] for c in yaml.safe_load((ROOT / "docs/assurance/provenance_concepts_v1.yaml").read_text(encoding="utf-8"))["concepts"]}
    assert set(records) == concepts
    for cid, record in records.items():
        assert record["concept_id"] == cid


def test_no_record_claims_more_than_the_ledger_can_show(records: dict[str, dict[str, Any]]) -> None:
    prior = yaml.safe_load((LEDGER / "PRIOR_ART.yaml").read_text(encoding="utf-8"))
    reviewed = {c for r in prior["reviews"] for c in r["concepts"]}
    for cid, record in records.items():
        if cid not in reviewed:
            assert record["classification"] == "UNKNOWN", cid
            assert record["origin"]["status"] == "claimed_original_contribution", cid
            assert record["prior_art"]["reviewed"] is False, cid
        assert record["license"]["spdx"] == "BUSL-1.1"
        assert record["distinguishing_contribution"]


def test_first_recorded_data_is_the_registers(records: dict[str, dict[str, Any]]) -> None:
    register = json.loads((ROOT / "docs/assurance/provenance_register_v1.json").read_text(encoding="utf-8"))
    first = {c["id"]: c["first"][0] for c in register["concepts"]}
    for cid, record in records.items():
        assert record["first_recorded"]["commit"] == first[cid]["commit"], cid
        assert record["evolution"][0]["commit"] == first[cid]["commit"], cid


@needs_history
def test_ledger_validates_and_manifest_reproduces_from_its_snapshot() -> None:
    module = _module("build_provenance_manifest")
    committed = json.loads((LEDGER / "manifests" / "provenance-manifest-v1.json").read_text(encoding="utf-8"))
    problems, records = module.validate(committed["snapshot"])
    assert problems == []
    rebuilt = module.build(committed["snapshot"], records, release=committed.get("release"))
    assert module._stable(rebuilt) == module._stable(committed)
    assert committed["ledger_sha256"] == rebuilt["ledger_sha256"]


def test_manifest_digests_every_record_and_register(manifest: dict[str, Any], records: dict[str, dict[str, Any]]) -> None:
    policy = yaml.safe_load((LEDGER / "POLICY.yaml").read_text(encoding="utf-8"))
    assert set(manifest["concepts"]) == set(records)
    assert set(manifest["registers"]) == set(policy["manifest"]["registers"])
    assert {Path(p).stem for p in manifest["concept_records"]} == set(records)
    for cid, entry in manifest["concepts"].items():
        for section in ("canonical_spec", "implementation", "tests"):
            assert [e["path"] for e in entry[section]] == [e["path"] for e in records[cid][section]], (cid, section)
            for e in entry[section]:
                assert len(e["sha256"]) == 64 and len(e["blob"]) == 40
    assert "manifests/provenance-manifest-v1.json" not in json.dumps(manifest["registers"]), "a manifest never digests itself"


def test_a_self_upgraded_classification_is_refused(tmp_path: Path) -> None:
    module = _module("build_provenance_manifest")
    src = LEDGER / "concepts" / "PROV-13.yaml"
    record = yaml.safe_load(src.read_text(encoding="utf-8"))
    record["classification"] = "ORIGINAL_CLAIM"
    validator = module._validator("concept-record-v1")
    errors = module._errors(validator, record, "PROV-13")
    assert errors, "schema must require a review before a classification"
    record["prior_art"]["reviewed"] = True
    record["prior_art"]["records"] = ["PA-REV-999"]
    assert module._errors(validator, record, "PROV-13") == []
    # The schema is satisfied, so the builder's cross-check must be the one
    # that refuses it: PA-REV-999 is not in PRIOR_ART.yaml.
    original = src.read_text(encoding="utf-8")
    try:
        src.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
        snapshot = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        problems, _ = module.validate(snapshot)
    finally:
        src.write_text(original, encoding="utf-8")
    assert any("PA-REV-999" in p for p in problems)
    assert any("without a review naming PROV-13" in p for p in problems)


def test_external_events_say_what_the_source_says_and_mark_maintainer_overlap() -> None:
    adoption = yaml.safe_load((LEDGER / "EXTERNAL_ADOPTION.yaml").read_text(encoding="utf-8"))
    ids = [e["id"] for e in adoption["events"]]
    assert len(ids) == len(set(ids))
    for event in adoption["events"]:
        assert event["source"]["url"].startswith("https://")
        assert event["relationship"]["claimed_by_external_source"]
        if "darklordVirtual/" in event["project"]:
            assert event["relationship"]["maintainer_overlap"] is True, event["id"]


def test_signature_gate_reports_and_only_fails_when_armed() -> None:
    policy = yaml.safe_load((LEDGER / "POLICY.yaml").read_text(encoding="utf-8"))
    out = subprocess.run([sys.executable, str(ROOT / "scripts/check_provenance_signatures.py"), "--report"],
                         cwd=ROOT, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[REPORT]" in out.stdout
    if policy["signatures"]["enforced_from"] is None:
        out = subprocess.run([sys.executable, str(ROOT / "scripts/check_provenance_signatures.py")],
                             cwd=ROOT, capture_output=True, text=True, check=False)
        assert out.returncode == 0
        assert "not armed" in out.stdout
