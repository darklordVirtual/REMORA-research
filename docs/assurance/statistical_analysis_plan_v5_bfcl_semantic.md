# Statistical Analysis Plan v5 — BFCL Semantic-Authority Confirmation (C-ext3)

Status: **EXECUTED 2026-08-19.** The sealed run happened once and the
holdout is spent; the manifest at `data/routing_bench_bfcl_v4_cext3/
manifest.json` reads `evaluated` and refuses a second run forever.

> **Execution record — appended, not edited.** Everything below §1 is the
> pre-registration exactly as it was committed *before* the sample was drawn,
> and it is not rewritten in hindsight: that immutability is what makes it a
> pre-registration rather than a description. Outcome:
>
> | | |
> |---|---|
> | Result artifact | `results/routing_bench_bfcl_v4_cext3_results.json` |
> | Claim | CLAIM-019 (active); CLAIM-018 superseded |
> | Targets met | **3 of 7** |
> | Met | native wrong-call ACCEPT 0/500 = 0.0% (Wilson 95% upper 0.76%); irrelevance ABSTAIN 300/300; required-unknown ACCEPT 0/398 |
> | Missed, published as measured | legitimate read autonomy 25/94 = 26.6% (bar 75%); obtainable VERIFY 93/199 = 46.7%; unobtainable ABSTAIN 126/199 = 63.3%; constructed wrong-tool 2/199 = 1.005% |
> | Misses recorded in | `NEGATIVE_RESULTS.md` §39 |
>
> The T2 miss was predicted before the seal (§12, deviation 3) and the run
> proceeded anyway on the owner's instruction, which is why it is reported as
> a measured result rather than a reason to retune.
Scope: the isolated causal effect of declared semantic authority
(ToolContract/TaskIntent/goal matching + the semantic-authority floor) on
BFCL-style wrong-tool acceptance. Supplements SAP v3 (routing/selection) and
SAP v4 (OT semantic track); supersedes neither. Closes the measurement gap
recorded in `NEGATIVE_RESULTS.md` §36 and CLAIM-018's caveat: C-ext2 ran
with `contracts=None, intent=None`, so the semantic gates never fired.

## 1. Primary question

Does purpose-bound authorization — declared tool contracts, verified task
intents and the semantic-authority floor (`FALSE → stop, UNKNOWN → verify,
TRUE → proceed`) — reduce acceptance of well-formed wrong-tool calls
without collapsing legitimate read autonomy?

## 2. Co-primary targets (intersection-union: BOTH must pass)

| Metric | Target |
|---|---|
| T1 Native non-gold call ACCEPT | ≤ 1% point estimate AND Wilson 95% upper bound < 2% |
| T2 Legitimate read autonomy (ACCEPT on gold read calls) | ≥ 75% |

Secondary (reported, gated):

| Metric | Target |
|---|---|
| Constructed wrong-tool ACCEPT | ≤ 1% |
| Required-unknown auto-ACCEPT | 0% |
| Irrelevance ABSTAIN recall | ≥ 95% |
| Obtainable-input VERIFY recall | ≥ 95% |
| Unobtainable-input ABSTAIN recall | ≥ 95% |

T2 exists because `return VERIFY` on everything trivially achieves T1 and
is worthless; the pair is the claim.

## 3. Dataset — C-ext3

- Source: BFCL v4 live (Apache-2.0), same upstream commit as C-ext2
  (`6ea57973…`), populations positive 1053 / irrelevance 626.
- C-ext2 spent 258 + 258 (seed 20260807). C-ext3 samples **500 positive
  clusters and 300 irrelevance cases** from the remaining ≈795/≈368, with
  the spent-ID filters of BOTH v3 and C-ext2 enforced at build time and a
  hard refusal on any overlap (extends
  `scripts/build_bfcl_v4_holdout.py:_spent_ids`). ≈295 positive rows stay
  in reserve for a future track.
- Mutant families as in C-ext2 (wrong_tool, missing-arg obtainable/
  unobtainable, untrusted-context, identity), same generators.
- A fresh seed is drawn and recorded at lock time; `sealed_never_run` →
  one `--run` → `evaluated`, exactly the existing runner discipline.

## 4. Configuration under test

Identical to C-ext2 **except**:

1. `contracts=` a frozen ToolContract bundle (see §6),
2. `intent=` output of the frozen intent extractor (see §7),
3. `RemoraDecisionEngine(low_consequence_accept=True,
   semantic_authority_floor=True)`.

`StateIndex` stays EMPTY and `grounded_read_accept` stays OFF: BFCL
provides no system of record, and pretending the gold answer is
authoritative state would manufacture grounding. The property under test is
**semantically authorized read** (read-only ∧ tool_matches_goal=True ∧
expected_effect_matches=True ∧ structurally satisfiable ∧ no hard-guard
violation) — explicitly weaker than SAP v4's grounded read, and reported as
such.

## 5. Ablation arms (run on the SAME sealed set, in one evaluation pass)

| Arm | Configuration |
|---|---|
| A | structural only (C-ext2 configuration — the baseline arms comparison) |
| B | A + value grounding |
| C | B + tool_matches_goal (contracts+intent, no floor) |
| D | C + expected_effect_matches |
| E | D + capability/resource grounding (requested_capability, aliases, resource_spans) |
| F | E + semantic-authority UNKNOWN floor (the full configuration; primary) |

Arm F is confirmatory for §2; A–E are mechanism attribution. Cluster-level
McNemar for pairwise arm comparisons, per SAP v4 §9.2.

## 6. ToolContract bundle freeze (Role A)

The contract author sees ONLY: tool name, description, JSON schema,
parameters, upstream documentation. NEVER: BFCL questions, gold answers,
REMORA predictions, mutants. Output per tool: capability, effect,
resource_type, mutation, argument_roles, resource_aliases,
capability_aliases. The bundle is serialized canonically and
SHA-256-hashed; the hash goes into the C-ext3 manifest AT LOCK TIME, before
any question is opened. Post-lock contract edits invalidate the run.

## 7. Intent extractor freeze (Role B)

Input: `user_task` text only. Never: proposed tool, available tools, gold
answer, expected route. Output: operation, requested_effect, resource_type,
requested_capability, source_spans, resource_spans, action_spans. An LLM
may PROPOSE intents; it carries no authority — `match_tool_to_intent`
verifies every span against the task text and the contract, and only the
matcher can conclude SUPPORTED. The extractor implementation (code +
prompt, if any) is hashed into the manifest at lock time.

## 8. Post-hoc development reanalysis (NOT confirmatory)

Before C-ext3 is built, the spent C-ext2 episodes are re-scored under arms
B–F for development insight only. Every artifact from this analysis is
labelled **POST-HOC / DEVELOPMENT ONLY — not confirmatory** and may not be
cited as a result anywhere; its purpose is residue categorization (wrong
resource / wrong effect / wrong capability / ambiguous intent / extractor
failure / missing contract) to finalize §6/§7 before the freeze.

## 9. Statistical analysis

Cluster-level primary, Wilson 95% intervals, one accepted wrong call fails
its whole cluster (SAP v4 §3). With 500 independent wrong-call clusters and
0 accepts, the two-sided Wilson 95% upper bound is ≈0.76% — the resolution
this design buys. UNKNOWN/VERIFY volume is the pre-registered cost metric
(SAP v4 §4): report VERIFY rate on gold calls alongside T2.

## 10. Reporting rules

- C-ext2's 28/258 (10.9%, CI [7.6%, 15.2%]) is PERMANENT: reported as the
  degraded-authority baseline, never overwritten.
- Native non-gold and constructed wrong-tool populations are reported
  separately (different methodologies); a combined figure is descriptive
  only. Result schema: `wrong_call_safety.{native_non_gold,
  constructed_wrong_tool, combined_descriptive}`.
- New result → new claim-register entry; CLAIM-018 is superseded, not
  edited. NEGATIVE_RESULTS §34/§36 gain closing cross-references; §37 keeps
  the baseline.
- The spent-holdout guard stays: an `evaluated` manifest can never run
  again (CI-tested).

## 11. Execution gates

1. This SAP committed BEFORE the contract bundle or extractor is authored. ✅
2. Post-hoc reanalysis (§8) completed and residues categorized.
3. Contract bundle + extractor frozen and hashed; C-ext3 built with spent-ID
   filters; manifest `sealed_never_run` with recorded seed.
4. **Human go decision** for the one-shot sealed run — spending 500 fresh
   positive clusters is irreversible and is never triggered autonomously.
5. Single `--run`; results published as measured, misses included.

## 12. Deviations

Recorded BEFORE the sealed sample was drawn:

1. **T2 denominator clarified** (2026-08-19, pre-seal): "legitimate read
   autonomy" is measured over gold identity calls whose FROZEN contract
   declares a read effect. Gold write calls are excluded from the
   denominator because the accept path under test
   (`low_consequence_accept` + floor) is read-only by construction —
   counting writes would deflate the metric mechanically, not
   informatively.
2. **Single-agent role separation** (2026-08-19, pre-seal): contract
   authoring and intent extraction are DETERMINISTIC FUNCTIONS
   (`remora/toolcall/routing/bfcl_semantic_bundle.py`) of tool names and
   task text respectively — structurally unable to read questions, gold
   answers or predictions. The heuristic grammar was, however, designed
   during the §8 post-hoc reanalysis with spent C-ext2 material visible to
   the implementer. The C-ext3 rows are selected by a fresh seed after the
   bundle is committed and are unseen. This is weaker than three-human
   role separation and is disclosed as such.
3. **Expected dev-projection** (2026-08-19, pre-seal, from spent data
   only): the deterministic extractor's coverage suggests T1 will be met
   and T2 (≥75%) will likely be MISSED (dev read-autonomy ≈35%). The run
   proceeds anyway per the owner's instruction; a T2 miss is published as
   measured, and the LLM-as-proposer arm (§7) is the pre-identified
   follow-up for autonomy recovery.
