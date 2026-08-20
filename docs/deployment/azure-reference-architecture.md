# Azure Reference Architecture

REMORA on Azure: mapping each component to the appropriate Azure service for enterprise deployment in regulated environments.

> **Illustrative reference design.** REMORA is a research-grade governance
> overlay running in `SHADOW_ONLY` mode; it is **not** currently deployed on
> Azure and is not production-certified. The services, commands, and cost
> figures below are a reference mapping for a hypothetical deployment, not a
> record of a live system.

---

## Component Mapping

| REMORA Component        | Azure Service                         | Notes                                                          |
|-------------------------|---------------------------------------|----------------------------------------------------------------|
| API Gateway             | Azure API Management                  | Rate limiting, auth, request routing                           |
| Worker / orchestration  | Azure Container Apps or AKS           | Container Apps for serverless; AKS for full Kubernetes control |
| Queue / async dispatch  | Azure Service Bus                     | Dead-letter queues for failed evaluations                      |
| Object storage          | Azure Blob Storage                    | Results artifacts, benchmark data, evidence corpus             |
| Secrets                 | Azure Key Vault                       | API keys, model endpoints, database credentials                |
| Identity                | Microsoft Entra ID                    | Service principals, managed identities, RBAC                   |
| Logs / metrics          | Azure Monitor + Application Insights  | SLOs, latency histograms, safety metric dashboards             |
| Policy engine           | Azure Policy + REMORA policy engine   | Azure Policy for infrastructure; REMORA for AI decision policy |
| LLM access              | Azure OpenAI Service                  | Private endpoints, content filtering, managed deployment       |
| Audit ledger            | Azure SQL or Azure Database for PostgreSQL | Append-only audit trail with row-level security            |
| Vector search           | Azure AI Search or pgvector extension | Evidence retrieval, RAG oracle grounding                       |

---

## Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│  Azure Subscription                                         │
│                                                             │
│  ┌──────────────┐       ┌─────────────────────────────┐    │
│  │ API Mgmt     │──────▶│  Container Apps / AKS       │    │
│  │ (gateway)    │       │  ┌───────────────────────┐  │    │
│  └──────────────┘       │  │ REMORA Assurance Pod  │  │    │
│                         │  │ • CascadeEngine       │  │    │
│                         │  │ • RemoraDecisionEngine│  │    │
│                         │  │ • ThermodynamicBraking│  │    │
│                         │  └───────────┬───────────┘  │    │
│                         └──────────────┼──────────────┘    │
│                                        │                    │
│         ┌──────────────────────────────┼───────────┐       │
│         │                              │           │       │
│  ┌──────▼──────┐  ┌───────────────┐  ┌▼────────┐  │       │
│  │ Azure OpenAI│  │ Key Vault     │  │ Service  │  │       │
│  │ (models)    │  │ (secrets)     │  │ Bus      │  │       │
│  └─────────────┘  └───────────────┘  └──────────┘  │       │
│         │                                          │       │
│  ┌──────▼──────┐  ┌───────────────┐  ┌──────────┐ │       │
│  │ AI Search   │  │ Azure SQL     │  │ Monitor  │ │       │
│  │ (RAG)       │  │ (audit)       │  │ (SLOs)   │ │       │
│  └─────────────┘  └───────────────┘  └──────────┘ │       │
│         │                                          │       │
│  ┌──────▼──────┐  ┌───────────────┐               │       │
│  │ Blob Storage│  │ Entra ID      │               │       │
│  │ (artifacts) │  │ (identity)    │               │       │
│  └─────────────┘  └───────────────┘               │       │
│                                                    │       │
└────────────────────────────────────────────────────┘       │
                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Deployment Steps

### 1. Infrastructure provisioning

```bash
# Resource group
az group create --name rg-remora --location norwayeast

# Container Apps environment
az containerapp env create \
  --name remora-env \
  --resource-group rg-remora \
  --location norwayeast

# Key Vault
az keyvault create \
  --name kv-remora \
  --resource-group rg-remora \
  --location norwayeast

# Azure OpenAI (requires approval)
az cognitiveservices account create \
  --name aoai-remora \
  --resource-group rg-remora \
  --kind OpenAI \
  --sku S0 \
  --location norwayeast

# PostgreSQL (audit ledger)
az postgres flexible-server create \
  --name pg-remora \
  --resource-group rg-remora \
  --location norwayeast \
  --sku-name Standard_B1ms \
  --tier Burstable
```

### 2. Secrets management

Store API keys and credentials in Key Vault, then reference them as environment variables via managed identity:

```bash
az keyvault secret set --vault-name kv-remora --name GROQ-API-KEY --value "..."
az keyvault secret set --vault-name kv-remora --name OPENROUTER-API-KEY --value "..."
```

### 3. Container deployment

```bash
az containerapp create \
  --name remora-assurance \
  --resource-group rg-remora \
  --environment remora-env \
  --image <registry>/remora:latest \
  --target-port 8080 \
  --ingress external \
  --secrets "groq-key=keyvaultref:kv-remora/GROQ-API-KEY,identityref:<managed-identity-id>" \
  --env-vars "GROQ_API_KEY=secretref:groq-key"
```

### 3b. Execution layer (governed dispatch)

The container above serves the assess path as-is. To enable the
enforcement-grade `/v1/execution/*` path (signed one-time grants, approval
freshness re-gate, lease-bound dispatch), extend the container app's
environment:

```bash
az containerapp update --name remora-assurance --resource-group rg-remora \
  --set-env-vars \
    "REMORA_ENV=production" \
    "REMORA_API_TOKENS=secretref:remora-tokens" \
    "REMORA_CONTROL_PLANE_DSN=secretref:pg-dsn" \
    "REMORA_PG_DSN=secretref:pg-dsn" \
    "REMORA_API_BEARER_TOKEN=secretref:bearer-token" \
    "REMORA_PDP_SIGNING_KEY=secretref:pdp-key" \
    "REMORA_ENVELOPE_SIGNING_KEY=secretref:envelope-key" \
    "REMORA_TOOL_REGISTRY_MODULE=my_app.remora_registry"
```

The Flexible Server provisioned in step 1 carries both stores: the durable
DecisionEnvelope store (`REMORA_CONTROL_PLANE_DSN`) and the execution state —
tenant audit chain, review queue, one-time-grant ledger (`REMORA_PG_DSN`).
Production mode refuses to start without them; without durable state a
consumed grant becomes replayable across container restarts. Keep signing
keys in Key Vault like the API keys above. The tool registry module is
deployment-owned code baked into the image — request payloads can never add
or replace callables. Full walkthrough and verification round:
[`execution-quickstart.md`](execution-quickstart.md).

Run **one replica** for the execution path until REM-025 (durable lease-nonce
ledger) closes: the jti grant ledger is durable in PostgreSQL, but lease
nonces are per-process.

### 4. Azure OpenAI configuration

Deploy models via Azure OpenAI:

```bash
az cognitiveservices account deployment create \
  --name aoai-remora \
  --resource-group rg-remora \
  --deployment-name gpt-4o \
  --model-name gpt-4o \
  --model-version "2024-08-06" \
  --model-format OpenAI \
  --sku-capacity 10 \
  --sku-name Standard
```

REMORA connects via the `AzureOpenAIAdapter` (see `remora/adapters/llm/azure_openai.py`), which wraps Azure's endpoint format and authentication.

---

## Network Security

For regulated environments (energy, finance, healthcare):

| Control                   | Implementation                                        |
|---------------------------|-------------------------------------------------------|
| Private endpoints         | Azure OpenAI, PostgreSQL, AI Search on private VNet   |
| Network isolation         | Container Apps in VNet-injected environment            |
| Egress control            | NSG + Azure Firewall for outbound model API calls     |
| Data residency            | Norway East region, all data stays within Azure Norway |
| Encryption at rest        | Azure-managed keys or customer-managed keys (CMK)     |
| Encryption in transit     | TLS 1.2+ enforced on all endpoints                    |
| Identity-based access     | Managed identities, no stored credentials in code     |

---

## Monitoring and SLOs

Deploy the observability stack described in [`reference_architecture.md`](../reference_architecture.md):

| Metric                        | Azure Service              | Alert Threshold    |
|-------------------------------|----------------------------|--------------------|
| Assurance latency P95         | Application Insights       | < 2s               |
| Abstention rate (rolling 1h)  | Azure Monitor custom metric| > 40% triggers alert|
| Audit trail write success     | Azure SQL metrics          | 100% (zero loss)   |
| Oracle error rate             | Application Insights       | < 5%               |
| Policy gate rejection rate    | Custom metric              | Dashboard only      |

---

## Cost Considerations

| Component              | Estimated monthly cost (dev)  | Production           |
|------------------------|-------------------------------|----------------------|
| Container Apps (2 vCPU)| ~$50                          | ~$200 (4 replicas)   |
| Azure OpenAI (GPT-4o)  | Usage-based                   | Usage-based          |
| PostgreSQL (B1ms)      | ~$30                          | ~$150 (GP, 4 vCPU)   |
| AI Search (Basic)      | ~$70                          | ~$250 (Standard)     |
| Key Vault              | ~$1                           | ~$5                  |
| Monitor / Insights     | ~$10                          | ~$50                 |

Total dev environment: ~$160/month (excluding LLM usage).

---

## Compliance Notes

- **Data residency:** All REMORA components can be deployed within a single Azure region (e.g., Norway East) to satisfy data sovereignty requirements.
- **Audit trail:** The reference audit-ledger schema (row-level security and append-only constraints) is provisioned as part of deployment and is compatible with Azure SQL. REMORA's committed audit mechanism is the hash-chained tenant audit (`remora/audit/`).
- **Model governance:** Azure OpenAI provides content filtering and usage logging. REMORA adds decision-level audit trails and policy gates on top.
- **RBAC:** Entra ID roles map to REMORA governance layers: `remora-operator` (runtime), `remora-policy-admin` (policy changes), `remora-auditor` (read-only audit access).
