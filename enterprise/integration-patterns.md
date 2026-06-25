# REMORA Enterprise Integration Patterns

## Design principle

REMORA does not own the enterprise data or process stack. It orchestrates trust between the systems that do. Every integration follows the same pattern: REMORA receives a query, routes it through the appropriate evidence and oracle pipeline, and returns a governed decision. The source system acts on the decision — REMORA does not reach into systems unless an explicit action gate has been configured.

---

## Integration Map

| System type | REMORA function | Integration pattern |
|---|---|---|
| Identity / IAM (Azure Entra ID, Okta) | Tenant routing, user role, access control | JWT / OIDC token forwarded to gateway; role extracted for policy evaluation |
| Workflow / ITSM (ServiceNow, Jira) | Escalation routing, human approval, work order creation | Outbound webhook or API call on ESCALATE verdict; ticket ID stored in escalation log |
| Data platform (Databricks, Cognite CDF) | Industrial context, sensor data, operational telemetry | RAG oracle queries data platform APIs; streamed into evidence layer |
| Document management (SharePoint, Confluence) | Procedures, policies, engineering standards | Indexed into vector store (Cloudflare Vectorize / pgvector); queried by RAG oracle |
| SIEM / SOC (Splunk, Microsoft Sentinel) | Cyber event context, threat indicators | SIEM events ingested as evidence; REMORA verdict feeds back as enrichment |
| CMMS / EAM (SAP PM, IBM Maximo) | Asset data, maintenance history, work orders | Oracle queries CMMS API via RAG layer; draft work orders submitted on ACT verdict with human approval |
| OT / SCADA | Operational parameters, process state | Read-only: process data ingested as evidence. No write path without critical-tier action gate + human approval |
| Observability (Grafana, Prometheus) | Telemetry, SLO tracking, drift detection | OpenTelemetry spans exported per decision; telemetry_daily table drives Grafana dashboards |
| Vector / semantic search | Evidence retrieval | Cloudflare Vectorize (in use), pgvector, Qdrant, Weaviate |
| Secret management (HashiCorp Vault, AWS KMS) | Oracle API keys, tenant credentials | Secrets never stored in REMORA config; resolved at runtime from vault |

---

## Pattern 1: Document Q&A (SharePoint / Confluence)

**Use case:** an engineer asks a question that should be answered from procedure documents or engineering standards.

```
Engineer (chat / API)
       │
       ▼
REMORA Gateway
  - tenant: maintenance
  - risk_profile: medium_risk
       │
       ▼
RAG Oracle (Cloudflare Worker)
  - queries Vectorize index of procedure documents
  - retrieves top-k relevant passages
       │
       ▼
ConsensusGate (3 oracles)
  - answer synthesised with retrieved passages as context
       │
       ▼
VerifierGate (LLM judge)
  - verifies answer against retrieved evidence
       │
       ▼
Decision: ACCEPT with source citations
  - response includes: answer, confidence, sources (doc name, section, page)
```

**Integration point:** SharePoint / Confluence content is indexed by the `scripts/ingest_corpus.py` pipeline into Cloudflare Vectorize. Re-indexing runs on a scheduled job triggered by document change events.

---

## Pattern 2: Escalation to ServiceNow

**Use case:** a high-risk question (production anomaly, safety concern) cannot be resolved by REMORA with sufficient confidence.

```
Operations system / agent
       │ POST /ask
       ▼
REMORA Gateway
  - tenant: production
  - risk_profile: high_risk
       │
       ▼
Cascade pipeline → ESCALATE verdict
  - reason: trust_score < 0.20 (disordered phase)
  - best_answer: partial answer with low confidence
  - evidence: 2 retrieved procedure excerpts
       │
       ▼
Escalation handler
  - creates ServiceNow incident via REST API
  - payload: question, best_answer, confidence, evidence, policy_trace
  - ticket_id stored in remora_escalations.external_ticket_id
       │
       ▼
ServiceNow routes to on-call production engineer
       │
       ▼
Engineer resolves → resolution POSTed back to REMORA
  - remora_escalations.status = RESOLVED
  - resolution stored in remora_feedback for eval harness
```

**Integration point:** the ServiceNow integration is a configurable outbound webhook. Target URL, authentication, and field mapping are configured per tenant in `enterprise/risk-profiles.yaml` under `action.approval_routing`.

---

## Pattern 3: Cyber Incident Triage (SIEM)

**Use case:** a SIEM alert fires. An automated pipeline submits the event to REMORA for triage classification before SOC analyst review.

```
SIEM (Splunk / Sentinel)
  - alert: unusual outbound connection from engineering workstation
       │ POST /ask  (structured alert as question)
       ▼
REMORA Gateway
  - tenant: cybersecurity
  - risk_profile: high_risk
       │
       ▼
RAG Oracle
  - queries threat intelligence feed (CVE, MITRE ATT&CK)
  - retrieves relevant TTPs and indicators
       │
       ▼
Cascade pipeline
  - multi-oracle analysis: classification, severity, likely campaign
       │
       ▼
Decision: ESCALATE
  - structured output: classification=SUSPICIOUS, severity=HIGH
  - matched_ttp: T1071.001 (Application Layer Protocol: Web Protocols)
  - evidence: 3 threat intel sources
  - recommended_action: isolate host, review proxy logs
  - note: RECOMMEND ONLY — SOC analyst must approve any response action
       │
       ▼
Alert enriched in SIEM with REMORA verdict
SOC analyst queue updated with pre-analysed triage
```

**Critical constraint:** no REMORA verdict triggers any network action autonomously. The `cybersecurity` tenant profile has `autonomous_act: false` and `require_human_approval: true` for all action-class decisions.

---

## Pattern 4: Maintenance Work Order (CMMS / SAP)

**Use case:** a technician asks REMORA for guidance on a reported equipment defect. REMORA returns a recommendation and optionally creates a draft work order.

```
Technician (mobile app / chat)
  "Pump P-201 showing high vibration alarm, 12.3 mm/s"
       │
       ▼
REMORA Gateway
  - tenant: maintenance
  - risk_profile: medium_risk
       │
       ▼
RAG Oracle
  - queries CMMS maintenance history for P-201
  - queries procedure database for vibration diagnosis
       │
       ▼
Cascade pipeline → ACCEPT (confidence 0.81)
  - answer: "High vibration likely bearing wear. Check lubrication
    first. If >18 mm/s or persistent, initiate bearing replacement
    per procedure MNT-044."
  - evidence: last 3 maintenance records for P-201, MNT-044 section 4.2
       │
       ▼
Action gate (approved tool: create_draft_work_order)
  - draft created in SAP PM with:
    equipment: P-201, fault_code: VIB-HIGH, recommended_action: CHECK_LUBRICATION
    status: DRAFT — not submitted
       │
       ▼
Technician reviews draft in mobile app
Technician approves → work order submitted to SAP
```

**Integration point:** SAP PM integration uses the SAP REST API (S/4HANA OData). Draft work orders are created with status `TECO` (technically complete but not released) until technician approval. REMORA stores the SAP object number in `remora_action_log.execution_result`.

---

## Pattern 5: Observability and SLO Tracking

**Use case:** operations team tracks AI quality, abstention rate, cost per tenant, and model drift over time.

```
Every REMORA decision
  ├── OpenTelemetry span exported to collector
  │     attributes: tenant_id, risk_profile, verdict, confidence,
  │                 oracle_calls, latency_ms, stages_run
  │
  └── remora_telemetry_daily table updated (batch job, nightly)
        aggregates: total_requests, accepted, abstained, escalated,
                    mean_confidence, mean_oracle_calls, oracle_cost_units,
                    accuracy_on_feedback

Grafana dashboards
  ├── Abstention rate by tenant (SLO: < 15% on low-risk domains)
  ├── Escalation rate by domain (SLO: < 5% on medium-risk)
  ├── Mean confidence trend (drift detection)
  ├── Oracle cost per request per tenant
  └── Accuracy on feedback (eval harness daily run)
```

**SLO definitions:**
- Low-risk abstention rate: ≤ 15%
- Medium-risk escalation rate: ≤ 10%
- High-risk escalation rate: ≤ 25% (high escalation rate is expected and correct)
- Accuracy on sampled feedback: ≥ 80% on medium-risk domains
- Oracle call budget utilisation: ≤ 90% of configured maximum

---

## OT / SCADA Integration — Special Constraints

OT and SCADA integration requires stricter controls than IT systems.

**Permitted:**
- Read-only data ingest: process historians, alarm logs, sensor readings ingested as evidence into RAG layer
- REMORA verdicts returned as structured recommendations to the operator interface

**Not permitted:**
- Direct REMORA write access to any OT/SCADA system
- Autonomous tool execution that modifies setpoints, alarms, or control logic
- Any `ACT` verdict on a request in the `ot_scada_interaction` or `critical` domain

**Architecture for OT:**
```
OT network (isolated)
  │ (read-only data export via historian connector)
  ▼
Data diode / one-way gateway
  │
  ▼
Enterprise data platform (Cognite CDF / OSIsoft PI)
  │
  ▼
REMORA RAG oracle (evidence ingest only)
  │
  ▼
REMORA consensus + decision (RECOMMEND ONLY)
  │
  ▼
Operator interface (DCS / operator workstation)
  - operator reads recommendation
  - operator executes manually if appropriate
```

The data diode ensures no path exists from REMORA's decision output back to the OT control layer.
