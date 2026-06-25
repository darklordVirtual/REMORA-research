# REMORA Production Readiness

## Readiness Position

REMORA is currently a research-grade control-plane prototype with strong
reproducibility and a growing enterprise architecture layer. It should not be
presented as production certified.

The right enterprise position is:

> REMORA is deployable as a controlled pilot for AI trust routing and tool-call
> governance when placed behind enterprise identity, policy-as-code, audit
> logging, dry-run tool execution, and human approval workflows.

## Readiness Scorecard

| Area | Current status | Production gate |
|---|---|---|
| Core policy engine | Implemented and tested | Versioned policy API and compatibility tests |
| Multi-oracle consensus | Implemented and benchmarked | Provider reliability and latency SLOs |
| Tool-call simulator | Implemented | Production executor must remain default-deny |
| Sandbox execution | Implemented for local proxy effects | Isolated runtime with egress controls |
| Audit ledger | Schema designed | Deployed append-only storage and retention policy |
| Policy-as-code | Designed | Validated schema, review workflow, signed policy bundle |
| RBAC | Designed | OIDC/SAML integration and role mapping |
| Human approval | Designed | Workflow engine integration and rejection path |
| Observability | Designed | Dashboards, alerts, SLO burn-rate policies |
| Incident response | Designed | Runbooks tested in tabletop exercises |
| External validation | Partial | Independent benchmark and domain-data pilot |
| Production certification | Not claimed | Security review, privacy review, operational acceptance |

## Deployment Stages

### Stage 0: Offline Review

Goal: prove the repository is reproducible and internally consistent.

Required:

- Run full test suite.
- Regenerate benchmark artifacts.
- Verify claim ledger against artifacts.
- Review threat model and policy pack.

Exit criteria:

- Tests pass.
- No unsupported production claims.
- Policy defaults fail closed.

### Stage 1: Shadow Mode

Goal: observe REMORA decisions without affecting users or systems.

Pattern:

- Existing AI workflow runs normally.
- REMORA receives a copy of the request and proposed answer/action.
- REMORA writes a decision trace but does not block or execute.

Metrics:

- action distribution
- abstain rate
- escalation rate
- disagreement rate
- evidence missing rate
- predicted unsafe action count
- latency and cost per request

Exit criteria:

- No critical policy bypass.
- Decision traces are complete.
- Human reviewers agree that escalations are meaningful.

### Stage 2: Human-Gated Pilot

Goal: allow REMORA to block, verify, or escalate, but not autonomously act.

Pattern:

- REMORA can return `ACCEPT`, `VERIFY`, `ABSTAIN`, or `ESCALATE`.
- Tool calls remain dry-run or sandbox-only.
- High-risk and critical decisions require explicit approval.

Exit criteria:

- False accept rate is below agreed pilot threshold.
- Escalation queue is operationally manageable.
- Audit ledger supports review and replay.

### Stage 3: Limited Low-Risk Automation

Goal: permit only pre-approved low-impact actions.

Allowed:

- read-only lookup
- write to sandbox path
- create draft ticket
- create draft report
- trigger deterministic dry-run

Not allowed:

- production mutation
- irreversible data change
- external customer communication
- access-control change
- safety or operational technology action

Exit criteria:

- Zero sandbox escape events.
- Tool allowlist enforced.
- Rollback and kill switch tested.

### Stage 4: Enterprise Runtime

Goal: operate REMORA as a governed AI control plane.

Required:

- multi-tenant gateway
- identity and RBAC integration
- signed policy bundles
- append-only audit ledger
- provider routing and budget controls
- SLO dashboards
- incident response process
- continuous evaluation harness

## Non-Negotiable Production Controls

- Default deny tool execution.
- Critical tier is recommendation-only.
- High-risk actions require human approval.
- Every decision records policy version and model pool hash.
- Evidence must be source-typed and freshness-checked.
- Production credentials are never exposed to model context.
- Dry-run is required before mutable workflows.
- Direct model/tool bypass must be monitored.
- Rollback and kill switch must be tested before pilot.

## Pilot Metrics

| Metric | Why it matters |
|---|---|
| Unsafe execution rate | Primary safety metric for action gating |
| False accept rate | Measures incorrect trust |
| False block rate | Measures lost utility |
| Abstain rate by domain | Reveals domain readiness and evidence gaps |
| Escalation rate by team | Shows human workflow load |
| Approval latency | Measures operational friction |
| Evidence missing rate | Indicates corpus quality |
| Oracle timeout rate | Indicates provider reliability |
| Cost per governed request | Supports scaling decisions |
| P95/P99 latency | Determines user experience and workflow fit |

## Honest Production Boundary

REMORA can be prepared for enterprise pilots now. It should not be described as
production-proven until a real deployment records:

- live domain traffic,
- approved authority boundaries,
- measured reviewer agreement,
- measured false accept and false block rates,
- incident response performance,
- and independent reproduction of benchmark results.
