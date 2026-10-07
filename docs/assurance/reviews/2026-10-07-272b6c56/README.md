# Security review 2026-10-07 (reviewed revision 272b6c56)

> **Producer-owned review. Not an external security certification.**
> Review tool: Claude Code (AI-assisted, directed by the maintainer).
> Reviewed revision: `272b6c56fc1d1a6a41640fe4b5e0195fcc155b51`.
> Revalidated at: `b9ade2ba40cc59f1b8849e1e14b655b491a30789` (v0.12.0).
> Independence: NOT_ESTABLISHED.

An adversarial review of REMORA's authority, credential, execution and
evidence model produced fifteen findings, RMR-CR-001 to RMR-CR-015. Each was
re-verified against the code at the revalidation revision before any fix,
mostly with a probe. This folder keeps the chain from finding to regression
test, pull request, fix and remaining boundary in the repository, so a reader
can follow it without trusting the summary.

| File | What it is | Changes? |
|---|---|---|
| [FINDINGS.md](FINDINGS.md) | The fifteen findings as written at review time | frozen |
| [ASSURANCE_MATRIX.md](ASSURANCE_MATRIX.md) | Property-by-property assurance matrix at review time | frozen |
| [CLAIM_AUDIT.md](CLAIM_AUDIT.md) | Claim ceiling and documentation audit at review time | frozen |
| [FIX_REBASE.md](FIX_REBASE.md) | Stage 0: every finding re-verified at the revalidation revision, with corrections to the review | frozen |
| [FINDING_DISPOSITION.md](FINDING_DISPOSITION.md) | Current status per finding: fix, tests, PR, remaining boundary | living |
| [MCP_EXECUTION_SURFACE.md](MCP_EXECUTION_SURFACE.md) | Stage H: every MCP execution surface, how authority reaches its effects, and the open gaps | living |
| [findings.json](findings.json) | The findings in machine-readable form, with provenance | frozen |

What this is not: an independent audit, a penetration test or a
certification. The same producer reviewed and fixed, so a finding marked
fixed means the stated regression test passes in CI, not that an outside
party has confirmed the property.
