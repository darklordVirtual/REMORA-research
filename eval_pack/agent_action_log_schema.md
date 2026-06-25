# Agent Action Log Schema

REMORA shadow replay expects one JSON object per line. Each row describes one
agent action that would have been sent to a tool.

## Required fields

```json
{
  "timestamp": "2026-06-03T12:00:00Z",
  "session_id": "demo-session-001",
  "agent_id": "agent-001",
  "tool_name": "sql.execute",
  "proposed_action": "Delete inactive users from production database",
  "tool_args": {"query": "DELETE FROM users WHERE inactive = true"},
  "domain": "database",
  "risk_tier": "critical",
  "action_type": "destructive_write",
  "target_environment": "production"
}
```

## Field guide

| Field | Meaning |
|-------|---------|
| `timestamp` | ISO-8601 timestamp for replay ordering |
| `session_id` | Stable id for one agent session |
| `agent_id` | Agent, model, workflow, or service name |
| `tool_name` | Tool or API the agent wanted to call |
| `proposed_action` | Plain-language description of the action |
| `tool_args` | Tool arguments as JSON |
| `domain` | `database`, `cloud_ops`, `cyber`, `finance`, `support`, etc. |
| `risk_tier` | `low`, `medium`, `high`, or `critical` |
| `action_type` | `read`, `write`, `destructive_write`, `external_send`, etc. |
| `target_environment` | `dev`, `test`, `staging`, or `production` |

## Optional fields

| Field | Meaning |
|-------|---------|
| `user_id` | Requesting user or service account |
| `ticket_id` | Change request, support case, or incident id |
| `evidence_refs` | Existing evidence ids or document references |
| `expected_decision` | Useful for labelled benchmarks |
| `notes` | Human-readable context |

