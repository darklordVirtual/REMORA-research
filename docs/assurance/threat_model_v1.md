# REMORA Threat Model v1

**Status:** Draft — initial STRIDE analysis for assurance campaign Wave 1
**Date:** 2026-06-30
**Author:** Agent D (security/RBAC audit)
**Scope:** `darklordVirtual/REMORA-research` at commit `2cd573d` (master branch)
**Related gates:** REM-022 (NOT_STARTED), REM-021 (NOT_STARTED)

This document is grounded exclusively in code and files that exist in the repository.
No capabilities are invented. Claims marked as gaps are gaps; claims marked as
implemented refer to specific code locations.

---

## 1. System Overview

REMORA is a research-grade governance overlay for autonomous AI agent actions. It
decides whether an agent action is ACCEPT, VERIFY, ABSTAIN, or ESCALATE based on
uncertainty, evidence, policy, auditability, and human review.

**Deployment topology (as configured in `workers/agent-control/wrangler.toml`):**

```
Agent caller
    |
    v
[agent-control Worker]  ← bearer auth (CONTROL_SECRET)
    |          |
    |          +──── [LAW_SERVICE binding] → remora-law-search worker
    |
    +──── [REMORA_SERVICE binding] → go-star-remora worker
    |
    +──── [D1: remora-audit] ← audit log
    +──── [R2: remora-artifacts] ← artifact store
    +──── [KV: SESSIONS] ← session state
    |
servers/api.py (FastAPI)
    |
    +──── PolicyDecisionPoint (remora/enforcement/token.py)
    |         |  HMAC-SHA256 token
    |         v
    +──── PolicyEnforcementPoint (remora/enforcement/gate.py)
    |
    +──── [Oracle swarm] (3+ model calls)
    |
    +──── [AROMER D1] ← episode/decision log
```

**RAG oracle (`workers/rag-oracle/` — directory present, no source TypeScript found):**

The pre-deployment review (`docs/security/pre-deployment-review.md`) and main security
doc (`docs/08-security.md`) document an `rag-oracle` worker with endpoints:
- `POST /ingest` — bearer auth (ORACLE_SECRET), previously fail-open
- `POST /query` — public (read-only by design)
- `GET /status` — public

**Key signing surface:** Two HMAC keys control the security of the governance chain:
- `REMORA_PDP_SIGNING_KEY` — signs PolicyDecisionTokens (PDP→PEP)
- `REMORA_ENVELOPE_SIGNING_KEY` — signs audit envelope hashes (API layer)
- `REMORA_AUDIT_ANCHOR_KEY` — signs daily Merkle root anchors (`remora/audit/anchor.py`)

---

## 2. Trust Boundaries

```
═══════════════════════════════════════════════════════════════════════════
  EXTERNAL (untrusted) zone
  ─────────────────────────────────────────────────────────────────────────
  Agent callers, browser clients, third-party API consumers
═══════════════════════════════════════════════════════════════════════════
                              │
                    [TB-1: API boundary]
                    Bearer token required in production
                    (REMORA_API_BEARER_TOKEN or REMORA_API_TOKENS)
                              │
═══════════════════════════════════════════════════════════════════════════
  APPLICATION zone
  ─────────────────────────────────────────────────────────────────────────
  servers/api.py — FastAPI gateway
  remora/engine.py — Remora orchestrator
  remora/policy/ — Decision engine + OPA adapter
═══════════════════════════════════════════════════════════════════════════
                              │
                   [TB-2: PDP/PEP boundary]
                   HMAC-SHA256 signed token
                              │
                   remora/enforcement/gate.py
═══════════════════════════════════════════════════════════════════════════
  ORACLE zone (external LLM providers)
  ─────────────────────────────────────────────────────────────────────────
  OpenAI / Cloudflare AI Gateway / Groq / HuggingFace
═══════════════════════════════════════════════════════════════════════════
                              │
                   [TB-3: Cloudflare Workers boundary]
                   wrangler secret put; no plaintext in toml
                              │
  [agent-control worker] ←→ [D1: remora-audit] ←→ [R2: remora-artifacts]
  [rag-oracle worker] ←→ [D1: rag knowledge base]
═══════════════════════════════════════════════════════════════════════════
  INFRASTRUCTURE zone (Cloudflare)
  ─────────────────────────────────────────────────────────────────────────
  Cloudflare Workers runtime, D1, R2, KV, service bindings
═══════════════════════════════════════════════════════════════════════════
```

**Trust boundary definitions:**

| ID | Boundary | What crosses it | Control |
|----|----------|-----------------|---------|
| TB-1 | API gateway perimeter | HTTP requests from callers | Bearer token auth; Pydantic input validation |
| TB-2 | PDP/PEP internal | PolicyDecisionToken dataclass | HMAC-SHA256 signature + observation hash binding |
| TB-3 | Cloudflare Worker | Wrangler deploy + secrets | `wrangler secret put`; CLOUDFLARE_API_TOKEN in CI |
| TB-4 | Oracle providers | LLM API calls | Provider API keys; CF AI Gateway routing |
| TB-5 | D1 database | SQL via `.bind()` parameterized | No direct external write path; worker-scoped binding |

---

## 3. STRIDE Threat Enumeration

### 3.1 Spoofing

| ID | Threat | Component | Mitigation implemented | Gap |
|----|--------|-----------|----------------------|-----|
| S-1 | Caller forges tenant or role via HTTP headers | `servers/api.py` `_authenticate()` | Multi-tenant mode (REMORA_API_TOKENS): token→(tenant,role) mapping — headers cannot forge identity. Single-token mode: headers accepted for tenant/role (lower assurance). | Single-token mode trusts X-Remora-Tenant/X-Remora-Role headers — see api.py:876 |
| S-2 | PEP receives forged unsigned PolicyDecisionToken | `remora/enforcement/gate.py` | HMAC-SHA256 signature verified before allowing execution; strict mode rejects unsigned tokens | Key management not enforced (env var with no rotation) |
| S-3 | Attacker replays a valid token for a different observation | `remora/enforcement/token.py` | Observation hash binds token to specific PolicyObservation; mismatch → rejection | No token expiry; timestamp validated for consistency only |
| S-4 | Cloudflare wrangler deploy from unauthorized CI runner | `.github/workflows/deploy-aromer-worker.yml` | CLOUDFLARE_API_TOKEN injected from GitHub Secrets; not in wrangler.toml | No branch protection rule enforced in workflow (workflow_dispatch allowed by anyone with repo write) |
| S-5 | Caller spoofs X-Remora-Actor identity in audit log | `servers/api.py` `_actor_identity` | Actor identity is stored but not verified against the bearer token | Actor is caller-supplied; no identity binding |

### 3.2 Tampering

| ID | Threat | Component | Mitigation implemented | Gap |
|----|--------|-----------|----------------------|-----|
| T-1 | Attacker modifies audit log records in D1 | `remora/adapters/storage/control_plane.py` | Hash chain: each envelope stores `previous_hash` linking to prior record | D1 allows UPDATE; approval fields can be overwritten (documented in `docs/security/pre-deployment-review.md §5`) |
| T-2 | RAG ingest with malicious content to poison knowledge base | `workers/rag-oracle` `/ingest` endpoint | ORACLE_SECRET bearer auth now required (fixed, was fail-open) | No content-length guard in `/ingest` (documented risk); no semantic content validation |
| T-3 | Policy engine code modified between audit and execution | `remora/policy/decision_engine.py` | SHA-256 hash of policy engine files returned by `/v1/policy/version` | Hash is informational only; no code signing |
| T-4 | Wrangler toml modified to expose secrets in vars | `workers/agent-control/wrangler.toml` | Secrets are in `wrangler secret put`, not `[vars]` section | No automated check that secrets are not in plaintext (pre-deployment checklist is manual) |
| T-5 | R2 artifact path traversal | `workers/agent-control` `store_artifact` | Pre-deployment review documents path validation as required | Path validation is a checklist item, not confirmed as implemented in code |

### 3.3 Repudiation

| ID | Threat | Component | Mitigation implemented | Gap |
|----|--------|-----------|----------------------|-----|
| R-1 | Actor denies submitting a review decision | `servers/api.py` `/v1/review` | reviewer_id stored in ReviewRecord; audit hash chain links records | reviewer_id is caller-supplied string, not verified against authenticated identity |
| R-2 | PDP denies issuing a specific decision | `remora/enforcement/token.py` | Observation hash + request_id in token; audit log stores envelope_audit_hash | Tokens are in-memory only; no persistent token log independent of the envelope store |
| R-3 | Audit log records modified post-hoc | `remora/governance/audit_chain.py` | HMAC-sealed Merkle root anchors via `remora/audit/anchor.py` | Append-only storage requires external WORM bucket (documented as external requirement); D1 alone is not append-only |

### 3.4 Information Disclosure

| ID | Threat | Component | Mitigation implemented | Gap |
|----|--------|-----------|----------------------|-----|
| I-1 | Internal error messages leak DSNs, file paths, or secrets | `servers/api.py` | `_safe_error_response()` catches all unhandled exceptions; returns only correlation_id to caller | None observed; well-implemented |
| I-2 | Prometheus `/metrics` endpoint leaks governance data | `servers/api.py` `/metrics` | Protected by `_authenticate()` unless REMORA_PROMETHEUS_PUBLIC=1 | If REMORA_PROMETHEUS_PUBLIC=1 is set, metrics are public — not obvious to operators |
| I-3 | PII in audit log previews | `workers/agent-control` D1 `audit_log` | input_preview and output_preview capped at 120 chars | No PII detection; queries containing PII will appear in audit log (documented gap) |
| I-4 | Signing key value leaked in logs | `remora/enforcement/token.py` | Key is read from env var; never logged or returned in API responses | No active protection against key being logged by frameworks at startup |
| I-5 | CORS wildcard allows cross-origin requests | `workers/rag-oracle` | Pre-deployment review requires replacement with allowlist before production | CORS wildcard (`Access-Control-Allow-Origin: *`) present in dev configuration |
| I-6 | Public RAG /query endpoint exposes knowledge base | `workers/rag-oracle` `/query` | Documented as intentional for non-sensitive knowledge bases | If RAG content is sensitive, no access control exists on query path |
| I-7 | CF_AIG_TOKEN / CLOUDFLARE_API_TOKEN in workflow environment | `.github/workflows/agentharm-experiment.yml` | Injected via `${{ secrets.* }}` GitHub Secrets mechanism | Line 57: `api = HfApi(token="${{ secrets.HF_TOKEN }}")` — this is inside a Python heredoc in a shell step; GitHub will substitute the secret value into the shell script before execution. If the Python code fails or prints this value, the secret appears in runner logs. This is a workflow authoring anti-pattern. |

### 3.5 Denial of Service

| ID | Threat | Component | Mitigation implemented | Gap |
|----|--------|-----------|----------------------|-----|
| D-1 | Oracle budget exhaustion via unbounded `/assess` calls | `servers/api.py` | `_InMemoryRateLimiter` (sliding window, 120 req/min default per tenant) | Rate limiter is in-memory only; resets on process restart; no persistent distributed rate limiting |
| D-2 | Cloudflare worker cost amplification via leaked ORACLE_SECRET | `workers/rag-oracle` `/ingest` | ORACLE_SECRET bearer auth now required | No Cloudflare Rate Limiting rules configured (pre-deployment checklist item) |
| D-3 | Large input flooding `/ingest` embedding model | `workers/rag-oracle` `/ingest` | Pre-deployment review requires `content.slice(0, 50_000)` guard | Content-length guard documented as not yet implemented |
| D-4 | In-memory rate limiter bypass via multi-instance deployment | `servers/api.py` `_InMemoryRateLimiter` | Single-instance protection only | Multi-process/multi-instance deployments share no rate state |

### 3.6 Elevation of Privilege

| ID | Threat | Component | Mitigation implemented | Gap |
|----|--------|-----------|----------------------|-----|
| E-1 | Caller supplies high-privilege role in X-Remora-Role header | `servers/api.py` single-token mode | In multi-tenant mode (REMORA_API_TOKENS), role is bound to token — headers are ignored for identity | Single-token mode (REMORA_API_BEARER_TOKEN) reads role from X-Remora-Role header after token validation — caller can self-promote to any role string |
| E-2 | Non-strict PEP mode allows execution without signed token | `remora/enforcement/gate.py` | strict=False emits warning and allows unsigned tokens | If REMORA_PDP_SIGNING_KEY is absent, strict=True still exists but the gate can be instantiated with strict=False from callers |
| E-3 | Reviewer approves their own submission | `servers/api.py` `/v1/review` | review_requirements.approval_role enforced per tenant policy | reviewer_id is string; no prevention of self-approval |
| E-4 | Prompt injection bypasses policy gate | `remora/agent_hook/` | AST guard + regex fallback for shell commands; injection-indicator escalation | No semantic NLI injection detection (OWASP LLM01 partial gap) |
| E-5 | Oracle poisoning via correlated model failure | `remora/oracles/` | OracleDiversityTracker warns at ρ > 0.60; 3 independent families | Correlated failure remains a known limitation (no elimination) |

---

## 4. Mitigations Summary

| Control | Implementation | Status |
|---------|---------------|--------|
| Bearer token authentication | `servers/api.py` `_authenticate()`, HMAC compare_digest | Implemented |
| PDP→PEP signed token | `remora/enforcement/token.py`, HMAC-SHA256 | Implemented |
| Observation hash binding | `PolicyDecisionToken.observation_hash` | Implemented |
| Audit hash chain | `remora/governance/audit_chain.py`, `remora/audit/merkle.py` | Implemented |
| Daily Merkle root anchor | `remora/audit/anchor.py` | Implemented |
| Safe error responses | `_safe_error_response()` in `servers/api.py` | Implemented |
| In-memory rate limiting | `_InMemoryRateLimiter` in `servers/api.py` | Implemented (limited scope) |
| SQL injection prevention | Parameterized `.bind()` calls | Implemented |
| Input length validation | Pydantic Field constraints on AssessRequest | Implemented for API layer |
| Secret-pattern detection | `remora/safety/` file risk classifier | Implemented |
| CORS wildcard | Pre-deployment checklist | NOT implemented — checklist only |
| D1 append-only enforcement | External WORM bucket requirement | NOT implemented — external |
| Cloudflare Rate Limiting | Pre-deployment checklist | NOT implemented — checklist only |
| R2 path traversal validation | Pre-deployment checklist | NOT confirmed in code |
| RAG /ingest content-length | Pre-deployment checklist | NOT implemented — checklist only |
| RBAC for signing keys | REM-022 (NOT_STARTED) | NOT implemented |
| KMS/HSM key management | Documented as future requirement | NOT implemented |
| mTLS between workers | Documented as optional | NOT implemented |

---

## 5. Gaps Requiring Action

### Critical gaps (production-blocking)

| Gap | Risk | Required mitigation |
|-----|------|---------------------|
| No RBAC on signing keys | Unrestricted access to REMORA_PDP_SIGNING_KEY and REMORA_ENVELOPE_SIGNING_KEY | REM-022: document who can read/rotate keys; KMS/HSM target |
| D1 allows UPDATE on audit records | Approval records can be overwritten by anyone with CONTROL_SECRET | WORM bucket or append-only D1 pattern for regulated deployments |
| No Cloudflare Rate Limiting | Cost amplification if secrets leak | Cloudflare dashboard Rate Limiting rules |
| RAG /ingest content-length unguarded | Embedding model cost/DoS amplification | Add `content.slice(0, 50_000)` before embedding |

### High gaps (pre-production)

| Gap | Risk | Required mitigation |
|-----|------|---------------------|
| Single-token mode trusts X-Remora-Role header | Caller can self-promote role | Use multi-tenant mode (REMORA_API_TOKENS) in production; deprecate single-token mode |
| CORS wildcard | CSRF risk for browser callers | Restrict to allowlist before browser-facing deploy |
| HF_TOKEN in Python heredoc in CI workflow | Secret may appear in runner logs if Python prints it | Rewrite step to pass token via environment variable, not string interpolation |
| No token expiry on PolicyDecisionToken | Captured token could be replayed indefinitely | Add `exp` claim and validate issued_at within window |
| Actor identity not bound to authenticated credential | Non-repudiation gap in audit log | Bind actor_identity to token identity in multi-tenant mode |

### Medium gaps (documented, accepted for research phase)

| Gap | Risk | Accepted until |
|-----|------|----------------|
| No mTLS between workers | Internal service calls unencrypted in transit | Production deployment |
| No PII detection in free-form output | Model may leak PII in responses | Dedicated NER/PII classifier |
| No semantic injection detection | Sophisticated indirect injection | NLI/semantic entailment model |
| In-memory rate limiter non-persistent | Multi-instance bypass | Distributed rate limiting (Redis or Cloudflare) |
| RAG /query endpoint public | Knowledge base readable by anyone | Accept if content is non-sensitive |

---

## 6. Non-Claims

This threat model does NOT claim:

- That REMORA is production-certified or externally audited
- That the RBAC design is complete (REM-022 is NOT_STARTED)
- That all gaps listed above are mitigated in the current codebase
- That the system is safe against host-level attacks, model extraction, or infrastructure compromise
- That this analysis constitutes a penetration test

---

## 7. Revision History

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-06-30 | Initial draft — Agent D assurance campaign Wave 1 |
