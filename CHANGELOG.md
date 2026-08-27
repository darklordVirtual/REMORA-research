# Changelog

This file lists externally relevant changes by release. Fine-grained development history remains available in Git commits and pull requests; the pre-cleanup changelog remains recoverable from repository history rather than being duplicated as a current documentation artifact.

## Unreleased

### Roadmap

- RF-12 (docs/13): database-enforced tenant isolation via Postgres row-level
  security, grounded against the tree. Records two blockers no earlier
  document named: the reference and pilot deployments connect as the Postgres
  superuser (RLS bypassed even when forced) and nothing binds the verified
  tenant to the connection. REM-026 notes and the multi-tenant security model
  point to it. Proposal only; nothing implemented.

### Documentation

- Prose-style scanner (`scripts/check_prose_style.py`) gained two
  sentence-level tells: `long_sentence` (over 35 words, wrapped lines
  joined, lists and tables skipped) and `meta_governance` (sentences about
  how a document is to be read rather than about the system). Baseline
  re-recorded at 575 and 45; both remain shrink-only. The character-level
  tells were near zero after the 2026-08-26 pass; these two name what
  still makes the documentation hard to read.
- `docs/README.md` rebuilt in two layers: a seven-step reading path and a
  "which one do I want" table for the topics with more than one document
  (architecture, security, MCP, GO-STAR, SAP versions, claims), with the
  full registered set in collapsible groups by question. Every link from
  the previous index is preserved (governance index-completeness check);
  meta-governance sentences in the index went from 7 to 0.
### Repository layout

- Root tidy, slice A: the licensing bundle (`COMMERCIAL_LICENSE.md`,
  `LICENSING.md`, `COPYRIGHT.md`, `TRADEMARKS.md`, `THIRD_PARTY_NOTICES.md`)
  moved to `legal/`; `EVIDENCE_OF_CAPABILITY.md` and `CONTRIBUTORS.md` to
  `docs/`; `docker-compose.test.yml` to `deploy/`. All moves via `git mv`
  (history preserved). Every reference updated: pyproject `license-files`,
  license-policy gate, document register, governance and provenance
  scanners, tests, NOTICE, codegraph paths and Markdown links. `LICENSE`,
  `NOTICE`, `CITATION.cff`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  `CONTRIBUTING.md` and `NEGATIVE_RESULTS.md` stay at the root (GitHub
  reads them there). Slice B (`ARCHITECTURE.md`, `DEVELOPER_OVERVIEW.md`)
  follows separately because it touches `CLAUDE.md` and CI workflows.

### Paper

- Reframed the paper around governed execution assurance: the authority-bound
  execution chain (signed ToolSpec, exact-call lease, key-custody separation,
  re-policying at the enforcement point, effect-evidence states) is now the
  stated identity, with the multi-oracle machinery positioned as routing
  support. The architecture chapter describes the deployed
  Ed25519/ToolSpec/lease/custody/PEP model with its gaps stated.
- Related work gains an authority-bound execution section with explicit
  non-claims, positioning against AIRGuard, Proof-Carrying Agent Actions,
  Proof of Execution and the agent-permissions survey (all four verified and
  added to both reference lists; citation parity 67=67).
- The version stamp moves to v0.11.0 / 2026-08-25 against the frozen release
  tag; the "synchronized" wording is dropped and the stale review-v1 pointer
  and test counts are corrected.

## 0.11.0 — 2026-08-25

The first frozen research release since 0.10.0: an exact, tagged commit that
the paper, external replication and citation can reference instead of a
moving master (issue #390).

### Execution assurance

- Cross-tenant argument values now hard-abstain instead of escalating to a
  human approver, on both the assess and the approved-redeem path; the
  boundary is re-checked when a previously approved item is redeemed.
- The decision record declares per-component trust-base coverage
  (`policy_components`): which policy, risk-profile, schema, registry,
  engine-mode and OPA digests the decision resolved, and — explicitly —
  which trust-base elements carry no digest. Written on both the
  authorization and the result chain records, re-read at dispatch so the
  two views can disagree.
- Governed dispatch verifies the lease against the clock it was issued
  under; an in-memory SQLite database is refused as a durable backend at
  the enforcement gate, the nonce store, the idempotency store and
  production startup.
- One runtime exception root (`remora.errors.RemoraError`) with
  machine-readable `code`/`category` across sixteen governance exceptions;
  every builtin base callers catch is preserved.

### Observability

- No silent fallback in the safety path: parser-layer degradation, a dead
  injection oracle, calibration failure, identity-verification failure and
  a crashed correlation model each emit one structured governance event,
  with their fallback semantics unchanged.
- Tracing is structural: spans nest as children, the decision span carries
  its DecisionEnvelope id, governed dispatch emits the OTel GenAI
  `execute_tool` span joined on the proposal id, and the authority→executor
  hop propagates W3C trace context.
- `/v1/health` reports the observed oracle-swarm size instead of a
  constant; the MCP server no longer silences warnings process-wide.

### Verification and CI

- Capability freshness binds to evidence-file content rather than commit
  count, so squash-merges no longer produce false staleness.
- A shipped-surfaces matrix names every advertised surface and the CI jobs
  that guard it, enforced with an additive ratchet.
- The execution TCB's injected collaborators are typed against structural
  ports, with conformance of every production implementation proven by the
  mypy gate.

### Security

- CodeQL triage to zero open security-severity alerts: a ReDoS in the
  admission-path coercion heuristic, two SSRF vectors in the pilot console,
  and error-detail exposure in the Cloudflare Workers, with the remaining
  alerts dismissed only with verified written reasons.

### Repository hygiene

- Simplified the public README and documentation index around one canonical runtime reading path.
- Added explicit CORE / OPTIONAL / EXPERIMENTAL / HISTORICAL boundaries for developer handoff.
- Added branch lifecycle and documentation-style rules to the contribution guide.
- Removed committed local frontend planning state and ignored future `.lovable/` workspace files.
- Added automatic deletion of branches with merged-PR evidence while preserving open and unverified branches.
- Preserved research history while removing older thermodynamic/statistical-physics work from the primary runtime documentation path.

### Execution assurance

- Added explicit `development`, `research`, `review` and `controlled_pilot` runtime profiles.
- `review` and `controlled_pilot` fail closed unless Signed ToolSpec, trusted signer identity, deployment-owned callable registry, durable execution state and PDP signing prerequisites are present.
- Clarified that `/v1/execution/*` is the enforcing surface and that advisory assessment APIs do not control bypass credential paths.

## 0.10.0 — 2026-07-25

### Licensing

- Moved new REMORA versions to Business Source License 1.1 with separate commercial licensing.
- Added licensing, copyright, trademark and third-party notice material.
- Added a CI policy check for license metadata drift.

### Research and assurance

- Continued the claim-register, capability-register, reproducibility and negative-result governance model.
- Preserved benchmark caveats and superseded findings as part of the evidence record.

For detailed changes between revisions, use Git history and merged pull requests.
