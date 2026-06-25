# REMORA Agent Tool Hook

The REMORA agent tool hook is an opt-in runtime guard for long-running coding
or operations agents. It extends REMORA from benchmark evaluation into a local
control loop around proposed tool calls.

The hook does not execute tools. It inspects the proposed call before execution
and can allow or block it.

## Control Flow

```text
Agent proposes tool call
  -> deterministic risk classifier
  -> local hard block for clearly destructive patterns
  -> optional intent-drift check against anchored session goal
  -> optional REMORA remote consensus verification
  -> Lyapunov trajectory update for session-level stability
  -> allow or block
```

## What The Files Do

| File | Purpose |
|---|---|
| `remora/agent_hook/risk_classifier.py` | Classifies proposed tool calls as LOW, MEDIUM or HIGH risk and marks locally blocked destructive patterns. |
| `remora/agent_hook/intent_anchor.py` | Stores a local session goal and computes transparent lexical drift from that goal. |
| `remora/agent_hook/lyapunov_tracker.py` | Converts tool-call observations into a Lyapunov-style stability trajectory over time. |
| `scripts/remora_anchor.py` | CLI for anchoring, showing or clearing the current session intent. |
| `scripts/remora_hook.py` | Hook entrypoint that reads JSON from stdin and exits `0` to allow or `2` to block. |
| `.claude/settings.json` | Optional local integration that wires the hook into Claude Code PreToolUse events. |

## Local State

The hook writes local session state under `.remora_session/`, which is ignored
by Git. This directory may contain:

- `intent.json`: anchored session goal and tool-call count.
- `lyapunov.json`: local tool-call stability trajectory.
- `hook_config.json`: optional local secret override for agent-control.

## Interpreting V(t)

`V(t)` is a session-local control signal, not a canonical benchmark score. Its
numeric value depends on the anchored intent, proposed tool payload, verifier
confidence, drift score, and prior observations in `.remora_session/`.

Use `V(t)` for trend inspection inside one session:

- decreasing or stable `V(t)`: the recent tool-call trajectory is not becoming
  less stable under the hook's current heuristic mapping.
- increasing `V(t)`: the session deserves review, especially when paired with
  high drift, low confidence, or a negative verifier verdict.

Do not cite a single `V(t)` value, such as a value from a demo run, as a fixed
REMORA result. Report a scenario-specific trajectory or aggregate statistics
over repeated runs instead.

## Usage

Anchor the session goal:

```bash
python scripts/remora_anchor.py "Improve documentation without changing benchmark claims"
```

Show current state:

```bash
python scripts/remora_anchor.py --show
```

Clear local hook state:

```bash
python scripts/remora_anchor.py --clear
```

Run the hook directly with a synthetic payload:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git status --short"}}' | python scripts/remora_hook.py
```

## Remote Verification

The hook works without live API calls. In offline mode:

- LOW-risk actions are allowed and recorded.
- Clearly destructive shell patterns are locally blocked.
- MEDIUM and non-destructive HIGH-risk actions are allowed unless
  `REMORA_HOOK_REQUIRE_REMOTE=1` is set.

When `AGENT_CONTROL_SECRET` is configured, the hook can call the optional
agent-control service for REMORA claim verification before high-risk actions.

Set strict high-risk behavior:

```bash
REMORA_HOOK_REQUIRE_REMOTE=1 python scripts/remora_hook.py
```

## Limitations

This is a runtime guardrail, not a proof of safety.

- Intent drift is lexical, not semantic entailment.
- The Lyapunov trajectory is a transparent control signal, not a formal proof
  that an agent is safe.
- Remote verification is optional and depends on the configured agent-control
  service.
- Production deployments should connect this hook to a reviewed policy store,
  audit ledger, RBAC and incident workflow.

## Why It Matters

REMORA's original contribution is selective trust: route outputs by consensus,
disagreement, evidence and risk. The agent hook moves that idea closer to
runtime agent governance. It asks not only "is this answer reliable?" but also
"is this proposed action aligned, stable and within the agent's authority right
now?"
