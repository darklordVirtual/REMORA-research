# REMORA Domain Pack Governance v1

**Date:** 2026-06-30
**Status:** DRAFT, not yet reviewed
**Author:** Agent E (RAG / Evidence Provenance Audit)
**Replaces:** none (first version)

---

## 1. What Is a Domain Pack?

A domain pack is the complete set of artifacts that REMORA uses to govern agent
actions in a specific operational domain. It has four components:

| Component | Where it lives | Purpose |
|-----------|---------------|---------|
| **Policy rules** | `docs/policy_cookbook/<domain>.md` | Decision rules mapping (action, environment, risk) → (outcome, required evidence) |
| **RAG knowledge chunks** | Cloudflare Vectorize (`remora-knowledge` or `remora-knowledge-multi`) | Primary-source documents ingested into the vector knowledge base for evidence retrieval |
| **Evidence pack** | `results/` or referenced external source | Benchmark or validation artifacts that support domain-specific claims |
| **Claim register entry** | `docs/claim_register.md` or `docs/assurance/claim_register_v1.yaml` | Formally registered claims with artifact pointers and confidence grades |

A domain pack is considered _complete_ only when all four components exist and
are mutually consistent. A policy cookbook page without supporting RAG chunks
is an incomplete domain pack; a policy page without supporting evidence is also
incomplete.

---

## 2. Existing Domain Packs

Three domain packs are currently active. All three have policy cookbook pages
but vary in RAG chunk coverage and evidence backing.

### 2.1 Database operations (`database`)

- **Policy rules:** `docs/policy_cookbook/database.md`, covers SELECT, UPDATE,
  DELETE, DROP, schema migration, and export scenarios across dev, staging, and
  production environments.
- **RAG chunk coverage:** The seed corpus includes general knowledge chunks in the
  `general` domain. No database-specific corpus (e.g., SQL standard references,
  production runbook extracts) is documented as ingested.
- **Evidence:** Internal toolcall benchmarks (`results/toolcall_blind_v3_results.json`,
  `results/false_accept_regression_v1.json`) test REMORA's gate decisions across
  domains including database actions, but there is no database-specific held-out
  evaluation set.
- **Gap:** No domain-specific RAG chunks ingested. No database-domain evidence pack.

### 2.2 Cloud operations (`cloud_ops`)

- **Policy rules:** `docs/policy_cookbook/cloud_ops.md`, covers metrics reads,
  IAM changes, secret rotation, Terraform plan/apply/destroy.
- **RAG chunk coverage:** No cloud-operations-specific corpus (cloud provider
  documentation, NIST cloud guidance, CIS benchmarks) is documented as ingested.
- **Evidence:** Same general toolcall benchmarks. No cloud-specific evaluation set.
- **Gap:** No domain-specific RAG chunks. No cloud-domain evidence pack.

### 2.3 Cybersecurity triage (`cyber`)

- **Policy rules:** `docs/policy_cookbook/cyber.md`, covers CISA KEV matches,
  EPSS-scored CVEs, CWE findings, credential exposure, prompt injection, and
  exploit payload requests.
- **RAG chunk coverage:** The `specialised` domain in the seed corpus includes
  ISO/IEC 27001:2022 and GDPR text. CISA KEV catalog, EPSS data, and NVD CVE
  entries are not documented as ingested.
- **Evidence:** `docs/cyber_evidence_layer.md` references cybersecurity-specific
  evidence. AROMER external benchmark (`results/external_benchmark_agentharm_v1.json`)
  includes cybersecurity-adjacent harm categories.
- **Gap:** CISA KEV, NVD, EPSS, and threat intelligence feeds are not in the
  RAG corpus.

---

## 3. Domains Without Domain Packs (Gap Analysis)

Four operational domains identified in `docs/assurance/operation_baseline_2026_06_30.md`
have no policy cookbook page, no RAG chunks, and no evidence pack:

| Domain | Risk Relevance | Notes |
|--------|---------------|-------|
| **Operational Technology (OT)** | Critical, ICS/SCADA systems; errors are potentially irreversible and safety-affecting | No policy rules, no RAG corpus, no evaluation set. IEC 62443 and NERC CIP references absent. |
| **Energy sector** | High, grid management, energy trading, regulatory compliance | Use-case page `docs/use-cases/04-energy.md` exists but no policy cookbook, no corpus. |
| **Telecommunications** | High, network configuration, service disruption risk | No representation anywhere in the repository. |
| **Cybersecurity (structured intelligence)** | High, addressed in cyber.md but incomplete | CISA KEV / EPSS / NVD integration not implemented. |

These gaps mean REMORA cannot retrieve domain-specific evidence for OT, energy,
or telecom agent actions. The RAG oracle will return `answer: null, confidence: 0.0`
on queries in these domains, routing to the parametric LLM oracles without
structured retrieval support.

---

## 4. Domain Pack Lifecycle

### 4.1 Proposal

A domain pack begins as a Proposal. The proposer must identify:

1. The target operational domain and its risk profile.
2. The primary sources that will form the RAG corpus (e.g., IEC 62443 for OT).
3. The policy outcome rules (at minimum: one ACCEPT and one ESCALATE scenario).
4. The evaluation protocol (what benchmark or shadow-mode corpus will validate the pack).

Proposals are documented as issues in the project tracker referencing this
governance document.

### 4.2 Draft

The Draft phase produces all four components in parallel:

- Draft policy rules page in `docs/policy_cookbook/<domain>.md`.
- Corpus ingestion plan listing sources, URLs, licence status, and confidence weights.
- Ingest candidate chunks into a staging Vectorize index (prefix: `remora-knowledge-staging-<domain>`).
- Open a claim register entry in `docs/assurance/claim_register_v1.yaml` with status `draft`.

No domain pack claims may be published during Draft.

### 4.3 Review

Review requires:

1. A minimum of 20 policy scenarios covering the domain's risk spectrum.
2. RAG coverage test: at minimum 10 representative queries must return `retrieved_chunks >= 1`
   from the domain-specific corpus.
3. A shadow-mode evaluation run on a domain-relevant episode corpus (minimum 50 episodes).
4. Policy owner sign-off (one named reviewer who is not the author).

Review artifacts are stored in `docs/assurance/domain_pack_reviews/`.

### 4.4 Approved

An Approved domain pack:

- Has a committed `docs/policy_cookbook/<domain>.md` with version number and
  approval date in the header.
- Has ingested RAG chunks promoted from staging to the production Vectorize index.
- Has a committed evidence artifact in `results/` with the shadow-mode evaluation.
- Has an updated `docs/assurance/claim_register_v1.yaml` entry with status `validated`.

### 4.5 Retired

A domain pack is Retired when:

- The primary sources are superseded (e.g., ISO standard replaced by a newer edition).
- The policy rules conflict with an updated REMORA core policy.
- The RAG corpus is demonstrably stale (more than 12 months without review).

Retired packs are moved to `docs/policy_cookbook/archive/<domain>_<version>.md`.
RAG chunks from retired packs are tagged `retired: true` in D1 metadata and excluded
from production queries via the `clearance_level` or `domain` filter.

---

## 5. RAG Chunk Lifecycle

### 5.1 Ingestion

Every chunk ingested into the Vectorize knowledge base must carry the following metadata
fields (enforced by `POST /ingest` in `workers/rag-oracle/src/index.ts`):

| Field | Required | Description |
|-------|----------|-------------|
| `source` | Yes | Human-readable source identifier (e.g., "IEC 62443-2-1:2010 §4.2.3") |
| `domain` | Yes | Domain pack identifier (e.g., `ot`, `energy`, `specialised`) |
| `title` | Recommended | Document title |
| `chunk_index` | Yes | Integer position within the source document |
| `confidence_weight` | Yes | Numeric weight (see §5.2 below) |
| `date_ingested` | Auto | ISO 8601 UTC timestamp set by the Worker |
| `clearance_level` | Yes | One of: `public`, `internal`, `restricted`, `secret` |
| `tenant_id` | Conditional | Required for multi-tenant deployments |

### 5.2 Confidence Weight Semantics

| Weight | Meaning | Example |
|--------|---------|---------|
| 2.0 | Primary source: legal statute, peer-reviewed paper, official standard | IEC 62443, GDPR, NIST SP 800-82 |
| 1.5 | Authoritative reference: encyclopaedia, official database, textbook | CISA KEV catalog, NCBI database |
| 1.0 | Neutral: general-purpose source, secondary reference | Industry guidance document |
| 0.5 | Uncertain provenance; verify before relying on | Extracted summary, unverified translation |

### 5.3 Update

When a source document is revised (e.g., a standard update):

1. Ingest the new version with an incremented `chunk_index` range and updated `source` string.
2. Tag the old chunks with `retired: true` in D1 (`remora-rag-meta` database) using a
   targeted UPDATE statement, old chunk vector IDs remain in Vectorize but receive a
   `retired=true` metadata flag that excludes them from production queries.
3. Update the domain pack version number in the policy cookbook page.
4. Commit a changelog entry to `docs/assurance/domain_pack_changelog.md`.

### 5.4 Retirement of Individual Chunks

Individual chunks are retired (not deleted) to preserve the audit trail. The D1
record is updated with `retired_at` (ISO 8601 UTC) and `retired_reason`. Vectorize
does not support soft-delete at the metadata level in the current implementation;
use the domain filter (`domain: { $ne: 'retired' }`) or a dedicated `status` metadata
field as a workaround until Vectorize supports conditional filtering on arbitrary fields.

### 5.5 Prohibited Chunk Content

Chunks MUST NOT contain:

- Secrets, credentials, or API keys.
- Exploit payloads or weaponized proof-of-concept steps (see `docs/policy_cookbook/cyber.md`).
- Personal data of natural persons (per GDPR Article 5(1)(e) storage limitation).
- Customer-specific operational data without explicit clearance classification.

---

## 6. Versioning

Domain packs use a `MAJOR.MINOR` version number in the policy cookbook page header.

| Change type | Version bump |
|-------------|-------------|
| New policy scenario added | MINOR |
| Existing scenario outcome changed | MAJOR |
| RAG corpus sources added | MINOR |
| RAG corpus sources retired | MAJOR |
| Policy owner changed | MINOR |
| Domain scope changed | MAJOR |

The version and effective date appear in the policy cookbook page header comment:

```
# Database Policy Cookbook
# version: 1.2
# effective: 2026-07-01
# approved_by: <reviewer name or role>
```

---

## 7. Conflict Resolution

When a domain-specific policy rule conflicts with a general REMORA policy rule:

1. **Specificity wins:** A domain-specific rule takes precedence over a general rule
   for actions that clearly fall within the domain (e.g., a SCADA write command is
   governed by the OT domain pack, not the general database pack).

2. **Escalation wins over ACCEPT:** If a domain-specific rule says ACCEPT and the
   general rule says ESCALATE, the ESCALATE outcome is used. This is the safe default.

3. **Ambiguous domain assignment:** If an action could fall under two domain packs,
   both policy pages are consulted and the stricter outcome (ESCALATE > VERIFY > ACCEPT)
   is applied. Ambiguity is flagged in the `DecisionEnvelope.assessment.policy_triggers`
   array.

4. **Policy owner escalation:** Conflicts between MAJOR-version policy changes and
   existing validated domain packs must be reviewed by the policy owner of each
   affected domain pack before the new version is marked Approved.

---

## 8. Approval Workflow

```
Proposal → [Author creates draft] → Draft
         → [Corpus ingestion + shadow eval] → Review
         → [Policy owner sign-off] → Approved (production promotion)
         → [Source obsolescence or 12-month staleness check] → Retired
```

Each state transition requires a committed artifact:

| Transition | Required artifact |
|------------|-------------------|
| Proposal → Draft | Issue tracking number, proposer, target domain |
| Draft → Review | Draft policy page, ingestion plan, claim register entry |
| Review → Approved | Signed review document in `docs/assurance/domain_pack_reviews/` |
| Approved → Retired | Changelog entry + retirement rationale |

---

## 9. Recommended Priority Order for New Domain Packs

Based on the gap analysis in §3 and the risk profile of each domain:

1. **OT / ICS**: highest consequence; create before any OT-adjacent deployment.
   Proposed primary sources: IEC 62443 series, NIST SP 800-82 Rev 3, NERC CIP standards.

2. **Energy sector**: existing use-case page provides a starting point.
   Proposed primary sources: ENTSO-E operational guidelines, national grid operator
   operating procedures (public portions), IEA energy security frameworks.

3. **Telecommunications**: no existing content; treat as greenfield.
   Proposed primary sources: ITU-T recommendations (public), 3GPP security specifications,
   ETSI NFVI security guidance.

4. **Cybersecurity intelligence** (extending `cyber.md`), partial coverage exists.
   Proposed additions: CISA KEV catalog, EPSS feed (daily snapshot), MITRE ATT&CK
   (public), NVD CVE summaries.

---

## 10. Constraints and Hard Limits

- Domain pack claims follow the same claim hygiene rules as all REMORA claims
  (`docs/claim_hygiene.md`): no result is claimed without a committed artifact.
- Domain-specific RAG chunks are not substitutes for external validation; they provide
  retrieval signal, not certification.
- A domain pack does NOT override the REMORA hard-block rules (permanent ESCALATE
  outcomes in core policy). Domain packs can only narrow the set of ACCEPT decisions,
  not widen it beyond what the core policy permits.
- No domain pack may claim to be "production-certified" or "safety-guaranteeing."
