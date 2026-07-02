# REMORA Assurance Operation Master Plan v1

**Status:** Wave 2 synthesis — 2026-06-30
**Based on:** Wave 0 baseline (`2cd573d`) + Wave 1 parallel audit (`e58d2f3`)
**Test count:** 3068 passed, 0 failed, 36 deselected
**AII:** 0.9701 (TRAINED); production gates: REM-020 IN_PROGRESS, REM-021/022 NOT_STARTED

---

## Executive Summary

Wave 0 established the factual baseline (10 test failures, schema contract gap, 20 missing
deliverables). Wave 1 deployed 8 parallel audit agents and resolved all 4 remaining failures,
created 20 new deliverables, and added 89 regression tests. The repository is now in the
strongest documented state it has ever been for external review.

Key advances:
- **0 test failures** (down from 10 at campaign start)
- **CI/CD operational** — `.github/workflows/ci.yml` closes P0 automation gap
- **Learning ablation artifact corrected** — prior artifact claimed n=88 (phantom); corrected to n=85
- **13 new docs/assurance/ documents** covering all required assurance dimensions
- **89 new regression tests** — 42 red-team adversarial + 47 policy engine audit
- **No hard-block bypass found** — policy engine audit confirms ESCALATE/VERIFY paths fire before any ACCEPT

Outstanding gaps are documented below with priority order for Wave 3 implementation.

---

## 1. Completed Deliverables (Wave 0 + Wave 1)

| Deliverable | File | Commit |
|-------------|------|--------|
| Wave 0 baseline | `docs/assurance/operation_baseline_2026_06_30.md` | 2cd573d |
| Schema contract fix (causal_explanation) | `schemas/decision_envelope_schema.yaml` | 2cd573d |
| **This document** | `docs/assurance/operation_master_plan_v1.md` | e58d2f3+ |
| Policy engine audit | `docs/assurance/policy_engine_audit_v1.md` | e58d2f3 |
| Benchmark audit | `docs/assurance/benchmark_audit_v1.md` | e58d2f3 |
| Reproducibility scorecard | `docs/assurance/reproducibility_scorecard_v1.md` | e58d2f3 |
| Artifact manifest (SHA-256) | `docs/assurance/artifact_manifest_v1.md` | e58d2f3 |
| Threat model (STRIDE) | `docs/assurance/threat_model_v1.md` | e58d2f3 |
| RBAC design | `docs/assurance/rbac_design_v1.md` | e58d2f3 |
| Domain pack governance | `docs/assurance/domain_pack_governance_v1.md` | e58d2f3 |
| Artifact provenance spec | `docs/assurance/artifact_provenance_spec_v1.md` | e58d2f3 |
| Red team plan (15 attack families) | `docs/assurance/red_team_plan_v1.md` | e58d2f3 |
| Machine-readable claim register | `docs/assurance/claim_register_v1.yaml` | e58d2f3 |
| Evidence levels taxonomy | `docs/assurance/evidence_levels.md` | e58d2f3 |
| Independent review protocol (REM-021) | `docs/assurance/independent_review_protocol_v1.md` | e58d2f3 |
| Product strategy | `docs/assurance/product_strategy_v1.md` | e58d2f3 |
| CI workflow | `.github/workflows/ci.yml` | e58d2f3 |
| Policy bundle hash utility | `remora/policy/versioning.py` | e58d2f3 |
| Red team regression tests (42) | `tests/test_red_team_v1.py` | e58d2f3 |
| Policy engine audit tests (47) | `tests/test_policy_engine_audit_v1.py` | e58d2f3 |

---

## 2. Consolidated Findings from Wave 1

### 2.1 Security Findings (Agent D)

| ID | Finding | Severity | Action |
|----|---------|----------|--------|
| C-1 | HMAC signing keys as bare env vars; no rotation, KMS, or access list | Critical | REM-022 scope |
| C-2 | D1 audit log allows UPDATE; tamper prevention requires external WORM | Critical | Architecture doc; WORM storage before production |
| C-3 | No Cloudflare rate limiting configured | Critical | CF dashboard — no code change needed |
| H-1 | `HF_TOKEN` string-interpolated into CI shell heredoc; leaks in error logs | High | **Wave 3 P0 fix** (1-line change) |
| H-2 | Single-token auth mode reads role from caller-supplied `X-Remora-Role` header | High | **Wave 3 P0 fix** |
| H-3 | `PolicyDecisionToken` has no expiry field | High | Wave 3 P1 |
| H-4 | No branch protection on wrangler deploy workflow | High | GitHub settings — no code change |
| M-1 | CORS wildcard in workers (checklist only, not enforced) | Medium | Wave 3 P2 |
| M-3 | `admin` role uses wildcard permission `{"*"}` | Medium | Wave 3 P2 |
| L-1 | `X-Remora-Actor` is caller-supplied, not bound to token | Low | Wave 3 P3 |

### 2.2 Architecture Findings (Agent A — Policy Engine)

| ID | Finding | Severity | Action |
|----|---------|----------|--------|
| F-1 | `action_type=None` + `risk_tier=None` can reach ACCEPT | Low | Intentional design; documented in tests; over-blocking avoided |
| F-2 | `PolicyDecisionToken` has no TTL/nonce; replay valid indefinitely | Low | REM-022 scope; nonce store required |
| F-3 | `AROMER_CONFORMAL_TRUST_THRESHOLD` constant has no effect on `decide()` | Informational | Dead code; remove or document |
| F-4 | `AuditBlock.policy_bundle_hash` always `None` unless integration sets it | Medium | **Fixed:** `remora/policy/versioning.py` added |
| — | **No hard-block bypass found** — all ESCALATE/VERIFY paths verified before ACCEPT | — | No action needed |

### 2.3 Benchmark Integrity (Agent B)

| Finding | Severity | Action |
|---------|----------|--------|
| Learning ablation artifact had phantom n=88 (only 85 cases exist) | **Critical** | **Fixed:** regenerated, committed |
| `external_benchmark_agentharm_v1.json` uses short commit hash (P0 gate artifact) | High | Wave 3: expand to full 40-char SHA |
| Universal provenance gap: `script` field absent from all 5 audited artifacts | High | Wave 3: add `build_provenance()` helper |
| `conformal_repeated_splits.json`: no schema, no commit hash, no timestamp | Medium | Wave 3: add sidecar provenance |
| Selective prediction N=25 too small for generalization claims | Medium | Documented; CI [70.0%, 95.8%] |

### 2.4 Adversarial Evaluation (Agent F — Red Team)

| Finding | Severity | Action |
|---------|----------|--------|
| **Oracle collusion gap:** no hard gate when all oracles agree at zero dissensus | Critical | Wave 3: add `valid_oracle_count < min_required` gate |
| **Caller-supplied metadata (M4 gap):** risk_tier, action_type, domain are agent-supplied | High | Architecture gap; documented in claim register |
| Unsigned `AssuranceEnvelope`: hash tamper detection works; cryptographic signing absent | Medium | Deployment-layer gap; PKI/HSM |
| No `evidence_timestamp` field in `PolicyObservation`; stale evidence undetectable | Medium | Wave 3 P2: add field |
| Approval fatigue: engine is stateless; no session tracker auto-populates counters | Medium | Architecture gap; deployment layer |

### 2.5 CI / Reproducibility (Agent C)

| Finding | Severity | Action |
|---------|----------|--------|
| **No CI/CD existed** | Critical | **Fixed:** `.github/workflows/ci.yml` created |
| `quality-gates.yml` used `@v6` action pins (does not exist; would fail) | High | **Fixed:** corrected to `@v4`/`@v5` |
| `requirements-lock.txt` is UTF-16 LE (Windows artifact; diff tools garble it) | Medium | Regenerate on Linux |
| Four result files lack `git_commit` provenance field | Low | Wave 3 P2 |
| Docker images not pinned by digest | Low | Acknowledged (REM-015) |

### 2.6 RAG / Domain / Provenance (Agent E)

| Finding | Severity | Action |
|---------|----------|--------|
| OT/ICS, energy, telecom, structured cybersecurity: zero RAG chunk coverage | High | Wave 3 P2 (OT/ICS first) |
| `source_url`, `source_sha256`, `ingest_script` absent from RAG ingest metadata | Medium | Wave 3 P2 |
| `build_provenance()` helper needed in all producing scripts | Medium | Wave 3 P2 |

### 2.7 External Review Readiness (Agent G)

| Finding | Severity | Action |
|---------|----------|--------|
| No REMORA claim reaches `independently_replicated` evidence level | Critical | Communicate clearly; REM-021 starts the path |
| REM-021 reviewer package existed as prose; machine-readable protocol now created | — | **Fixed:** `independent_review_protocol_v1.md` |
| README had 4 claim mismatches + missing "deterministic simulator" qualifier | High | **Fixed** |
| N_accepted=25: widest headline CI [70.0%, 95.8%] | Medium | Documented |

### 2.8 Product Strategy (Agent H)

| Finding | Action |
|---------|--------|
| Shortest commercial path: B2B/OEM channel (REMORA as SDK component for platform vendors) | Start design partner conversations after REM-020 closes |
| SR-4 (High): external validation dependency — findings during commercial eval > proactive | Assemble REM-021 package NOW, in parallel with REM-020 window |
| SR-1 (High): market timing — platform vendors may compress independent overlay market | Prioritize B2B/OEM positioning over direct enterprise |
| SR-5: AROMER organic brr spike resets REM-020 gate clock | Monitor daily; no seeding permitted |

---

## 3. Wave 3 Work Plan (Prioritized)

### P0 — Do now (no gate required; high risk if deferred)

| Task | Owner | Files | Expected effort |
|------|-------|-------|----------------|
| Fix `HF_TOKEN` CI anti-pattern (H-1) | Engineer | `.github/workflows/agentharm-experiment.yml` | 15 min |
| Fix single-token mode role escalation (H-2) | Engineer | `servers/api.py` | 1 hour |
| Enable Cloudflare rate limiting (C-3) | DevOps | CF dashboard | 30 min |
| Add GitHub branch protection + required reviewer for wrangler deploy (H-4) | DevOps | GitHub settings | 30 min |
| Expand `external_benchmark_agentharm_v1.json` short commit hash to full 40-char SHA | Engineer | `results/external_benchmark_agentharm_v1.json` | 15 min |

### P1 — This week

| Task | Owner | Files | Expected effort |
|------|-------|-------|----------------|
| Add `valid_oracle_count < min_required` gate (oracle collusion) | Engineer | `remora/policy/decision_engine.py`, tests | 3 hours |
| Wire `compute_policy_bundle_hash()` into API at request time | Engineer | `servers/api.py`, `remora/policy/versioning.py` | 2 hours |
| Add `PolicyDecisionToken` expiry/TTL field | Engineer | `remora/enforcement/token.py`, schema | 2 hours |
| Add `build_provenance()` helper to all producing scripts | Engineer | `scripts/*.py`, `remora/aromer/evals/*.py` | 4 hours |
| Add sidecar provenance to P0 gate artifacts (agentharm, false_accept_regression) | Engineer | `results/` | 2 hours |
| Assign external reviewer for REM-021 | PM/lead | `docs/assurance/independent_review_protocol_v1.md` | — |

### P2 — Before REM-021 reviewer starts

| Task | Owner | Files | Expected effort |
|------|-------|-------|----------------|
| Create `schemas/result_provenance_schema.yaml` | Engineer | `schemas/` | 2 hours |
| Add `tests/test_artifact_provenance.py` (CI validation of P0/P1 artifact provenance) | Engineer | `tests/` | 3 hours |
| Add `evidence_timestamp` field to `PolicyObservation` | Engineer | `remora/policy/`, schema, tests | 2 hours |
| Scope admin role from `{"*"}` to enumerated permissions (M-3) | Engineer | `servers/api.py` | 1 hour |
| Add `source_url`, `source_sha256`, `ingest_script` to RAG ingest metadata | Engineer | `workers/rag-oracle/src/` | 3 hours |
| Regenerate `requirements-lock.txt` on Linux (UTF-8) | Engineer | CI | 30 min |
| Begin OT/ICS domain pack (highest consequence; Policy cookbook + RAG chunks) | Domain expert | `policy_cookbooks/`, `workers/rag-oracle/` | 1 week |

### P3 — Production readiness (post REM-020/021/022)

| Task | Owner | Files | Expected effort |
|------|-------|-------|----------------|
| Production API gateway design + OIDC binding | Architect | `docs/assurance/`, `servers/` | 2 weeks |
| KMS/HSM binding for HMAC signing keys | DevOps/Infra | `remora/enforcement/`, deployment | 1 week |
| WORM storage for D1 audit log | DevOps/Infra | deployment config | 1 week |
| SBOM generation (pip-audit, syft) | DevOps | CI | 1 day |
| B2B/OEM design partner engagement | Commercial lead | — | — |

---

## 4. Production Gate Roadmap

### REM-020 — Longitudinal Stability (IN_PROGRESS)

- **Requirement:** AII EMA ≥ 0.80 for 7 consecutive calendar days with FAR=0.0%
- **Current AII:** 0.9701 (TRAINED) — well above threshold
- **Earliest eligible close:** 2026-07-05
- **Risk:** organic `brr` spike resets the clock; no seeding permitted during window
- **Action:** daily monitoring; do not tune thresholds during window

### REM-021 — Independent Human Review (NOT_STARTED)

- **Requirement:** Independent reviewer with no conflicts; 21-question scorecard
- **Reviewer package:** `docs/assurance/independent_review_protocol_v1.md` (ready)
- **Materials checklist:** 14 documents, 6 artifacts, 6 source modules (listed in protocol)
- **Risk (SR-4):** every day without a reviewer is a day closer to commercial evaluation
- **Action:** assign reviewer immediately; can run in parallel with REM-020 window

### REM-022 — RBAC Audit (NOT_STARTED)

- **Requirement:** Documented role-based access control for signing key, D1, API
- **Design:** `docs/assurance/rbac_design_v1.md` (ready)
- **Implementation gaps:** scoped CF token, GitHub environment with required reviewers,
  deprecate single-token mode header role trust (H-2 — P0 fix)
- **Action:** implement P0 security fixes first; then close REM-022 with RBAC design doc

---

## 5. Claim Hygiene Summary

All claims remain consistent with their artifacts as of Wave 1 completion.
No new numbers were introduced without matching artifacts.

| Claim | Evidence level | Caveat required |
|-------|---------------|-----------------|
| FAR=0% on adversarial tool-call benchmark (CLAIM-001) | internal_benchmark | Wilson CI [0.00%, 0.55%]; deterministic simulator; policy layer only |
| FAR=0% on external AgentHarm benchmark, N=208 (CLAIM-002) | externally_benchmarked | Intent-gating only; FBR=100% on benign variants |
| 88% selective accuracy at 23.2% coverage (CLAIM-004) | internal_benchmark | N_accepted=25; Wilson CI [70.0%, 95.8%]; single split |
| AROMER 0% false-accept on 96-case arena | internal_benchmark | EXPERIMENTAL; shadow mode only; self-labeled |
| AII TRAINED status (CLAIM-006) | internal_simulation | Production gates remain before deployment; not a safety metric |
| AROMER FA=30.7% under neutral metadata (CLAIM-009) | internal_benchmark | NEGATIVE RESULT; structural gates achieve 0% only with accurate metadata |

No REMORA claim currently reaches `independently_replicated` or `externally_validated`.
The highest level is `externally_benchmarked` (REM-014, AgentHarm, n=208).

---

## 6. Risk Register Delta (Wave 1 additions)

| Risk | Severity | Mitigation |
|------|----------|------------|
| Oracle collusion: all oracles agree at zero dissensus | Critical | Add min_required gate (Wave 3 P1) |
| H-2 role escalation in single-token mode | High | Fix in Wave 3 P0 |
| H-1 HF_TOKEN leak in CI logs | High | Fix in Wave 3 P0 |
| No claim reaches independently_replicated | High | REM-021 starts the path |
| SR-4: external validation dependency | High | Assign REM-021 reviewer now |
| SR-1: market timing | High | B2B/OEM positioning; start design partner conversations |

---

## 7. Wave 3 Entry Criteria

Wave 3 implementation begins when:

1. Wave 2 master plan (`this document`) is reviewed and committed
2. P0 security fixes (H-1, H-2, rate limiting, branch protection, short hash) are assigned
3. REM-021 reviewer is identified (not necessarily started)

Wave 3 exits when:
- All P0 items above are implemented and tested
- All P1 items above are implemented and tested
- REM-020 gate is eligible for close (2026-07-05)
- REM-021 reviewer has been assigned and the reviewer package has been sent
