# What is the AgentHarm external validation protocol?

This document covers the run order, caveats, and claim rules for the AgentHarm
external validation harness. Read this before running any AgentHarm experiment.

→ [05-claim-hygiene.md](05-claim-hygiene.md) for the decision rule on what may
be claimed from results.
→ [02-evidence-and-claims.md](02-evidence-and-claims.md) for the current
evidence status of AgentHarm claims.

---

## What this harness is and is not

**Is:** an intent-gating harness. For each AgentHarm sample, REMORA records a
`DecisionEnvelope` over the agent's proposed action surface and logs mode
degradation.

**Is not yet:** a true PreToolUse tool-call interceptor. Do not describe it as
blocking tool calls until `inspect_tools_probe.py` reports
`tools_beyond_submit_exposed: true` and a real tool-wrapping hook is in place.

This distinction matters for claims. See `experiments/agentharm/INTERCEPTION_NOTES.md`.

---

## Arms

| Arm | Meaning |
|-----|---------|
| `baseline` | Agent alone, no REMORA governance. |
| `remora_full` | Full REMORA gate: multi-oracle consensus plus hard blocks. |
| `hardblocks_only` | Deterministic hard blocks only; no oracle calls. |
| `single_oracle` | Single-oracle gate; degrades visibly if engine init fails. |

Oracle-backed arms degrade to `hardblocks_only` if the engine cannot initialise.
Degradation is recorded in `results/agentharm/mode_metadata.jsonl` and is never
hidden from scoring.

---

## Run order

```bash
# 1. Preflight and environment checks — no evaluation yet.
python experiments/agentharm/preflight.py
python experiments/agentharm/check_hf_access.py
python experiments/agentharm/check_cloudflare_openai_compat.py
python experiments/agentharm/inspect_tools_probe.py
```

`inspect_tools_probe.py` writes `results/agentharm/tool_probe.json` with the
field `tools_beyond_submit_exposed`. If this is `false`, the current run is
intent-gating only — no tool-interception claims may be made.

```bash
# 2. Baseline-only pilot (small --limit). Must pass before full matrix.
bash experiments/agentharm/run_pilot.sh
```

The pilot must complete successfully on both the harmful and benign splits before
proceeding. A `--limit` pilot does not licence any headline external-guardrail
claim.

```bash
# 3. Full matrix — only after the baseline pilot is clean.
bash experiments/agentharm/run_full.sh

# 4. Score.
python experiments/agentharm/score_guardrail.py
```

`score_guardrail.py` exits non-zero and writes a `status:invalid` summary if no
baseline results exist. Passing `--allow-missing` is only for CI smoke; it still
forbids headline claims.

---

## Environment variables

Values are never printed or written to artifacts; only presence booleans are
recorded.

| Variable | Purpose |
|---|---|
| `CF_AIG_TOKEN`, `CF_AI_GATEWAY_KEY`, or `CLOUDFLARE_API_TOKEN` | Cloudflare token |
| `CLOUDFLARE_ACCOUNT_ID` or `CF_ACCOUNT_ID` | Cloudflare account for Workers AI |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible base URL; for Cloudflare Unified Billing end at `/ai/v1` |
| `CF_GATEWAY_ID` | Optional AI Gateway id; omit to bypass AI Gateway logging |
| `CF_AIG_MODEL` | Model to use (e.g. `@cf/meta/llama-3.3-70b-instruct-fp8-fast`) |
| `HF_TOKEN` | Gated access to `ai-safety-institute/AgentHarm` dataset |

---

## Interception status (honest diagnosis)

`remora_mediated_solver.py` records and gates the proposed action surface, but
it is not yet installed as a verified wrapper around every Inspect tool call.

**What REMORA can legitimately do today:**
- Intent gating: evaluate the proposed action string, tool name, and arguments
  before the agent's final `submit`, then record a `DecisionEnvelope`.
- Mode visibility: record whether a run used full REMORA, single-oracle mode, or
  degraded to hard-blocks.
- Claim hygiene: block headline claims when baseline, probe, or scoring artifacts
  are missing.

**What true PreToolUse interception requires** (not yet implemented):

1. Inspect tool wrapping: wrap each `Tool` attached to `TaskState.tools` in a
   decorator that calls the REMORA gate before delegating to the underlying tool,
   returning a refusal `ToolResult` on `ABSTAIN` or `ESCALATE`.
2. Native AgentHarm solver/tool environment: use AgentHarm's own agent plumbing
   and insert the gate where tools are dispatched.

Until one of these paths is merged and the probe shows scenario tools are
exposed, result artifacts and reports must describe REMORA's AgentHarm role as
intent-gating, not tool-call interception.

---

## Claim rules (summary)

**Permitted now:**
- "On a pilot of N harmful / M benign AgentHarm samples, REMORA's intent-gating
  recorded `DecisionEnvelope` artifacts for the proposed action surface. This is
  not a tool-call interception result."
- "REMORA's deterministic hard blocks fired on K proposed actions. Oracle-backed
  modes were unavailable or degraded, so no oracle-consensus claim is made."

**Forbidden now:**
- "REMORA intercepts every tool call in AgentHarm."
- "REMORA achieves 0% unsafe execution in AgentHarm."
- Any external-guardrail comparison without full baseline, benign split,
  harmful split, probe, and scoring artifacts.
- Any statement citing recall > 0.852 / precision > 0.974 / FPR < 0.023 as
  REMORA results — those are external reference numbers.

The full decision rule is in → [05-claim-hygiene.md](05-claim-hygiene.md).

---

## Required artifacts for a headline claim

| Artifact | Required state |
|---|---|
| `results/agentharm/guardrail_scores.json` | `"status": "ok"` |
| `results/agentharm/tool_probe.json` | `tools_beyond_submit_exposed: true` |
| `results/agentharm/mode_metadata.jsonl` | `degraded: false` for the claimed arm |
| Baseline arm | Full harmful + full benign split (no `--limit`) |
| REMORA arm | Same splits as baseline |

If any condition fails, the result is roadmap / not-yet-validated, not a claim.
