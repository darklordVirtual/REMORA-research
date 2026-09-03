# REMORA vs. AI-assurance best practice — control-coverage gap audit (v1)

> **Status: proposal / roadmap, NOT a claims document.** This audit grades where
> REMORA stands against the control stack in the local AI-assurance compendium
> (`docs/researchpapers/kompendium_ai_assurance_3utgave.md`, ~201 works). Every
> "implemented" grade is a pointer to a truth source you can verify, the
> research-control matrix (`RES-*`), the capability register (`CAP-*`), or the
> remediation register (`REM-*`), not a new claim. Every gap is roadmap.
> Snapshot date: **2026-07-21**. If a grade and its register disagree, the
> register wins and this file is the bug.
>
> **Deployment reality (unchanged):** nothing here is `ENFORCED_PRODUCTION` or
> `EXTERNALLY_VERIFIED`. The system is `SHADOW_ONLY` until REM-021 (independent
> review) closes. See the generated Status block in the README.

## How to read this

The compendium is organised as a ten-chapter control stack, from statistical
foundations up to runtime governance. REMORA does not aim to cover all of it;
it is a pre-execution governance overlay, not a model, an MLOps platform, or a
supply-chain toolchain. This audit separates *four* things that are easy to
conflate:

| Grade | Meaning |
|-------|---------|
| ✅ **Implemented** | Module + tests exist and are wired; cite `RES-*`/`CAP-*`. Read the cited caveat — "implemented" never means "production-proven". |
| 🟡 **Partial** | Exists but bounded: library-only, reference-path-only, or carries a known honesty caveat. In scope to strengthen. |
| ⛔ **Gap** | In scope for REMORA's mission but not built. This is where the roadmap lives. |
| ⚪ **Out of scope** | Deliberately not REMORA's job; recorded in the matrix `landscape.not_implemented` block. Not roadmap. |

Grades describe *control coverage*, not maturity on the deployment ladder. A ✅
control can still be `WIRED_REFERENCE_PATH` (demo-only); check the `CAP-*`
status in `capability_register_v1.yaml` for how far each one is actually wired.

## Chapter-by-chapter coverage

### Ch. 1 — Statistical foundations, calibration, uncertainty

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Selective prediction / abstention | ✅ | RES-002 (`remora/selective/guardrail.py`); abstention is the deny-by-default path. |
| Conformal risk control | ✅ | RES-003 (`remora/selective/crc.py`); exchangeability-dependent (documented). |
| Anytime-valid confidence sequences | ✅ | RES-010; used by REM-020 FAR monitoring. |
| Post-hoc calibration (temperature/Platt) | 🟡 | `remora.calibration.platt_scaler` exists (library); not the headline signal. |
| Semantic entropy (NLI-clustered) | 🟡 | Backend exists but **unused for every reported result** — reported runs use `TokenFingerprintBackend`, not NLI semantic entropy (NEGATIVE_RESULTS §3). |

**Read:** the uncertainty core is strong and tested. The one honest gap-within-a-line is that the NLI semantic-entropy backend is built but never evaluated end-to-end.

### Ch. 2 — Language models, reasoning, agent architecture

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Multi-oracle consensus / cross-model verification | ✅ | RES-004a/RES-004b (`remora/cascade/stages.py`, verifier, diversity). |
| Governed context flow / memory layers | 🟡 | RES-008 governance framing only; REMORA does not implement the Nested Learning architecture. |
| The agent itself (planning, tool loop, model) | ⚪ | REMORA governs a proposed action; it does not build or replace the agent. |
| Mechanistic interpretability | ⚪ | `landscape.not_implemented`: model-internal feature/circuit analysis is out of scope; RES-001 is post-hoc *policy* causality. |

### Ch. 3 — Evaluation, benchmarks, capability measurement

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| External adversarial benchmark | ✅ | REM-014 AgentHarm (`results/external_benchmark_agentharm_v1.json`). **Intent-gating, not interception** (INTERCEPTION_NOTES); routing accuracy, not execution prevention. |
| Tool-call safety benchmark | ✅ | RES-005 v2; deterministic simulator, effective N=70, cluster-level CIs. Not field-deployment proof. |
| Selective accuracy on held-out split | ✅ | CLAIM-004, now **superseded** by CLAIM-012; N_accepted=18, p=0.052, wide CI (directional). |
| Repeated-run consistency (pass^k) | ⛔ | REMORA does not measure its own decision consistency over repeated runs — a `tau-bench`-style metric the compendium flags as the one that matters most in drift. |
| Long-horizon / computer-use safety eval | ⚪ | REMORA governs single proposed actions; long-horizon and computer-use capability measurement are out of scope. |

### Ch. 4 — Security, attacks, robustness

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Critical-action routing / tool-call gate | ✅ | RES-005 + CAP-001 decision engine; hard-block invariants run first (Stage 1). |
| Deterministic hard-block policy invariants | ✅ | CAP-001; cannot be overridden by any probabilistic oracle. |
| Prompt-injection defence | 🟡 | **Policy-level intent-gating, not structural defence.** REMORA does not separate instruction/data channels (StruQ) or confine capabilities around the model (CaMeL); true tool-call interception is unverified (INTERCEPTION_NOTES). |
| Lethal-trifecta containment | 🟡 | Policy can gate privileged/egress actions per decision, but REMORA does not structurally break the trifecta at the model boundary. |
| Memory-lifecycle security | 🟡 | AROMER memory governance exists (`aromer_memory_governance_v1.md`); not a full write/store/retrieve/delete threat-model coverage. |
| Agentic detection & response (telemetry correlation) | ⛔ | CAP-011 is instrumentation only ("no deployed collector pipeline"). No ADR/monitoring layer correlates tool-call telemetry to detect a hijacked agent. |

### Ch. 5 — Governance, standards, accountability

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Policy-as-code + PDP/PEP separation | ✅ | CAP-001/003; signed PDP→PEP token (mandatory expiry, one-time jti). |
| Human-approval workflow | ✅ | CAP-007 review queue, TTL-to-ABSTAIN, approval-freshness re-gate. |
| Audit ledger (hash-chained) | ✅ | CAP-005 (`PERSISTED_ATOMIC` when a durable store is configured). Tamper-evident, not tamper-proof (no WORM). |
| Fail-closed degradation | ✅ | CAP-008 G0–G4 ladder with tamper-evident transition log. |
| NIST/ISO/EU-AI-Act crosswalk | ✅ (reference) | RES-009 + TOGAF package; the compendium's own Ch. 11 crosswalk aligns. Reference-design grade, not certified. |
| Verifiable-claims discipline | ✅ | Claim register + artifact manifest + `make audit`; this repo's core hygiene. |
| RSP-style if-then capability commitments | 🟡 | AII bands + release gates are threshold-driven, but not a formal responsible-scaling commitment framework. |

**Read:** governance is REMORA's strongest area: reference-design maturity, with the honest ceiling that it is not externally certified.

### Ch. 6 — MLOps, system design, production operations

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Policy/config versioning + reproducible replay | 🟡 | Policy bundle hashing + shadow replay (`make shadow-replay`) give decision reproducibility; not full agent-config (prompt/tool/memory) versioning discipline. |
| Observability (OTel GenAI spans) | 🟡 | CAP-011 instrumentation helpers; no deployed collector. |
| MLOps platform (pipelines, SRE error budgets, drift) | ⚪ | `landscape.not_implemented`: REMORA consumes host infra, it is not an MLOps platform. |

### Ch. 7 — Provenance, identity, software supply chain

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Decision provenance | 🟡 | CAP-005 hash-chained envelope; tamper-evident, needs external WORM for tamper-resistance. |
| Delegated authority / workload identity | 🟡 | CAP-006 A2A delegation envelope (HMAC reference — production needs JWS/COSE + trust anchors); CAP-003 signed execution token. |
| SBOM/ML-BOM, SLSA, Sigstore, SPIFFE, C2PA | ⚪ | `landscape.not_implemented`: artifact/supply-chain provenance assumed provided by the host. |

### Ch. 8 — Formal methods, verification, guaranteed safety

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Verify-the-cage: deterministic invariants | 🟡 | Stage-1 hard-block invariants are tested; OPA/Rego conformance is CI-gated (CAP-002). This is tested policy logic, not formal proof. |
| Shielding analogy | 🟡 | PhaseAwareGuardrail plays a shield-like role; not a formally synthesised shield with a proof. |
| Neural-network verification / guaranteed-safe AI | ⚪ | `landscape.not_implemented`: proofs about the governed model are out of scope; the safety floor is a policy property, not a proved model property. |

### Ch. 9 — Fairness, privacy, data protection

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Access control / tenant isolation | 🟡 | CAP-009 RBAC (eight roles) + tenant-scoped audit chain (`test_rbac_isolation`); symmetric bearer tokens, OIDC/MFA is roadmap. |
| Differential privacy, membership-inference defence, fairness metrics | ⚪ | `landscape.not_implemented`: REMORA governs execution permission, not model training or fairness measurement. |

### Ch. 10 — Assurance cases, guardrails, runtime governance

| Control area | Grade | REMORA evidence / caveat |
|--------------|-------|--------------------------|
| Runtime policy enforcement outside the model | ✅ | CAP-001/003/008; this is REMORA's heartland (AgentSpec/Progent/MI9 family). |
| Guardrails / selective routing | ✅ | RES-002/005 (PhaseAwareGuardrail). |
| Stop / escalate / degrade / explain | ✅ | ESCALATE routing, degradation ladder (CAP-008), causal explanation (RES-001). |
| Assurance case (structured argument) | ✅ | `docs/assurance/assurance_case_v1.md`. |
| AI-control (assume-subversive) protocol | 🟡 | Hard-block invariants + PDP/PEP separation assume untrusted model output, but there is no formal control-protocol red-team evaluation. |
| Trace-to-trust automation | 🟡 | Audit chain + shadow replay exist; assurance cases are not auto-generated/refreshed from live traces. |

## Prioritised roadmap (the in-scope gaps only)

These are the 🟡/⛔ items that are *within* REMORA's mission. Out-of-scope (⚪)
areas are boundaries, not backlog; see the recap below. Priority reflects
distance from REMORA's core value proposition and how load-bearing the gap is
for honest claims.

| # | Gap | Priority | What would close it |
|---|-----|----------|---------------------|
| 1 | Structural prompt-injection defence + proven interception (Ch. 4) | **High** | Move beyond intent-gating: instruction/data separation or capability confinement (StruQ/CaMeL-style), and land the `inspect_tools_probe.py` result that proves true tool-call interception (per CLAUDE.md + INTERCEPTION_NOTES). This is the single biggest honesty caveat today. |
| 2 | Independent verification (REM-021) | **High** | Cross-cutting blocker to `EXTERNALLY_VERIFIED`. Every ✅ above stays internally-attested until this closes. Already the known shadow-mode exit gate. |
| 3 | NLI semantic-entropy backend, actually evaluated (Ch. 1) | Medium | Wire the existing NLI backend into a reported run and record the result, closing the "built but unused" gap (NEGATIVE_RESULTS §3). |
| 4 | Agentic detection & response layer (Ch. 4) | Medium | Deploy a collector + correlation over CAP-011 telemetry to detect a hijacked agent from tool-call/protocol traces. |
| 5 | Decision-provenance & delegation hardening (Ch. 7) | Medium | External WORM/append-only audit storage; JWS/COSE + trust anchors for CAP-006; durable jti/queue stores for CAP-003/007. Needed for `ENFORCED_PRODUCTION`. |
| 6 | Repeated-run consistency (pass^k) self-eval (Ch. 3) | Medium | Measure REMORA's own decision consistency over repeated runs of the same scenario — the drift-relevant metric the compendium stresses. |
| 7 | Trace-to-trust automation (Ch. 10) | Low–Medium | Generate/refresh the assurance case from audit traces with a freshness requirement, instead of hand-maintaining it. |

## Deliberately out of scope (recap — not roadmap)

Recorded machine-readably in `research_control_matrix_v1.yaml` →
`landscape.not_implemented`, so the boundary is explicit and auditable:

- Formal methods / neural-network verification / guaranteed-safe AI: REMORA verifies its policy layer by tests, not proofs about the governed model.
- Provenance / SBOM / SLSA / SPIFFE / C2PA: artifact and supply-chain integrity are assumed provided by the host environment.
- Fairness / differential privacy / training-data protection: REMORA governs inference-time execution, not model training.
- Full MLOps platform: data pipelines, SRE error budgets, and deployment infrastructure are the host's responsibility.
- Mechanistic interpretability: model-internal feature/circuit analysis of the governed model.

## Bottom line

Against the compendium's ten-chapter control stack, REMORA is **strong and
tested where it claims to operate** (uncertainty (Ch. 1), governance (Ch. 5),
and runtime governance (Ch. 10)) and **honest about its edges**: prompt-injection
defence is intent-gating rather than structural, detection-and-response is not
deployed, and semantic-entropy quality is unproven. The largest single lever is
gap #1 (structural injection defence + proven interception); the largest
*status* lever is gap #2 (independent verification), which alone separates every
internally-attested control from external verification. None of the ⚪ areas are
deficiencies; they are the deliberate scope of a governance overlay.
