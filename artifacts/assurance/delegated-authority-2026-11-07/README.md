# Delegated authority across agents: four questions, two REMORA paths (2026-11-07)

An external analysis of delegated authorization in agent-to-agent systems prompted a re-check of REMORA. It drew a line between a delegation chain that is cryptographically intact and one that still carries what the original authority allowed. The source is not used here: no text, code, data or number is taken from it. The four questions below are REMORA's own, and they were asked of both REMORA paths.

1. An intermediary widens the scope it was delegated.
2. A legitimate intermediary changes what the original authority allowed: a payment of 250 becomes one of 25000. The intermediary holds whatever symmetric key the envelope is signed with.
3. A used authorization is presented again after a restart, or to another verifier process.
4. A correctly signed chain is used for an action outside the task it was delegated for.

## Before: the A2A reference path at `dea40402`

`baseline_probe.py`, run at `dea40402`, writes `baseline.json`. Each line is what `verify()` returned with every strict argument supplied. The chain is two hops, origin to intermediary to worker, and each hop signs its link with its own registered HMAC key.

| Case | Result at `dea40402` |
|---|---|
| 1. The intermediary's link adds `vendor:add` | refused, `scope_widened_at_link` |
| 2. The envelope is issued for 25000, and nothing in the chain says 250 | **VALID** |
| 2. The origin's link is dropped and the chain starts at the intermediary's key | **VALID** |
| 2. One HMAC key is registered for every principal, and the intermediary signs as the origin | **VALID** |
| 3. Replay with the same in-memory guard | refused, `replay_detected` |
| 3. Replay after a restart that empties the guard | **VALID** |
| 3. Replay to another audience | refused, `audience_mismatch` |
| 4. Another task, and the verifier asks | refused, `task_mismatch` |
| 4. Another task, and the verifier does not ask | **VALID** |

Question 1 was stopped. Question 2 was accepted in three forms, question 3 whenever the caller's guard forgot, and question 4 whenever the verifier did not ask. NEGATIVE_RESULTS §103 records this.

## After: the change

`tests/test_delegated_authority_propagation.py` asks the same four questions of both paths (50 cases, with the adversarial review's).

**The A2A reference path** (`remora/governance/a2a_envelope.py`):

- **Conditions per link.** A link carries argument `conditions` (`{"lte": 250, "argument": "amount"}`, the vocabulary of `remora/capabilities/constraints.py`). Every link's conditions hold together.
  - An envelope for 25000 is refused as `argument_outside_delegation:0:amount`.
  - Loosening the origin's condition breaks its link signature.
  - A later link can add a condition, not remove one.
  - Conditions with no arguments to check them against fail in every mode (`link_conditions_unchecked`).
- **Anchored root.** `expected_roots` names who may start a chain, and strict mode requires it. A re-rooted chain is refused as `untrusted_delegation_root`.
- **No shared HMAC keys.** A link signed with an HMAC key registered for more than one principal is refused as `shared_link_key_at_link`.
- **Ed25519 links.** A link may be signed with the delegator's Ed25519 key. Its registry entry then holds only the public key. HMAC and Ed25519 never stand in for each other, and the registry entry decides which one applies.
- **Durable replay guard.** `durable_replay_guard` consumes nonces in the durable nonce store (SQLite, PostgreSQL or the state endpoint), under `a2a:<verifier>`. A replay is refused after a restart and by a separate OS process on the same store. A tampered envelope consumes no nonce.
- **Task binding.** A link may bind its task, a later link keeps it, and the envelope must name it (`task_changed_at_link`, `task_outside_delegation`). In strict mode, a bound task or declared operation the verifier did not ask to check fails.
- **Bound parent.** A link after the first signs the digest of the link before it, and strict mode requires it. A looser link from the same origin put in front of a link issued under a bounded one is refused as `parent_mismatch_at_link`.
- **Distinct keys, as HMAC sees them.** A link's HMAC key is compared with other principals' keys and with the envelope key after RFC 2104's padding and hashing, so `k` and `k + b"\0"` are one key.

An adversarial review of the first version of this change found the last two gaps. It also found four smaller ones. A non-string condition argument raised instead of failing. `True` met `eq 1`, and infinity met a one-sided bound. `expected_roots` as a bare string was read as its characters. Each now has a `test_review_*` case. NEGATIVE_RESULTS §103 records them.

**The execution API.** Question 2 now applies to work orders as well: `IntentScope` takes `arguments` conditions. Through the API, the pilot's WO-1201 with a bound on the setpoint value refuses a larger move at assess, with no review item. The answers to the other questions were already in place, and are cited rather than re-proved:

| Question | Execution API | Evidence |
|---|---|---|
| 1 | A delegated capability set is a subset of its parent, and inherits the parent's argument conditions | `tests/capabilities/test_capability_delegation.py`; the first execution case here |
| 2 | Arguments are bound by hash at assess, approval, execute and dispatch. The capability conditions hold at dispatch, and work-order argument bounds now hold at assess and execute | `tests/test_intent_scope.py`; the second execution case here |
| 3 | A grant or lease spent before a restart is refused after it, and a shared durable store serves every process | `tests/test_ws1_m4_fault_matrix.py::test_m4_t20_a_grant_replayed_after_a_restart_is_refused`, `tests/conformance/test_execution_boundary_process_split.py::test_p8_a_lease_spent_before_a_restart_is_refused_after_it` |
| 4 | A call outside its work order is refused at assess with no review (AACP D). A lease bound to one task refuses another | `tests/test_intent_scope.py`, `tests/test_ot_pilot_intent_scope.py`, `tests/test_task_bound_lease_and_envelope.py` |

## What AACP can express

The properties of agent-authority-conformance (v0.1 and v0.2, read at `30a5982`) name every question:

- **Question 1** is B: delegation chains and attenuation.
- **Question 2** is B and D: the provenance of approved intent, and the provenance of the meaning used to authorise. C does not cover it, because a call re-bound by the intermediary is bound exactly.
- **Question 3** is A: replay and single-use semantics.
- **Question 4** is D. AACP states that C does not imply D.

What AACP does not ship is a probe for these cases. Its portable adversarial suite (`aacp-portable-cfg-adversarial-v1`) covers C, F and G only. An implementation assessing B, D or the replay half of A has to bring its own cases, as this file does. Implementation-neutral B and A cases would fill that gap: attenuation, a re-rooted chain, a symmetric key shared across principals, and replay across a restart and across verifiers.

## What this does not show

- **The A2A envelope is a reference path.** No REMORA route receives one, and CAP-006 stays `WIRED_REFERENCE_PATH`. The envelope's own signature is still symmetric. The requested scope, the call binding and the envelope's task are therefore only as strong as that key's custody. What each delegator decided is protected by that delegator's own link signature.
- **The verifier computes the arguments.** The conditions bind the arguments the verifier passes. Computing those and the call hash from the same call is the verifier's job.
- **Argument conditions only.** A link carries no trusted state, so a condition cannot compare with a record, such as "the account's owner".
- **Not a proof of possession.** Nothing here proves the presenter holds a key: the task binding binds, and does not authenticate.
- **Author-written, not independent.** Every case was written by the producer.

Copyright 2026 Stian Skogbrott. Licensed under BUSL-1.1 (`legal/LICENSING.md`); rights ownership in `legal/COPYRIGHT.md`.
