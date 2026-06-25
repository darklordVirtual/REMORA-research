# REMORA Agent Safety Eval Pack

Bring your own agent logs. Run REMORA in Shadow Mode. Get a governance report
without changing your production agent.

This pack is for teams that are curious about REMORA but are not ready to
insert a runtime gate yet.

## What it answers

| Question | Output |
|----------|--------|
| What did the agent try to do? | Action log summary |
| Which actions would REMORA accept? | ACCEPT count and examples |
| Which actions need evidence? | VERIFY count and required evidence |
| Which actions should not run autonomously? | ABSTAIN and ESCALATE examples |
| What can be audited later? | DecisionEnvelope and hash references |

## Minimal workflow

```bash
# 1. Convert agent tool calls to the JSONL schema.
# See eval_pack/agent_action_log_schema.md

# 2. Run shadow replay.
make shadow-replay INPUT=eval_pack/sample_logs/simple_agent_actions.jsonl

# 3. Inspect the generated report.
cat artifacts/shadow_mode/governance_delta_report.json
```

## What this is not

- Not a production certification.
- Not a substitute for human review in critical systems.
- Not evidence that every unsafe action will be caught.
- Not a requirement to use REMORA enforcement mode.

## Recommended next step

Start with 100 to 500 real or realistic agent tool calls. Keep the run in
Shadow Mode. Review the actions REMORA would have escalated, then decide
whether enforcement is appropriate for specific domains.

