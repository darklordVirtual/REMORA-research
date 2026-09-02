# REMORA Decision-to-Effect Execution Trace v1

Reference note for ACS / cMCP / TRACE review.
Repository state: `darklordVirtual/REMORA-research`, default branch at `2724fa0`.
Status: reference implementation. The capability register states explicitly that nothing in the repository is `ENFORCED_PRODUCTION` or `EXTERNALLY_VERIFIED`; deployment status is shadow-only. This document describes implemented and tested mechanisms, not deployment assurance.

## What you asked for, and where it is

| your point | answered in | runnable evidence |
|---|---|---|
| canonical representation covered by the authorization signature | §1 | V-02, V-03 |
| mutable and defaulted parameters | §2 | V-03 |
| the exact point authorization is consumed | §3 | V-04, V-05, V-08 |
| replay, substitution, concurrent dispatch | §3, §6 | V-02, V-04, V-05, V-08 |
| revocation between evaluation and dispatch | §4 | V-11 |
| attempted, accepted, committed, independently verified | §5 | V-13, V-14, V-15 |
| negative tests for the five named cases | §6 | V-02, V-06, V-07, V-04/V-08, V-13 |
| mapping to ACS, cMCP and TRACE without duplicate concepts | §7 | crosswalk table |

The suite in this directory runs the vectors and writes a hash-bound record. Reproducing it is three commands, listed in `README.md`.

## 1. The binding chain covered by the authorization signature

An external verifier holding the invocation and the authorization context can recompute the complete binding chain. The call hash needs only the invocation; `context_hash` additionally needs tenant, principal, target, policy bundle, ToolSpec identity and intent authority, so the context is part of what must be conveyed, not derived from the call.

```
full tool call {name, arguments, tenant, target}
  -> canonical_tool_call_hash            SHA-256 over remora/json-sorted-v1 bytes
  -> PolicyObservation.tool_call_hash    remora/policy/observation.py
  -> PolicyDecisionToken.observation_hash
  -> HMAC-SHA256 signature over {action, observation_hash, request_id,
                                 issued_at, expires_at, jti, audience,
                                 kid, issuer, context_hash}
```

`observation_hash` is set from `tool_call_hash` on the execution path (`remora/execution/service.py`), so the signature covers the exact invocation rather than a description of it. The hash preimage is the complete argument object, never a preview or a selected subset of security-relevant fields.

`context_hash` is a second, independent SHA-256 over the `AuthorizationContext`: tenant, principal, target_environment, policy_bundle_hash, toolspec_hash, intent_authority_hash. Call identity and authorization conditions are therefore separate signed properties. A signature that verifies says nothing about whether the context still holds; the PEP recomputes the context at redemption and refuses on `context_mismatch`, naming the differing fields.

Two canonical formats exist and there is no migration between them:

| identifier | scope | changes |
|---|---|---|
| `remora/json-sorted-v1` | every internal binding: call hashes, tokens, leases, receipts, audit chain | never |
| `remora/jcs-rfc8785-v0` | wire interoperability only (`remora/interop/jcs.py`) | this profile |

A signature is not portable between the two and must never be re-derived across them. In the JCS path, RFC 8785 divergence classes 1 to 3 are closed. Class 4 (numbers as binary64) is deliberately declined. Binary64 maps distinct large integers onto identical canonical bytes. In a system whose premise is that an approval cannot be reused for different arguments, that is an argument-substitution hole. REMORA refuses exactly the integers whose binary64 form is shared with a neighbour and serialises every other integer exactly. Refusal is the fail-closed direction. Canonical bytes are still not injective over all payloads: distinct float literals collapse in `json.loads` before canonicalisation. That limit is stated here rather than left for a reader to find.

## 2. Mutable and defaulted parameters

There is no post-authorization completion step. The binding is computed over the complete argument object presented for evaluation, and in strict profiles the arguments must also validate against the signed ToolSpec `argument_schema` (`remora/toolcall/toolspec.py`). Defaults must therefore be materialised before authorization, because the enforcement point recomputes `canonical_tool_call_hash` from the arguments actually being dispatched and refuses any difference. An implicit default introduced after authorization is indistinguishable from tampering and is treated as tampering.

## 3. Where authorization is consumed

There are two distinct single-use boundaries, not one:

```
PDP issues PolicyDecisionToken (jti)
  -> PEP redeems: signature, audience, expiry, observation_hash, context recheck
  -> jti consumed exactly once            refusal: token_already_consumed
  -> ExecutionLease issued (narrower)
  -> dispatcher consumes lease nonce atomically at the dispatch boundary
  -> tool invocation
```

The `ExecutionLease` binds decision, tenant, actor identity, tool name, tool args hash, target, policy_bundle_hash, toolspec hash and version, proposal_id, the originating `grant_jti`, and `runtime_identity_hash`. It carries its own short lifetime and its own nonce. The dispatcher, not the agent, holds the callable and the downstream credential path.

Replay state is durable when a Postgres, SQLite or D1 ledger is configured. An in-process ledger alone is documented as insufficient for production, and REM-025 tracks the remaining in-process `NonceLedger` case. That limit is a live caveat, not a closed item.

## 4. Revocation and change between evaluation and dispatch

Authorization is not treated as permanent because evaluation once succeeded. Current context is rechecked immediately before dispatch, so a changed ToolSpec identity, policy bundle, audience, validity window or revocation state invalidates an otherwise correctly signed earlier decision. Principal revocation is stored durably on the execution path, and an unavailable revocation store fails closed rather than answering "not revoked". Signing-key identity (`kid`) revocation is checked separately during token verification.

## 5. Attempted, accepted, committed, independently verified

| claim | what REMORA can support | artifact |
|---|---|---|
| authorized | enforcement authority existed for this exact call under this exact context | signed token plus context_hash |
| attempted | the dispatcher crossed the execution boundary with a consumed lease | dispatch record |
| accepted | the downstream system took the request | `DispatchOutcome.SUCCEEDED`, which cannot separate this from committed |
| committed | a durable downstream effect exists | not established by dispatch success alone; requires downstream evidence or read-back |
| indeterminate | dispatch may have begun and the outcome cannot be established | `DispatchOutcome.UNKNOWN` |
| independently verified | a read-back against a system of record confirms the authorized postcondition | `EffectStatus.VERIFIED` |

On the four-state distinction: REMORA separates attempted from committed and committed from independently verified, but it does **not** separate accepted from committed. `SUCCEEDED` means the callable returned without raising, which for an asynchronous downstream system is acceptance rather than commitment. A system that returns 202 and commits later is recorded here as `SUCCEEDED`, so commitment is not established by dispatch alone and only the effect verification step can settle it. If a profile needs that distinction, it belongs in the dispatch outcome rather than in a second evidence document.

`UNKNOWN` is deliberate and durable: `asserts_no_effect` is true only for `REFUSED` and `FAILED`, so uncertainty is never converted into "it did not happen" and then retried. Effect verification is a separate step producing `EFFECT_VERIFIED`, `EFFECT_MISMATCH`, `EFFECT_UNOBSERVABLE`, `EFFECT_VERIFIER_FAILED` or `EFFECT_UNSUPPORTED` (`remora/governance/effect_verification.py`). An effect receipt is lineage-bound to an actual dispatch, so a proposal that was only authorized cannot acquire `EFFECT_VERIFIED`.

The evidence model is intentionally non-transitive:

```
authorized != attempted
attempted  != accepted
accepted   != committed
committed  != independently verified
```

## 6. Negative vectors

These ship as a runnable suite in `conformance/decision-to-effect-v1/`, written so that the vectors contain no REMORA. Each vector is a step programme with a normalized expected outcome class; an adapter replays it against one system and reports what that system decided. A second adapter is roughly a hundred lines.

The current author-run against this repository is 15 of 15 matching, 0 divergent, 0 unsupported, recorded in `run-record.json` with the suite, adapter and runner hashes and the repository commit. Author-run is stated in the record itself, because the number means nothing until someone else produces one.

| vector | required behaviour |
|---|---|
| arguments mutated after evaluation | refuse before invocation, call-hash mismatch |
| wrong audience | refuse |
| duplicate PDP token use | refuse, `token_already_consumed` |
| duplicate or concurrent lease use | refuse, nonce consumed once |
| expired or stale authorization | refuse |
| ToolSpec changed after assessment | refuse, context mismatch names `toolspec_hash` |
| policy bundle or principal changed | refuse, context mismatch |
| principal revoked between evaluation and dispatch | refuse; an unavailable revocation store also refuses |
| dispatch outcome indeterminate | persist `UNKNOWN`, assert no effect claim |
| effect evidence without dispatch lineage | refuse the receipt |
| observed effect differs from authorized call | `EFFECT_MISMATCH`, never verified |

## 7. Crosswalk to ACS, cMCP and TRACE

Read against ACS (`microsoft/agent-governance-toolkit/policy-engine`, SPECIFICATION.md §4, §17, §17.1),
cMCP (`agentrust-io/cmcp`) and TRACE (`agentrust-io/trace-spec`, v0.2).

| REMORA property | REMORA artifact | existing field or concept | new concept? |
|---|---|---|---|
| exact invocation identity | `canonical_tool_call_hash` over `{name, arguments, tenant, target}` | ACS `enforced_identity`, the SHA-256 of the canonical policy input | no, same primitive with a narrower preimage |
| revalidation before the action runs | PEP recompute at redemption | ACS §17.1 rederivation of `enforced_identity`, failing closed on `approval_action_mismatch` | no |
| enforcement point | `EnforcementGate` / `GovernedToolDispatcher` | ACS `pre_tool_call` intervention point, host obligation in §17 | no |
| authorization conditions | `AuthorizationContext.context_hash` (tenant, principal, target, policy_bundle_hash, toolspec_hash, intent_authority_hash) | ACS covers the snapshot inside `enforced_identity`; cMCP carries `trace.policy.bundle_hash` | no, but REMORA hashes the conditions separately from the call so a refusal can name the field that changed |
| policy bundle identity | `policy_bundle_hash` | `trace.policy.bundle_hash`, TRACE `policy.bundle_hash` + `enforcement_mode` | no |
| tool contract identity | `toolspec_hash` / `toolspec_version` | cMCP measures the Cedar bundle, not a per-tool contract | partial gap |
| audit chain | tenant audit chain | `gateway.audit_chain` (root, tip, length) | no |
| dispatch record | dispatch record and lifecycle | TRACE `tool_transcript` | no |
| effect verification result | `EffectStatus`, lineage-bound receipt | TRACE `appraisal` and evidence reference | no |
| single-use authority | token `jti`, consumed once | no single-use, replay or nonce mechanism identified in the reviewed public specification | candidate |
| bounded execution authority distinct from the decision | `ExecutionLease` (own nonce, own lifetime, binds `grant_jti` and `runtime_identity_hash`) | no equivalent identified in the reviewed public specifications; cMCP enforces per call rather than issuing a bounded authority | candidate |
| revocation between evaluation and dispatch | durable revocation store, fails closed when unavailable | none identified in the reviewed public specification | candidate |
| indeterminate dispatch state | `DispatchOutcome.UNKNOWN`, `asserts_no_effect` false | TRACE records what happened; no explicit non-assertion state identified in the reviewed version | candidate |

I have deliberately not introduced a REMORA synonym for anything ACS or TRACE already names. Where the concepts coincide, the ACS or TRACE name should win.

## 8. The trust-boundary question

Your criterion is the right one, so I will state where REMORA does and does not meet it.

cMCP already provides an independent trust boundary, and it is hardware: the Cedar bundle hash is measured into the attestation report before any code runs, and the audit chain is hardware-sealed. REMORA's custody split (the dispatcher holds the callable and the downstream credential, the agent holds neither) is a software boundary and is strictly weaker. It does not earn a new layer on its own, and running REMORA enforcement inside a cMCP TEE would be a better composition than either claiming that boundary independently.

What is left after that subtraction is four rows, and they are all about authority lifetime rather than about policy or evidence content:

1. authority that is single-use rather than re-evaluable,
2. a bounded execution authority that is narrower than the decision and binds the executing runtime,
3. revocation that takes effect between evaluation and dispatch,
4. an explicit "effect state unknown" that refuses to assert non-occurrence.

ACS closes the time-of-check to time-of-use gap by rederiving `enforced_identity`, which handles parameter tampering. It does not, on my reading, prevent a still-valid approval from being redeemed twice, or invalidate an approval when the principal is revoked one second after evaluation. Those are different failures from tampering, and they are the ones the four rows address.

## Specification boundary

On this evidence, my view has moved closer to yours. Rows 1 to 3 look like an ACS/cMCP enforcement profile: bounded, single-use, revocable authority expressed over ACS `enforced_identity` rather than over a new identity. Row 4 looks like a TRACE evidence question: whether the format can carry "attempted, occurrence not established" without an appraiser reading absence as non-occurrence.

If both hold, REMORA is a reference enforcement implementation for the decision-to-effect seam and a source of negative vectors, not a new layer. I would rather land it that way than argue for a layer the evidence does not require.

## Stated limits

- No `ENFORCED_PRODUCTION` and no `EXTERNALLY_VERIFIED` capability in the register.
- The APS Authority Profile is draft and claims semantic alignment only, with no wire-level interoperability.
- The suite result above is author-run. `run_kind` says so in the record, and a test asserts that it keeps saying so.
- Concurrency evidence is process-local; multiprocess and field validation is not claimed.
- The ACS, cMCP and TRACE readings above come from the public repositories as of 2026-09-01 (`microsoft/agent-governance-toolkit` policy-engine spec, `agentrust-io/cmcp`, `agentrust-io/trace-spec` v0.2). Where I claim a specification is silent on something, that is my reading of those documents and I would rather be corrected than build on it.
- V-05 demonstrates single-use consumption across eight concurrent threads in one process. Multiprocess and restart behaviour require a durable ledger and are not claimed by this run.
- The effect vectors use an in-suite reader rather than a system of record. Swapping in a real one changes the adapter and not the vectors, which is the point of the split.
