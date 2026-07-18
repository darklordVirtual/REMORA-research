# REMORA Artifact Provenance Specification v1

**Date:** 2026-06-30
**Status:** DRAFT, not yet reviewed
**Author:** Agent E (RAG / Evidence Provenance Audit)
**Replaces:** none (first version)

---

## 1. Purpose

This specification defines the required provenance metadata for REMORA result
artifacts, the canonical JSON Schema for that metadata, verification procedures,
and the remediation path for existing artifacts that are missing fields.

Provenance metadata is required because REMORA's claim hygiene rules
(`docs/claim_hygiene.md`, `docs/05-claim-hygiene.md`) mandate that every published
claim is traceable to a committed artifact. Without provenance, it is not possible
to determine whether a result was produced by the current code, on the current
dataset, at what point in time, or under what experimental controls.

---

## 2. Audit of Current Artifacts

Five representative result files were inspected:

### 2.1 `results/conformal_repeated_splits.json`

| Field | Present | Value |
|-------|---------|-------|
| Schema identifier | No |, |
| Commit hash | No |, |
| Timestamp | No |, |
| Script | No |, |
| n_samples | Yes (implicit: `n_seeds=20`) |, |
| Split description | Partial (`notes` field) | "benchmark-locked; exchangeability assumed..." |
| Model version | No |, |
| Jurisdiction | No |, |
| Reviewed_at | No |, |

**Provenance grade: POOR.** No schema, commit, or timestamp. Split methodology described
only in a `notes` string.

### 2.2 `results/external_benchmark_agentharm_v1.json`

| Field | Present | Value |
|-------|---------|-------|
| Schema identifier | Yes | `"schema": "external_benchmark_agentharm_v1"` |
| Commit hash | Yes | `"current_system_commit": "483d1b0"` |
| Timestamp | No (top-level) |, |
| Script | No |, |
| n_samples | Yes | `n_total=416, n_harmful=208, n_benign=208` |
| Benchmark name | Yes | `"ai-safety-institute/AgentHarm"` |
| Benchmark arXiv | Yes | `"benchmark_arxiv": "2410.09024"` |
| Worker endpoint | Yes | `"worker": "https://aromer.razorsharp.workers.dev"` |
| Dry run flag | Yes | `"dry_run": false` |
| Model version | No |, |
| Jurisdiction | No |, |
| Reviewed_at | No |, |

**Provenance grade: GOOD.** Schema, commit hash, benchmark reference all present.
Missing: generation timestamp, model versions used, and reviewer sign-off.

### 2.3 `results/false_accept_regression_v1.json`

| Field | Present | Value |
|-------|---------|-------|
| Schema identifier | Yes | `"schema": "false_accept_regression_v1"` |
| Commit hash | Yes | `"current_system_commit": "27fe2a112f6..."` (full SHA) |
| Timestamp | No |, |
| Script | No |, |
| n_samples | Yes | `n_scenarios=167` |
| Gate result | Yes | `"gate": "PASS"` |
| Model version | No |, |
| Jurisdiction | No |, |
| Reviewed_at | No |, |

**Provenance grade: FAIR.** Schema and full commit hash present. Missing: timestamp,
producing script, model versions.

### 2.4 `results/toolcall_llm_baselines_pilot_n100.json`

| Field | Present | Value |
|-------|---------|-------|
| Schema identifier | Yes | `"schema_version": "llm_baselines_v1"` |
| Commit hash | No |, |
| Timestamp | Yes | `"generated_at": "2026-06-28T22:00:46.200863+00:00"` |
| Model | Yes | `"model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast"` |
| n_samples | Yes | `"n_tasks": 100` |
| Benchmark | Yes | `"benchmark": "toolcall_blind_v3"` |
| Jurisdiction | No |, |
| Reviewed_at | No |, |

**Provenance grade: FAIR.** Good model versioning and timestamp. Missing: commit hash
and producing script.

### 2.5 `results/toolcall_blind_v3_results.json`

| Field | Present | Value |
|-------|---------|-------|
| Schema identifier | No (uses `"benchmark"`) | `"benchmark": "toolcall_blind_v3"` |
| Commit hash | No |, |
| Timestamp | Yes | `"timestamp": "2026-06-28T21:17:36.562393+00:00"` |
| Script | No |, |
| Protocol | Yes | `"protocol"` field with blinding description |
| Gate | Yes | `"gate": "RemoraToolCallGate (default)"` |
| n_samples | Yes | `n_tasks=700` |
| Model version | No |, |
| Jurisdiction | No |, |
| Reviewed_at | No |, |

**Provenance grade: FAIR.** Protocol description and timestamp present. Missing:
commit hash, model versions, producing script.

### Summary of Gaps Across Audited Artifacts

| Field | `conformal_repeated_splits` | `agentharm_v1` | `false_accept_regression` | `llm_baselines_pilot` | `toolcall_blind_v3` |
|-------|:--:|:--:|:--:|:--:|:--:|
| `schema` / `schema_version` | No | Yes | Yes | Yes | No |
| `commit_hash` | No | Yes (short) | Yes (full) | No | No |
| `generated_at` (ISO 8601) | No | No | No | Yes | Yes |
| `script` | No | No | No | No | No |
| `n_samples` | Yes | Yes | Yes | Yes | Yes |
| `model_version` | No | No | No | Yes | No |
| `jurisdiction` | No | No | No | No | No |
| `reviewed_at` | No | No | No | No | No |
| `split` description | Partial | N/A | N/A | N/A | Partial |

The most common gaps are: `script` (producing script), `commit_hash` (all artifacts
except the two regression/benchmark files), and `generated_at` (most artifacts lack
a top-level timestamp).

---

## 3. Required Provenance Fields

Every result artifact in `results/` must carry the following top-level fields:

| Field | Type | Required? | Description |
|-------|------|-----------|-------------|
| `schema` | string | Yes | Schema identifier (e.g., `"false_accept_regression_v1"`) |
| `schema_version` | string | Yes | Semantic version of the schema (e.g., `"1.0"`) |
| `commit_hash` | string | Yes | Full 40-character git SHA of the producing commit |
| `generated_at` | string | Yes | ISO 8601 UTC timestamp of artifact generation |
| `script` | string | Yes | Relative path to the producing script (e.g., `"scripts/run_regression.py"`) |
| `n_samples` | integer | Yes | Total number of items evaluated |
| `model_version` | string | Conditional | Required when a model was used; identifier string (e.g., `"@cf/meta/llama-3.3-70b-instruct-fp8-fast"`) |
| `split` | string or object | Conditional | Required for benchmark results; description of train/calibration/test split |
| `jurisdiction` | string | Conditional | Required for legal/regulatory domain evaluations; ISO 3166 or free-form |
| `reviewed_at` | string | Conditional | ISO 8601 UTC timestamp of reviewer sign-off; required before promoting to `validated` in claim register |
| `gate` | string | Conditional | Required for safety gate artifacts; one of `"PASS"`, `"FAIL"`, `"CONDITIONAL"` |
| `notes` | string | Optional | Free-form comments |

---

## 4. Provenance JSON Schema

The following JSON Schema defines the required provenance envelope. Individual
artifact schemas extend this base.

```yaml
# schemas/result_provenance_schema.yaml
$schema: "https://json-schema.org/draft/2020-12/schema"
$id: "https://remora.dev/schemas/result_provenance/v1"
title: "REMORA Result Artifact Provenance v1"
description: >
  Base provenance envelope that every result artifact in results/ must satisfy.
  Domain-specific artifact schemas extend this schema using JSON Schema $ref
  or allOf composition.
type: object
required:
  - schema
  - schema_version
  - commit_hash
  - generated_at
  - script
  - n_samples
properties:
  schema:
    type: string
    description: "Schema name identifying the artifact type"
    example: "false_accept_regression_v1"
  schema_version:
    type: string
    description: "Semantic version of this artifact schema"
    pattern: "^\\d+\\.\\d+$"
    example: "1.0"
  commit_hash:
    type: string
    description: "Full 40-character git SHA of the producing commit"
    pattern: "^[0-9a-f]{40}$"
    example: "27fe2a112f6257d65b7e3d56d4b22c67f49ca8de"
  generated_at:
    type: string
    format: date-time
    description: "ISO 8601 UTC timestamp of artifact generation"
    example: "2026-06-29T08:02:39+00:00"
  script:
    type: string
    description: "Relative path to the producing script from repository root"
    example: "scripts/run_false_accept_regression.py"
  n_samples:
    type: integer
    minimum: 1
    description: "Total number of items evaluated"
  model_version:
    type: [string, "null"]
    description: "Model identifier when a model was used; null if not applicable"
    example: "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
  split:
    type: [string, object, "null"]
    description: >
      Description of train/calibration/test split.
      For object form: {calibration_fraction, test_fraction, seed, n_calibration, n_test}
  jurisdiction:
    type: [string, "null"]
    description: "ISO 3166-1 alpha-2 country code or free-form jurisdiction string"
    example: "EU"
  reviewed_at:
    type: [string, "null"]
    format: date-time
    description: "ISO 8601 UTC timestamp of reviewer sign-off"
  reviewer:
    type: [string, "null"]
    description: "Reviewer identifier (role or anonymized identifier, not personal data)"
    example: "policy-owner-A"
  gate:
    type: [string, "null"]
    enum: ["PASS", "FAIL", "CONDITIONAL", null]
    description: "Safety gate result; required for gated artifacts"
  notes:
    type: [string, "null"]
    description: "Free-form human-readable notes"
additionalProperties: true
```

This schema is stored at `schemas/result_provenance_schema.yaml`. Test coverage
is provided by `tests/test_artifact_provenance.py` (to be created as part of
remediation, see §6).

---

## 5. Provenance Chain Verification

### 5.1 What the chain guarantees

The provenance chain verifies that:

1. The artifact was produced by the claimed commit (`commit_hash` matches
   `git log` in the repository).
2. The artifact was produced by the claimed script (`script` file exists and
   has not changed since the commit).
3. The artifact was produced at the claimed time (`generated_at` is plausible
   relative to the commit date).

### 5.2 Verification procedure

```python
# scripts/verify_provenance.py (to be created)
import json, subprocess, sys
from pathlib import Path

def verify(artifact_path: str) -> bool:
    artifact = json.loads(Path(artifact_path).read_text())

    # 1. Schema fields present
    required = {"schema", "schema_version", "commit_hash", "generated_at", "script", "n_samples"}
    missing = required - artifact.keys()
    if missing:
        print(f"FAIL: missing fields: {missing}")
        return False

    # 2. Commit hash exists in repo history
    result = subprocess.run(
        ["git", "cat-file", "-t", artifact["commit_hash"]],
        capture_output=True, text=True
    )
    if result.returncode != 0 or result.stdout.strip() != "commit":
        print(f"FAIL: commit_hash {artifact['commit_hash']!r} not in repo history")
        return False

    # 3. Script file exists
    script_path = Path(artifact["script"])
    if not script_path.exists():
        print(f"WARN: script {artifact['script']!r} not found (may be in private repo)")

    print(f"PASS: {artifact_path}")
    return True
```

Run: `python scripts/verify_provenance.py results/<artifact>.json`

### 5.3 CI integration

Add the following step to `.github/workflows/ci.yml` to verify provenance on
every push:

```yaml
- name: Verify artifact provenance
  run: |
    python scripts/verify_provenance.py results/external_benchmark_agentharm_v1.json
    python scripts/verify_provenance.py results/false_accept_regression_v1.json
    python scripts/verify_provenance.py results/toolcall_blind_v3_results.json
```

This step should not block the build for artifacts whose scripts live in the
private implementation repository (log a warning instead of an error).

---

## 6. Remediation Path for Non-Compliant Artifacts

Existing artifacts cannot be retroactively modified without risking the audit
trail. The remediation approach is:

### 6.1 Priority tiers

| Tier | Criteria | Action |
|------|----------|--------|
| **P0** | Artifact is cited in a published claim or release gate | Add a sidecar provenance file immediately |
| **P1** | Artifact is used in CI tests | Regenerate with provenance fields on next benchmark run |
| **P2** | Artifact is historical / informational | Document known gaps in this spec and in the claim register |

### 6.2 Sidecar provenance file

For artifacts that cannot be regenerated (because the run is expensive or
requires external access), create a sidecar file `<artifact>.provenance.json`:

```json
{
  "artifact": "results/external_benchmark_agentharm_v1.json",
  "schema": "provenance_sidecar_v1",
  "schema_version": "1.0",
  "commit_hash": "483d1b0[NEEDS FULL SHA]",
  "generated_at": "[date from git log]",
  "script": "scripts/run_agentharm_benchmark.py",
  "n_samples": 416,
  "model_version": null,
  "notes": "Script lives in private REMORA main repo. Artifact reproduced and committed to REMORA-research for reference.",
  "sidecar_created_at": "2026-06-30T00:00:00+00:00",
  "sidecar_created_by": "Agent E assurance audit"
}
```

Sidecar files are referenced by the claim register entry for the artifact.

### 6.3 Artifact remediation register

The following table tracks remediation status for the five audited artifacts:

| Artifact | Grade | P-tier | Remediation | Status |
|----------|-------|--------|-------------|--------|
| `conformal_repeated_splits.json` | POOR | P2 | Document gaps in claim register | OPEN |
| `external_benchmark_agentharm_v1.json` | GOOD | P0 | Expand commit hash to full 40-char SHA; add `generated_at`; add sidecar noting private script | OPEN |
| `false_accept_regression_v1.json` | FAIR | P0 | Add `generated_at`; add `script`; add sidecar | OPEN |
| `toolcall_llm_baselines_pilot_n100.json` | FAIR | P1 | Add `commit_hash` on next run | OPEN |
| `toolcall_blind_v3_results.json` | FAIR | P1 | Add `commit_hash`, `schema_version`, `script` on next run | OPEN |

### 6.4 New artifacts

All newly generated artifacts must include the full provenance envelope from
creation. Producing scripts must inject `commit_hash` at runtime:

```python
import subprocess, datetime, json

def build_provenance(n_samples: int, model: str | None = None) -> dict:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    return {
        "schema_version": "1.0",
        "commit_hash": commit,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "script": __file__.replace("\\", "/"),
        "n_samples": n_samples,
        "model_version": model,
    }
```

---

## 7. Provenance for RAG Knowledge Chunks

The RAG oracle ingest endpoint (`POST /ingest`) automatically captures the
following provenance metadata for each ingested chunk:

| Field | Captured | Notes |
|-------|---------|-------|
| `source` | Yes | Caller-supplied source identifier |
| `domain` | Yes | Caller-supplied domain label |
| `date_ingested` | Yes | Auto-set to `new Date().toISOString()` by Worker |
| `chunk_index` | Yes | Position within source document |
| `confidence_weight` | Yes | Numeric authority weight (see §5.2 of domain_pack_governance_v1.md) |
| `clearance_level` | Yes | Access control classification |
| `tenant_id` | Yes (optional) | Multi-tenant boundary |

**What is missing from RAG chunk provenance:**

1. **Committer / script reference:** There is no record of which script or operator
   performed the ingest. This should be added as an optional `ingest_script` metadata
   field in `workers/rag-oracle/src/index.ts`.

2. **Source document hash:** The Worker stores `content.slice(0, 1000)` but not a
   hash of the full source document. Adding a `source_sha256` field (SHA-256 of the
   full ingested content) would enable verification that the chunk matches the
   claimed source.

3. **Source URL or canonical reference:** The `source` field is free-form text. For
   structured domains, a `source_url` field (the canonical URL or DOI of the source)
   would enable automated freshness checks.

Recommended addition to the `IngestRequest` interface in `workers/rag-oracle/src/index.ts`:

```typescript
interface IngestRequest {
  // ... existing fields ...
  source_url?: string;    // Canonical URL or DOI
  ingest_script?: string; // Script or tool that performed the ingest
  ingest_operator?: string; // Role identifier (not personal data)
}
```

---

## 8. Jurisdiction and Regulatory Metadata

For artifacts involving regulatory or legal domain evaluations, the `jurisdiction`
field is required. The following conventions apply:

| Scenario | `jurisdiction` value |
|----------|---------------------|
| GDPR / EU data protection | `"EU"` |
| Norwegian law (inkassolov, etc.) | `"NO"` |
| US CISA / NIST guidance | `"US"` |
| IEC international standard | `"INT-IEC"` |
| Multi-jurisdiction | `"MULTI:<ISO1>,<ISO2>"` |
| Not applicable | `null` |

Jurisdiction is informational, it does not affect REMORA's gating logic directly,
but it is required for external reviewers to assess whether the evaluation set is
appropriate for the claimed domain.

---

## 9. Constraints

- No existing result artifacts in `results/` are modified by this specification.
  Remediation is forward-only (new artifacts or sidecars).
- Provenance metadata is informational and traceability-enabling; it does not
  constitute a safety certification or external validation.
- The `reviewed_at` and `reviewer` fields do not substitute for the independent
  human review required by REM-021.
- Claims citing artifacts with POOR provenance grades must be caveated accordingly
  in the claim register.
