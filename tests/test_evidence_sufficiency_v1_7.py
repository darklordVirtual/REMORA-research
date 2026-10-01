# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evidence-sufficiency v1.7: API surface, call sequences, contract crossing (v1.3 spec, section 17).

v1.6 is frozen by this change. v1.7 must carry it verbatim, pass sections 17 to 19
with the frozen checker, and show each section catching a fault of its class.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "conformance" / "evidence-sufficiency-v1"
V16 = ROOT / "conformance" / "evidence-sufficiency-v1.6"
V17 = ROOT / "conformance" / "evidence-sufficiency-v1.7"

# v1.6 as scored by held-out probe 3 (NEGATIVE_RESULTS.md §72); the README is prose and is not pinned.
FROZEN_V16 = {
    "cases.json": "739840ad0f762cadfe552abfd640eb27f17d8fe88958fa649e67ee487f96ce93",
    "model.json": "27537a9cfa60397c56c9539f6040ab251934d9a63f69ce15e627e030aa153a53",
    "run_evidence_sufficiency.py": "c66198a0564756375405427aa3a5354893698591347e7c6cf40ed2648f7f4081",
    "run-record.json": "c0e06a3618a8ed8e90b1b9ddd4adc9dce0004190611d38b0daa9859f296ae67f",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load("evidence_sufficiency_v1_7_runner", V17 / "run_evidence_sufficiency.py")


@pytest.fixture(scope="module")
def record() -> dict:
    return RUNNER.build_record()


def _faulty(tmp_path: Path, anchor: str, replacement: str, label: str):
    source = (V1 / "checker.py").read_text(encoding="utf-8")
    assert source.count(anchor) == 1, anchor
    path = tmp_path / f"checker_{label}.py"
    path.write_text(source.replace(anchor, replacement), encoding="utf-8")
    return _load(f"v17_faulty_{label}_{tmp_path.name}", path)


def test_v16_is_frozen() -> None:
    for name, digest in FROZEN_V16.items():
        assert _sha(V16 / name) == digest, name


def test_v16_is_carried_verbatim() -> None:
    for name in ("guidance.json", "ladders.json", "invariants.json", "model.json"):
        assert _sha(V17 / name) == _sha(V16 / name), name
    before = json.loads((V16 / "cases.json").read_text(encoding="utf-8"))
    after = json.loads((V17 / "cases.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in after.items() if k != "artifact"} == {k: v for k, v in before.items() if k != "artifact"}


def test_record_has_no_failures(record: dict) -> None:
    assert record["failures"] == [] and record["crashes"] == []
    assert record["api_surface"]["failures"] == [] and record["api_surface"]["names"] > 0
    assert record["call_sequences"]["calls"] == RUNNER.SEQUENCES * RUNNER.SEQUENCE_LENGTH
    assert record["contract_crossing"]["checks"] > 0 and record["contract_crossing"]["failures"] == []


def test_api_surface_snapshot_is_the_frozen_checker() -> None:
    expected = json.loads((V17 / "api_surface.json").read_text(encoding="utf-8"))
    assert expected == json.loads(json.dumps(RUNNER.api_surface(RUNNER.checker)))
    assert "MISSING" in json.dumps(expected), "default sentinels must not carry a memory address"


@pytest.mark.parametrize(
    ("label", "anchor", "replacement", "section"),
    [
        ("kw_only", "@dataclass(frozen=True)", "@dataclass(frozen=True, kw_only=True)", "api_surface"),
        ("alias_member", '    NOT_ESTABLISHED = "not_established"\n',
         '    NOT_ESTABLISHED = "not_established"\n    UNKNOWN = "not_established"\n', "api_surface"),
        ("shared_default_scope", '        return {"kind": "synthetic_fixture", "bounded": True}',
         '        return _scope.__dict__.setdefault("default", {"kind": "synthetic_fixture", "bounded": True})',
         "call_sequence"),
        ("empty_observations_skip_scope", "    if scope is not None:\n",
         "    if scope is not None and observations:\n", "contract_crossing"),
    ],
)
def test_each_section_catches_its_class(tmp_path: Path, label: str, anchor: str, replacement: str, section: str) -> None:
    failures = RUNNER.build_record(_faulty(tmp_path, anchor, replacement, label))["failures"]
    assert any(f.startswith(f"{section}:") for f in failures), (label, failures[:6])


def test_record_states_the_snapshot_limit(record: dict) -> None:
    assert any("api_surface.json is a snapshot" in limit for limit in record["limits"])


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run([sys.executable, str(V17 / "run_evidence_sufficiency.py"), "--check"],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
