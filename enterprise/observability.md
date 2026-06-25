# REMORA Observability And SLOs

## Purpose

Enterprise REMORA deployments need operational telemetry that separates three
questions:

1. Is the service healthy?
2. Are decisions safe?
3. Is the system still useful?

Accuracy alone is not enough. A safe but useless system escalates everything. A
useful but unsafe system executes too much. REMORA should be monitored as a
control system.

## Golden Signals

| Signal | Metric examples |
|---|---|
| Traffic | requests per minute, requests by tenant, requests by risk tier |
| Latency | P50/P95/P99 decision latency, oracle fan-out latency, evidence latency |
| Errors | provider timeout rate, parser error rate, policy load error rate |
| Saturation | queue depth, escalation backlog, budget exhaustion rate |

## Safety Metrics

| Metric | Definition |
|---|---|
| unsafe_execution_rate | unsafe executed tool calls / total tasks |
| false_accept_rate | accepted decisions later judged incorrect / accepted decisions |
| false_block_rate | useful safe requests blocked / useful safe requests |
| critical_escalation_rate | critical requests routed to human review |
| evidence_contradiction_rate | requests with contradictory evidence |
| policy_downgrade_count | decisions downgraded by policy after model output |
| prompt_injection_intercept_rate | detected injection attempts blocked or escalated |

## Utility Metrics

| Metric | Definition |
|---|---|
| acceptance_rate | accepted requests / total requests |
| useful_completion_rate | accepted or verified useful outcomes / total useful requests |
| abstain_rate_by_domain | abstentions per domain |
| escalation_rate_by_team | escalations routed to each approval group |
| approval_latency_seconds | time from escalation to approval/rejection |
| evidence_hit_rate | requests with sufficient source evidence |

## Suggested SLOs

Initial pilot SLOs should be conservative and domain-specific:

| Area | Pilot SLO |
|---|---|
| Audit completeness | 99.9% of governed decisions have an audit row |
| Critical autonomous action | 0 critical autonomous executions |
| Tool allowlist violations | 0 violations |
| High-risk missing evidence | 0 direct accepts |
| P95 low-risk latency | under 5 seconds |
| P95 high-risk async decision | under agreed workflow SLA |
| Escalation stale time | no critical escalation older than tenant SLA |

## Required Audit Fields

Every governed decision should emit:

- request id,
- request hash,
- tenant id,
- user id or service principal,
- risk profile,
- policy version,
- policy bundle hash,
- model pool hash,
- evidence reference hashes,
- phase and trust score,
- final action,
- source of decision,
- human approval state,
- trace root hash.

## Alerting Rules

Alert immediately when:

- any critical request receives autonomous execution,
- tool allowlist violation occurs,
- audit writes fail for high or critical risk requests,
- unsafe execution rate is above target,
- policy bundle hash changes outside release window,
- prompt-injection intercepts spike,
- escalation queue breaches SLA,
- model provider timeout rate exceeds budget.

## Continuous Evaluation

Production telemetry should feed an evaluation loop:

1. Sample accepted, blocked, and escalated decisions.
2. Label outcomes with reviewer agreement and observed incidents.
3. Add hard cases to a tenant golden set.
4. Re-run policy changes against the golden set before deployment.
5. Track metric deltas by policy version.

Policy changes should not be promoted when they reduce high-risk abstention or
escalation rates without measured evidence that false accepts also decrease.
