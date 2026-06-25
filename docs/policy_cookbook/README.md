# REMORA Policy Cookbook

This cookbook gives practical starting policies for common agent action
domains. It is intentionally simple: action, environment, risk, recommended
outcome, and required evidence.

Use these pages as examples, not production policy.

| Domain | Start here |
|--------|------------|
| Database operations | [database.md](database.md) |
| Cloud operations | [cloud_ops.md](cloud_ops.md) |
| Cybersecurity triage | [cyber.md](cyber.md) |

## Outcome guide

| Outcome | Use when |
|---------|----------|
| ACCEPT | Low-risk, reversible, well-scoped action |
| VERIFY | More evidence or approval is required |
| ABSTAIN | The agent does not have enough reliable context |
| ESCALATE | High-risk, regulated, destructive, or ambiguous action |

## Hard rule

Policy decides. History may inform. Human owners approve policy changes.

