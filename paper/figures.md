# REMORA Paper: Figure Descriptions and Mermaid Diagrams

## Figure 1: REMORA Architecture (Mermaid)

```mermaid
flowchart TD
    A([Agent Proposed Action<br/>query q, action a, context c]) --> B

    B[/Stage 1: Intake & Risk Classification/]
    B -->|adversarial_detected| FIRE1([ESCALATE — Admission Firewall])
    B -->|clean| C

    C[/Stage 2: Oracle Fan-Out<br/>ThreadPoolExecutor, parallel/]
    C --> C1[Oracle 1<br/>Llama-3.1-8B]
    C --> C2[Oracle 2<br/>Llama-3.3-70B]
    C --> C3[Oracle 3<br/>Llama-4-Scout]
    C1 & C2 & C3 --> FILT{Filter failed oracles}
    FILT -->|O' valid set| D

    D[/Stage 3: Canonicalization & Weighted Consensus/]
    D --> D1["φ(): raw → (polarity, claim_hash, magnitude, tags)"]
    D1 --> D2["ρ(a,b): rolling pairwise agreement"]
    D2 --> D3["w(o): diversity weights<br/>p̂(v): weighted support"]
    D3 --> E

    E[/Stage 4: Thermodynamic Observables/]
    E --> E1["H = −Σ p̂ log₂ p̂<br/>D = 1 − max p̂<br/>η = order parameter"]
    E --> E2["T = f(prompt) — structural temperature<br/>F = λD − T·H<br/>τ = trust score"]
    E --> E3["V(t) = H + λD — Lyapunov observable<br/>phase ∈ {ordered, critical, disordered}"]
    E1 & E2 & E3 --> F

    F{phase?}
    F -->|ordered| G
    F -->|disordered| H[Default ABSTAIN]
    F -->|critical| EVRT

    EVRT[/Stage 5: Critical Evidence Router/]
    EVRT --> EVRT1{EvidenceSignal}
    EVRT1 -->|coverage < 0.50| FIRE2([ESCALATE])
    EVRT1 -->|contradiction > 0.50| ABS([ABSTAIN])
    EVRT1 -->|strength ≥ 0.80| EVRT2([evidence_accept → G])
    EVRT1 -->|default| FIRE3([ESCALATE])
    EVRT2 --> G

    G[/Stage 6: Policy Engine/]
    G --> PH1["Hard Block 1: Adversarial → ESCALATE"]
    G --> PH2["Hard Block 2: Counterfactual → ESCALATE"]
    G --> PH3["Hard Block 3: Evidence contradicted → ESC/ABS"]
    G --> PH4["Hard Block 4: Require evidence → VERIFY"]
    G --> PH5["Hard Block 5: Distribution shift → VERIFY"]
    G --> PH6["Hard Block 6: Critical+Critical → ESCALATE"]
    G --> PH7["Hard Block 7: Risk+no evidence → VERIFY"]
    PH1 & PH2 & PH3 & PH4 & PH5 & PH6 & PH7 --> ROUTE

    ROUTE{Routing}
    ROUTE --> ACC([ACCEPT])
    ROUTE --> VER([VERIFY])
    H --> ABS2([ABSTAIN])
    ROUTE --> ESC([ESCALATE])

    ACC & VER & ABS2 & ABS & ESC --> ENV

    ENV[/Stage 7: DecisionEnvelope v2/]
    ENV --> ENV1["request | assessment | gate"]
    ENV --> ENV2["reviewer_context | follow_up"]
    ENV --> ENV3["history | policy_learning"]
    ENV --> ENV4["audit — SHA-256 hash-chain"]

    style ACC fill:#22c55e,color:#fff
    style VER fill:#f59e0b,color:#fff
    style ABS fill:#94a3b8,color:#fff
    style ABS2 fill:#94a3b8,color:#fff
    style ESC fill:#ef4444,color:#fff
    style FIRE1 fill:#ef4444,color:#fff
    style FIRE2 fill:#ef4444,color:#fff
    style FIRE3 fill:#ef4444,color:#fff
```

**To convert to a publication figure:**
1. Render with Mermaid CLI: `mmdc -i figures.md -o remora_arch.svg`
2. Simplify to a clean box-and-arrow diagram in Inkscape or draw.io
3. Export as PDF for LaTeX inclusion

---

## Figure 2: Decision Gate Flow

```mermaid
flowchart LR
    RAW([Raw action metadata]) -.->|"opt-in v0.9.0"| GI[Governance Intelligence\nenrichment - strengthen-only\nnormalize / semantics / misspec\nblast radius / fleet risk]
    GI -.-> IN
    RAW --> IN([PolicyObservation\n55 fields]) --> BLOCKS

    BLOCKS[7 Hard Blocks\npriority-ordered]
    BLOCKS -->|"block 1–3 fire"| ESC([ESCALATE])
    BLOCKS -->|"block 4,5,7 fire"| VER([VERIFY])
    BLOCKS -->|no hard block| ROUTING

    ROUTING[Routing Logic]
    ROUTING -->|"conformal accept\nor ordered+trust≥τ*"| ACC([ACCEPT])
    ROUTING -->|"critical phase\nor high contradiction"| VER2([VERIFY])
    ROUTING -->|"disordered+no evidence\nor trust<0.2"| ABS([ABSTAIN])
    ROUTING -->|default safe| ABS2([ABSTAIN])

    style ESC fill:#ef4444,color:#fff
    style VER fill:#f59e0b,color:#fff
    style VER2 fill:#f59e0b,color:#fff
    style ACC fill:#22c55e,color:#fff
    style ABS fill:#94a3b8,color:#fff
    style ABS2 fill:#94a3b8,color:#fff
```

---

## Figure 3: Phase Routing

```mermaid
flowchart TD
    T[/"Structural Temperature T\n(prompt: zlib, length, domain prior)"/]
    ETA[/"Order Parameter η\n= (max p̂ − 1/k) / (1 − 1/k)"/]

    T & ETA --> PHASE

    PHASE{Phase Classification}
    PHASE -->|"T < Tc AND η > 0.5"| ORD[Ordered Phase]
    PHASE -->|"|T − Tc|/Tc < 0.15"| CRIT[Critical Phase]
    PHASE -->|otherwise| DIS[Disordered Phase]

    ORD --> ORD1["τ weight: 1.0\nHigh coverage possible\nConformal at 15%: 99.9% coverage, 0/20 failures (augmented N=2,161)"]
    CRIT --> CRIT1["τ weight: 0.5\nTrust anticorrelation confirmed\nEvidence routing required\nResolution: 38.5% at 100% precision"]
    DIS --> DIS1["τ weight: 0.1\nDefault ABSTAIN\nConformal: near-zero coverage"]

    style ORD fill:#22c55e,color:#fff
    style CRIT fill:#f59e0b,color:#fff
    style DIS fill:#ef4444,color:#fff
```

---

## Figure 4: Evidence + Policy + Audit Envelope

```mermaid
flowchart LR
    subgraph EV[Evidence Router]
        ES[/"EvidenceSignal\nstrength, contradiction,\ncoverage, consistency,\nreliability"/]
        ES --> EV1{Gates}
        EV1 -->|"coverage < 0.50"| EESC([Escalate])
        EV1 -->|"contradiction > 0.50"| EABS([Abstain])
        EV1 -->|"all thresholds met"| EACC([evidence_accept])
        EV1 -->|default| EESC2([Escalate])
    end

    subgraph POL[Policy Engine]
        PO[PolicyObservation] --> HB[7 Hard Blocks]
        HB --> |OPA first| OPA[OPA/Rego]
        OPA -->|fail| PY[Python fallback\nfail-closed]
        OPA & PY --> GATE[Gate Decision]
    end

    subgraph AUD[Audit Envelope]
        GATE --> ENV[DecisionEnvelope v2]
        ENV --> HC["SHA-256 hash-chain\nh_i = SHA256(h_{i-1} || entry_i)"]
        HC --> STORE["Tamper-evident\n(not tamper-proof without WORM storage)"]
    end
```

---

## Figure 5: Case Study Sequence (Well Barrier Agent Action)

```mermaid
sequenceDiagram
    actor Agent
    participant REMORA
    participant Oracles
    participant PolicyEngine
    participant HumanReviewer

    Agent->>REMORA: propose_action("Reduce mud weight 1.52→1.48 SG")
    REMORA->>REMORA: classify(domain=well_engineering, risk=critical)

    par Oracle fan-out
        REMORA->>Oracles: ask(oracle_1: Llama-3.1-8B)
        REMORA->>Oracles: ask(oracle_2: Llama-3.3-70B)
        REMORA->>Oracles: ask(oracle_3: Llama-4-Scout)
    end

    Oracles-->>REMORA: ESCALATE(0.78), ESCALATE(0.85), VERIFY(0.62)
    REMORA->>REMORA: canonicalize → p̂(ESC)=0.71, p̂(VER)=0.29
    REMORA->>REMORA: H=0.866, D=0.29, T=0.85, phase=critical, τ=0.31
    REMORA->>REMORA: evidence_signal(citation_coverage=0.18 < 0.50)

    REMORA->>PolicyEngine: evaluate(phase=critical, risk=critical, ...)
    PolicyEngine-->>REMORA: HARD_BLOCK_6: CRITICAL_PHASE → ESCALATE

    REMORA-->>Agent: BLOCKED — gate=ESCALATE, SLA=4h
    REMORA->>HumanReviewer: follow_up(assign=Well Engineer, evidence=[ECD calc, OIM sign-off])
    REMORA->>REMORA: audit_chain.append(hash=3f7a2c...)

    Note over Agent: Action is blocked.<br/>Autonomous execution prevented.
    Note over HumanReviewer: Receives structured<br/>follow-up request.
```

---

## Figure Captions (for LaTeX)

**Figure 1.** REMORA gate architecture. Six decision stages process each
proposed agent action, followed by DecisionEnvelope emission (Stage 7). Hard
blocks in Stage 6 can override any earlier routing signal. Stage 7 is the
output record, not a decision stage. The policy engine queries OPA/Rego first
and falls closed to a Python fallback when OPA is unavailable.

**Figure 2.** Decision gate flow. Seven hard blocks are evaluated in priority
order before any routing logic. Policy blocks override thermodynamic consensus.

**Figure 3.** Phase routing and empirical outcomes. The ordered phase achieves
99.9% conformal coverage with 0/20 seed failures at the 15% risk target.
The critical phase cannot achieve meaningful coverage via trust scoring alone;
evidence routing resolves 38.5% of critical items with 100% precision.

**Figure 4.** Evidence router, policy engine, and audit envelope integration.
The hash-chain provides tamper-detection; tamper-proof storage requires an
external WORM backend.

**Figure 5.** Case study sequence for a well barrier agent action. The agent
proposes a mud weight reduction; REMORA fires Hard Block 6 (critical phase +
critical risk) and routes the decision to a human reviewer with a structured
follow-up request.
