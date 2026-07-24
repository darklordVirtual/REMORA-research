# Changelog

All notable changes to this repository are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project is
research-grade software; version tags mark review handoffs, not production
releases.

## [Unreleased]

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
