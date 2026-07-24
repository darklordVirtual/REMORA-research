# Changelog

All notable changes to this repository are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project is
research-grade software; version tags mark review handoffs, not production
releases.

## [Unreleased]

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
