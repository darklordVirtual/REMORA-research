# REMORA × EU AI Act and NSM Grunnprinsipper Mapping

**Status:** internal mapping, not independently audited. Not legal advice.
**Created:** 2026-07-20
**References:** Regulation (EU) 2024/1689 (AI Act); Regulation (EU) 2016/679
(GDPR); NSM *Grunnprinsipper for IKT-sikkerhet* (v2.1).
**Companion mappings (same controls, different regime):**
[`governance/nist_ai_rmf_mapping.md`](nist_ai_rmf_mapping.md),
[`security/owasp_genai_mapping.md`](../security/owasp_genai_mapping.md).

This document maps REMORA's **existing technical controls** to the EU AI Act and
to NSM's four functions. It follows the principle *build the controls once and
map them to every regime — never the reverse*: each control below is a real
artifact on disk, cited once, and points at every regime function it serves. The
NIST AI RMF and OWASP GenAI documents are alternative views on the same control
set.

Because REMORA is a research-grade governance overlay in `SHADOW_ONLY` mode,
**"Implemented" means the control exists in code and is tested; it does not mean
the obligation is discharged for any specific deployment.** A deployer remains
responsible for its own risk classification, DPIA/FRIA, and conformity work.

---

## Part A — EU AI Act (Regulation (EU) 2024/1689)

The Act's obligations for high-risk systems are addressed article by article.
Whether a given deployment *is* high-risk (Annex III) is a deployer
determination, not something REMORA decides.

| Article | Obligation | REMORA control | Path | Status |
|---|---|---|---|---|
| Art. 9 | Risk management system; conservative, fail-safe default | Hard-block floor + machine-verifiable invariants; unknown tier/action fail closed to VERIFY; risk-tiered profiles | `remora/policy/decision_engine.py`, `remora/policy/invariants.py`, `schemas/risk-profiles.yaml` | Implemented (design) |
| Art. 10 | Data and data governance; no tuning on evaluation data | AST evaluation-leakage detector gating CI; blinded benchmark protocol | `scripts/check_no_evaluation_leakage.py`, `benchmarks/toolcall_blind_v3/` | Implemented |
| Art. 11 + Annex IV | Technical documentation | Threat model, resilience plan, AI-assisted adversarial security review, remediation register, architecture, preserved negative results | `docs/assurance/threat_model_v1.md`, `docs/assurance/resilience_plan_v1.md`, `docs/assurance/ai_assisted_adversarial_security_review_v1.md`, `docs/assurance/remediation_register.yaml`, `ARCHITECTURE.md`, `NEGATIVE_RESULTS.md` | Implemented |
| Art. 12 | Automatic logging / record-keeping | Canonical `DecisionEnvelope`; envelope-level and atomic per-tenant tamper-evident hash chains | `remora/governance/envelope.py`, `remora/governance/audit_chain.py`, `remora/governance/tenant_chain.py` | Implemented |
| Art. 13 | Transparency of the decision | Envelope carries action, reasons, phase observables, policy version; flat export for downstream consumers | `remora/governance/envelope.py`, `schemas/decision_envelope_schema.yaml` | Implemented |
| Art. 14 | Human oversight with ability to intervene and stop | Review queue (TTL→ABSTAIN), approval-freshness re-gate, per-profile approval roles, PDP/PEP enforcement point, opt-in PreToolUse hook | `remora/governance/review_queue.py`, `servers/execution_api.py`, `remora/enforcement/gate.py`, `scripts/remora_hook.py` | Implemented (design); operational layer is roadmap |
| Art. 15 | Accuracy, robustness, cybersecurity | Fail-closed engine + monotonicity over external PDP; degradation ladder; Lyapunov stability controller; drift monitor; credential-derived auth, RBAC, rate limiting, application-level tenant isolation (DB-enforced RLS is roadmap) | `remora/policy/opa_adapter.py`, `remora/governance/degradation.py`, `remora/lyapunov.py`, `remora/governance/drift_monitor.py`, `servers/api.py` | Implemented |
| Art. 17 | Quality management system | Remediation register (P0→P4 gates), claim register + provenance gate, change log | `docs/assurance/remediation_register.yaml`, `docs/assurance/claim_register_v1.yaml`, `scripts/check_claim_provenance.py` | Partial |
| Art. 27 | Fundamental-rights impact assessment (FRIA), where required | — | — | Gap (see §C, REM-031) |
| Art. 73 | Serious-incident reporting | Degradation-mode transitions recorded; drift monitor severity; OTel traces | `remora/governance/degradation.py`, `remora/observability/otel.py` | Partial (telemetry exists; reporting process is a deployer concern) |

## Part B — NSM Grunnprinsipper for IKT-sikkerhet

NSM structures controls into four functions: **identifisere, beskytte,
opprettholde, håndtere.** Norwegian deployers can reuse the same controls; note
that NIS2 and DORA incident and supplier-governance obligations often bind
sooner and harder than the AI Act, and their foundations are reusable here.

| Function | What it requires | REMORA control | Path |
|---|---|---|---|
| **Identifisere** | Know the system, its risks, and its data | System register (claim/remediation registers), risk-tier profiles, threat model, memory attack-surface inventory | `docs/assurance/claim_register_v1.yaml`, `schemas/risk-profiles.yaml`, `docs/assurance/threat_model_v1.md`, `docs/assurance/aromer_memory_governance_v1.md` |
| **Beskytte** | Prevent unsafe actions and unauthorised access | Hard-block floor + invariants; PDP/PEP signed one-time token; RBAC + credential-derived identity + application-level tenant isolation; PreToolUse hook | `remora/policy/decision_engine.py`, `remora/enforcement/gate.py`, `servers/api.py`, `scripts/remora_hook.py` |
| **Opprettholde** | Keep controls working; logging and continuity | Tamper-evident audit chains; recorded G0–G4 degradation ladder; OTel tracing; CI leakage/claim gates | `remora/governance/audit_chain.py`, `remora/governance/degradation.py`, `remora/observability/otel.py`, `scripts/check_no_evaluation_leakage.py` |
| **Håndtere** | Detect, escalate, and respond to incidents | Drift monitor; Lyapunov abort signal; escalate-to-human review lifecycle; per-tenant durable audit chain for forensics | `remora/governance/drift_monitor.py`, `remora/lyapunov.py`, `remora/governance/review_queue.py`, `remora/governance/tenant_chain.py` |

## Part C — Gaps (honest, tracked)

These obligations are **not** met by an existing REMORA control. They are
tracked in [remediation_register.yaml](../assurance/remediation_register.yaml)
and disclosed in the [assurance case](../assurance/assurance_case_v1.md).

| Obligation | Gap | Tracked |
|---|---|---|
| Art. 27 FRIA / GDPR Art. 35 DPIA | No DPIA or FRIA artifact exists | REM-031 (roadmap) |
| Art. 9 / Annex IV intended-purpose record | No runtime intended-use classification | REM-031 |
| Art. 10 / Art. 15 non-discrimination | No fairness / disparate-impact evaluation (general-domain benchmark only) | Gap; NIST MS-4 |
| GDPR minimisation / erasure; Art. 12 retention | `data_classification` / `retention_policy` envelope fields are integration-provided, not enforced; AROMER memory has no deletion/retention window | REM-031, REM-043 |
| Art. 12 durable integrity | Local HMAC only; no KMS/HSM, RFC 3161 timestamps, WORM anchoring (REM-025); no OIDC-bound approver identity (REM-022 §8, REM-042) | REM-025, REM-042 |
| Art. 15 tenant isolation | Application/store-level only; not DB-enforced (no Postgres RLS, per-tenant crypto domains) | REM-026 |
| Art. 14 operational oversight | SLA, escalation taxonomy, alarm-fatigue, on-call, routing are design-only | REM-021, REM-042 |
| Art. 15 tool-call interception | Intent-gating only; interception unverified | REM-030 |

## Part D — Regulatory timeline (verify against current legal state)

The AI Act obligation timeline is **politically movable** and must be checked
against the current legal state before any compliance decision (the ongoing
omnibus process is precisely why): in force 2024-08-01; prohibitions +
AI-literacy 2025-02-02; GPAI 2025-08-02; main application 2026-08-02; selected
high-risk 2027-12-02; product-integrated high-risk 2028-08-02.

**Norwegian implementation** runs through the EEA into existing regimes, with a
split supervisory landscape: Datatilsynet (privacy), sector authorities such as
Finanstilsynet and NKOM, and NSM (security). NIS2 and DORA often apply first and
most concretely; their incident-handling, supplier-governance, and
board-accountability requirements are a reusable foundation for AI governance.

*This mapping is descriptive engineering documentation, not legal advice. A
deployer must obtain its own legal assessment.*
