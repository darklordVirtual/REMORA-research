# REMORA Enterprise Readiness Pack

This folder describes how REMORA can be evaluated as an enterprise AI control
plane. The documents are deployment design artifacts, not claims of production
certification.

## Read This First

| Document | Use |
|---|---|
| [`executive-brief.md`](executive-brief.md) | Strategic summary for leaders and reviewers |
| [`ENTERPRISE_LICENSE.md`](ENTERPRISE_LICENSE.md) | Hosted/managed, support, certification, and pro-layer commercial boundary |
| [`architecture.md`](architecture.md) | Control-plane architecture and component map |
| [`production-readiness.md`](production-readiness.md) | Readiness scorecard, rollout gates, and production boundary |
| [`deployment-runbook.md`](deployment-runbook.md) | Secure deployment, scaling, rollback, and operations runbook |
| [`threat-model.md`](threat-model.md) | Threat model, trust boundaries, abuse cases, and controls |
| [`policy-model.md`](policy-model.md) | Risk tiers and decision outcomes |
| [`risk-profiles.yaml`](risk-profiles.yaml) | Full machine-readable risk profile design |
| [`policy_as_code_example.yaml`](policy_as_code_example.yaml) | Compact fail-closed policy-as-code example |
| [`nested_governance_layers.yaml`](nested_governance_layers.yaml) | Multi-frequency memory and governance layer policy |
| [`human-approval-workflow.md`](human-approval-workflow.md) | Approval states, separation of duties, and authority boundaries |
| [`observability.md`](observability.md) | SLOs, safety metrics, alerting, and continuous evaluation |
| [`audit-ledger-schema.sql`](audit-ledger-schema.sql) | PostgreSQL audit ledger schema with retention/RLS concepts |
| [`tool-governance.md`](tool-governance.md) | Enterprise tool governance — risk tiers, gated execution, MFA, zero-trust credentials, prompt injection policy |
| [`integration-patterns.md`](integration-patterns.md) | Integration with enterprise systems |
| [`industrial-use-case.md`](industrial-use-case.md) | Generic industrial maintenance recommendation gate |
| [`sector-use-cases.md`](sector-use-cases.md) | Broader domain use cases |

## Enterprise Design Goal

REMORA should sit between AI systems and consequential decisions:

```text
AI request or proposed action
  -> identity and tenant context
  -> risk profile
  -> evidence requirements
  -> multi-oracle consensus
  -> policy decision
  -> audit trace
  -> answer, abstention, escalation, or approved low-risk action
```

## Deployment Principle

The safe default is not "answer anyway." The safe default is:

- answer when evidence and consensus are sufficient,
- verify when uncertainty is manageable,
- abstain when trust is insufficient,
- escalate when authority or risk exceeds automation boundaries.

Critical operations are recommendation-only. Production mutation requires
explicit policy permission, dry-run support, audit logging, and human approval.

## Current Maturity

REMORA is currently suitable for:

- architecture review,
- controlled demonstrations,
- offline and replay evaluation,
- shadow-mode enterprise pilot planning,
- policy and governance design discussions.

REMORA is not yet production certified. Production readiness requires identity
integration, signed policy bundles, deployed audit storage, approval workflow
integration, live-domain validation, SLO monitoring, and incident response
testing.

## Commercial Boundary

The public REMORA repository is Apache-2.0 open source. Hosted or managed
offerings under AROMER or Luftfiber AS branding, official SaaS/control-plane
deployments, certification, compliance, support, audit packages, and closed
pro-layer extensions require a separate written enterprise agreement with
Luftfiber AS / Stian Skogbrott. GO-STAR, law search, DCE, private policy packs,
customer integrations, and other custom modules are proprietary Luftfiber AS /
Stian Skogbrott solutions unless separately released as open source. See
[`ENTERPRISE_LICENSE.md`](ENTERPRISE_LICENSE.md) and
[`../TRADEMARKS.md`](../TRADEMARKS.md).

## Related Research Context

The nested governance and continuum-memory terminology is attributed in
[`../docs/related_work.md`](../docs/related_work.md) and
[`../docs/nested_governance.md`](../docs/nested_governance.md). REMORA uses
those ideas as governance architecture, not as a claim that it implements
model-level continual learning or self-modifying training.
