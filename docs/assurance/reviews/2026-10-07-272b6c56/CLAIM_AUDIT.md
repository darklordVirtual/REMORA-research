> **Historical snapshot (2026-10-07): producer-owned review, not an external security certification.**
> Review tool: Claude Code (AI-assisted, directed by the maintainer).
> Reviewed revision: `272b6c56fc1d1a6a41640fe4b5e0195fcc155b51`.
> Revalidated at: `b9ade2ba40cc59f1b8849e1e14b655b491a30789` (v0.12.0).
> Independence: NOT_ESTABLISHED. The reviewer and the fixer are the same
> producer; tool output is not evidence by itself (docs/AI_USE.md).
> This file is a frozen snapshot of the review as written. Current status per
> finding: [FINDING_DISPOSITION.md](FINDING_DISPOSITION.md).

# Phases 14, 42–43 — Claim ceiling, documentation and paper

## Overall

Claim discipline is above the norm for research code: "tamper-evident, not tamper-proof" is repeated consistently (`paper/claim_ledger.md:37,54`, `paper/remora_paper.md:903,1400,1465`); the safety-floor claim is stated with effective N=70 and CI [0, 5.2%] and p=0.50; the README states that REMORA cannot enforce against bypass credential paths. Term scan (lines): "guarantee" README 2 / paper 13; "tamper-proof" paper 12 (all negated); "unbypassable" docs 1; "complete mediation" docs 1; "production-ready" paper 1, docs 4. The remaining issues are scope, not inflation.

## Claims to narrow

| Location | Current | Class | Proposed |
|---|---|---|---|
| `DEVELOPER_OVERVIEW.md` Q3 | "Is authorization bound to the exact action? Yes" | PARTIALLY SUPPORTED | "Yes for (tool, arguments, tenant, target); ToolSpec/task/capability/effect/runtime bindings are enforced under strict profiles with their resolvers configured." |
| `DEVELOPER_OVERVIEW.md` Q1 | "Who defines tool meaning? The deployment" | PARTIALLY SUPPORTED | "…the holder of the ToolSpec signing key, which today includes the authority runtime." |
| `README.md` l.19 | approval "consumed once, at the policy-enforcement point" | SUPPORTED | add: PEP and PDP are co-located on the API path. |
| `paper/remora_paper.md:1491` | TEE shows "correct model under the correct policy" | CONTRADICTED by attestation semantics | "a workload whose measurement matches the approved build and policy digest" |
| `toolcall/toolspec.py` docstring | "does not hold or generate signing keys. The deployment signs" | PARTIALLY SUPPORTED | true of the module; false of the topology under HMAC |
| Effect status name `EFFECT_VERIFIED` | — | stronger than semantics | qualify with vantage + declared-delta scope in reports |
| PROV-15 "custody split as a hard guard" | — | PARTIALLY SUPPORTED | "declared-credential custody guard" |

## Claim that may be stronger than maintainers realise

The federation tooling (self-service runner + base-owned admission workflow + contract graph that cannot confer authority) is a reusable, well-scoped conformance primitive and could be offered to other projects as-is.

## Documentation consistency

- `servers/api.py::_get_env_mode` docstring says any non-production value is "treated as development"; `_authenticate` treats it as non-development and the production guard treats it as non-production (RMR-CR-003).
- `remora/enforcement/lease.py` header still calls the module "library-level PEP … groundwork"; the API path now wires it with durable nonces. The understatement is harmless but inconsistent with `ARCHITECTURE.md` §9 ("CORE").
- Skill `remora-research-frontier` snapshot `fea7928` predates HEAD; its "known register drift" table should be re-verified (not done here).
