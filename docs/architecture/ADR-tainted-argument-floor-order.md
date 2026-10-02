# ADR: Tainted arguments — severity-monotone floor order (WP-1 alternative A)

- Status: **accepted** (2026-10-02)
- Deciders: repository owner
- Extends: `docs/architecture/ADR-tainted-argument-approval.md` (option **a**, accepted 2026-08-20)
- Related: issue #40 (option **b**, open), `docs/13-research-frontier-roadmap.md` RF-02,
  `remora/policy/decision_engine.py` (`hard_guard_floor`),
  `tests/test_tainted_argument_approval_contract.py`,
  `SDD-REMORA-CONSOLIDATION-v1.md` WP-1

## Context

The taint branch of `hard_guard_floor()` has three rungs, evaluated last among the
unconditional guards:

1. Untrusted content controls a sensitive argument: ESCALATE
   (`UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT`), tier-independent.
2. Tainted at CRITICAL risk: ESCALATE (`TAINTED_ARGUMENT_ESCALATE`; issue #40 option
   (c), shipped in #94).
3. Tainted below CRITICAL: VERIFY floor (`TAINTED_ARGUMENT_VERIFY`).

Rung 3 returns early from the floor. When it fires, `decide()`'s later conditional
gates for the same observation never run. The two that matter are
rollback-unavailable and uncertain-state-transition: a HIGH-risk write with a tainted
argument and no rollback is routed VERIFY on the taint alone, and the
rollback condition is never recorded as a reason. The outcome (review) is the same as
the unconditional floor intends; what is lost is severity monotonicity in the reason
set and in any triage that reads it. This was recorded as POLICY-PRIORITY-TAINT in the
2026-10-02 review.

ADR-tainted-argument-approval settled a different question: below CRITICAL an approved
tainted call may execute with the taint standing (option (a)), because the re-gate
refuses only ESCALATE and a sanitiser would need per-value labels (RF-02). That
decision is about what review may redeem. This ADR is about what the floor reports
before review.

## Options

- Alt A (chosen): keep the three rungs, but before the rung-3 VERIFY return, apply
  the floor's own conditional severity signals. Tainted at HIGH risk with
  `rollback_available is False` or `state_transition_uncertain is True` routes to
  ESCALATE with the existing `TAINTED_ARGUMENT_ESCALATE` reason. All other
  below-critical tainted calls keep the VERIFY floor. No new reason code, no change to
  what review may redeem.
- Alt B: implement issue #40 option (b): sanitise and revalidate tainted arguments
  before approval is grantable. Rejected here for the reason ADR-tainted-argument-
  approval already gives: with a single caller-asserted taint bit there is nothing to
  revalidate against. Alt B is RF-02 work, not this ADR.

## Decision

**Alt A.** The floor's early VERIFY return is narrowed so that the two severity
conditions it was silently absorbing (no rollback, uncertain state) escalate rather
than verify when the taint is also present.

This is a routing change inside the safety floor, not a change to the floor's
blocking power: nothing that was ACCEPT becomes reachable, nothing that was blocked
becomes approvable. The direction of travel is strictly more conservative.

## Consequences

- `hard_guard_floor()` and the `explain()` trace change together; the
  decide/explain parity tests pin both.
- The pinned residual in `test_below_critical_an_approved_tainted_call_does_execute_unsanitised`
  is unchanged: it covers a HIGH-risk VERIFY whose only escalating factor is the
  taint, and that case still verifies and still executes on approval. Alt A does not
  close it; Alt B would.
- The pinned floor test `test_below_critical_the_taint_is_a_verify_floor_not_an_escalation`
  uses `rollback_available=True`, so it is unaffected. The new branches need new tests
  (HIGH + no rollback + taint, HIGH + uncertain state + taint), each asserting the
  ESCALATE and the reason.
- Behavioural change on the enforcing path, so it is merged alone (never in the same
  PR as the WP-3 config refactor), with a re-benchmark run on master after merge per
  `docs/assurance/rebenchmark_protocol_v1.md`, and a capability-register re-audit of
  the decision-engine capability in the same change.
- If RF-02 (per-value taint labels) ships, this ADR is revisited together with
  ADR-tainted-argument-approval, since the reason both rest on (nothing to revalidate
  against) is then gone.
