# Azure Reference Architecture

REMORA on Azure: mapping each component to the appropriate Azure service for enterprise deployment in regulated environments.

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
│                         │  │ • PolicyDecisionEngine│  │    │
│                         │  │ • ThermodynamicRouter │  │    │
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

Deploy the observability stack described in [`enterprise/observability.md`](../reference_architecture.md):

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
- **Audit trail:** The audit ledger schema (`enterprise/audit-ledger-schema.sql`) includes row-level security and append-only constraints compatible with Azure SQL.
- **Model governance:** Azure OpenAI provides content filtering and usage logging. REMORA adds decision-level audit trails and policy gates on top.
- **RBAC:** Entra ID roles map to REMORA governance layers: `remora-operator` (runtime), `remora-policy-admin` (policy changes), `remora-auditor` (read-only audit access).
