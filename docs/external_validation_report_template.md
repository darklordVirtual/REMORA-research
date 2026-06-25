# REMORA External Validation Report Template

Use this template to produce an external-facing validation report. Fill all
sections and attach `results/external_validation_raw.jsonl` alongside the
report for audit.

Title: REMORA External Validation — [dataset / benchmark]
Date: YYYY-MM-DD
Authors: [names]

Executive Summary
-----------------
- Short (3-5 bullets) about what was tested and high-level findings.

Experimental Setup
------------------
- Datasets and splits (names, versions, sample sizes)
- Models / providers used (exact model ids and provider)
- Oracle configurations (temperature, top_k, n_samples)
- Prompt templates and version
- Random seeds and environment details
- Cost estimates and provider quotas used

Benchmarks and Baselines
------------------------
- List baselines compared
- For each baseline, precise command used to generate outputs

Results (Tabular)
-----------------
- Include per-benchmark table with metrics required in the protocol (accuracy,
  accepted/abstained/escalated, coverage, Wilson CIs, latency p50/p95/p99).

Per-item Audit Log
------------------
- Attach `results/external_validation_raw.jsonl` (one JSON object per line)

Analysis
--------
- Interpretation of results, where REMORA helps/hurts, failure modes,
  correlated model-family failures, and operational considerations.

Limitations
-----------
- Explicitly list what remains untested, assumptions, and what requires
  external replication.

Conclusions & Recommendations
-----------------------------
- Practical recommendations for deployers and next steps for external
  replication.
