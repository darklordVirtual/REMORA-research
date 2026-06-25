# ArchiMate-Style View — REMORA Governance Capability

**Status:** draft — not independently audited.
**Notation:** ArchiMate 3.x layer structure (Motivation, Business, Application, Technology)
expressed in Mermaid flowcharts. For native ArchiMate tooling, these diagrams should be
recreated in Archi or equivalent.
**Audience:** Enterprise architects, modelling teams.
**Companion:** [`solution_building_block.md`](solution_building_block.md),
[`deployment_architecture.md`](deployment_architecture.md)

---

## 1. Full Layered Overview

This diagram shows the complete ArchiMate-style view across all four layers.

```mermaid
flowchart TB
  subgraph Motivation["Motivation Layer"]
    direction LR
    DRV["Driver\nUnsafe autonomous AI actions\nin enterprise environments"]
    ASMT["Assessment\nInsufficient governance of\nagent tool calls"]
    GOAL["Goal\nZero unauthorised high-risk\nagent executions in production"]
    PRIN["Principles\nFail-closed · Audit by design\nShadow Mode first · HITL"]
    CAP["Capability\nAI Action Governance"]
    REQ["Requirement\nPre-execution gating with\nfour-outcome policy evaluation"]
  end

  subgraph Business["Business Layer"]
    direction LR
    PROC["Business Process\nAgent action governance\n(assess → decide → approve/block)"]
    ROLE1["Business Role\nPlatform Owner"]
    ROLE2["Business Role\nDomain Approver"]
    ROLE3["Business Role\nCompliance Owner"]
    FUNC["Business Function\nAI Governance Operations"]
    SERV_B["Business Service\nGoverned AI action execution"]
    OBJ["Business Object\nGovernance Decision Record"]
  end

  subgraph Application["Application Layer"]
    direction LR
    APP1["Application Component\nREMORA API"]
    APP7["Application Component\nGovernance Intelligence\nEnrichment (opt-in, v0.9.0)"]
    APP2["Application Component\nPolicy Engine"]
    APP3["Application Component\nDecisionEnvelope Service"]
    APP4["Application Component\nShadow Replay Service"]
    APP5["Application Component\nAdapter Layer\n(OpenAI / LangGraph / MCP)"]
    APP6["Application Component\nReview Queue Interface"]
    DATA1["Data Object\nDecisionEnvelope"]
    DATA2["Data Object\nRisk Profile"]
    DATA3["Data Object\nAudit Record"]
    DATA4["Data Object\nPolicy Bundle"]
    DATA5["Data Object\nGolden Set"]
    SERV_A["Application Service\nAction Assessment API\n(POST /v1/assess)"]
  end

  subgraph Technology["Technology Layer"]
    direction LR
    NODE1["Node\nKubernetes Cluster / VM"]
    SS1["System Software\nPostgres (Control Plane Store)"]
    SS2["System Software\nOTel / Prometheus / Grafana"]
    SS3["System Software\nIdP / OIDC Provider"]
    SS4["System Software\nSIEM"]
    TS1["Technology Service\nTool Executor\n(isolated zone)"]
    TS2["External Service\nModel / Evidence Providers"]
    TS3["Technology Service\nSecrets Manager"]
    TS4["Technology Service\nAPI Gateway / Ingress"]
  end

  DRV --> ASMT --> GOAL
  GOAL --> PRIN --> CAP
  CAP --> REQ
  REQ --> PROC
  ROLE1 --> PROC
  ROLE2 --> PROC
  ROLE3 --> FUNC
  PROC --> SERV_B
  FUNC --> SERV_B
  SERV_B --> SERV_A
  PROC --> OBJ

  SERV_A --> APP1
  APP1 --> APP7
  APP7 --> APP2
  APP1 --> APP2
  APP1 --> APP3
  APP1 --> APP4
  APP1 --> APP5
  APP1 --> APP6
  APP2 --> DATA2
  APP2 --> DATA4
  APP3 --> DATA1
  APP3 --> DATA3
  APP4 --> DATA5

  APP1 --> NODE1
  APP1 --> TS4
  APP3 --> SS1
  APP1 --> SS2
  APP1 --> SS3
  APP3 --> SS4
  APP5 --> TS1
  APP2 --> TS2
  APP1 --> TS3
```

---

## 2. Decision Flow (Sequence View)

```mermaid
sequenceDiagram
    participant A as Agent Runtime
    participant G as REMORA Gateway
    participant P as Policy Engine
    participant E as DecisionEnvelope Service
    participant S as Audit Store (append-only)
    participant H as Human Review Queue
    participant T as Tool Executor

    A->>G: Proposed action + context + tenant_id
    G->>G: Authenticate caller (IdP)
    opt Governance Intelligence enrichment (opt-in, v0.9.0)
        G->>G: Normalize labels fail-closed, infer semantics,
        G->>G: misspecification / blast-radius / fleet risk
        Note over G: strengthen-only — caller labels never trusted blindly
    end
    G->>P: assess(action, risk_profile, evidence, policy_bundle)
    P->>P: Evaluate hard blocks
    P->>P: Classify risk tier
    P->>P: Evaluate evidence sufficiency
    P->>P: Determine outcome
    P->>E: generate_envelope(outcome, metadata, hash)
    E->>S: write_envelope(envelope) [append-only]
    E-->>G: envelope + outcome

    alt ACCEPT
        G->>T: dispatch(action, clearance_token)
        T-->>A: execution result
        G->>S: log_final_state(envelope, executed=true)
    else VERIFY
        G->>H: submit_review_request(envelope, evidence_requirements)
        H-->>G: reviewer_decision (approved / rejected)
        alt Approved
            G->>T: dispatch(action, clearance_token)
            G->>S: log_final_state(envelope, executed=true, approver_id)
        else Rejected
            G-->>A: rejection with reason
            G->>S: log_final_state(envelope, executed=false)
        end
    else ABSTAIN
        G-->>A: structured rejection (no evidence basis)
        G->>S: log_final_state(envelope, executed=false)
    else ESCALATE
        G->>H: escalate(envelope, urgency=high, sla=defined)
        H-->>G: escalation_decision (approved / rejected)
        alt Approved
            G->>T: dispatch(action, clearance_token)
            G->>S: log_final_state(envelope, executed=true, approver_id)
        else Rejected
            G-->>A: rejection with reason
            G->>S: log_final_state(envelope, executed=false)
        end
    end
```

---

## 3. Motivation View

```mermaid
flowchart LR
  subgraph External["External Environment"]
    D1["Driver: Agent autonomy\nincreasing in enterprises"]
    D2["Driver: Regulatory pressure\nAI Act / ISO 42001"]
    D3["Driver: Incident risk\nAgent-caused data/system damage"]
  end
  subgraph Internal["Internal Assessment"]
    A1["Assessment: No pre-execution\ngovernance for agent actions"]
    A2["Assessment: Audit trail\ngaps in current tooling"]
    A3["Assessment: Human oversight\nnot systematically enforced"]
  end
  subgraph Response["Architectural Response"]
    G1["Goal: Prevent unsafe\nautonomous execution"]
    G2["Goal: Complete and replayable\naudit of all decisions"]
    G3["Goal: Enforceable human\napproval boundaries"]
    P1["Principle: Fail-closed"]
    P2["Principle: Audit by design"]
    P3["Principle: HITL for high/critical"]
    CAP["Capability:\nAI Action Governance"]
  end

  D1 & D2 & D3 --> A1 & A2 & A3
  A1 --> G1
  A2 --> G2
  A3 --> G3
  G1 & G2 & G3 --> P1 & P2 & P3
  P1 & P2 & P3 --> CAP
```

---

## 4. Business Layer Detail

```mermaid
flowchart TB
  subgraph Roles
    R1["Platform Owner\n(operates REMORA)"]
    R2["Domain Approver\n(reviews queue)"]
    R3["Security Architect\n(owns policy)"]
    R4["Compliance Owner\n(audits records)"]
  end

  subgraph Process["Core Governance Process"]
    P1["Receive proposed action"]
    P2["Policy evaluation"]
    P3{Outcome}
    P4["Log to audit trail"]
    P5["Route to review queue"]
    P6["Execute approved action"]
    P7["Block / reject action"]
    P8["Escalate to approver"]
  end

  R1 --> P1
  P1 --> P2
  P2 --> P3
  P3 -->|accept| P4
  P3 -->|verify| P5
  P3 -->|abstain| P7
  P3 -->|escalate| P8
  P4 --> P6
  P5 --> R2
  R2 -->|approved| P4
  R2 -->|rejected| P7
  P8 --> R2
  P7 --> P4
```

---

## 5. Application Layer — Component Relationships

| From | Relationship Type | To | Notes |
|---|---|---|---|
| Agent runtime | `TriggeringRelationship` | REMORA Adapter | Sends proposed action |
| REMORA Adapter | `ServingRelationship` | REMORA API | Wraps action as API call |
| REMORA API | `CompositionRelationship` | Policy Engine | API orchestrates policy evaluation |
| REMORA API | `CompositionRelationship` | Governance Intelligence Enrichment | Opt-in pre-policy enrichment (v0.9.0): fail-closed normalization, semantics, misspecification / blast-radius / fleet-risk signals, strengthen-only |
| Governance Intelligence Enrichment | `FlowRelationship` | Policy Engine | Enriched PolicyObservation; engine remains sole decision authority |
| Policy Engine | `AssignmentRelationship` | DecisionEnvelope Service | Engine produces envelope |
| DecisionEnvelope Service | `AssociationRelationship` | Control Plane Store | Envelope written append-only |
| DecisionEnvelope Service | `FlowRelationship` | SIEM | Audit events forwarded |
| Policy Engine | `AccessRelationship` | Evidence Connectors / RAG | Evidence retrieved for VERIFY |
| REMORA API | `AssociationRelationship` | IdP / OIDC | Caller and approver authenticated |
| Review Queue Interface | `ServingRelationship` | Domain Approver | Human review is served |
| Tool Executor | `TriggeringRelationship` | Target System | Approved action executes |
| Shadow Replay Service | `AccessRelationship` | Control Plane Store | Reads envelopes for replay |

---

## 6. Technology Layer — Network Topology

```mermaid
flowchart LR
  subgraph AgentZone["Agent Zone (untrusted)"]
    A[Agent Runtimes]
  end
  subgraph Gateway["Gateway Zone"]
    GW[API Gateway / Ingress\nTLS termination, rate limiting]
  end
  subgraph Control["Control Plane Zone (trusted)"]
    API[REMORA API]
    DB[(Control Plane Store\nPostgres, append-only)]
    OBS[Observability\nOTel / Prometheus]
  end
  subgraph Review["Review Zone"]
    RQ[Review Queue]
    UI[Approver Interface]
  end
  subgraph Execution["Execution Zone (isolated)"]
    TE[Tool Executor\nAllowlisted tools only]
  end
  subgraph External["External Zone"]
    IDP[IdP / OIDC]
    SIEM[SIEM]
    EVD[Evidence / RAG]
  end

  A --> GW --> API
  API --> DB
  API --> OBS --> SIEM
  API --> RQ --> UI
  API --> IDP
  API --> EVD
  API -->|clearance token| TE
  TE -->|blocked without token| X[/Block/]
```
