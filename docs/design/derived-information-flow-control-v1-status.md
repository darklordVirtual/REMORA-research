# Derived information-flow control: implementation status

This is the work list for `docs/design/derived-information-flow-control-v1.md`
(SDD v1.3, frozen 2026-10-17). It follows the SDD's release order (§10).
Each line moves to DONE only when every acceptance item of its work package
has a passing test on master; partial work stays IN_PROGRESS and names what
is missing. Changes to the SDD itself come only from implementation findings,
recorded as ADRs and listed at the end.

Statuses: NOT_STARTED, IN_PROGRESS, DONE, BLOCKED (with the reason).

IFC-05b, IFC-07, IFC-08 and IFC-14 are also prerequisites of the
compositional authority work packages CAPR-03 to CAPR-05 and CAPR-09
(`docs/design/compositional-authority-preservation-v1.md`).

## Release order

| Step | Work package | Priority | Status | PR | Missing / note |
|---|---|---|---|---|---|
| 1 | COMP-01 Meet composition and AgentHarm re-score | P0 | DONE | #907, #908; amended by #944 | Meet composition is on master (#907), and the AgentHarm re-score is `artifacts/posthoc/comp01_agentharm_rescore_v1.json` (#908, NEGATIVE_RESULTS.md §84). #944 (R3) made every firing guard and gate enter the meet; two monotonicity cases stay open (§90). |
| 1 | IFC-01 Label lattice | P0 | DONE | #906 | Every acceptance law is a Hypothesis property in `tests/flow/test_label_lattice.py`. Not wired into any decision. |
| 2 | IFC-02 Context store and minting | P0 | DONE | #910 (02a), #912 (02b) | `tests/flow/test_context_store.py` and `tests/flow/test_contexts_route.py` cover every acceptance item. The Postgres cases skip without `REMORA_PG_DSN` and run in the CI Postgres job. |
| 2 | IFC-03 ToolSpec v4 `flow` block, linter, signing | P0 | IN_PROGRESS | #913 (03a, merged via #916); #914 (03b, open) | Schema, parser and lint rules FL-01 to FL-13 have tests in `tests/flow/test_toolspec_flow.py`. Missing on master: refusal of a spec without `flow` at registry load under the strict profile, and bundle hash coverage in `remora/policy/versioning.py`. Both are in #914. |
| 2 | IFC-04 Result labelling and handles | P0 | IN_PROGRESS | #915 (04a, merged via #916) | Handle length hiding, foreign-handle refusal and `test_resolve_value_labels` pass in `tests/flow/test_labeler_handles.py`. Missing (IFC-04b): the `GovernedToolDispatcher.dispatch` change with `DispatchResult.rendered_result`, and the commit-before-return fault-injection test. |
| 2 | IFC-05 Flow check and decision rungs | P0 | IN_PROGRESS | #916 (05a) | `recipients` and `flow_check` pass the four mandatory invariant tests in `tests/flow/test_flow_check.py`. Missing (IFC-05b): rungs F1 to F6 in `hard_guard_floor`, `RemoraDecisionEngine-v6`, v5 golden cases unchanged with flow off, a golden case per F-rung, and the test that a client-supplied `flow` is ignored. No decision reads the verdict yet. |
| 2 | IFC-06 Dispatch-time re-check | P0 | NOT_STARTED | | |
| 3 | IFC-11 Mediation completeness, execution API | P0 | NOT_STARTED | | |
| 3 | IFC-12 Enforced egress and network isolation | P0 | NOT_STARTED | | |
| 3 | IFC-13 Source provenance, M1 tools | P0 | NOT_STARTED | | |
| 3 | IFC-14 Labelled ingress, user turns | P1 | NOT_STARTED | | |
| 4 | M1 gate | gate | NOT_STARTED | | Nothing below starts before it passes (§10). |
| 5 | EVAL-01 AgentDojo substrate, arms A0–A3 | | NOT_STARTED | | |
| 6 | IFC-07 Extraction with capacity accounting | P1 | NOT_STARTED | | |
| 6 | IFC-08 Endorsement and grants | P1 | NOT_STARTED | | |
| 6 | IFC-09 Respond sink | P1 | NOT_STARTED | | |
| 6 | IFC-11 rest, IFC-13 rest, IFC-14 rest | | NOT_STARTED | | |
| 6 | IFC-10 Formal model | P1 | NOT_STARTED | | |
| 7 | EVAL-02 Adaptive white-box attacker | | NOT_STARTED | | |
| 7 | EVAL-03 Scheming-agent track | | NOT_STARTED | | |
| 7 | EVAL-04 / EVAL-05 Metrics and statistics | | NOT_STARTED | | |

## Baseline check

The SDD's §2 mapping was re-verified at master `203a6210` on 2026-10-17.
Every file exists, and every line reference names the definition the SDD
gives:

- `hard_guard_floor` and its taint rungs;
- `_registry_only_observation`;
- `DispatchResult` and `dispatch`;
- `canonical_tool_call_hash` and `decide`.

`LoopEvent` has no kind field. The loop fold ends at a `reset` marker.
`canonical_resource` refuses the `@` form of an email principal.
`CapabilityMediator` and `ResolvedEffectGraph` exist.
`ADR-sdd-as-v1-owner-decisions.md` has D4 for the isolation runtime.

## Relation to SAP v7

SAP v7 (`docs/assurance/statistical_analysis_plan_v7_control_eval.md`, draft)
was written before this SDD. Its harness and statistics are reused:

- the AgentDojo gated executor;
- the split rule;
- the budget guard;
- McNemar, the cluster bootstrap and AUROC.

Its REMORA arm, semantic bundle v2 with an intent proposer, is superseded
by the SDD's flow-control arms A1–A6 (§7.2). Its development dry run stays
the A1 baseline evidence: REMORA v5 blocked 90 of 91 legitimate calls.
Its Q3 composition question becomes COMP-01. Model calls wait for the SDD's
order: the 20-case pilot of §7.7 runs after M1. The owner's decisions of
2026-10-17 carry over to the SDD's `[FREEZE]` values:

- Claude via the API;
- at most 50 USD for the first stage;
- OSF registration.

The frontier model of §7.3 is therefore a Claude model.

## Implementation findings (ADRs)

No ADR has been filed. Two deviations from the SDD are recorded in commits
and in the schema file:

- IFC-03a (`52cbcd35`, #913): `schemas/tool_spec_v4.yaml` adds three fields
  beyond the SDD's §5.1 excerpt (`provider`, argument kinds and
  `disclosure`), because lint rules the SDD assigns to the linter cannot be
  checked without them. The schema file states the reason for each.
- RMR-AUD-007 and RMR-AUD-008, from an external audit of `b64e3cc1` on
  2026-10-18.
  - **Fixed, empty recipients.** Take a `from_args`, `url_host_of`,
    `iban_of` or `resource_of` sink whose recipient argument is `[]`,
    `null` or missing. The rule reached no one, so `flow_check` passed a
    secret payload as clean. A derived rule that yields no value now names
    each argument it reads as `unresolved:<argument>`. One absent argument
    beside a resolved one (a `cc` beside a `to`) is still allowed.
  - **Fixed, FL-01.** The rule caught a `url` argument only under
    `recipients: none`. It now also refuses a `url` argument that is not
    the `url_host_of` argument. On a tool that writes, it refuses an
    `email` or `iban` argument the recipients rule does not name. The SDD (§3.5)
    refuses only `url` under `none`. A read-only lookup by address reaches
    no one, so email and iban count only for tools that write.
  - **Fixed, handle references.** `HandleStore.resolve` treated the
    `{"$handle", "$type"}` object the model is shown as literal text, so
    the tool received the wrapper. The unchanged reference now resolves as
    a whole handle (`L_value = L_h`). A reference with another tag, an
    extra key or extra text stays literal and keeps `L_ctx`.
  - **Not changed, rule-less containers.** The audit asks the labeler to
    walk into a container that has no rule but has rules below it. Under
    §3.2.1 a node is shown by value only if its label flows to the model,
    and an undeclared container's label is `{user_principal}`. Under §3.3
    key presence and list length are data. Walking the container would show
    its structure to a model that may not read it, so the labeler still
    renders it as one handle.
  - **SDD inconsistency, new rule FL-14.** The SDD's own §5.1 `get_inbox`
    excerpt declares `$[*].subject` BY_VALUE with no rule for `$` or
    `$[*]`. Under §3.2.1 the subject is never shown. FL-14 now refuses a
    BY_VALUE rule under a container with no BY_VALUE rule, so the author
    learns this at lint time and not at run time. The excerpt as written
    fails FL-14, and the test fixture adds the two container rules it
    needs.
  - **Not changed, argument labels.** The audit asks that a PUBLIC field
    not take the label of the call's arguments. §3.3 requires that join
    ("data that went in can come out"). A PUBLIC rule written by the
    ToolSpec author cannot declassify data the call was given.
