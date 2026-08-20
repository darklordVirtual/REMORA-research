# REMORA External Review Panel

## Competence, scope, and sign-off matrix v1

| Field | Value |
|---|---|
| Document status | Normative reviewer and scope matrix |
| Version | 1.0 |
| Date | 2026-07-25 |
| Repository | `darklordVirtual/REMORA-research` |
| Primary gate | REM-021 — independent human review |
| Related gates | REM-023, REM-024, REM-025, REM-026, REM-027, REM-030, REM-031, REM-037, REM-045, REM-046 |
| Current profile | `SHADOW_PILOT` / `SHADOW_ONLY` |
| Owner | Stian Skogbrott |

> **Decision:** REMORA is too broad for any single person to issue a credible
> external sign-off alone. REM-021 shall be conducted as a small, independent
> panel with separated disciplinary mandates. Every conclusion shall be bound
> to a specific commit, an explicit scope, and one specific release profile.

This document establishes **who is qualified to assess what**. It complements
the [Independent Review Protocol](independent_review_protocol_v1.md), which
describes the review questions. In any conflict over reviewer competence, panel
coverage, or signature requirements, this matrix governs.

A panel sign-off is not the same as accredited certification, a legal
compliance opinion, or a guarantee that a specific production environment is
safe.

---

## 1. Panel model

### 1.1 Mandatory roles

| ID | Discipline | Minimum qualification | Primary mandate | Required for |
|---|---|---|---|---|
| **R1** | Scientific method and statistics | PhD and peer-reviewed publication in selective/conformal prediction, risk control, uncertainty quantification, calibration, ensemble methods, or AI evaluation | Validate method, inference, benchmark design, and that the claims do not exceed the evidence | REM-021, research and claim sign-off |
| **R2** | Agentic AI security and production architecture | Senior security architect or researcher with demonstrated experience in capability security, PDP/PEP, execution leases, identity binding, replay protection, distributed systems, and agent red-teaming | Attempt to bypass the controls and validate fail-closed enforcement against actual execution paths | REM-021; `LIMITED_ENFORCEMENT`; REM-024/030 |
| **R3** | AI assurance and governance | Experienced assessor with demonstrated work against ISO/IEC 42001, ISO/IEC 23894, NIST AI RMF, EU AI Act, assurance cases, and regulated industries | Verify traceability from risk and claim to control, code, test, evidence, and operational ownership | REM-021; overall panel conclusion |
| **R4** | Software and supply-chain review | Independent principal engineer with strong Python, API, PostgreSQL, distributed-systems, packaging, and CI/CD competence | Validate installability, state, concurrency, release, dependencies, and consistency between documented and actual API | Production maturity; issue #14/#15; REM-027/037/045 |
| **R5** | License and IP counsel | Lawyer/counsel with demonstrated experience in open-source/source-available licensing, copyright, CLAs, datasets, software transactions, and commercial licenses | Separate legal assessment of the chain of rights and the BUSL/commercial licensing | Legal clearance; not a technical REM-021 signature |

### 1.2 Minimum staffing

| Purpose | Required staffing | Boundary |
|---|---|---|
| Research and claim review | R1 + R3 | Cannot attest enforcement or production readiness |
| REM-021 / `CONTROLLED_PILOT` | R1 + R2 + R3 | R2 must cover the security architecture; a documentation-only review is not sufficient |
| Production maturity | R1 + R2 + R3 + R4 | Requires that open production findings and the relevant release gates are actually closed |
| License/IP | R5 | Separate legal workstream and separate conclusion |
| Customer-specific industrial pilot | The panel above + the customer's independent domain/OT authority | The sign-off applies only to the assessed tool surface, risk class, and operating context |

R1, R2, and R3 shall normally be three different people. R4 may be combined with
R2 only if that person documents both offensive security competence and
production/supply-chain competence. R5 shall always be a separate legal mandate.

### 1.3 Roles that are not sufficient on their own

The following may provide useful commercial or architectural feedback, but
cannot alone attest to REMORA's scientific and security quality:

- hiring manager;
- generalist enterprise architect;
- generalist LLM/prompt consultant;
- internal REMORA contributor;
- AI-generated review without a named, accountable human reviewer;
- security reviewer without statistical competence;
- researcher without practical enforcement or attack experience.

---

## 2. Common requirements for all reviewers

Every reviewer shall:

1. state name, institution, role, and demonstrable competence;
2. sign a conflict-of-interest declaration before the review starts;
3. be independent of Stian Skogbrott, Luftfiber AS, and REMORA development;
4. record commit SHA, environment, policy bundle, configuration, and dataset version;
5. state included and excluded scope;
6. describe the methods, commands, tests, and attacks actually run;
7. classify findings as `CRITICAL`, `MAJOR`, `MINOR`, or `INFORMATIONAL`;
8. require retest of every remediated `CRITICAL` and `MAJOR` finding;
9. issue `PASS`, `CONDITIONAL PASS`, or `FAIL` only for their own mandate;
10. state which changes would invalidate the conclusion.

The review shall be bound to a frozen commit. Changes to the policy bundle,
model set, tool surface, identity/tenant model, benchmark corpus, enforcement
architecture, or threat model shall trigger targeted re-review.

---

## 3. Master mapping: discipline to code and evidence

| Area | Owner | Primary code | Tests and evidence | Question to decide |
|---|---|---|---|---|
| Selective prediction and risk/coverage | R1 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`guardrail.py`](../../remora/selective/guardrail.py), [`risk_coverage.py`](../../remora/selective/risk_coverage.py) | [`tests/test_selective_router.py`](../../tests/test_selective_router.py), `results/selective_*` | Are threshold selection, coverage, and holdout interpretation statistically valid and correctly scoped? |
| CRC status | R1 | [`remora/selective/crc.py`](../../remora/selective/crc.py) | [`tests/test_crc.py`](../../tests/test_crc.py), [`paper/remora_mathematical_supplement.md`](../../paper/remora_mathematical_supplement.md) | Is the component correctly described as an empirical selector — not a CRC procedure with a distribution-free guarantee? |
| PVD and ensemble disagreement | R1 | [`remora/selective/pvd.py`](../../remora/selective/pvd.py), [`remora/correlation.py`](../../remora/correlation.py) | [`tests/test_pvd.py`](../../tests/test_pvd.py), [`paper/remora_paper.md`](../../paper/remora_paper.md) | Is PVD correctly scoped as a PVD-inspired offline agreement score, and is model correlation handled honestly? |
| Confidence intervals and running FAR | R1 | [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py), [`confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | `tests/test_confidence_sequence.py`, [`results/far_confidence_sequence_v1.json`](../../results/far_confidence_sequence_v1.json) | Are the Wilson / anytime-valid intervals applied to the correct unit of analysis and under the correct assumptions? |
| Benchmark design and claim inference | R1 | [`experiments/`](../../experiments), [`scripts/check_no_evaluation_leakage.py`](../../scripts/check_no_evaluation_leakage.py) | [`claim_register_v1.yaml`](claim_register_v1.yaml), [`statistical_analysis_plan.md`](statistical_analysis_plan.md), [`benchmark_audit_v1.md`](benchmark_audit_v1.md), `results/` | Are effective N, clustering, leakage, exclusions, post-hoc choices, and baseline comparison correct? |
| Decision rules and policy floor | R2 | [`remora/policy/decision_engine.py`](../../remora/policy/decision_engine.py), [`observation.py`](../../remora/policy/observation.py), [`opa_adapter.py`](../../remora/policy/opa_adapter.py) | [`tests/test_rem017_policy_mutations.py`](../../tests/test_rem017_policy_mutations.py), [`tests/test_opa_parity.py`](../../tests/test_opa_parity.py) | Can any probabilistic or adapter-based path weaken a hard denial or create fail-open? |
| PDP token and PEP | R2 | [`remora/enforcement/token.py`](../../remora/enforcement/token.py), [`gate.py`](../../remora/enforcement/gate.py) | [`tests/test_rem013_pdp_pep_boundary.py`](../../tests/test_rem013_pdp_pep_boundary.py), `tests/test_token_hardening.py`, [`policy_engine_audit_v1.md`](policy_engine_audit_v1.md) | Is the token signed, time-bounded, payload-bound, and single-use in a way that cannot be bypassed? |
| Execution lease and dispatcher | R2 | [`remora/enforcement/lease.py`](../../remora/enforcement/lease.py) | [`tests/test_execution_lease.py`](../../tests/test_execution_lease.py), [issue #13](https://github.com/darklordVirtual/REMORA-research/issues/13), [issue #16](https://github.com/darklordVirtual/REMORA-research/issues/16) | Does the PEP hold the real credentials, and does it deny all mismatch, replay, and stale-policy attempts before any side effect? |
| API's actual execution path | R2 + R4 | [`servers/execution_api.py`](../../servers/execution_api.py), [`servers/api.py`](../../servers/api.py) | [`tests/test_execution_api.py`](../../tests/test_execution_api.py), [`docs/07-api-reference.md`](../07-api-reference.md), [issue #13](https://github.com/darklordVirtual/REMORA-research/issues/13) | Does the endpoint actually perform what the documentation promises, exactly once, with a traceable effect status? |
| Actor, tenant, and RBAC binding | R2 + R3 | [`servers/api.py`](../../servers/api.py), [`schemas/risk-profiles.yaml`](../../schemas/risk-profiles.yaml) | [`tests/test_rbac_isolation.py`](../../tests/test_rbac_isolation.py), `tests/test_rbac_role_contract.py`, [`rbac_design_v1.md`](rbac_design_v1.md) | Does authority come from authenticated context, and is isolation proven negatively across tenants? |
| Review queue, replay state, and idempotency | R2 + R4 | [`remora/governance/review_queue.py`](../../remora/governance/review_queue.py), [`servers/execution_api.py`](../../servers/execution_api.py) | [`tests/test_review_queue.py`](../../tests/test_review_queue.py), [issue #15](https://github.com/darklordVirtual/REMORA-research/issues/15) | Do approvals, JTI/nonces, and idempotency survive restart and multiple replicas without double execution? |
| Audit chain and persistent state | R2 + R4 | [`remora/governance/audit_chain.py`](../../remora/governance/audit_chain.py), [`tenant_chain.py`](../../remora/governance/tenant_chain.py) | [`tests/test_execution_api.py`](../../tests/test_execution_api.py), [`decision_envelope_audit.md`](../evidence/decision_envelope_audit.md) | Are sequence, append, tenant binding, and verification atomic and durable, and is "tamper-evident" correctly scoped? |
| DecisionEnvelope and traceability | R3 | [`remora/governance/envelope.py`](../../remora/governance/envelope.py) | [`assurance_case_v1.md`](assurance_case_v1.md), [`capability_register_v1.yaml`](capability_register_v1.yaml), [`remediation_register.yaml`](remediation_register.yaml) | Can an enterprise assessor trace the decision from input and policy through to evidence, review, and audit without documentation drift? |
| Human oversight and reviewer handoff | R3 | [`remora/governance/review_queue.py`](../../remora/governance/review_queue.py) | [`human_oversight_operations_v1.md`](human_oversight_operations_v1.md), [`release_profiles_v1.yaml`](release_profiles_v1.yaml) | Are there clear accountability, TTL, re-gate, severity routing, identity, SLA, and operational escalation? |
| Wheel, API, and resource loading | R4 | [`pyproject.toml`](../../pyproject.toml), [`servers/`](../../servers), [`schemas/`](../../schemas) | [issue #14](https://github.com/darklordVirtual/REMORA-research/issues/14), `.github/workflows/ci.yml` | Can the documented API be installed and started from the built wheel in an empty environment without a repository checkout? |
| CI, tests, and supply chain | R4 | [`pyproject.toml`](../../pyproject.toml), [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), [`.github/CODEOWNERS`](../../.github/CODEOWNERS) | [`reproducibility_scorecard_v1.md`](reproducibility_scorecard_v1.md), REM-027/037/045 | Are dependencies locked, SBOM/provenance produced, artifacts signed, and critical code covered by adequate gates? |
| BUSL, CLA, third party, and commercial IP | R5 | [`LICENSE`](../../LICENSE), [`LICENSES/BUSL-1.1.txt`](../../LICENSES/BUSL-1.1.txt), [`LICENSING.md`](../../LICENSING.md), [`COMMERCIAL_LICENSE.md`](../../COMMERCIAL_LICENSE.md) | [`CONTRIBUTING.md`](../../CONTRIBUTING.md), [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md), git/contribution history | Does the licensor have the right to relicense every relevant contribution and dataset, and are the BUSL/commercial terms consistent and enforceable? |

---

## 4. R1 — Scientific method and statistics

### 4.1 Qualification requirements

R1 shall hold a PhD and demonstrated publication in at least one of:

- selective prediction, conformal prediction, or risk control;
- uncertainty quantification and calibration;
- ensemble methods and correlated models;
- AI evaluation, benchmark design, or statistical inference.

They must be able to read both the Python implementation and the
method/results section of the paper. A purely domain or governance background
is not sufficient.

### 4.2 Mandatory review scope

| Part | Code/evidence | Mandatory check |
|---|---|---|
| Empirical selective router | `remora/selective/conformal.py`, `guardrail.py`, `risk_coverage.py` | Splits, threshold search, ties, unattainable thresholds, coverage, and accepted-set risk |
| CRC status | `remora/selective/crc.py`, `tests/test_crc.py` | Confirm that `WeightedEmpiricalSelectiveRouter` receives no CRC guarantee; verify the missing finite-sample term and the non-monotone loss |
| PVD status | `remora/selective/pvd.py`, `tests/test_pvd.py` | Verify that PVD is not presented as a validated uncertainty bound or online safety metric |
| Correlation and thermodynamic measures | `remora/correlation.py`, `remora/thermodynamics.py`, `remora/research_attic/statphys/potts.py` | Verify dependency assumptions, the ρ clamp, `h_bound`, the λ configuration, and analogy-versus-theorem language |
| Holdout and calibration | `results/selective_n500_holdout_results.json`, `results/selective_trust_curve_results.json` | Separate the calibration-set upper bound from true holdout; always report N accepted and CI |
| Tool-call v2/v3 | `results/toolcall_benchmark_v2_results.json`, `results/toolcall_benchmark_v2_significance.json`, `results/toolcall_blind_v3_results.json` | Use the template cluster as the unit of analysis where 700 tasks are 70 templates × 10 variants |
| REM-014 | `results/external_benchmark_agentharm_v1.json`, `tests/test_rem014_external_benchmark.py` | Separate the imported historical result from reproduction in this repository; verify FAR/FBR and the intent-gating scope |
| REM-019/020 | `results/false_accept_regression_v1.json`, `results/longitudinal_stability_v1.json` | Assess corpus provenance, the two exclusions, the policy change, the missing full time series, and stopping assumptions |
| Claim check | `docs/assurance/claim_register_v1.yaml`, `paper/`, `README.md`, `NEGATIVE_RESULTS.md` | Every numeric claim shall have the correct N, CI, unit of analysis, evidence level, and caveat |

### 4.3 Minimum tests R1 shall run

```bash
python -m pytest \
  tests/test_crc.py \
  tests/test_pvd.py \
  tests/test_selective_router.py \
  tests/test_confidence_sequence.py \
  tests/test_check_claim_provenance.py \
  tests/test_paper_no_stale_claims.py -v

python scripts/check_claim_provenance.py
```

R1 shall additionally regenerate or independently recompute a representative
sample of the main results. Structural validation of a JSON file alone is not
external replication.

### 4.4 Sign-off criterion

R1 may issue `PASS` only when:

- effective N and the dependency structure are correct;
- confidence intervals and tests can be recomputed;
- CRC and PVD have the correct epistemic status in code, paper, and claim register;
- no headline claim lacks a scope boundary;
- all method-critical findings are remediated and retested.

---

## 5. R2 — Agentic AI security and production architecture

### 5.1 Qualification requirements

R2 shall document practical experience with:

- capability-based security and short-lived execution leases;
- authentication, actor/tenant binding, and replay protection;
- policy enforcement, tool execution, and fail-closed design;
- distributed transactions, idempotency, and audit chains;
- offensive testing of LLM, agent, or API systems.

Architecture reading alone is not sufficient. R2 shall run code, build a threat
model, and attempt real bypasses.

### 5.2 Mandatory attack classes

| Attack | Target | Expected safe outcome |
|---|---|---|
| Direct tool call without PEP | Dispatcher/API | No side effect; explicit denial and audit |
| Token/lease replay | JTI/nonce store | Exactly one winner, including across replicas and restart |
| Argument mutation | Canonical payload binding | Denial before tool invocation |
| Actor/tenant swap | Authenticated context | Denial; headers/body cannot self-assign authority |
| Policy rotation | `policy_bundle_hash` | Old lease denied per the documented rotation rule |
| Stolen or unsigned token | Signature/key path | Fail-closed |
| Timeout/exception after dispatch start | Execution state | Lease burned; result becomes an auditable `failed` or `unknown`, never a safe retry without reconciliation |
| Concurrent duplicate | Idempotency/transaction | Tool runs at most once |
| Legacy/alternate endpoint | `/v1/assess`, hook, and direct adapter | No route around the production PEP |
| Control plane unavailable | Degradation G0–G4 | Production profile denies actions above the permitted risk level |

### 5.3 Special focus on open production findings

- [Issue #13](https://github.com/darklordVirtual/REMORA-research/issues/13):
  `/v1/execution/execute` must actually be wired to the credential-holding
  `GovernedToolDispatcher`; an authorized response with no side effect is not
  end-to-end execution.
- [Issue #15](https://github.com/darklordVirtual/REMORA-research/issues/15):
  the review queue, approvals, JTI, nonces, and idempotency state must be
  shared, durable, and atomic.
- [Issue #16](https://github.com/darklordVirtual/REMORA-research/issues/16):
  the production dispatcher must require an active policy-bundle hash and deny
  stale leases.

### 5.4 Minimum tests R2 shall run and extend

```bash
python -m pytest \
  tests/test_rem013_pdp_pep_boundary.py \
  tests/test_execution_lease.py \
  tests/test_execution_api.py \
  tests/test_tool_call_hash_binding.py \
  tests/test_review_queue.py \
  tests/test_rbac_isolation.py \
  tests/test_fail_closed_hardening.py \
  tests/test_degradation_ladder.py -v
```

R2's report shall include its own adversarial test cases, raw test results, and
negative evidence that the side effect did not occur for denied attempts.

### 5.5 Sign-off criterion

R2 cannot approve `LIMITED_ENFORCEMENT` until:

- the PEP holds the real downstream credentials;
- issues #13, #15, and #16 are resolved for the assessed deployment;
- tool interception has been tested externally;
- no open `CRITICAL` or `MAJOR` bypass affects the profile;
- failure/unknown state, replay, and idempotency are demonstrated under concurrency.

---

## 6. R3 — AI assurance and governance

### 6.1 Qualification requirements

R3 shall have documented assessor experience with several of:

- [ISO/IEC 42001](https://www.iso.org/standard/42001) — AI management systems;
- [ISO/IEC 23894](https://www.iso.org/standard/77304.html) — AI risk management;
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework);
- EU AI Act and sector/risk classification;
- assurance cases, defeaters, traceability, and evidence management;
- safety-critical or regulated industries.

Familiarity with the standards is not enough. R3 must be able to assess whether
the control evidence is usable by an enterprise customer and distinguish
between mapping, readiness, conformity assessment, and certification.

### 6.2 Control chain to be verified

For each material claim, R3 shall be able to follow this chain without logical
gaps:

```text
risk/requirement
  -> assurance claim
  -> technical control
  -> implemented code path
  -> test/attack
  -> versioned result
  -> residual risk/defeater
  -> release profile and accountable owner
```

### 6.3 Mandatory documents and code

| Object | Primary reference | R3 shall verify |
|---|---|---|
| Assurance case | [`assurance_case_v1.md`](assurance_case_v1.md) | That the goals are scoped, defeaters are open where the control is not proven, and the argument is not presented as certification |
| Claim register | [`claim_register_v1.yaml`](claim_register_v1.yaml) | That evidence level, artifact, N, caveat, and reproduce instructions are correct |
| Capability register | [`capability_register_v1.yaml`](capability_register_v1.yaml) | That `IMPLEMENTED_LIBRARY`, `WIRED_API_PATH`, `ENFORCED_PRODUCTION`, and `EXTERNALLY_VERIFIED` are not conflated |
| Remediation and release | [`remediation_register.yaml`](remediation_register.yaml), [`release_profiles_v1.yaml`](release_profiles_v1.yaml) | That profile elevation happens only after documented closure |
| DecisionEnvelope | [`remora/governance/envelope.py`](../../remora/governance/envelope.py) | That identity, policy version, evidence, review, history, and audit are sufficient and actually populated |
| Human oversight | [`human_oversight_operations_v1.md`](human_oversight_operations_v1.md), [`review_queue.py`](../../remora/governance/review_queue.py) | That accountability, TTL, re-gate, SLA, and escalation are operationally manageable |
| Regulatory mappings | [`eu_ai_act_nsm_mapping.md`](../governance/eu_ai_act_nsm_mapping.md), [`nist_ai_rmf_mapping.md`](../governance/nist_ai_rmf_mapping.md) | That the mappings point to existing controls and are not presented as legal compliance |

### 6.4 Sign-off criterion

R3 may issue an overall panel `PASS` only when:

- R1 and R2 have signed their own mandates;
- every mandatory scope row has an owner and evidence;
- open defeaters are compatible with the approved release profile;
- claims, capability status, and release profile are consistent;
- the conclusion states exactly what is approved, not approved, and what triggers re-review.

---

## 7. R4 — Software, distributed systems, and supply chain

### 7.1 Qualification requirements

R4 shall be an independent principal engineer or equivalent with strong
competence in:

- Python packaging and API/ASGI operation;
- PostgreSQL transactions, locking, and constraints;
- concurrency, idempotency, and persistent state;
- CI/CD, test isolation, and release engineering;
- SBOM, dependency locking, and build provenance.

### 7.2 Mandatory scope

| Area | Code/evidence | Acceptance test |
|---|---|---|
| Wheel and API | `pyproject.toml`, `servers/`, `schemas/`, issue #14 | Install the built wheel in an empty environment; import and start the API without a checkout |
| Resource loading | Risk profiles and schemas | Loaded via installed package resource, not an arbitrary working directory |
| PostgreSQL runtime | `tenant_chain.py`, API storage, CI | The driver is declared; contract tests run without ad-hoc installation |
| Shared authorization state | `review_queue.py`, `execution_api.py`, issue #15 | Two processes/replicas cannot consume the same approval/JTI/nonce |
| Concurrency | `engine.py`, `correlation.py`, execution state | Barrier/race test with deterministic invariants and a single execution winner |
| CI quality | `.github/workflows/ci.yml`, `pyproject.toml` | Reproducible install path, adequate coverage/type/lint/mutation gates |
| Supply chain | requirements/locks, build, and release | Hash-locked dependencies, SBOM, provenance, and signed release artifacts |
| Documented API semantics | `docs/07-api-reference.md`, endpoints | The documentation describes actual behavior, failure states, and persistence |

### 7.3 Sign-off criterion

R4 may attest production maturity only when issues #14 and #15 are closed and
retested, the installed artifact is independently runnable, state is
durable/atomic, and the supply-chain evidence can be verified from a clean
build.

---

## 8. R5 — License and IP

### 8.1 Legal scope

R5 shall assess:

- whether the BUSL-1.1 parameters and the Additional Use Grant are valid and
  consistent across `LICENSE`, `LICENSING.md`, package metadata, and README;
- the effects of previously permissively licensed versions and rights already
  granted;
- whether Stian Skogbrott has sufficient chain of title to offer separate
  commercial licenses;
- all external contributions, the CLAs actually signed, and whether the CLA
  text grants the necessary relicensing rights;
- third-party code, datasets, benchmark terms, and
  `THIRD_PARTY_NOTICES.md`;
- copyright risk from AI-assisted development;
- the commercial license, warranties, liability, indemnity, support/SLA, and
  transaction-ready IP;
- trademark and name use.

`CONTRIBUTING.md` states that contributions require a REMORA CLA. That is not
in itself evidence that an operative CLA text is legally sufficient or that the
necessary signatures exist. R5 shall verify the text itself and the signature
archive.

### 8.2 Deliverable

R5 delivers a separate, confidential or public legal memorandum with:

- the factual basis and documents reviewed;
- a chain-of-title table per external contributor;
- discrepancies between license files and published marketing;
- a third-party and dataset register;
- a blocker/risk list;
- a clear conclusion for source publication, pilot, commercial license, and
  possible IP sale.

A technical panel sign-off cannot replace this memorandum.

---

## 9. Sign-off levels

| Level | Permitted conclusion | Required signatures | Absolute blockers |
|---|---|---|---|
| **A — Research claims reviewed** | "Method and claims have been externally reviewed for commit X" | R1 + R3 | Unresolved statistical error, overclaim, or missing claim evidence |
| **B — Approved for controlled pilot** | "Approved for a bounded `CONTROLLED_PILOT`; not production-certified" | R1 + R2 + R3 | REM-021/023 open; relevant `CRITICAL`/`MAJOR`; unbounded tool/risk surface |
| **C — Approved for limited enforcement** | "Approved for named tools, environments, and risk classes" | R1 + R2 + R3 + R4 + the customer's domain authority | REM-024/030 open; PEP does not hold credentials; interception/replay not externally tested |
| **D — Production assurance package complete** | "The panel finds the evidence package complete for the defined deployment" | R1 + R2 + R3 + R4 + domain authority | Unfinished P0–P3 gates, undocumented residual risk, missing durable state/audit/supply chain |
| **L — Legal/IP cleared** | "License and IP basis legally cleared for the stated use/transaction" | R5 | Unclear chain of title, CLA, third-party terms, or conflicting license documents |

None of the levels shall be described as accredited certification unless a
competent certification / conformity-assessment process has explicitly
delivered it.

---

## 10. Candidate review environments

These environments are relevant candidate sources. The institution name alone
does not qualify; the named person must document competence and independence
per this matrix.

| Environment | Most relevant role | Rationale |
|---|---|---|
| [SINTEF Digital / SECASSURED](https://www.sintef.no/en/projects/2025/secassured-security-assurance-driven-ai-based-security-services-for-trustworthy-security-engineering-from-left-to-right/) | R1 and/or R2 | SECASSURED works on assurance-driven security, compliance interpretation, vulnerability discovery, and trustworthy security engineering |
| [DNV Digital Trust — AI regulations and standards compliance](https://www.dnv.com/digital-trust/services/ai-regulations-and-standards-compliance/) | R3 | Relevant for standards mapping, industrial AI, and regulatory readiness |
| [DNV — AI vendor capability assessment](https://www.dnv.com/digital-trust/services/ai-vendor-capability-assessment/) | R3 and overall third-party assessment | DNV describes the service as an independent third-party audit of the ability to develop and operate trustworthy AI/ML |
| [DNV — Industrial AI strategy and governance](https://www.dnv.com/digital-trust/services/ai-strategy-and-governance/) | R3 and customer-specific industrial assurance | Particularly relevant when REMORA is assessed for energy, oil & gas, or similar industrial-operator contexts |
| [TRUST — Norwegian Centre for Trustworthy AI](https://www.trust-aicentre.no/english/) | R1 and research-adjacent R3 | National, interdisciplinary environment for robust, transparent, and verifiable AI; not automatically a certification body |
| Specialist security environment | R2 | Must document agent/API red-teaming and deliver reproducible attack findings |
| Independent principal engineer | R4 | Should have production experience with Python, PostgreSQL, distributed authorization flows, and secure SDLC |
| Technology/IP lawyer | R5 | To be selected separately from the technical panel |

For any regulated industrial customer, a review package with DNV/SINTEF/TRUST-grade
professional weight, real named reviewers, and reproducible reports will be
substantially more credible than further AI-generated reviews.

---

## 11. Deliverable format

Each role delivers one standalone report:

```text
docs/assurance/reviews/
  r1_scientific_methods_review_v1.md
  r2_agent_security_red_team_v1.md
  r3_ai_assurance_review_v1.md
  r4_software_supply_chain_review_v1.md
  r5_license_ip_opinion_v1.md
```

R3 consolidates the technical reports in:

```text
docs/assurance/independent_review_v1.md
```

Each report shall contain:

1. reviewer identity and qualifications;
2. independence and conflict-of-interest declaration;
3. commit, environment, configuration, and dataset;
4. included and excluded scope;
5. review method and commands run;
6. findings with severity, owner, and status;
7. retest evidence;
8. residual risk and limitations;
9. mandate-specific conclusion and signature.

---

## 12. Global definition of done

A review level is approved only when:

- all mandatory roles have signed;
- 100% of the mandatory scope has a named reviewer;
- no relevant `CRITICAL` or `MAJOR` remains open;
- all remediated high-severity findings have been retested by whoever found them;
- claims, capability register, remediation register, and release profile point
  to the same actual maturity;
- the conclusion is bound to a commit and deployment evidence set;
- the panel lead has documented dissent and minority notes;
- README status changes only after the machine-readable registers and the
  signed review artifacts are consistent.

---

## 13. External method and standard references

- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI RMF Playbook — Govern](https://airc.nist.gov/airmf-resources/playbook/govern/)
- [NIST AI RMF Playbook — Measure](https://airc.nist.gov/airmf-resources/playbook/measure/)
- [ISO/IEC 42001:2023](https://www.iso.org/standard/42001)
- [ISO/IEC 23894:2023](https://www.iso.org/standard/77304.html)
- [ISO/IEC 42006:2025](https://www.iso.org/standard/42006) — requirements for bodies that audit and certify AI management systems
- [DNV-RP-0671 — Assurance of AI-enabled systems](https://www.dnv.com/digital-trust/recommended-practices/assurance-of-ai-enabled-systems-dnv-rp-0671/)

NIST's Playbook describes red-teaming as adversarial testing under stress and
emphasizes external experts or personnel independent of internal AI actors.
This supports REMORA's requirement that R2 actually test the system rather than
only read the documentation.
