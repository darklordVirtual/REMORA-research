> **Historical snapshot (2026-10-07): producer-owned review, not an external security certification.**
> Review tool: Claude Code (AI-assisted, directed by the maintainer).
> Reviewed revision: `272b6c56fc1d1a6a41640fe4b5e0195fcc155b51`.
> Revalidated at: `b9ade2ba40cc59f1b8849e1e14b655b491a30789` (v0.12.0).
> Independence: NOT_ESTABLISHED. The reviewer and the fixer are the same
> producer; tool output is not evidence by itself (docs/AI_USE.md).
> This file is a frozen snapshot of the review as written. Current status per
> finding: [FINDING_DISPOSITION.md](FINDING_DISPOSITION.md).

# Phase 51 — Final assurance matrix

| Property | Code | Runtime test | Adversarial test | External evidence | Status | Boundary |
|---|---|---|---|---|---|---|
| identity binding | `api.py::_authenticate` | yes | partial | no | PARTIALLY_ESTABLISHED | token-table mode only |
| authority resolution | decision_engine, roles | yes | yes | no | PARTIALLY_ESTABLISHED | SoD role-only |
| capability attenuation | `capabilities/delegation.py` | yes | partial | no | PARTIALLY_ESTABLISHED | mediated tools |
| exact-call binding | `lease.py`, `observation.py` | yes | yes | recorded, not independent | ESTABLISHED (name,args,tenant,target) | in-process, Python canonical form |
| fresh authority | expiry, epochs, plan, surface | yes | yes | no | PARTIALLY_ESTABLISHED | resolver-dependent |
| replay protection | jti ledger, nonce store | yes | yes (properties) | no | ESTABLISHED with durable store | row deletion evident not prevented |
| one-shot execution | nonce consume | yes | yes | no | ESTABLISHED | per process without durable store |
| tenant isolation | tenant-scoped stores | yes | partial | no | PARTIALLY_ESTABLISHED | single-token header (RMR-CR-003) |
| environment binding | target in call hash | yes | yes | no | ESTABLISHED | REMORA_ENV semantics tri-state |
| credential custody | `custody.py` | yes | yes | no | PARTIALLY_ESTABLISHED | declared env names |
| credential non-bypassability | — | — | — | — | NOT_ESTABLISHED | stated in README |
| governed execution | dispatcher | yes | yes | no | ESTABLISHED for registered tools | — |
| complete mediation | — | — | — | — | NOT_ESTABLISHED | — |
| effect declaration | ToolSpec, postcondition contract | yes | partial | no | PARTIALLY_ESTABLISHED | — |
| downstream effect mediation | CapabilityMediator | yes | yes | no | PARTIALLY_ESTABLISHED | opt-in per tool |
| effect observation | verifier receipts | yes | yes | no | PARTIALLY_ESTABLISHED | declared delta only |
| independent effect verification | — | — | — | — | NOT_ESTABLISHED | same deployment |
| evidence integrity | tenant chain | yes | yes | no | PARTIALLY_ESTABLISHED | tamper-evident; HMAC |
| evidence provenance | proposal/grant joins | yes | partial | no | PARTIALLY_ESTABLISHED | — |
| claim ceiling | claim register + gates | CI gates | — | — | PARTIALLY_ESTABLISHED | RMR-CR-006/008/010 wording |
| runtime surface completeness | — | — | — | — | NOT_ESTABLISHED | — |
| external reproducibility | runner + admission | yes | — | one run | PARTIALLY_ESTABLISHED | NOT_INDEPENDENT |
| host isolation | — | — | — | — | NOT_ESTABLISHED | declared |
| hardware attestation | — | — | — | — | NOT_ESTABLISHED | excluded §11 |
