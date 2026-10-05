# Prior art per provenance concept (reading aid, 2026-10-04, master `fea7928`)

Purpose: stop "novel" from appearing in prose before the review is done. The
ledger `provenance/` holds one record per concept, all currently
`classification: UNKNOWN`, and `provenance/PRIOR_ART.yaml` holds
`reviews: []`. A classification moves only through a dated `PA-REV-xxx`
entry naming the works compared, the overlap, the difference and the one
sentence the contribution is limited to; the manifest gate refuses anything
else. The "candidate" column below uses the ledger vocabulary but is this
skill's reading, not a recorded review. Treat every row as a hypothesis to
confirm against the cited sources before it enters a review, related work or
the paper.

| PROV | REMORA concept | Nearest prior art (arXiv id where known) | Candidate classification |
|---|---|---|---|
| 01 | DecisionEnvelope, signed per-decision record | Crosby & Wallach 2009 tamper-evident logging; RFC 6962; Auditable Agents 2604.05485; AEGIS 2603.12621 Ed25519/SHA-256 chain | composition; hash-chain itself is classic |
| 02 | ToolSpec, deployment-owned tool contract | AgentSpec 2503.18666; Progent 2504.11703; CaMeL 2503.18813; ToolGuardian (SHELF-001) | extension / composition |
| 03 | Exact-call binding of authorization to one concrete call | AEGIS binds represented call fields (crosswalk §1); capability systems; Proof-Carrying Agent Actions 2606.04104 | plausible REMORA extension; needs the AEGIS delta stated precisely |
| 04 | Fresh re-gate of a stale approval | TOCTOU literature; runtime re-authorization; AID-Guard (SHELF-027) commit-time revalidation | extension |
| 05 | PolicyDecisionToken (PDP→PEP) | XACML PDP/PEP; signed authorization tokens; OPA | known pattern |
| 06 | ExecutionLease, short-lived single-use capability | object capabilities; expiring/one-time tokens; macaroons | composition |
| 07 | GovernedToolDispatcher | AEGIS pre-execution mediator; LlamaFirewall 2505.03574; AIRGuard 2605.28914 | related prior art, state the difference |
| 08 | Refusal when ToolSpec changed between assess and dispatch | version binding, TOCTOU; MCPTox tool poisoning | known principle, specific composition |
| 09 | Runtime capability surface completeness | assurance-case / claim discipline (Kelly 1998) | property framing, not a mechanism |
| 10 | Non-transitivity of authority | capability attenuation; CaMeL data capabilities; Progent | strong prior art |
| 11 | Evidence sufficiency tri-state | verification theory; "Silence Is Endorsement" (SHELF-038) | needs dedicated review |
| 12 | Separation of authority and effect domains | separation of duties; trust domains; custody split | PRIOR_ART_OVERLAP likely; composition at most |
| 13 | Canonical tool-call hash, recomputed at dispatch | canonical serialisation (RFC 8785), content binding; AEGIS binds represented fields; APS suite vocabulary (PA-SRC-003) | IMPLEMENTATION_INNOVATION at most; primitive is classic |
| 14 | One-time lease nonce | replay prevention, nonce ledgers | PRIOR_ART_OVERLAP; composition only |
| 15 | Custody split as a hard guard | key custody, separation of duty, HSM role split | PRIOR_ART_OVERLAP; composition only |
| 16 | Task identity bound into the lease | context-bound / resource-bound capabilities; Safety Does Not Compose 2608.27141 | COMPOSITIONAL_CONTRIBUTION candidate |
| 17 | The authority-to-effect chain, taken together | each link exists separately (AEGIS, CaMeL, Progent, capability systems, audit logs) | strongest COMPOSITIONAL_CONTRIBUTION candidate; the AEGIS crosswalk already argues the difference property by property |

Rows 13–15 are classic cryptographic hygiene. The whole chain (policy →
task/authority grounding → exact-call binding → one-time lease → custody
split → governed dispatch → effect evidence → evidence sufficiency) is the
contribution worth defending, which is what PROV-17 records.

## How to record a review

Add a `PA-REV-xxx` entry to `provenance/PRIOR_ART.yaml` (shape is in the
file's comment), set `prior_art.reviewed` and `records` in the concept file,
then run `python scripts/build_provenance_manifest.py --write` and commit
the new manifest. Sources that are not yet `PA-SRC` entries (AEGIS, CaMeL,
Progent, AgentSpec, Crosby & Wallach, RFC 6962) need a source row first.
The ledger paths are protected by `provenance/POLICY.yaml`; the signature
gate reports until `enforced_from` is set.

## What AEGIS does and does not claim (from the crosswalk and 2603.12621)

Register status today: AEGIS is in no register. The crosswalk is a system
comparison, not a bibliography entry. Until a shelf row and a matrix
bibliography row exist, "AEGIS is prior art for PROV-xx" is a proposal and
may not appear in `docs/09-related-work.md` or the paper.

Claims: pre-execution mediation, policy validation, human approval,
Ed25519/SHA-256 hash-chained audit, process-local replay bounding, binding of
represented call fields. Does not claim: semantic authority, non-bypassability
across processes, external effect verification. The crosswalk assesses both
systems against the same A–G properties; rows may not be summed.

## Reading order for a prior-art pass

1. `docs/benchmarks/aegis-remora-crosswalk.md` §0–§1.
2. `docs/research/adjacent-systems-crosswalk-v2.md` (and NR §42 on how the
   first version got four rows wrong).
3. Matrix bibliography `positioning_only` block: LlamaFirewall, Llama Guard,
   NeMo Guardrails, GuardAgent, AgentSpec, Progent, CaMeL, AIRGuard,
   Proof-Carrying Agent Actions, Proof of Execution, AgentTrust, Membrane.
4. `docs/09-related-work.md` §4b path-dependent runtime governance (2026
   comparators) and §12 From Authority to Effect.
