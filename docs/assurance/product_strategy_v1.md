# REMORA Product Strategy v1
## Assurance Campaign — Commercial Readiness

**Status:** Pre-commercial. Research-grade system. Three production gates open.
**Author:** Assurance campaign — Agent H analysis, 2026-06-30
**References:** `README.md`, `docs/02-evidence-and-claims.md`, `NEGATIVE_RESULTS.md`,
`docs/architecture_risk_register.md`, `artifacts/credibility-pack/executive-summary.md`,
`docs/governance/nist_ai_rmf_mapping.md`

---

## 1. Positioning

### What REMORA Is

REMORA is a **pre-execution governance overlay** for autonomous AI agents. It interposes
a deterministic policy layer and a multi-oracle consensus pipeline before any agent
action executes, returning one of four outcomes: ACCEPT, VERIFY, ABSTAIN, or ESCALATE.
Every decision is logged in a tamper-evident `DecisionEnvelope` hash chain.

The defensible positioning statement, grounded in committed artifacts:

> REMORA implements a reproducible, policy-gated control architecture that routes
> agent action proposals through uncertainty measurement, evidence verification, and
> explicit human escalation — producing auditable governance decisions before
> consequential actions execute.

This positions REMORA as infrastructure, analogous to a firewall or admission controller,
not as an AI product or a model-replacement layer.

### What REMORA Is Not (Required Caveats)

These caveats are part of the claim. Every external communication must carry them.

**"TRAINED AII" (AII = 0.84, TRAINED_SHADOW_ONLY) — what it proves and does not prove**

AII is AROMER's closed-loop learning health index, a weighted composite of five internal
diagnostic scores (T1 calibration, T2 friction suppression, T3 MetaJudge quality,
T4 transfer, T5 stability). TRAINED status (AII ≥ 0.80) means the internal learning
loop has reached a stable, low-friction operating regime.

TRAINED does NOT prove:
- Production deployment readiness (three gates remain: REM-020, REM-021, REM-022)
- External validation of the core governance architecture (AROMER is experimental
  and separately assessed from the policy engine)
- Safety under adversarial caller-supplied metadata (FA=30.7% under neutral metadata
  on external datasets; see `NEGATIVE_RESULTS.md §8`)
- Durable TRAINED status — the AII crossed TRAINED→CAPABLE and back organically on
  2026-06-28 within hours; the system is in shadow-only research mode

AROMER AII numbers must not be cited as evidence for the core governance system.
Cite benchmark artifacts, not live telemetry, in external claims.

**"0% false-accept on benchmarks" — what it proves and does not prove**

Two benchmark results carry this label:

1. External AgentHarm benchmark (N=208 harmful scenarios): FAR=0.0%,
   Wilson 95% CI [0.00%, 1.81%]. External validity: this dataset was not in
   REMORA's training corpus. Architectural source: Stage 1 hard-block policy
   invariants. The multi-oracle consensus machinery does NOT drive this result.

2. Tool-call benchmark v2 (N=700 adversarial tasks): FAR=0.0%,
   Wilson 95% CI [0.00%, 0.55%]. This is a deterministic simulator — no real
   shell, network, or database mutations occur.

"0% false-accept" does NOT prove:
- Field deployment safety. Controlled benchmarks do not prove field safety.
- Safety under neutral metadata. FA=30.7% on external datasets under neutral
  trust parameters (see `NEGATIVE_RESULTS.md §8`).
- Safety from the consensus machinery. Hard-block policy invariants alone
  produce the 0% rate.
- Independent replication. All benchmarks are internally replicated.
  External replication is listed as a required evidence tier (REM-021 scope).

Always cite the Wilson CI alongside the 0% point estimate. Never omit it.

**Shadow mode — what it proves and what production requires**

Shadow mode means REMORA evaluates proposed actions and produces governance records
without actually blocking execution. The shadow-replay engine (`make shadow-replay`)
demonstrates that the governance architecture produces deterministic, reproducible
decisions on a given action log.

Shadow mode does NOT prove:
- That production interception works (INTERCEPTION_NOTES.md: AgentHarm harness
  is intent-gating, not tool-call interception, until `inspect_tools_probe.py`
  proves otherwise)
- Production latency, cost, or reliability under real traffic
- That RBAC and access controls are correctly scoped (REM-022 is open)
- That longitudinal performance is stable over 7 days at FAR=0.0% (REM-020 is open)

**Competitive differentiation — what can be asserted**

Assertable without overclaiming:
- Deterministic hard-block policy layer that cannot be overridden by probabilistic
  oracle output (architectural property, tested in `remora/policy/invariants.py`)
- Per-action, pre-execution governance decision with full audit trail
  (DecisionEnvelope schema committed; hash chain implementation committed)
- Policy-as-code (OPA adapter designed; Rego skeleton committed)
- Explicit abstention and escalation as first-class policy outcomes
  (not failure modes — design intent)
- NIST AI RMF alignment mapping (internal; not independently audited)
- Zero-dependency Python core (verifiable from `pyproject.toml`)

Do not assert:
- Production certification or safety guarantees
- Superiority to specific named competitors without benchmark comparisons
- Market size figures without a cited independent source

---

## 2. Target Segments

Segments are prioritized by: (a) acuteness of need for pre-execution governance,
(b) alignment with REMORA's current coverage, (c) regulatory forcing function
that creates budget for governance tooling.

### Priority 1 — AI Safety / Governance Tool Vendors and Platforms (B2B tooling)

**Who:** Enterprise AI platform vendors (cloud providers, agent framework vendors)
embedding governance into their offerings; AI safety companies building enterprise
assurance layers; AI infrastructure vendors seeking differentiation on compliance.

**Why most acute:** The B2B channel avoids the need for REMORA to achieve its own
enterprise production certification before commercial value is realized. A vendor
integrating REMORA as a reference architecture or OEM component is the shortest
path from TRAINED_SHADOW_ONLY to commercial engagement.

**REMORA fit:** Modular architecture (zero-dependency Python core, pluggable oracle
adapters, MCP server with 12 tools, OPA integration, Cloudflare Workers deployment)
is designed for integration, not standalone product deployment.

**Deployment model:** OEM / white-label integration; SDK licensing.

**Gate to unlock:** REM-021 (independent review package) is the credibility artifact
needed for this conversation. The credibility pack (`artifacts/credibility-pack/`)
is the starting point.

### Priority 2 — Operational Technology (OT) / Energy / Critical Infrastructure

**Who:** Energy producers and grid operators, water and wastewater utilities,
manufacturing with AI-augmented SCADA advisory systems.

**Why most acute:** The building-automation demo directly addresses this domain
(per-zone occupancy governance, energy policy enforcement). SCADA advisory systems
are the canonical use case for pre-execution governance: low tolerance for false
accepts, explicit human escalation requirements, audit trail mandated by regulation.

**REMORA fit:** Critical-tier policy (RECOMMEND ONLY, never autonomous ACT) maps
directly to the OT/SCADA advisory pattern. The energy use case is documented with
a working dry-run demo (`docs/use-cases/04-energy.md`, `scripts/demo_building_lights.py`).
NIST AI RMF alignment addresses the regulatory framing.

**Deployment model:** On-premises or private cloud required. Air-gapped possible
with the zero-dependency Python core. RAG oracle could be on-premises with
static knowledge base (`StaticJsonlEvidenceProvider`).

**Gate to unlock:** REM-020 (longitudinal stability) and REM-021 (independent
review) are minimum requirements before engagement with regulated OT buyers.
REM-022 (RBAC audit) is essential because OT deployments require documented
access control at the system boundary.

**Honest gap:** Caller-supplied metadata dependency (M4, open gate) is a
deployment risk in OT: the signed tool-schema registry required to authenticate
risk_tier and action_type signals does not yet exist. This must be disclosed
to OT prospects and framed as a deployment gate, not a product limitation.

### Priority 3 — Regulated Financial Services

**Who:** Investment banks, asset managers, insurance carriers deploying AI in
KYC, credit decisioning, trade surveillance, or compliance workflows.

**Why relevant:** Financial regulators (MAS, FCA, SEC AI guidance) require
explainability and audit trails for algorithmic decisions. REMORA's
DecisionEnvelope and OPA policy-as-code align with model governance obligations.

**REMORA fit:** The financial evidence provider is committed
(`datasets/finance_v1/`). The selective accuracy result (88.0%, CI [70.0%, 95.8%])
at 23.2% coverage provides a governance-relevant framing: REMORA can identify
which AI-assisted financial decisions are high-confidence versus which require
human review.

**Deployment model:** Private cloud or on-premises (data residency requirements).
Multi-tenant architecture is designed but not implemented.

**Gate to unlock:** REM-022 (RBAC audit) is table stakes for financial services —
access control documentation is required before any procurement conversation.
External replication of selective accuracy results (REM-021 scope) is required
before regulated buyers will credit the 88.0% figure.

**Honest gap:** N_accepted=25 in the held-out accuracy split yields a wide Wilson
CI [70.0%, 95.8%]. This is a directional confirmation, not a production SLA.
Financial buyers need a tighter accuracy estimate before deploying at scale.

### Priority 4 — Healthcare / Clinical Decision Support

**Who:** Hospital systems, clinical information vendors, health insurers evaluating
AI for clinical note summarization, drug interaction flagging, or prior
authorization.

**Why relevant:** FDA AI/ML-based SaMD guidance and EU MDR requirements create
explicit human oversight obligations for AI in clinical pathways. REMORA's
ESCALATE outcome and human approval workflow design directly address these.

**REMORA fit:** Healthcare use case is documented (`docs/use-cases/01-healthcare.md`).
The oracle diversity model (different model families cannot share systematic
failures) is relevant to clinical safety.

**Deployment model:** On-premises or private cloud with strict data sovereignty.

**Gate to unlock:** All three production gates (REM-020/021/022) plus independent
clinical validation (not in current gate register — this is a segment-specific
additional gate). Healthcare AI requires domain-specific evidence, not
general-domain benchmarks.

**Honest gap:** General-domain benchmarks do not support healthcare-specific
accuracy claims. A healthcare-specific pilot with domain oracle configuration
and clinical knowledge base is required before this segment is credible.

### Priority 5 — Enterprise IT / Security Operations

**Who:** Large enterprises running agentic AI in IT automation, DevSecOps
pipelines, or SOC workflows.

**Why relevant:** Agent-driven infrastructure changes (cloud provisioning,
deployment pipelines, incident response automation) are the canonical use case
for tool-call governance. The tool-call benchmark v2 result (0% unsafe execution)
directly addresses this.

**REMORA fit:** The MCP server (12 tools), Cloudflare Workers deployment, and
the security evidence provider (`datasets/cyber_evidence_v1/`) are directly
applicable. The OWASP GenAI Top 10 mapping (`docs/security/owasp_genai_mapping.md`)
provides a security-buyer-facing compliance artifact.

**Deployment model:** SaaS (Cloudflare Workers) is the fastest path for this
segment. CORS wildcard restriction and rate limiting (noted in pre-deployment
review) must be resolved before production.

**Gate to unlock:** REM-020 and REM-021. The tool-call benchmark v2 result
is the primary credibility artifact for this segment. External replication
(REM-021 scope) is needed before security buyers will accept the benchmark.

---

## 3. Go-to-Market Path

### Phase 0 — Research and Academic Credibility (Current)

**Goal:** Establish the governance architecture as a credible research artifact.

**Status:** Substantially complete. The following artifacts are committed
and available for external review:
- Full paper with mathematical supplement and claim ledger
- External AgentHarm benchmark result (REM-014 PASS)
- Tool-call benchmark v2 (internally replicated)
- Negative results published (`NEGATIVE_RESULTS.md`)
- Credibility pack (`artifacts/credibility-pack/`)

**What remains for Phase 0 completion:**
- Peer review submission (NEGATIVE_RESULTS.md §14 documents M1–M9 findings
  from one external reviewer; journal / workshop submission is the logical next step)
- Close the semantic entropy gap (M5 / NEGATIVE_RESULTS.md §3): run benchmarks
  with NLISemanticBackend once torch DLL restriction is resolved
- External replication of tool-call v2 benchmark by an independent party

### Phase 1 — Enterprise Pilot Readiness (Production Gates Required)

**Goal:** Reach a state where REMORA can be offered to a design partner for
a structured pilot under a research/beta agreement.

**Required gates before any pilot commitment:**

| Gate | ID | Eligibility / Current state |
|------|----|-----------------------------|
| Longitudinal stability (7-day TRAINED at FAR=0.0%) | REM-020 | Earliest eligible: 2026-07-05 (TRAINED recovered 2026-06-28 15:53 UTC). Requires 7 unbroken days of TRAINED status with FAR=0.0% per AROMER telemetry. |
| Independent human review | REM-021 | Reviewer package must be assembled (see §4). |
| RBAC audit | REM-022 | RBAC documentation must be produced (see §4). |

**Additional requirements for pilot engagement (not currently in gate register):**
- Resolve caller-supplied metadata dependency (M4): document it as a deployment
  constraint and provide a signed registry design, even if not yet built
- CORS wildcard restriction (pre-deployment review item) must be resolved
- Production API gateway design (currently "not attempted" per executive brief)
- Tenant isolation design if multi-tenant pilot (multi-tenant architecture is
  designed but not implemented)

**Phase 1 output:** A pilot-ready package including: reviewer-approved negative
results, REM-020/021/022 closed, deployment runbook, a supported deployment
model (on-premises or Cloudflare Workers), and a design partner NDA template.

### Phase 2 — Production Deployment (Infrastructure Gap Closure)

**Goal:** First non-shadow production deployment with a design partner under
controlled conditions.

**Infrastructure gaps to close (from executive brief "not yet built"):**
- Production API gateway (authentication, rate limiting, routing)
- Enterprise identity integration (OIDC / SSO)
- Live evaluation harness with production feedback loop
- Temporal workflow orchestration for long-running human approval workflows
- Multi-tenant deployment infrastructure with tenant isolation

**Additional security items from pre-deployment review:**
- Rate limiting on all worker endpoints
- mTLS between workers for regulated deployments
- WORM/append-only audit log integration for regulated environments
- R2 key validation and content length guards

**Evidence required for Phase 2:**
- Live-oracle (non-simulator) replication of tool-call safety metrics
- Production evidence retrieval validation beyond MultiNLI proxy
- Fairness and bias evaluation on domain-specific corpora (MS-4 per NIST RMF)
- Penetration test by a party not on the development team (pre-deployment
  review item)

**Phase 2 output:** A production-deployed system running in production-shadow mode
(decisions logged, not yet blocking) with a design partner, with live telemetry
feeding back into AROMER.

### Phase 3 — Scale

**Goal:** Multiple production deployments; commercial licensing established.

**Preconditions:**
- Phase 2 deployment operating stably for ≥30 days
- Independent external replication of at least one benchmark (closes REM-021
  external replication scope)
- AROMER organic TRAINED stability demonstrated over a sustained window *(the formal REM-020 gate criterion is 7 days of AII-EMA ≥ 0.80 with FAR = 0.0%; see release_gates.md)*
  (not just 7 days per REM-020)
- Signed tool-schema registry built (M4 resolution)
- Commercial licensing terms, support model, and SLA framework defined

---

## 4. Production Gate Roadmap

The three open gates (REM-020, REM-021, REM-022) are the blocking prerequisites
for any commercial engagement. This section details what must happen before each.

### REM-020 — Longitudinal Stability

**Requirement:** 7 consecutive days of TRAINED status (AII ≥ 0.80) with FAR=0.0%
as reported by AROMER telemetry.

**Earliest eligibility:** 2026-07-05 (TRAINED confirmed at 15:53 UTC 2026-06-28).

**Risks to eligibility:**
- Organic T2 regression (documented in §12–§13 of NEGATIVE_RESULTS.md): borderline-
  benign organic traffic can drive AII below 0.80 within hours. The 7-day window
  must be unbroken. One organic regression resets the clock.
- Sliding-window composition sensitivity: the 200-episode FIFO window is sensitive
  to session hook traffic. Low-volume periods may cause INSUFFICIENT_SAFETY_EVIDENCE
  window gate without being a safety regression.
- No further seeding during the stability window (seeding invalidates the organic
  stability claim).

**What to document at gate close:**
- AROMER telemetry log covering the 7-day window
- Confirmation of FAR=0.0% (global gate, not window gate) throughout
- Any T2 fluctuations and their root cause (organic vs. seeding artifact)
- Explicit statement that no synthetic seeding occurred during the window

### REM-021 — Independent Human Review

**Requirement:** An independent reviewer (not the development team) reviews the
governance architecture, benchmark claims, and negative results, and produces
a written assessment.

**Reviewer package must contain (minimum):**

1. **Claim register** (`paper/claim_ledger.md`, `artifacts/credibility-pack/results-snapshot.md`):
   all headline claims with artifact links, Wilson CIs, and scope caveats

2. **Benchmark reproducibility guide** (`docs/06-reproducibility.md`,
   `artifacts/credibility-pack/repro-guide.md`): step-by-step instructions
   for an independent rerun; should be executable without access to the author

3. **Negative results** (`NEGATIVE_RESULTS.md`, `artifacts/credibility-pack/negative-results.md`):
   complete active findings list, including FA=30.7% under neutral metadata (§8),
   M1–M9 peer-review findings (§14), and all open gaps

4. **Architecture overview** (`artifacts/credibility-pack/architecture-overview.md`,
   `ARCHITECTURE.md`): data flow, per-stage contracts, hard-block precedence

5. **Threat model** (`artifacts/credibility-pack/threat-model.md`): known attack
   surfaces, including caller-supplied metadata (M4) and indirect injection gap (§2)

6. **Scope boundaries**: explicit statement of what the system does not do
   (does not make models truthful, not a replacement for domain authority, not a
   universal AI safety solution)

**Reviewer qualification:** At minimum, a person with experience in ML evaluation
methodology, familiar with selective prediction, Wilson CIs, and adversarial
benchmark design. For regulated vertical claims, domain expertise is required
additionally (e.g., a clinical informaticist for healthcare claims).

**What the reviewer must produce:**
- Written assessment covering: claim accuracy, caveat sufficiency, negative result
  completeness, reproducibility verification (or attempt)
- Classification: approvable as governance architecture paper / requires revision /
  reject
- Specific findings (analogous to M1–M9 in §14) that must be addressed before
  any external claim is made

**What the reviewer must NOT be asked to do:**
- Certify production safety (no reviewer can do this without production evidence)
- Validate AROMER AII as a safety metric (AROMER is experimental)

### REM-022 — RBAC Audit

**Requirement:** Role-based access control for all REMORA system components is
documented, reviewed, and confirmed consistent with the least-privilege principle.

**What must be documented:**

1. **Worker endpoint authorization matrix** (extend `docs/security/pre-deployment-review.md`):
   - agent-control: `/execute`, `/sessions`, `/audit`, `/test-bindings` (Bearer CONTROL_SECRET)
   - rag-oracle: `/ingest` (Bearer ORACLE_SECRET), `/query` (intentionally public — must be confirmed
     acceptable for each deployment's sensitivity level)
   - aromer worker: document all endpoints and their authorization requirements

2. **Secret rotation policy**: who can rotate CONTROL_SECRET, ORACLE_SECRET, REMORA_SECRET,
   RAG_SECRET; under what conditions; how rotation is documented

3. **Human approval authority matrix** (`enterprise/human-approval-workflow.md`):
   - Which roles can approve ESCALATE decisions
   - What constitutes a two-person rule for critical-tier actions
   - Audit log write access (who can write; is UPDATE of approval records permitted)

4. **Principle of least privilege confirmation**: each component (Python core, Cloudflare
   Workers, D1, R2) has access only to what it requires; no shared secrets across
   tenants; no secrets in version control (confirm with `git grep`)

5. **Known gaps to disclose**: CORS wildcard (must be restricted before customer-facing
   deploy), no rate limiting currently implemented, audit log UPDATE permitted on D1
   (WORM log required for regulated deployments), no mTLS between workers

**Reviewer:** The RBAC audit should be reviewed by someone other than the primary
developer. For a regulated vertical deployment, an independent security reviewer is
required (noted in pre-deployment review checklist).

---

## 5. Risk Register Contribution — Strategic Risks

The architecture risk register (`docs/architecture_risk_register.md`) covers technical
risks. This section documents strategic risks not already in the technical register.

### SR-1 — Market Timing Risk

**Description:** The enterprise AI governance market is forming rapidly. Major cloud
providers (AWS, Azure, GCP) and foundation model vendors (Anthropic, OpenAI, Google)
are building governance tooling into their platforms. If their integrated offerings
achieve adequate governance coverage before REMORA reaches commercial readiness,
the independent governance layer market may compress significantly.

**Severity:** High. The three production gates (REM-020, REM-021, REM-022) and the
infrastructure gap (production API gateway, OIDC, multi-tenant) mean commercial
readiness is at minimum 60–90 days away assuming no technical blockers.

**Mitigation:**
- Prioritize the B2B tooling channel (Priority 1 segment): position REMORA as a
  component for platform vendors to integrate, not a standalone product competing
  with platform vendors
- The deterministic hard-block architecture and zero-dependency Python core are
  genuine integration advantages — they do not require the integrating vendor to
  adopt a specific LLM or cloud
- Academic publication and credibility-pack release can establish architecture
  priority without waiting for commercial readiness

**Residual risk:** If foundation model vendors implement hard-block policy layers
equivalent to REMORA's Stage 1 invariants at the model layer, the primary
differentiator is auditable governance decisions (DecisionEnvelope), not the
safety floor itself.

### SR-2 — Competitive Response Risk

**Description:** Once REMORA's architecture is published, the specific design
choices (hard-block precedence, multi-oracle consensus, phase-aware guardrail,
DecisionEnvelope hash chain) are replicable by well-resourced competitors.

**Severity:** Medium. Publication is the right scientific choice and creates
academic priority. But it eliminates trade-secret protection for the core
architecture.

**Mitigation:**
- Defensive moat is in operational knowledge: the documented failure modes,
  seeding instability, window-rotation bottlenecks, and calibration dynamics
  (all in `NEGATIVE_RESULTS.md`) represent real-world operational experience
  that cannot be replicated from a paper alone
- First-mover advantage in specific regulated verticals requires customer
  relationships, not just architecture
- The AROMER closed-loop learning layer (experimental) represents a
  differentiation path that a competitor would need years of operational
  data to replicate

### SR-3 — Regulatory Framing Risk

**Description:** REMORA is positioned as a governance overlay for AI agents.
Regulators (EU AI Act, US Executive Order on AI, sector-specific rules) are
defining obligations for AI governance in ways that may or may not align with
REMORA's current architecture. Misalignment could result in REMORA being
technically compliant with its own design but not satisfying regulatory
requirements in a given jurisdiction.

**Severity:** Medium. Current NIST AI RMF mapping is internal and not
independently audited. EU AI Act applicability depends on deployment context
(system integrator vs. deployer vs. developer obligations).

**Mitigation:**
- The NIST AI RMF mapping (`docs/governance/nist_ai_rmf_mapping.md`) is a
  starting point; it should be reviewed by a legal or compliance professional
  before being presented to regulated buyers
- EU AI Act classification depends on the end-use deployment, not on REMORA
  itself; communicate this clearly to prospects
- Track regulatory guidance on agentic AI (NIST, EUAIAB, MHRA for healthcare)
  and flag changes that affect the REMORA governance model

### SR-4 — External Validation Dependency Risk

**Description:** REMORA's commercial credibility in regulated verticals depends
critically on independent external validation of benchmark results. REM-021
is a blocking gate. If the independent reviewer finds significant issues (as
the §14 peer reviewer found M1–M9), the validation timeline extends and
commercial conversations are delayed.

**Severity:** High. The §14 peer review finding (M1 construct validity violation)
was critical and required a fix. A second reviewer could identify additional
issues, particularly around:
- Benchmark construction validity (M1 remaining caveat: correlated structural
  flags may produce tautological results)
- The FA=30.7% gap under neutral metadata (§8 in NEGATIVE_RESULTS.md) which
  is the honest answer to "what happens in real adversarial conditions"
- The single-split holdout limitation (M8) for the 88.0% accuracy claim

**Mitigation:**
- Commission the independent review early — before commercial conversations,
  not after. A negative finding from an external reviewer during a commercial
  evaluation is worse than finding it proactively.
- Prepare the reviewer package completely before inviting a reviewer, using
  the §4 checklist above. An incomplete reviewer package delays the review
  and signals poor readiness.
- Explicitly disclose known residual risks (FA=30.7%, M1 caveat, M8) in the
  reviewer package rather than waiting for the reviewer to find them.

### SR-5 — Operational Stability Risk (AROMER / Shadow-Only)

**Description:** AII reached TRAINED twice, regressed to CAPABLE twice, and
recovered organically. The 200-episode sliding window architecture is documented
as sensitive to seeding, organic traffic spikes, and composition shifts
(`NEGATIVE_RESULTS.md §6–§13`). A prolonged CAPABLE period during the REM-020
7-day window resets the gate clock. If organic traffic is insufficient to generate
the needed MEDIUM/HIGH risk `/decide` episodes, the window may stagnate.

**Severity:** Medium. This is a measurement architecture issue, not a safety
regression (FAR=0 throughout all documented regressions).

**Mitigation:**
- Do not apply additional seeding during the REM-020 window; it invalidates
  the organic stability claim
- Monitor brr and window composition daily during the window; document any
  regression and its root cause immediately
- If the window stagnates (adapt cycles not generating /decide episodes),
  identify and address the root cause in hook traffic generation before
  declaring gate eligibility
- Consider documenting the sliding-window architecture's known sensitivity
  as an open design improvement (EMA dual-window) in the REM-022 or a
  separate architectural note, to demonstrate awareness and a resolution path

---

## Recommended Next Steps for Commercial Readiness

In priority order:

1. **Assemble the REM-021 reviewer package now.** Do not wait for REM-020
   to close. The reviewer package can be assembled and reviewed in parallel
   with the 7-day stability window. Use the checklist in §4.

2. **Produce the REM-022 RBAC documentation.** Extend
   `docs/security/pre-deployment-review.md` with the human approval authority
   matrix and secret rotation policy. This is a documentation task that can
   be completed this week.

3. **Monitor REM-020 eligibility daily.** TRAINED confirmed 2026-06-28 15:53 UTC.
   Target gate close: 2026-07-05. Log daily AII, brr, and FAR. Document any
   regression with root cause. Do not seed during this window.

4. **Commission independent review immediately after REM-020 closes.**
   Do not allow the commercial timeline to compress the review. A reviewer
   who is rushed produces a less thorough review, which defeats the purpose.

5. **Select a target design partner from Priority 1 (B2B tooling) or
   Priority 2 (OT/energy).** The design partner conversation should begin
   during Phase 1 (after gates close), not after Phase 2. A design partner
   NDA and structured pilot agreement are the first commercial artifacts needed.

6. **Resolve the production API gateway gap.** The current architecture has
   no production API gateway. This is the highest-complexity infrastructure
   gap and has the longest lead time. Begin design work now; do not defer
   until Phase 2 kickoff.

7. **Do not upgrade claims before gates close.** The honest state is
   TRAINED_SHADOW_ONLY with three production gates open. Until REM-020,
   REM-021, and REM-022 are closed, no communication should imply commercial
   readiness, production certification, or field deployment safety.

---

## File Created

`C:\Users\Stian\REMORA-research\docs\assurance\product_strategy_v1.md`

## Strategic Risks Identified

| ID | Risk | Severity |
|----|------|----------|
| SR-1 | Market timing: platform vendor integration risk | High |
| SR-2 | Competitive response to published architecture | Medium |
| SR-3 | Regulatory framing misalignment across jurisdictions | Medium |
| SR-4 | External validation dependency — reviewer findings delay commercial timeline | High |
| SR-5 | AROMER operational stability during REM-020 7-day window | Medium |

## Recommended Next Steps for Commercial Readiness

1. Assemble REM-021 reviewer package in parallel with REM-020 window (now)
2. Produce REM-022 RBAC documentation this week
3. Monitor REM-020 daily; target gate close 2026-07-05; no seeding during window
4. Commission independent review immediately after REM-020 closes
5. Identify a design partner from Priority 1 (B2B tooling) or Priority 2 (OT/energy)
6. Begin production API gateway design work now (longest-lead infrastructure gap)
7. Do not upgrade external claims before all three gates close
