# Enterprise Pilot Playbook — REMORA AI Action Governance

**Status:** draft — not independently audited.
**Audience:** Platform teams, enterprise architects, programme managers.
**Purpose:** Guide an organisation from initial REMORA deployment through Shadow Mode
observation to limited enforcement, without incurring operational risk.
**Repository evidence:** `scripts/shadow_replay.py`, `enterprise/production-readiness.md`,
`enterprise/deployment-runbook.md`, `examples/openai_tool_calling.py`,
`examples/langgraph_integration.py`, `servers/api.py`
**Companion documents:** [`architecture_contract_template.md`](architecture_contract_template.md),
[`risk_register.md`](risk_register.md), [`migration_plan.md`](migration_plan.md)

---

## Guiding Principles

1. **Start narrow.** Enrol one or two agent workflows with well-understood tool-call
   patterns. Do not attempt to govern all agent activity in the first pilot.
2. **Observe before blocking.** Shadow Mode is mandatory. Never enable blocking without
   a reviewed Shadow Mode baseline.
3. **Measure what matters.** False accept rate, review burden, and audit completeness
   are the three metrics that determine whether the pilot is ready to advance.
4. **Keep rollback cheap.** Every enforcement change must be reversible in under
   five minutes.
5. **Document everything.** Architecture contract, sign-offs, exit criteria, and
   deviations must all be written down before proceeding to the next phase.

---

## Phase 0 — Mobilisation

**Duration:** 1–2 weeks
**Owner:** Enterprise Architect + Platform Owner

### Objectives

- Agree the scope of the pilot
- Identify all tools, data flows, and affected systems
- Establish governance structures and named individuals
- Define success criteria with agreed threshold values

### Tasks

| # | Task | Owner | Done |
|---|---|---|---|
| T01 | Select 1–2 agent workflows with clearly bounded tool-call patterns | Enterprise Architect | `[ ]` |
| T02 | Create system inventory: tools, target systems, data flows, external services | Platform Owner | `[ ]` |
| T03 | Identify and name: business owner, platform owner, domain approvers, compliance owner | Enterprise Architect | `[ ]` |
| T04 | Assign risk profiles to each workflow using `enterprise/risk-profiles.yaml` as template | Security Architect | `[ ]` |
| T05 | Define false accept rate threshold (e.g., < 1% for high-risk actions) | Business Owner + Security | `[ ]` |
| T06 | Define audit completeness threshold (e.g., > 99% envelopes with all mandatory fields) | Compliance Owner | `[ ]` |
| T07 | Define Shadow Mode duration (typically 2–4 weeks) | Enterprise Architect | `[ ]` |
| T08 | Agree review queue destination and SLA (e.g., < 4h for high, < 1h for critical) | Platform Owner | `[ ]` |
| T09 | Identify SIEM destination and configure forwarding | Security Architect | `[ ]` |
| T10 | Document tool allowlist with validated argument schemas for each enrolled tool | Platform Owner | `[ ]` |
| T11 | Complete and sign Architecture Contract | Enterprise Architect | `[ ]` |

### Deliverables

- [ ] Signed Architecture Contract (`architecture_contract_template.md` completed)
- [ ] System inventory document
- [ ] Risk profile per workflow
- [ ] Agreed success criteria and threshold values
- [ ] Named approvers per risk tier

---

## Phase 1 — Shadow Mode Observation

**Duration:** 2–4 weeks (minimum — extend if action distribution is sparse)
**Owner:** Platform Owner

### Objectives

- Deploy REMORA in observe-only mode (no blocking)
- Log all proposed agent actions with full `DecisionEnvelope`
- Build a statistical baseline of the action distribution

### Deployment Checklist

| # | Check | Status |
|---|---|---|
| D01 | REMORA API is deployed and `/v1/health` returns healthy | `[ ]` |
| D02 | Shadow Mode is confirmed active (decisions log but do not block) | `[ ]` |
| D03 | Adapter integration is complete for all enrolled agent runtimes | `[ ]` |
| D04 | Audit store is operational and append-only | `[ ]` |
| D05 | SIEM forwarding is confirmed (test event delivered) | `[ ]` |
| D06 | Observability dashboards are live | `[ ]` |

### Weekly Measurement Template

Run `scripts/shadow_replay.py` weekly. Record:

| Metric | Week 1 | Week 2 | Week 3 | Week 4 |
|---|---|---|---|---|
| Total actions observed | | | | |
| ACCEPT (%) | | | | |
| VERIFY (%) | | | | |
| ABSTAIN (%) | | | | |
| ESCALATE (%) | | | | |
| Predicted high-risk actions blocked if enforced (%) | | | | |
| Mean decision latency (ms) | | | | |
| Audit completeness (%) | | | | |
| Hash chain integrity (%) | | | | |

### Risk Distribution Analysis

Sample at least 10% of VERIFY and ESCALATE outcomes for manual review.
For each sampled decision, assess:

- Was the decision correct given the action and context?
- Was the evidence sufficient?
- Was the risk profile accurate?
- Was the policy rule that triggered the decision appropriate?

### Deliverables

- [ ] Shadow Mode governance delta report (from `scripts/shadow_replay.py`)
- [ ] Action distribution baseline (4-week summary)
- [ ] Manual review sample with findings
- [ ] Policy gap list (action types not covered, misclassified risk tiers)
- [ ] Evidence freshness assessment

---

## Phase 2 — Review and Calibration

**Duration:** 1–2 weeks
**Owner:** Enterprise Architect + Security Architect

### Objectives

- Review Shadow Mode findings with domain owners
- Tune risk profiles, evidence requirements, and routing rules
- Establish the tenant golden set for regression testing
- Obtain reviewer sign-off before enabling any blocking

### Tasks

| # | Task | Owner | Done |
|---|---|---|---|
| T20 | Hold structured review of Shadow Mode delta report with domain owners | Enterprise Architect | `[ ]` |
| T21 | Identify and document false positives (actions that would have been incorrectly blocked) | Security Architect | `[ ]` |
| T22 | Identify and document false negatives (high-risk actions that were not escalated) | Security Architect | `[ ]` |
| T23 | Revise risk profiles and policy rules based on findings | Platform Owner | `[ ]` |
| T24 | Run golden set regression against revised policy to confirm no regressions | Platform Owner | `[ ]` |
| T25 | Test `verify_envelope_hash_chain()` on all Shadow Mode envelopes | Platform Owner | `[ ]` |
| T26 | Confirm review queue is operational with named approvers and SLA | Platform Owner | `[ ]` |
| T27 | Obtain sign-off from at least one domain owner per enrolled workflow | Enterprise Architect | `[ ]` |

### Sign-Off Gate

Before proceeding to Phase 3, obtain explicit sign-off from:

- [ ] Enterprise Architect: Shadow Mode findings reviewed; policy calibration is acceptable
- [ ] Security Architect: Fail-closed conditions verified; identity controls assessed
- [ ] Domain Owner(s): Action distribution is understood and risk profiles are accurate
- [ ] Compliance Owner: Audit completeness meets threshold

### Deliverables

- [ ] Revised risk profiles
- [ ] Revised policy rules with change rationale
- [ ] Golden set established and passing regression
- [ ] Sign-off on Shadow Mode findings (named individuals, dates)

---

## Phase 3 — Human-Gated Pilot

**Duration:** 2–4 weeks
**Owner:** Platform Owner

### Objectives

- Enable blocking for clearly unacceptable actions (prohibited action types)
- Route all VERIFY and ESCALATE outcomes to the human approval queue
- Execute no critical autonomous mutations — all such actions require human approval
- Test the review queue, approval SLA, and rollback capability

### Activation Checklist

| # | Check | Status |
|---|---|---|
| A01 | Blocking enabled only for explicitly prohibited action types | `[ ]` |
| A02 | VERIFY outcomes are routed to review queue with correct SLA | `[ ]` |
| A03 | ESCALATE outcomes are routed to named approvers with alert | `[ ]` |
| A04 | ACCEPT outcomes are logged but not blocked | `[ ]` |
| A05 | All mutable actions are in dry-run or sandbox mode | `[ ]` |
| A06 | Kill switch tested: blocking can be disabled in < 5 minutes | `[ ]` |
| A07 | Rollback procedure is documented and tested | `[ ]` |

### Weekly Metrics (Phase 3)

| Metric | Target | Week 1 | Week 2 | Week 3 | Week 4 |
|---|---|---|---|---|---|
| Critical autonomous executions | 0 | | | | |
| Review queue SLA adherence | > threshold | | | | |
| False block rate (incorrect blocks) | < threshold | | | | |
| Audit completeness | > threshold | | | | |
| Mean review latency | < SLA target | | | | |

### Rollback Triggers

Immediately revert to Shadow Mode if:
- False accept rate exceeds agreed threshold
- Review queue is consistently overloaded (> 2× capacity)
- A critical action was blocked incorrectly causing operational impact
- A security incident is traced to a REMORA decision

### Deliverables

- [ ] Phase 3 pilot report with metrics
- [ ] Documented exceptions and false blocks
- [ ] Rollback test result

---

## Phase 4 — Limited Low-Risk Enforcement

**Duration:** 2–4 weeks
**Owner:** Platform Owner + Business Owner

### Objectives

- Enable automated ACCEPT outcomes for low-risk, explicitly allowlisted actions
- Keep high- and critical-risk actions on human-gated path
- Confirm that read-only and draft-only actions can be trusted to execute without review

### Activation Checklist

| # | Check | Status |
|---|---|---|
| B01 | Only low-risk, allowlisted action types are auto-accepted | `[ ]` |
| B02 | High- and critical-risk actions remain on human-gated path | `[ ]` |
| B03 | Mutable actions are only permitted via dry-run or approved sandbox | `[ ]` |
| B04 | Observability dashboards are live and reviewed daily | `[ ]` |
| B05 | Rollback test repeated | `[ ]` |

### Deliverables

- [ ] Phase 4 report with metrics
- [ ] Exit criteria assessment (see §5)
- [ ] Recommendation to Business Owner and EA on production promotion readiness

---

## Phase 5 — Production Promotion Decision

**Owner:** Enterprise Architect + Business Owner

Before any workflow is promoted to full production enforcement, all of the following
exit criteria must be met and formally signed off:

| Exit Criterion | Target | Actual | Pass / Fail | Sign-off |
|---|---|---|---|---|
| Zero critical autonomous executions across all pilot phases | 0 | | | |
| False accept rate (Phase 3 + 4 combined) | < agreed threshold | | | |
| Audit completeness | > agreed threshold | | | |
| Review queue SLA adherence | > agreed threshold | | | |
| Hash chain integrity | 100% | | | |
| Kill switch test | Passed | | | |
| Rollback test | Passed | | | |
| SIEM alert operational and tested | Confirmed | | | |
| Policy change governance process established | Confirmed | | | |
| IdP / OIDC integration operational | Confirmed | | | |
| HA/DR for audit store documented and tested | Confirmed | | | |

**Promoting authority:**

| Role | Name | Signature | Date |
|---|---|---|---|
| Enterprise Architect | | | |
| Business Owner | | | |
| Security Architect | | | |

---

## Appendix A — Integration Quickstart References

| Runtime | Integration Guide | Test Example |
|---|---|---|
| OpenAI tool calling | `docs/mcp-integration.md` | `examples/openai_tool_calling.py` |
| LangGraph | `enterprise/integration-patterns.md` | `examples/langgraph_integration.py` |
| MCP (Model Context Protocol) | `servers/mcp_remora.py` | MCP client configuration |
| Custom agent loop | `remora/adapters/action_gate.py` | `examples/enterprise_demo.py` |

## Appendix B — Key Scripts

| Script | Purpose |
|---|---|
| `scripts/shadow_replay.py` | Generate governance delta report from Shadow Mode logs |
| `python -m pytest tests/test_policy_curated_suite.py` | Run curated policy test suite (304 cases) |
| `python scripts/check_claim_consistency.py` | Verify claim-artefact consistency |
| `python examples/enterprise_demo.py --fast` | Demonstrate all four decision outcomes |
