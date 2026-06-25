# REMORA Enterprise Deployment Runbook

## Purpose

This runbook describes a secure, scalable deployment pattern for REMORA as an AI
control plane. It is written for platform teams preparing a pilot or production
readiness assessment.

## Reference Topology

```text
User / app / agent
  -> API gateway / service mesh
  -> REMORA gateway
  -> intent and risk classifier
  -> policy engine
  -> oracle router
  -> evidence connectors
  -> decision gate
  -> audit ledger
  -> answer, abstention, escalation, or approved tool executor
```

## Environment Layout

| Environment | Purpose | Tool execution | External model calls |
|---|---|---|---|
| local | developer tests | dry-run only | optional |
| ci | reproducibility and regression | disabled | disabled |
| dev | integration testing | sandbox only | tenant allowlist |
| staging | pilot rehearsal | sandbox or shadow mode | tenant allowlist |
| production | governed runtime | allowlist + approval only | tenant allowlist |

## Deployment Prerequisites

- Enterprise identity provider with OIDC or SAML.
- Tenant registry with risk-profile mapping.
- Secrets manager for model provider keys and connector credentials.
- Append-only audit datastore.
- Approved evidence sources and source freshness rules.
- Tool executor with allowlist and dry-run support.
- Human approval workflow for high and critical risk tiers.
- Dashboard and alerting stack.

## Configuration Bundles

Each deployment should version these as a single release bundle:

- REMORA application version
- `enterprise/policy_as_code_example.yaml` or tenant-specific policy
- risk profile version
- oracle provider allowlist
- evidence connector allowlist
- tool allowlist
- audit retention policy
- escalation routing table

The bundle hash should be written to every audit ledger row.

## Scaling Model

REMORA scales along four axes:

| Axis | Scaling mechanism |
|---|---|
| Request volume | Stateless gateway replicas behind load balancer |
| Oracle latency | Async fan-out, timeouts, provider fallback, budget caps |
| Evidence retrieval | Cached retrieval, per-tenant indexes, source freshness filters |
| Audit writes | Append-only partitioned ledger with async export |

Recommended runtime behavior:

- Use queue-backed execution for high-latency verification workflows.
- Keep low-risk FAQ and read-only lookup paths synchronous.
- Put high and critical risk requests into durable workflows.
- Cache deterministic evidence lookups by source hash and query hash.
- Cache oracle responses only when policy allows storing model output.

## Reliability Patterns

### Circuit Breakers

- Provider timeout -> `VERIFY`
- Provider outage -> fallback provider if allowed, otherwise `ABSTAIN`
- Evidence connector outage -> `VERIFY` or `ESCALATE` for medium and above
- Audit ledger outage -> block high and critical decisions
- Tool executor uncertainty -> `ESCALATE`

### Budget Guards

- Per-request oracle call budget.
- Per-tenant cost budget.
- Per-domain escalation budget alerts.
- Hard stop on recursive critique or self-consistency loops.

### Backpressure

- Queue high-risk requests.
- Degrade low-risk requests to fewer oracles under load.
- Never degrade high-risk policy into lower scrutiny.
- Prefer `VERIFY` over forced answer when budget is exhausted.

## Secure Tool Execution

Production tool execution should use a dedicated executor service:

- no direct shell access from model context,
- no production credentials in prompts,
- explicit typed schemas for every tool,
- allowlist by tenant and risk profile,
- dry-run before mutation,
- approval token required for high-risk action,
- immutable record of proposed args and approved args,
- sandbox escape detection for file/database/network operations.

Critical operations remain recommendation-only.

## Rollout Plan

1. Deploy in shadow mode.
2. Compare REMORA decisions with current human/team decisions.
3. Tune policy thresholds only on calibration data.
4. Enable blocking for high-risk unsafe actions.
5. Enable human-gated approvals.
6. Enable limited low-risk automation.
7. Review pilot metrics and incident logs.
8. Promote only if production gates are satisfied.

## Rollback Plan

- Disable autonomous `EXECUTE` outcomes.
- Route all medium and above requests to `VERIFY`.
- Fall back to read-only answer mode.
- Preserve audit logging.
- Keep human escalation channel active.

## Operational Checks

Daily:

- policy bundle hash matches deployed version,
- audit writer is healthy,
- model providers are within timeout and error SLO,
- escalation queue has no stale critical items,
- unsafe execution rate remains at target,
- evidence connector freshness checks pass.

Weekly:

- sample accepted decisions for reviewer agreement,
- review false blocks and false accepts,
- inspect policy override patterns,
- check cost and latency trends,
- refresh golden evaluation set with accepted incidents.
