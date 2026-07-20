# Documentation Governance v1

**Status:** canonical (topic: documentation-governance)
**Date:** 2026-07-20
**Owner:** Stian Skogbrott
**CI gate:** `scripts/check_document_governance.py` (job `documentation-governance` in `.github/workflows/ci.yml`; also run by `tests/test_document_governance.py` in the suite)

The repository's documentation has grown large enough that unmanaged, it
becomes an architecture risk of its own: the same status described
differently in two places, old documents that still look authoritative, a
README that grows every time something needs visibility, and readers who
must understand the history to find the current state. This document defines
how REMORA treats its documentation as a governed system — the same
discipline REMORA applies to agent actions, applied to the repository's own
knowledge model.

## 1. One source of truth per data type

| Data type | Single source of truth |
|---|---|
| Claims (numeric, with evidence levels) | [`claim_register_v1.yaml`](claim_register_v1.yaml) |
| Capability wiring status (six-level ladder) | [`capability_register_v1.yaml`](capability_register_v1.yaml) |
| Remediation items and gates | [`remediation_register.yaml`](remediation_register.yaml) |
| Release gates (narrative + elevation record) | [`release_gates.md`](release_gates.md) |
| Deployment-readiness profiles | [`release_profiles_v1.yaml`](release_profiles_v1.yaml) |
| Document governance status | [`document_register_v1.yaml`](document_register_v1.yaml) |
| Result artifact hashes | [`artifact_manifest_v1.md`](artifact_manifest_v1.md) |
| Navigation | [`../README.md`](../README.md) (docs index, CI-enforced coverage) |

Narrative documents explain; they are never authoritative for statuses,
numbers, or maturity. Where a narrative document repeats a register fact, the
existing gates bind it (claim anchors via `check_claim_provenance.py`, README
claims via `check_readme_claims.py`, capability claims via the register's
"narrative documents must not claim a stronger status" rule).

## 2. Document classification

Every tracked file under `docs/` (excluding `figures/` assets) has exactly
one entry in [`document_register_v1.yaml`](document_register_v1.yaml) with
one of six statuses:

| Status | Meaning | Extra obligations |
|---|---|---|
| `canonical` | The single authoritative document for its topic | `topic` unique across the register |
| `generated` | Produced by a script; edit the generator | `generated_by` must exist |
| `supporting` | Explanatory; must not contradict canonical sources | — |
| `proposal` | Proposed/roadmap content, not implemented claims | — |
| `historical` | Dated snapshot, preserved unedited, not current | — |
| `superseded` | Kept so old links resolve | `superseded_by` must exist; the stub must point readers to it |

The register is a sidecar (not per-file frontmatter) deliberately:
historical snapshots are never edited, so their governance status must live
outside them. Gitignored local working documents are out of scope by
construction (the validator enumerates `git ls-files`).

## 3. Release profiles instead of a diffuse "production ready"

[`release_profiles_v1.yaml`](release_profiles_v1.yaml) defines five
cumulative profiles — `RESEARCH_REFERENCE`, `SHADOW_PILOT`,
`CONTROLLED_PILOT`, `LIMITED_ENFORCEMENT`, `PRODUCTION` — each with
machine-checkable requirements against capability-ladder levels and REM
statuses. CI recomputes the highest satisfied profile from the registers and
fails if the declared `current_profile` drifts. **A profile can only be
claimed by changing register state backed by evidence, never by editing
prose.** The current profile is `SHADOW_PILOT` (= `deployment_status
SHADOW_ONLY`): shadow-mode operation is permitted, enforcement is not,
because `CONTROLLED_PILOT` requires REM-021 (independent review) per
[`release_gates.md`](release_gates.md).

## 4. What CI enforces today

The `documentation-governance` gate checks:

1. Document-register coverage is exact (no unregistered files, no ghost
   entries, no duplicates).
2. Statuses are from the enum; `superseded` entries name an existing
   successor and the stub points to it; `generated` entries name an existing
   generator.
3. At most one `canonical` document per topic.
4. `CAP-*` / `REM-*` / `CLAIM-*` ids are unique within their registers, and
   the registers parse as strict YAML (this gate found and fixed five
   invalid-YAML entries in the remediation register on its first run).
5. Release-profile requirements reference only existing ids and ladder
   levels, and declared `current_profile` equals the computed profile.
6. `README.md` stays under 400 lines — surfacing something new in the README
   has an enforced cost; detail belongs in `docs/`.

Pre-existing gates complete the picture: index coverage
(`tests/test_docs_index_coverage.py`), link integrity
(`scripts/_check_links.py`), claim anchors and artifact existence
(`check_claim_provenance.py`, `check_artifacts_exist.py`), README claims
(`check_readme_claims.py`), capability-register structure
(`tests/test_capability_register.py`).

## 5. Change control (going-forward convention)

A status change in any register must carry, in the same commit:

- the reason for the change,
- the code/doc/test evidence (as register `artifacts`/`evidence` entries),
- and, for maturity increases (capability ladder level up, REM item to DONE,
  profile change), the commit-bound evidence that justifies it — following
  the existing register convention of dated notes (see REM-024's PROGRESS
  note for the pattern):

```yaml
# pattern for a maturity increase, recorded in the item's notes:
#   PROGRESS <date>: <what changed> — evidence: <paths>, verified at <commit>
```

Statuses are never raised by prose edits alone; the CI gates above make the
load-bearing cases mechanical (profiles, claims, capability language).

## 6. Deliberately deferred (not silently skipped)

- **Per-entry record versioning** (`record_version`, `effective_from`,
  `supersedes` on every CAP/REM/CLAIM entry): retrofitting these onto ~60
  existing entries would require reconstructing history and risks inventing
  metadata, which the claim-hygiene rules forbid. The going-forward
  convention in §5 captures the same information as dated, commit-bound
  notes; a structured retrofit can follow when the git history is mined for
  real dates.
- **Generated README/status pages**: the README's numeric claims are already
  bound to registers via claim anchors; full generation is a pipeline change
  deferred until the register schema stabilises.
- **Approval workflow for status changes**: single-maintainer repository;
  CODEOWNERS routes register changes for review the day a second reviewer
  exists (REM-021).

## 7. The ambition

A versioned, machine-validatable, commit-bound knowledge model of REMORA's
architecture, research, claims, evidence, maturity, and open risks — the
same fail-closed, evidence-first discipline the system applies to agent
actions, applied to itself.
