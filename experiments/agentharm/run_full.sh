#!/usr/bin/env bash
# AgentHarm full matrix. Only run after run_pilot.sh baseline completes cleanly.
# Arms: baseline, remora_full, hardblocks_only, single_oracle x harmful/benign.
set -euo pipefail

cd "$(dirname "$0")/../.."   # repo root
LIMIT="${LIMIT:-0}"   # 0 = full split
ARMS="${ARMS:-baseline,remora_full,hardblocks_only,single_oracle}"

eval "$(
python - <<'PY'
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

if [ ! -d results/agentharm/baseline/agentharm ] || \
   [ -z "$(ls -A results/agentharm/baseline/agentharm 2>/dev/null)" ]; then
  echo "ERROR: baseline results missing. Run run_pilot.sh first." >&2
  exit 2
fi

IFS=',' read -ra ARM_LIST <<< "$ARMS"
for arm in "${ARM_LIST[@]}"; do
  for split in agentharm agentharm_benign; do
    echo "== Arm=$arm Split=$split Limit=$LIMIT =="
    LIMIT_ARGS=()
    if [[ "$LIMIT" != "0" ]]; then
      LIMIT_ARGS=(--limit "$LIMIT")
    fi
    inspect eval "inspect_evals/$split" \
      --model "$INSPECT_MODEL" \
      "${MODEL_CONFIG_ARGS[@]}" \
      --solver "experiments/agentharm/solvers.py@$arm" \
      "${LIMIT_ARGS[@]}" --temperature 0.0 --seed 42 \
      --no-parallel-tool-calls \
      --log-dir "results/agentharm/$arm/$split"
  done
done

echo "== Score =="
python experiments/agentharm/score_guardrail.py
