# What is in this repo and where do I start?

| File | Question answered |
|------|------------------|
| README.md | What does REMORA do and what are its main findings? |
| [01-architecture.md](01-architecture.md) | How does REMORA work end to end? |
| [02-evidence-and-claims.md](02-evidence-and-claims.md) | What are the headline claims and what supports each one? |
| [03-experiments.md](03-experiments.md) | How were the experiments designed and what did they produce? |
| [04-negative-results-detail.md](04-negative-results-detail.md) | What didn't work and what remains open? |
| [05-claim-hygiene.md](05-claim-hygiene.md) | What is the decision rule for adding a claim? |
| [06-reproducibility.md](06-reproducibility.md) | How do I reproduce every result from scratch? |
| [07-api-reference.md](07-api-reference.md) | What are the public interfaces? |
| [08-security.md](08-security.md) | What are the security properties and known gaps? |
| [09-related-work.md](09-related-work.md) | Where does REMORA sit in the literature? |
| [10-contributing.md](10-contributing.md) | How do I contribute a result, fix, or new oracle? |
| [11-benchmark-validation-plan.md](11-benchmark-validation-plan.md) | What is the plan for external validation? |
| [12-agentharm-validation.md](12-agentharm-validation.md) | What is the AgentHarm external validation protocol? |

## Start here

- To understand REMORA: read `README.md` then `01-architecture.md`.
- To verify a claim: read `02-evidence-and-claims.md`.
- To reproduce results: read `06-reproducibility.md`.
- To run AgentHarm validation: read `12-agentharm-validation.md`.
- To add a new result or oracle: read `10-contributing.md`.
- To understand claim rules: read `05-claim-hygiene.md`.

## Scope and status

REMORA is a research-grade governance overlay. No file in this repo certifies production readiness or safety guarantees. Every headline number is bounded by documented assumptions — see `02-evidence-and-claims.md` caveat blocks and `04-negative-results-detail.md` for active limitations.
