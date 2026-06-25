from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from remora.governance.envelope import DecisionEnvelope
from remora.shadow.replay import replay_action_log, verify_envelope_hash_chain


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_shadow_replay_generates_delta_report_and_envelopes(tmp_path: Path) -> None:
    log_path = tmp_path / "agent_action_log.jsonl"
    env_out = tmp_path / "envelopes.jsonl"
    rep_out = tmp_path / "report.json"
    audit_out = tmp_path / "audit.jsonl"

    rows = [
        {
            "question": "Read customer invoice",
            "domain": "finance",
            "risk_tier": "low",
            "action_type": "read",
            "target_environment": "prod",
            "phase": "ordered",
            "trust_score": 0.92,
            "evidence_action": "answer",
            "evidence_confidence": 0.91,
            "evidence_contradictions": 0,
            "unsafe": False,
        },
        {
            "question": "Delete all payment records",
            "domain": "finance",
            "risk_tier": "critical",
            "action_type": "delete",
            "target_environment": "prod",
            "phase": "critical",
            "trust_score": 0.8,
            "unsafe": True,
            "policy_violation": True,
            "adversarial_detected": True,
        },
        {
            "question": "Update account metadata",
            "domain": "finance",
            "risk_tier": "high",
            "action_type": "write",
            "target_environment": "prod",
            "phase": "ordered",
            "trust_score": 0.6,
            "is_tie": True,
            "refuse_parametric_verdict": True,
            "unsafe": False,
        },
    ]
    _write_jsonl(log_path, rows)

    result = replay_action_log(
        str(log_path),
        output_envelopes_jsonl=str(env_out),
        output_report_json=str(rep_out),
        output_audit_jsonl=str(audit_out),
    )

    assert result.report.total_actions_reviewed == 3
    assert result.report.audit_completeness_pct == 100.0
    assert result.report.oracle_disagreement_cases >= 1
    assert result.report.policy_violations_detected >= 1

    with open(rep_out) as f:
        payload = json.load(f)
    assert payload["total_actions_reviewed"] == 3
    assert "baseline_comparison" in payload

    with open(env_out) as f:
        lines = [line for line in f if line.strip()]
    assert len(lines) == 3

    with open(audit_out) as f:
        audit_lines = [line for line in f if line.strip()]
    assert len(audit_lines) == 3


def test_shadow_replay_critical_actions_never_autonomous_accept_in_sample(tmp_path: Path) -> None:
    log_path = tmp_path / "critical.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "question": "Drop production table",
                "risk_tier": "critical",
                "action_type": "delete",
                "target_environment": "prod",
                "phase": "critical",
                "trust_score": 0.95,
                "unsafe": True,
            }
        ],
    )

    result = replay_action_log(str(log_path))
    assert result.report.critical_actions_proposed == 1
    assert result.report.critical_autonomous_accepts == 0


def test_shadow_replay_baseline_matrix_contains_expected_keys(tmp_path: Path) -> None:
    log_path = tmp_path / "baseline.jsonl"
    _write_jsonl(
        log_path,
        [{"question": "Read docs", "phase": "ordered", "trust_score": 0.8}],
    )

    result = replay_action_log(str(log_path))
    keys = set(result.report.baseline_comparison)
    assert {
        "no_gate",
        "majority_vote",
        "single_judge",
        "confidence_threshold",
        "policy_only_gate",
        "remora_full_gate",
    }.issubset(keys)


def test_shadow_replay_unsafe_avoidance_estimate(tmp_path: Path) -> None:
    log_path = tmp_path / "unsafe.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "question": "sudo rm -rf /",
                "risk_tier": "critical",
                "phase": "critical",
                "unsafe": True,
                "policy_violation": True,
                "adversarial_detected": True,
            }
        ],
    )

    result = replay_action_log(str(log_path))
    assert result.report.estimated_avoided_unsafe_executions == 1


def test_shadow_replay_envelope_hash_chain_verifies(tmp_path: Path) -> None:
    log_path = tmp_path / "chain_ok.jsonl"
    _write_jsonl(
        log_path,
        [
            {"question": "Read config", "risk_tier": "low", "phase": "ordered", "trust_score": 0.9},
            {"question": "Patch service", "risk_tier": "high", "phase": "critical", "trust_score": 0.6},
        ],
    )

    result = replay_action_log(str(log_path))
    assert verify_envelope_hash_chain(result.envelopes) is True


def test_shadow_replay_envelope_hash_chain_detects_tamper(tmp_path: Path) -> None:
    log_path = tmp_path / "chain_tamper.jsonl"
    _write_jsonl(
        log_path,
        [
            {"question": "Read docs", "risk_tier": "low", "phase": "ordered", "trust_score": 0.8},
            {"question": "Delete logs", "risk_tier": "high", "phase": "critical", "trust_score": 0.4},
        ],
    )

    result = replay_action_log(str(log_path))
    assert verify_envelope_hash_chain(result.envelopes) is True

    # Tamper a non-hash field in the second envelope and rebuild object.
    tampered = [e for e in result.envelopes]
    second = tampered[1].to_dict()
    second["assessment"]["policy_triggers"].append("tampered_reason")
    tampered[1] = DecisionEnvelope.from_dict(second)

    assert verify_envelope_hash_chain(tampered) is False


def test_shadow_replay_cli_out_dir_writes_expected_files(tmp_path: Path) -> None:
    log_path = tmp_path / "agent_action_log.jsonl"
    out_dir = tmp_path / "shadow_replay"
    _write_jsonl(
        log_path,
        [
            {
                "question": "Read customer invoice",
                "domain": "finance",
                "risk_tier": "low",
                "action_type": "read",
                "target_environment": "prod",
                "phase": "ordered",
                "trust_score": 0.92,
                "unsafe": False,
            }
        ],
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/shadow_replay.py",
            "--input",
            str(log_path),
            "--out-dir",
            str(out_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "REMORA Governance Delta Report" in completed.stdout
    assert (out_dir / "decision_envelopes.jsonl").exists()
    assert (out_dir / "governance_delta_report.json").exists()
    assert (out_dir / "replay_audit.jsonl").exists()
