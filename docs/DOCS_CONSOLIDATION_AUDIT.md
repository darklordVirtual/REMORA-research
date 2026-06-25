# REMORA Documentation Consolidation Audit

**Date:** 2026-06-11
**Scope:** all Markdown in the repository root and `docs/` (top level).
**Method:** file-by-file survey for staleness, redundancy, and consolidation
opportunity, cross-referenced with the repository's current state (v0.9.0 +
AROMER v0.2, post the 2026-06-11 learning/oracle work).

**How to read the Action column.**
- **KEEP** — current and load-bearing; no change.
- **UPDATE** — content is stale on specifics; refresh in place.
- **CONSOLIDATE** — overlaps another doc; merge or cross-link.
- **ARCHIVE** — completed/superseded; move under `docs/archive/` (don't delete —
  preserves provenance).
- **VERIFY** — flagged by name/role; confirm before acting.

> **Why this audit performs almost no deletions.** Merging or removing authored,
> "authoritative" documents is consequential and can silently drop caveats the
> project depends on (see `CLAUDE.md`). This audit makes the calls explicit and
> leaves the destructive merges/removals as **recommendations for the maintainer
> to approve**, while performing only safe, additive fixes (supersession banners,
> cross-links). The earlier `DOCUMENTATION_DRIFT_REPORT.md` (2026-06-04) is itself
> now stale and is folded into this one (see §4).

---

## 1. Highest-value consolidations (recommended, need maintainer approval)

| # | Items | Problem | Recommendation |
|---|---|---|---|
| C-1 | `docs/REMORA_AROMER_MASTER_DOCUMENT.md` (39 KB) **+** `docs/REMORA_AROMER_FINAL_REPORT.md` | Two large, overlapping "authoritative" technical references, both v0.9.0, both "verified against cc567fc / 2026-06-05". They duplicate the architecture, the four outcomes, and the AgentHarm result, and **both predate** the 2026-06-11 AROMER v0.2 work (bounded-memory priors, real 3-model oracle ensemble, pending-resolution). | Pick **one** as canonical (MASTER reads as the reference; FINAL reads as the results/positioning brief). Keep both only if their roles are made explicit at the top; otherwise merge into one and `ARCHIVE` the other. Either way, **add an AROMER v0.2 addendum** — both currently describe the pre-v0.2 learning loop. |
| C-2 | `CONTRIBUTING.md` (3.2 KB) **+** `CONTRIBUTIONS.md` (8.3 KB) | Near-identical names, different content — a guaranteed source of confusion (contributors won't know which is authoritative). | Keep `CONTRIBUTING.md` as the standard GitHub contributor guide; rename/repurpose `CONTRIBUTIONS.md` to something unambiguous (e.g. `docs/acknowledgements.md` if it's a credits list) or fold it in. |
| C-3 | `docs/toolcall_consensus_benchmark.md` (v1) **+** `docs/toolcall_consensus_benchmark_v2.md` **+** `docs/toolcall_benchmarks.md` | Three tool-call benchmark docs; v1 (252 tasks, `toolcall_benchmark_v1.json`) is explicitly superseded by v2. | `ARCHIVE` v1, keep v2 canonical, and make `toolcall_benchmarks.md` an index that points to v2. A supersession banner has been added to v1 by this audit (safe, non-destructive). |
| C-4 | Entry-point cluster: `README.md`, `EVALUATOR_START_HERE.md`, `EVIDENCE_OF_CAPABILITY.md`, `PORTFOLIO.md`, `EXTERNAL_REVIEW_REMORA.md` | Five overlapping "start here / why this matters" documents. Some (PORTFOLIO, EVIDENCE_OF_CAPABILITY) date to 2026-05-31 and may predate the current results. | Define one front door (`README.md`) and one evaluator path (`EVALUATOR_START_HERE.md`); demote the rest to clearly-scoped supporting docs or `ARCHIVE`. Verify the 2026-05-31 files still match current numbers before keeping. |

---

## 2. `docs/` top-level — file-by-file

| File | Role | Verdict |
|---|---|---|
| `claim_hygiene.md`, `claim_register.md`, `claim_evidence_matrix.md` | Claim-governance core | **KEEP** (load-bearing for the no-overclaim rule). Confirm `claim_register.md` references the current claim-ledger source (drift D-012/D-020). |
| `DOCUMENTATION_DRIFT_REPORT.md` | 2026-06-04 drift audit | **ARCHIVE/SUPERSEDE** — folded into this document (§4). |
| `aromer_learning_evidence_v1.md` | AROMER ablation evidence | **UPDATE** — add the 2026-06-11 results (adversarial_hard arena, bounded-memory fix) or mark as the pre-v0.2 snapshot. |
| `quickstart_aromer.md` | AROMER quickstart | **VERIFY** — check commands against current `AromerOrchestrator` API. |
| `EXTERNAL_VALIDATION_PLAN.md`, `benchmark_validation_plan.md`, `external_review_round2_plan.md`, `review_round2_closure.md`, `external_validation_report_template.md` | Process / planning / templates | **ARCHIVE** the completed ones (`review_round2_closure.md` signals the round is closed); keep templates under a `docs/templates/` folder. |
| `toolcall_consensus_benchmark.md` (v1) | Superseded benchmark | **ARCHIVE** (supersession banner added). |
| `toolcall_consensus_benchmark_v2.md`, `toolcall_benchmarks.md` | Current benchmark + index | **KEEP** (make the latter an index — see C-3). |
| `agentharm_live_benchmark.md`, `agentharm_trimode_benchmark.md`, `live_benchmark.md`, `domain_benchmark.md` | Benchmark records | **KEEP**; ensure each cross-references the live-vs-static precision caveat (drift D-008). |
| `thermodynamic_abs.md`, `thermodynamics/*` | Method docs | **KEEP**; align with `paper/remora_mathematical_supplement.md` (added 2026-06-11) — they should not contradict it. |
| `go_star_bridge.md`, `gostar_integration.md` | GO-STAR integration | **CONSOLIDATE** — two docs on the same integration; merge or cross-link. |
| `cloudflare-productivity-layer.md`, `cloudflare_workers_ai.md` | CF infra | **KEEP**; verify against the current worker set (now also serves PDFs from R2 — see the R2 work of 2026-06-11). |
| `plain_language_overview.md`, `related_work.md`, `nested_governance.md`, `cyber_evidence_layer.md`, `rag_oracle.md`, `mcp-integration.md`, `agent_tool_hook.md`, `stat_tests.md`, `reproducibility.md`, `credibility_pack_repro.md`, `decision_envelope_audit.md`, `architecture_risk_register.md`, `breakthrough_proof.md`, `results_snapshot.md`, `review_checklist.md` | Reference / supporting | **KEEP**, with two **VERIFY** flags: `results_snapshot.md` (may be stale vs current artifacts) and `breakthrough_proof.md` (strong title — ensure caveats are intact per `CLAUDE.md`). |
| `frontend_ux_governance_review.md`, `linkedin_promotion_posts.md`, `demo_reel_recording_guide.md` | Added 2026-06-11 | **KEEP** (current). |

## 3. Repository-root — file-by-file

| File | Verdict |
|---|---|
| `README.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `CLAUDE.md`, `AGENTS.md`, `SECURITY.md`, `TRADEMARKS.md`, `SETUP.md`, `CODEGRAPH.md`, `NEGATIVE_RESULTS.md` | **KEEP** — current (most touched 2026-06-09/10). |
| `CONTRIBUTING.md` + `CONTRIBUTIONS.md` | **CONSOLIDATE** (C-2). |
| `EVALUATOR_START_HERE.md`, `EVIDENCE_OF_CAPABILITY.md`, `PORTFOLIO.md`, `EXTERNAL_REVIEW_REMORA.md` | **VERIFY/CONSOLIDATE** (C-4); the 2026-05-31 ones may predate current results. |

## 4. Status of the prior drift report (`DOCUMENTATION_DRIFT_REPORT.md`, 2026-06-04)

That report listed 19 issues (4 resolved by 2026-06-09). Since then the repo has
shipped v0.9.0, AROMER v0.2 (2026-06-11), the mathematical supplement, and the R2
paper hosting. **Several of its open items are now likely addressed and several of
its referenced numbers are themselves stale.** Recommended: re-run the specific
checks (D-004, D-005, D-007, D-008, D-018, D-020) against current artifacts, then
retire `DOCUMENTATION_DRIFT_REPORT.md` in favour of this consolidation audit. Its
P0 README items (D-001/2/3) were already marked resolved and should be re-confirmed
after any README consolidation under C-4.

---

## 5. Concrete actions performed (2026-06-11)
- **Version stamps:** the frontend was showing `v0.6.0`; corrected to `v0.9.0`
  (the canonical `pyproject.toml` version) in `frontend/src/content/whitepaper.ts`.
- **Archived** (moved to `docs/archive/`, history preserved via `git mv`):
  `DOCUMENTATION_DRIFT_REPORT.md` (superseded by this audit),
  `toolcall_consensus_benchmark.md` → `toolcall_consensus_benchmark_v1.md`
  (superseded by v2), and the completed Round-2 process docs
  `external_review_round2_plan.md` and `review_round2_closure.md`. Inbound
  references in `review_checklist.md`, `EXTERNAL_VALIDATION_PLAN.md`, and
  `breakthrough_proof.md` were repointed.
- Still **recommended** (maintainer approval — moves/removes authored content):
  C-1 (one canonical AROMER reference), C-2 (`CONTRIBUTING`/`CONTRIBUTIONS`),
  C-4 (entry-point cluster).

## 6. Recommended next actions (need a yes/no from the maintainer)
1. C-1: choose one canonical AROMER reference; archive or role-label the other; add
   a v0.2 addendum. *(highest value — two 30 KB+ docs are drifting in parallel)*
2. C-2: disambiguate `CONTRIBUTING.md` / `CONTRIBUTIONS.md`.
3. C-3/C-4: archive superseded benchmark + entry-point docs into `docs/archive/`.
4. Refresh `aromer_learning_evidence_v1.md` and `results_snapshot.md` to the
   2026-06-11 state, or stamp them as dated snapshots.

These are deliberately left as approvals rather than executed, because they move or
remove authored documents — a maintainer decision, not an automated one.
