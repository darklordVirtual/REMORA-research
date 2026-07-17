# REMORA + AROMER Documentation Drift Report

> **ARCHIVED — historical document.** Superseded; preserved as record only. Do not cite as current. Current documentation index: [`../README.md`](../README.md).


**Generated:** 2026-06-04  
**Commit audited:** cc567fc  
**Auditor scope:** README.md, NEGATIVE_RESULTS.md, docs/claim_register.md, paper/whitepaper.md, docs/agentharm_trimode_benchmark.md, docs/go_star_bridge.md, artifacts/*.json, key source files.

**Priority scale:**
- **P0** — Dangerous or misleading: could cause external parties to over-trust safety claims or misinterpret results
- **P1** — Important: materially affects how results should be cited or understood
- **P2** — Cleanup: technically correct but incomplete or easy to misread
- **P3** — Cosmetic: minor precision or consistency issues

---

## Documentation Issues

| # | File | Problem | Evidence | Recommended Fix | Priority |
|---|---|---|---|---|---|
| D-001 | `README.md` (AROMER section, results table) | "Full REMORA gate: **0.977** | **0.023**" without explaining that 0.977 is blocked_recall (ESCALATE+VERIFY), not ESCALATE-only recall (0.114). A reader scanning the table could interpret 0.977 as the fraction of harmful cases that were hard-blocked. | `artifacts/agentharm_trimode_results.json`: `modes.mode3_remora_gate_m2_input.recall=0.1136`, `blocked_recall=0.9773` | Add footnote or inline note clarifying: "blocked_recall = ESCALATE + VERIFY; ESCALATE-only recall = 0.114" | P0 |
| D-002 | `README.md` (AROMER section, "Zero false negatives" claim) | "Zero false negatives across all 8 harm categories" is stated without the critical qualifier that this applies only to Mode 1 and Mode 2, not Mode 3 (which has FN=39). A reader reading Mode 3 results could assume zero false negatives persists. | `artifacts/agentharm_trimode_results.json`: `modes.mode3_remora_gate_m2_input.FN=39` | Rewrite to: "Zero false negatives in Mode 1 and Mode 2 oracle passes. Mode 3 routes 39/44 harmful cases to VERIFY (not hard-blocked), which are counted as FN under strict ESCALATE-only definition." | P0 |
| D-003 | `README.md` (AROMER section, cross-domain claim) | "Cross-domain replay benchmark (65 factory cases)" header but only 32 cases are domain benchmark cases (artifacts/domain_benchmark_results.json). The 65 count is the replay factory benchmark (artifacts/replay_benchmark.json). These two benchmarks are conflated in the section header. | `artifacts/domain_benchmark_results.json`: total=32 (cyber=12, ai_governance=10, finance=10). `artifacts/replay_benchmark.json`: total_episodes=65 | Separate the two benchmarks clearly: "Factory replay benchmark (65 cases): ..." and "Cross-domain evidence benchmark (32 cases): ..." | P0 |
| D-004 | `README.md` (AROMER section, oracle bandit claim) | "Oracle bandit (Thompson Sampling): cf_strong 98.8%, cf_fast 97.6%" presented as factual performance data without clarifying these are Thompson Sampling posteriors derived from self-labeled episode data, not independently validated model quality metrics. | `remora/aromer/integration/bridge.py`: OracleBandit Thompson Sampling; auto-label hook creates systematic benign-labeling bias | Add: "These are Thompson Sampling posterior means from self-labeled episode data. Not independently validated." | P1 |
| D-005 | `README.md` (AROMER section, world model claim) | "Bayesian world model: 44 contexts tracked, updating from outcomes" states a specific count that: (a) comes from live worker state, not a committed artifact, (b) may include mostly LOW-confidence contexts (n<5), and (c) is in shadow mode by default (adjustments computed but not applied). | `remora/aromer/orchestrator.py` line 95: `world_model_shadow_mode: bool = True`; `domain_prior.py`: LOW confidence for n<5 | Add: "(shadow mode active by default — adjustments computed but not applied; most contexts likely have LOW confidence n<5)" | P1 |
| D-006 | `README.md` (Benchmarks at a glance table) | The benchmarks table mixes multiple benchmark types (QA selective, stress replay, AgentHarm) without scope labels. The "700 tasks" stress replay and "N500 selective routing" results are simulator/curated benchmarks that predate the AgentHarm work but appear in the same table, making it look like a unified evaluation. | `paper/whitepaper.md` sections 4.1-4.7 show these are distinct benchmark artifacts with different scopes | Add scope labels in the table (e.g., "[QA benchmark]", "[simulator]", "[curated factory]") | P1 |
| D-007 | `README.md` (AROMER section) | "AROMER quality gate: FA rate=0.000, 200+ episodes processed" appears in the task prompt context but has no backing committed artifact. No artifact in `artifacts/` records this figure. | `remora/aromer/experience/store.py`: store summary API has false_accept_rate field but no static artifact captures 0.000 / 200+ | Remove this specific claim or replace with: "FA rate and episode count are from live worker state; not statically verifiable from committed artifacts." | P1 |
| D-008 | `docs/agentharm_trimode_benchmark.md` | The document is accurate and well-caveated but does not prominently note that the live oracle benchmark (`artifacts/live_benchmark_results.json`) shows dramatically lower directional precision (0.480 overall) than the AgentHarm static benchmark suggests. These should be cross-referenced. | `artifacts/live_benchmark_results.json`: overall directional precision=0.48 vs static benchmark escalation_recall=1.000 | Add a note: "Note: the live oracle benchmark on the same 32-case domain set shows overall oracle directional precision=0.480 (ai_governance=0.250, finance=0.250), indicating the static evidence provider and live LLM oracle do not agree on most non-cyber cases." | P1 |
| D-009 | `paper/whitepaper.md` (Abstract, third claim) | "REMORA now includes structural governance primitives for long-running agents" is accurate but the word "now" suggests these are new. The limitations section correctly notes they are "not yet validated on live enterprise telemetry" but this caveat is separated from the claim. | `paper/whitepaper.md` Section 7: limitation 1 and limitation 7 acknowledge no production deployment | Move the validation caveat closer to the claim in the abstract, or add an inline qualifier: "(structural and unit-tested; no deployment telemetry available)" | P2 |
| D-010 | `paper/whitepaper.md` | The whitepaper title references "Multi-oracle consensus, selective trust, tool-call gating, and memory governance for long-running AI systems" but no deployed long-running AI system exists to validate the memory governance layer. The title implies broader validation than the work supports. | `paper/whitepaper.md` Section 7 limitation 7: "Governance thresholds are uncalibrated for real deployments." | Consider softening to "...architecture for long-running AI systems" to signal the work is architectural/design, not empirical validation in production. | P2 |
| D-011 | `README.md` (live demo links) | Live links (`remora.razorsharp.workers.dev`) are presented as "Live:" but there is no guarantee they remain live for external reviewers. A dead link at evaluation time undermines credibility. | README.md line 29 | Add "(requires active CF Worker deployment)" or equivalent caveat, and ensure links are checked periodically in CI. | P2 |
| D-012 | `docs/claim_register.md` | The claim register references `docs/thermodynamics/claim_ledger.yaml` as the "source of truth" but this audit could not verify that file is current or aligned with the AROMER-era additions (AgentHarm, replay benchmark, world model). | `docs/claim_register.md` lines 9-10, 123: references claim_ledger.yaml as canonical source | Audit `docs/thermodynamics/claim_ledger.yaml` and add AROMER-era claims to it, or note that the JSON register at `artifacts/remora_aromer_claim_register.json` supersedes it for AROMER claims. | P2 |
| D-013 | `README.md` (Benchmarks caveats section) | The caveats section includes "The hallucination bound is a candidate hallucination-bound proxy and an implemented research heuristic" — this language is from earlier REMORA versions and predates the AgentHarm/AROMER work. It may confuse readers who are not familiar with the older architecture. | README.md lines 166-177 | Consider moving legacy benchmark caveats to a dedicated versioned section or to the NEGATIVE_RESULTS archive. | P2 |
| D-014 | `docs/go_star_bridge.md` | The document describes `remora.integrations.gostar` (GoStarFinding, OracleSignal, Severity) as if it exists, with a Python code example. This integration module was not verified to exist in the repository during this audit. | README.md and code audit: `remora/integrations/` directory not directly verified | Verify `remora/integrations/gostar.py` exists and is tested, or mark the code example as "forthcoming / not yet implemented." | P2 |
| D-015 | `NEGATIVE_RESULTS.md` | The Resolved Findings Archive references R10 ("χ-proxy difficulty signal below chance, AUC=0.39") as resolved by "repurposing to OOD/adversarial escalation." This is a significant architectural decision that is not cross-referenced in the current whitepaper or AROMER documentation. | `NEGATIVE_RESULTS.md` line R10 | Add a cross-reference in docs to clarify how the χ signal is currently used, or note it is from pre-AROMER architecture. | P3 |
| D-016 | `README.md` (Benchmarks at a glance) | The "Selective routing can be accurate under abstention: 88.0% at 23.2% coverage" result cites "held-out N500 split, n_accepted=25, wide CI" but the CI is not stated inline. Readers could cite the 88.0% without understanding the wide CI from n=25. | `results/selective_n500_holdout_results.json` (per README cross-reference) | Add the Wilson CI inline: "88.0% at 23.2% coverage [wide CI; n_accepted=25]" | P2 |
| D-017 | `README.md` (Implementation status table) | "Multi-oracle governance engine: Implemented" — the three Workers AI oracle models are the go-star-remora worker, not a local multi-oracle engine. The local RemoraDecisionEngine accepts a single PolicyObservation (post-oracle-aggregation). The claim of "multi-oracle" is accurate for the full system but misleading about what runs locally vs. in CF Workers. | `remora/policy/decision_engine.py`: single PolicyObservation input; workers/go-star-remora handles multi-oracle consensus | Clarify: "Multi-oracle consensus (Workers AI): Implemented as CF Worker; Local policy engine: Implemented as Python library accepting pre-aggregated oracle signals." | P2 |
| D-018 | `README.md` (AROMER "Live log" link) | "Live log: https://aromer.razorsharp.workers.dev/log?format=text" — the log contains real tool-call data from Claude Code sessions including development commands. Privacy and security implications of a public log of agent tool calls are not documented. | `.claude/settings.json`: all tool calls recorded via aromer_recorder_hook.py | Add a note about what the live log contains and any PII/operational security considerations for the public log endpoint. | P1 |
| D-019 | `paper/whitepaper.md` (Section 3.5, review states) | The section describes a rich human review workflow (PENDING_REVIEW, FOLLOW_UP_REQUIRED, SITE_VERIFICATION_PENDING, etc.) with the caveat "This is a deterministic GUI demonstration." This workflow architecture is presented in technical detail but has no deployment evidence. Evaluators may overestimate implementation maturity. | `paper/whitepaper.md` line: "This is a deterministic GUI demonstration." | The caveat is present but should be more prominent. Consider adding a visible callout box or bold note at the start of Section 3.5. | P2 |
| D-020 | `docs/claim_register.md` | The claim register says "docs/thermodynamics/claim_ledger.yaml is source of truth" but the AROMER section of README claims results that do not appear to be registered in the original claim taxonomy (aspirational/empirical/etc.). The AROMER evidence layer (cyber, ai_governance, finance domain benchmarks) and AgentHarm results should be formally registered. | `docs/claim_register.md`: no AROMER-specific entries visible | Add AROMER-era claims to claim_ledger.yaml with appropriate status labels (empirical/internal, simulator_only, etc.) and cross-reference the three benchmark artifacts. | P1 |

---

## Summary Statistics

| Priority | Count | Resolved (2026-06-09) |
|---|---|---|
| P0 (Dangerous/Misleading) | 3 | **3** — D-001 (inline †), D-002 (Mode qualifier), D-003 (benchmarks separated) |
| P1 (Important) | 7 | 0 |
| P2 (Cleanup) | 8 | 1 — D-014 (gostar module verified) |
| P3 (Cosmetic) | 1 | 0 |
| **Total** | **19** | **4 resolved; 15 open** |

---

## Top Priority Fixes

### P0 fixes required before any external citation

1. **D-001:** Clarify that blocked_recall=0.977 includes VERIFY, and ESCALATE-only recall=0.114.
2. **D-002:** Qualify "zero false negatives" to Mode 1 and Mode 2 only.
3. **D-003:** Separate the 65-case factory replay benchmark from the 32-case domain evidence benchmark in the README results table.

### P1 fixes required before broader publication

4. **D-004:** Label oracle bandit win-rates as self-labeled posterior estimates.
5. **D-005:** Note world model shadow mode default and confidence level implications.
6. **D-007:** Remove or qualify the FA rate=0.000 / 200+ episodes claim without artifact backing.
7. **D-008:** Cross-reference the live oracle benchmark (0.480 directional precision) in the trimode benchmark document.
8. **D-018:** Document privacy/security implications of the public live tool-call log.
9. **D-020:** Register AROMER-era claims in claim_ledger.yaml.

---

## Documents That Should Be Archived or Superseded

| Document | Reason |
|---|---|
| Legacy selective-routing and QA benchmark caveats in README benchmarks section | These predate the AgentHarm/AROMER work and mix two unrelated benchmark families. Consider moving to a versioned results archive. |

---

## Resolved Issues (2026-06-09)

| # | Fix | Commit area |
|---|---|---|
| D-014 | `remora/integrations/gostar.py` verified to exist and be tested. No longer a gap. | Verification |
| — | `remora/toolcalls/` (forlatt duplikatpakke) slettet. | Kodebase |
| — | `remora/causality.py` og `causality_v2.py` wrappers slettet; tester migrert til `remora.counterfactual`. | Kodebase |
| — | `AuditBlock` utvidet med `tool_args_hash` (SHA-256 av assessed action). Felt dokumentert med roadmap-gaps (OIDC, KMS, RFC 3161) i docstring. Schema og `to_flat_dict` oppdatert. | `remora/governance/envelope.py`, `servers/api.py` |
| — | `servers/api.py` docstring oppdatert fra "2 endpoints" til komplett liste over 11 endpoints. | `servers/api.py` |
| — | `CLAUDE.md` fikset: `INTERCEPTION_NOTES.md` → korrekt sti `experiments/agentharm/INTERCEPTION_NOTES.md`. | `CLAUDE.md` |
| — | `PhaseAwareGuardrail` 22.1%/84.2%-påstand fikset: backing-artefakt `results/phase_aware_guardrail_n544_results.json` generert. Docstring oppdatert med artefakt-baserte tall (85.0%) og metodikk-note. | `remora/selective/guardrail.py`, ny artefakt |
| — | `sqlglot` lagt til `dev`-avhengigheter; 3 skippede SQL AST-guard-tester er nå aktive. | `pyproject.toml` |
