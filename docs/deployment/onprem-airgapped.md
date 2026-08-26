# On-Premises and Air-Gapped Deployment


> **Note on `enterprise/*` references:** paths under `enterprise/` name design
> artifacts maintained in the enterprise edition / main implementation repo; they
> are not bundled in this research repo. Descriptive references are retained; the
> files themselves live outside this repository.

REMORA can run without depending on external SaaS, provided local or approved model endpoints are available. This document covers deployment in restricted environments where internet access is limited or prohibited.

---

## Design Principle

REMORA is platform-agnostic. Cloudflare Workers and cloud-hosted oracles are one deployment profile, not a dependency. Every external integration has a local equivalent:

| External Service         | On-Premises Equivalent                                   |
|--------------------------|----------------------------------------------------------|
| Groq / OpenRouter APIs   | Ollama, vLLM, llama.cpp, or internal Azure OpenAI        |
| Cloudflare Workers       | Docker containers or Kubernetes pods                     |
| Cloudflare D1 / KV       | PostgreSQL + Redis                                       |
| Cloudflare Vectorize     | pgvector or local FAISS index                            |
| Cloud storage (S3/R2)    | MinIO (S3-compatible) or local filesystem                |
| External identity (OAuth)| Keycloak, Entra ID on-premises, or OIDC-compatible IdP  |

---

## Component Architecture

```text
┌───────────────────────────────────────────────────┐
│  Secure Zone / Air-Gapped Network                 │
│                                                   │
│  ┌─────────────┐    ┌──────────────────────────┐ │
│  │ REMORA      │    │ Local Model Servers      │ │
│  │ Application │───▶│ Ollama / vLLM / llama.cpp│ │
│  │ (Docker/K8s)│    │ (GPU nodes)              │ │
│  └──────┬──────┘    └──────────────────────────┘ │
│         │                                         │
│  ┌──────▼──────┐    ┌──────────────────────────┐ │
│  │ PostgreSQL  │    │ MinIO (S3-compatible)    │ │
│  │ + pgvector  │    │ Evidence & artifacts     │ │
│  │ (audit +    │    └──────────────────────────┘ │
│  │  vectors)   │                                  │
│  └──────┬──────┘    ┌──────────────────────────┐ │
│         │           │ Redis / NATS             │ │
│         │           │ (async dispatch)         │ │
│  ┌──────▼──────┐    └──────────────────────────┘ │
│  │ Keycloak    │                                  │
│  │ (identity)  │    ┌──────────────────────────┐ │
│  └─────────────┘    │ Prometheus + Grafana     │ │
│                     │ (observability)          │ │
│                     └──────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

---

## Component Requirements

| Component       | Purpose                    | Minimum Spec                              |
|-----------------|----------------------------|-------------------------------------------|
| Docker / K8s    | Runtime                    | Docker 24+ or K8s 1.28+                   |
| PostgreSQL      | Audit ledger + vectors     | PostgreSQL 15+ with pgvector extension     |
| Model server    | Local LLM inference        | Ollama 0.3+ or vLLM 0.4+ with GPU         |
| Redis / NATS    | Async queue (optional)     | Redis 7+ or NATS 2.10+                    |
| MinIO           | S3-compatible storage      | MinIO latest or any S3-compatible service  |
| Keycloak        | Identity / OIDC            | Keycloak 24+ (optional, JWT also works)   |
| Prometheus      | Metrics collection         | Prometheus 2.50+ (optional)                |
| Grafana         | Dashboards                 | Grafana 10+ (optional)                     |

---

## Quick Start (Docker)

```bash
# 1. Start infrastructure
# container build: docker build -f artifacts/docker/Dockerfile -t remora:local .

# 2. Pull local models
docker exec remora-ollama-1 ollama pull llama3.1:8b
docker exec remora-ollama-1 ollama pull mistral:7b

# 3. Configure REMORA to use local models
export OLLAMA_HOST=http://localhost:11434
export REMORA_ORACLE_BACKEND=ollama

# 4. Run tests (no external network required)
python -m pytest tests/ -q

# 5. Run benchmarks (deterministic replay, no model calls)
make benchmark
```

---

## Model Selection for Air-Gapped Environments

REMORA requires at least three oracle models from different families for meaningful consensus. Recommended local configurations:

| Role                 | Model                              | Size   | Hardware         |
|----------------------|------------------------------------|--------|------------------|
| Fast oracle (Stage 1)| Llama 3.1 8B (Ollama)             | 4.7 GB | 8 GB VRAM        |
| Consensus oracle 1   | Llama 3.1 8B (Ollama)             | 4.7 GB | 8 GB VRAM        |
| Consensus oracle 2   | Mistral 7B (Ollama)               | 4.1 GB | 8 GB VRAM        |
| Consensus oracle 3   | Gemma 2 9B (Ollama)               | 5.4 GB | 8 GB VRAM        |
| Judge (Stage 3)      | Mistral 7B Instruct (Ollama)      | 4.1 GB | 8 GB VRAM        |

Total VRAM for all models loaded simultaneously: ~24 GB (fits on a single A10G or RTX 4090).

For sequential loading (lower VRAM), Ollama automatically manages model loading/unloading.

---

## Security Controls

| Control                  | Implementation                                            |
|--------------------------|-----------------------------------------------------------|
| Network isolation        | No outbound internet from REMORA runtime                  |
| Data residency           | All data stays within the on-premises network             |
| Encryption at rest       | PostgreSQL TDE, MinIO server-side encryption               |
| Encryption in transit    | TLS 1.2+ between all components                           |
| Access control           | Keycloak RBAC or JWT-based identity                       |
| Audit trail              | Append-only PostgreSQL tables (see `enterprise/audit-ledger-schema.sql`) |
| Model provenance         | Document model checksums and sources in deployment manifest|
| No telemetry             | REMORA does not phone home, no external telemetry        |

---

## Hybrid Mode

For environments that allow restricted outbound access (e.g., via a proxy or approved endpoints only):

```text
REMORA → Approved proxy → Azure OpenAI private endpoint
                        → Internal model registry
```

Configure the LLM adapter to route through the approved endpoint:

```python
from remora.adapters.llm.azure_openai import AzureOpenAIAdapter

adapter = AzureOpenAIAdapter(
    endpoint="https://your-internal-aoai.openai.azure.com",
    api_key="from-key-vault",
    deployment="gpt-4o",
)
```

---

## Execution layer (governed dispatch)

Everything above covers the assess/decision path. To also run the
enforcement-grade execution path (`/v1/execution/*`: signed one-time grants,
approval freshness re-gate, lease-bound dispatch through
`GovernedToolDispatcher`), the air-gapped host additionally needs:

- **Durable execution state**, on-box: `REMORA_CHAIN_DB=<path>.db` (SQLite,
  single node) or `REMORA_PG_DSN` against the local PostgreSQL. Without one,
  a consumed execution grant becomes replayable after a process restart, and
  production mode refuses to start.
- Durable envelope store: `REMORA_CONTROL_PLANE_DB=<path>.db` or
  `REMORA_CONTROL_PLANE_DSN`.
- **A deployment-owned tool registry** (`REMORA_TOOL_REGISTRY_MODULE`);
  request payloads can never add or replace callables. Template:
  `servers/tool_registry_research.py`.
- **Signing keys** (`REMORA_PDP_SIGNING_KEY`, `REMORA_LEASE_SIGNING_KEY`,
  `REMORA_AUDIT_SIGNING_KEY`, `REMORA_ENVELOPE_SIGNING_KEY`) generated and
  stored on-box; no external KMS dependency exists (that is also the current
  gap; see `docs/assurance/rbac_policy_v1.md`).

The whole execution round works offline: decisions, grants, dispatch and
chain verification make no external calls. Walkthrough:
[`execution-quickstart.md`](execution-quickstart.md). Offline chain audit:
`python scripts/verify_envelope_chain.py --store-db <path>`.

## Validation

After deployment, run the REMORA credibility pack to verify the installation:

```bash
make test              # Full deterministic test suite, no external dependencies
make benchmark         # Deterministic replay benchmarks
make credibility-pack  # Full credibility pack for audit
```

All tests and benchmarks run in deterministic replay mode: no external API calls are made.
