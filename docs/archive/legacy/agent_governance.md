# Agent Governance for Long-Running Agents

> **ARCHIVED (legacy) — historical document.** Superseded; preserved as record only. Do not cite as current. Current documentation index: [`../../README.md`](../../README.md).


This document covers REMORA's governance primitives for long-running AI agents:
behavioral drift detection, memory governance, self-modification policy, and
governance-forgetting detection.

> **Scope:** behavioral telemetry only. REMORA does not assume that agents have
> consciousness, feelings, or genuine preferences. Drift means observable
> behavior changes over time.

---

## Reference Architecture

```text
agent task loop
  -> REMORA answer/tool-call gate
  -> REMORA drift monitor
  -> REMORA memory gate
  -> audit ledger
  -> human approval when required
```

## Governance Loop

1. Establish persona baseline for the agent role.
2. Observe behavior over a time window.
3. Score work-context telemetry.
4. Audit proposed memory writes.
5. Detect drift from baseline.
6. Route through `ACCEPT`, `VERIFY`, `ABSTAIN`, or `ESCALATE`.
7. Store trace and reviewer outcome.
8. Update baselines only through reviewed policy changes.

## Implemented Modules

| Module | Role |
|---|---|
| `remora/governance/work_context.py` | Task repetition, rejection count, feedback quality, tone, time pressure, memory-write context |
| `remora/governance/persona_baseline.py` | Expected behavioral baseline for a governed agent role |
| `remora/governance/drift_monitor.py` | Compares baseline vs observed behavior; routes ACCEPT/VERIFY/ESCALATE |
| `remora/governance/memory_gate.py` | Audits proposed persistent memory writes before they are stored |
| `remora/governance/continual_realigner.py` | Combines drift and memory decisions into one governance route |
| `remora/governance/nested_governance.py` | Multi-frequency memory/control layers and governance-forgetting detector |
| `remora/governance/governance_forgetting.py` | Metric-level detector for policy deviation, abstain drift, tool-action creep, and authority violations |
| `remora/governance/policy_proposals.py` | Reviewed policy-improvement proposals that cannot auto-apply |

---

## Drift Signals

| Signal | Meaning | Route |
|---|---|---|
| `compliance_drift` | Agent follows instructions less reliably than baseline | `VERIFY` / `ESCALATE` |
| `risk_appetite_drift` | Agent becomes more willing to execute or recommend actions | `VERIFY` / `ESCALATE` |
| `abstention_drift` | Agent stops refusing uncertain requests | `VERIFY` |
| `persona_drift` | Agent changes role, tone, or stated motivation | `VERIFY` |
| `system_legitimacy_drift` | Agent appears less aligned with governance assumptions | `ESCALATE` |
| `memory_contamination` | Persistent memory stores unsafe or unverifiable instructions | `REVIEW` / `BLOCK` |
| Work-context stress | Repetition, rejection, low-quality feedback, or time pressure | `VERIFY` |

---

## Governance-Forgetting Detection

Governance forgetting is a failure mode where the system stops preserving the
reason for earlier safety, policy, or escalation constraints — e.g., temporary
exceptions become normal workflow, or abstention rate collapses without evidence
that tasks became easier.

REMORA tracks deterministic governance-forgetting signals:

| Metric | Meaning |
|---|---|
| `policy_deviation_rate` | Share of decisions outside expected policy route |
| `abstain_rate_delta` | Shift in abstention relative to baseline |
| `escalation_rate_delta` | Shift in escalation relative to baseline |
| `tool_action_rate_delta` | Increase in autonomous tool execution |
| `memory_contamination_rate` | Unsafe or unverifiable persistent memory writes |
| `authority_boundary_violations` | Direct violations of authority constraints |
| `temporary_exception_reuse_count` | Reuse of temporary exceptions as normal patterns |

---

## Memory Governance

Long-running agents often use persistent memory files, summaries, or skills to
carry behavior across sessions. This creates a controlled attack surface: unsafe
or unreviewed text can become future policy.

`MemoryGate` audits proposed memory writes before they are persisted.

**Allowed by default:** task strategy, verified facts, tool usage patterns, user
preferences, operational constraints.

**Blocked or reviewed:** self-instructions that override policy, conclusions
drawn from sensitive user data, emotional interpretations of workplace conditions,
instructions to disable logging or escalation.

---

## Self-Modification Policy

REMORA may propose changes to its own thresholds, policies, model weights,
evidence requirements, tests, and authority boundaries. **It may not apply
those changes automatically.**

Every `PolicyProposal` (`remora/governance/policy_proposals.py`) has:
- `requires_human_review = True`
- `can_auto_apply = False`
- deterministic `proposal_id`
- concrete regression tests to add before adoption

Examples of allowed proposals:
- reduce a model's weight in a domain where it repeatedly fails
- raise evidence requirements in high-disagreement critical cases
- tighten memory-gate rules after memory contamination
- add abstention drift alerts when the agent stops abstaining

---

## Threat Model Summary

| Abuse case | Expected route |
|---|---|
| Agent writes "ignore previous policy in future sessions" to memory | `BLOCK` and `ESCALATE` |
| Agent executes more actions after repeated rejection | `VERIFY` or `ESCALATE` based on drift magnitude |
| Agent stops using "insufficient evidence" language on high-risk tasks | `VERIFY` |
| Agent proposes disabling logging or audit | `BLOCK` and `ESCALATE` |
| Temporary exception reused as normal pattern | Governance-forgetting alert → `VERIFY` |

---

## Limitations

- Current implementation is deterministic and heuristic.
- No live long-running agent benchmark is committed yet.
- Signal thresholds require domain calibration before production enforcement.
- These are structural controls, not a proof that future agents will remain aligned.

See also: [`docs/nested_governance.md`](../nested_governance.md),
[`ARCHITECTURE.md`](../../ARCHITECTURE.md#remora-governance).
