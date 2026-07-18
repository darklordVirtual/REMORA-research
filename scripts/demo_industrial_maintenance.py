#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic REMORA dry-run demo: governing an industrial maintenance agent.

Scenario: a root-cause-analysis agent has investigated abnormal vibration on a
seawater lift pump and now proposes a sequence of actions with escalating
consequence. This demo drives the REAL components end to end:

    A2AGovernanceEnvelope.verify()          (delegation actually verified)
            │
    capability outside effective scope → PolicyObservation.tool_forbidden
            │
    RemoraDecisionEngine.decide()           (real engine, real reason codes)

No live industrial system is contacted and nothing is mutated.

The autonomy boundary this demo encodes:

1. **Reading is cheap.** Telemetry and document reads with evidence are
   ACCEPTed — governance does not add friction where consequence is low.
2. **Recommendations pass through review by explicit policy.** The proposal
   is a high-risk production write against the work-order system, so the
   engine's production-write policy matrix routes it to VERIFY: a human
   approves before any business-system write. (The data comes from the
   operator's own controlled maintenance sources, so it is *not* modeled as
   tainted — review is a policy decision, not a data-provenance workaround.)
3. **Actuation is out of bounds — and provably so.** The agent's delegation
   chain simply does not include the OT-actuation capability. The A2A
   envelope for that request fails scope verification, the failure sets the
   forbidden-tool signal, and the engine hard-ESCALATEs — regardless of how
   confident the analysis is.
4. **Uncertainty degrades autonomy.** The same work-order proposal with
   contradicting evidence in the source data ABSTAINs instead of VERIFYing:
   contradictions must be resolved before a human is even asked to approve.

This is the pattern for placing an assurance layer between agent platforms
and industrial systems (work-order management, maintenance planning, OT/SCADA
gateways): recommendations flow, actuation does not, and every decision is
explainable via `report.reasons` and the envelope's verification failures.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Terminal presentation — an exclusive finish within plain-terminal limits.
# Colour is used only on a real TTY, honours NO_COLOR and --no-color, and
# degrades to clean ASCII so piping/CI output stays readable. None of this
# touches the decision logic: every value shown is computed live below.
# ---------------------------------------------------------------------------

_WIDTH = 78


class _Glyphs:
    """Two glyph sets: refined box-drawing where the terminal encoding can
    render it, clean ASCII where it cannot (Windows cp1252, dumb terminals)."""

    def __init__(self, unicode_ok: bool) -> None:
        if unicode_ok:
            self.tl, self.tr, self.bl, self.br = "╔", "╗", "╚", "╝"
            self.h, self.v, self.rule = "═", "║", "─"
            self.acc, self.ver, self.abs, self.esc = "●", "◐", "○", "▲"
            self.ok, self.bad, self.dot = "✓", "✗", "•"
        else:
            self.tl, self.tr, self.bl, self.br = "+", "+", "+", "+"
            self.h, self.v, self.rule = "=", "|", "-"
            self.acc, self.ver, self.abs, self.esc = "[+]", "[~]", "[o]", "[!]"
            self.ok, self.bad, self.dot = "OK", "x", "-"


def _unicode_ok() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    if "utf" in enc:
        return True
    try:
        "╔●◐○▲✓✗".encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError, TypeError):
        return False


_ASCII_MAP = {
    ord("\u2014"): "-",   # em dash
    ord("\u2013"): "-",   # en dash
    ord("\u00b7"): "/",   # middot
    ord("\u2192"): "->",  # arrow
    ord("\u2011"): "-",   # non-breaking hyphen
}


def _ascii(text: str) -> str:
    return text.translate(_ASCII_MAP)


class _Style:
    def __init__(self, enabled: bool) -> None:
        self.on = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.on else text

    def bold(self, t: str) -> str:   return self._wrap("1", t)
    def dim(self, t: str) -> str:    return self._wrap("2", t)
    def cyan(self, t: str) -> str:   return self._wrap("36", t)
    def green(self, t: str) -> str:  return self._wrap("32", t)
    def yellow(self, t: str) -> str: return self._wrap("33", t)
    def red(self, t: str) -> str:    return self._wrap("91", t)
    def gray(self, t: str) -> str:   return self._wrap("90", t)


# Decision → (glyph attr on _Glyphs, colouriser attr on _Style)
_VERDICT_STYLE = {
    "ACCEPT":   ("acc", "green"),
    "VERIFY":   ("ver", "yellow"),
    "ABSTAIN":  ("abs", "gray"),
    "ESCALATE": ("esc", "red"),
}


def _make_style() -> _Style:
    enabled = (
        sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and "--no-color" not in sys.argv
        and os.environ.get("TERM") != "dumb"
    )
    return _Style(enabled)

from remora.governance.a2a_envelope import (  # noqa: E402
    A2AGovernanceEnvelope,
    AgentIdentity,
    DelegationLink,
    RegisteredKey,
    sign_delegation_link,
)
from remora.policy import PolicyObservation, RemoraDecisionEngine  # noqa: E402
from remora.policy.observation import canonical_tool_call_hash  # noqa: E402

# Demo-fixed keys (this is a dry run — in production these come from key
# management, and the HMAC layer is replaced by asymmetric signatures).
ENVELOPE_KEY = b"demo-envelope-key"
COE_KEY, ORCH_KEY = b"demo-coe-key", b"demo-orchestrator-key"
# kid -> RegisteredKey binds key material to a principal: a valid registered
# key cannot sign a link claiming a different delegator.
LINK_KEYS = {
    "coe-2026": RegisteredKey(key=COE_KEY, principal="operator-coe"),
    "orch-2026": RegisteredKey(key=ORCH_KEY, principal="agent://orchestrator/01"),
}

# Replay guard: the verifier remembers seen nonces (caller-owned state).
_SEEN_NONCES: set[str] = set()


def _replay_guard(nonce: str) -> bool:
    seen = nonce in _SEEN_NONCES
    _SEEN_NONCES.add(nonce)
    return seen

AGENT_ID = "agent://maintenance-planner/07"
AUDIENCE = "control-plane://operator-remora"

# What the operator actually delegated to this agent — note what is absent:
# no "ot:*" capability. Actuation authority was never granted.
DELEGATED_SCOPE = ("telemetry:read", "docs:read", "workorder:propose_change")


def issue_envelope(capability: str, tool_call_hash: str | None = None) -> A2AGovernanceEnvelope:
    """Issue the agent's delegation envelope for one requested capability,
    bound to the exact tool-call payload it authorises."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    chain = (
        sign_delegation_link(
            DelegationLink(
                delegator="operator-coe",
                delegatee="agent://orchestrator/01",
                scope=("telemetry:read", "docs:read",
                       "workorder:propose_change", "workorder:read"),
                issued_at=now,
            ),
            key=COE_KEY, kid="coe-2026",
        ),
        sign_delegation_link(
            DelegationLink(
                delegator="agent://orchestrator/01",
                delegatee=AGENT_ID,
                scope=DELEGATED_SCOPE,  # attenuated: workorder:read dropped
                issued_at=now,
            ),
            key=ORCH_KEY, kid="orch-2026",
        ),
    )
    return A2AGovernanceEnvelope.issue(
        identity=AgentIdentity(
            agent_id=AGENT_ID,
            agent_version="2.4.1",
            issuer_org="operator-coe",
            responsible_org="operator-asset-team",
        ),
        delegation_chain=chain,
        requested_scope=(capability,),
        policy_version="RemoraDecisionEngine-v3",
        audience=AUDIENCE,
        tool_call_hash=tool_call_hash,
        signing_key=ENVELOPE_KEY,
    )


def delegation_check(
    capability: str, tool_call_hash: str,
) -> tuple[bool, tuple[str, ...], A2AGovernanceEnvelope]:
    """Verify the A2A envelope for a capability, bound to the exact payload.

    Returns (tool_forbidden, failures, envelope): a request outside the
    verified effective scope — or any verification failure, including a
    payload-binding mismatch or nonce replay — sets the forbidden-tool
    signal, which the engine hard-escalates. Fail closed.
    """
    envelope = issue_envelope(capability, tool_call_hash=tool_call_hash)
    result = envelope.verify(
        signing_key=ENVELOPE_KEY,
        expected_audience=AUDIENCE,
        link_keys=LINK_KEYS,
        expected_tool_call_hash=tool_call_hash,
        replay_guard=_replay_guard,
    )
    return (not result.valid), result.failures, envelope


@dataclass(frozen=True)
class ProposedAction:
    label: str
    narrative: str
    capability: str
    observation: PolicyObservation
    delegation_failures: tuple[str, ...]


def build_actions() -> list[ProposedAction]:
    """The agent's proposed action sequence.

    For each action the A2A envelope is verified first; the delegation
    outcome feeds `tool_forbidden` on the PolicyObservation. REMORA is
    stateless: sensor evidence and schema validation are the caller's
    responsibility, encoded as observation fields.
    """

    def action(label: str, narrative: str, capability: str,
               tool: str, tool_args: dict, **obs_fields) -> ProposedAction:
        # Bind the delegation envelope to the exact payload — the same hash the
        # enforcement gate recomputes immediately before execution.
        payload_hash = canonical_tool_call_hash(
            name=tool, arguments=tool_args,
            target=obs_fields.get("target_environment"),
        )
        tool_forbidden, failures, _envelope = delegation_check(capability, payload_hash)
        return ProposedAction(
            label=label,
            narrative=narrative,
            capability=capability,
            observation=PolicyObservation(
                tool_forbidden=tool_forbidden,
                tool_call_hash=payload_hash,
                **obs_fields,
            ),
            delegation_failures=failures,
        )

    return [
        action(
            "read_vibration_telemetry",
            "Read 24h vibration trend for pump P-3101A",
            "telemetry:read",
            tool="read_telemetry",
            tool_args={"asset": "P-3101A", "signal": "vibration", "window": "24h"},
            question="read_telemetry(asset=P-3101A, signal=vibration, window=24h)",
            phase="ordered", trust_score=0.91,
            evidence_action="answer", evidence_confidence=0.94,
            evidence_signal_source="retrieval",
            risk_tier="low", action_type="read", domain="maintenance",
            target_environment="prod", schema_valid=True,
        ),
        action(
            "read_equipment_history",
            "Retrieve maintenance history and last overhaul report",
            "docs:read",
            tool="read_documents",
            tool_args={"asset": "P-3101A", "type": "maintenance_history"},
            question="read_documents(asset=P-3101A, type=maintenance_history)",
            phase="ordered", trust_score=0.88,
            evidence_action="answer", evidence_confidence=0.90,
            evidence_signal_source="retrieval",
            risk_tier="low", action_type="read", domain="maintenance",
            target_environment="prod", schema_valid=True,
        ),
        action(
            "propose_workorder_change",
            "Propose advancing the bearing-replacement work order by 3 weeks "
            "based on vibration trend + history",
            "workorder:propose_change",
            tool="update_work_order",
            tool_args={"order": "WO-88231", "action": "reschedule",
                       "new_date": "advance_3_weeks",
                       "justification": "vibration_trend"},
            question=(
                "update_work_order(order=WO-88231, action=reschedule, "
                "new_date=advance_3_weeks, justification=vibration_trend)"
            ),
            phase="ordered", trust_score=0.86,
            evidence_action="verify", evidence_confidence=0.82,
            evidence_supporters=3, evidence_signal_source="retrieval",
            # High-risk production write → the engine's explicit
            # production-write policy matrix requires human review.
            risk_tier="high", action_type="production_write",
            domain="maintenance", target_environment="prod",
            schema_valid=True, rollback_available=True,
        ),
        action(
            "propose_with_contradicting_evidence",
            "Same work-order proposal, but the overhaul report contradicts "
            "the vibration interpretation",
            "workorder:propose_change",
            tool="update_work_order",
            tool_args={"order": "WO-88231", "action": "reschedule",
                       "new_date": "advance_3_weeks",
                       "justification": "vibration_trend",
                       "evidence_state": "contradicted"},
            question=(
                "update_work_order(order=WO-88231, action=reschedule, "
                "new_date=advance_3_weeks, justification=vibration_trend)"
            ),
            phase="critical", trust_score=0.61,
            evidence_action="verify", evidence_confidence=0.55,
            evidence_supporters=2,
            evidence_contradictions=1,   # hard guard: contradiction blocks
            evidence_signal_source="retrieval",
            risk_tier="high", action_type="production_write",
            domain="maintenance", target_environment="prod",
            schema_valid=True, rollback_available=True,
        ),
        action(
            "direct_ot_actuation",
            "Directly reduce pump speed via the control system",
            "ot:set_pump_speed",   # never delegated → envelope verify fails
            tool="set_pump_speed",
            tool_args={"asset": "P-3101A", "target_rpm": 2400},
            question="set_pump_speed(asset=P-3101A, target_rpm=2400)",
            phase="ordered", trust_score=0.93,   # confidence is irrelevant:
            evidence_action="answer",            # authority was never granted
            evidence_confidence=0.95,
            evidence_signal_source="retrieval",
            risk_tier="critical", action_type="write", domain="ot_control",
            target_environment="prod", schema_valid=True,
            rollback_available=True,
        ),
    ]


def main() -> int:
    # Prefer UTF-8 so the refined glyphs render on any modern terminal; the
    # ASCII fallback below handles the rest. Never fatal.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    engine = RemoraDecisionEngine()
    actions = build_actions()
    s = _make_style()
    g = _Glyphs(_unicode_ok())
    bullet_sep = " · " if _unicode_ok() else " / "
    rule = s.gray(g.rule * _WIDTH)

    inner = _WIDTH - 2

    def emit(text: str = "") -> None:
        print(text if _unicode_ok() else _ascii(text))

    # ── Banner ────────────────────────────────────────────────────────────
    emit()
    emit(s.cyan(g.tl + g.h * inner + g.tr))
    title = "REMORA " + bullet_sep.strip() + " Assurance Control Plane"
    sub = "Industrial Maintenance " + bullet_sep.strip() + " dry run"
    gap = max(3, inner - 4 - len(title) - len(sub))
    content = ("  " + title + " " * gap + sub + "  ")[:inner].ljust(inner)
    emit(s.cyan(g.v) + s.bold(content) + s.cyan(g.v))
    emit(s.cyan(g.bl + g.h * inner + g.br))
    emit()

    # ── Context ───────────────────────────────────────────────────────────
    def meta(label: str, value: str) -> None:
        emit(f"  {s.gray(label.ljust(10))}{value}")

    meta("Scenario", "RCA agent investigated abnormal vibration on pump P-3101A")
    meta("Delegated", s.dim(bullet_sep.join(DELEGATED_SCOPE)) + s.gray("   (A2A envelope, per-link signed)"))
    meta("Safety", "no live industrial system is contacted — " + s.bold("every decision below is real"))
    emit()

    # ── Proposed actions ──────────────────────────────────────────────────
    emit("  " + s.bold("PROPOSED ACTIONS") + s.gray("   agent -> A2A delegation -> RemoraDecisionEngine"))
    emit("  " + rule)
    for action in actions:
        report = engine.decide(action.observation)
        verdict = report.action.value.upper()
        glyph_attr, colour = _VERDICT_STYLE.get(verdict, ("dot", "dim"))
        glyph = getattr(g, glyph_attr)
        paint = getattr(s, colour)
        review = "human review" if report.human_review_required else "no review"
        badge = paint(f"{glyph} {verdict:8s}")
        emit(f"  {badge}  {s.bold(action.label)}"
              + s.gray(f"   [{review}]"))
        emit(f"             {s.dim(action.narrative)}")
        reason_codes = ", ".join(r.value for r in report.reasons)
        emit(f"             {s.gray('cap')} {action.capability}"
              + s.gray("   reasons ") + s.dim(reason_codes))
        if action.delegation_failures:
            emit(f"             {s.red(g.bad + ' delegation verify failed:')} "
                  + s.red(", ".join(action.delegation_failures)))
        emit()
    emit("  " + rule)

    # ── Interpretation ────────────────────────────────────────────────────
    emit("  " + s.bold("WHAT THIS PROVES"))
    for bullet in (
        "Low-consequence reads ACCEPT — governance adds no friction where none is needed.",
        "The work-order proposal routes to VERIFY via the production-write policy matrix:",
        "  a human approves before any business-system write. The agent recommends, it does not apply.",
        "Contradicting evidence turns the same proposal to ABSTAIN — resolve first, then ask a human.",
        "Direct OT actuation fails A2A scope verification (never delegated) -> forbidden-tool -> ESCALATE.",
        "  Analysis confidence cannot buy actuation authority.",
    ):
        lead = s.cyan("  " + g.dot) if not bullet.startswith("  ") else "   "
        emit(f"  {lead} {s.dim(bullet.strip())}")
    emit()

    # ── Adversarial checks ────────────────────────────────────────────────
    emit("  " + s.bold("ADVERSARIAL CHECKS") + s.gray("   one telemetry envelope, attacked two ways"))
    emit("  " + rule)
    telemetry_hash = canonical_tool_call_hash(
        name="read_telemetry",
        arguments={"asset": "P-3101A", "signal": "vibration", "window": "24h"},
        target="prod",
    )
    envelope = issue_envelope("telemetry:read", tool_call_hash=telemetry_hash)
    first = envelope.verify(
        signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE,
        link_keys=LINK_KEYS, expected_tool_call_hash=telemetry_hash,
        replay_guard=_replay_guard,
    )
    replayed = envelope.verify(
        signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE,
        link_keys=LINK_KEYS, expected_tool_call_hash=telemetry_hash,
        replay_guard=_replay_guard,
    )
    other_payload = canonical_tool_call_hash(
        name="read_telemetry",
        arguments={"asset": "P-9999Z", "signal": "vibration", "window": "24h"},
        target="prod",
    )
    rebound = envelope.verify(
        signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE,
        link_keys=LINK_KEYS, expected_tool_call_hash=other_payload,
    )

    def check(label: str, result, want_valid: bool) -> None:
        if result.valid == want_valid:
            mark, detail = (s.green(g.ok + " accepted") if result.valid
                            else s.green(g.ok + " rejected")), ""
        else:
            mark, detail = s.red(g.bad + " unexpected"), ""
        codes = "" if result.valid else s.dim("  " + ", ".join(result.failures))
        emit(f"  {mark}  {label.ljust(26)}{codes}{detail}")

    check("first use", first, True)
    check("replayed (same nonce)", replayed, False)
    check("different payload hash", rebound, False)
    emit("  " + rule)
    emit("  " + s.dim("One envelope authorises one payload, once."))
    emit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
