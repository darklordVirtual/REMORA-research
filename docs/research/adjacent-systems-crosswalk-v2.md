# Adjacent-systems crosswalk v2 — corrected against HEAD

Status: research note. Supersedes crosswalk v1 (unpublished working document,
2026-08-23). v1's errors are reproduced here rather than deleted, because a
correction that hides what it corrected teaches nothing.

Baseline commit: `3bb5797` (`fix(enforcement): the jti ledger was in-process on
the Cloudflare deployment (#350)`).

Method: v1 was written from the comparison projects inward and checked REMORA
only where a comparator suggested a gap. That is the wrong direction, and it
produced four false gaps and one false strength. v2 reads REMORA's
implementation first and asks what the comparison projects still add.

---

## 1. Corrections

Each correction gives the v1 claim, the evidence at HEAD, the corrected
reading, and what follows architecturally.

### 1.1 "No taint dimension" — FALSE

**v1 claim.** Listed as a CRITICAL gap: *"REMORA has no taint dimension at
all. This is the largest single capability gap in the crosswalk."*

**Evidence at HEAD.**

- `remora/policy/observation.py:187`: `argument_tainted: bool`, documented as
  "the call's arguments derive from untrusted input, never auto-accept".
- `remora/policy/observation.py:293`: `untrusted_controlled_arguments:
  tuple[str, ...]`, documented as meaningful only with `argument_tainted`, and
  as distinguishing untrusted content that is *authorising* from untrusted
  content that is merely *informing*.
- `remora/policy/decision_engine.py:192-207`: a tainted-argument floor with
  sink discrimination via `_controls_sensitive_argument()`, and a
  tier-dependent branch recorded as an explicit decision (issue #40,
  2026-07-30).
- `remora/policy/decision_engine.py:1263`, `1715`: the check is a recorded
  reason (`tainted_argument_check`, `TAINTED_ARGUMENT_VERIFY` /
  `taint_floor`), not an internal heuristic.
- `tests/test_untrusted_provenance.py`, `tests/test_tainted_argument_approval_contract.py`.

**Corrected reading.** REMORA has call-level untrusted-provenance control with
sink discrimination, a named refusal reason, and a contract test. On the
specific axis of *sink constraints* it is comparable to Janus. v1 was wrong.

**What is actually missing.** Two things, and neither is "taint":

1. **Persistence.** `Observation` describes one call. Nothing carries
   provenance from call *n* to call *n+1*. A trajectory that reads
   attacker-controlled content in one call and acts on it three calls later
   presents as untainted at the sink.
2. **Caller authority over the label.** `Observation.from_record()`
   (`observation.py:509`) builds `argument_tainted` from a caller-supplied
   record. The agent (or whatever assembles the observation) is currently
   authoritative for its own taint status.

Of the two, (2) is the more serious and was invisible to v1's framing. Adding
more taint sources to a label the caller controls strengthens nothing.

**Architectural consequence.** The work is *not* a taint subsystem. It is
moving the authoritative provenance state out of the caller and into tenant
state bound into the authority object. Deferred to ADR-C; see §4.

### 1.2 "No multi-agent delegation" — FALSE

**v1 claim.** *"REMORA has no multi-agent delegation story at all."* ADCS was
proposed as filling an absence.

**Evidence at HEAD.** `remora/governance/a2a_envelope.py` (566 lines),
`tests/test_a2a_envelope.py` (663 lines), CAP-006. The implementation carries:

- identity and accountability, verification failing closed when accountability
  is absent;
- a delegation chain with capability attenuation on subset semantics;
  verification *rejects any link that widens scope*, and wildcards are
  deliberately unsupported because a wildcard grant cannot be attenuated
  safely (`a2a_envelope.py:42`);
- per-link signatures with `kid`, verified against a key registry, so the
  envelope issuer cannot fabricate delegation history;
- a mandatory `audience`, a per-envelope `nonce` checked against a replay
  guard, and an optional `tool_call_hash` binding the envelope to exact
  arguments.

**Corrected reading.** REMORA already implements principal-bound keys,
attenuation, replay protection and payload binding. v1 was wrong. Note also
that v1's headline recommendation ("adopt decision-os-min's attenuation, it is
the strongest single idea available to steal") was largely redundant: REMORA
already has intersection-style narrowing on the A2A path. What decision-os-min
genuinely has and REMORA does not is *asymmetric* signing (§1.6, ADR-A).

**Corrected framing of ADCS.** An **interoperability profile** for an existing
capability, not a replacement for an absent one. The open question is whether
ADCS's chain representation, budget propagation and cycle prevention can be
emitted and consumed at REMORA's boundary without displacing the internal
model. Not implemented; recorded as P1 research.

### 1.3 "Add a Merkle audit layer" — FALSE PREMISE

**v1 claim.** Proposed adopting Microsoft's Merkle chain and commitment records
"as if none existed", and rated the work "a week".

**Evidence at HEAD.** `remora/audit/merkle.py`, `remora/audit/checkpoint.py`
(277 lines: `merkle_root_from_hex_leaves`, `tenant_chain_leaves`,
`envelope_chain_leaves`, `Checkpoint` with `prev_checkpoint_root`,
`make_checkpoint`, `verify_span`, `verify_checkpoint_chain`,
`sign_checkpoint`), `remora/audit/anchor.py`,
`docs/enterprise/audit-anchoring-guide.md`.

**Corrected reading.** The Merkle layer, chain-linked checkpoints, signing
payloads and tenant-chain adapters all exist. More to the point, the guide
already states the limitation v1 "discovered", and states it more precisely
than v1 did: external transparency-log / WORM publishing is *"not implemented
(slice 2; REM-025 remains open)"*, and the guide explicitly declines to claim
tamper resistance without it. REMORA's own claim discipline had already
recorded this correctly.

**What is actually missing.** Only the publisher and the external verifier. The
sharp question is the one v1 never asked: *can an operator with full write
access to REMORA's own storage rewrite history and produce a replacement
internally-consistent chain?* Today, yes; every root is recomputable from data
that same operator controls. Recorded as ADR-E; not implemented in this pass.

### 1.4 "TOCTOU resistance absent" — OVER-GENERALISED

**v1 claim.** Property F recorded UNTESTED at evidence tier NONE, described as
"REMORA's weakest row".

**Evidence at HEAD.** `ExecutionLease` (`remora/enforcement/lease.py:108-140`)
binds, and signs: `decision`, `tenant_id`, `actor_identity`, `tool_name`,
`tool_args_hash`, `target_environment`, `policy_bundle_hash`, `nonce`,
`issued_at`, `expires_at`, `tool_contract_bundle_hash`,
`intent_authority_hash`, `toolspec_hash`, `toolspec_version`, and the proposal
identity. `verify_binding()` re-checks each with `hmac.compare_digest` and
returns named refusals (`toolspec_hash_mismatch` and siblings) immediately
before execution.

**Corrected reading: F must be split.**

| Class | Drift | Covered at HEAD |
|---|---|---|
| **F1** internal authorization-state | arguments changed | yes — `tool_args_hash` |
| | target/environment changed | yes — `target_environment` |
| | actor changed | yes — `actor_identity` |
| | tenant changed | yes — `tenant_id` |
| | policy bundle changed | yes — `policy_bundle_hash` |
| | ToolSpec declaration changed | yes — `toolspec_hash` + `toolspec_version`, signed |
| | tool contract bundle changed | yes — `tool_contract_bundle_hash` |
| | intent-authority source changed | yes — `intent_authority_hash` |
| | proposal changed | yes — bound proposal identity |
| **F2** external implementation/runtime | remote MCP server schema changed | **no** |
| | tool implementation changed under an unchanged declaration | **no** |
| | remote server identity changed | **no** |
| | deployment/container image changed after authorization | **no** |
| | Worker version / deployment generation changed | **no** |

F1 coverage is substantial and evidenced; v1 credited none of it. F2 is
genuinely open: no lease field names the runtime that will execute. The
statement "TOCTOU resistance absent" must not be made. The statement "F1
covered at the listed scope, F2 open" is the accurate one.

### 1.5 E2 and H were conflated — CORRECTED

v1 folded ambient bypass and runtime trust-base integrity into a single
candidate property H. They answer different questions and fail differently.

- **E2, Ambient / Alternate-Path Execution Integrity.** *Can the governed
  actor reach the protected effect by a path that does not traverse the PEP?*
  Failure mode: the decision was never consulted. decision-os-min's TM-A probe
  is evidence for this and only this.
- **H, Runtime Trust-Base Integrity.** *Was the authority decision evaluated
  against the same runtime/deployment trust base that actually executed?*
  Failure mode: the decision was consulted, was correct, and executed somewhere
  else. Cloudflare rollout identity is evidence for this and only this.

A system can pass E2 completely and fail H completely. See §3 for the
discriminating test, which determines whether H earns its place at all.

### 1.6 "The container contains no credentials" — FALSE, AND BACKWARDS

**v1 claim.** Recorded as REMORA's strongest boundary property and as
ALREADY STRONGER than every comparator: *"No database credential exists in the
container at all."*

**Evidence at HEAD.** `workers/mcp-gateway/src/index.ts:37-97`, the container's
`envVars` are populated from Worker secrets including:

```
REMORA_PG_DSN            REMORA_GITHUB_TOKEN       REMORA_API_TOKENS
REMORA_PDP_SIGNING_KEY   REMORA_LEASE_SIGNING_KEY
REMORA_AUDIT_SIGNING_KEY REMORA_ENVELOPE_SIGNING_KEY
```

**Corrected reading.** The narrow claim that survives is: *knowledge-graph state
is reached through a Worker binding (`outboundByHost`), and a binding cannot be
read out of the process and replayed elsewhere.* That is true, and it is worth
keeping; but it covers one state path, not the container, and it was
generalised into a claim the code contradicts.

**The finding v1 inverted.** The execution container holds
`REMORA_PDP_SIGNING_KEY` and `REMORA_LEASE_SIGNING_KEY`. Both are symmetric.
Therefore **the component that enforces authority also holds the material to
mint it.** The PDP→PEP trust boundary is cryptographically expressible today
and is not expressed: compromise of the executing container is not merely a
replay risk, it is an authority-forgery risk.

This is the single most important correction in v2. It reframes ADR-A: the
priority is not "HMAC is a weaker algorithm" but "the verifier is the issuer".
Changing the algorithm without separating custody would improve nothing.

**Defensible goal.** Not "the container holds no credentials", but:

> The remote agent never receives a credential capable of bypassing REMORA, and
> the executing component never holds material capable of minting authority.

The first clause is about E2; the second is ADR-A. They are separate claims
requiring separate evidence.

---

## 2. What survives from v1

Not everything was wrong. These hold up against HEAD:

- **Effect verification is unmatched in the comparison set.** Five-valued
  outcome space, cross-language digests pinned. Narrow (graph writes), and
  honest about it.
- **The bundle-hash binding of tool metadata** is a genuine differentiator no
  comparator replicates.
- The four-decision model, specifically ABSTAIN ("nothing here for a human
  to decide") versus ESCALATE ("a human must decide"), has no equivalent in
  the set.
- **Invariant's dataflow claim does not hold at code tier.**
  `analyzer/runtime/input.py` builds a sequential graph per top-level list;
  `has_flow(a, b)` returns temporal precedence, and the canonical test is named
  for calling something *after* something. Re-checked; the finding stands. It
  is also a caution that applies to this document: v1 made the same class of
  error about REMORA, in the opposite direction.
- **Do not build a general MCP gateway.** Unchanged.
- **AgentGovBench is a useful corpus with a disclosable conflict of interest.**
  Unchanged.
- **Janus's honesty about granularity** is the model to copy for §4's non-claim.

---

## 3. Is candidate H reducible to A–G?

The discriminating case, per the brief:

> At authorization: ToolSpec T1, policy P1, runtime R1. No drift before
> authorization. At execution: arguments unchanged, target unchanged, policy
> still P1, ToolSpec *declaration* still T1; but the runtime implementation is
> R2.

Walked against HEAD:

- C (Exact-Call Integrity): passes. `tool_args_hash` matches; the call is
  the authorized call.
- F1: passes. Every bound field matches, including `toolspec_hash` and
  `toolspec_version`: the *declaration* did not change.
- E: passes. The call traversed the PEP; no alternate path was used.
- E2: passes. No ambient bypass occurred.

Every existing property reports success while the action executed against an
implementation nobody authorized. **H is not reducible to A–G as REMORA
implements them**, because no lease field names the executing runtime.

Note the relationship to F2: H is the *authority-side* statement of the same
underlying fact that F2 states from the *drift* side. They may ultimately merge.
The conservative move is to record H as a **candidate with a discriminating
test**, and to require an implemented `RuntimeTrustBaseIdentity` bound into the
lease before either is claimed. Neither is claimed in this pass.

**Proposal for `docs/benchmarks/agent-authority-conformance-v0.1.md`.** Items 1
and 3 were applied on 2026-08-30 once the condition in item 3 was met; item 2
still awaits review. Vocabulary changes need review, not a silent edit:

1. Record F with explicit scope: `F1` internal authorization-state drift,
   `F2` external implementation/runtime drift. Do not renumber A–G.
2. Record E2 as a **declared scope under E**, not a new letter. It answers the
   same question E asks (did the effect traverse the boundary) at a different
   layer.
3. Hold H as a candidate. Admit it only when the discriminating test above runs
   against an implementation and fails without it.

**Condition met, 2026-08-30.** `remora/enforcement/runtime_identity.py` binds a
`RuntimeTrustBaseIdentity` hash into `ExecutionLease`, signed, and
`GovernedToolDispatcher` compares it against the executing process's own cached
identity before the nonce is consumed.
`tests/test_runtime_trust_base_binding.py` runs the case above. With the
comparison removed, the mismatched-runtime call executes and four tests fail.
With it in place, dispatch refuses on `runtime_identity_mismatch` while the
lease itself still verifies. That is the non-reducibility claim asserted in
code rather than in prose. H stays a candidate with a passing discriminating
test; it is not promoted to an eighth property in v0.1.

The binding is self-declared. The executor reads its identity from its own
environment once at startup, so nothing in the call path can present a
different one. A process that controls its environment can still misdeclare.
That closes execution by the *wrong* runtime, not by a *lying* one. External
attestation remains unimplemented and unclaimed.

---

## 4. Corrected gap list

Ranked by whether evidence supports acting now.

| Gap | Status at HEAD | Action this pass |
|---|---|---|
| PDP signing key held by the executing container | confirmed, `index.ts:76-77` | **ADR-A, implemented** |
| `ExecutionLease` nonce ledger is in-process | confirmed, `lease.py:387-398`, self-documented, REM-025 | **ADR-B, implemented** |
| F2 / runtime identity unbound | confirmed | ADR-D, **implemented 2026-08-30** |
| Trajectory provenance not persisted; caller authoritative for taint | confirmed | ADR-C, **not implemented** |
| External audit anchoring absent | confirmed, already correctly scoped by REMORA | ADR-E, **not implemented** |
| ToolSpec not automatically authoritative on the cloud path | confirmed, `index.ts:137-146` documents the deliberate non-pinning | not implemented; the existing posture is honest, not a defect |
| Effect verification narrow | confirmed | not implemented |
| No external benchmark result | confirmed | not implemented |

The last five are recorded, not built. This pass implements two properties
because two are what the evidence supports finishing, with adversarial tests
and claim updates, in one reviewable change.

---

## 5. Method note

v1's failure mode is worth recording as its own finding, because it is the
failure mode this repository exists to guard against. Every one of the four
false gaps came from reading a comparator's README, forming a hypothesis about
REMORA, and not opening REMORA's source. The taint gap was contradicted by a
test file whose name says what it tests. The delegation gap was contradicted by
a 566-line module. The Merkle gap was contradicted by a document that had
already stated the limitation more precisely.

The credential claim is the instructive one: it went the *other* way, inflating
a narrow structural property into a general one, and it was the claim v1 was
most confident about. Confidence tracked how much the finding flattered the
system, not how much evidence supported it.

Applied rule, going forward: no gap or strength is recorded about REMORA
without a file-and-line citation from REMORA, regardless of how strongly a
comparison project suggests it.
