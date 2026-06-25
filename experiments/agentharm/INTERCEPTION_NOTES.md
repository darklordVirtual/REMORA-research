# AgentHarm x REMORA interception notes

Status: reviewer-safe diagnosis. Do not claim true PreToolUse tool-call gating
until the probe confirms it and a working interception path is merged.

## What we observed

Earlier runs surfaced only Inspect's synthetic `submit` tool in the request
trace. Two explanations are possible:

1. The custom `--solver` override replaced AgentHarm's default plan, which
   normally injects scenario tools from sample metadata. `solvers.py` now
   restores that tool surface via `_agentharm_tools_from_metadata`, so the
   tools should be present on `TaskState.tools`. Run `inspect_tools_probe.py`
   to confirm; it writes `results/agentharm/tool_probe.json` with
   `tools_beyond_submit_exposed`.
2. Even when tools are attached to `TaskState`, Inspect executes them inside
   its own generate/tool loop. A solver wrapper does not automatically receive
   a hook for every tool invocation.

## Honest assessment of the current wrapper

`remora_mediated_solver.py` records and gates the proposed action surface, but
it is not yet installed as a verified wrapper around every Inspect tool call.
Therefore, in the current setup REMORA should be described as intent-gating
unless the probe and a real tool wrapper prove otherwise.

What REMORA can legitimately do today:

- Intent gating: evaluate the proposed action string, tool name, and arguments
  before the agent's final `submit`, then record a `DecisionEnvelope`.
- Mode visibility: record whether a run used full REMORA, single-oracle mode, or
  degraded to hard-blocks.
- Claim hygiene: block headline claims when baseline, probe, or scoring artifacts
  are missing.

## What true PreToolUse interception requires

To gate real tool calls, one of the following must be implemented and verified:

1. Inspect tool wrapping: wrap each `Tool` attached to `TaskState.tools` in a
   decorator that calls the REMORA gate before delegating to the underlying tool,
   returning a refusal `ToolResult` on `ABSTAIN` or `ESCALATE`.
2. Native AgentHarm solver/tool environment: use AgentHarm's own agent plumbing
   and insert the gate where tools are dispatched.

Until one of these paths is merged and the probe shows scenario tools are
exposed, result artifacts and reports must describe REMORA's AgentHarm role as
intent-gating, not tool-call interception.

## Claim impact

Allowed now:

- "REMORA records a `DecisionEnvelope` for the agent's proposed action and can
  block at intent level on this benchmark configuration."

Forbidden now:

- "REMORA intercepts every tool call in AgentHarm."
- "REMORA achieves 0% unsafe execution in AgentHarm."
- Any external-guardrail comparison without full baseline, benign split,
  harmful split, probe, and scoring artifacts.

See `docs/claim_hygiene.md`.
