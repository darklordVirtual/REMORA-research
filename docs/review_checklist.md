# REMORA External Review Checklist

## Scope

Use this checklist for academic review, security-oriented technical review, and
commercial technical diligence.

Round-2 execution plan reference:

- `docs/archive/external_review_round2_plan.md`

## Reproducibility

1. Run `make audit` (canonical reviewer gate).
2. Run `make credibility-pack` to generate handoff bundle in `artifacts/credibility-pack/`.
3. Run `python -m pytest tests/ -q` if an isolated test-only rerun is required.
4. Regenerate tool-call artifacts:
   - `python experiments/generate_toolcall_benchmark.py`
   - `python experiments/evaluate_toolcall_benchmark.py`
   - `python experiments/toolcall_ablation.py`
   - `python experiments/generate_toolcall_benchmark_v2.py`
   - `python experiments/evaluate_toolcall_benchmark_v2.py`
   - `python experiments/toolcall_ablation_v2.py`
   - `python experiments/toolcall_v2_significance.py`
5. Regenerate N500 policy artifact:
   - `python experiments/end_to_end_n500_v3.py`
6. Regenerate documentation consistency audit:
   - `python experiments/claim_consistency_audit.py`
7. Confirm regenerated outputs match committed files in `results/` and `artifacts/`.
8. Confirm the Round-2 entry criteria in `docs/archive/external_review_round2_plan.md` are satisfied before handoff.

## Claim Integrity

1. For each claim in `docs/thermodynamics/claim_ledger.yaml`:
   - verify referenced artifact exists
   - verify referenced test exists and passes
   - verify wording matches measured values
2. Confirm `not_demonstrated` claims are retained and visible.
3. Confirm `results/claim_consistency_audit.json` reports `all_passed=true`.
4. Confirm no README or docs statement exceeds claim ledger scope.

## Tool-Call Safety Evaluation

1. Confirm all task domains are deterministic dry-run domains.
2. Confirm no simulator executes real commands or mutates real systems.
3. Confirm all baselines are explicitly heuristic and deterministic.
4. Confirm benchmark limitations are explicit in:
   - `results/toolcall_benchmark_v1_results.json`
   - `docs/toolcall_consensus_benchmark_v2.md`
   - `README.md`

## Shadow Replay Overlay Review

1. Run `make shadow-replay INPUT=artifacts/demo/shadow_mode_sample_agent_action_log.jsonl`.
2. Confirm output files exist:
   - `artifacts/shadow_mode/decision_envelopes.jsonl`
   - `artifacts/shadow_mode/governance_delta_report.json`
   - `artifacts/shadow_mode/replay_audit.jsonl`
3. Confirm baseline comparisons include:
   - `no_gate`
   - `majority_vote`
   - `single_judge`
   - `confidence_threshold`
   - `policy_only_gate`
   - `remora_full`
4. Confirm replay caveat is explicit: unsafe labels come from benchmark dataset labels, not live ground-truth execution.

## Policy Layer Review

1. Confirm hard blocks precede acceptance paths in `remora/policy/decision_engine.py`.
2. Confirm contradiction logic:
   - non-zero contradictions block acceptance
   - `None`/`0` behavior matches tests
3. Confirm `DecisionReport` provenance fields:
   - `source_of_decision`
   - `policy_version`
   - `in_sample_calibration_warning`

## Control-Plane API Review

1. Confirm endpoints exist and return expected schema:
   - `POST /v1/assess`
   - `GET /v1/envelope/{request_id}`
   - `GET /v1/audit/{request_id}`
   - `POST /v1/review`
   - `POST /v1/follow-up`
   - `GET /v1/metrics`
   - `GET /metrics`
2. Confirm tenant scoping is enforced via `X-Remora-Tenant`.
3. Confirm bearer auth behavior with and without `REMORA_API_BEARER_TOKEN`.
4. Confirm metrics include assess/review/follow-up counters.
5. Confirm OpenAPI docs from FastAPI align with README endpoint documentation.

## Persistence and Auditability Review

1. Confirm control-plane storage backends are available:
   - `InMemoryControlPlaneStore`
   - `PostgresControlPlaneStore`
2. Confirm decision persistence is append-only/versioned (no in-place overwrite).
3. Confirm latest-read behavior returns newest version while historical versions are retained.
4. Confirm tenant isolation in storage keys/queries.
5. Confirm review/follow-up records are persisted with timestamp and tenant id.

## Evidence Layer Review

1. Confirm `EvidenceVerifierProtocol` exists and default verifier is lexical.
2. Confirm no semantic-entailment claim is made without implementation.
3. Confirm custom verifier behavior is tested.
4. Confirm `docs/gostar_integration.md` states that GO-STAR scanner internals
   are closed-source and that public REMORA claims cover only the bridge
   contract and tests.

## Cascade Pipeline Review

1. Confirm `remora/cascade/` contains `engine.py`, `stages.py`, `result.py`.
2. Confirm Stage 1 (`FastGate`) exits on verbalized confidence ≥ 0.90.
3. Confirm Stage 2 (`ConsensusGate`) wraps `remora.engine.Remora` with thermodynamic phase classification.
4. Confirm Stage 3 (`VerifierGate`) uses a judge oracle from a different model family than consensus oracles.
5. Confirm Stage 3b (`CritiqueRevisionGate`) implements the Constitutional AI pattern (judge → revision → re-judge, max 2 rounds).
6. Confirm Stage 4 (`SelfConsistencyGate`) uses 7 samples with 0.72 agreement threshold and is terminal unless Stage 6 (`MixtureOfAgentsSynth`) is enabled.
7. Confirm optional Stage 6 (`MixtureOfAgentsSynth`) runs after Stage 4 VERIFY outcomes when a `synthesis_oracle` is configured.
8. Confirm `budget_oracle_calls` halts the pipeline and returns VERIFY (not a forced answer) when exhausted.
9. Confirm `ARCHITECTURE.md` Cascade Pipeline section matches current `stages.py` thresholds.

## Enterprise Catalog Review

1. Confirm `enterprise/` directory contains all 15+ architecture and design documents.
2. Confirm `enterprise/risk-profiles.yaml` and `enterprise/policy_as_code_example.yaml` are valid YAML.
3. Confirm `enterprise/audit-ledger-schema.sql` contains row-level security and immutability rules.
4. Confirm `enterprise/threat-model.md`, `enterprise/production-readiness.md`, `enterprise/deployment-runbook.md` exist and are non-empty.
5. Confirm `enterprise/executive-brief.md` "Current state" table accurately reflects completed vs. designed vs. not-built items.
6. Confirm `paper/future_state.md` speculative disclaimer is present at the top of the file.

## Documentation Quality

1. README serves three audiences:
   - non-technical reader
   - technical reviewer
   - commercial evaluator
2. Ensure all key numbers in README/docs match artifacts.
3. Ensure limitations are concrete, not generic.
4. Confirm `docs/figures/` contains all 7 benchmark PNG files.
5. Confirm `ARCHITECTURE.md` Cascade Pipeline section is present and accurate.
6. Confirm `docs/architecture_risk_register.md` covers live evidence quality,
   oracle-swarm cost/latency, canonicalization brittleness, correlated oracle
   failure, and simulator-scoped tool-call safety.

## Round-2 Closure

1. Confirm all critical/high findings have owner and due date.
2. Confirm residual-risk ledger entries are recorded and accepted explicitly.
3. Confirm closure note is published (`docs/review_round2_closure.md`).

## Commercial Diligence Readiness

1. Confirm risk posture language is conservative and explicit.
2. Confirm deployment claims are bounded to research status.
3. Confirm roadmap to harder benchmark (`toolcall_benchmark_v2`) is documented.
4. Confirm N500 in-sample calibration warning appears in both README and ARCHITECTURE.md.
5. Confirm tool-call v2 deterministic-simulator scope is disclosed in README, ARCHITECTURE.md, and executive brief.
