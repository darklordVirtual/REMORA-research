# Author: Stian Skogbrott
# License: Apache-2.0
"""REM-032 acceptance tests: degradation ladder G0–G4 with recorded,
tamper-evident mode transitions, and the G4 action policy."""
from __future__ import annotations

from datetime import datetime, timezone

from remora.governance.degradation import (
    ChainedEventLog,
    DegradationRecorder,
    GovernanceLink,
    GovernanceMode,
    g4_refuses,
)

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def _recorder() -> DegradationRecorder:
    return DegradationRecorder(now_fn=lambda: NOW)


# ---------------------------------------------------------------------------
# Ladder semantics — simulated partition per link
# ---------------------------------------------------------------------------

def test_each_link_maps_to_its_mode() -> None:
    expected = {
        GovernanceLink.TELEMETRY: GovernanceMode.G1_NO_LEARNING,
        GovernanceLink.EXTERNAL_PDP: GovernanceMode.G2_NO_EXTERNAL_PDP,
        GovernanceLink.ORACLE_POOL: GovernanceMode.G3_NO_ORACLES,
        GovernanceLink.CONTROL_PLANE: GovernanceMode.G4_CONTROL_PLANE_UNREACHABLE,
    }
    for link, mode in expected.items():
        rec = _recorder()
        assert rec.current_mode is GovernanceMode.G0_FULL
        assert rec.link_down(link, cause=f"simulated {link.value} outage") is mode


def test_worst_mode_wins_with_multiple_links_down() -> None:
    rec = _recorder()
    rec.link_down(GovernanceLink.TELEMETRY, "aromer timeout")
    assert rec.current_mode is GovernanceMode.G1_NO_LEARNING
    rec.link_down(GovernanceLink.ORACLE_POOL, "quorum lost")
    assert rec.current_mode is GovernanceMode.G3_NO_ORACLES
    rec.link_down(GovernanceLink.EXTERNAL_PDP, "opa 503")
    # G3 outranks G2 — mode must not regress when a lesser link also fails.
    assert rec.current_mode is GovernanceMode.G3_NO_ORACLES


def test_recovery_transitions_are_recorded_too() -> None:
    rec = _recorder()
    rec.link_down(GovernanceLink.CONTROL_PLANE, "partition")
    rec.link_up(GovernanceLink.CONTROL_PLANE, "partition healed")
    assert rec.current_mode is GovernanceMode.G0_FULL
    kinds = [(e.payload["direction"], e.payload["to_mode"]) for e in rec.events]
    assert kinds == [
        ("degradation", GovernanceMode.G4_CONTROL_PLANE_UNREACHABLE.value),
        ("recovery", GovernanceMode.G0_FULL.value),
    ]


def test_no_event_without_mode_change() -> None:
    rec = _recorder()
    rec.link_down(GovernanceLink.ORACLE_POOL, "quorum lost")
    n_events = len(rec.events)
    # A lesser link failing while G3 holds does not change the mode.
    rec.link_down(GovernanceLink.TELEMETRY, "aromer timeout")
    assert len(rec.events) == n_events
    # But recovering only the lesser link does not change the mode either.
    rec.link_up(GovernanceLink.TELEMETRY, "aromer back")
    assert len(rec.events) == n_events


# ---------------------------------------------------------------------------
# Tamper evidence
# ---------------------------------------------------------------------------

def test_event_chain_verifies_and_detects_tampering() -> None:
    rec = _recorder()
    rec.link_down(GovernanceLink.EXTERNAL_PDP, "opa down")
    rec.link_up(GovernanceLink.EXTERNAL_PDP, "opa back")
    ok, problems = rec.verify_chain()
    assert ok, problems
    # Tamper with a recorded event payload (bypass frozen via object.__setattr__).
    tampered = rec.events[0]
    object.__setattr__(tampered, "payload", {**tampered.payload, "cause": "benign"})
    ok, problems = rec.verify_chain()
    assert not ok
    assert any(p.startswith("hash_mismatch_at:0") for p in problems)


def test_sink_receives_every_event() -> None:
    received = []
    rec = DegradationRecorder(sink=received.append, now_fn=lambda: NOW)
    rec.link_down(GovernanceLink.CONTROL_PLANE, "partition")
    rec.link_up(GovernanceLink.CONTROL_PLANE, "healed")
    assert [e.kind for e in received] == ["governance_mode_transition"] * 2


def test_export_jsonl_round_trip(tmp_path) -> None:
    import json

    rec = _recorder()
    rec.link_down(GovernanceLink.TELEMETRY, "outage")
    path = tmp_path / "degradation_events.jsonl"
    rec.export_jsonl(path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["kind"] == "governance_mode_transition"
    assert lines[0]["payload"]["to_mode"] == GovernanceMode.G1_NO_LEARNING.value


# ---------------------------------------------------------------------------
# G4 action policy — engine-vocabulary aligned
# ---------------------------------------------------------------------------

def test_g4_refuses_mutating_and_production_actions() -> None:
    assert g4_refuses("production_write", "staging")   # mutating type
    assert g4_refuses("write", None)                   # mutating type
    assert g4_refuses("read", "prod")                  # production target
    assert g4_refuses("  Destructive_Write  ", None)   # normalisation
    assert g4_refuses(None, " PROD ")                  # normalisation


def test_g4_allows_read_only_non_production() -> None:
    assert not g4_refuses("read", "staging")
    assert not g4_refuses("query", None)
    assert not g4_refuses(None, None)


def test_g4_vocabulary_is_the_engines_own() -> None:
    """The G4 policy must use the decision engine's vocabularies, so hook
    and engine cannot drift apart on what counts as mutating/production."""
    from remora.policy.decision_engine import _MUTATING_TYPES, _PROD_ENVS

    for action_type in _MUTATING_TYPES:
        assert g4_refuses(action_type, None), action_type
    for env in _PROD_ENVS:
        assert g4_refuses(None, env), env


# ---------------------------------------------------------------------------
# ChainedEventLog is deterministic given a fixed clock
# ---------------------------------------------------------------------------

def test_chained_log_is_deterministic() -> None:
    def build() -> ChainedEventLog:
        log = ChainedEventLog(now_fn=lambda: NOW)
        log.append("a", {"x": 1})
        log.append("b", {"y": 2})
        return log

    first, second = build(), build()
    assert [e.entry_hash for e in first.events] == [e.entry_hash for e in second.events]
