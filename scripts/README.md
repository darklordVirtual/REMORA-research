# Scripts Directory Guide

This folder contains operational scripts for benchmarking, documentation quality gates, demos, and one-off maintenance patches.

## Conventions

- All Python scripts must use UTF-8 source encoding.
- Each script should have:
  - `# Author: Stian Skogbrott`
  - `# License: Apache-2.0`
  - A module docstring describing purpose and usage.
- Prefer deterministic outputs for benchmark/report scripts.
- One-off patch scripts should be treated as maintenance utilities, not runtime dependencies.

## Active Operational Scripts

These are expected to remain in regular use.

- Benchmarking and evaluation:
  - `build_benchmark.py`
  - `build_rag_adversarial.py`
  - `gen_toolcall_benchmark.py`
  - `selective_n500_holdout.py`
  - `statistical_tests.py`
  - `validate_corpus.py`
  - `phase_frontier.py`
- Quality gates and consistency checks:
  - `check_artifacts_exist.py`
  - `check_claim_consistency.py`
  - `check_no_overclaims.py`
  - `check_readme_claims.py`
  - `_check_conformal.py`
  - `_check_imports.py`
  - `_check_links.py`
- Documentation and figure generation:
  - `generate_analysis.py`
  - `generate_n1000_figures.py`
  - `generate_readme_figures.py`
  - `generate_results_snapshot.py`
  - `generate_linkedin_visuals.py`
  - `generate_usecase_visuals.py`
  - `generate_asker_visual.py`
  - `generate_demo_gif.py`
- Runtime and integration tooling:
  - `remora_hook.py`
  - `remora_anchor.py`
  - `setup_cloudflare_infra.py`
  - `shadow_replay.py`
  - `ingest_corpus.py`
  - `enrich_corpus.py`
  - `mcp_test.py`
- Demos:
  - `demo.py`
  - `demo_building_lights.py`
  - `demo_norwegian_law.py`
  - `capture_demo.py`
  - `demo_future_concept.py` (experimental)

## Maintenance / One-Off Patch Scripts

These maintenance helpers are now located in `scripts/legacy/` to keep the root
scripts folder focused on operational tooling.

- Paper/doc patching (`scripts/legacy/`):
  - `patch_bibliography.py`
  - `patch_citations.py`
  - `patch_crc_paper.py`
  - `patch_crc_paper_md.py`
  - `patch_paper.py`
  - `patch_paper_md.py`
  - `patch_paper_md2.py`
  - `patch_pvd_paper.py`
  - `patch_stages.py`
  - `patch_tee_paper.py`
- Code patching helpers (`scripts/legacy/`):
  - `_patch_ast_guard.py`
  - `_patch_lyapunov.py`
  - `_patch_lyapunov2.py`
  - `_patch_thermodynamics.py`
  - `fix_crc_tests.py`
