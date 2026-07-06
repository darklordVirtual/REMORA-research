# Author: Stian Skogbrott
# License: Apache-2.0
"""Knowledge-domain modules: small, deterministic, artifact-backed techniques
that support REMORA's assurance surface.

Each module is a self-contained, stdlib-only algorithm with a matching result
artifact under results/knowledge_domains/. Per docs/claim_hygiene.md, every
number a doc states is computed here and written to an artifact with a
`result_provenance_v1` block and `status: "ok"` — no invented results.

Modules:
    eval_harness   — grounding P/R/F1 + refusal accuracy scorer for cited-answer systems.
    evidence_graph — evidence-as-a-graph integrity (orphan claims, chain depth).
    multitenant    — tenant-isolation invariant for a shared assurance service.
    ontology       — machine-readable claim ontology + register conformance.
    cost_routing   — cost-aware model routing under per-request quality floors.
"""
