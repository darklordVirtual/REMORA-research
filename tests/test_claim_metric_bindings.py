# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-007: the claim gates must be able to be wrong about a number.

Every structural gate passed while CLAIM-007 stated a false-accept rate of 30%
and cited a file recording 1.43%. The register parsed, the anchors lined up,
the artifact existed and its hash was fresh. Nothing opened the file.

The decisive test here is the counterexample: the withdrawn claim, restored as
an active claim with its original numbers, must turn this gate red. A gate that
cannot fail on the case that motivated it is not a gate.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "check_claim_metric_bindings.py"
REGISTER = REPO_ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
BASELINE = REPO_ROOT / "docs" / "assurance" / "claim_metric_binding_baseline.json"


def run_gate(register_text: str | None = None, baseline: dict | None = None, tmp_path=None):
    """Run the gate, optionally against a mutated register in a scratch repo."""

    if register_text is None and baseline is None:
        return subprocess.run(
            [sys.executable, str(GATE)], capture_output=True, text=True, cwd=REPO_ROOT
        )

    original_register = REGISTER.read_text(encoding="utf-8")
    original_baseline = BASELINE.read_text(encoding="utf-8")
    try:
        if register_text is not None:
            REGISTER.write_text(register_text, encoding="utf-8")
        if baseline is not None:
            BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(GATE)], capture_output=True, text=True, cwd=REPO_ROOT
        )
    finally:
        REGISTER.write_text(original_register, encoding="utf-8")
        BASELINE.write_text(original_baseline, encoding="utf-8")


def register_dict() -> dict:
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8"))


def test_the_repository_passes_its_own_gate():
    assert run_gate().returncode == 0


def test_the_withdrawn_claim_would_turn_the_gate_red():
    """The counterexample. CLAIM-007's numbers were not in the file it cited."""

    data = register_dict()
    data["claims"].append(
        {
            "id": "CLAIM-900",
            "title": "Reconstruction of the withdrawn component ablation",
            "statement": "Condition A reaches a false-accept rate of 30%.",
            "evidence_level": "internal_benchmark",
            "status": "active",
            "artifact": ["results/toolcall_benchmark_v2_results.json"],
            "n": 700,
            "n_detail": "counterexample fixture",
            "metrics": {"condition_a_far": 0.30},
            "metric_bindings": {
                "condition_a_far": {
                    "path": (
                        "results/toolcall_benchmark_v2_results.json"
                        "#baselines.single_model_heuristic.false_accept_rate"
                    ),
                    "path_rationale": "far is the false-accept rate.",
                }
            },
            "caveat": "Fixture for the RMR-007 counterexample test.",
            "reproduce": "not applicable",
        }
    )
    result = run_gate(register_text=yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    assert result.returncode == 1
    assert "CLAIM-900.condition_a_far" in result.stdout
    assert "claims 0.3" in result.stdout


def test_a_number_with_no_binding_at_all_fails():
    data = register_dict()
    data["claims"].append(
        {
            "id": "CLAIM-901",
            "title": "A claim that publishes a number and points nowhere",
            "statement": "Something is 42.",
            "evidence_level": "internal_benchmark",
            "status": "active",
            "artifact": ["results/toolcall_benchmark_v2_results.json"],
            "n": 1,
            "n_detail": "fixture",
            "metrics": {"something": 42},
            "caveat": "fixture",
            "reproduce": "not applicable",
        }
    )
    result = run_gate(register_text=yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    assert result.returncode == 1
    assert "no metric_bindings block" in result.stdout


def test_an_unbound_metric_needs_a_reason():
    data = register_dict()
    data["claims"].append(
        {
            "id": "CLAIM-902",
            "title": "A claim that declares unbound without saying why",
            "statement": "Something is 42.",
            "evidence_level": "internal_benchmark",
            "status": "active",
            "artifact": ["results/toolcall_benchmark_v2_results.json"],
            "n": 1,
            "n_detail": "fixture",
            "metrics": {"something": 42},
            "metric_bindings": {"something": {"unbound": ""}},
            "caveat": "fixture",
            "reproduce": "not applicable",
        }
    )
    result = run_gate(register_text=yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    assert result.returncode == 1
    assert "unbound with no reason" in result.stdout


def test_the_unbound_debt_may_not_grow():
    """A new unbound number must be bound, not absorbed into the baseline."""

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    result = run_gate(baseline={**baseline, "unbound_metrics": baseline["unbound_metrics"] - 1})
    assert result.returncode == 1
    assert "baseline allows" in result.stdout


def test_a_pointer_into_a_missing_key_fails_rather_than_passing_quietly():
    data = register_dict()
    data["claims"].append(
        {
            "id": "CLAIM-903",
            "title": "A claim pointing at a key that is not there",
            "statement": "Something is 1.",
            "evidence_level": "internal_benchmark",
            "status": "active",
            "artifact": ["results/toolcall_benchmark_v2_results.json"],
            "n": 1,
            "n_detail": "fixture",
            "metrics": {"something": 1.0},
            "metric_bindings": {
                "something": {
                    "path": "results/toolcall_benchmark_v2_results.json#no.such.key"
                }
            },
            "caveat": "fixture",
            "reproduce": "not applicable",
        }
    )
    result = run_gate(register_text=yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    assert result.returncode == 1
    assert "no key" in result.stdout


def test_every_active_numeric_metric_is_accounted_for():
    """No active claim publishes a number the register does not speak about."""

    for claim in register_dict()["claims"]:
        if claim.get("status") != "active":
            continue
        numeric = {
            name
            for name, value in (claim.get("metrics") or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if not numeric:
            continue
        bindings = claim.get("metric_bindings") or {}
        missing = numeric - set(bindings)
        assert not missing, f"{claim['id']} publishes unaccounted numbers: {sorted(missing)}"


def _fixture_claim(claim_id: str, metrics: dict, bindings: dict) -> dict:
    return {
        "id": claim_id,
        "title": "fixture",
        "statement": "fixture",
        "evidence_level": "internal_benchmark",
        "status": "active",
        "artifact": ["results/toolcall_benchmark_v2_results.json"],
        "n": 1,
        "n_detail": "fixture",
        "metrics": metrics,
        "metric_bindings": bindings,
        "caveat": "fixture",
        "reproduce": "not applicable",
    }


def run_with_claim(claim: dict):
    data = register_dict()
    data["claims"].append(claim)
    return run_gate(register_text=yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


FULL_GATE_FAR = (
    "results/toolcall_benchmark_v2_results.json"
    "#baselines.remora_full_policy_gate.false_accept_rate"
)


def test_two_metrics_of_one_claim_may_not_share_a_path():
    """One field cannot be the evidence for two different quantities."""

    result = run_with_claim(
        _fixture_claim(
            "CLAIM-904",
            {"false_accept_rate_a": 0.0, "false_accept_rate_b": 0.0},
            {
                "false_accept_rate_a": {"path": FULL_GATE_FAR},
                "false_accept_rate_b": {"path": FULL_GATE_FAR},
            },
        )
    )
    assert result.returncode == 1
    assert "cannot be the evidence for two different numbers" in result.stdout


def test_a_path_that_does_not_name_the_metric_fails_without_a_rationale():
    """The right number at the wrong path is a coincidence, not provenance."""

    result = run_with_claim(
        _fixture_claim(
            "CLAIM-905",
            {"benign_review_friction": 0.0},
            {"benign_review_friction": {"path": FULL_GATE_FAR}},
        )
    )
    assert result.returncode == 1
    assert "shares no word with the metric name" in result.stdout


def test_a_stated_path_rationale_admits_a_mismatched_name():
    result = run_with_claim(
        _fixture_claim(
            "CLAIM-906",
            {"far_pct": 0.0},
            {
                "far_pct": {
                    "path": FULL_GATE_FAR,
                    "scale": 100,
                    "path_rationale": "FAR is the false-accept rate.",
                }
            },
        )
    )
    assert result.returncode == 0, result.stdout


def test_a_rounded_claim_must_round_to_the_artifact_value():
    """1.4% is 10/700 published to one decimal; 1.5% is not."""

    binding = {
        "path": (
            "results/toolcall_benchmark_v2_results.json"
            "#baselines.single_model_heuristic.false_accept_rate"
        ),
        "scale": 100,
        "rounded_to": 1,
        "path_rationale": "FAR is the false-accept rate.",
    }
    ok = run_with_claim(_fixture_claim("CLAIM-907", {"far_pct": 1.4}, {"far_pct": binding}))
    assert ok.returncode == 0, ok.stdout

    bad = run_with_claim(_fixture_claim("CLAIM-908", {"far_pct": 1.5}, {"far_pct": binding}))
    assert bad.returncode == 1
    assert "rounds to" in bad.stdout


def test_the_audited_bindings_point_at_the_field_they_name():
    """Regression: bindings that hit the right number at the wrong path."""

    claims = {claim["id"]: claim for claim in register_dict()["claims"]}

    bindings = claims["CLAIM-001"]["metric_bindings"]
    assert bindings["far_pct"]["path"].endswith(
        "#baselines.remora_full_policy_gate.false_accept_rate"
    )
    assert bindings["n_effective"]["path"].endswith("#n_template_clusters")
    assert bindings["baseline_far_pct"]["path"].endswith(
        "#baselines.single_model_heuristic.false_accept_rate"
    )

    bindings = claims["CLAIM-014"]["metric_bindings"]
    for name in ("read_utility_without_validators", "read_utility_with_validators"):
        assert bindings[name]["path"].endswith("#validator_study." + name)
    assert bindings["corrupt_accept_rate"]["path"].endswith(
        "#validator_study.targets.corrupt_id_accept_after_resolver.value"
    )

    bindings = claims["CLAIM-019"]["metric_bindings"]
    assert bindings["wrong_call_accept_pct"]["path"].endswith(
        "#targets.known_wrong_call_accept.value"
    )
    assert bindings["required_unknown_accept_pct"]["path"].endswith(
        "#targets.required_unknown_auto_accept.value"
    )


def test_a_superseded_claim_names_only_the_claim_that_superseded_it():
    for claim in register_dict()["claims"]:
        target = claim.get("superseded_by")
        if not target:
            continue
        mentioned = set(
            re.findall(r"CLAIM-\d+", f"{claim.get('title', '')} {claim.get('statement', '')}")
        )
        assert mentioned <= {target}, (
            f"{claim['id']} is superseded by {target} but its prose points at "
            f"{sorted(mentioned - {target})}"
        )
