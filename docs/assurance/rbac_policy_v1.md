# REMORA RBAC Access Control Policy v1

**Status:** Active  
**Gate:** REM-022 (P3, production deployment gate)  
**Date:** 2026-06-30  
**Scope:** Signing keys, AROMER D1 database, production API bearer tokens, worker deployment

---

## 1. Asset Inventory

| Asset | Location | Risk if compromised |
|-------|----------|---------------------|
| `REMORA_PDP_SIGNING_KEY` | Environment variable (server) | Token forgery, PEP accepts unsigned or forged decisions |
| `REMORA_ENVELOPE_SIGNING_KEY` | Environment variable (server) | Envelope hash-chain forgery, audit trail tampered undetected |
| `REMORA_API_BEARER_TOKEN` / `REMORA_API_TOKENS` | Environment variable (server) | Unauthorized API access |
| AROMER D1 database (`b91e1f0b-e2bd-4a12-9150-cda2048e508b`) | Cloudflare D1 (aromer worker binding) | Episode tampering, world model poisoning, AII manipulation |
| AROMER worker (wrangler deploy) | Cloudflare account | Malicious worker code deployed to production |
| Agent-control D1 (`642489ab-6c3d-4709-9ad0-d58896e1ce5f`) | Cloudflare D1 (agent-control binding) | Audit ledger tampering |

---

## 2. Role Matrix

Defined in `servers/api.py:_BUILTIN_ROLE_PERMISSIONS`.

| Role | assess | evidence | execute | rerun | read | review | follow_up |
|------|--------|----------|---------|-------|------|--------|-----------|
| admin | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| operator | ✓ | ✓ | ✓ | ✓ | ✓ | (|) |
| reviewer | (|) | (|) | ✓ | ✓ | ✓ |
| domain_expert | (|) | (|) | ✓ | ✓ |, |
| senior_authority | (|) | (|) | ✓ | ✓ |, |
| soc_analyst | (|) | (|) | ✓ | ✓ |, |
| legal_counsel | (|) | (|) | ✓ | ✓ |, |
| viewer | (|) | (|) | ✓ | (|) |

**Capability definitions:**
- `assess`, submit a governance request (`POST /v1/assess`)
- `evidence`, attach external evidence (`POST /v1/evidence`)
- `rerun`, replay a request deterministically (`POST /v1/rerun`)
- `read`, read envelopes and audit records (`GET /v1/envelope/*`, `GET /v1/audit/*`)
- `review`, submit human review (`POST /v1/review`)
- `execute`, execute an approved review item, consuming a one-time grant (`POST /v1/execution/execute`); granted to admin and operator only
- `follow_up`, add follow-up information (`POST /v1/follow-up`)

(`assess` also gates `POST /v1/execution/assess`; `review` gates `POST /v1/execution/approve`.)

**Role enforcement:** `X-Remora-Role` header is validated against `REMORA_API_TOKENS` tenant map or the builtin table. An empty or missing role grants zero permissions. See `servers/api.py:_require_capability()`.

---

## 3. Key Management: Current State

### 3.1 REMORA_PDP_SIGNING_KEY

- **Purpose:** HMAC-SHA256 signature on `PolicyDecisionToken`. Binds the PDP decision to a specific observation hash and request ID. PEP (`EnforcementGate`) rejects unsigned tokens in strict mode.
- **Current storage:** Environment variable on the server process. Not in any committed file.
- **Algorithm:** HMAC-SHA256 over canonical JSON payload (sorted keys, no whitespace).
- **Implemented in:** `remora/enforcement/token.py`
- **If absent:** Token is issued UNSIGNED. `EnforcementGate(strict=True)` rejects all unsigned tokens. `EnforcementGate(strict=False)` logs a warning and allows (dev/test only).
- **Gap (acknowledged):** No KMS/HSM integration. Key is a plaintext env var. Rotation requires a server restart. Formal rotation cadence, not yet defined.

### 3.2 REMORA_ENVELOPE_SIGNING_KEY

- **Purpose:** HMAC-SHA256 of the DecisionEnvelope `hash` field. Enables offline audit verification of envelope integrity.
- **Current storage:** Environment variable on the server process.
- **Algorithm:** HMAC-SHA256 over the envelope's `hash` (SHA-256 compact hash).
- **Implemented in:** `servers/api.py:_finalize_envelope_audit()`, `remora/audit/merkle.py`
- **Gap (acknowledged):** No KMS/HSM. No RFC 3161 timestamp binding.

### 3.3 API Bearer Tokens

- **Format (single-tenant):** `REMORA_API_BEARER_TOKEN=<secret>`: grants the role specified by `REMORA_API_DEFAULT_ROLE`.
- **Format (multi-tenant):** `REMORA_API_TOKENS={"<token>": {"tenant": "<id>", "role": "<role>"}}`: per-token tenant and role binding.
- **Implemented in:** `servers/api.py:_auth_token_data()`
- **Revocation:** Remove the token from `REMORA_API_TOKENS` and restart the server. No hot revocation mechanism in v1.
- **Gap (acknowledged):** No token expiry enforcement in the bearer layer (envelope token has expiry; bearer token does not). Revocation requires server restart.

---

## 4. AROMER D1 Database Access

| Control | State |
|---------|-------|
| Write access | Restricted to the `aromer` Cloudflare Worker via D1 binding. No direct SQL connection from dev machines in production. |
| Read access | Same: Worker binding only. No external DB client access. |
| Dev/test | SQLite in-memory or file (`TEST_DB_PATH` env var). Isolated from production D1. |
| Worker deployment | Requires Cloudflare account API token with `Workers Scripts:Edit` scope. Only humans with CF account access can deploy. |
| D1 binding name | `DB` (see `workers/aromer/wrangler.toml`) |

**Gap (acknowledged):** No Cloudflare Access rule enforcing that wrangler deploy is only callable from a CI/CD pipeline. A developer with a valid CF API token can deploy directly from a local machine. CI/CD pipeline access restriction is future work.

---

## 5. Worker Deployment Access

| Worker | Database binding | Deployment auth |
|--------|-----------------|-----------------|
| aromer | D1 `b91e1f0b` (episodes, adapt cycles) | CF account API token |
| agent-control | D1 `642489ab` (audit ledger) | CF account API token |
| rag-oracle | D1 `6928cf08` (chunks) | CF account API token |
| law-search | D1 `98c4cc05` (law index) | CF account API token |

All deployments: `cd workers/<name> && npx wrangler deploy`. Requires `CLOUDFLARE_API_TOKEN` with Workers:Edit + D1:Edit scopes.

---

## 6. Rotation Policy

| Asset | Recommended cadence | Procedure |
|-------|--------------------|-----------| 
| `REMORA_PDP_SIGNING_KEY` | Every 90 days, or on suspected compromise | 1. Generate new 256-bit random key. 2. Update env var on server. 3. Restart server. 4. Log rotation in this document. |
| `REMORA_ENVELOPE_SIGNING_KEY` | Every 90 days | Same as above. Old signatures remain verifiable against old key; new signatures use new key. |
| API bearer tokens | Per-tenant, on personnel change or suspected compromise | Remove old token from `REMORA_API_TOKENS`, add new token, restart server. Notify affected tenant. |
| CF API token (wrangler deploy) | Every 180 days or on team change | Regenerate in Cloudflare dashboard. Update CI/CD secrets. |

**Key generation:** `python -c "import secrets; print(secrets.token_hex(32))"`: produces 256-bit hex key.

---

## 7. Audit Log Retention

| Log | Location | Retention |
|----|----------|-----------|
| DecisionEnvelope records | `REMORA_CONTROL_PLANE_DSN` (PostgreSQL) or in-memory | Operator-defined; recommended minimum: 1 year |
| AROMER D1 episodes | Cloudflare D1 | Indefinite (no TTL configured) |
| Agent-control audit ledger | Cloudflare D1 | Indefinite |
| Server access logs | Platform/infra layer | Operator-defined |

---

## 8. Acknowledged Gaps (REM-022 scope boundary)

The following are documented as future work; they do not block REM-022 closure because this policy establishes the current control state and rotation procedure:

1. **KMS/HSM integration**: signing keys are plaintext env vars. HSM or cloud KMS (AWS KMS, GCP Cloud KMS, Cloudflare KMS) is the production target.
2. **RFC 3161 timestamp binding**: envelope signatures lack third-party timestamp authority.
3. **Bearer token expiry**: no automatic expiry on the bearer token layer (only on the inner PolicyDecisionToken).
4. **CI/CD-only wrangler deploy**: no Cloudflare Access rule enforcing pipeline-only deploys.
5. **OIDC approver binding**: reviewer identity in the `AuditBlock` is not verified against an OIDC token.

These gaps are consistent with TRL 3–4 (SHADOW_ONLY deployment). They must be resolved before production certification.

---

## 9. Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-06-30 | v1 initial policy document (closes REM-022) | REMORA assurance team |
