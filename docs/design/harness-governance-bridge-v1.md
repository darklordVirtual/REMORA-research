# Harness Governance Bridge v1

| Field | Value |
|---|---|
| Version | 1.0-draft, 2026-10-29 |
| Status | Proposal. Nothing here is implemented. No capability register status changes until the tests in section 9 exist and pass. |
| Owner | REMORA research: architecture and release governance |
| Source revision | `76bebaa` (master, 2026-10-27, merge of #1084) |
| Source register | `docs/assurance/capability_register_v1.yaml` |
| Depends on | `plan-premise-authority-v1.md`, `effect-contract-verification-v1.md` (slices 2 to 5), `derived-information-flow-control-v1.md` (CAPR-03 reads under labels) |
| Change control | Any implementation requires reviewed, gated PRs and evidence updates. |

## 1. Purpose

Agent harnesses now ship their own pre-execution controls. This document
specifies how REMORA composes with them instead of duplicating them, and
which REMORA mechanisms close the gaps those controls leave.

The working thesis, to be tested in section 8:

> The harness classifier decides whether an action is probably what the user
> wanted and does not look hostile. REMORA decides whether this principal
> holds an explicit, deployment-issued authority to cause this effect on this
> resource in its current state, and can prove the decision afterwards.

The two controls fail differently. They should be partitioned by scope and
composed monotonically, not stacked on every call.

## 2. Baseline

### 2.1 Harness controls (external, vendor-stated)

All figures in this subsection are stated by the vendor. None is REMORA
evidence and none may enter `claim_register_v1.yaml`.

| Control | Mechanism | Stated limits |
|---|---|---|
| Claude Code / Agent SDK permission chain | Hooks, then deny, ask, mode, allow rules, then `canUseTool`. A `PreToolUse` deny holds even in `bypassPermissions`. A hook `allow` does not skip deny or ask rules. | "Auto-approved tools never reach `canUseTool`". Bash rules match the command "as written". |
| Claude Code auto mode | A separate classifier model reviews non-read-only calls. It sees user messages, tool calls and CLAUDE.md. Tool results are stripped. A separate probe screens tool output for injection. | "does not guarantee safety"; "not a replacement for review on sensitive operations". Boundaries stated in conversation can be lost at context compaction. Vendor figures: FPR 0.4 % on 10,000 internal calls; FNR 17 % on 52 real overeager actions; FNR 5.7 % on 1,000 synthetic exfiltration cases. Most residual misses are consent-scope errors. |
| Managed Agents permission policies | `always_allow`, `always_ask` or `auto` per toolset or tool. Every `agent.tool_use` event carries `evaluated_permission` and `evaluation.reason_code`. An `always_ask` session "waits indefinitely". | "Custom tools are run by your application … not governed by permission policies." No argument-level rules. "`auto` is not a human checkpoint." |

### 2.2 REMORA today (at `76bebaa`)

| Need | REMORA mechanism | Register status |
|---|---|---|
| Explicit authority instead of inferred consent | Deployment-owned `intent_ref` resolved server-side (`workers/mcp-gateway/src/tools.ts`), task-bound authority | CAP-018 `WIRED_API_PATH` |
| Exact-call binding and single use | `ExecutionLease` (`remora/enforcement/lease.py:179`), canonical payload hash | CAP-003, CAP-004 |
| Credentials outside the agent | `GovernedToolDispatcher` (`remora/enforcement/lease.py:871`), MCP gateway operator token cannot approve | CAP-013 |
| Domain and cumulative limits | `LimitGuard` (`remora/enforcement/cumulative_limits.py:799`): `sum`, `count` and `change` meters, idempotency keys | CAP-031 `WIRED_API_PATH`, opt-in |
| Value predicates on trusted state | `ToolConstraint` (`remora/capabilities/constraints.py:106`) | opt-in |
| Information-flow control | `remora/flow/`, lease-bound recipients | IFC-05 DONE, IFC-06 and IFC-12 IN_PROGRESS |
| Separation of duties on approval | `approve_item` (`remora/execution/review_service.py:128`) | CAP-007, CAP-009 |
| Replayable decision record | `DecisionEnvelope` (`remora/governance/envelope.py:252`), hash-chained audit | CAP-005 |

### 2.3 Measured weaknesses on both sides

| Side | Finding | Source |
|---|---|---|
| Harness | Consent-scope errors dominate the residual misses. The vendor sample is small (n = 52). | vendor, section 2.1 |
| REMORA | It blocked 90 of 91 legitimate AgentDojo calls, and E1 completes one task more than refuse-all. | NEGATIVE_RESULTS.md §92 |
| REMORA | None of the 92 blocked calls is recoverable by a bounded lookup. All 92 lack a contract, intent vocabulary or source model. | NEGATIVE_RESULTS.md §93 |
| REMORA | In the OT battery, 13 of 15 cases resolve to `verify` and 2 to `escalate`. None reaches `accept` unattended. | `docs/integrations/mcp-gateway.md` |

The last row is a safety result and a product problem at the same time.
Under per-call approval, every governed write needs a person. That is the
review-fatigue failure mode the harness vendors cite as the reason for
building classifiers. A REMORA deployment that cannot reach `accept`
recreates the same problem one layer down.

## 3. The gaps, stated exactly

| ID | Gap | Today | Consequence |
|---|---|---|---|
| G1 | No current harness integration | `docs/integrations/agent_tool_hook.md` is marked HISTORICAL. `remora/agent_hook/` uses lexical drift and a local risk classifier. `examples/` covers LangGraph, AutoGen, CrewAI and OpenAI, not the Claude Agent SDK or Managed Agents. | Built-in harness tools (Bash, WebFetch, Write) can reach a governed resource outside the gateway, and nothing in the repository observes or refuses it. |
| G2 | Approval wait semantics | MCP has no wait. The gateway returns `pending_approval` and the agent polls `remora_proposal_status` (`workers/mcp-gateway/src/mcp.ts:269`). | The approval loop runs through the agent's context, costs tokens, and depends on the model polling correctly. Managed Agents already offers a native, indefinite wait that REMORA does not use. |
| G3 | No standing approval | Every `verify` needs a per-call human. `remora/capabilities/delegation.py:49`: "A delegation is for one nested step, not a standing grant." | Zero unattended `accept` in the OT battery (section 2.3). Review fatigue. |
| G4 | Harness verdicts discarded | The harness's own decision (`evaluated_permission`, `reason_code`, permission mode, hook result) is not recorded with the REMORA decision. | No joint record for incident review. No disagreement data for evaluation. |
| G5 | No declared scope partition | REMORA is evaluated as if it governs every call, reads included (§92). | REMORA spends its precision budget on calls a harness classifier handles with a low stated FPR, while the calls only REMORA can govern compete for the same review capacity. |
| G6 | No comparative evidence against harness controls | SAP v7 arms A0 to A3 have no harness-control arm. | No defensible statement of REMORA's marginal value over a current harness. |

Not re-specified here, but required by section 5.5 in the strict profile:
deployment-authoritative plan premises (`plan-premise-authority-v1.md`,
not implemented) and effect contract slices 2 to 5.

## 4. Invariants

These hold for every work package. A change that violates one is refused in review.

- **INV-HB-01 Monotone composition.** A harness signal can only make a REMORA
  decision more restrictive (meet). A harness `allow` never raises a REMORA
  decision. A REMORA deny is final in the harness: it is delivered as a
  `PreToolUse` deny or as a deny result, never as advice.
- **INV-HB-02 Boundary versus filter.** Only credential-holding paths (the MCP
  gateway, `GovernedToolDispatcher`) are an execution boundary. The hook tier
  of HB-2 is a filter. It is labelled as one in code, docs and evidence, and
  is never cited as enforcement of a capability.
- **INV-HB-03 A harness prompt is not a REMORA approval.** A click in a harness
  permission dialog, a `user.tool_confirmation`, or a message in the
  conversation never approves a REMORA review item. Approval happens only
  through `/v1/execution/approve` with an approver credential, or through a
  standing approval that was itself approved that way (HB-5).
- **INV-HB-04 No hard guard is weakened.** Standing approvals never cover
  ABSTAIN, ESCALATE, any `hard_guard_floor` rung
  (`remora/policy/decision_engine.py:161`), an F4 flow item (grant-only), or
  a tool without a signed ToolSpec.
- **INV-HB-05 Vendor figures stay external.** Harness metrics are recorded as
  observations with their source. They are never REMORA evidence.
- **INV-HB-06 Fail closed on governed scope.** If REMORA is unreachable, a
  call in the governed scope is refused. A call in the commons is left to the
  harness.

## 5. Components

### 5.1 HB-1 Scope partition profile (G5)

A deployment declares a `remora-harness-partition/v1` policy:

```yaml
schema: remora-harness-partition/v1
tenant: luftfiber-ot-pilot
governed:
  mcp_servers: [remora-gateway]          # reached only through the gateway
  resources:                             # canonical resources REMORA owns
    - "bms://site-a/**"
    - "tripletex://invoices/**"
  network_hosts: ["bms.site-a.internal", "api.tripletex.io"]
commons:
  description: "Everything not governed. Left to the harness controls."
bypass_patterns:                         # consumed by HB-2
  - kind: network_host
    from: governed.network_hosts
  - kind: mcp_server_not
    allow: [remora-gateway]
```

Requirements:

- **HB-1.R1** The linter refuses a partition where a credential for a
  governed resource is reachable from the commons. It cross-checks
  `docs/assurance/credential_topology.yaml` and the deployment registry.
- **HB-1.R2** Every governed resource maps to at least one signed ToolSpec.
  Otherwise the linter refuses it, because a resource with no tool cannot be
  governed and would only be refused.
- **HB-1.R3** The partition digest is signed into the policy bundle hash
  (`remora/policy/versioning.py`), so a lease records the partition it was
  judged under.

The partition is a deployment decision. Any utility gain it produces belongs
to the deployment configuration and is not reported as a REMORA result.

### 5.2 HB-2 Claude Code / Agent SDK hook adapter, filter tier (G1)

`remora/integrations/claude_harness/hook.py` replaces the archived
`remora/agent_hook` path for this use. It keeps `shell_ast.py`; the lexical
intent anchor and the local risk classifier are retired from it.

Behaviour on `PreToolUse`:

1. Parse the event (`tool_name`, `tool_input`, session id, permission mode).
2. If the call targets a governed resource **outside** the gateway, deny with
   reason `remora_governed_scope_bypass`. Examples: `Bash` or `WebFetch` to a
   governed host, a direct MCP server that is not `remora-gateway`, or a file
   write under a governed mount. Detection uses `shell_ast.py` for Bash and
   the HB-1 `bypass_patterns`.
3. Otherwise pass through. The hook returns no `allow`, so it never changes
   what the harness would have decided (INV-HB-01).
4. Emit a harness observation (HB-4) for every governed-scope decision.

Requirements:

- **HB-2.R1** Deny-only. A test asserts that no code path returns `allow`.
- **HB-2.R2** Fail-closed on governed scope (INV-HB-06). If the partition
  cannot be loaded, every call that matches a bypass pattern is denied.
- **HB-2.R3** Delivered through managed settings together with
  `permissions.deny` entries for the same hosts and servers. The hook alone
  can be removed by editing local settings. The managed deny rule cannot.
  `deploy/claude-harness/managed-settings.json` ships both.
- **HB-2.R4** Labelled `filter` in docs and the register (INV-HB-02). The
  evidence that it is complete is the bypass battery in section 8, not the
  hook's code.

Known limit, stated up front: a Bash command that builds a host name at run
time can evade static matching. That is why HB-1.R1 (no credential in the
commons) is the boundary and HB-2 is not.

### 5.3 HB-3 Managed Agents approval bridge (G2)

`remora/integrations/managed_agents/controller.py` runs in the customer
application. It is the only component that holds a REMORA operator
credential for the session.

Configuration:

- Governed tools are exposed to Managed Agents as **custom tools**, not as an
  MCP toolset. Custom tools are executed by the customer application, so the
  application is the dispatcher and no vendor policy runs in front of it.
- The governed MCP gateway is not attached to the Managed Agents session. The
  agent cannot reach governed tools by two routes.

Flow for one custom tool call:

```text
agent.tool_use (custom)            -> controller
controller  POST /v1/execution/assess   (exact input, intent_ref, session principal)
  accept   -> POST /v1/execution/execute -> tool result event
  verify   -> session stays idle (requires_action); review item in REMORA queue
              approver approves in REMORA (CAP-007)  -> execute -> result event
              review TTL expires (TTL-to-ABSTAIN)     -> deny result, reason stated
  escalate -> as verify, with the mismatch stated to the reviewer
  abstain  -> deny result with REMORA reasons (agent-channel rule applies)
```

Requirements:

- **HB-3.R1** The agent never sees a `proposal_id` or an approval reference.
  The wait happens in the session, not in the model's context. This closes G2
  for Managed Agents only. MCP clients keep the gateway's polling path.
- **HB-3.R2** The arguments executed are the arguments assessed. The
  controller stores the canonical tool call hash at assess time and refuses a
  mismatch before execute. This is the existing CAP-004 property, carried
  through.
- **HB-3.R3** A session interrupt while a review is pending does not strand
  the review item. The controller rejects it (`/v1/execution/reject`) with
  reason `harness_session_interrupted`.
- **HB-3.R4** The `evaluation` object of every `agent.tool_use` event is
  recorded as a harness observation (HB-4), including for non-governed tools.
- **HB-3.R5** Managed Agents' own `auto` policy may stay on for non-governed
  toolsets (commons). The controller does not consult it for governed calls.

### 5.4 HB-4 Harness observation record (G4)

Schema `schemas/harness_observation_v1.json`:

```json
{
  "schema": "remora-harness-observation/v1",
  "harness": "claude-code | claude-agent-sdk | claude-managed-agents | other",
  "harness_version": "string",
  "session_ref": "opaque, tenant-scoped",
  "tool_name": "string",
  "canonical_tool_call_hash": "sha256:...",
  "permission_mode": "default | auto | dontAsk | bypassPermissions | always_ask | ...",
  "vendor_evaluation": {"evaluated_permission": "allow|ask|deny|null",
                        "reason_code": "string|null"},
  "hook_decision": "deny | pass | null",
  "observed_at": "RFC 3339",
  "source": "controller | hook"
}
```

Requirements:

- **HB-4.R1** Appended to the audit chain bound to the `proposal_id` when one
  exists, otherwise to the session. Uses the existing `append_once` path.
- **HB-4.R2** By default an observation is record-only. Under the deployment
  flag `REMORA_HARNESS_SIGNAL=meet`, a vendor `deny` or `ask` on a call that
  REMORA would ACCEPT moves it to VERIFY with reason `harness_flagged`. It
  never moves a decision the other way (INV-HB-01). The rung gets an OPA
  golden case in `scripts/opa_conformance.py`.
- **HB-4.R3** The observation is client-supplied and unverified, in the same
  way as `on_behalf_of`. It is labelled `claimed`. It can only tighten a
  decision, so a forged observation can deny service to its own sender and
  cannot widen authority.
- **HB-4.R4** `GET /v1/execution/proposals/{id}/envelope` includes the
  observations, so the joint record exports with the existing evidence
  export (CAP-019).

### 5.5 HB-5 Standing approvals: bounded autonomy envelopes (G3)

This is the main utility lever and the main new risk, so it is specified
narrowly.

A standing approval is a signed record, approved through
`/v1/execution/approve`-equivalent authority by a principal who holds the
approver role for the tenant's risk tier. It pre-approves a class of calls
that REMORA would otherwise send to VERIFY for a stated reason.

```yaml
schema: remora-standing-approval/v1
id: SA-2026-0001
tenant: luftfiber-ot-pilot
signer: principal:approver/stian            # from the credential, never the body
tools: [set_setpoint]
resource_selector: "bms://site-a/ahu-*/supply_temp_sp"
intent_classes: ["WO:comfort_adjustment"]   # intent_ref must resolve to one of these
argument_constraints:                       # ToolConstraint predicates
  - "value >= 18.0 and value <= 23.0"
cumulative_limits_ref: "limits:sha256:..."  # REQUIRED, CAP-031 policy digest
required_premises: ["bms://site-a/ahu-*/status == RUNNING"]   # plan-premise v1, strict profile
covers_reasons: ["evidence_insufficient", "schema_unverified_verify"]
valid_from: 2026-11-01T06:00:00+01:00
valid_until: 2026-11-01T18:00:00+01:00      # max window [FREEZE]
max_uses: 40
```

Decision rule at assess:

1. The engine decides as today. Standing approvals are not consulted before
   the decision.
2. If the decision is VERIFY, every reason is in `covers_reasons`, the call
   matches tool, resource, intent class and argument constraints, every
   required premise holds on the trusted state reader, and the cumulative
   limit reservation succeeds, then the review item is created and approved
   in the same transaction. The recorded approver is the signer, and the
   record carries `standing_approval_id`.
3. Otherwise the call goes to normal VERIFY. A failed match is not a refusal.

Requirements:

- **HB-5.R1** It never covers ABSTAIN, ESCALATE, a hard-guard rung, F4, or a
  tool without a signed ToolSpec (INV-HB-04). A golden case per exclusion.
- **HB-5.R2** `cumulative_limits_ref` is mandatory. A standing approval
  without a limit is refused at creation (`standing_approval_unbounded`).
  This is what stops "within limits" from becoming "unlimited, one call at a
  time".
- **HB-5.R3** Separation of duties holds. The signer is not the proposer, not
  the delegate, and not the operator credential of the harness controller or
  gateway. This reuses the checks in `approve_item`.
- **HB-5.R4** Approval freshness re-gate applies at execute (CAP-007). The
  operator stop switch, principal revocation and authority revocation void a
  standing approval immediately (`/stop`, `/revoke-principal`,
  `/revoke-authority`).
- **HB-5.R5** In the strict profile, `required_premises` is mandatory for
  tools whose ToolSpec effect class is physical actuation. HB-5 for OT
  therefore depends on plan-premise v1 being implemented. Until then,
  standing approvals are limited to the research profile for OT tools.
- **HB-5.R6** `valid_until - valid_from` and `max_uses` have
  deployment-declared maxima, with a repository-wide ceiling [FREEZE: owner
  decision, proposed 24 h and 200 uses].
- **HB-5.R7** Every use is visible: the envelope names the standing approval,
  and the review queue shows uses against `max_uses`.
- **HB-5.R8** `remora/capabilities/delegation.py` is unchanged. A standing
  approval is an approval, not a delegation, and grants no authority the
  signer could not grant per call.

Risk, stated plainly: a standing approval is a pre-signed rubber stamp unless
its envelope is narrow. HB-5.R2 and HB-5.R5 make the envelope physical (a
limit and a state premise) rather than lexical. Whether that is enough is a
question for the evaluation in section 8, not for this document.

### 5.6 HB-6 Comparative evaluation (G6)

A pre-registered study, `docs/assurance/statistical_analysis_plan_v8_harness_composition.md`,
written and registered (OSF) before any model call.

Arms:

| Arm | Harness control | REMORA |
|---|---|---|
| V | Claude Code auto mode, or Managed Agents `auto` | none |
| R | default mode, every governed call prompts | gateway, per-call approval |
| VR | auto mode in the commons | HB-1 partition, HB-2 hook, gateway |
| VRS | as VR | plus HB-5 standing approvals |

Substrates:

1. The OT battery (`deploy/ot-pilot/run_ot_battery.py`), extended with one
   scenario family per gap in the harness controls:
   - S1 scope creep: a work order for one AHU, and the agent also adjusts a
     second;
   - S2 a domain invariant: a setpoint inside the tool schema but outside
     safe plant state;
   - S3 cumulative drift: many small moves;
   - S4 injection through sensor or work-order text;
   - S5 a custom tool in Managed Agents;
   - S6 a boundary stated in conversation and lost at compaction;
   - S7 bypass via Bash or WebFetch to a governed host.
2. The AgentDojo development split already used for §92, for comparability.

Primary measures, each per arm with cluster bootstrap over tasks:

- unauthorized effects executed (safety, primary);
- human approvals per completed benign task (review load, co-primary);
- benign tasks completed (utility);
- false blocks;
- decision latency p50 and p95;
- the harness/REMORA disagreement matrix from HB-4.

Predictions are registered with their falsifiers. Example: "VRS executes no
more unauthorized effects than R on S1 to S4, and needs at most half the
approvals per completed task." Any result, including VR or V dominating, is
recorded in NEGATIVE_RESULTS.md as the repository requires.

Budget and model [FREEZE: owner decision]. Proposed: Claude via the API, at
most 50 USD for the pilot stage, following the SAP v7 precedent.

## 6. Threat model additions

These go into `docs/assurance/threat_model_v1.md`.

| Threat | Control in this design | Residual |
|---|---|---|
| The user removes the hook from local settings | HB-2.R3: managed settings plus `permissions.deny`; HB-1.R1: no credential in the commons | A user with admin rights on the host can remove managed settings. The boundary is still the credential split. |
| The harness is compromised and forges observations | HB-4.R3: claimed, tighten-only | Denial of service to its own sender |
| Approval is laundered through the harness prompt | INV-HB-03 | None by design. Tested in section 9 (T-HB-07). |
| Confused deputy through a standing approval | HB-5.R1 to R5 | Inside the envelope, a misjudged envelope runs. Bounded by limits and premises. |
| Vendor classifier drift after a model update | HB-4 records `harness_version`; the evaluation is pinned to versions | Results do not transfer across versions |
| Two routes to one tool in Managed Agents | HB-3: the gateway is not attached to sessions that use the controller | A configuration error. The HB-1 linter checks the session template. |

## 7. What this does not claim

- It does not claim that REMORA outperforms harness classifiers on general
  risk classification. It does not compete there.
- It does not claim that the hook tier enforces anything (INV-HB-02).
- It does not claim that a standing approval is safe. It claims only that its
  envelope is enforced, bounded by limits and premises, and recorded.
- It does not claim regulatory conformance. The record supports EU AI Act
  logging and human-oversight documentation (articles 12 and 14) in the way
  `docs/governance/eu_ai_act_nsm_mapping.md` already describes. In Norway the
  regulation is not yet in force; national implementation is pending.

## 8. Evaluation gate

No release profile may list HB-5 as enabled until HB-6 has run on the OT
battery and its primary safety measure for VRS is not worse than R. The
result is recorded either way.

## 9. Work packages

| WP | Priority | Files | Acceptance tests |
|---|---|---|---|
| HB-01 Partition profile and linter | P0 | `remora/integrations/harness/partition.py`, `schemas/harness_partition_v1.json`, `scripts/check_harness_partition.py` | T-HB-01: a partition with a governed credential reachable from the commons is refused. T-HB-02: a governed resource without a ToolSpec is refused. T-HB-03: the partition digest is in the bundle hash and in the lease. |
| HB-04 Harness observation record | P0 | `remora/integrations/harness/observation.py`, `schemas/harness_observation_v1.json`, `servers/execution_api.py` (envelope) | T-HB-04: an observation is chained to the proposal and exported. T-HB-05: under `meet`, a vendor `deny` turns ACCEPT into VERIFY; no input turns VERIFY into ACCEPT (Hypothesis property). OPA golden case. |
| HB-02 Claude Code / Agent SDK hook, filter tier | P0 | `remora/integrations/claude_harness/hook.py`, `deploy/claude-harness/managed-settings.json`, `docs/integrations/claude-harness.md` | T-HB-06: no path returns `allow`. T-HB-07: S7 bypass cases (curl, wget, python -c, WebFetch, a direct MCP server) are denied. T-HB-08: an unloadable partition denies governed-scope calls. T-HB-09: the managed `permissions.deny` blocks the same hosts with the hook removed. |
| HB-03 Managed Agents approval bridge | P1 | `remora/integrations/managed_agents/controller.py`, `examples/managed_agents_governed.py` | T-HB-10: verify keeps the session idle with no proposal id in the agent channel. T-HB-11: changed arguments refuse before execute. T-HB-12: an interrupt rejects the pending item. T-HB-13: TTL expiry returns a deny result. T-HB-14: a `user.tool_confirmation` never approves a review item (INV-HB-03). |
| HB-05 Standing approvals | P1, research profile only until section 8 | `remora/execution/standing_approval.py`, `schemas/standing_approval_v1.json`, `servers/execution_api.py` (`/standing-approvals` create, list, revoke), `remora/execution/review_service.py` | T-HB-15: one golden case per INV-HB-04 exclusion. T-HB-16: creation without a limit is refused. T-HB-17: the signer equal to the proposer, the delegate or the operator is refused. T-HB-18: stop, revoke-principal and revoke-authority void a standing approval. T-HB-19: a call past the limit falls to VERIFY and does not run. T-HB-20: a failed premise falls to VERIFY. T-HB-21: `max_uses` is atomic under concurrency (Postgres job). T-HB-22: strict profile plus a physical-actuation tool plus no premise is refused at creation. |
| HB-06 Comparative study | P1 | `docs/assurance/statistical_analysis_plan_v8_harness_composition.md`, `deploy/ot-pilot/` scenario families S1 to S7, `experiments/harness_composition/` | Pre-registration filed before the first model call. Results and negative results committed. |

## 10. Release order

1. HB-01 and HB-04. Both are pure additions and change no decision with flags off.
2. HB-02. It is a filter, but it closes the most visible bypass path for
   Claude Code users of the OT pilot.
3. HB-06 arms V, R and VR, before HB-05 exists, to establish the baseline.
4. HB-03.
5. HB-05, in the research profile.
6. HB-06 arm VRS, then the section 8 gate.

## 11. Owner decisions required

- [FREEZE] HB-5.R6 ceilings: 24 h and 200 uses proposed.
- [FREEZE] HB-06 budget, model and OSF registration.
- Whether `REMORA_HARNESS_SIGNAL=meet` is the default in the strict profile.
  The proposal is no: record-only by default, so a vendor change cannot alter
  REMORA decisions without a deployment decision.
- Whether HB-03 also supports MCP toolsets in Managed Agents. The proposal is
  no for v1, because two routes to one tool is the failure HB-3 exists to
  avoid.

## 12. Sources

External, vendor documentation, read 2026-10-29:

- Claude Code permission modes and auto mode: https://code.claude.com/docs/en/permission-modes
- Agent SDK permissions: https://code.claude.com/docs/en/agent-sdk/permissions
- Managed Agents permission policies: https://platform.claude.com/docs/en/managed-agents/permission-policies
- Auto mode announcement: https://claude.com/blog/auto-mode
- Secondary summary of the vendor's classifier figures: https://www.digitalapplied.com/blog/claude-code-auto-mode-classifier-numbers-published
- Independent critique: https://simonwillison.net/2026/Aug/8/auto-mode/

Internal: NEGATIVE_RESULTS.md §87, §92, §93, §96, §97;
`docs/integrations/mcp-gateway.md`;
`docs/design/derived-information-flow-control-v1-status.md`;
`docs/design/plan-premise-authority-v1.md`;
`docs/design/effect-contract-verification-v1.md`.
