# Cloudflare Workers AI & Fine-Tunes (LoRA) in REMORA

REMORA deeply integrates with Cloudflare Workers AI to allow high-performance, low-cost routing using both native base models and specialised Fine-tunes (LoRAs). 

This guide covers how to utilize the `CloudflareOracle` natively to bypass `AI Gateway` bottlenecks safely, lowering latencies and avoiding strict quota limitations specifically on structural components of the cascade (like FastGate and VerifierGate).

## The `CloudflareOracle`

We provide a dedicated oracle for Cloudflare Workers AI.

```python
from remora.oracles.cloudflare import CloudflareOracle

# Base native model
base_oracle = CloudflareOracle(model="@cf/meta/llama-3.3-70b-instruct-fp8-fast")

# LoRA injection (Zero-shot specialization)
security_lora = CloudflareOracle(
    model="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    lora="00000000-0000-0000-0000-000000000000" # Your fine-tune ID
)
```

## Architectural Guidelines

To preserve REMORA's uncertainty-routing properties, you must configure LoRAs meticulously. Improper use of fine-tunes in the Consensus stage can artificially inflate consensus by destroying oracle diversity.

### 1. FastGate (Stage 1) - **Highly Recommended**
The `FastGate` relies on confident self-reflection to quickly `ACCEPT` simple, harmless queries. 
By utilizing a Cloudflare LoRA specialized in policy gating:
- **Cost**: Hugely reduced. You bypass AI Gateway and big model API costs.
- **Latency**: low single-call latency matters for `PreToolUse` agent intercepts (no committed latency benchmark exists: measure in your own deployment before relying on a number).
- **Accuracy**: A custom LoRA learns your exact `ACCEPT` criteria.

```python
from remora.cascade import CascadeEngine
from remora.oracles.cloudflare import CloudflareOracle

# Inject a highly specific LoRA for Stage 1 (FastGate)
fast_oracle = CloudflareOracle(
    model="@cf/meta/llama-3.1-8b-instruct-fp8", 
    lora="<FASTGATE_LORA_ID>"
)

engine = CascadeEngine(
    consensus_oracles=[...], # Keep diverse baselines here
    fast_oracle=fast_oracle,
    # ...
)
```

### 2. ConsensusGate (Stage 2) - **Warning: Avoid LoRAs!**
REMORA's Free Energy formula ($F(T) = \lambda D - TH$) intrinsically expects structural diversity (e.g. `Meta`, `Anthropic`, `Google`). 
Do NOT replace your consensus panel with identical LoRA adaptations. This raises inter-oracle correlation ($\bar{\rho}$), eliminating the "wisdom of the crowd" and heavily skewing the system into false `Ordered` phases.

### 3. VerifierGate (Stage 3) - **Recommended**
The `VerifierGate` acts as the LLM-as-a-judge for factual NLI support. A custom LoRA tuned precisely on NLI structures (`SUPPORTED`, `CHALLENGED`, `REFUTED`) avoids complex parsing errors and increases verdict reliability.

```python
verifier_oracle = CloudflareOracle(
    model="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    lora="<VERIFIER_LORA_ID>"
)
```

### 4. GO-STAR Cybersecurity Bridge - **Recommended**
The `GoStarBridge` handles localized cybersecurity findings. Passing a LoRA explicitly fine-tuned on CWE analysis directly into GO-STAR enables specialized evaluation of taint traces and AST patterns.
```python
security_specialist = CloudflareOracle(
    model="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    lora="<GO-STAR_CWE_LORA_ID>"
)
```

## Setup Environment

Ensure your `.env.vars` configures the correct auth details for native access:

```shell
CLOUDFLARE_API_TOKEN="cfat_..."
CLOUDFLARE_ACCOUNT_ID="ca13904..."

# To configure the Inspect/AgentHarm test harness globally
CF_AIG_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
CF_AIG_LORA="<OPTIONAL LORA ID>"
```
