# Changelog

All notable changes to this repository are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project is
research-grade software; version tags mark review handoffs, not production
releases.

## [Unreleased]

### Fixed (external paper-to-code review 2026-07-24)

- **Publication-blocking headline (paper .tex)**: the LaTeX source still
  carried the withdrawn tool-call numbers (baselines 10–20%, task-level
  Wilson [0.00%, 0.55%], "700 independent tasks"); abstract, results table,
  and conclusion now match the authoritative claim register (effective N=70
  clusters, cluster-level Wilson [0.0%, 5.2%], baselines 1.4%, safety delta
  not significant at p=0.50, significant gains utility +0.456 and accuracy,
  "unsafe acceptance" wording, no real side effects).
- **Implemented ≠ integrated**: implementation tables in both paper sources
  gained an "Integrated in /v1/assess" column; OPA, Governance Intelligence,
  PhaseAwareGuardrail, CRC, and the PVD-inspired score are labeled offline/
  adapter components; correlation weighting is marked per-request in the API.
- **CRC honesty**: `CRCReport.guaranteed_risk_bound` → `nominal_risk_bound`,
  `weighted_holdout_risk` → `holdout_risk`; docstrings state the Theorem-1
  guarantee does not attach under fixed-β phase-heuristic weights.
- **PVD reframed**: "PVD-inspired offline agreement score" (no training game,
  no live deliberation); Kirchner et al. citation corrected (was "Kirsch,
  Harrison, Misra, & Leike").
- **Audit wording**: envelopes are attribute-frozen (not deep-frozen);
  evidence records are hash-chained and HMAC-signed only when the signing
  key is configured; "deployable operating point" → "stable internal
  benchmark operating point"; undefined `fig:arch`/`sec:se` references fixed;
  paper version now cites tag `review-v1`. Tracked as REM-046.

### Fixed (external technical review 2026-07-24)

- **Actor binding enforced (F-02)**: an `ExecutionLease` issued to a named
  actor now refuses to verify/dispatch without a matching authenticated
  identity (`actor_identity_required` / `actor_identity_mismatch`);
  previously the actor was signed audit metadata a stolen lease ignored.
- **Token not-before (F-03)**: `PolicyDecisionToken.verify()` rejects tokens
  whose `issued_at` lies in the future (`token_not_yet_valid`), closing the
  path where a future-dated five-minute token was accepted for ~30 days.
- **Postgres audit signatures (F-04)**: `PostgresTenantChain.append()` now
  writes the HMAC signature in the same transaction, matching the SQLite
  contract; previously every entry verified as `signature_missing` once
  `REMORA_AUDIT_SIGNING_KEY` was configured.
- **Request-ID collisions (F-08)**: `/v1/assess` and `/v1/rerun` IDs use a
  uuid4 suffix instead of monotonic-milliseconds modulo 1e6 (repeated every
  ~16.7 minutes and could interleave audit records).
- **AROMER state path (F-10)**: default `~/.aromer` paths are resolved at
  instantiation with a `REMORA_AROMER_HOME` override, so locked-down homes
  no longer break the default-configured store/bridge.
- **Register honesty (F-09, F-01, F-05)**: REM-015 retitled to "captured
  development environment snapshot" (its old title promised uv.lock/SBOM/
  digests its own notes denied — REM-027 stays the only supply-chain gate);
  REM-035 now states that `/v1/execution/execute` consumes the grant without
  invoking a tool; new REM-045 records that the built wheel omits `servers/`
  and the Postgres drivers; the README architecture diagram marks "Execute"
  as the caller's step pending PEP integration.

### Fixed (REM-021 handoff consolidation)

- **Source-of-truth scoping completed**: the thermodynamics ledger
  (`docs/thermodynamics/claim_ledger.yaml`) and its credibility-pack copy no
  longer call themselves the overall "single source of truth"; the external
  review checklist now starts claim integrity from
  `docs/assurance/claim_register_v1.yaml`; the authoritative register is
  shipped in the credibility pack (`claim-register.yaml`); and the guard test
  scans YAML and pack files, not only Markdown.
- **AgentHarm register drift**: the remediation register no longer says
  "external validity guaranteed" or "10/10 gate tests";
  `scripts/run_agentharm_benchmark.py` is marked as a separate local protocol,
  not a reproduce artifact, in line with the imported-historical
  classification of CLAIM-002.
- **Stale-green hardening**: the committed (dirty-worktree) test attestation
  was removed from the repository and gitignored; the attestation workflow
  deletes any leftover attestation files before generating, so `if: always()`
  can only ever upload freshly generated PASS or FAIL files.
- **SHA-bound handoff**: the review-tag workflow now also builds the
  governance benchmark pack, verifies that the pack manifest `commit_sha` and
  the attestation commit equal `github.sha`, and uploads a single combined
  handoff artifact (`remora-review-handoff-<sha>`).
- **CONTRIBUTING.md / provenance spec**: removed self-referential
  "redirect stub" and duplicated-path text around `docs/05-claim-hygiene.md`.

### Fixed (external-review readiness)

- **CLAIM-005** critical-phase trust inversion is now backed by a committed,
  reproducible artifact (`results/critical_trust_split_v1.json`); the headline
  numbers were corrected to their aggregate-consistent values (low-trust 76.2%,
  high-trust 36.4% at the τ=0.10 boundary) across the register, docs, and paper.
- **Single source of truth**: `docs/assurance/claim_register_v1.yaml` is now the
  sole authoritative claim register; conflicting statements in companion docs
  were aligned and a guard test added.
- **AgentHarm (CLAIM-002)** reclassified as an imported-historical result with a
  structural verifier (`tests/test_rem014_external_benchmark.py`); the
  non-matching reproduce command was removed.
- **Reviewer pack** rebuilt with clean-dir builds, per-file SHA-256, commit SHA,
  and lockfile hashes; the stale task-level Wilson bound was replaced by the
  canonical cluster-level figure.
- **Review docs**: resolved the `enterprise/` catalog contradiction, made the
  stage-order review question testable, and fixed a dead evidence-and-claims link.

### Added

- CI-generated review attestation from a clean checkout
  (`.github/workflows/attestation.yml`, `--require-clean`).
- Dependabot configuration for pip, npm, and GitHub Actions.
- `CITATION.cff` and `CODE_OF_CONDUCT.md`.
- Theory roadmap proposals: value of information, optimal stopping.
