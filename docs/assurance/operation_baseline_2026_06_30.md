# REMORA Assurance Operation Baseline — 2026-06-30

## Purpose

This document establishes the factual baseline for a structured assurance campaign
against the REMORA-research repository, executed per `internal_prompt.txt`. It records
the exact state of tests, artifacts, release gates, claims, security observations, and
known gaps at campaign start. No prose exceeds available evidence.

---

## 1. Repository Identity

| Field | Value |
|-------|-------|
| Repository | `darklordVirtual/REMORA-research` |
| Commit SHA | `32ddc73e9fa339e151453e1985316ab116619422` |
| Branch | `master` |
| Date | 2026-06-30 |
| Python | 3.14.0 |
| pytest | 8.4.2 |

---

## 2. Test Suite Status

### Pre-campaign state (before any Wave 0 fixes)

| Stat | Value |
|------|-------|
| Collected | ~3005 |
| Passed | 2969 |
| Failed | **10** |
| Deselected | 36 |

### Failing tests (pre-campaign)

| Test | Root cause | Severity |
|------|-----------|----------|
| `test_api_server.py::test_assess_envelope_conforms_to_schema_contract` | `causal_explanation` missing from `schemas/decision_envelope_schema.yaml` | P0 |
| `test_api_server.py::test_assess_envelope_conforms_to_schema_with_enterprise_fields` | Same schema gap | P0 |
| `test_decision_envelope_v2.py::test_validate_decision_envelope_dict_accepts_valid_payload` | Same schema gap | P0 |
| `test_decision_envelope_v2.py::test_audit_block_enterprise_fields_roundtrip_and_flat_dict` | Same schema gap | P0 |
| `test_decision_envelope_v2.py::test_audit_block_enterprise_fields_have_backward_compatible_defaults` | Same schema gap | P0 |
| `test_decision_envelope_v2.py::test_tool_args_hash_is_deterministic_sha256` | Same schema gap | P0 |
| `test_claim_consistency_audit.py::test_claim_consistency_audit_passes` | README claim/artifact mismatches (`readme_n500_historical_note`, `readme_result1_25pct`, `readme_toolcall_v1_metrics`) | P1 |
| `test_learning_ablation.py::TestProfileCArtifactLock::test_profile_c_reproduces_committed_artifact` | Profile C `false_block_rate` 0.0222 vs committed 0.0217 (drift 0.0005) | P1 |
| `test_review_readiness_docs.py::test_readme_uses_research_candidate_language` | README missing "deterministic simulator" qualifier in tool-call section | P1 |
| `test_shadow_replay.py::test_shadow_replay_cli_out_dir_writes_expected_files` | `scripts/shadow_replay.py` exits non-zero when run from this repo (relative path issue) | P2 |

### Wave 0 fix applied

**Fix:** Added `causal_explanation` as optional `["object", "null"]` with `additionalProperties: true`
to `schemas/decision_envelope_schema.yaml`. Field exists in `remora/governance/envelope.py:160`
but was missing from schema. Resolves 6 schema-contract test failures.

### Post Wave-0-fix state

| Stat | Value |
|------|-------|
| Passed | 2975 |
| Failed | **4** |
| Deselected | 36 |

---

## 3. Release Gate Status

### P0 Safety Gates (DONE — required for v1.0)

| ID | Gate | Status | Artifact |
|----|------|--------|----------|
| REM-014 | External benchmark AgentHarm (n=208, FAR=0.0%) | **DONE** | `results/external_benchmark_agentharm_v1.json` |
| REM-019 | Regression proof — 167 historical false accepts (FAR=0.0%) | **DONE** | `results/false_accept_regression_v1.json` |

### P3 Production Deployment Gates (OPEN — required before leaving SHADOW_ONLY)

| ID | Gate | Status | Eligible close |
|----|------|--------|---------------|
| REM-020 | Longitudinal stability — 7-day TRAINED AII ≥ 0.80, FAR=0.0% | **IN_PROGRESS** | Not before 2026-07-05 |
| REM-021 | Independent human review | **NOT_STARTED** | External reviewer; no self-cert |
| REM-022 | RBAC access control audit | **NOT_STARTED** | Signing key, D1, API |

---

## 4. Evidence Map

### Internal benchmarks (artifact-backed)

| Claim | Artifact | N | Status |
|-------|---------|---|--------|
| FAR=0% on adversarial tool-call benchmark (v2) | `results/toolcall_benchmark_v2_results.json` | 700 | VERIFIED |
| FAR=0% on blinded v3 benchmark (no label access) | `results/toolcall_blind_v3_results.json` | 700 | VERIFIED |
| 88% selective accuracy at 23.2% coverage (hold-out) | `results/selective_n500_holdout_results.json` | N_accepted=25 | VERIFIED; wide CI [70.0%, 95.8%] |
| 99.9% conformal coverage (ordered-phase) | `results/mondrian_repeated_splits_results.json` | 20 splits | VERIFIED |
| M1 leakage fix: FAR=0 without `is_unsafe_if_executed` | `results/toolcall_m1_clean_signal.json` | 700 | VERIFIED |
| AROMER replay accuracy 87.5% (96-case arena) | `artifacts/aromer/replay_arena_report.json` | 96 | EXPERIMENTAL |

### External benchmark

| Claim | Artifact | N | Status |
|-------|---------|---|--------|
| FAR=0% AgentHarm (ai-safety-institute) | `results/external_benchmark_agentharm_v1.json` | 208 | VERIFIED; external validity gate |

### Active negative results (MUST NOT BE REMOVED)

| # | Finding | Status |
|---|---------|--------|
| 1 | External replication pending | Active |
| 2 | AROMER external holdout FA=30.7% under neutral metadata | Partially de-risked; structural gates achieve 0% |
| 3 | Entropy backend is token-fingerprint, not Semantic Entropy | Active; NLI backend blocked by torch DLL |
| 4 | AROMER TRAINED via seeding; organic regression/recovery documented | Resolved (recovered); design gap remains |
| 8 | External adversarial dataset FA=30.7% (Phase 2 with semantic enrichment) | Partially addressed |
| 14 (M1) | Toolcall benchmark label leakage | **FIXED 2026-06-28** |
| 14 (M4) | Caller-supplied metadata not registry-authoritative | Open; deployment gate |

---

## 5. Remediation Register Status

All REM-001 through REM-018 are DONE. Summary:

| Priority | Items | Status |
|----------|-------|--------|
| P0 | REM-001, 002, 003, 004, 008, 013, 014, 016, 019 | All DONE |
| P1 | REM-005, 006, 007, 009, 010, 011, 012, 017, 018 | All DONE |
| P3 | REM-015, 020, 021, 022 | 015 DONE; 020 IN_PROGRESS; 021, 022 NOT_STARTED |

---

## 6. Known Gaps vs internal_prompt.txt Deliverables

The following deliverables from the campaign brief do NOT exist yet:

| Deliverable | Path | Status |
|-------------|------|--------|
| Operation baseline (this doc) | `docs/assurance/operation_baseline_2026_06_30.md` | Created now |
| Operation master plan | `docs/assurance/operation_master_plan_v1.md` | Not started |
| Machine-readable claim register | `docs/assurance/claim_register_v1.yaml` | Not started (text version exists at `docs/claim_register.md`) |
| Evidence levels taxonomy | `docs/assurance/evidence_levels.md` | Not started |
| Independent review protocol | `docs/assurance/independent_review_protocol_v1.md` | Not started |
| RBAC design | `docs/assurance/rbac_design_v1.md` | Not started (REM-022 open) |
| Threat model | `docs/assurance/threat_model_v1.md` | Not started |
| Reproducibility scorecard | `docs/assurance/reproducibility_scorecard_v1.md` | Not started |
| Domain pack governance | `docs/assurance/domain_pack_governance_v1.md` | Not started |
| Red team plan | `docs/assurance/red_team_plan_v1.md` | Not started |
| Artifact provenance spec | `docs/assurance/artifact_provenance_spec_v1.md` | Not started |
| Machine-readable artifact manifest | TBD | Not started |
| Machine-readable evidence-pack schema | TBD | Not started |
| REM-020 live-observation protocol | scripts/run_longitudinal_stability.py | Not started |
| REM-021 reviewer package | docs/assurance/ | Not started |
| REM-022 RBAC audit package | docs/assurance/ | Not started |

---

## 7. Reproducibility Blockers

| Blocker | Impact |
|---------|--------|
| `torch/lib/shm.dll` DLL policy (Windows) | Blocks NLI backend for Semantic Entropy comparison |
| REMORA main repo (private) required for AROMER scripts | `run_false_accept_regression.py`, `run_agentharm_benchmark.py` cannot be reproduced without the private implementation repo |
| Cloudflare Workers AI API key | Live oracle LLM baseline (`run_llm_baselines_v3.py`) requires network access + API key |
| HF_TOKEN | Some external dataset evaluations require HuggingFace API token |
| No CI/CD workflows | `.github/workflows/` directory is empty — no automated test execution on push |
| `scripts/shadow_replay.py` path issue | Shadow replay CLI exits non-zero when invoked from REMORA-research directory |
| Learning ablation artifact drift | Profile C `false_block_rate` 0.0005 off from committed artifact |

---

## 8. Security and Access-Control Observations

| Area | Observation |
|------|-------------|
| RBAC | REM-022 NOT_STARTED — no documented role-based access control for signing key, D1 DB, production API |
| PDP/PEP separation | Implemented (REM-013) — `remora/enforcement/token.py` with HMAC-SHA256; process-boundary gap documented |
| Signing key management | `REMORA_PDP_SIGNING_KEY` env var — no rotation policy, no KMS/HSM binding documented |
| D1 write access | Not restricted at application level — deployment-layer only |
| CI secrets | No workflow files to audit for secret handling |
| AST leakage detector | Present: `scripts/check_no_evaluation_leakage.py` — wired into `make audit` |
| Benchmark labels | Separated: `benchmarks/toolcall_blind_v3/labels.json` vs `tasks.json` — labels never passed to gate |
| Caller metadata | `risk_tier`, `action_type`, `target_environment` are agent-supplied — M4 open gap |

---

## 9. Prioritized Risk Register

| Priority | Risk | Current mitigation | Campaign action |
|----------|------|--------------------|-----------------|
| P0 | Schema contract violation (`causal_explanation`) breaks envelope validation | None | **FIXED in Wave 0** |
| P0 | No CI/CD — tests never run automatically on push | Manual `make test` | Create `.github/workflows/ci.yml` |
| P1 | README claims have 3 mismatches vs committed artifacts | Test fails on fresh audit run | Fix README in Wave 1 |
| P1 | Missing `docs/assurance/` deliverables (threat model, RBAC design, red team) | NEGATIVE_RESULTS.md exists | Create in Wave 1 |
| P1 | Shadow replay CLI broken in REMORA-research | No automated replay validation | Fix `scripts/shadow_replay.py` |
| P1 | Learning ablation artifact lock drift (0.0005) | Test flags it | Re-run or widen tolerance |
| P1 | Token-fingerprint heuristic used where Semantic Entropy claimed | Documented caveat in NEGATIVE_RESULTS.md (§3) | NLI backend DLL fix or better docs |
| P2 | No machine-readable claim register or evidence-pack schema | Text claim_register.md exists | Create YAML versions |
| P2 | No artifact provenance metadata (source, hash, jurisdiction, reviewed_at) | Results exist but no metadata | Add provenance schema |
| P2 | Domain packs missing for OT, energy, telecom, cybersecurity | Policy cookbook exists | Extend in Wave 1 |
| P3 | REM-020 longitudinal monitor has no automated snapshot/validation | Manual monitoring | Create script + cron |
| P3 | SBOM, Docker digests, uv.lock not present | requirements-lock.txt exists | Generate SBOM |

---

## 10. Claim Hygiene Summary

Per `docs/claim_hygiene.md` and `docs/05-claim-hygiene.md`:

**Claims that must carry caveats (enforced by test or document):**

| Claim | Required caveat |
|-------|----------------|
| 0% unsafe execution | [0.00%, 0.55%] Wilson CI; deterministic simulator; policy layer only |
| 88% selective accuracy | N_accepted=25; Wilson CI [70.0%, 95.8%]; single 80/20 split |
| Critical-phase trust inversion | N=32 total; directional finding only |
| Tamper-evident audit chain | Evident, not proof; requires external WORM storage |
| AROMER 0% false-accept | EXPERIMENTAL; partly self-labeled; shadow mode only |
| TRAINED AII ≥ 0.80 | Three production gates remain before deployment |

**Claims that are NOT made (per this baseline):**
- AII is not a safety proof
- Lyapunov analysis is not a universal mathematical proof
- Internal experiments are not external validation
- Simulation results are not field deployment proof

---

## 11. Wave 0 Actions Taken

1. Read `README.md`, `docs/assurance/release_gates.md`, `docs/02-evidence-and-claims.md`, `NEGATIVE_RESULTS.md`, `docs/01-architecture.md`, `docs/assurance/remediation_register.yaml`, `docs/assurance/baseline_snapshot.md`
2. Ran `python -m pytest tests/ -q --tb=no` — 10 failing tests identified
3. **Fix applied:** Added `causal_explanation` to `schemas/decision_envelope_schema.yaml` — resolves 6 test failures
4. Re-ran failing tests — 4 remaining failures documented above (§2)
5. Created this baseline document

---

## 12. Proceeding to Wave 1

Wave 1 will spawn parallel audit agents for:

- **A:** Policy engine and assurance architecture
- **B:** Benchmark integrity and statistical validity
- **C:** Reproducibility, CI, and artifact integrity
- **D:** Security, RBAC, and operational hardening
- **E:** RAG, domain knowledge, and evidence provenance
- **F:** Red team and adversarial evaluation
- **G:** External review readiness and scientific communication
- **H:** Product and operationalization strategy

P0 implementation targets for Wave 1:
1. Create `.github/workflows/ci.yml` (no automated CI exists)
2. Fix README claim mismatches (3 failing checks in claim audit)
3. Fix `scripts/shadow_replay.py` invocation from REMORA-research
4. Create `docs/assurance/claim_register_v1.yaml` (machine-readable)
5. Create `docs/assurance/threat_model_v1.md`
6. Create `docs/assurance/independent_review_protocol_v1.md`
7. Create `docs/assurance/rbac_design_v1.md`
8. REM-020 longitudinal snapshot script and validation
