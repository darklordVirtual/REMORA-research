# Knowledge-domain modules

Five small, deterministic, artifact-backed techniques that support REMORA's
assurance surface. Each lives in `remora/knowledge_domains/`, is stdlib-only and
offline, and writes a result artifact under `results/knowledge_domains/` with a
`result_provenance_v1` block and a `status` field.

Regenerate all five:

```
python scripts/gen_knowledge_domains.py
```

Per `docs/claim_hygiene.md`, every number below is computed by the code and
written to the cited artifact; an invariant breach is written with
`status: "invalid"` and the generator exits non-zero. These are demonstrations
of each technique on **committed, synthetic fixtures**, not validated external
results.

| Module | What it computes | Artifact | Key numbers |
|--------|------------------|----------|-------------|
| `eval_harness` | Grounding precision/recall/F1 + refusal accuracy for a cited-answer system, scored against a fixed gold set | `results/knowledge_domains/eval_harness.json` | 10 cases · F1 0.9 · refusal 0.6667 |
| `evidence_graph` | Register-as-graph integrity (orphan claims, evidence depth) over a committed fixture | `results/knowledge_domains/evidence_graph.json` | 18 nodes · 15 edges · 0 orphans |
| `multitenant` | Tenant-isolation invariant: no cross-tenant reads, no chain interleave | `results/knowledge_domains/multitenant.json` | 5 tenants · 85 checks · 0 leaks |
| `ontology` | Machine-readable claim ontology + register conformance | `results/knowledge_domains/ontology.json` | 6 levels · 5 types · 0 non-conforming |
| `cost_routing` | Cheapest model clearing each request's quality floor vs. always-premium | `results/knowledge_domains/cost_routing.json` | 8 requests · 0.8059 saving · 0 violations |

## Scope and honesty

- The gold set, fixtures, price table and quality scores are **synthetic and
  fixed**. The numbers grade the *method* (the scorer, the graph builder, the
  isolation logic, the validator, the router), not any live model, tenant, or
  price.
- `cost_routing` is the policy the REMORA audit recommends for the worker's
  otherwise-unbounded AI endpoints, never call the premium model when a cheaper
  one clears the request's quality floor.
- `multitenant` models the isolation invariant only; a deployment must still
  enforce the same boundary at the auth and storage layers.

Tests: `tests/test_knowledge_domains.py` (logic + artifact agreement).
