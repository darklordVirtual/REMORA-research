# REMORA × NIST AI Risk Management Framework (AI RMF 1.0) Mapping

**Status:** internal mapping — not independently audited.
**Reference:** NIST AI RMF 1.0 (January 2023).
**Companion documents:**
- [`enterprise/governance-model.md`](../../enterprise/policy-model.md)
- [`enterprise/human-approval-workflow.md`](../../enterprise/human-approval-workflow.md)
- [`enterprise/observability.md`](../../enterprise/observability.md)
- [`enterprise/threat-model.md`](../../enterprise/threat-model.md)

The [NIST AI Risk Management Framework](https://www.nist.gov/artificial-intelligence)
organises AI risk into four functions: **Govern, Map, Measure, Manage**.
This document maps REMORA's architecture and controls to each function so that
enterprise governance teams can use it as a due-diligence checklist.

---

## GOVERN — Establishing Policies and Accountability

The Govern function ensures that organisational policies, roles, and processes
are in place before deployment.

| AI RMF Sub-category | REMORA Implementation | Status |
|---|---|---|
| GV-1 Policies defined | `enterprise/policy-model.md` + `enterprise/policy_as_code_example.yaml` | Implemented |
| GV-1 Risk appetite documented | `enterprise/risk-profiles.yaml` — LOW / MEDIUM / HIGH / CRITICAL tiers | Implemented |
| GV-2 Roles & accountability | `enterprise/human-approval-workflow.md` — RBAC, two-person rule for critical actions | Implemented (design) |
| GV-3 Organisational culture | Not a codebase concern — requires deployer commitment | N/A |
| GV-4 Team practices | `enterprise/deployment-runbook.md`, `enterprise/production-readiness.md` | Implemented |
| GV-5 Policies for AI procurement | `enterprise/integration-patterns.md` — vendor neutrality via Oracle ABC | Implemented |
| GV-6 Policies reviewed regularly | `CHANGELOG.md` tracks policy changes; claim register is versioned | Partial |

**Gaps:** GV-3 (organisational culture) is a people process, not a technical
control.  GV-6 policy review cadence must be established by the deployer.

---

## MAP — Categorising and Contextualising AI Risk

The Map function identifies the AI system's purpose, users, deployment context,
and risk categories relevant to each use case.

| AI RMF Sub-category | REMORA Implementation | Status |
|---|---|---|
| MP-1 System purpose documented | `README.md`, `docs/plain_language_overview.md`, `paper/whitepaper.md` | Implemented |
| MP-2 Intended users / stakeholders | `enterprise/sector-use-cases.md`, `docs/use-cases/` | Implemented |
| MP-3 AI system type categorised | Multi-oracle consensus system with selective abstention; not a training pipeline | Documented |
| MP-4 Risk categories identified | `enterprise/threat-model.md` — five primary threat categories | Implemented |
| MP-5 Failure modes documented | `NEGATIVE_RESULTS.md` — archived failure modes + active external-validation gap with mitigation path | Implemented |
| MP-5 Sociotechnical impacts | `enterprise/sector-use-cases.md` — healthcare, legal, finance sectors | Partial |
| MP-6 Benefits identified | `enterprise/executive-brief.md`, `EVIDENCE_OF_CAPABILITY.md` | Implemented |

**Gaps:** MP-5 sociotechnical impact analysis (e.g., disparate performance
across demographic groups) has not been performed.  The benchmark corpus is
general-domain; domain-specific fairness analysis is not yet included.

---

## MEASURE — Quantifying AI Risk

The Measure function calls for metrics, benchmarks, and ongoing evaluation
to quantify AI system performance and risk levels.

| AI RMF Sub-category | REMORA Implementation | Status |
|---|---|---|
| MS-1 Metrics defined | Accuracy, ETR (evaluation-to-run ratio), F1, calibration ECE | Implemented |
| MS-1 Evaluation methodology documented | `docs/stat_tests.md`, `artifacts/reproduce.sh` | Implemented |
| MS-2 Baseline comparisons | Single oracle, majority vote, REMORA full cascade vs. selective | `artifacts/benchmark_summary.json` |
| MS-2 Negative results documented | `NEGATIVE_RESULTS.md` — resolved findings archive with root cause/mitigation and one active replication gap | Implemented |
| MS-3 Calibration measured | `remora/calibration/platt_scaler.py` — ECE reduction from ~0.19 to ~0.05 | Implemented |
| MS-3 Uncertainty quantified | `remora/uncertainty/decompose.py` — epistemic vs. aleatoric decomposition | Implemented |
| MS-4 Bias / fairness assessment | Not yet performed — general-domain benchmark only | Gap |
| MS-5 Performance monitoring | `enterprise/observability.md` — OTel integration design | Partial (design) |
| MS-6 Adversarial testing | `redteam/` skeleton — cases defined, automated runner in progress | Partial |

**Gaps:** MS-4 (fairness/bias) and MS-5 (live performance monitoring)
are the most significant measurement gaps.  The `redteam/` directory
provides a starting point for MS-6 but does not yet cover all scenarios.

---

## MANAGE — Prioritising and Treating AI Risk

The Manage function implements controls, mitigation strategies, incident
response, and continuous improvement.

| AI RMF Sub-category | REMORA Implementation | Status |
|---|---|---|
| MG-1 Risk treatment decisions | `enterprise/risk-profiles.yaml` — per-tier treatment (monitor / escalate / block) | Implemented |
| MG-2 Residual risks documented | `docs/claim_register.md §Requires External Replication` | Implemented |
| MG-2 Incident response | `enterprise/deployment-runbook.md §Incident Response` | Partial |
| MG-3 Feedback loops | `remora/adaptation/` — continual re-alignment of oracle weights | Implemented |
| MG-3 Human oversight | `enterprise/human-approval-workflow.md` — two-person rule, audit trail | Implemented (design) |
| MG-4 Decommission / sunset | Not documented | Gap |
| MG-5 Change management | `CHANGELOG.md`, semantic versioning (`pyproject.toml`) | Implemented |
| MG-6 Third-party dependencies | `enterprise/production-readiness.md §Supply Chain` | Partial |

**Key controls:**

1. **Selective abstention** — REMORA refuses to answer rather than produce
   low-quality output.  Coverage rate vs. accuracy tradeoff is configurable
   via `DomainCoverageOptimizer`.

2. **Policy-as-code** — All access control and tool-call decisions are
   evaluated by OPA policies in `enterprise/policy_as_code_example.yaml`,
   making them auditable and version-controlled.

3. **Append-only audit ledger** — Every oracle call, policy decision, and
   human approval is written to the audit ledger (`enterprise/audit-ledger-schema.sql`),
   creating an immutable accountability chain.

4. **Thermodynamic drift detection** — The Lyapunov function `V(t)` in
   `remora/lyapunov.py` detects when an agent is drifting out of safe
   operating bounds and triggers escalation before irreversible actions
   are taken.

---

## Summary Scorecard

| Function | Controls in Place | Gaps |
|---|---|---|
| **Govern** | Policies, risk tiers, RBAC design, runbook | Policy review cadence; org culture |
| **Map** | Use cases, threat model, failure modes, sector mapping | Sociotechnical impact analysis |
| **Measure** | Benchmarks, baselines, calibration, uncertainty, negative results | Fairness/bias, live monitoring |
| **Manage** | Risk treatment, human oversight, audit ledger, feedback loops, change log | Decommission process; full red-team coverage |

**Recommended next steps to close gaps:**
1. Commission a third-party fairness evaluation on domain-specific corpora (MS-4).
2. Deploy the OTel observability pipeline in shadow mode to establish live baselines (MS-5).
3. Run the `redteam/benchmark_runner.py` against a curated external dataset and publish results (MS-6).
4. Document the decommission and model-replacement process in the runbook (MG-4).
