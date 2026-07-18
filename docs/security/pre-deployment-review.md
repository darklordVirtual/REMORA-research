# REMORA Pre-Deployment Security Review

**Status:** Required before any production deployment  
**Scope:** Cloudflare Workers (agent-control, rag-oracle, law-search), Python core  
**Framework:** OWASP Top 10, OWASP GenAI Top 10 (see `docs/security/owasp_genai_mapping.md`)

---

## 1. Authentication & Authorization

### agent-control Worker

| Endpoint | Method | Auth Required | Status |
|---|---|---|---|
| `/execute` | POST | ✅ Bearer (CONTROL_SECRET) | ✅ Fixed |
| `/sessions` | POST | ✅ Bearer (CONTROL_SECRET) | ✅ Fixed |
| `/sessions/:id` | DELETE | ✅ Bearer (CONTROL_SECRET) | ✅ Fixed |
| `/audit` | GET | ✅ Bearer (CONTROL_SECRET) | ✅ Fixed (was open) |
| `/test-bindings` | GET | ✅ Bearer (CONTROL_SECRET) | ✅ Fixed (was open) |
| `/tools` | GET | Public | Intentional |
| `/status` | GET | Public (no upstream URLs) | ✅ Fixed |

**Action required before go-live:** `wrangler secret put CONTROL_SECRET`

### rag-oracle Worker

| Endpoint | Method | Auth Required | Status |
|---|---|---|---|
| `/ingest` | POST | ✅ Bearer (ORACLE_SECRET) | ✅ Fixed (was fail-open) |
| `/query` | POST | Public (read-only) | Intentional, review if RAG content is sensitive |
| `/status` | GET | Public | OK |

**Action required before go-live:** `wrangler secret put ORACLE_SECRET`  
**Critical:** Previous code was fail-open if `ORACLE_SECRET` unset. Now fail-closed.

---

## 2. Input Validation

| Location | Risk | Status |
|---|---|---|
| `/execute` body: `tool`, `input`, `session_id` | Missing field returns 400 | ✅ Validated |
| `/ingest` body: `content`, `source`, `domain` | Passed to AI model | ⚠️ No max-length guard, add `content.slice(0, 50_000)` before embedding |
| SQL queries (D1 bindings) | All parameterised via `.bind()` | ✅ No SQL injection risk |
| `store_artifact` key | Written to R2, path traversal risk | ⚠️ Validate key matches `[a-zA-Z0-9/_\-\.]+` before write |
| Shell commands in agent_hook | AST-primary, regex fallback | ✅ See `remora/agent_hook.py` |

---

## 3. CORS Policy

Current setting: `Access-Control-Allow-Origin: *`

**Risk:** Any web page can make credentialed requests to the worker endpoints.  
**Recommendation for production:** Restrict to known origins.

```typescript
// Replace in both workers before production:
const ALLOWED_ORIGINS = ["https://your-frontend.com", "https://your-claude-host.com"];
const origin = request.headers.get("Origin") ?? "";
const corsOrigin = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
```

**Current status:** Acceptable for development/demo. Must restrict before customer-facing deploy.

---

## 4. Secrets Management

| Secret | Worker | Set via | Rotation |
|---|---|---|---|
| `CONTROL_SECRET` | agent-control | `wrangler secret put` | Rotate on any team change |
| `ORACLE_SECRET` | rag-oracle | `wrangler secret put` | Rotate on any team change |
| `REMORA_SECRET` | agent-control | `wrangler secret put` | Rotate on any team change |
| `RAG_SECRET` | agent-control | `wrangler secret put` | Rotate on any team change |

**Never** store secrets in `wrangler.toml`, environment variables in git, or `.env` files.  
**Verify:** `git grep -r "secret\|password\|token" wrangler.toml` should return nothing sensitive.

---

## 5. Audit Log Integrity

The D1 `audit_log` table is append-mostly but allows `UPDATE` via the `audit_decision`
tool (to record human approval/rejection).

**Risk:** A compromised `CONTROL_SECRET` allows overwriting approval fields.  
**Recommendation for regulated deployments:** Enable D1 point-in-time recovery, or
pipe audit records to an external append-only log (e.g., Cloudflare R2 WORM bucket).

---

## 6. Rate Limiting

No rate limiting is currently implemented on any worker endpoint.

**Risk:** A leaked `CONTROL_SECRET` enables unbounded `/execute` calls, driving up
AI inference costs and polluting the audit log.

**Recommendation:** Add Cloudflare Rate Limiting rules (100 req/min per IP) before
production. Can be set in the Cloudflare dashboard without code changes.

---

## 7. Dependency Supply Chain

Python core has zero runtime dependencies (`dependencies = []` in pyproject.toml).  
Optional extras pull in well-maintained packages (openai, groq, boto3, cryptography).

Cloudflare Worker dependencies (see `package.json`): review with `npm audit` before deploy.

```bash
cd workers/agent-control && npm audit
cd workers/rag-oracle && npm audit
```

---

## 8. Data Privacy

- `input_preview` (120 chars) and `output_preview` (120 chars) are stored in `audit_log`
- If user queries contain PII, these previews contain PII
- **GDPR action required:** Classify `audit_log` as personal data, implement retention
  policy, enable right-to-erasure via session deletion

---

## 9. Deployment Checklist

Before any production deployment, confirm:

- [ ] `CONTROL_SECRET` set via `wrangler secret put` (non-empty, cryptographically random)
- [ ] `ORACLE_SECRET` set via `wrangler secret put` (non-empty, cryptographically random)
- [ ] CORS `Access-Control-Allow-Origin: *` replaced with allowlist
- [ ] R2 key validation added to `store_artifact` handler
- [ ] Content length guard added to `/ingest` handler
- [ ] Rate limiting configured in Cloudflare dashboard
- [ ] `npm audit` clean on both workers
- [ ] D1 backup / PITR enabled
- [ ] Reviewed against `docs/security/owasp_genai_mapping.md` gaps section
- [ ] Penetration test or security review by a person not on the development team

---

## 10. Known Gaps (Honest Failure Surface)

| Gap | Risk | Mitigation |
|---|---|---|
| No /query auth on rag-oracle | Anyone can query the knowledge base | Accept if KB is non-sensitive; add auth if sensitive |
| CORS wildcard | CSRF risk for browser-based callers | Restrict origins before browser-facing deploy |
| No rate limiting | DoS / cost amplification | Add CF Rate Limiting rules |
| Audit log UPDATE allowed | Approval records can be overwritten | WORM log for regulated deployments |
| No mTLS between workers | Service binding calls unencrypted in transit | Enable mTLS in Cloudflare Zero Trust if required |

This document is maintained by the development team and should be reviewed before
each major release. Last updated: 2026-05-28.
