# Claim Evidence Matrix

This matrix maps each major claim in the README/whitepaper to evidence and
artifacts. Use it to produce traceable links from claims to `results/` and
`tests/` artifacts.

Columns:
- Claim id / short description
- Status: `externally_validated` | `internally_supported` | `simulator_only` | `theoretical` | `candidate` | `failed`
- Evidence artifacts (paths)
- Required external replication steps

Example row:

| Claim | Status | Evidence | Next steps |
|---|---|---|---|
| REMORA blocks unsafe tool-calls in full-policy gate | `simulator_only` | `results/toolcall_benchmark_v2.json` | Run live agent/tool integration with 3 external providers and log DecisionEnvelopes |

Keep this file up to date when promoting claims. Every promoted claim must
reference a concrete artifact (file, test, or reproducible pipeline).
