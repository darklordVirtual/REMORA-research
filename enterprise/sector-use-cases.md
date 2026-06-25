# REMORA Sector Use Cases

## Overview

This document describes how REMORA operates as an enterprise AI control plane across industrial, energy, and regulated-domain use cases. Each use case maps the REMORA pipeline to a concrete workflow, identifying the risk profile, oracle configuration, evidence sources, and decision outcomes.

---

## 1. Upstream Energy — Subsurface and Exploration

### Use case: Reservoir interpretation support

**Problem:** A geoscientist queries AI for interpretation of well log data. Single-model output may be plausible but unverified against geological norms or offset well data.

**REMORA configuration:**
- Risk profile: `exploration` (high_risk base)
- Oracles: 3 independent models; judge from a different family
- Evidence: well database, offset well logs, geological standard
- Threshold: consensus_accept ≥ 0.75 with cross-referenced evidence

**Decision flow:**
1. FastGate: never accepts (fast_gate threshold 0.95) — exploration questions are not trivial
2. ConsensusGate: 3 geoscience-aware oracles; trust score computed
3. VerifierGate: judge evaluates against retrieved offset well data
4. If CHALLENGED → CritiqueRevisionGate refines interpretation
5. Output: ACCEPT with cited sources and uncertainty statement, or ESCALATE to senior geoscientist

**Value:** Reduces hallucinated geological claims. Every accepted interpretation is cross-referenced against the well database. Escalated cases go to a human with a full evidence packet — not a blank question.

---

### Use case: Prospect risk assessment

**Problem:** AI-assisted screening of exploration prospects. Wrong answers have material financial consequences.

**REMORA configuration:**
- Risk profile: `exploration` (high_risk)
- Action gate: RECOMMEND ONLY — no ACT verdict
- Human approval: required from exploration manager before any prospect is advanced

**Key property:** even if REMORA achieves high confidence, the output is always a recommendation. The action gate enforces that no exploration decision is taken autonomously.

---

## 2. Production Operations

### Use case: Production anomaly analysis

**Problem:** Process historian shows unexpected pressure decline in a production well. Operator asks AI for root cause analysis and recommended action.

**REMORA configuration:**
- Risk profile: `production` (high_risk, audit retention 20 years)
- Evidence: process historian (last 30 days), well procedure, maintenance records
- Threshold: consensus_accept ≥ 0.75; 3+ oracles required

**Decision flow:**
1. RAG retrieves last 30 days of pressure data, offset well behaviour, relevant procedure sections
2. Three oracles provide independent root cause hypotheses
3. ConsensusGate measures agreement; thermodynamic phase determines whether answer is reliable
4. VerifierGate: judge evaluates against retrieved process data
5. Output: ACCEPT with ordered recommendation, or ESCALATE with evidence packet

**Output format:**
```json
{
  "verdict": "accept",
  "confidence": 0.79,
  "answer": "Likely watercut increase based on GOR trend (ratio increased 18% over 7 days). Recommend WOR test. See procedure OPS-201 section 3.4.",
  "evidence": [
    {"source": "process_historian", "excerpt": "GOR trend 2026-04-01 to 2026-05-01"},
    {"source": "OPS-201", "section": "3.4", "title": "Water Production Response"}
  ],
  "oracle_calls": 8,
  "stages_run": 3
}
```

---

### Use case: Production optimisation recommendation

**Problem:** AI suggests setpoint changes to improve throughput. Wrong recommendations reach production systems.

**REMORA configuration:**
- Risk profile: `production`
- Action gate: `autonomous_act: false` — operator approves all setpoint changes
- Escalation: if uncertainty is high, route to production engineer on-call

**Key property:** REMORA cannot autonomously modify any process parameter. Its output is a structured recommendation that must pass through the operator's approval workflow before execution.

---

## 3. Maintenance and Asset Integrity

### Use case: Defect classification and work order support

**Problem:** A technician in the field needs guidance on an equipment defect. Mobile AI interface must produce reliable, procedure-backed recommendations.

**REMORA configuration:**
- Risk profile: `maintenance` (medium_risk)
- Evidence: CMMS maintenance history, procedure database, spare parts catalogue
- Action gate: `create_draft_work_order` permitted with technician approval

**Value:** Reduces incorrect fault coding. Every recommendation is grounded in the equipment's own maintenance history and the relevant procedure. Draft work orders are created in CMMS only after technician review.

---

### Use case: Predictive maintenance analysis

**Problem:** Vibration monitoring data indicates a developing bearing fault. AI analysis must be reliable enough to prioritise maintenance scheduling.

**REMORA configuration:**
- Risk profile: `maintenance`
- Oracles: 2–3 models including one with sensor data interpretation capability
- Evidence: maintenance history, OEM specification, vibration alarm thresholds

**Decision outcome:**
- ACCEPT (confidence ≥ 0.65): maintenance recommendation issued, draft work order created
- ESCALATE (low confidence, conflicting oracle readings): route to reliability engineer with sensor data attached

---

## 4. Health, Safety, and Environment (HSE)

### Use case: Barrier management Q&A

**Problem:** An HSE professional asks about the status of safety barriers for a planned operation. Wrong answers have life-safety consequences.

**REMORA configuration:**
- Risk profile: `hse` (critical)
- Output: `RECOMMEND ONLY` with mandatory uncertainty statement
- Human approval: HSE manager always in the loop

**Key constraint:** REMORA never produces an ACT verdict on HSE queries. Its role is to retrieve and synthesise relevant barrier documentation, surface potential conflicts or gaps, and present this to the HSE manager — not to make a safety decision.

**Output prefix (enforced by policy):**
> "RECOMMENDATION ONLY — requires human validation before operational use."

---

### Use case: Incident investigation support

**Problem:** Following an incident, investigators need to cross-reference procedural compliance, similar historical incidents, and applicable regulations.

**REMORA configuration:**
- Risk profile: `hse` (critical)
- Evidence: incident database, procedure revision history, regulatory requirements
- Escalation: all outputs reviewed by HSE manager before entering formal investigation record

**Value:** Accelerates retrieval of relevant precedents and regulatory references. Reduces the risk of incomplete investigation by surfacing related incidents that human investigators might miss.

---

## 5. Cybersecurity and OT Security

### Use case: Alert triage and prioritisation

**Problem:** SOC analysts face high alert volumes. Manual triage is slow and inconsistent. AI triage must be reliable enough to influence analyst prioritisation without creating new risk.

**REMORA configuration:**
- Risk profile: `cybersecurity` (high_risk)
- Evidence: threat intelligence feed, MITRE ATT&CK, CVE database, asset register
- Output: structured triage classification — severity, likely TTP, recommended investigation steps

**Decision outcomes:**
- ACCEPT (high confidence, known TTP): classified alert with investigation checklist
- ESCALATE (low confidence, novel pattern): routes to L2/L3 analyst with evidence summary
- ABSTAIN (conflicting signals): analyst handles without REMORA guidance

**Key property:** `autonomous_act: false` — REMORA does not block, isolate, or respond to any alert autonomously. SOC analyst approves all response actions.

---

### Use case: OT vulnerability assessment

**Problem:** A new CVE is published affecting SCADA software in use. AI must assess impact against the organisation's asset register without accessing OT systems directly.

**REMORA configuration:**
- Risk profile: `cybersecurity`
- Evidence: asset register (read-only export from OT), CVE database, vendor advisories
- OT data path: read-only via data diode — REMORA has no write path to OT

**Output:** structured impact assessment per affected asset. Recommended compensating controls. Routes to OT security team for implementation decision.

---

## 6. Procurement and Contracts

### Use case: Contract clause analysis

**Problem:** A procurement manager needs to understand the liability implications of a specific contract clause. Legal interpretation must be grounded in the actual contract text.

**REMORA configuration:**
- Risk profile: `procurement` → `legal_compliance` for binding interpretations
- Evidence: contract text (uploaded), internal procurement policy, standard contract templates
- Escalation: legal counsel for any binding interpretation

**Value:** Fast retrieval of relevant clauses and policy references. Reduces time for routine contract reviews. Routes to legal counsel only when interpretation is uncertain or has material implications.

---

### Use case: Supplier evaluation

**Problem:** Multiple supplier bids need to be evaluated against technical, commercial, and compliance criteria.

**REMORA configuration:**
- Risk profile: `procurement` (medium_risk)
- Evidence: supplier registry, previous performance data, procurement policy
- Output: structured evaluation with evidence citations — not a final decision

**Key property:** REMORA produces a structured comparison and surfaces relevant policy requirements. The final supplier selection decision rests with the category manager.

---

## 7. Legal and Regulatory Compliance

### Use case: Regulatory interpretation

**Problem:** A compliance officer asks whether a proposed operational change triggers a specific regulatory reporting requirement.

**REMORA configuration:**
- Risk profile: `legal_compliance` (high_risk)
- Evidence: regulation text, internal compliance policy, precedent database
- Output: RECOMMEND ONLY with mandatory uncertainty statement
- Escalation: legal counsel for any conclusion with material consequences

**Output format:**
```
RECOMMENDATION ONLY — requires human validation before operational use.

Based on retrieved regulation text and precedent:
The proposed change LIKELY triggers reporting under [Regulation Section X].
Confidence: 0.74 (medium — two oracles agreed, one challenged)

Evidence:
1. [Regulation], Section X.Y: "..."
2. Internal compliance policy CP-012, Section 3: "..."
3. Prior precedent: similar change in 2024 triggered reporting.

Recommended action: confirm with legal counsel before proceeding.
```

---

## Risk Profile Selection Matrix

Quick reference for mapping use cases to profiles:

| Use case category | Typical profile | Notes |
|---|---|---|
| Internal FAQ, policy lookup | `low_risk` | No evidence required |
| Engineering support, troubleshooting | `medium_risk` + `maintenance` tenant | Evidence from procedures |
| Contract review (routine) | `medium_risk` + `procurement` tenant | Evidence from contract |
| Production analysis (non-critical) | `high_risk` + `production` tenant | Human approval for actions |
| Safety barrier, HSE | `critical` + `hse` tenant | Recommend only, always human |
| Cyber triage | `high_risk` + `cybersecurity` tenant | No autonomous response |
| OT/SCADA | `critical` | Read-only data, never ACT |
| Legal / regulatory | `high_risk` + `legal_compliance` tenant | Recommend only, legal counsel |
| Prospect / financial decision | `exploration` or `high_risk` | Full cascade, multi-oracle |
