# What are the security properties and known gaps?

This document covers the threat model, OWASP GenAI Top 10 mapping, and the
pre-deployment checklist. Status: internal mapping, not externally audited.

Companion documents:
- `enterprise/threat-model.md`, full threat narrative and controls
- `enterprise/policy-model.md`, OPA policy gates
- `docs/security/owasp_genai_mapping.md`, source for the mapping table below

→ [01-architecture.md](01-architecture.md) for architectural context.
→ [07-api-reference.md](07-api-reference.md) for the adversarial detection API.

---

## Threat model summary

REMORA is an application-layer governance overlay. It does not control model
weights, inference infrastructure, or network perimeter. Its threat surface is:

1. **Prompt injection**, malicious content in user input or retrieved documents
   instructing the model to bypass policy.
2. **Tool-call abuse**, agent invokes a tool outside its role/clearance scope or
   with malformed arguments.
3. **Audit tampering**: modification of past `DecisionEnvelope` records.
4. **Oracle failure**: all oracles agree and are all wrong (correlated failure).
5. **Governance forgetting**: a temporary exception becomes permanent behaviour.

REMORA addresses 1–5 at the application layer with the controls below. It does
not prevent host-level attacks, model extraction, or infrastructure compromise.

---

## OWASP GenAI Top 10 mapping

| OWASP Risk | Controls implemented | Status | Known gap |
|---|---|---|---|
| LLM01 Prompt Injection | PreToolUse hook AST guard (`remora/agent_hook/`), retrieved text treated as data, injection-indicator escalation, audit log of detection | Partial | No semantic NLI injection detection yet |
| LLM02 Insecure Output | Tool-call schema validation (`remora/toolcall/`), allowlist-only tool execution (`enterprise/risk-profiles.yaml`), dry-run simulation | Implemented for tool calls | No HTML-output escaping (integrator responsibility for rendered output) |
| LLM03 Training Data Poisoning | Multi-oracle consensus (3 independent families), `OracleDiversityTracker` (warns at ρ > 0.60), independent judge verification (Stage 3) | Partial | No corpus poisoning detection in retrieval store |
| LLM04 Model DoS | `budget_oracle_calls` hard cap, stage short-circuit on terminal verdict, tenant isolation (infra-level) | Budget cap implemented | Tenant isolation is infrastructure-level |
| LLM05 Supply Chain | Pure Python core, pinned `pyproject.toml` deps, signed artifacts, deterministic locked benchmarks | Implemented at code level | Infra signing is deployer responsibility |
| LLM06 Sensitive Disclosure | Secret-pattern detection in file risk classifier (`remora/safety/`), context isolation, audit redaction runbook | Partial | No PII detection in free-form model output |
| LLM07 Insecure Plugin | Policy gate + OPA (`remora/policy/`), risk-profile allowlist, default-deny on missing policy | Implemented |, |
| LLM08 Excessive Agency | Autonomy degradation (`remora/governance/`), human approval workflow (`enterprise/human-approval-workflow.md`), `ESCALATE` on high uncertainty, Lyapunov V(t) drift detection | Implemented |, |
| LLM09 Overreliance | Selective abstention, Platt-scaled confidence calibration, uncertainty decomposition (epistemic vs aleatoric), explicit `VERIFY` verdict | Implemented |, |
| LLM10 Model Theft | System prompt isolation (programmatic construction, not user-accessible), audit trail (question hash logged by default) | Application-layer only | Model extraction protection is inference-infrastructure responsibility |

**Overall posture:** REMORA addresses 8/10 OWASP GenAI risks at the application
layer. LLM03 (corpus poisoning detection) and LLM06 (PII in free-form output)
remain partial gaps requiring additional tooling outside REMORA's current scope.

---

## Pre-deployment checklist

Before any production deployment, confirm all items below. Source:
`docs/security/pre-deployment-review.md`.

### Authentication

- [ ] `CONTROL_SECRET` set via `wrangler secret put` (non-empty, cryptographically random)
- [ ] `ORACLE_SECRET` set via `wrangler secret put` (non-empty, cryptographically random)
- [ ] `/audit` and `/test-bindings` endpoints require Bearer auth (previously open, fixed)
- [ ] `/ingest` endpoint is fail-closed when `ORACLE_SECRET` is unset (previously fail-open, fixed)

### Input validation

- [ ] Content length guard added to `/ingest` handler (`content.slice(0, 50_000)`)
- [ ] R2 key validation matches `[a-zA-Z0-9/_\-\.]+` before write (path traversal risk)
- [ ] SQL queries use parameterised `.bind()` calls (no SQL injection risk in current code)

### CORS

- [ ] `Access-Control-Allow-Origin: *` replaced with origin allowlist before browser-facing deploy
  ```typescript
  const ALLOWED_ORIGINS = ["https://your-frontend.com"];
  ```

### Secrets management

- [ ] No secrets in `wrangler.toml`, `.env`, or git history
  ```bash
  git grep -r "secret\|password\|token" wrangler.toml  # must return nothing sensitive
  ```
- [ ] Rotation plan in place for `CONTROL_SECRET`, `ORACLE_SECRET`, `REMORA_SECRET`, `RAG_SECRET`

### Audit integrity

- [ ] D1 backup / PITR enabled
- [ ] For regulated deployments: append-only external log (R2 WORM bucket) in place
  (hash chains detect tampering; preventing full-chain replacement requires WORM storage)

### Rate limiting

- [ ] Cloudflare Rate Limiting rules configured (100 req/min per IP minimum)
  (no rate limiting currently implemented, risk of DoS / cost amplification on leaked secret)

### Dependencies

- [ ] `npm audit` clean on `workers/agent-control` and `workers/rag-oracle`

### Privacy

- [ ] `audit_log` classified as personal data if queries contain PII
- [ ] Retention policy and right-to-erasure implemented for session records

### Final review

- [ ] Reviewed against `docs/security/owasp_genai_mapping.md` gaps section
- [ ] Penetration test or security review by a person not on the development team

---

## Known gaps (honest failure surface)

| Gap | Risk | Required mitigation |
|---|---|---|
| No `/query` auth on `rag-oracle` | Anyone can query the knowledge base | Accept if KB is non-sensitive; add auth if sensitive |
| CORS wildcard | CSRF risk for browser-based callers | Restrict origins before browser-facing deploy |
| No rate limiting | DoS / cost amplification | Add CF Rate Limiting rules |
| Audit log `UPDATE` allowed | Approval records can be overwritten | WORM log for regulated deployments |
| No mTLS between workers | Service binding calls unencrypted in transit | Enable mTLS in Cloudflare Zero Trust if required |
| No semantic injection detection | Sophisticated indirect injection not caught | NLI/semantic entailment model at retrieval layer |
| No PII detection in free-form output | Model may leak PII in text responses | Dedicated NER/PII classifier at output layer |

---

## Cyber evidence layer

REMORA includes a standalone public cyber evidence layer for security finding
triage (`remora/evidence/cyber.py`, `datasets/cyber_evidence_v1/`). It provides:

- exact lookup for CVE, CWE, ATT&CK, KEV, EPSS, package-version identifiers,
- RAG/vector search over advisory narratives and remediation text,
- exploit classification (`KNOWN_EXPLOITED`, `PUBLIC_EXPLOIT_LIKELY`,
  `EMERGING_OR_UNKNOWN`, `WEAK_OR_UNCORROBORATED`, `LIKELY_FALSE_POSITIVE`),
- defensive PoC plans (not exploit payloads, production exploitation is
  explicitly blocked by the provider API).

What this layer does not claim: it is not a full vulnerability database, not
scanner accuracy evidence, does not prove GO-STAR performance, and does not
auto-update policy. See `docs/cyber_evidence_layer.md`.
