# GO-STAR → REMORA Bridge

## Purpose

`remora/evidence/finding_envelope.py` defines the boundary types that carry
a GO-STAR proprietary scanner finding into REMORA's public governance layer.

The design principle is strict separation:
- **Public REMORA** sees structured metadata — no scanner internals, no
  exploit code, no private customer data.
- **Proprietary GO-STAR** keeps all scan rules, taint traces, and PoC
  reproduction artifacts in its own controlled environment.

## Types

### `TargetScanProfile`

Authorised scope for a GO-STAR scan session.  Only findings from
authorised targets may produce `CyberFindingEnvelope` objects.

```python
TargetScanProfile(
    target_id       = "target-001",
    repo_url        = "https://github.com/owner/repo",
    language        = "python",
    threat_model    = "public_api",
    allowed_scope   = ("src/", "api/"),
    authorization_ref = "hackerone:12345",   # bug-bounty or scope doc reference
    scan_mode       = "MODE2",               # MODE1/MODE2/MODE3/MODE4
    created_at      = "2026-06-03T00:00:00Z",
)
```

### `ResearchArtifactRef`

Metadata-only reference to a private GO-STAR vault artifact (crash log,
reproduction script, network trace, SBOM excerpt, or patch candidate).

This type deliberately stores **only** the SHA-256 hash of the artifact,
never its content.  The `vault_ref` is an opaque GO-STAR internal pointer.

```python
ResearchArtifactRef(
    artifact_hash       = "a3f9c2...",          # sha256(artifact_bytes)
    artifact_type       = "repro_script",        # or crash_log / patch / etc.
    sandbox_environment = "docker-isolated",
    preconditions       = ("python 3.11", "service running on :8080"),
    reviewer            = "security-lead",
    vault_ref           = "go-star://vault/repros/find-001",
    created_at          = "2026-06-03T10:00:00Z",
)
```

### `DisclosureLedger`

Tracks a finding through the **six-stage capability ladder**:

```
COVERAGE_HIT        scanner found a candidate; not yet validated
     ↓
REACHABLE_SINK      static / CodeGraph analysis confirms reachability
     ↓
REPRODUCIBLE_CRASH  the condition can be reproduced
     ↓
CONTROLLED_REPRO    controlled reproduction in an owned sandbox
     ↓
PATCH_VALIDATED     fix confirmed, regression test passes
     ↓
REPORT_READY        ready for coordinated disclosure
```

Transitions are **forward-only** — a finding can skip stages (e.g. jump
straight to CONTROLLED_REPRO when a KEV is confirmed), but cannot go
backwards.  Each advance is logged in the ledger's history.

```python
ledger = DisclosureLedger.new(
    finding_id = "find-001",
    content    = {"title": "SQL injection", "cwe": "CWE-89"},
    created_at = "2026-06-03T00:00:00Z",
)

ledger.advance(DisclosureStatus.REACHABLE_SINK, note="taint confirmed via CodeGraph")
ledger.advance(DisclosureStatus.CONTROLLED_REPRO, note="reproduced in Docker sandbox")

print(ledger.status)       # DisclosureStatus.CONTROLLED_REPRO
print(ledger.is_complete()) # False
```

A SHA-256 `commitment_hash` is computed over the initial finding content
at creation time, providing tamper evidence for the disclosure record.

### `CyberFindingEnvelope`

The primary bridge type.  Wraps a scanner finding with its scope profile,
vault references, and disclosure ledger.  Calling `apply_remora()` runs
REMORA's public evidence triage and returns a new envelope with the verdict
attached — the original is unchanged.

```python
from remora.evidence.finding_envelope import (
    CyberFindingEnvelope, TargetScanProfile, DisclosureLedger, DisclosureStatus,
    ResearchArtifactRef,
)
from remora.evidence.cyber import CyberEvidenceProvider

profile = TargetScanProfile(
    target_id="oss-target-001",
    repo_url="https://github.com/owner/repo",
    language="python",
    threat_model="public_api",
    allowed_scope=("src/",),
    authorization_ref="huntr:oss",
    scan_mode="MODE2",
)

ledger = DisclosureLedger.new(
    finding_id="find-001",
    content={"title": "SQL injection", "cwe": "CWE-89"},
    created_at="2026-06-03T00:00:00Z",
)

env = CyberFindingEnvelope(
    finding_id="find-001",
    target_profile=profile,
    title="Unsanitized SQL query in login path",
    description="User-controlled input concatenated into SELECT. CWE-89.",
    severity="high",
    cwe_ids=("CWE-89",),
    cve_ids=(),
    attack_ids=("T1190",),
    packages=(),
    source_file="api/auth.py",
    sink_file="api/auth.py",
    tool_signals=2,
    exposed=True,
    production=True,
    ledger=ledger,
)

provider = CyberEvidenceProvider()
env_with_verdict = env.apply_remora(provider)

print(env_with_verdict.verdict())           # "REPORT_READY"
print(env_with_verdict.governance_action()) # "VERIFY"
print(env_with_verdict.triage_result.confidence)  # 0.72

# Advance the ledger after manual confirmation
env_with_verdict.ledger.advance(
    DisclosureStatus.REACHABLE_SINK,
    note="CodeGraph confirms source-to-sink path"
)
```

### Constructing from a `GoStarFinding`

When GO-STAR produces a `GoStarFinding` object (from `remora.integrations.gostar`),
use the convenience constructor:

```python
from remora.integrations.gostar import GoStarFinding, OracleSignal, Severity

go_star_finding = GoStarFinding(
    finding_id="gf-001",
    title="Path traversal in file upload",
    description="CWE-22 traversal in upload handler",
    severity=Severity.HIGH,
    cwe="CWE-22",
    file_path="api/upload.py",
    sink="open(",
    oracle_signals=[
        OracleSignal(tool="semgrep", family="static", evidence_role="primary", confidence=0.85),
        OracleSignal(tool="codegraph", family="graph", evidence_role="corroborating", confidence=0.80),
    ],
)

envelope = CyberFindingEnvelope.from_gostar_finding(go_star_finding, profile)
envelope_with_verdict = envelope.apply_remora(CyberEvidenceProvider())
```

## Boundary Rules

1. `CyberFindingEnvelope` must never carry exploit payloads, weaponized PoC
   code, or credential values.  Those stay in the GO-STAR vault.
2. `ResearchArtifactRef.vault_ref` is an opaque identifier.  REMORA does not
   resolve it — it is logged for audit purposes only.
3. `DisclosureLedger.disclosure_locked = True` freezes the ledger.  No status
   changes are permitted after lock.
4. `TargetScanProfile.authorization_ref` must reference a valid bug-bounty
   programme or explicit scope document before MODE 1 or MODE 2 scans.

## Relationship to GO-STAR Skill

The GO-STAR skill (`/go-star`) describes the four scan modes and the
`go-star-remora.razorsharp.workers.dev` worker endpoint.  The bridge types
in this module are the data contract between GO-STAR pipeline output and
that worker's governance API.
