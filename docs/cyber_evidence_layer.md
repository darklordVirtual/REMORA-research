# Cyber Evidence Layer

REMORA now includes a standalone public cyber evidence layer:

```text
datasets/cyber_evidence_v1/
remora/evidence/cyber.py
```

The purpose is to give REMORA a clean, modular evidence surface for security
finding triage without mixing public REMORA code with proprietary scanner
internals.

## Why This Exists

Security triage is noisy:

- static tools produce false positives
- advisory databases lag or disagree
- LLMs can over-trust weak evidence
- reviewers need source-linked justification

REMORA should not simply accept a scanner finding. It should ask:

```text
Which public evidence supports this finding?
Is there exact CVE, CWE, ATT&CK, KEV, EPSS, or package-version evidence?
Is the finding exposed, reachable, and production-relevant?
Is it known exploited, public-exploit-likely, or emerging/unknown?
Should this be report-ready, reviewed, suppressed, or escalated?
```

## Separation From Proprietary Extensions

The public REMORA layer contains:

- public evidence schemas
- curated seed evidence
- exact lookup and retrieval logic
- triage policy rules
- validation and vector payload scripts
- tests

It does not contain:

- proprietary GO-STAR source code
- private scan rules
- private customer findings
- scanner-internal traces
- automatic policy mutation

GO-STAR can later be sold as a proprietary extension that supplies candidate
findings into this public REMORA boundary. The boundary remains:

```text
candidate finding -> CyberEvidenceProvider -> REMORA governance verdict
```

This keeps the open-source REMORA project useful and reviewable while leaving
commercial scanner capability outside the public repository.

## Retrieval Model

Cyber evidence should not be pure vector search. REMORA uses two retrieval
modes:

| Mode | Used For |
|------|----------|
| Exact lookup | CVE, CWE, ATT&CK, package, KEV, EPSS, CVSS |
| RAG/vector search | Advisory narratives, remediation text, similar case descriptions |

This matters because a vector store can find similar text, but exact security
identifiers are operational facts.

## Exploit Classification

The cyber layer separates exploit maturity from ordinary severity:

| Class | Meaning |
|-------|---------|
| `KNOWN_EXPLOITED` | KEV or explicit known-exploitation evidence is present |
| `PUBLIC_EXPLOIT_LIKELY` | Exact vulnerability evidence plus high exploit-probability signal |
| `EMERGING_OR_UNKNOWN` | Strong weakness or technique evidence, but no known-exploited signal |
| `WEAK_OR_UNCORROBORATED` | Evidence exists but is not strong enough |
| `LIKELY_FALSE_POSITIVE` | Contradiction or benign-context evidence dominates |

This makes the platform useful for target-oriented scanning:

```text
Open-source repository
  -> manifest, dependency, IaC and source-code signals
  -> exact evidence lookup
  -> exploit maturity classification
  -> defensive validation plan
  -> REMORA governance verdict
```

## Dynamic Threat Intelligence

The cyber layer includes a public source registry:

```text
datasets/cyber_evidence_v1/live_sources/threat_source_registry.yaml
```

The registry tracks metadata-only feeds for current threat context:

| Source | REMORA use |
|--------|------------|
| CISA KEV | `KNOWN_EXPLOITED` classification and escalation |
| NVD CVE API | CVE, CVSS, CWE and affected-product metadata |
| FIRST EPSS | exploit-probability signal for exact CVE matches |
| OSV.dev | open-source package advisory and affected-version context |
| GitHub Advisory Database | GHSA/CVE package advisory enrichment |
| MITRE ATT&CK STIX | technique and tactic mapping |
| CWE | weakness taxonomy and remediation vocabulary |
| CISA ICS advisories | OT/energy/industrial-control relevance |

Sync supported feeds with:

```bash
python scripts/sync_cyber_threat_feeds.py --source all --max-records 50
```

The script writes normalized JSONL under:

```text
datasets/cyber_evidence_v1/live_feeds/
```

The sync layer is metadata-only. It does not download exploit payloads,
weaponized PoC code, or proprietary scanner traces. Restricted research PoC
artifacts belong in controlled systems with access control and audit, not in
the public REMORA dataset.

## Defensive PoC Plan

The provider can return a `poc_plan`, but this is intentionally a defensive
validation plan, not weaponized exploit code. A plan may ask the reviewer to:

- confirm package and version evidence from SBOM or lockfiles
- confirm source-to-sink reachability
- reproduce only the control-flow condition in an owned sandbox
- use synthetic data
- collect screenshots, command transcripts and reviewer sign-off

It explicitly blocks:

- exploit payloads against third-party systems
- credential theft, persistence, lateral movement or exfiltration
- destructive proof steps in production

This gives security teams evidence and repeatability without turning REMORA
into an offensive exploit generator.

## Provider API

```python
from remora.evidence import CyberEvidenceProvider

provider = CyberEvidenceProvider()

result = provider.triage(
    title="Internet-facing Log4j dependency",
    description="Production service includes log4j 2.14.1 and CVE-2021-44228",
    severity="critical",
    cve_ids=["CVE-2021-44228"],
    packages=["log4j"],
    exposed=True,
    production=True,
    tool_signals=3,
)

print(result.verdict.value)       # ESCALATE
print(result.governance_action)   # ESCALATE
print(result.exploit_classification.value)  # KNOWN_EXPLOITED
print(result.poc_plan.readiness.value)      # HUMAN_REVIEW_REQUIRED
print(result.matches[0].record.source)
```

The provider also implements the REMORA evidence provider interface:

```python
provider.fetch(
    question="Should CVE-2024-3094 in production xz be escalated?",
    domain="supply_chain_security",
    risk_tier="critical",
    action_type="triage",
    target_environment="production",
    oracle_responses=[],
)
```

## Vector Payload

Build vector-store payloads with:

```bash
make cyber-vector-payload
```

Output:

```text
artifacts/cyber_evidence_v1/vector_payload.jsonl
```

The payload has:

```json
{
  "id": "ev_nvd_CVE_2021_44228",
  "text": "RAG-ready evidence text",
  "metadata": {
    "source": "nvd",
    "cve_ids": ["CVE-2021-44228"],
    "kev": true,
    "epss_score": 0.97
  }
}
```

## Validation

```bash
make cyber-evidence
```

The validator checks schema, score ranges, decision labels, source URLs, and
that proprietary markers are not embedded in the public dataset.

## Current Claim Status

Supported:

- The module loads curated public cyber evidence.
- Exact lookup for CVE/CWE/ATT&CK/package works deterministically.
- Vector payloads can be generated without API keys.
- Triage decisions are test-backed on the bundled seed cases.

Not claimed:

- This is not a full vulnerability database.
- This is not scanner accuracy evidence.
- This does not prove GO-STAR performance.
- This does not certify production security.
- This does not auto-update policy.
