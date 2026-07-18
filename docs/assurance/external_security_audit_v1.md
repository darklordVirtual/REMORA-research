# External Security & Enterprise-Readiness Audit: Findings & Disposition v1

**Status:** INTERNAL: findings register + disposition. Nothing here is a claim.
**Date:** 2026-07-03
**Source:** External static architecture/source audit (ChatGPT), scoping REMORA
as a *research prototype and assurance framework, not a production enterprise
control plane*. The audit's classification is accepted; this document records
each concrete finding, its **independent verification against the actual
source**, and its disposition (FIXED with commit reference, or ROADMAP with a
remediation-register id).

**Verification method:** every code-level claim was checked against source
before action (a prior review pass on this repo found external audits can
contain confabulations). Two of six code claims were downgraded on
verification (see below). The audit's high-level scorecard, strong
deterministic-first policy design, weak runtime-enforcement placement and
tenant/identity binding: is accurate and not disputed.

Cross-references: `simulated_hostile_review_v1.md` (academic/XAI review, closed
2026-07-03), `rbac_design_v1.md` + REM-023 (RBAC follow-through), the
five-wave remediation already completed.

---

## Part A: Concrete code defects (verified, FIXED)

### A-1. P0-A (Header-derived role escalation) **CONFIRMED → FIXED**
`servers/api.py` authenticated a token to a `(tenant, role)` but the capability
check (`_require_tenant_capability`) discarded the token role and re-read the
caller-controlled `X-Remora-Role` header via `_role_from_request`; `admin` has
wildcard `{"*"}`. A viewer-bound multi-tenant token sending `X-Remora-Role:
admin` obtained admin capability.
**Fix:** `_require_tenant_capability(role, tenant_id, capability)` now takes the
**authenticated** role from `_authenticate()`; the header is never read on an
authorization path. `_role_from_request` marked deprecated. Regression tests:
`test_header_role_cannot_override_authenticated_token_role` (viewer token +
admin header → 403) and a positive admin-token control. This closes the RBAC
half of REM-023.

### A-2. Unknown action_type reaches ACCEPT, **CONFIRMED → FIXED**
`remora/policy/decision_engine.py`: the schema-unverified VERIFY floor gated
only on `_MUTATING_TYPES` membership, so a **non-empty, unrecognised**
`action_type` with a declared low/medium risk tier and high trust bypassed it
and reached the conformal/temperature/evidence/ordered-trust ACCEPT paths.
**Fix:** new deny-by-default VERIFY floor (`UNKNOWN_ACTION_TYPE_VERIFY`), a
non-empty `action_type` outside the known vocabulary (`_MUTATING_TYPES` ∪
`_READ_ONLY_TYPES` ∪ `_NON_ACTUATING_TYPES`) routes to VERIFY. `action_type=None`
(pure QA / no tool call) is intentionally preserved as ACCEPT-eligible.
Mirrored in `explain()` (parity harness enforces this); 4 dedicated tests;
full suite green (no benchmark regression).

### A-3. Audit-chain concurrent fork, **CONFIRMED → FIXED**
`remora/audit/hash_chain.py` `AuditHashChain.append()` read `_entries[-1]` and
appended with no synchronisation; concurrent writers could derive the same
`previous_hash` and fork the chain. **Fix:** a `threading.Lock` serialises
`append()`. Test: 200 threads with a start barrier produce one linear,
verifying chain. NOTE: this fixes the **in-process** chain only; a
multi-process / durable deployment still needs the transactional per-tenant
sequence in Part B (REM-025).

### A-4. Local hook fails open, **CONFIRMED → FIXED (opt-in fail-closed)**
`scripts/remora_hook.py` allowed execution (exit 0) on malformed input, missing
tool fields, unexpected exceptions, and permitted MEDIUM-risk actions when the
remote verifier was unavailable. **Fix:** `REMORA_HOOK_FAIL_CLOSED=1` makes all
error paths BLOCK (exit 2) and blocks MEDIUM-risk on remote-unavailable; default
(`0`) preserves the permissive research behavior with an explicit warning naming
the flag. Local deterministic blocks still block in either mode. 5 tests.
(The deeper "the hook is optional / not a mandatory PEP" point is architectural
- Part B, REM-024.)

### A-5. Tool arguments not bound to approval, **PARTIALLY-CONFIRMED → FIXED**
A `tool_args_hash` existed but bound only the truncated 120-char question
preview (`observation.py` `from_tool_call`), so two calls differing only beyond
120 chars collided. **Fix:** new `canonical_tool_call_hash(name, arguments,
tenant, target)` (SHA-256 over the FULL canonical tool call) and a
`PolicyObservation.tool_call_hash` field populated by `from_tool_call`. The
documented contract (API reference): an enforcement point recomputes this
immediately before execution and refuses on mismatch (TOCTOU defense). 4 tests.
The end-to-end recompute-before-execute step depends on the mandatory PEP
(REM-024).

### A-6. Cascade can ACCEPT without policy, **PARTIALLY-CONFIRMED → GUARDED**
`FastGate` can return terminal ACCEPT from one oracle's self-reported
confidence ≥ 0.90, and `CascadeEngine.run()` carries no policy/action metadata.
**Verified NOT wired** to any execution/authorization path (imported only by
experiments/tests). **Fix:** explicit "answer-quality only, NOT an
execution-authorization component" warning on the class, plus
`test_cascade_not_authorization.py` asserting no enforcement module
(`decision_engine`, `enforcement/*`, `adapters/*`, `remora_hook`, `api`) imports
`CascadeEngine`, so it cannot silently become an enforcement path.

---

## Part B: Platform-scale gaps (verified real, ROADMAP)

These are genuine and correctly identified, but they require enterprise
platform infrastructure that is out of scope for a research repository. They
are recorded as remediation items and gate any production/multi-tenant
deployment. They do **not** contradict any current claim, the repo is declared
SHADOW_ONLY and research-grade throughout.

| REM | Capability | Gap | Disposition |
|-----|-----------|-----|-------------|
| REM-023 | RBAC (identity) | Header role escalation | **RBAC half FIXED (A-1)**; isolation test and admin-wildcard removal DONE 2026-07-03 (same day as this audit); external confirmation still open, folded into REM-021 |
| REM-024 | Mandatory fail-closed PEP | Enforcement is not inseparable from tool execution (hook is optional; no signed execution lease binding tenant/tool/args-hash/policy-version/nonce/expiry) | ROADMAP, native dispatcher middleware or tool proxy; agent must not hold downstream credentials |
| REM-025 | Durable audit integrity | In-memory chain fork fixed (A-3), but no transactional per-tenant sequence, WORM, KMS/HSM signing, RFC 3161 timestamps, or transparency-log anchoring | ROADMAP, transactional sequence + external immutable anchoring |
| REM-026 | Tenant isolation | `tenant_id` in envelope, but no DB-enforced RLS / per-tenant crypto domains | ROADMAP, Postgres RLS keyed to verified claims + tenant KMS |
| REM-027 | Supply chain | Unbounded lower-bound deps; CI installs editable extras, not a hash-verified lock; artifacts checked for presence, not recomputed | ROADMAP, hash-pinned lock, SBOM, SLSA provenance, Sigstore signing, artifact-hash verification (note: the claim-provenance gate already recomputes result-artifact SHA-256 against the manifest) |
| REM-028 | HA / latency control | Synchronous engine in request path; no circuit breaker / bounded queue / deadline propagation / distributed rate limit | ROADMAP, stateless PDP service, deadline propagation, circuit breakers, cached signed policy bundles |
| REM-029 | SIEM / IR | Prometheus-style metrics only | ROADMAP, OTel traces + immutable events to SIEM, deny-spike / policy-bypass alerts |
| REM-030 | Independent tool-interception validation | AgentHarm is intent-gating, not verified per-tool wrapping | ROADMAP, verified tool-wrapper integration tests, external red team (overlaps REM-021) |
| REM-031 | GDPR / EU AI Act evidence | Retention/classification fields are integration-provided, not enforced; no intended-use classification record | ROADMAP (P2), DPIA, field minimization, AI Act technical-documentation pack (Reg. (EU) 2016/679; Reg. (EU) 2024/1689) |

---

## Disposition summary

- **6/6 concrete code defects addressed** (4 fully fixed, 2 correctly downgraded
  on verification and guarded/bounded), each with regression tests.
- **9 platform-scale items** recorded as REM-023…REM-031; these are the honest
  "not a production enterprise control plane" boundary the audit itself draws.
- The single most important architectural item remains **REM-024** (a mandatory,
  fail-closed, cryptographically-bound PEP between decision and dispatcher).
  A-4 (opt-in hook fail-closed) and A-5 (full-args binding) are the in-repo
  building blocks; making enforcement *mandatory and inseparable from execution*
  is platform work, and is the correct next investment per the audit's own
  final assessment.
