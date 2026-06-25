# REMORA Artifact Package

This folder is the canonical artifact package for reproducibility and submission.

Structure:
- datasets: frozen benchmark snapshots and metadata manifests
- raw_model_outputs: raw oracle outputs for each condition/run
- result_tables: aggregated metrics and final paper tables
- statistical_tests: paired bootstrap and McNemar outputs
- configs: exact run configs and hyperparameter settings
- docker: container environment used for reproduction

Use `./artifacts/reproduce.sh` to regenerate summary artifacts from cached results.
