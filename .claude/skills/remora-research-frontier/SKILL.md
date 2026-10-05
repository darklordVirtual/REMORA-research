---
name: remora-research-frontier
description: Use when touching REMORA code, docs or registers that cite research, when asked which paper grounds a mechanism, when proposing a new sensor/protocol/benchmark, when writing related-work or prior-art text, when wording a status (ABSENT/PARTIAL/ESTABLISHED, library_only, positioning_only), or when asked "hva sier forskningsfronten", "er X implementert", "prior art for Y", "hvilken benchmark bør vi kjøre".
---

# remora-research-frontier

Fast path from a research question to the committed truth in this repo, plus
the frontier literature the repo does not yet record. The registers are the
truth; this skill is an index and a reading list. Nothing here is evidence.
Snapshot: master `fea7928`, 2026-10-04. If `git log -1` is newer, re-grep
before quoting any status from the sibling files.

## Where truth lives (open these, in this order)

| Question | Canonical file | Gate |
|---|---|---|
| Is method X implemented, and how mature? | `docs/research/research_control_matrix_v1.yaml` (RES-001..021, `maturity`, `code`, `tests`, bibliography with `role`) | `check_claim_provenance.py` |
| Is paper Y adopted, scoped or declined? | `docs/research/research_shelf_v1.yaml` (SHELF-001..041, `adoption`, `verification`) | `check_research_shelf.py` |
| What is the planned work package? | `docs/13-research-frontier-roadmap.md` (RF-01..13, §0 coverage, §11 excluded, §12 intake) | prose ratchet |
| What number may I quote? | `docs/assurance/claim_register_v1.yaml` (CLAIM-001..020) + `docs/assurance/evidence_levels.md` | `check_claim_sync.py`, `check_no_overclaims.py` |
| What was tried and failed? | `NEGATIVE_RESULTS.md` (open / accepted / superseded tables near the end) | `check_negative_results_status.py` |
| Which concepts does REMORA claim priority on, and what is their prior-art status? | `docs/assurance/provenance_concepts_v1.yaml` (PROV-01..17) and the ledger `provenance/` (`concepts/PROV-xx.yaml`, `PRIOR_ART.yaml`, `EXTERNAL_ADOPTION.yaml`, `POLICY.yaml`) | `build_provenance_manifest.py --check`, `check_provenance_signatures.py` |
| How does REMORA compare to the nearest system? | `docs/benchmarks/aegis-remora-crosswalk.md`, `docs/research/adjacent-systems-crosswalk-v2.md` | none |
| Narrative related work | `docs/09-related-work.md` (14 sections) | `check_paper_sync.py` |

Compact snapshot of all registers: `register-map.md` (this directory).
Frontier bibliography with verified arXiv IDs and REMORA binding:
`literature.md` (this directory). Prior-art classification per PROV concept:
`prior-art.md` (this directory).

## Status vocabulary (use these words, no others)

- Matrix maturity: `implemented_and_tested`, `empirically_evaluated_adaptation`,
  `conceptual_translation_implemented`, `library_only`, `reference_design`.
- Shelf adoption: `ADOPTED`, `PARTIAL`, `SCOPED`, `PROTOTYPE_ONLY`, `DECLINED`,
  `UNEVALUATED`. Source verification: `VERIFIED_RETRIEVED`, `UNVERIFIED`,
  `RETRIEVAL_FAILED`, `INTERNAL`.
- Bibliography role: `implemented_line` (code named) vs `positioning_only`
  (argued against or framed, not built on). "Mentioned in the paper" is
  `positioning_only`, never implementation.
- Capability wording: `ESTABLISHED` / `PARTIAL` / `NOT_ESTABLISHED`. A
  mechanism with primitives in code but no end-to-end property is `PARTIAL`.

## Rules that hold on every edit

1. A literature claim about REMORA resolves to `code` + `tests` + a register
   row, or it is written as a proposal. Author-reported numbers stay the
   authors' numbers (`reported_results`), never next to a REMORA number.
2. New paper in: add a shelf entry with `verification: UNVERIFIED` until the
   publisher page is checked, then `VERIFIED_RETRIEVED` with the date. Only
   then may a narrative document cite it. Run
   `python scripts/check_research_shelf.py`.
3. Library-only modules (`control_protocols.py`, `risk_control.py`,
   `confidence_sequence.py`) are not wired into the decision path. Do not
   describe them as runtime behaviour.
4. Accepted negative results are closed to tuning. Check the "Accepted" table
   in `NEGATIVE_RESULTS.md` before proposing a fix for §18 (temperature), §19
   (AgentHarm FBR), §20 (registry coverage), §57 (ablation).
5. Prior art: every PROV record is `classification: UNKNOWN` and
   `claimed_original_contribution` until a dated `PA-REV-xxx` review in
   `provenance/PRIOR_ART.yaml` names the works compared, the overlap, the
   difference and the one sentence the contribution is limited to. The
   vocabulary is `ORIGINAL_CLAIM`, `PRIOR_ART_OVERLAP`,
   `COMPOSITIONAL_CONTRIBUTION`, `IMPLEMENTATION_INNOVATION`,
   `TERMINOLOGY_ONLY`, `DERIVED`, `UNKNOWN`. Prose may not say "novel"
   ahead of the register. Hash chains, nonces, canonical hashing, custody
   split and least privilege are classic; see `prior-art.md`.
6. External PDFs are not vendored. Record id, URL, SHA-256 of the file read,
   and the exact sentence used. `_*_extract.txt` scratch is gitignored.

## Known register drift (verify before quoting)

| Topic | What the registers say | What the code says |
|---|---|---|
| CRC | RES-003 "CRC-inspired" selector, `crc.py`, no Theorem 1 | A second, direct `crc_threshold` with the `B/(n+1)` term exists in `remora/selective/risk_control.py`, library-only. Name both. |
| Learn then Test | `risk_control.py` docstring says "LTT-style"; `ltt-2021` is a compendium ref | No LTT fixed-sequence / multiple-testing procedure exists. Write "reviewed, not implemented". |
| AgentDojo | matrix bibliography: `positioning_only`, "not run" | Adapter `remora/toolcall/routing/sources/agentdojo.py` + pinned `data/routing_bench_v1/agentdojo.jsonl`. Write "adapter available, full benchmark not run". |
| Argument provenance | RF-02 "High gap", SHELF-007/008/041 `UNEVALUATED` | Taint floor, `source_spans`, `DerivationReceipt`, derivation re-execution exist. Status is `PARTIAL`, not absent. |
| PROV ledger | 17 concept records, all `UNKNOWN` | `provenance/PRIOR_ART.yaml` has `reviews: []` and only three `PA-SRC` sources (related work, adjacent crosswalk, APS suite). AEGIS, CaMeL, Progent, AgentSpec and classic audit/capability prior art are not yet review sources. |
| Roadmap | ends at RF-13 | RF-16..22 (Casper-derived baselines, trojan recall, sealed test set) are an external proposal, not in the repo. |

## Workflow for "should we build X from paper Y?"

1. `grep -ril "<paper title words>" docs remora tests NEGATIVE_RESULTS.md`
   and look up the id in `literature.md`.
2. Find the nearest RES / SHELF / RF row. If the shelf has it `UNEVALUATED`
   or `DECLINED`, the decision and reason are already recorded.
3. Ask what the paper would falsify. Prefer an adapter that runs the paper's
   benchmark against the existing gate over a new mechanism. The repo's
   stated gap is external falsification, not missing sensors.
4. Write negative vectors the current code cannot express before adding a
   formalism (RES-018 procedure contracts before AgentLTL, taint floor before
   CaMeL IFC).
5. Any shipped slice with a pre-committed target that misses goes to
   `NEGATIVE_RESULTS.md` with the number, and the roadmap gets a dated note.

## Common mistakes

- Reading `positioning_only` as "we do this too".
- Quoting a matrix `maturity` for a module while skipping the `scope_boundary`
  text that says what is not done.
- Treating the AgentHarm FBR=100% as a tuning failure. It is structural: the
  source artifact is all-ESCALATE and control protocols act on VERIFY only.
- Proposing CoT monitors, activation probes or sleeper-agent detectors as
  REMORA components. They are threat-model context (tier C in
  `literature.md`); the architectural lesson is already taken: model
  self-report and visible reasoning never grant authority.
- Writing `docs/literature/` with vendored PDFs. Licence and size; use the
  shelf entry instead.
