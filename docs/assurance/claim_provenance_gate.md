# Claim Provenance Gate

**Status:** Living
**Introduced:** 2026-07-02
**Enforced by:** `scripts/check_claim_provenance.py` (CI: quality-gates workflow)
**Tests:** `tests/test_check_claim_provenance.py`

## Purpose

Cross-document drift — headline numbers, evidence levels, artifact paths, and
gate definitions diverging between README, paper, and assurance docs — is the
single most recurrent claim-hygiene failure mode in this repository (see the
2026-07-02 external review). This gate makes the claim register
(`docs/assurance/claim_register_v1.yaml`) the single source of truth and fails
CI when any bound document disagrees with it.

## Checks

1. **Register integrity.** Every claim carries `id`, `title`,
   `evidence_level`, `artifact`, `caveat`; `evidence_level` must be one of the
   eight taxonomy values in `evidence_levels.md`.
2. **Artifact existence.** Every artifact path cited by a claim must exist on
   disk (CLAUDE.md: "No claims without artifacts").
3. **Manifest verification.** Every SHA-256 row in
   `artifact_manifest_v1.md` is recomputed from file bytes. Hashes must be
   canonical lowercase hex over committed (LF) bytes; CRLF working trees pass
   with a note; content mismatches fail.
4. **Documentation binding.**
   - *Claim anchors:* `<!-- claim:CLAIM-NNN accuracy_pct coverage_pct n -->`
     (with `NNN` = the claim number, e.g. 004)
     placed before a paragraph (or heading) asserts that the register's value
     for each listed metric appears in that paragraph. `n` binds to the
     claim's `n` field; other names bind to the claim's `metrics` map.
   - *Evidence-level citations:* any doc line citing a `CLAIM-###` id together
     with an evidence-level term must match the register's level for that
     claim.

## Workflow for changing a number

1. Update `claim_register_v1.yaml` (the `metrics` map and/or `n`).
2. Update the anchored doc paragraphs — the gate lists every location that
   still carries the old value.
3. If a result artifact changed, update `artifact_manifest_v1.md` under a
   documented protocol (see its Revision Note for the required form).

## Baseline policy

Known violations are grandfathered in `claim_provenance_baseline.json` with a
reason and date; they report as WARN and do not fail the gate. Do not add
entries to avoid fixing new drift — the baseline exists only so the gate could
be adopted while pre-existing defects (currently: the two missing CLAIM-009
artifacts) are remediated. The gate reports stale baseline entries so they can
be deleted once fixed.

## Known limitations

- Anchors bind numbers by presence in the following paragraph, not by exact
  position; a paragraph containing both the old and new value would pass.
- Evidence-level citation checking only fires where a `CLAIM-###` id and a
  taxonomy term share a line; prose that paraphrases a claim without its id
  (e.g. `operation_master_plan_v1.md` §5's table) is not covered — add claim
  ids to such tables to bring them under the gate.
- The paper (`paper/remora_paper.md`) is scanned but not yet anchored;
  anchoring its headline numbers is the natural next increment.
