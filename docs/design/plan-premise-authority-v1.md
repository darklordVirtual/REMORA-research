# Deployment-Authoritative Plan Premises v1

Status: proposal, written 2026-10-01. Nothing here is implemented. No
capability register status changes until the tests in the requirements table
exist and pass.

The finding this document answers was reported by an external party. The report
is not the evidence. The behaviour was reproduced against this repository at
master `35db242`, and every line reference below points at committed code in
this repository. No HEIMEL or VALO source was read, and no implementation from
either is copied here. The mechanism proposed is an application of an existing
REMORA rule (Q8.1) to a module that predates it.

## The gap, stated exactly

Checked against master at `35db242`.

| Concern | Today | Gap |
|---|---|---|
| Which resources a write depends on | `PlanBinding.depends_on`, built only from what the caller passes (`remora/governance/plan_binding.py:67`, `:75`) | No deployment-authored operand exists anywhere in the repository |
| A dependency whose revision moved | Refuses `stale_plan` (`remora/governance/plan_binding.py:105`) | Only for resources the planner placed in `depends_on` |
| A read the write does not depend on | Re-read, reported as `moved_other_reads`, never refuses (`remora/governance/plan_binding.py:122`) | A safety-critical premise parked here moves freely |
| A resource the plan never read | Not represented | Cannot be compared, so cannot refuse |
| A call carrying no plan at all | `_plan_refusal` returns `None` when the lease has no `plan_binding_hash` (`remora/enforcement/lease.py:976`) | No `require_plan_binding` switch beside `require_capability_set` (`remora/enforcement/lease.py:708`) |

The consequence is narrow and exact. `PlanBinding` alone does not stop a write
whose safety premise was omitted from `depends_on`. Other layers may still stop
it when the deployment configured them: a `ToolConstraint` value predicate read
through the trusted state reader (`remora/capabilities/constraints.py:106`), or
a procedure contract (`remora/governance/procedure.py:130`). Both are opt-in,
and neither expresses freshness relative to a plan revision.

## This boundary is already documented

Four committed places state it. The caveat on CAP-020,
`docs/assurance/capability_register_v1.yaml:561`, reads:

> Plan dependencies are declared by the plan's author, and the plan is signed
> into the lease at execution, not into the ACCEPT token.

The module docstring, `remora/governance/plan_binding.py:30`, reads:

> Which reads a write depends on is declared by whoever builds the plan, and an
> under-declared dependency is not detected.

The same sentence appears at `docs/research/research_shelf_v1.yaml:855`
(SHELF-032) and `docs/research/research_control_matrix.generated.md:280`.

So the report identifies a scope boundary REMORA publishes, not a defect
against its specification. That distinction belongs in any public account of
this exchange. It is also not a reason to leave the boundary where it is.

## The rule this applies

Q8.1, closed on 2026-09-28 under WS8, states the principle already:

> A capability set is derived from trusted state, never from the agent.

Q7.5 built `PlanBinding` before WS8 existed, and its dependency set still comes
from the planner. This proposal extends the Q8.1 rule to plan premises. Stated
as an invariant:

```
effective_dependencies = required_dependencies(tool, effect)
                       | plan.declared_dependencies
```

A planner may enlarge the set it will be held to. It is never authoritative
over the minimum. The union is computed from the signed ToolSpec and the
capability policy, so omitting a premise, moving it out of `depends_on` or
sending `depends_on=[]` all leave the required part intact.

## What exists and is reused rather than rebuilt

| Part | Existing mechanism |
|---|---|
| Signed carrier for the plan digest | `plan_binding_hash`, signed when set (`remora/enforcement/lease.py:201`, `:291`) |
| Digest comparison at dispatch | `hmac.compare_digest` against the lease field (`remora/enforcement/lease.py:980`) |
| Fail-closed revision reader | `plan_state_unverifiable` when the reader is absent or raises (`remora/enforcement/lease.py:984`, `remora/governance/plan_binding.py:124`) |
| Refusal position before the effect | `_plan_refusal` inside the pre-nonce chain, after `verify()` (`remora/enforcement/lease.py:1287`) |
| Deployment requirement read from the signed ToolSpec by tool name | `DownstreamCeiling` (`remora/capabilities/ceiling.py:67`, parsed at `remora/toolcall/toolspec.py:118`, bound at `servers/execution_api.py:1317`) |
| Deployment-authored policy with a trusted state reader | `ToolConstraint` and `StateReader` (`remora/capabilities/constraints.py:106`, `:43`, evaluated at `remora/enforcement/lease.py:903`) |
| Wire forwarding for plan fields | `remora/execution/remote_dispatch.py:166` |

The only missing piece at `remora/enforcement/lease.py:976` is an operand
saying which resources this tool must have declared.

## Deviations from the shape proposed to us

1. No new top-level contract object. The requirement goes into ToolSpec v2 and
   the capability policy, both already signed and already digested into the
   lease. A third contract would duplicate `ToolConstraint`.
2. Refusal reasons are `snake_case` codes, matching `stale_plan` and
   `capability_not_allowed`.
3. Value predicates stay in `ToolConstraint` (Q8.4). This item governs
   declaration and freshness. Mixing the two would make a predicate failure
   indistinguishable from a stale premise in the refusal reason.
4. The evaluation point is the existing pre-nonce chain. REMORA already
   re-reads premises immediately before the effect, so no new timing concept is
   introduced.

## Requirements

Proposed as workstream WS9. WS8 is the last one allocated
(`docs/design/remora-quality-program-v1.md:156`).

| ID | Requirement | Acceptance criterion |
|---|---|---|
| Q9.1 | The required dependency set comes from deployment-authored, signed state and never from the caller. | A `required_plan_dependencies` field on ToolSpec v2 and in the capability policy YAML. A resolver returns the union with the plan's declared set. The resolved set is covered by the lease digest. |
| Q9.2 | A required dependency the plan did not read refuses. | New code `plan_premise_undeclared`, raised before the nonce is consumed, with the tool never called and the nonce left spendable. |
| Q9.3 | A required dependency whose revision moved refuses. | `stale_plan`, by the path that exists today, with no change to its meaning. |
| Q9.4 | A required dependency whose revision cannot be read refuses. | `plan_state_unverifiable`, including when the deployment bound no reader at all. |
| Q9.5 | A deployment may require that a tool carry a plan. | `require_plan_binding` on `GovernedToolDispatcher` and an env var beside `REMORA_REQUIRE_CAPABILITY_SET`. A call with no plan refuses `plan_binding_required`. |
| Q9.6 | A planner may declare more than the minimum. | A plan whose `depends_on` is a strict superset of the required set runs, and the extra entries refuse on movement exactly as declared ones do. |
| Q9.7 | The resolved set cannot be stripped from a lease. | `tests/test_lease_verification_completeness.py` lists the new field in `SIGNED_WHEN_SET`, and adding it to an unbound lease breaks the signature. |
| Q9.8 | The API path binds what the library refuses. | A server-path test on `/v1/execution/dispatch-leased`, and forwarding across the custody split, which the WS8 review found missing once already (`remora/execution/remote_dispatch.py:157`). |

## How each requirement is referenced

Each row names the code that must change, the artifact that records the run and
the test that pins it. The literature column cites the shelf entry, which holds
the verified source record; this table does not restate those authors' results.

| ID | Code | Artifact | Test | Literature |
|---|---|---|---|---|
| Q9.1 | `remora/governance/plan_binding.py`, `remora/toolcall/toolspec.py`, `schemas/tool_spec_v2.yaml`, `remora/capabilities/resolver.py` | `conformance/plan-premise-authority-v1/run-record.json` | `tests/test_plan_premise_authority.py` | SHELF-009, SHELF-001 |
| Q9.2 | `remora/enforcement/lease.py` | same run record | `tests/test_plan_premise_authority.py` | SHELF-032 |
| Q9.3 | `remora/governance/plan_binding.py` | same run record | `tests/test_plan_binding.py` (unchanged behaviour) | SHELF-032 |
| Q9.4 | `remora/enforcement/lease.py` | same run record | `tests/test_plan_premise_authority.py` | SHELF-027 |
| Q9.5 | `remora/enforcement/lease.py`, `servers/execution_api.py` | same run record | `tests/test_ws9_server_path.py` | SHELF-009 |
| Q9.6 | `remora/governance/plan_binding.py` | same run record | `tests/test_plan_premise_authority.py` | SHELF-029 |
| Q9.7 | `remora/enforcement/lease.py` | none | `tests/test_lease_verification_completeness.py` | SHELF-027 |
| Q9.8 | `servers/execution_api.py`, `remora/execution/remote_dispatch.py` | same run record | `tests/test_ws9_server_path.py`, `tests/capabilities/test_ws8_review_findings.py` | SHELF-008 |

The shelf entries are all recorded `VERIFIED_RETRIEVED` in
`docs/research/research_shelf_v1.yaml`. They include SHELF-032 dependency-scoped
plan validity (`:843`), SHELF-008 capabilities bound to data rather than only to
tools (`:201`), SHELF-009 programmable fine-grained privilege policy (`:231`)
and SHELF-001 declarative tool policy (`:46`).

The remaining references are SHELF-027 stateful authorization for delegated
agent effects (`:718`), SHELF-012 temporal constraints (`:299`) and SHELF-029
how strongly task state should influence an agent (`:784`). SHELF-032 is the
source `PlanBinding` was built from. The case in Q9.2 is the one its mechanism
leaves to the plan's author.

## Proposed conformance profile

A new suite `conformance/plan-premise-authority-v1/` in the vector and adapter
shape used by `conformance/non-transitivity-of-authority-v1/`: `vectors.json`,
`adapter.py`, `adapter_skeleton.py`, `adapter_remora.py`, `run_conformance.py`
and a committed `run-record.json`, with `README.md` registered in
`docs/assurance/document_register_v1.yaml`.

The vectors are written here, before any run. They cover:

- a required premise declared and unmoved;
- a required premise declared and moved;
- a required premise the planner omitted from `depends_on`;
- a required premise the planner omitted from `reads`;
- an empty `depends_on`;
- a planner-declared superset;
- a required premise whose reader raises;
- a tool with no required premises, which must behave exactly as it does today.

Outcomes are refusal classes, not scores, and `UNSUPPORTED` is neither pass nor
fail.

## What this does not establish

This document makes no claim about HEIMEL or VALO. Neither was run here, and
their reported results stay theirs.

It does not establish causal completeness. The required set is a declaration a
deployment writes, and a premise nobody declared is still undetected. The
change moves the declaration out of the planner's trust domain; it does not
discover premises.

It does not validate deployment-supplied inputs. The revision reader and the
required-dependency declaration both come from the deployment and are compared,
never interpreted. The CAP-020 caveat survives in narrowed form, and the
narrowing is recorded only once the tests exist.

Until implementation, CAP-020 keeps its present status and caveat, and SHELF-032
keeps its `remora_status` as written.
