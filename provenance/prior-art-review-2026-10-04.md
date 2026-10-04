# Prior-art review round 1: PROV-01 to PROV-17

Date: 2026-10-04. Reviews: PA-REV-001 to PA-REV-017 in
[PRIOR_ART.yaml](PRIOR_ART.yaml). Reviewer: AI-assisted pass (GitHub
Copilot), directed by the maintainer. Per [docs/AI_USE.md](../docs/AI_USE.md),
AI-generated text requires independent checking; every row below can be
verified against the locators named in the review entries.

## Purpose

The provenance ledger registered seventeen concepts with first-recorded
commits, invariants, code and tests, but zero external classifications. This
round supplies the first classification per concept. The question per concept
is narrow: what does earlier or independent work already contain, what does it
not contain, and which sentence may REMORA use about its own contribution.

## Method

Sources: the related-work survey (PA-SRC-001), the adjacent-systems
crosswalk (PA-SRC-002), the APS conformance vocabulary (PA-SRC-003), and
twenty-two canonical works added as PA-SRC-004 to PA-SRC-025. Every canonical
work predates the first_recorded commit of the concepts it is compared
against. One exception exists by design: PACE (arXiv:2610.01349) is dated
2026-10-01, after the REMORA records it resembles, and is recorded as
independent convergence. Only the PACE abstract was retrieved, on
2026-10-04.

The classification vocabulary is the extended set in
[POLICY.yaml](POLICY.yaml): KNOWN_PRIOR_ART, RELATED_PRIOR_ART,
INDEPENDENT_CONVERGENCE, REMORA_EXTENSION, REMORA_COMPOSITION,
POTENTIALLY_DISTINCT, NOT_ENOUGH_EVIDENCE, beside the original coarse grades.
No review in this round assigns ORIGINAL_CLAIM or POTENTIALLY_DISTINCT. Those
grades require a wider literature search and a patent search, which this round
did not perform.

## Outcome per concept

| Concept | First recorded | Closest prior mechanism | Material difference | Classification |
|---|---|---|---|---|
| PROV-01 DecisionEnvelope | 2026-06-25 | Hash-chained signed audit logs (Schneier & Kelsey 1999); CT logs (RFC 6962); in-toto | one signed record per governance decision, joinable to execution from either end | REMORA_COMPOSITION |
| PROV-02 ToolSpec | 2026-08-05 | ToolGuardian declarative contracts; in-toto signed metadata; MCP tool descriptions | deployment-owned signing with identity-mismatch refusal, agent never supplies the contract | REMORA_EXTENSION |
| PROV-03 exact-call binding | 2026-08-19 | Macaroons caveats; DPoP (RFC 9449); resource indicators (RFC 8707) | application at the agent tool boundary with dispatch-time recomputation | KNOWN_PRIOR_ART |
| PROV-04 fresh re-gate | 2026-07-18 | TOCTOU race literature (Bishop & Dilger 1996); Kerberos lifetimes | freshness as a fresh decision on the execution-time observation, not a clock property | KNOWN_PRIOR_ART |
| PROV-05 PolicyDecisionToken | 2026-06-28 | XACML PDP/PEP; JWT (RFC 7519) | one-time jti and the decision bound to the observation hash | RELATED_PRIOR_ART |
| PROV-06 ExecutionLease | 2026-07-20 | Kerberos tickets; Macaroons; object capabilities | single-use, exact-call-bound capability minted only from an accepted decision | REMORA_COMPOSITION |
| PROV-07 GovernedToolDispatcher | 2026-07-20 | reference monitor (Anderson 1972); complete mediation; ocap custody | dispatcher holds callable and credentials; agent holds only a lease | RELATED_PRIOR_ART |
| PROV-08 ToolSpec-change refusal | 2026-08-05 | TOCTOU version binding; canonical digests (RFC 8785) | a redeployed definition cannot inherit an earlier approval | RELATED_PRIOR_ART |
| PROV-09 surface completeness | 2026-09-27 | attack-surface measurement (Howard et al. 2005) | completeness kept as a separate, usually unestablished claim | REMORA_EXTENSION |
| PROV-10 non-transitivity | 2026-09-29 | SPKI delegation bit (RFC 2693); confused deputy (Hardy 1988); ocap attenuation | tested as an explicit invariant over capabilities and effect reach | KNOWN_PRIOR_ART |
| PROV-11 evidence sufficiency tri-state | 2026-09-10 | Dempster-Shafer epistemics (Shafer 1976) | operational verdict over evidence sets, corpus adequacy-tested | RELATED_PRIOR_ART |
| PROV-12 authority/effect domain split | 2026-09-27 | privilege separation (Provos et al. 2003); Saltzer & Schroeder 1975 | the split applied across a governance pipeline, executor never signs | KNOWN_PRIOR_ART |
| PROV-13 canonical call hash | 2026-07-03 | JCS (RFC 8785); content addressing | full-call hash recomputed at the enforcement point, never a preview | KNOWN_PRIOR_ART |
| PROV-14 one-time nonce | 2026-07-20 | Kerberos replay caches; JWT jti | durable consumption plus the burned-by-failure distinction | KNOWN_PRIOR_ART |
| PROV-15 custody split hard guard | 2026-08-27 | privilege separation; KDC custody (RFC 4120) | process-role declaration enforced as a startup refusal under strict profiles | RELATED_PRIOR_ART |
| PROV-16 task identity in lease | 2026-09-28 | audience binding (RFC 8707); caveat scoping | dispatch refused under another task identity or none | RELATED_PRIOR_ART |
| PROV-17 the chain as a whole | 2026-07-20 | reference monitor; in-toto chains | the integrated, tested chain from proposal to verified effect for agent tool governance | REMORA_COMPOSITION |

Distribution: seven KNOWN_PRIOR_ART, six RELATED_PRIOR_ART, two
REMORA_EXTENSION, two REMORA_COMPOSITION.

## What this changes

The ledger now records what REMORA does not claim. No concept may be
described as novel, first, or unprecedented in any reader-facing document.
The permitted wording per concept is the `claimed_contribution_limited_to`
sentence of its review entry. The two compositions (PROV-01, PROV-17) are
claimed at the level of the integrated, tested artifact, and the two
extensions (PROV-02, PROV-09) at the level of the added mechanism. PACE is
recorded as independent convergence dated after the REMORA records; a
full-text comparison is future work.

## Limitations

This round read canonical works and one abstract. It did not run a patent
search, a systematic literature review, or full-text comparison of the 2026
agent-security systems. A human reviewer should spot-check the overlap and
difference statements before any classification feeds an external document.
Reviews that find these classifications wrong are recorded the same way, with
the same care.

## Next round

Full-text comparison with PACE and AgentSecBench. A patent search before any
concept moves toward POTENTIALLY_DISTINCT. Re-review on evidence, not on a
schedule.
