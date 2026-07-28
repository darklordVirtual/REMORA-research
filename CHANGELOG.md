# Changelog

All notable changes to this repository are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project is
research-grade software; version tags mark review handoffs, not production
releases.

## [0.10.0] - 2026-07-25

### Licensing

- Changed the license for new REMORA versions to the Business Source
  License 1.1 (source-available). Licensor: Stian Skogbrott. No commercial
  use is permitted without a separate REMORA Commercial License and
  compensation agreed with the Licensor.
- Change Date 2030-07-25; Change License GNU GPL v2.0 or later (BSL's
  covenant requires a GPL-compatible change license).
- Added `LICENSING.md`, `COMMERCIAL_LICENSE.md`, `COPYRIGHT.md`,
  `TRADEMARKS.md`, `THIRD_PARTY_NOTICES.md`, and `LICENSES/BUSL-1.1.txt`;
  rewrote `NOTICE`; migrated ~400 source headers to
  `SPDX-License-Identifier: BUSL-1.1`.
- Historical versions prior to 0.10.0 keep the license terms they were
  actually distributed with; no new grants are made under those terms.
- Added `scripts/check_license_policy.py` as a CI gate against legacy
  open-source license metadata drift, and a contribution-licensing/CLA
  section to the contributing docs.

## [Unreleased]

### Changed (documentation clarity and drift alignment, 2026-07-28)

- README front page rewritten for first-time readers: a "Key terms" section
  defines every abbreviation and benchmark concept in plain language; the
  negative headline results (temperature falsification, N544 holdout,
  critical-phase trust inversion) moved with their claim anchors to a new
  headline table at the top of `NEGATIVE_RESULTS.md` — moved, not removed.
- `docs/README.md` rewritten in English as the single authoritative
  documentation index, organized by reader goal; superseded documents are no
  longer linked (succession is tracked in the document register). Deleted the
  competing Norwegian `docs/INDEX.md` and its register entry.
- Aligned documentation with shipped code: the paper's wiring table now
  reflects the dispatched `/v1/execution/*` PEP path (wired 2026-07-27); the
  API reference scopes "caller-populated" fields to `/v1/assess` only; the
  documentation-governance spec now states honestly which checks are HARD vs
  ADVISORY; the nested-governance layer model matches the eight layers in
  `remora/governance/nested_governance.py`.

### Fixed (CI and governance tooling, 2026-07-28)

- The scheduled AROMER telemetry workflow pushed from a detached HEAD with an
  unqualified refspec and had failed every run since the telemetry-branch
  strategy landed; the push is now fully qualified and verified green.
- `run_docs_gate` (audit-gates API) previously ignored the historical-ban
  list it built and only ever matched one hardcoded filename, and its
  unregistered-document check was limited to a test-only filename prefix.
  It now enforces both checks generically, scoped to git-tracked files, and
  the formerly empty metatest asserts the unregistered-document failure.
- Committed the pre-SAP-v3 Groq-live N500 artifacts under
  `results/superseded_groq_live_2026-07-27/` with an explicit superseded
  notice and their provenance sidecars, instead of leaving them untracked.

### Changed (complete Apache-2.0 removal, 2026-07-25)

- Owner decision: remove every REMORA-authored reference to the Apache-2.0
  license so the whole repository points only to BUSL-1.1 / the REMORA
  Commercial License. Converted the demo banners, the AROMER master document,
  the HF dataset card, the knowledge/cyber dataset license notes, the archived
  infographic, and a claim-register snapshot to BUSL-1.1; dropped the optional
  "OPA (Apache 2.0)" phrasing from the paper acknowledgements; deleted the
  now-obsolete `scripts/migrate_license_headers.py`; deleted the
  `v0.9.0-apache-last` boundary tag; and reworded the enforcement-gate labels
  to "legacy-license drift".
- Deliberately KEPT (removing these would misrepresent third parties or break
  the ban's own enforcement): the third-party upstream license facts in
  `THIRD_PARTY_NOTICES.md` (OPA and TruthfulQA are genuinely Apache-2.0) and
  the Kubernetes-docs source license in the knowledge dataset manifest; the
  "Apache Jena" product name in `rdf_export.py`; Apache-software CVE content in
  the cyber-evidence dataset; and the Apache SPDX strings inside
  `scripts/check_license_policy.py`, which names them only to DETECT and forbid
  them. The license-policy gate confirms no REMORA-authored Apache metadata
  remains.

### Changed (Grok review P1 — calibrated vs heuristic thresholds, 2026-07-25)

- The hand-tuned decision thresholds (ordered-high-trust 0.72, evidence
  confidence 0.7, low-trust 0.2, minimax ambiguity width 0.15, env/session
  0.80, classification/misspecification 0.60, session count 100, policy
  generalization 0.70, similar-action flood 50) were promoted from inline
  magic numbers to named module constants in `remora/policy/decision_engine.py`
  under an explicit HEURISTIC section, with a header that separates them from
  the CALIBRATED thresholds (temperature T*≈0.1972, conformal) which remain
  constructor-injected from committed artifacts and are never hard-coded.
  Each heuristic constant is documented as hand-tuned and NOT artifact-backed
  (claim hygiene). Values are unchanged; `tests/test_policy_threshold_constants.py`
  pins each to its historical value and asserts the calibrated thresholds stay
  injection-only.

### Changed (Grok review P1 — decide/explain single source, 2026-07-25)

- The 25 uniform conditional policy gates (between the hard-guard floor and
  the ACCEPT tail) now live once in `_CONDITIONAL_GATES`;
  `RemoraDecisionEngine.decide()` returns on the first gate that fires and
  `explain()` records every gate from the same ordered inventory, so the audit
  trace can no longer drift from the decision when a gate is added. Behaviour
  is unchanged (each gate's predicate is self-contained). New
  `tests/test_decide_explain_single_source.py` locks decide/explain agreement
  across a broad battery. The hard-guard floor (already centralised in
  `hard_guard_floor()`), the two-phase schema-unverified handling, and the
  ACCEPT/VERIFY/ABSTAIN tail remain literal. Also documented that the
  non-ACCEPT `risk_estimate` values are relative labels, not calibrated
  probabilities (Grok review 4.4).

### Fixed (review round 3b, 2026-07-25)

- **R3-01**: the selective-risk component no longer claims the CRC theorem.
  `CovariateShiftCRC` → `WeightedEmpiricalSelectiveRouter` (alias kept); code
  and all three paper sources state why Theorem 1 cannot attach (threshold
  rule omits the B/(n+1) term; accepted-conditional loss is not monotone);
  `finite_sample_slack`/`nominal_risk_bound` are documented as informational
  reference values only. All evidence for the component is empirical.
- **R3-02**: `load_seeds()` resolves the episodes path once via
  `REMORA_AROMER_HOME`-aware `state_paths` and passes a concrete path to both
  golden-episode calls; the `Path.home()` fallback is gone. New end-to-end
  test imports the real seed packs under an override home.
- **R3-03**: the stale-claim guard now also scans
  `remora_mathematical_supplement.md`; the supplement's "hallucination-rate
  bound" wording is fixed to the false-consensus-proxy framing, its worked
  CRC example is marked illustrative-only, and the main paper's threshold
  direction ("minimises accepted items") is corrected to maximum coverage.

### Fixed (review round 3, 2026-07-25)

- **F-10 completed**: ALL AROMER default state paths now resolve through
  `remora/aromer/state_paths.py` at call time with `REMORA_AROMER_HOME`
  override — including `DomainHarmPrior` (previously a module-level
  `Path.home()`), the seed loader, the promotion ledger, and the friction
  optimizer; a new test exercises the full persistence graph under the
  override (fixes the four read-only-home failures the re-review found).
- **Paper honesty (second round)**: `h_bound` reframed as a heuristic
  false-consensus risk proxy (not a mathematical bound); χ OOD use marked
  exploratory; "Seven hard blocks" → seven headline controls with a pointer
  to the full gate inventory; λ=0.3 documented as paper config vs library
  default 1.0; remaining "no tagged release" text fixed.
- **Stale-claim CI guard**: `tests/test_paper_no_stale_claims.py` fails if
  superseded values or withdrawn formulations re-enter either paper source
  (caught one live leftover on its first run).
- **Postgres operational evidence**: new CI job runs the DSN-gated tenant-
  chain contract tests (including the F-04 HMAC signing test) against a real
  postgres:16 service and fails if they skip.
- **Request IDs**: full uuid4 hex suffix (was 12 hex chars).
- **Contributors**: Erlend Barli (erlendbarli) added to CONTRIBUTORS.md and
  the paper acknowledgements.

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
