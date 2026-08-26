# AROMER as a named subproject

- Status: **accepted** (2026-08-20)
- Deciders: repository owner
- Closes: issue #297
- Code: `remora/aromer/` (31 files, ~8,400 lines), `workers/aromer/`
- Related: `ARCHITECTURE.md` §5.5, `docs/product/product_truth_contract.yaml`
  (class `experimental`), `tests/test_aromer_subproject_boundary.py`

## The question this answers

`remora/aromer/` is a complete second cognitive stack; orchestrator, world
model, meta-judge, experience store, evaluation harnesses. It imports the core;
nothing in the core imports it back. Its position had never been decided, so a
reader walking the tree counted 8,400 lines of learning machinery as part of the
product surface.

Two options were on the table: move it to `remora/research_attic/`, or name it
as a subproject. **Named subproject was chosen.** AROMER is not retained
history (it is under active development with its own research programme) and
the attic is for modules with no ongoing role.

## What "named subproject" means here

1. **Its own version line.** `AROMER_VERSION` in `remora/aromer/__init__.py`
   (currently `0.2.0-experimental`) is independent of the REMORA package
   version. Neither bumps because the other did.
2. **A one-way dependency, enforced.** AROMER may import the core. The core may
   never import AROMER. No module under `remora/` outside `remora/aromer/`, and
   nothing under `servers/`, may import `remora.aromer`. This is not a
   convention: `tests/test_aromer_subproject_boundary.py` fails on a new
   importer.
3. **Not part of the product surface.** AROMER is classified `experimental` in
   `docs/product/product_truth_contract.yaml`, which means it may inform the
   `/v1/assess` research surface and is never a prerequisite for the canonical
   execution path. It cannot override the deterministic hard-guard floor,
   because it is not on that path at all.
4. **Its claims stay its own.** AROMER numbers are shadow-only and are not
   external evidence for REMORA; `ARCHITECTURE.md` §5.5 and
   `NEGATIVE_RESULTS.md` carry the specific limitations (episode labelling,
   seeding artefacts, the AII calibration ceiling). A REMORA claim may not cite
   an AROMER measurement as production evidence.

## What would change the decision

The boundary test is the tripwire. If a core module ever needs to import
AROMER, that is not a test to relax: it means the overlay has become part of
the decision path, and it must instead be promoted deliberately; a capability
register entry, a stated wiring status, and the claim discipline that comes with
being on the enforcing path.

The reverse also holds. If AROMER's research programme stops, the attic is the
correct destination and this document is superseded rather than amended.

## Deliberately left open: `remora/cascade/`

The same question at smaller scale (1,269 lines, no production importer, kept
alive by the claim-verification scripts that assert README statements still
import) is **not** decided here. It has no active research programme, which
makes it a different case from AROMER, and deciding it in passing while
answering a question about AROMER would be exactly the kind of undeclared
architectural drift this document exists to prevent. It stays open.
