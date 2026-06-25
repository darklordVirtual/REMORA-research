# REMORA External Validation Plan

This plan defines how REMORA should be externally validated in a reviewer-facing cycle.

## 1. Validation Goals

1. Verify governance controls behave as documented under realistic risk tiers.
2. Verify benchmark claims are reproducible and clearly scoped to benchmark conditions.
3. Verify audit and replay outputs are tamper-evident and externally inspectable.
4. Verify production fail-closed behavior for auth, persistence, and oracle backend config.

## 2. Scope

In scope:

- Governance API endpoints (`/v1/assess`, `/v1/policy/version`, `/v1/evidence`, `/v1/rerun`)
- Policy gate behavior for high/critical actions
- DecisionEnvelope schema contract and audit metadata
- Benchmark and credibility artifact generation

Out of scope (for this cycle):

- Claims of production certification
- Vendor-specific SLA claims
- Full red-team coverage beyond documented benchmark/adversarial suites

## 3. Required Environment

- Python 3.11+
- Clean checkout of pinned commit SHA
- Optional: FastAPI dependencies for API contract tests
- For production-mode checks:
  - `REMORA_ENV=production`
  - `REMORA_API_BEARER_TOKEN=<token>`
  - `REMORA_CONTROL_PLANE_DSN=<dsn>`
  - `REMORA_ORACLE_BACKEND=<non-mock backend>`

## 4. Validation Procedure

Run in order:

```bash
make audit
make benchmark-package
make credibility-pack
make external-review
python scripts/check_claim_sync.py
```

If FastAPI test dependencies are available:

```bash
pytest -q tests/test_api_server.py
```

If replay-heavy checks are enabled in the environment:

```bash
pytest -q -m live_replay_heavy \
  tests/test_toolcall_live_exec_results.py \
  tests/test_toolcall_live_cache_replay.py
```

## 5. Acceptance Criteria

All must pass:

1. `make external-review` exits successfully.
2. `/v1/policy/version` returns hash metadata (`policy_hash`, `risk_profile_hash`, `schema_hash`).
3. Assess/rerun envelopes include audit hash chain (`hash`, `previous_hash`) and optional signature when signing key is configured.
4. Rerun response reports determinism checks and stable policy hash presence.
5. Claim-language checks pass with benchmark-qualified wording.

## 6. Evidence Package for Reviewers

Deliver at minimum:

- `artifacts/governance-benchmark-pack/manifest.json`
- `artifacts/governance-benchmark-pack.zip`
- `artifacts/credibility-pack/`
- `docs/archive/external_review_round2_plan.md`
- `docs/archive/review_round2_closure.md`
- `docs/EXTERNAL_VALIDATION_PLAN.md`

## 7. Reporting Template

For each validation cycle include:

1. Commit SHA validated
2. Command transcript
3. Pass/fail summary
4. Any deviations and justification
5. Residual risks accepted with owner/date

## 8. Residual Risks to Track

1. Synthetic benchmark assumptions versus live deployment behavior.
2. Retrieval quality limits for non-semantic evidence stores.
3. External oracle variability by backend/model version.
4. Operational constraints for production persistence and key management.
