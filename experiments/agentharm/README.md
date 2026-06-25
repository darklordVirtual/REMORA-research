# REMORA x AgentHarm external validation

This directory runs AgentHarm through `inspect-ai` / `inspect-evals` against
REMORA governance arms and scores the result as a guardrail confusion matrix.
It is designed to be reviewer-safe: prerequisites fail loudly, secrets are not
printed, and no headline claim is emitted without the matching artifact.

## What this is and is not

- Is: an intent-gating harness. For each sample, REMORA records a
  `DecisionEnvelope` over the agent's proposed action surface and logs mode
  degradation. See `INTERCEPTION_NOTES.md`.
- Is not yet: a true PreToolUse tool-call interceptor. Do not describe it as
  blocking tool calls until `inspect_tools_probe.py` reports
  `tools_beyond_submit_exposed: true` and a real tool-wrapping hook is added.

## Arms

| Arm | Meaning |
|-----|---------|
| `baseline` | Agent alone, no REMORA. |
| `remora_full` | Full REMORA gate: multi-oracle consensus plus hard blocks. |
| `hardblocks_only` | Deterministic hard blocks only, no oracle calls. |
| `single_oracle` | Single-oracle gate, degraded visibly if engine init fails. |

Oracle-backed arms degrade to `hardblocks_only` if the engine cannot initialize.
The degradation is recorded in `results/agentharm/mode_metadata.jsonl` and is
never hidden.

## Environment

Values are never printed or written to artifacts; only presence booleans are
recorded.

- `CF_AIG_TOKEN`, `CF_AI_GATEWAY_KEY`, or `CLOUDFLARE_API_TOKEN`: Cloudflare token.
- `CLOUDFLARE_ACCOUNT_ID` or `CF_ACCOUNT_ID`: used to build the Unified Billing
  REST base URL when `OPENAI_BASE_URL` is not set.
- `OPENAI_BASE_URL`: optional OpenAI-compatible base URL. For Cloudflare Unified
  Billing (Workers AI) it should end at `/ai/v1`. The OpenAI SDK appends `/chat/completions`.
- `CF_GATEWAY_ID`: optional AI Gateway id. When set, the workflow passes it as
  `cf-aig-gateway-id`. To bypass AI Gateway entirely (and avoid gateway logging/forbruk), simply leave this unset.
- `CF_AIG_MODEL`: The model to use. For AI Gateway proxies, e.g. `openai/gpt-4o`. 
  To run native **Cloudflare Workers AI** models directly, set this to the model ID, 
  e.g., `@cf/meta/llama-3.3-70b-instruct-fp8-fast`. `cf_compat.to_inspect_model()` 
  automatically adds the `openai/` prefix required by the Inspect framework.
- `HF_TOKEN`: for the gated `ai-safety-institute/AgentHarm` dataset.

## Run order

```bash
# 1. Sanity / preflight; no eval yet.
python experiments/agentharm/preflight.py
python experiments/agentharm/check_hf_access.py
python experiments/agentharm/check_cloudflare_openai_compat.py
python experiments/agentharm/inspect_tools_probe.py

# 2. Baseline-only pilot with a small limit. This must pass before full matrix.
bash experiments/agentharm/run_pilot.sh

# 3. Full matrix, only after the baseline pilot is clean.
bash experiments/agentharm/run_full.sh

# 4. Score.
python experiments/agentharm/score_guardrail.py
```

`score_guardrail.py` exits non-zero and writes a `status:invalid` summary if no
baseline results exist. Passing `--allow-missing` is only for CI smoke; it still
forbids headline claims.

## Claims

Read `docs/claim_hygiene.md` before writing anything into README, paper, badges,
or public summaries.
