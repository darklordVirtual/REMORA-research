# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for the REMORA knowledge dataset structural integrity.

These tests are always runnable — they either test the validator logic
itself (no external files needed) or are skipped if the dataset is absent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATASET_ROOT = Path(__file__).resolve().parents[1] / "datasets" / "remora_knowledge_v1"
_SCENARIOS = _DATASET_ROOT / "scenarios" / "agent_action_scenarios.jsonl"
_EXPECTED = _DATASET_ROOT / "expected_decisions" / "expected_gate_decisions.jsonl"
_EVIDENCE = _DATASET_ROOT / "evidence_packs" / "evidence_objects.jsonl"
_REPLAY = _DATASET_ROOT / "replay_logs" / "shadow_replay_demo.jsonl"
_GATE_RULES = _DATASET_ROOT / "policies" / "remora_gate_rules.yaml"
_RISK_TIER = _DATASET_ROOT / "policies" / "risk_tier_mapping.yaml"

_DATASET_PRESENT = _SCENARIOS.exists() and _EXPECTED.exists() and _EVIDENCE.exists()


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Validator unit tests (always run — no dataset required)
# ---------------------------------------------------------------------------

class TestValidatorInvariants:
    """Test the validator logic against synthetic fixtures."""

    def setup_method(self):
        # Import the validator module
        import importlib.util
        script = _DATASET_ROOT / "scripts" / "validate_knowledge_dataset.py"
        if not script.exists():
            pytest.skip("validate_knowledge_dataset.py not present")
        spec = importlib.util.spec_from_file_location("validate_kd", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.v = mod

    def _ev_obj(self, eid: str = "ev_001", domain: str = "ai_governance") -> dict:
        return {
            "evidence_id": eid, "source": "NIST", "title": "T", "content": "C",
            "domain": domain, "risk_tags": ["high"], "authority_score": 0.8,
            "freshness_score": 0.8, "coverage_score": 0.8, "contradiction_score": 0.05,
        }

    def test_inv1_missing_expected_decision(self):
        scenarios = [{"scenario_id": "s001"}]
        expected = []
        r = self.v.check_inv1_inv2(scenarios, expected)
        assert not r.passed
        assert any("s001" in e for e in r.errors)

    def test_inv2_orphan_expected_decision(self):
        scenarios = []
        expected = [{"scenario_id": "s999"}]
        r = self.v.check_inv1_inv2(scenarios, expected)
        assert not r.passed
        assert any("s999" in e for e in r.errors)

    def test_inv1_inv2_pass(self):
        scenarios = [{"scenario_id": "s001"}, {"scenario_id": "s002"}]
        expected = [{"scenario_id": "s001", "expected_decision": "accept"},
                    {"scenario_id": "s002", "expected_decision": "escalate"}]
        r = self.v.check_inv1_inv2(scenarios, expected)
        assert r.passed

    def test_inv3_missing_field(self):
        obj = self._ev_obj()
        del obj["authority_score"]
        r = self.v.check_inv3_evidence_fields([obj])
        assert not r.passed

    def test_inv3_all_fields_pass(self):
        r = self.v.check_inv3_evidence_fields([self._ev_obj()])
        assert r.passed

    def test_inv4_critical_destructive_accept_fails(self):
        scenarios = [{"scenario_id": "s001", "risk_tier": "critical",
                      "action_type": "destructive_write"}]
        expected = [{"scenario_id": "s001", "expected_decision": "accept"}]
        r = self.v.check_inv4_no_accept_for_destructive(scenarios, expected)
        assert not r.passed

    def test_inv4_high_destructive_escalate_passes(self):
        scenarios = [{"scenario_id": "s001", "risk_tier": "high",
                      "action_type": "destructive_write"}]
        expected = [{"scenario_id": "s001", "expected_decision": "escalate"}]
        r = self.v.check_inv4_no_accept_for_destructive(scenarios, expected)
        assert r.passed

    def test_inv5_missing_outcome_fails(self):
        expected = [
            {"expected_decision": "accept"},
            {"expected_decision": "verify"},
            # missing abstain, escalate
        ]
        r = self.v.check_inv5_decision_distribution(expected)
        assert not r.passed

    def test_inv5_all_outcomes_pass(self):
        expected = [
            {"expected_decision": "accept"},
            {"expected_decision": "verify"},
            {"expected_decision": "abstain"},
            {"expected_decision": "escalate"},
        ]
        r = self.v.check_inv5_decision_distribution(expected)
        assert r.passed

    def test_inv6_out_of_range_fails(self):
        obj = self._ev_obj()
        obj["authority_score"] = 1.5  # > 1
        r = self.v.check_inv6_scores_in_range([obj])
        assert not r.passed

    def test_inv6_valid_scores_pass(self):
        r = self.v.check_inv6_scores_in_range([self._ev_obj()])
        assert r.passed

    def test_inv7_duplicate_scenario_id(self):
        scenarios = [{"scenario_id": "s001"}, {"scenario_id": "s001"}]
        evidence = []
        r = self.v.check_inv7_no_duplicates(scenarios, evidence)
        assert not r.passed

    def test_inv7_duplicate_evidence_id(self):
        scenarios = []
        evidence = [self._ev_obj("ev_001"), self._ev_obj("ev_001")]
        r = self.v.check_inv7_no_duplicates(scenarios, evidence)
        assert not r.passed

    def test_inv7_unique_pass(self):
        scenarios = [{"scenario_id": "s001"}, {"scenario_id": "s002"}]
        evidence = [self._ev_obj("ev_001"), self._ev_obj("ev_002")]
        r = self.v.check_inv7_no_duplicates(scenarios, evidence)
        assert r.passed


# ---------------------------------------------------------------------------
# Dataset integrity (skipped if dataset absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _DATASET_PRESENT, reason="Knowledge dataset not present")
class TestDatasetIntegrity:
    def test_scenarios_count(self):
        scenarios = _load_jsonl(_SCENARIOS)
        assert len(scenarios) >= 100, f"Expected ≥100 scenarios, got {len(scenarios)}"

    def test_expected_decisions_count(self):
        expected = _load_jsonl(_EXPECTED)
        assert len(expected) >= 100

    def test_bijection(self):
        scenarios = _load_jsonl(_SCENARIOS)
        expected = _load_jsonl(_EXPECTED)
        s_ids = {s["scenario_id"] for s in scenarios}
        e_ids = {e["scenario_id"] for e in expected}
        missing = s_ids - e_ids
        orphan = e_ids - s_ids
        assert not missing, f"Scenarios missing expected_decision: {missing}"
        assert not orphan, f"Orphan expected_decisions: {orphan}"

    def test_no_duplicate_scenario_ids(self):
        scenarios = _load_jsonl(_SCENARIOS)
        ids = [s["scenario_id"] for s in scenarios]
        assert len(ids) == len(set(ids)), "Duplicate scenario_ids found"

    def test_no_duplicate_evidence_ids(self):
        evidence = _load_jsonl(_EVIDENCE)
        ids = [e["evidence_id"] for e in evidence]
        assert len(ids) == len(set(ids)), "Duplicate evidence_ids found"

    def test_all_four_decisions_present(self):
        expected = _load_jsonl(_EXPECTED)
        outcomes = {e.get("expected_decision", "").lower() for e in expected}
        for required in ("accept", "verify", "abstain", "escalate"):
            assert required in outcomes, f"No '{required}' in expected decisions"

    def test_no_critical_destructive_accept(self):
        scenarios = _load_jsonl(_SCENARIOS)
        expected = _load_jsonl(_EXPECTED)
        e_map = {e["scenario_id"]: e.get("expected_decision", "").lower() for e in expected}
        violations = []
        for s in scenarios:
            sid = s.get("scenario_id", "?")
            tier = (s.get("risk_tier") or "").lower()
            atype = (s.get("action_type") or "").lower()
            if tier in ("high", "critical") and "destructive" in atype:
                dec = e_map.get(sid, "")
                if dec == "accept":
                    violations.append(sid)
        assert not violations, f"INV-4 violated: {violations}"

    def test_evidence_authority_scores_in_range(self):
        evidence = _load_jsonl(_EVIDENCE)
        for obj in evidence:
            eid = obj.get("evidence_id", "?")
            for field in ("authority_score", "freshness_score", "coverage_score"):
                val = float(obj.get(field, 0))
                assert 0.0 <= val <= 1.0, f"{eid}: {field}={val} out of [0, 1]"

    def test_required_scenario_fields(self):
        scenarios = _load_jsonl(_SCENARIOS)
        required = {"scenario_id", "domain", "risk_tier", "action_type",
                    "expected_decision", "proposed_action"}
        for s in scenarios:
            missing = required - s.keys()
            assert not missing, f"Scenario {s.get('scenario_id','?')}: missing {missing}"

    def test_replay_log_count(self):
        if not _REPLAY.exists():
            pytest.skip("Replay log not present")
        replay = _load_jsonl(_REPLAY)
        assert len(replay) >= 100

    def test_replay_has_required_fields(self):
        if not _REPLAY.exists():
            pytest.skip("Replay log not present")
        replay = _load_jsonl(_REPLAY)
        required = {"timestamp", "agent_id", "tool_name", "expected_decision"}
        for i, entry in enumerate(replay[:10], 1):
            missing = required - entry.keys()
            assert not missing, f"Replay entry {i}: missing {missing}"

    def test_decision_distribution_reasonable(self):
        """No single outcome should dominate more than 60% of all decisions."""
        expected = _load_jsonl(_EXPECTED)
        outcome_counts: dict[str, int] = {}
        for e in expected:
            d = e.get("expected_decision", "unknown").lower()
            outcome_counts[d] = outcome_counts.get(d, 0) + 1
        total = len(expected)
        for outcome, count in outcome_counts.items():
            fraction = count / total
            assert fraction < 0.60, (
                f"Outcome '{outcome}' makes up {fraction:.0%} of decisions — too skewed"
            )


# ---------------------------------------------------------------------------
# Validator integration test (runs the full validator)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _DATASET_PRESENT, reason="Knowledge dataset not present")
def test_validator_script_passes():
    """The standalone validator script should exit 0 on the real dataset."""
    import subprocess
    import sys
    script = _DATASET_ROOT / "scripts" / "validate_knowledge_dataset.py"
    if not script.exists():
        pytest.skip("Validator script not found")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Validator failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
