# REMORA Cyber Evidence v1

This is a public, curated cyber evidence pack for REMORA.

It is designed to support security-finding triage, evidence-aware action
governance, benchmark demos, and vector-store seeding. It is not a scanner and
does not contain proprietary GO-STAR internals or private customer findings.

## What It Provides

- Public evidence objects from NVD, CISA KEV, FIRST EPSS, MITRE ATT&CK, CWE,
  OWASP, and GitHub Advisory Database style sources.
- A dynamic source registry for current known-exploited, exploit-likelihood,
  package advisory, technique, weakness, and OT/ICS metadata.
- Exact lookup fields for CVE, CWE, ATT&CK technique, package, KEV, EPSS, and
  CVSS.
- RAG-ready text fields for vector indexing.
- Labelled cyber triage cases for REMORA demonstrations.
- Policy rules for report-ready, review, false-positive, and escalation
  decisions.
- A deterministic validation script and vector-payload builder.

## What It Does Not Provide

- It is not a full vulnerability database.
- It is not production security certification.
- It does not perform code scanning.
- It does not include GO-STAR source code, proprietary rules, private findings,
  or commercial scanner data.
- It does not automatically update REMORA policy.

## Intended Architecture

```text
Public cyber evidence pack
  -> CyberEvidenceProvider
  -> REMORA evidence signal and triage verdict
  -> REPORT_READY / NEEDS_REVIEW / LIKELY_FALSE_POSITIVE / ESCALATE

Optional future commercial extension
  -> proprietary scanner findings
  -> same public CyberEvidenceProvider boundary
  -> REMORA governance
```

The important boundary is that the public dataset describes evidence and
decision logic. Proprietary products may later provide candidate findings, but
they are not required to use this evidence layer.

## Directory Structure

```text
cyber_evidence_v1/
  README.md
  manifest.yaml
  evidence/
    cyber_evidence_objects.jsonl
  cases/
    security_cases.jsonl
  expected_decisions/
    cyber_expected_decisions.jsonl
  policies/
    cyber_triage_rules.yaml
  live_sources/
    threat_source_registry.yaml
  vectors/
    vectorization_manifest.json
  scripts/
    validate_cyber_evidence.py
```

## Evidence Object Schema

Each JSONL row contains:

```json
{
  "evidence_id": "ev_nvd_CVE_2021_44228",
  "source": "nvd",
  "source_url": "https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
  "source_type": "api|static_rag|manual_seed",
  "title": "NVD: CVE-2021-44228 Log4Shell",
  "content": "Concise evidence text.",
  "domain": "vulnerability_management",
  "risk_tags": ["rce", "kev", "critical"],
  "authority_score": 0.98,
  "freshness_score": 0.90,
  "coverage_score": 0.95,
  "contradiction_score": 0.0,
  "cve_ids": ["CVE-2021-44228"],
  "cwe_ids": ["CWE-502"],
  "attack_ids": ["T1190"],
  "packages": ["log4j"],
  "kev": true,
  "epss_score": 0.97,
  "cvss_score": 10.0,
  "exploit_maturity": "known_exploited",
  "remediation": "Patch or remove affected dependency.",
  "license_note": "public_domain",
  "retrieved_at": "2026-06-03T00:00:00Z",
  "version": "1.0.0"
}
```

## Vectorization

Use the builder to produce RAG/vector-store payloads:

```bash
python scripts/build_cyber_vector_payload.py
```

Output:

```text
artifacts/cyber_evidence_v1/vector_payload.jsonl
```

The payload separates `text` from `metadata` so it can be sent to Cloudflare
Vectorize, Qdrant, Chroma, pgvector, or another store.

## Dynamic Threat Sources

The source registry is:

```text
live_sources/threat_source_registry.yaml
```

It lists metadata-only sources for current threat context:

- CISA KEV for known exploited vulnerabilities
- NVD CVE API for CVE/CVSS/CWE metadata
- FIRST EPSS for exploit probability
- OSV and GitHub Advisory Database for open-source package advisories
- MITRE ATT&CK STIX for adversary technique mapping
- CWE/CAPEC-style taxonomy sources for weakness context
- CISA ICS advisories for operational technology relevance

Sync supported public feeds with:

```bash
python scripts/sync_cyber_threat_feeds.py --source all --max-records 50
```

Output is written under:

```text
datasets/cyber_evidence_v1/live_feeds/
```

Public REMORA ingests advisory and classification metadata only. It does not
collect exploit payloads, weaponized PoC code, or proprietary scanner traces.

## Validation

```bash
python datasets/cyber_evidence_v1/scripts/validate_cyber_evidence.py
```

Validation checks:

- required evidence fields
- score ranges
- unique evidence and case IDs
- expected decisions for all cases
- no high-risk public cases marked as autonomous closure
- all public evidence rows have source URLs
- no proprietary scanner payloads embedded in the public dataset

## Safe Learning Rule

Reviewer outcomes may create policy update candidates, but policy candidates
are never auto-applied. Every policy change requires human owner approval and
regression tests.
