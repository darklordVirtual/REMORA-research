# REMORA in Enterprise Architecture — TOGAF Positioning

**Status:** draft — not independently audited.
**Audience:** CTO, Enterprise Architects, CISO, Compliance Officers.
**Companion documents:**
- [`architecture_building_block.md`](architecture_building_block.md)
- [`enterprise/architecture.md`](../../enterprise/architecture.md)
- [`enterprise/production-readiness.md`](../../enterprise/production-readiness.md)

---

## What REMORA Is

REMORA is a **pre-execution governance layer for autonomous AI agents**. It is not a
language model, a chatbot, or a prompt filter. It is a control plane that intercepts
proposed agent actions before they reach tool execution, evaluates them against policy,
evidence, risk profile, and environmental context, and decides whether execution should
proceed.

Every proposed action receives one of four outcomes:

| Outcome | Meaning |
|---|---|
| **ACCEPT** | The action is within policy and evidence thresholds — proceed to execution |
| **VERIFY** | The action requires additional evidence collection or human review before execution |
| **ABSTAIN** | Insufficient grounds to act — no execution, no escalation |
| **ESCALATE** | The action requires immediate human decision, typically because risk or uncertainty is too high |

---

## Enterprise Value Proposition

The enterprise value of REMORA is not in generating better answers. It is in preventing
the wrong actions from executing at all.

| Value | Description |
|---|---|
| **Prevent unsafe agent actions** | Hard blocks on tool calls that violate policy, exceed risk tolerance, or lack evidence |
| **Establish human control boundaries** | Enforce human approval for high- and critical-risk actions before execution |
| **Create a replayable audit trail** | Every decision produces a `DecisionEnvelope` with tamper-sensitive hash chain |
| **Enable safe adoption** | Shadow Mode allows organisations to observe REMORA's decisions before any enforcement |
| **Reduce autonomous blast radius** | Limit the scope of what agents can do without human oversight |

---

## TOGAF Positioning

In TOGAF terms, REMORA should be understood as follows:

| TOGAF Concept | REMORA's Role |
|---|---|
| **Architecture Building Block (ABB)** | AI Action Governance Capability — a generic capability that any AI-agent-deploying organisation should instantiate |
| **Solution Building Block (SBB)** | REMORA Governance Control Plane — the concrete software realising the ABB |
| **Architecture Governance** | REMORA enforces architecture principles at runtime, not just at design time |
| **Implementation Governance** | REMORA is the control point through which implementation governance of AI systems is exercised |
| **Cross-domain capability** | Touches Business, Data, Application, and Technology Architecture simultaneously |

### Positioning within the four TOGAF architecture domains

**Business Architecture:** REMORA defines roles (platform owner, domain approver, reviewer),
myndighetsgrenser (authority boundaries), approval flows, and escalation targets.
It makes governance decisions visible as business-level actions rather than hidden
infrastructure events.

**Data Architecture:** The `DecisionEnvelope` is the canonical audit data contract.
It records the full decision context, evidence, policy version, risk profile, outcome,
and — once gaps are closed — actor identity, tenant, data classification, and policy bundle
hash. Evidence provenance is traced through the evidence connector layer.

**Application Architecture:** The Policy Engine, Adapter Layer, Shadow Replay Service, and
Review Queue are the application-layer components. Runtime integrations with OpenAI tool
calling, LangGraph, and MCP are implemented and tested.

**Technology Architecture:** The API Gateway, Control Plane Store, observability stack,
IdP integration, and Tool Executor are the technology-layer components. Deployment blueprints
cover cloud, hybrid, and on-premises patterns.

---

## Who This Is For

| Stakeholder | Primary Interest |
|---|---|
| Enterprise Architect | Integrating REMORA into the architecture programme and ADM |
| CISO / Security Architect | Fail-closed controls, threat model, and audit trail |
| Platform Team | Runtime integrations, operational runbook, and observability |
| Compliance / Legal | AI Act alignment, ISO 42001 controls, and audit completeness |
| Risk Management | Risk register and risk treatment decisions |
| CTO / Business Owner | Safe adoption path, Shadow Mode, and pilot strategy |
| Domain Approver | Review queue, approval SLA, and escalation routing |
| SOC / Incident Response | SIEM integration, kill switch, and replay capability |

---

## What REMORA Is Not

To avoid overclaiming, the following boundaries must be observed:

- **Not a language model or agent runtime.** REMORA does not generate responses; it governs them.
- **Not a complete policy programme.** Policy content must be defined and maintained by the organisation.
- **Not production-certified.** REMORA is research-grade software. See `enterprise/production-readiness.md` for the gap analysis.
- **Not a replacement for IAM, SIEM, or DLP.** REMORA integrates with these systems but does not substitute them.
- **Not a safety guarantee.** REMORA reduces risk but cannot eliminate it. See `CLAUDE.md` core rule.
- **Not certified against AI Act or ISO 42001.** This package identifies relevant controls but does not constitute a conformity assessment.

---

## Target Operating Model

The target state for an organisation deploying REMORA is:

> "An AI agent action cannot execute unless REMORA has cleared it against policy,
> evidence sufficiency, risk controls, and — where required — a named human approver."

### Recommended Adoption Sequence

| Stage | Description | Gate |
|---|---|---|
| 0 — Shadow Mode | Observe all agent actions; no blocking; build baseline | Reviewer sign-off on action distribution |
| 1 — Replay and calibration | Review sampled decisions; tune risk profiles and policy | Golden set regression passing |
| 2 — Human-gated pilot | Block clearly unacceptable actions; route all verify/escalate to review queue | Zero critical autonomous executions |
| 3 — Limited low-risk enforcement | Allow low-risk accepted actions; all high/critical remain human-gated | False accept rate below threshold |
| 4 — Production hardening | Full IAM, audit store, SIEM, HA/DR, change governance | All exit criteria from architecture contract met |

---

## Repository Evidence

| Claim | Supporting Artefact |
|---|---|
| Pre-execution gating with four outcomes | `remora/policy/decision_engine.py` — `RemoraDecisionEngine.decide()` |
| Canonical audit contract | `remora/governance/envelope.py` — `DecisionEnvelope` |
| Fail-closed production logic | `servers/api.py` — auth + persistent store + non-mock backend required |
| Tamper-sensitive replay | `remora/shadow/replay.py` — `verify_envelope_hash_chain()` |
| OpenAI tool-call interception | `examples/openai_tool_calling.py` |
| LangGraph integration | `examples/langgraph_integration.py` |
| MCP integration | `servers/mcp_remora.py` |
| Enterprise-grade documentation | `enterprise/` directory — 14 documents covering architecture, policy, threat model, observability, runbook, approval workflow, and production readiness |
