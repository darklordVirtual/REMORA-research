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
| 2 | IFC-03 ToolSpec v4 `flow` block, linter, signing | P0 | DONE | #913 (03a, merged via #916); #914 (03b, merged at `b64e3cc1`); FL-01 widened and FL-14 added by #939 | Schema, parser and lint rules FL-01 to FL-14 have tests in `tests/flow/test_toolspec_flow.py`. At bundle load (`tests/flow/test_toolspec_flow_load.py`) a flow block below schema version 4 is refused, every block is parsed and linted, and under a strict profile with `REMORA_FLOW_CONTROL=1` startup refuses a bundle with a spec that has no block (FL-13). `remora/flow/label.py` and `remora/flow/spec.py` are in the policy bundle hash (`remora/policy/versioning.py`). |
| 2 | IFC-04 Result labelling and handles | P0 | IN_PROGRESS | #915 (04a, merged via #916); handle-reference fix in #939 | Handle length hiding, foreign-handle refusal, `test_resolve_value_labels` and the resolution of an unchanged `{"$handle", "$type"}` reference pass in `tests/flow/test_labeler_handles.py`. Missing (IFC-04b), checked at master `90d8914e`: the `GovernedToolDispatcher.dispatch` change with `DispatchResult.rendered_result` (no such field exists), and the commit-before-return fault-injection test. |
| 2 | IFC-05 Flow check and decision rungs | P0 | DONE | #916 (05a); empty-recipient fix in #939; IFC-05b in #952 | `recipients` and `flow_check` pass the four mandatory invariant tests and the empty-recipient cases in `tests/flow/test_flow_check.py`. IFC-05b: rungs F1 to F6 in `hard_guard_floor` and `RemoraDecisionEngine-v6`; the v5 golden cases decide as before with flow off and with a clean flow (`tests/policy/test_flow_rungs.py`); every rung has a golden case in `scripts/opa_conformance.py` and the Rego gate; a client-supplied `flow` is ignored (`tests/flow/test_flow_decision_route.py`). The decision reads the verdict only on `/v1/execution` with `REMORA_FLOW_CONTROL=1`; deviations are listed below. |
| 2 | IFC-06 Dispatch-time re-check | P0 | IN_PROGRESS | #975 (`abf05328`, `61367677`); resolved invocation in this change | On `/v1/execution` with `REMORA_FLOW_CONTROL=1` the call is re-checked against the current flow context before the lease is minted, a moved epoch or digest refuses, and the result's labels commit before it is returned (`tests/flow/test_flow_at_dispatch.py`, `tests/flow/test_flow_dispatch_leased.py`). The tool receives the resolved handle values; the dispatcher judges the capability, effect and procedure checks over both the wire form and the resolved form (`tests/test_execution_lease.py`). The lease signs `flow_epoch`, `flow_digest` and `resolved_tool_call_hash` when the call was judged under flow control (SDD unified capability execution v1.1, P0 item 6; absent fields are omitted from the preimage, so earlier leases verify as before). `/dispatch-leased` takes its expected epoch and digest from the signed lease instead of computing them itself a moment before the comparison, refuses a lease without them as `flow_lease_unbound`, and the dispatcher refuses an invocation whose hash is not the signed one as `resolved_call_mismatch` before the nonce (`tests/flow/test_flow_dispatch_leased.py`, `tests/test_execution_lease.py`, `tests/test_lease_verification_completeness.py`). The dispatch fence closes the race: after the re-check, the call appends a `dispatch` event to the context stream at the sequence it checked, and a context held by another proposal's unexpired dispatch (or a fence lost to a concurrent writer) refuses as `flow_dispatch_contended` before the tool runs and before anything is spent; the fence is taken with the sequence the re-check read (`begin_dispatch(expected_seq=...)`), so a raise committed between the check and the fence refuses as `flow_dispatch_contended` before the tool runs; the fence is released by the commit or on every refusing path, is renewed every third of the lease TTL while the tool runs (`renew_dispatch`), and expires with the lease TTL only for a process that died mid-call; a commit whose own fence is no longer live withholds the result as `flow_dispatch_fence_expired` (`tests/flow/test_context_store.py`, `tests/flow/test_flow_dispatch_leased.py`: two dispatches in one context run exactly one tool, a raise between the check and the fence refuses, a tool held past the TTL still holds the context). A raise that lands while the holder runs still withholds the holder's result. Missing: TLA+ (§6.3). |
| 3 | IFC-11 Mediation completeness | P0 | DONE for the repository's surfaces | #1060 (execution API); the rest in this change | Every route of `servers/execution_api.py` (both routers, 28 routes) is classified in code as TOOL_DISPATCH or NO_TOOL_RESULT; `scripts/check_flow_mediation_surface.py` holds the routers to the classification and, by AST, holds the three dispatching routes and the worker entry to `_dispatch_under_lease`, forbids any other handler from reaching the dispatcher, and allowlists the service-layer and dispatcher call sites. The same script inventories the other surfaces §4 names: `servers/api.py` reaches no dispatcher; the `tools/call` handlers of `servers/mcp_remora.py` must agree with its advertised tools, be module functions, reach no dispatcher, and the one forwarding handler must post to the agent-control worker; the SDK's two clients and the two TypeScript workers may name only served routes, and the SDK's side-effect paths must be TOOL_DISPATCH routes. `tests/flow/test_mediation_surface.py` pins each rule on synthetic sources and probes forged, foreign and replayed contexts on `/dispatch-leased`, an SDK call under flow control (refused; the SDK cannot name a context), a governed tool named at the MCP server (unknown) and a foreign tool presented to the execution API (`unknown_tool`). Outside the property, recorded in the register: the agent-control worker's in-worker tools (their results reach the agent without a flow context), an MCP server registered outside REMORA, and any running deployment. The SDD's probe "through an MCP server registered outside REMORA" is met by its in-repository analogue only. |
| 3 | IFC-12 Enforced egress and network isolation | P0 | IN_PROGRESS | first slice in this change | The recipient set the flow check approves for a call is carried to the mediated effects. The authority signs its digest into the lease (`flow_recipients_digest`). The executor recomputes the set and refuses a lease whose digest differs (`flow_recipients_changed`). The `CapabilityMediator` refuses a network effect on a host outside the set before the ceiling is consulted (`capability_recipient_not_approved`, in the effect record). The effect domain admits an effect only under the set the worker presents, and only when it matches the lease (`flow_recipients_mismatch`). `tests/capabilities/test_flow_recipients.py`, the dispatch-leased and effect-domain server paths, the authority path (`/execute-accepted` under flow control mints the lease with the digest and the mediator refuses the collector for the recipient, `tests/capabilities/test_mediation_flow_recipients_server_path.py`), and the process split (conformance P11: the executor, in its own process with the credential, refuses the effect to a host outside the set, and the effect service's mailbox confirms exactly one delivery; a set that differs from the lease refuses before the tool, nonce unspent). Covered of §3.5.1: a tool that forwards a payload to an undeclared host is refused by the mediator; the effect evidence shows the refusal. Not covered: redirects, because the effect executors are deployment primitives and no reference HTTP executor exists in this repository. Not covered either: DNS resolution and pinning, TLS termination, and the network namespace (deployment runtime, ADR D4). Write effects on `workspace://` or `database://` resources name no recipient here and are not narrowed. The register says so. |
| 3 | IFC-13 Source provenance, M1 tools | P0 | NOT_STARTED | | |
| 3 | IFC-14 Labelled ingress, user turns | P1 | NOT_STARTED | | |
| 4 | M1 gate | gate | NOT_STARTED | | Nothing below starts before it passes (§10). |
| 5 | EVAL-01 AgentDojo substrate, arms A0–A3 | | NOT_STARTED | | |
| 6 | IFC-07 Extraction with capacity accounting | P1 | NOT_STARTED | | |
| 6 | IFC-08 Endorsement and grants | P1 | NOT_STARTED | | |
| 6 | IFC-09 Respond sink | P1 | NOT_STARTED | | |
| 6 | IFC-13 rest, IFC-14 rest | | NOT_STARTED | | The rest of IFC-11 landed in #1066 (row 3). |
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

No ADR has been filed. The deviations from the SDD are recorded in commits,
in the schema file and here:

- IFC-06 (SDD unified capability execution v1.1, P0 item 6): the dispatch-time
  refusals are named `flow_epoch_changed` and `flow_digest_changed` (the
  epoch is compared first), not the single `flow_label_advanced` of §3.8;
  `flow_lease_unbound` is as in §3.8. The lease signs `flow_epoch` whenever
  it is non-zero, not only beside `flow_digest`, so the field is tamper
  evident on its own; a non-zero epoch without a digest is refused as
  `flow_binding_malformed`. The check and the dispatch are made one step by
  a dispatch fence on the context stream (`dispatch`/`dispatch_end` events,
  `FlowContextStore.begin_dispatch`/`renew_dispatch`/`end_dispatch`), not
  by a database transaction spanning the tool call. The fence is appended at
  the stream sequence the check read, so any write after the check (a raise,
  another fence, a renewal) is contention. The loser refuses as
  `flow_dispatch_contended`, which §3.8 does not name. A fence of the same
  proposal on another hop (the authority forwarding to the execution
  domain) does not contend with itself, and an expired fence is ignored.
  The holder renews its own while the tool runs and through the commit and
  release. A commit whose fence lapsed refuses as
  `flow_dispatch_fence_expired`, which §3.8 does not name either. The
  ownership check is the append that records the commit
  (`FlowContextStore.raise_label(dispatch_id=...)`). An expired fence cannot
  reverse an external side effect the tool already caused. It withholds the
  result and refuses the competing call, nothing more.

- IFC-12 (first slice): the recipient set is bound as a signed lease field
  (`flow_recipients_digest`) beside the IFC-06 fields and compared by
  the executor. §3.5.1 reads it from the execution context instead; in
  the three-domain split the set must be lease-bound, or the worker
  could present any set. A network effect names the host of its http(s)
  resource as `ext://<host>`, the form the flow check gives a URL
  argument. A resource with a recipient scheme names itself. Other
  effects are not narrowed. The refusal names
  (`capability_recipient_not_approved`, `flow_recipients_changed`,
  `flow_recipients_mismatch`) are not in §3.5.1.
- External review of 2026-10-25 (five findings verified against the code,
  fixed with regression tests in
  `tests/flow/test_flow_review_findings_2026_10_25.py` and
  `tests/capabilities/test_flow_recipients.py`). A delegate redeeming an
  ACCEPT token now reads the proposer's flow context. The authority no
  longer commits a result the execution domain committed. A
  recipient-bound lease for a mediated tool without a recipient set
  refuses `flow_recipients_required`. `/dispatch-leased` verifies the
  lease's signature before the fence. Every `network.*` effect names its
  host. Two findings were already recorded and are unchanged. The handle
  store is per process (F2), so a handle does not cross the custody
  split. The commit and the dispatch-time check pass no resource ACL or
  source metadata: a `resource_acl` reader rule yields no readers and a
  `resource_of` sink is unresolved, and both refuse.
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
- IFC-05b, 2026-10-19.
  - **Flat fields, not `FlowVerdict`.** §3.7 names one field
    `PolicyObservation.flow: FlowVerdict | None`. The observation carries
    `flow_status`, two violation flags, `flow_epoch` and `flow_digest`
    instead. Observations are persisted and rebuilt as flat records, the
    OPA input is flat JSON, and the verdict's recipient sets must not reach
    a report or a refusal (the agent channel rule). The status values are
    `FLOW_STATUSES` in `remora/flow/observe.py`; an unknown value is read as
    F1.
  - **F4 is grant-only.** A reviewer's approval of an F4 escalation is
    voided at every re-gate (`GRANT_ONLY_REASONS` in
    `remora/policy/composition.py`). §3.6 c lets only a
    DeclassificationGrant from a reader with the declassifier role release
    the payload, and a plain approval would bypass both conditions. Until
    IFC-08 an F4 item can be reviewed and nothing it covers runs. F5 and F6
    stay approvable: §3.11 sends integrity to a human.
  - **The principal.** Contexts belong to a principal, and the observation
    builders take only the tenant, so `_auth` records the authenticated
    principal for the request. A re-gate with no request principal, such as
    the async dispatch worker, gets `flow_context_unknown` and does not
    run. IFC-06 owns the dispatch-time check.
  - **No block outside the strict profile.** F3 fires under the strict
    profile only, as §3.7 says. Elsewhere a call whose ToolSpec has no
    `flow` block is `not_declared` and no rung fires.
  - **No resource ACL registry.** The server passes no resource ACL to the
    check, so every `resource_of` recipient is unresolved and every write
    in a flow context is F4. The attack evaluation measures that cost
    (NEGATIVE_RESULTS.md §87).
