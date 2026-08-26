# `scripts/`

121 scripts, of which 52 are referenced by CI or the Makefile. The rest are
not dead (they are one-shot builders and demos), but a reader cannot tell
which is which from the filenames, so this is the map.

## Gated (CI or `make` runs them)

Everything named in `.github/workflows/` or the `Makefile`. These are
maintained: a change that breaks one fails the build. The claim, document and
provenance checkers (`check_*.py`) are the largest group and are the
repository's actual assurance surface.

## One-shot, and deliberately never re-run

Sealed-holdout builders and runners:

- `build_bfcl_v4_cext3.py`, `run_bfcl_cext3.py`: built and evaluated the
  C-ext3 track exactly once. The manifest is marked `evaluated`, the runner
  refuses a second run, and a spent holdout can never serve as a blind set
  again. The same applies to the earlier `build_bfcl_holdout.py`,
  `build_bfcl_v4_holdout.py`, `build_routing_holdout.py` and
  `build_grounding_holdout.py`.
- `bfcl_posthoc_semantic_reanalysis.py`: labelled POST-HOC / DEVELOPMENT
  ONLY; its output may not be cited as a result anywhere.

Running one of these again does not reproduce a result; it destroys the
property that made the result worth having. If you need a fresh measurement,
build a new track with a new seed and pre-register it.

## Demos and generators

`demo_*.py`, `generate_*.py`, `export_*.py`: illustrative or artifact-
producing, run by hand. A demo that stops working is a bug worth fixing, but
it does not gate anything.

## Adding a script

State in the module docstring which of the three groups it belongs to. A
one-shot script must say what makes it one-shot and what refusing a re-run
protects; `scripts/run_bfcl_cext3.py` is the model.
