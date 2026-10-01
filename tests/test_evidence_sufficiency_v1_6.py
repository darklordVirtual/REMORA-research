# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evidence-sufficiency v1.6: the public API against an executable contract (v1.3 spec, section 16).

v1.5 is frozen by this change. v1.6 must carry it verbatim, pass section 16 with the
frozen checker, and show each projection of section 16 catching a fault of its class.
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
V15 = ROOT / "conformance" / "evidence-sufficiency-v1.5"
V16 = ROOT / "conformance" / "evidence-sufficiency-v1.6"

# v1.5 as scored by held-out probe 2 (NEGATIVE_RESULTS.md §71); the README is prose and is not pinned.
FROZEN_V15 = {
    "cases.json": "1ee0454c00ec937836914efe376375e0a56d59546fb633c1ae85a4a53e8bc554",
    "model.json": "27537a9cfa60397c56c9539f6040ab251934d9a63f69ce15e627e030aa153a53",
    "run_evidence_sufficiency.py": "06b19e4b150673fd5b766e68426cf5e6152bdd4c962a3f4208670b9a38b57570",
    "run-record.json": "d154d8ff79b2689217d8822dad369f4deafbbe09c6874e2596070e65fe556ac1",
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


RUNNER = _load("evidence_sufficiency_v1_6_runner", V16 / "run_evidence_sufficiency.py")


@pytest.fixture(scope="module")
def record() -> dict:
    return RUNNER.build_record()


def _faulty(tmp_path: Path, anchor: str, replacement: str, label: str):
    source = (V1 / "checker.py").read_text(encoding="utf-8")
    assert source.count(anchor) == 1, anchor
    path = tmp_path / f"checker_{label}.py"
    path.write_text(source.replace(anchor, replacement), encoding="utf-8")
    return _load(f"v16_faulty_{label}_{tmp_path.name}", path)


def test_v15_is_frozen() -> None:
    for name, digest in FROZEN_V15.items():
        assert _sha(V15 / name) == digest, name


def test_v15_is_carried_verbatim() -> None:
    for name in ("guidance.json", "ladders.json", "invariants.json", "model.json"):
        assert _sha(V16 / name) == _sha(V15 / name), name
    before = json.loads((V15 / "cases.json").read_text(encoding="utf-8"))
    after = json.loads((V16 / "cases.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in after.items() if k != "artifact"} == {k: v for k, v in before.items() if k != "artifact"}


def test_record_has_no_failures(record: dict) -> None:
    assert record["failures"] == [] and record["crashes"] == []
    api = record["api_differential"]
    assert api["failures"] == [] and api["inputs"] == api["projections"] == RUNNER.API_INPUTS


def test_generated_inputs_are_seeded_and_reach_every_verdict() -> None:
    model = RUNNER.load_json(V16 / "model.json")
    inputs = RUNNER.generated_api_inputs(model)
    assert inputs == RUNNER.generated_api_inputs(model)
    outcomes = {RUNNER.interpret_model(model, claim, obs) for claim, obs, _ in inputs}
    assert {status for status, _ in outcomes} == {"established", "violated", "not_established"}
    reasons = {reason for _, reason in outcomes}
    vocabulary = RUNNER.reason_vocabulary((V1 / "checker.py").read_text(encoding="utf-8"))
    assert reasons == vocabulary["inconclusive"] | vocabulary["decisive"]


@pytest.mark.parametrize(
    ("label", "anchor", "replacement", "projection"),
    [
        # Verdict value equality broken (the class held-out probe 2 found).
        ("equality", "@dataclass(frozen=True)", "@dataclass(frozen=True, eq=False)", "equality"),
        # A field type changed while as_dict() still renders it the same.
        ("field_type", "        missing_evidence=missing,", "        missing_evidence=list(missing),", "fields"),
        # A module-level table mutated by a call.
        ("module_state", "        missing, decisive_if = _REASON_GUIDANCE[reason]",
         "        missing, decisive_if = _REASON_GUIDANCE[reason]\n        _REASON_GUIDANCE.setdefault('_seen', ((), ''))",
         "module_state"),
        # The caller's input mutated in place.
        ("input_mutated", "    return ASSESSORS[claim](observations, scope)",
         "    if isinstance(observations, dict):\n        observations.setdefault('_assessed', True)\n    return ASSESSORS[claim](observations, scope)",
         "input_mutated"),
    ],
)
def test_each_projection_catches_its_class(tmp_path: Path, label: str, anchor: str, replacement: str, projection: str) -> None:
    failures = RUNNER.build_record(_faulty(tmp_path, anchor, replacement, label))["failures"]
    assert any(f.startswith(f"api_differential:{projection}:") for f in failures), (label, failures[:6])


def test_record_states_the_contract_limit(record: dict) -> None:
    assert any("executable contract" in limit and "not independent evidence" in limit for limit in record["limits"])


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run([sys.executable, str(V16 / "run_evidence_sufficiency.py"), "--check"],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
