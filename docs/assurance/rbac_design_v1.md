# REMORA RBAC Design v1

**Status:** Design proposal — REM-022 NOT_STARTED; this document initiates the audit
**Date:** 2026-06-30
**Author:** Agent D (security/RBAC audit)
**Scope:** `darklordVirtual/REMORA-research` at commit `2cd573d` (master branch)
**Related gates:** REM-022 (NOT_STARTED) — RBAC audit is a required production deployment gate

**IMPORTANT:** This document describes the RBAC design that REMORA needs. It does
NOT claim that RBAC is implemented or that REM-022 is closed. The gate status is
NOT_STARTED as recorded in `docs/assurance/release_gates.md` and
`docs/assurance/remediation_register.yaml`.

---

## 1. Resources Requiring Access Control

The following resources are identified from code and configuration. Access control
requirements are described per resource; implementation status is noted honestly.

### 1.1 Signing Keys

| Key | Environment variable | Used in | Current control |
|-----|---------------------|---------|-----------------|
| PDP signing key | `REMORA_PDP_SIGNING_KEY` | `remora/enforcement/token.py` — signs PolicyDecisionTokens | Environment variable; no documented access list or rotation policy |
| Envelope signing key | `REMORA_ENVELOPE_SIGNING_KEY` | `servers/api.py:462` — signs audit envelope hashes | Environment variable; same gap |
| Audit anchor key | `REMORA_AUDIT_ANCHOR_KEY` | `remora/audit/anchor.py:61` — signs daily Merkle root anchors | Environment variable; same gap |

All three keys are HMAC-SHA256 secret keys. The paper (`paper/remora_paper.md:209`) explicitly
acknowledges: "RBAC on the signing key, KMS/HSM key management, and process-boundary token
transport (gRPC/mTLS) are not implemented in this version."

### 1.2 D1 Database

| Database | Binding | Worker | Content | Current write control |
|----------|---------|--------|---------|----------------------|
| `remora-audit` | `AUDIT_DB` | agent-control | Governance decisions, review records, evidence, session data | Worker-scoped binding; no application-layer write RBAC |
| AROMER D1 | aromer worker | aromer | Episode/decision corpus | Worker-scoped binding |

The pre-deployment review (`docs/security/pre-deployment-review.md §5`) notes that the D1
`audit_log` table allows UPDATE, creating a tamper risk for approval records.

### 1.3 Production API

The FastAPI gateway (`servers/api.py`) implements a role-permission system. The built-in
role permissions are defined at `servers/api.py:236`:

```python
_BUILTIN_ROLE_PERMISSIONS = {
    "admin": {"*"},
    "operator": {"assess", "evidence", "rerun", "read"},
    "reviewer": {"review", "follow_up", "read"},
    "domain_expert": {"review", "read"},
    "senior_authority": {"review", "read"},
    "soc_analyst": {"review", "read"},
    "legal_counsel": {"review", "read"},
    "viewer": {"read"},
}
```

These roles are enforced by `_require_tenant_capability()` and `_enforce_review_approval_role()`.
The multi-tenant authentication mode (`REMORA_API_TOKENS`) binds tokens to (tenant, role) pairs.

### 1.4 Wrangler Deploy (Cloudflare Workers)

Deployment is controlled by `CLOUDFLARE_API_TOKEN` (GitHub Secret) and invoked by the
GitHub Actions workflow `deploy-aromer-worker.yml`. No branch protection rules or
environment-level approval gates are configured in the workflow.

### 1.5 R2 Artifact Store

| Bucket | Binding | Worker | Content | Current control |
|--------|---------|--------|---------|-----------------|
| `remora-artifacts` | `ARTIFACTS` | agent-control | Agent action artifacts | Worker-scoped binding; path validation required before write (checklist item) |

---

## 2. Roles

The following roles are proposed for the REMORA system. Roles in the "API layer" column
exist in code; roles in the "Infrastructure layer" column require external IAM configuration.

### 2.1 Role Definitions

| Role | Description | Layer | Status |
|------|-------------|-------|--------|
| `viewer` | Read-only access to envelopes, audit records, metrics | API | Implemented in code |
| `operator` | Can submit assessments, attach evidence, trigger reruns | API | Implemented in code |
| `reviewer` | Can submit human review decisions and follow-ups | API | Implemented in code |
| `domain_expert` | Can review decisions in their domain; read-only otherwise | API | Implemented in code |
| `senior_authority` | Senior reviewer for critical-tier approvals | API | Implemented in code |
| `audit_reader` | Read-only access to audit logs and Merkle anchors | API | Maps to `viewer` in current code |
| `policy_author` | Can propose policy changes (not yet wired to an API endpoint) | Application | NOT implemented |
| `policy_approver` | Can approve and activate policy bundle changes | Application | NOT implemented |
| `deploy` | Can trigger wrangler deploy of Cloudflare Workers | Infrastructure | Requires GitHub environment with required reviewers |
| `key_admin` | Can rotate signing keys; requires KMS/HSM access | Infrastructure | NOT implemented; requires KMS |
| `production_executor` | Can authorize actual (non-shadow) agent action execution | Application | NOT implemented; blocked by SHADOW_ONLY status |

---

## 3. Permissions Matrix

The following matrix describes what each role should be permitted to do. Cells marked
with a checkmark are designed; cells marked with a question mark require policy decisions.

### 3.1 API Endpoints

| Endpoint | viewer | operator | reviewer | domain_expert | senior_authority | audit_reader | policy_author | policy_approver | admin |
|----------|--------|----------|----------|---------------|-----------------|--------------|---------------|-----------------|-------|
| GET /v1/health | open | open | open | open | open | open | open | open | open |
| POST /v1/assess | | Y | | | | | | | Y |
| GET /v1/envelope/{id} | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| GET /v1/audit/{id} | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| POST /v1/review | | | Y | Y | Y | | | | Y |
| POST /v1/follow-up | | | Y | Y | Y | | | | Y |
| POST /v1/evidence | | Y | | | | | | | Y |
| POST /v1/rerun | | Y | | | | | | | Y |
| GET /v1/metrics | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| GET /metrics (Prometheus) | * | * | * | * | * | * | * | * | Y |
| GET /v1/policy/version | Y | Y | Y | Y | Y | Y | Y | Y | Y |

*Prometheus endpoint is publicly accessible if `REMORA_PROMETHEUS_PUBLIC=1` is set;
otherwise requires authentication.

### 3.2 Signing Key Operations

| Operation | key_admin | admin | All others |
|-----------|-----------|-------|-----------|
| Read signing key value | Y | N | N |
| Rotate signing key | Y | N | N |
| View key metadata (algorithm, rotation date) | Y | Y | N |
| Configure KMS/HSM target | Y | N | N |

**Current state:** No access control exists on signing keys. They are environment
variables accessible to any process running in the same environment. REM-022 must
establish: who has access to key rotation, what the rotation schedule is, and what
KMS/HSM infrastructure is used.

### 3.3 D1 Database Operations

| Operation | viewer | operator | reviewer | audit_reader | key_admin | admin |
|-----------|--------|----------|----------|--------------|-----------|-------|
| SELECT decisions/envelopes (own tenant) | Y | Y | Y | Y | N | Y |
| SELECT audit_log | Y | Y | Y | Y | N | Y |
| INSERT decision record | N | Y (via API) | N | N | N | Y |
| UPDATE review fields | N | N | Y (via API) | N | N | Y |
| INSERT evidence | N | Y (via API) | N | N | N | Y |
| Full D1 admin (DDL, cross-tenant) | N | N | N | N | N | Y |

**Current state:** D1 access is worker-scoped at the Cloudflare level. No application-layer
column or row-level restrictions exist. Write operations all flow through the worker API,
which enforces role checks at the endpoint level.

**Gap:** The D1 binding grants the entire worker process read/write on all tables. An
application logic bug in the worker could expose cross-tenant data. Row-level isolation
must be enforced at the SQL level (tenant_id column present in schema; used in queries).

### 3.4 Cloudflare Worker Deployment

| Operation | deploy role | admin | All others |
|-----------|-------------|-------|------------|
| `npx wrangler deploy` | Y | Y | N |
| `wrangler secret put` | Y | Y | N |
| `wrangler d1 execute` (schema changes) | Y | Y | N |
| `wrangler r2 bucket create` | Y | Y | N |

**Current state:** `CLOUDFLARE_API_TOKEN` in GitHub Secrets is the sole access control.
The workflow `deploy-aromer-worker.yml` runs on `push: branches: [main]` and
`workflow_dispatch` — the latter allows any repository collaborator with write access
to trigger a deploy without additional approval.

**Gap:** No GitHub environment with required reviewers is configured for production deploys.
No least-privilege scoped Cloudflare API token (Workers-only, not account-wide) is documented.

### 3.5 Policy Authoring and Approval

| Operation | policy_author | policy_approver | admin |
|-----------|---------------|-----------------|-------|
| Propose policy bundle change | Y | N | Y |
| Review proposed change | N | Y | Y |
| Activate new policy bundle | N | Y | Y |
| Read active policy hash | all authenticated | all authenticated | all |

**Current state:** Policy authoring is not exposed as an API capability. Policy changes
are made by modifying Python files and deploying. No dual-control / four-eyes mechanism
exists for policy changes. This is a research-phase limitation.

---

## 4. Least-Privilege Analysis

### 4.1 Implemented controls

The following least-privilege mechanisms are implemented in `servers/api.py`:

1. **Multi-tenant token binding:** When `REMORA_API_TOKENS` is set, each bearer token
   is bound to a fixed `(tenant, role)` pair at startup (`_load_token_table()`). Callers
   cannot promote their role by sending different headers.

2. **Tenant-scoped data access:** All store queries include `tenant_id` as a filter
   (`_CONTROL_PLANE_STORE.get_envelope(request_id=..., tenant_id=tenant_id)`). Tenants
   cannot read each other's envelopes through the API.

3. **Endpoint-level capability checks:** `_require_tenant_capability()` validates that
   the caller's role has the required permission before processing any request.

4. **Approval role enforcement:** `_enforce_review_approval_role()` validates that
   approval decisions are submitted by the required role (configurable per tenant).

5. **Production fail-closed:** Missing `REMORA_API_BEARER_TOKEN` in non-development
   mode raises `RuntimeError` at startup.

### 4.2 Gaps in least privilege

| Gap | Impact | Remediation |
|-----|--------|-------------|
| Single-token mode trusts X-Remora-Role header | Caller can self-assign any role after passing token check | Deprecate single-token mode; enforce multi-tenant mode in production |
| CLOUDFLARE_API_TOKEN may be account-wide | Deploy access is broader than necessary | Create a scoped token with `Workers Scripts:Edit` only |
| Worker process holds full D1 write access | An app bug could corrupt audit log | Consider append-only write path or D1 row-level triggers |
| No separation of duties on signing key | Same person can issue and verify tokens | Requires HSM or at minimum separate env var management |
| No session token rotation | Bearer tokens have no expiry mechanism | Implement token TTL and refresh in multi-tenant table |
| `admin` role has `{"*"}` permissions | Wildcard grants all future capabilities | Enumerate specific admin permissions; remove wildcard |

---

## 5. Gaps Requiring External Infrastructure

The following controls cannot be implemented with environment variables and application
code alone. They require external infrastructure decisions.

### 5.1 KMS/HSM for Signing Keys

**Current state:** All three signing keys (`REMORA_PDP_SIGNING_KEY`,
`REMORA_ENVELOPE_SIGNING_KEY`, `REMORA_AUDIT_ANCHOR_KEY`) are environment variables.
Any process with access to the environment can read the key value.

**Required:** A key management service (AWS KMS, Azure Key Vault, HashiCorp Vault, or
equivalent) where:
- The signing key material never leaves the HSM boundary
- Key usage is logged per-operation
- Key rotation is automated with configurable schedule
- Access to sign/verify is controlled by IAM policy, not environment variable

**Code reference:** `paper/remora_paper.md:209` acknowledges this gap explicitly.
`remora/governance/envelope.py:120` includes a `kms_key_id` stub field in the envelope schema.

### 5.2 Cloud IAM for Deployment

**Required:** GitHub Actions environment with required reviewers for production deploys, plus
a Cloudflare API token scoped to specific account/zone/Workers permissions.

**Minimum viable controls:**
- GitHub environment named `production` with at least one required reviewer
- `workflow_dispatch` restricted to protected environments
- Cloudflare API token with `Workers Scripts:Edit` + `D1:Edit` only (no account-level access)

### 5.3 Append-Only Audit Storage

**Required for regulated deployments:** An external append-only log (Cloudflare R2 WORM
bucket, AWS S3 Object Lock, or equivalent) that receives each audit record at write time.
The D1 hash chain provides tamper evidence but not tamper prevention — a compromised
`CONTROL_SECRET` allows D1 UPDATE operations.

**Code reference:** `docs/security/pre-deployment-review.md §5`, `docs/08-security.md`.

---

## 6. Role Resolution Flow

The following describes how roles are resolved in the current API implementation:

```
Request arrives at API endpoint
         │
         ▼
_authenticate(request) → (tenant_id, role)
         │
         ├─ REMORA_API_TOKENS set?
         │    YES: token lookup → fixed (tenant, role); headers ignored
         │    NO:  REMORA_API_BEARER_TOKEN set?
         │         YES: token validated; tenant from X-Remora-Tenant header;
         │              role from X-Remora-Role header (gap: self-promotion)
         │         NO:  REMORA_ENV=development? allow dev fallback; else 500
         │
         ▼
_require_tenant_capability(request, tenant_id, capability)
         │
         ├─ tenant_access_policy: allowed_roles check
         ├─ role_permissions_map: capability check
         └─ HTTPException 403 if not authorized
```

---

## 7. Implementation Roadmap (REM-022)

The following steps are required to close REM-022. These are NOT done; they are the
acceptance criteria.

| Step | Action | Artifact |
|------|--------|----------|
| 1 | Document signing key access list: who can read/rotate each key | `docs/assurance/rbac_design_v1.md` (this doc) |
| 2 | Document key rotation schedule and procedure | Addendum to this document or ops runbook |
| 3 | Identify KMS/HSM target for production signing key custody | Architecture decision record |
| 4 | Create scoped Cloudflare API token for deploy (Workers only) | Cloudflare dashboard action |
| 5 | Create GitHub environment `production` with required reviewers | GitHub repository settings |
| 6 | Deprecate single-token auth mode or harden header trust | Code change in `servers/api.py` |
| 7 | Document D1 row-level tenant isolation verification | Test or audit artifact |
| 8 | Create test: no cross-tenant data leakage via API | ✅ DONE 2026-07-03 — `tests/test_rbac_isolation.py` |
| 9 | Enumerate admin permissions (remove wildcard) | ✅ DONE 2026-07-03 — explicit set in `servers/api.py` + both `risk-profiles.yaml`; `"*"` branch removed; `default_role` admin→viewer |
| 10 | External review of this RBAC design | OPEN — folded into REM-021 |

REM-022 is DONE when: all steps above have artifacts committed, an external reviewer
has confirmed the design, and the artifact is at `docs/assurance/rbac_policy_v1.md`
(note: that path differs from this document's path; this document serves as the design
input; the policy document will be the formal output after review).

> **Closure deviation (2026-07-02).** REM-022 was closed 2026-06-30 without
> steps 8 (isolation test), 9 (admin-wildcard removal), and 10 (external
> confirmation) being met. The deviation is recorded in
> `remediation_register.yaml` (REM-022 notes) and the unmet steps are tracked
> as **REM-023**. This paragraph exists so the criteria above remain as
> originally written rather than being silently weakened after the fact.

---

## 8. Non-Claims

This document does NOT claim:

- That RBAC is implemented or REM-022 is closed
- That the permissions matrix above is enforced by automated tests
- That signing key access is currently restricted to named individuals
- That the system is production-ready from an access control perspective

The defensible claim is: this document describes the target RBAC state and the gap
between current implementation and that target, grounded in actual code.

---

## 9. Revision History

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-06-30 | Initial draft — Agent D assurance campaign Wave 1 |
