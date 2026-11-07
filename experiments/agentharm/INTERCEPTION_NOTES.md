# AgentHarm x REMORA interception notes

## Update 2026-11-06: the interceptor exists; no run has used it

Path 1 below is implemented: `gate_tool` in `remora_mediated_solver.py`
replaces every tool on `TaskState.tools` with a wrapper that calls the gate
with the model's arguments and runs the original tool only on ACCEPT. The
probe reports `tools_beyond_submit_exposed: true`
(`results/agentharm/tool_probe.json`). `tests/test_agentharm_tool_interception.py`
verifies with Inspect's mock model that refused calls do not execute. CI does
not install the agentharm extra, so that test skips there; run it where
`inspect-ai` is installed.

Allowed now, in addition to the list at the end: "the AgentHarm harness gates
each tool call before it executes (verified offline)". Still forbidden: any
blocking or execution rate on AgentHarm, until the full splits have run
through the interceptor and been scored. The sections below are kept as the
diagnosis that led here.

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

See `docs/05-claim-hygiene.md`.
