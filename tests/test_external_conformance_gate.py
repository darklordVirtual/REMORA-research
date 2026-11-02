# SPDX-License-Identifier: BUSL-1.1
"""Fail-closed badge gate: never hide unsupported or divergent vectors."""
import importlib.util
import json
from pathlib import Path


GATE_PATH = Path(__file__).resolve().parents[1] / "scripts/check_external_conformance.py"
SPEC = importlib.util.spec_from_file_location("external_conformance_gate", GATE_PATH)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def sample(tmp_path):
    suite = {
        "suite": "decision-to-effect-v1",
        "vectors": [{"id": "V-01", "expect": "EXECUTED"},
                    {"id": "V-02", "expect": "REFUSED"}],
    }
    paths = {name: tmp_path / name for name in ("suite", "runner", "adapter")}
    paths["suite"].write_text(json.dumps(suite), encoding="utf-8")
    paths["runner"].write_text("runner", encoding="utf-8")
    paths["adapter"].write_text("adapter", encoding="utf-8")
    sha = "a" * 40
    record = {
        "suite": suite["suite"],
        "suite_sha256": GATE.digest(paths["suite"]),
        "runner_sha256": GATE.digest(paths["runner"]),
        "adapter_sha256": GATE.digest(paths["adapter"]),
        "repo_commit": sha,
        "run_kind": "author-run",
        "adapter": "partner",
        "counts": {"match": 2, "divergent": 0, "unsupported": 0, "error": 0, "total": 2},
        "results": [
            {"id": "V-01", "expected": "EXECUTED", "observed": "EXECUTED", "status": "MATCH"},
            {"id": "V-02", "expected": "REFUSED", "observed": "REFUSED", "status": "MATCH"},
        ],
    }
    return suite, paths, sha, record


def verify(case):
    suite, paths, sha, record = case
    return GATE.validate(
        record, suite, suite_path=paths["suite"],
        runner_path=paths["runner"], adapter_path=paths["adapter"], suite_sha=sha,
    )


def test_genuine_full_match(tmp_path):
    assert verify(sample(tmp_path)) == []


def test_unsupported_fails_even_when_runner_exits_zero(tmp_path):
    case = sample(tmp_path)
    case[3]["results"][1]["status"] = "UNSUPPORTED"
    assert verify(case)


def test_false_match_on_vector_fails(tmp_path):
    case = sample(tmp_path)
    case[3]["results"][0]["observed"] = "WRONG"
    assert verify(case)


def test_missing_or_duplicate_vectors_fail(tmp_path):
    case = sample(tmp_path)
    case[3]["results"][1] = dict(case[3]["results"][0])
    assert verify(case)


def test_changed_adapter_hash_fails(tmp_path):
    case = sample(tmp_path)
    case[1]["adapter"].write_text("modified", encoding="utf-8")
    assert verify(case)


def test_claim_of_independence_fails(tmp_path):
    case = sample(tmp_path)
    case[3]["run_kind"] = "L3_INDEPENDENT_RECOMPUTATION"
    assert verify(case)


def test_skeleton_cannot_pass(tmp_path):
    case = sample(tmp_path)
    case[3]["adapter"] = "skeleton"
    assert verify(case)
