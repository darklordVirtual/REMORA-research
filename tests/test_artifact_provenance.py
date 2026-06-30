"""Tests for artifact provenance compliance (artifact_provenance_spec_v1.md §4-5).

Validates that gated P0 artifacts have companion provenance sidecars with all
required fields and correct commit hash format.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FIELDS = {"schema", "schema_version", "commit_hash", "generated_at", "script", "n_samples"}
VALID_GATE_VALUES = {"PASS", "FAIL", "CONDITIONAL", None}

GATED_ARTIFACTS = [
    "results/external_benchmark_agentharm_v1.json",
    "results/false_accept_regression_v1.json",
]


def _load_provenance(artifact_rel: str) -> dict:
    provenance_path = REPO_ROOT / artifact_rel.replace(".json", ".provenance.json")
    assert provenance_path.exists(), (
        f"Missing sidecar provenance for {artifact_rel}: "
        f"expected {provenance_path.relative_to(REPO_ROOT)}"
    )
    return json.loads(provenance_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("artifact_rel", GATED_ARTIFACTS)
def test_provenance_sidecar_exists(artifact_rel):
    """Each gated artifact must have a companion .provenance.json file."""
    artifact_path = REPO_ROOT / artifact_rel
    assert artifact_path.exists(), f"Artifact missing: {artifact_rel}"
    provenance_path = REPO_ROOT / artifact_rel.replace(".json", ".provenance.json")
    assert provenance_path.exists(), f"Sidecar missing: {provenance_path.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("artifact_rel", GATED_ARTIFACTS)
def test_provenance_required_fields(artifact_rel):
    """Sidecar must contain all required provenance fields."""
    prov = _load_provenance(artifact_rel)
    missing = REQUIRED_FIELDS - set(prov.keys())
    assert not missing, f"{artifact_rel} provenance missing fields: {missing}"


@pytest.mark.parametrize("artifact_rel", GATED_ARTIFACTS)
def test_provenance_commit_hash_is_full_sha(artifact_rel):
    """commit_hash must be a full 40-character hex SHA."""
    prov = _load_provenance(artifact_rel)
    commit_hash = prov.get("commit_hash", "")
    assert len(commit_hash) == 40 and all(c in "0123456789abcdef" for c in commit_hash), (
        f"{artifact_rel} provenance commit_hash '{commit_hash}' is not a full 40-char SHA"
    )


@pytest.mark.parametrize("artifact_rel", GATED_ARTIFACTS)
def test_provenance_n_samples_positive(artifact_rel):
    """n_samples must be a positive integer."""
    prov = _load_provenance(artifact_rel)
    n = prov.get("n_samples")
    assert isinstance(n, int) and n >= 1, (
        f"{artifact_rel} provenance n_samples={n!r} must be a positive integer"
    )


@pytest.mark.parametrize("artifact_rel", GATED_ARTIFACTS)
def test_provenance_schema_identifier(artifact_rel):
    """schema field must be 'result_provenance_v1'."""
    prov = _load_provenance(artifact_rel)
    assert prov.get("schema") == "result_provenance_v1", (
        f"{artifact_rel} provenance schema={prov.get('schema')!r}"
    )


@pytest.mark.parametrize("artifact_rel", GATED_ARTIFACTS)
def test_provenance_gate_value_is_valid(artifact_rel):
    """gate field (if present) must be one of PASS, FAIL, CONDITIONAL, or null."""
    prov = _load_provenance(artifact_rel)
    if "gate" in prov:
        assert prov["gate"] in VALID_GATE_VALUES, (
            f"{artifact_rel} provenance gate={prov['gate']!r} not in {VALID_GATE_VALUES}"
        )


@pytest.mark.parametrize("artifact_rel", GATED_ARTIFACTS)
def test_provenance_generated_at_looks_like_iso8601(artifact_rel):
    """generated_at must look like a UTC ISO-8601 timestamp."""
    prov = _load_provenance(artifact_rel)
    generated_at = prov.get("generated_at", "")
    assert isinstance(generated_at, str) and len(generated_at) >= 16 and "T" in generated_at, (
        f"{artifact_rel} provenance generated_at={generated_at!r} does not look like ISO-8601"
    )


# ── build_provenance() unit tests ────────────────────────────────────────────

def test_build_provenance_required_fields():
    from remora.provenance import build_provenance

    prov = build_provenance(
        script="scripts/example.py",
        generated_at="2026-06-30T10:00:00Z",
        n_samples=100,
        commit_hash="a" * 40,
    )
    assert REQUIRED_FIELDS <= set(prov.keys())
    assert prov["schema"] == "result_provenance_v1"
    assert prov["schema_version"] == "1"
    assert prov["n_samples"] == 100
    assert prov["commit_hash"] == "a" * 40


def test_build_provenance_gate_included_when_set():
    from remora.provenance import build_provenance

    prov = build_provenance(
        script="s.py", generated_at="2026-06-30T00:00:00Z", n_samples=1,
        commit_hash="b" * 40, gate="PASS",
    )
    assert prov["gate"] == "PASS"


def test_build_provenance_gate_omitted_when_none():
    from remora.provenance import build_provenance

    prov = build_provenance(
        script="s.py", generated_at="2026-06-30T00:00:00Z", n_samples=1,
        commit_hash="c" * 40,
    )
    assert "gate" not in prov


def test_build_provenance_extra_fields_pass_through():
    from remora.provenance import build_provenance

    prov = build_provenance(
        script="s.py", generated_at="2026-06-30T00:00:00Z", n_samples=5,
        commit_hash="d" * 40, custom_field="hello",
    )
    assert prov["custom_field"] == "hello"


def test_build_provenance_model_version_omitted_when_none():
    from remora.provenance import build_provenance

    prov = build_provenance(
        script="s.py", generated_at="2026-06-30T00:00:00Z", n_samples=1,
        commit_hash="e" * 40,
    )
    assert "model_version" not in prov


def test_build_provenance_notes_included_when_set():
    from remora.provenance import build_provenance

    prov = build_provenance(
        script="s.py", generated_at="2026-06-30T00:00:00Z", n_samples=1,
        commit_hash="f" * 40, notes="test note",
    )
    assert prov["notes"] == "test note"
