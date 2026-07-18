# Partition and Stale-Approval Resilience Plan (v1)

**Status:** IMPLEMENTED (2026-07-18) — REM-032 and REM-033 are DONE in
[`remediation_register.yaml`](remediation_register.yaml). Implementation:
`remora/governance/degradation.py` (ladder + tamper-evident transition log),
`remora/governance/review_queue.py` (queue TTL, mandatory-expiry approvals,
execution-time re-gate), `scripts/remora_hook.py`
(`REMORA_HOOK_PROFILE=production` refuses above-LOW actions under G4).
Tests: `tests/test_degradation_ladder.py`, `tests/test_review_queue.py`,
`tests/test_hook_production_profile.py`. This document remains the design
rationale; on any discrepancy the code + tests win.
**Date:** 2026-07-18

Two failure classes this plan covers, both raised in internal review:

1. **Communication failure (partition):** any link in the governance chain
   becomes unreachable — what may still execute, and what must stop?
2. **Stale approvals:** a VERIFY/ESCALATE decision is approved by a human,
   but the world changed between decision time and execution time — when is
   the approval still valid?

The governing principle for both is the one the engine already enforces
everywhere else: **absence of information degrades toward review or refusal,
never toward execution, and every degradation is recorded** (the canonical
mode-degradation rule, [`../01-architecture.md`](../01-architecture.md)).

---

## 1. Partition behavior — link-by-link matrix

| Link | Behavior today | Status |
|---|---|---|
| PDP → OPA daemon | Fail-closed by tier: unreachable OPA on high/critical → VERIFY/ESCALATE with `fallback_used` recorded; otherwise Python-engine fallback. Malformed responses route the same way. `remora/policy/opa_adapter.py` | **Implemented** |
| PDP → oracle pool | Quorum gate: consultation attempted but < 2 valid votes → VERIFY (`INSUFFICIENT_ORACLE_VOTES`). `remora/policy/decision_engine.py` | **Implemented** |
| PDP → PEP (token) | Signed token; expiry (when set) is inside the signed payload; enforcement gate recomputes the observation hash and refuses on mismatch, tamper, or expiry. `remora/enforcement/` | **Implemented** (expiry optional — see §3) |
| A2A counterparty | Envelope expiry, clock-skew bounds, nonce replay guard, fail-closed verification. `remora/governance/a2a_envelope.py` | **Implemented** |
| Agent hook → control plane | `REMORA_HOOK_PROFILE=production` refuses every above-LOW action when the control plane is unreachable (G4) and implies fail-closed error paths; the research default keeps the documented fail-open local behavior. `scripts/remora_hook.py`, `tests/test_hook_production_profile.py` | **Implemented (REM-032)** |
| Control plane → human review channel | Queue TTL: unattended VERIFY/ESCALATE items resolve to ABSTAIN with a recorded `review_expired_to_abstain` event. `remora/governance/review_queue.py` | **Implemented (REM-032)** |
| Control plane → AROMER telemetry | Engine operates on REMORA defaults when telemetry is absent (advisory-only by design); the outage is now recordable as a G1 transition via `DegradationRecorder`. | **Implemented (REM-032)** |

## 2. Required behavior: the degradation ladder (REM-032)

Five recorded modes. Transitions in either direction MUST emit a degradation
event into the audit chain (mode, cause, timestamp, affected links) — this
operationalizes the existing mode-degradation rule, which today is stated but
has no dedicated recorder.

| Mode | Trigger | What still executes |
|---|---|---|
| G0 Full governance | all links up | Normal ACCEPT/VERIFY/ABSTAIN/ESCALATE |
| G1 No learning | AROMER/telemetry unreachable | Everything — engine defaults; adapted thresholds frozen at last-known-good; event recorded |
| G2 No external PDP | OPA unreachable/malformed | Python engine authoritative (already implemented per-call; G2 adds the recorded mode transition when outage persists) |
| G3 No oracle pool | quorum unreachable | Hard blocks + risk-tier floors only; every consensus-dependent path → VERIFY |
| G4 Control plane unreachable | hook cannot reach PDP | **Read-only actions:** configurable, default allow-with-warning. **Mutating/production actions: refuse (fail closed).** The current hook default (fail-open for everything) is the documented research-mode exception and must be explicit opt-out in any deployment |

Review-channel outage (orthogonal to G-modes): pending VERIFY/ESCALATE items
MUST carry a queue TTL. On TTL expiry without human contact the item resolves
to **ABSTAIN with a recorded expiry event** — never to auto-accept, and never
to indefinite silent pending.

## 3. Stale approvals: the approval freshness contract (REM-033)

An approval is a claim about the world at decision time. Three mechanisms
make it safe to act on later — the first exists, the other two are the plan:

**3a. Payload binding — implemented.** The decision is bound to
`canonical_tool_call_hash` (name, full arguments, tenant, target) and to the
observation hash; the enforcement gate recomputes both immediately before
execution and refuses on any mismatch. If the tool call's *values changed*
after approval, the approval is already void by construction.
(`remora/policy/observation.py`, `remora/enforcement/gate.py`.)

**3b. Mandatory expiry — partial, to be tightened.** `PolicyDecisionToken`
supports signed `expires_at`, but legacy no-expiry tokens are still accepted
(recorded as audit finding F-2). REM-033 makes expiry mandatory for VERIFY
and ESCALATE approvals: recommended default TTL 15 minutes for production
writes, 24 h ceiling for anything. An expired approval returns the item to
the review queue; it never silently re-executes.

**3c. Re-gate at execution — the missing piece.** Identical arguments do not
imply an unchanged world: occupancy changed, telemetry crossed a threshold,
evidence was contradicted while the item sat in the queue. Required
execution-time semantics:

```
on execute(approved_item):
    fresh_obs   = rebuild observation from current signals
    fresh       = engine.decide(fresh_obs)
    if severity(fresh.action) <= severity(approved_action):
        execute            # world got no riskier — approval stands
    else:
        void approval      # recorded as approval_invalidated event
        route fresh.action # stricter fresh decision wins, back to queue
```

This is decision monotonicity applied over time: an approval can survive a
world that stayed equal or got safer, and can never override a world that
got riskier. The comparison uses the same severity order the OPA floor uses
(ACCEPT < VERIFY < ABSTAIN < ESCALATE).

Invalidation while pending (no polling required at approval time): any
change to the underlying observation hash voids the approval via 3a; 3c
catches world-state drift that the observation inputs only reveal when
re-collected.

## 4. Explicitly out of scope for v1

- Multi-region control-plane replication and consensus (infrastructure, not
  governance semantics).
- Offline-token schemes for extended G4 operation — under G4, mutating
  actions stop; that is the point.
- Automatic retry/backoff tuning (deployment concern; the semantics above
  are retry-invariant).

## 5. Register entries

| Item | Scope | Acceptance |
|---|---|---|
| REM-032 | Degradation ladder G0–G4: recorder emitting audit-chain events on mode transitions; hook production profile (fail-closed for mutating/production under G4); review-queue TTL → ABSTAIN with recorded expiry | Simulated partition tests per link; degradation events present in audit chain; hook test proving mutating actions refuse when control plane is unreachable in production profile |
| REM-033 | Approval freshness: mandatory `expires_at` on VERIFY/ESCALATE approvals (close audit F-2); execution-time re-gate with monotone severity comparison; `approval_invalidated` audit events | Tests: expired approval → queue; fresh-stricter → void + recorded; fresh-equal-or-safer → executes; argument change → refused by existing hash binding |

Both items are DONE (2026-07-18) — implemented with the acceptance criteria
above as tests. Deployment wiring (which process hosts the recorder and the
queue, and where the JSONL event exports land) remains a deployment concern;
the semantics are fixed here and pinned by the test suites.
