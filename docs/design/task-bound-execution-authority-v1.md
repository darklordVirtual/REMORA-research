# Task-Bound Execution Authority v1

Status: design, approved 2026-08-30. Implements the first of the four gaps
found by the AGNTCY/A2A crosswalk of 2026-08-29. The second (durable
principal revocation) shipped separately as PR #502.

## The gap, stated exactly

REMORA binds an authorization to the exact call it was granted for. It does
not bind it to the *task* the call was made under.

Verified against `5576670` and re-verified at `9aeedc6`:

| structure | carries a task identity |
|---|---|
| `PolicyDecisionToken.AuthorizationContext` | no |
| `ExecutionLease` (20 signed fields) | no |
| `A2AGovernanceEnvelope` (16 fields) | no |

`task_id` and `context_id` appear nowhere in the governance or enforcement
path. The twelve files that match those names are all under
`remora/toolcall/`, where they identify benchmark cases, an unrelated
concept that must not be conflated with this one.

The consequence is precise and is not hypothetical. An approval granted for
task A authorises the identical call under task B. Every binding REMORA
checks still holds: same tool, same arguments, same tenant, same target,
same policy bundle, same ToolSpec. Nothing in the chain records that the
approver was answering a different question.

## Why now, and from three directions

Three independent lines arrived at the same change within two days of each
other. That convergence, not any one of them, is the argument.

**AGNTCY Identity WG, from the standards side.** Their 2026-08-25 analysis
states that Identity + TBAC today grants *standing* authority, and that
cryptographic binding to `taskId`, action/resource scope, lifetime,
delegation constraints and proof-of-possession remains open work on a task
authorization profile.

**The crosswalk, from the code side.** A row-by-row comparison of AGNTCY
against implemented REMORA produced `GAP` on exactly two rows: A2A `taskId`
and A2A `contextId`.

**Two papers, empirically.** *Do User-Authored Permission Policies Improve
Protection Against AI Agent Overreach?* (113 human subjects) found that a
reusable-policy setup blocked **less** overreach than either human-in-the-
loop or automatic review, because users chose `ask` and then approved
actions outside the original task. "The user approved" is measurably not
the same as "the task authorised". *Safety Does Not Compose* shows the
adjacent failure: safety signals distributed across agent iterations stay
under threshold individually while risk accumulates, because the monitor
resets each trajectory.

The two papers describe the same missing thing from opposite ends. One says
authority must not outlive its task; the other says risk must not be
forgotten between iterations of one task. Both need a durable identity for
"this task", and neither can be built without it.

## Scope

Three changes, one shared key. Explicitly **not** in scope: asymmetric
cross-organisation trust (the fourth crosswalk gap, which needs key
distribution and is better decided after we know whether we consume AGNTCY
Agent Badge), and proof-of-possession (REMORA claims none today, and
`grep` confirms it; the lease signature must never be presented as PoP).

### 1. Task identity in the three signed structures

`task_id` and `context_id` are added to `AuthorizationContext`,
`ExecutionLease` and `A2AGovernanceEnvelope`. All three must agree or the
call is refused.

`context_id` is the longer-lived identity: one agent conversation or
delegation context. `task_id` is one unit of work inside it. The pair
matches A2A's own vocabulary deliberately, so a REMORA family record can be
crosswalked against the profile AGNTCY is drafting rather than requiring a
translation table.

### 2. Declared operation at the A2A hop

`A2AGovernanceEnvelope` today has two extremes and nothing between them:
`requested_scope`, which is opaque strings, and `tool_call_hash`, which is
the exact call. The middle is a declared action and resource at the hop,
which is what a receiving implementation can check without knowing our
canonical hash.

The invariant is deny-only, matching REMORA's existing rules-only-exclude
discipline: `actual ⊆ declared ⊆ authorized`. A declaration can only narrow.
It never grants, and an absent declaration never widens.

### 3. Loop safety state

A durable, tenant-scoped record keyed on `(tenant_id, context_id)` holding
what a single call cannot see: denied intents, authority probes, tool
switches after a denial, and irreversible effects. Non-decaying within the
context.

This is the same shape as the revocation store shipped in #502, which is
the third instance of the pattern in this codebase after the consumed-jti
ledger and the lease nonce ledger. It reuses that pattern rather than
introducing a fourth bespoke store.

## The load-bearing constraint: existing signatures

`A2AGovernanceEnvelope._signable_payload` is `asdict(self)` over the whole
dataclass. Adding any field therefore changes the signed bytes of **every**
envelope, including ones already issued and verified. This is the same
constraint that governed the JCS work: historical bytes are what a verifier
recomputes, and changing them leaves the record unverifiable against the
code that verifies it.

The resolution is that **`None`-valued new fields are omitted from the
signable payload**. An envelope carrying no task identity produces
byte-identical bytes to one issued before this change, so every existing
signature still verifies. An envelope carrying a task identity produces
different bytes because it genuinely asserts something more.

`PROTOCOL_VERSION` stays `remora-a2a-governance/v1`. It is not bumped,
because a v1 verifier reading a v1 envelope still gets a correct answer.
What changes is what a *strict* deployment requires, which is configuration,
not format.

The same rule applies to `ExecutionLease` and `AuthorizationContext`, both
of which already have precedent for it: `AuthorizationContext.hash()` was
added in RMR-001 and is signed only when set.

## Refusal semantics

Fail closed, and specific about which failure occurred, because the three
are operationally different.

| condition | outcome |
|---|---|
| no task identity anywhere, non-strict profile | permitted, unchanged behaviour |
| no task identity, strict profile | `task_unbound` |
| identities present but disagreeing | `task_mismatch` |
| declared operation not a subset of authorized | `declared_operation_exceeds_authority` |
| loop safety state unreadable | raise, do not execute |

The last row follows the revocation store's rule and for the same reason: an
unreachable store must not be read as "nothing accumulated", or an outage
becomes the way around the control. It raises rather than voiding the
authorization, because voiding would destroy valid authority over a
transient fault.

`task_mismatch` is deliberately distinct from `context_unbound` and
`context_mismatch`, which RMR-001 already defines. A caller must be able to
tell "you never bound a task" from "you bound a different one".

## Components

| unit | responsibility |
|---|---|
| `remora/governance/task_identity.py` | `TaskIdentity(context_id, task_id)`, construction rules, equality, the omit-when-absent serialisation rule |
| `remora/governance/loop_safety.py` | `LoopSafetyState` and its store, following `revocation_store.py` |
| `remora/enforcement/token.py` | two fields on `AuthorizationContext`, folded into `hash()` and `differences()` |
| `remora/enforcement/lease.py` | two fields in the signed set |
| `remora/governance/a2a_envelope.py` | two fields, the declared operation, the subset check, the omit-when-None payload rule |

Each is independently testable and none reaches into another's internals.
`task_identity.py` is the only place that knows how a task identity is
formed and compared; the other four consume it.

## Testing

Beyond per-unit tests, four properties carry the design and each gets a test
that fails against today's code:

1. An approval granted under task A refuses the identical call under task B.
2. An envelope with no task identity produces byte-identical signable bytes
   to one issued before this change, so historical signatures still verify.
3. A declared operation outside the authorized scope refuses, and an absent
   declaration never widens.
4. Loop safety state accumulated in one process is visible to another, and
   an unreadable store refuses rather than reporting nothing accumulated.

Property 2 is the regression guard for the whole change. If it fails, the
change is unshippable regardless of the rest.

## Documentation and register obligations

Following the pattern the rest of REMORA uses, this work is not complete
until it resolves in the machine-readable registers.

| register | obligation |
|---|---|
| `docs/research/research_control_matrix_v1.yaml` | a new `RES-012` line: source, concepts, controls, code, tests, evidence, maturity, scope boundary |
| the same file, `bibliography.code_only` | the three new sources, each naming a code path where its anchor appears, since none is a reference in the paper |
| `docs/research/research_control_matrix.generated.md` | regenerated by `scripts/generate_research_control_matrix.py`, never hand-edited |
| `docs/09-related-work.md` | a new section, the narrative companion to `RES-012` |
| `docs/assurance/capability_register_v1.yaml` | re-audit of every capability citing a changed file, bound to the branch head and rebound to the squash commit after merge |
| `docs/design/aps-authority-profile-v0.md` | the profile's open-requirements table updated where task binding closes part of it |

`maturity` is `implemented_and_tested`. `in_code_citation` is `true` with
`citation_anchor` set to a name that appears verbatim in the cited module,
so the citation cannot drift from the code.

## What this does not establish

Task-bound authority is not proof-of-possession, and this design adds none.
It binds an authorization to a task; it does not prove the presenter holds a
key. Nothing here should be cited as closing the AGNTCY profile's PoP
requirement.

It also makes no claim about cross-organisation trust. The envelope remains
HMAC against a registry key, which the module's own docstring already
flags as a reference implementation. A record produced under this design
should continue to say semantic alignment, not wire-level interoperability,
until asymmetric signing lands.
