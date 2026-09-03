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
how REMORA treats its documentation as a governed system, the same
discipline REMORA applies to agent actions, applied to the repository's own
knowledge model.

## 1. One source of truth per data type

| Data type | Single source of truth |
|---|---|
| Claims (numeric, with evidence levels) | [`claim_register_v1.yaml`](claim_register_v1.yaml) |
| Capability wiring status (six-level ladder) | [`capability_register_v1.yaml`](capability_register_v1.yaml) |
| Remediation items and gate status | [`remediation_register.yaml`](remediation_register.yaml) |
| Deployment maturity (computed profile) | [`release_profiles_v1.yaml`](release_profiles_v1.yaml) |
| Gate register + decision history | [`release_gates.md`](release_gates.md) |
| Research → control → code → test chain | [`../research/research_control_matrix_v1.yaml`](../research/research_control_matrix_v1.yaml) |
| Document governance status | [`document_register_v1.yaml`](document_register_v1.yaml) |
| Result artifact hashes | [`artifact_manifest_v1.md`](artifact_manifest_v1.md) |
| Navigation | [`../README.md`](../README.md) (docs index, CI-enforced coverage) |

Narrative documents explain; they are never authoritative for statuses,
numbers, or maturity. The one document that holds status in prose,
`release_gates.md`, is explicitly subordinate: its REM columns *mirror*
`remediation_register.yaml` (the machine source) and it declares so in its own
Authority note; the computed maturity profile is recomputed from the registers,
never read from that table. Hierarchy: `remediation_register.yaml` →
`release_profiles_v1.yaml` (computed) → `release_gates.md` (register + history)
→ the README status block (generated). Where a narrative document repeats a
register fact, the existing gates bind it (claim anchors via
`check_claim_provenance.py`, README claims via `check_readme_claims.py`,
capability claims via the register's "narrative documents must not claim a
stronger status" rule, and the README status block via
`generate_readme_status.py --check`).

## 2. Document classification

Every tracked knowledge document, meaning everything under `docs/` (excluding
`figures/` assets) and `paper/`, plus a root-document allowlist (README,
ARCHITECTURE, NEGATIVE_RESULTS, SECURITY, CONTRIBUTING, CONTRIBUTORS, CLAUDE,
EVIDENCE_OF_CAPABILITY, NOTICE), has exactly one entry in
[`document_register_v1.yaml`](document_register_v1.yaml) with one of six
statuses:

| Status | Meaning | Extra obligations |
|---|---|---|
| `canonical` | The single authoritative document for its topic | `topic` unique across the register |
| `generated` | Produced by a script; edit the generator | `generated_by` must exist |
| `supporting` | Explanatory; must not contradict canonical sources | — |
| `proposal` | Proposed/roadmap content, not implemented claims | — |
| `historical` | Dated snapshot; body immutable, not current | banner required in the first 15 lines |
| `superseded` | Kept so old links resolve | `superseded_by` must exist; the stub must point readers to it |

The register is a sidecar (not per-file frontmatter) deliberately:
historical snapshot *bodies* are immutable: the findings, numbers and
dispositions they recorded must never be rewritten to match the present;
so their governance status must live outside them. One narrowly scoped
exception exists: a clearly separated governance banner (a `> **Historical
…**` block quote above the original content) may be *prepended* when a
document is reclassified, so a reader landing on the file sees its vintage
before its findings. The banner may name what has changed since; it may not
alter, delete or reword anything below it. The machine-enforced form
(`VINTAGE_BANNER_RE` in `scripts/check_document_governance.py`) requires a
block-quote line carrying a bold span with a vintage keyword, such as `>
**Historical …**`, `> **ARCHIVED — historical …**` or `> **NOTICE:** …
**HISTORICAL** …` all qualify; the bold span must close on one line. HTML
assets use the equivalent `<!-- ARCHIVED - … -->` comment banner. A bare
mention of the words ("This is not a historical document.") does not count.
Gitignored local working
documents are out of scope by construction (the validator enumerates
`git ls-files`).

## 3. Release profiles instead of a diffuse "production ready"

[`release_profiles_v1.yaml`](release_profiles_v1.yaml) defines five
cumulative profiles (`RESEARCH_REFERENCE`, `SHADOW_PILOT`,
`CONTROLLED_PILOT`, `LIMITED_ENFORCEMENT`, `PRODUCTION`), each with
machine-checkable requirements against capability-ladder levels and REM
statuses. CI recomputes the highest satisfied profile from the registers and
fails if the declared `current_profile` drifts. **A profile can only be
claimed by changing register state backed by evidence, never by editing
prose.** The current profile is `SHADOW_PILOT` (= `deployment_status
SHADOW_ONLY`): shadow-mode operation is permitted, enforcement is not,
because `CONTROLLED_PILOT` requires REM-021 (independent review) per
[`release_gates.md`](release_gates.md).

## 4. What CI enforces today

The `documentation-governance` gate checks, as HARD failures:

1. Statuses are from the enum; `superseded` entries name an existing
   successor and the stub points to it; `generated` entries name an existing
   generator; `historical` entries carry a structured vintage banner in
   their first 15 lines (see §2).
2. Canonical topics come from the controlled `topics:` registry, and at most
   one `canonical` document claims each topic. Caveat (2026-07-28 audit):
   topics are currently path-derived for effectively all entries, so the
   uniqueness rule cannot fire in practice, closing the topic-fragmentation
   gap requires subject-level topics, tracked in the governance backlog.
3. `CAP-*` / `REM-*` / `CLAIM-*` ids are unique within their registers, and
   the registers parse as strict YAML (this gate found and fixed five
   invalid-YAML entries in the remediation register on its first run).
4. Release-profile requirements reference only existing ids and ladder
   levels, and declared `current_profile` equals the computed profile.

And as ADVISORY warnings (printed, never failing the build):

5. Document-register coverage across `docs/` + `paper/` + the root-doc
   allowlist (unregistered files, ghost entries, duplicates warn only).
6. Per-entry `id`/`version`/`code_synced`/`verdict` presence and
   `last_reviewed` consistency.
7. The `README.md` line budget: 160 lines advisory (`README_LINE_SOFT_CAP`),
   200 lines hard (`README_LINE_HARD_CAP`). Corrected 2026-09-03; this entry
   said "300-line budget", a figure the script has never used. Detail still
   belongs in `docs/`.

A **generated-doc drift** step then regenerates every text generator and fails
on any diff: `research_control_matrix.generated.md`
(`generate_research_control_matrix.py --check`), the README status block
(`generate_readme_status.py --check`), and `results_snapshot.md`; the
remora-dependent `failure_analysis.md` is diffed in `quality-gates.yml`. A
committed generated document can no longer go stale silently.

Pre-existing gates complete the picture: link integrity
(`scripts/_check_links.py`, link *targets* only; index *coverage* is not
CI-enforced), claim anchors and artifact existence
(`check_claim_provenance.py`, `check_artifacts_exist.py`), README claims
(`check_readme_claims.py`), capability-register structure
(`tests/test_capability_register.py`), research-matrix path integrity
(`tests/test_research_control_matrix.py`).

## 5. Change control (going-forward convention)

A status change in any register must carry, in the same commit:

- the reason for the change,
- the code/doc/test evidence (as register `artifacts`/`evidence` entries),
- and, for maturity increases (capability ladder level up, REM item to DONE,
  profile change), the commit-bound evidence that justifies it, following
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
- Full README generation: the load-bearing status (deployment profile,
  open gates, capability count) is now a generated, `--check`-guarded block,
  and the numeric claims are bound via claim anchors. Generating the *entire*
  README (prose included) is deliberately not done; the narrative is
  hand-written for readability; only the drift-prone facts are generated.
- Approval workflow for status changes: single-maintainer repository;
  CODEOWNERS routes register changes for review the day a second reviewer
  exists (REM-021).
- **MkDocs site, split human-index/generated-catalog, per-release
  documentation manifests**: a presentation-plane program. A root
  `mkdocs.yml` with a hand-written 16-entry nav exists but is itself
  ungoverned (config files are outside register scope); generating its
  navigation from the register remains deferred as a separate body of work.

## 7. The ambition

A versioned, machine-validatable, commit-bound knowledge model of REMORA's
architecture, research, claims, evidence, maturity, and open risks; the
same fail-closed, evidence-first discipline the system applies to agent
actions, applied to itself.
