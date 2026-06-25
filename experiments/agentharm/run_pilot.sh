#!/usr/bin/env bash
# AgentHarm pilot: baseline arm only, tiny limit. No REMORA arms run here.
# Baseline must complete with >0 samples before any REMORA arm or scoring.
set -euo pipefail

cd "$(dirname "$0")/../.."   # repo root
LIMIT="${LIMIT:-3}"

eval "$(
python - <<'PY'
import os
import shlex

from experiments.agentharm.cf_compat import (
    resolve_api_key,
    resolve_base_url,
    resolve_model,
    to_inspect_model,
)

api_key = resolve_api_key()
if not api_key:
    raise SystemExit("No Cloudflare/OpenAI-compatible token found.")
base_url = resolve_base_url()
model = to_inspect_model(resolve_model())

print(f"export OPENAI_API_KEY={shlex.quote(api_key)}")
print(f"export OPENAI_BASE_URL={shlex.quote(base_url)}")
print(f"export INSPECT_MODEL={shlex.quote(model)}")
PY
)"

MODEL_CONFIG_ARGS=()
if [[ "${OPENAI_BASE_URL}" == https://api.cloudflare.com/* && -n "${CF_GATEWAY_ID:-}" ]]; then
  CFG="/tmp/remora_cf_model_config.yaml"
  cat > "$CFG" <<YAML
default_headers:
  cf-aig-gateway-id: "${CF_GATEWAY_ID}"
YAML
  MODEL_CONFIG_ARGS+=(--model-config "$CFG")
fi

if [[ -n "${CF_AIG_LORA:-}" ]]; then
  MODEL_CONFIG_ARGS+=(--model-args "lora=${CF_AIG_LORA}")
fi

echo "== Preflight =="
python experiments/agentharm/preflight.py
python experiments/agentharm/check_hf_access.py
python experiments/agentharm/check_cloudflare_openai_compat.py
python experiments/agentharm/inspect_tools_probe.py --limit "$LIMIT" || true

echo "== Baseline pilot (harmful, limit=$LIMIT) =="
inspect eval inspect_evals/agentharm \
  --model "$INSPECT_MODEL" \
  "${MODEL_CONFIG_ARGS[@]}" \
  --solver experiments/agentharm/solvers.py@baseline \
  --limit "$LIMIT" --temperature 0.0 --seed 42 \
  --no-parallel-tool-calls \
  --log-dir results/agentharm/baseline/agentharm

echo "== Baseline pilot (benign, limit=$LIMIT) =="
inspect eval inspect_evals/agentharm_benign \
  --model "$INSPECT_MODEL" \
  "${MODEL_CONFIG_ARGS[@]}" \
  --solver experiments/agentharm/solvers.py@baseline \
  --limit "$LIMIT" --temperature 0.0 --seed 42 \
  --no-parallel-tool-calls \
  --log-dir results/agentharm/baseline/agentharm_benign

echo "== Score (fails non-zero if baseline empty) =="
python experiments/agentharm/score_guardrail.py
echo "Pilot complete. Inspect results before enabling REMORA arms (run_full.sh)."
