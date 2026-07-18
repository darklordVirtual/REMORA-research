# REMORA Policy Engine Assurance Audit v1

**Date:** 2026-06-30
**Scope:** Policy engine, PDP/PEP boundaries, DecisionEnvelope, hash chain, policy versioning
**Auditor role:** Agent A (automated assurance campaign)
**Commit audited:** 2cd573d (master)

---

## 1. Threat Model (STRIDE)

### 1.1 Scope

The threat model covers the 5-stage pipeline:

```
[Agent Action] → Stage 1: Hard Blocks → Stage 2: Oracle Consensus/Credal
              → Stage 3: Evidence Gates → Stage 4: Trust Routing
              → Stage 5: Audit/PEP Enforcement
```

Key assets:
- **PolicyObservation**: the governance observation; field manipulation is the primary attack surface
- **DecisionReport / DecisionAction**: the governance verdict (ACCEPT/VERIFY/ABSTAIN/ESCALATE)
- **PolicyDecisionToken**: signed PDP→PEP authorization
- **AuditHashChain**: tamper-detectable audit ledger
- **REMORA_PDP_SIGNING_KEY**: signing secret protecting token integrity

### 1.2 STRIDE Analysis

| Threat | Location | Existing Control | Gap |
|--------|----------|-----------------|-----|
| **S**, Spoofing observation fields | PolicyObservation construction | `_normalize_observation` normalises risk_tier/action_type/target_environment; factory methods validate structure | Caller can set `adversarial_detected=False` on a real adversarial input; detection depends on upstream classifier |
| **S**, Token forgery (PDP→PEP) | PolicyDecisionToken | HMAC-SHA256 over canonical payload; observation_hash binds token to specific call | Unsigned tokens accepted in non-strict mode; no replay-window TTL on token |
| **T**, Observation field tampering | PolicyObservation (frozen dataclass) | Frozen dataclass prevents mutation after construction | `from_dict` / `from_json_record` accepts any serialized dict, no signature on the observation itself |
| **T**, Verdict tampering in transit | PolicyDecisionToken to EnforcementGate | HMAC-SHA256; changing `action` field invalidates signature | Token carries no expiry; a captured signed ACCEPT token remains valid indefinitely |
| **T**, Audit chain tampering | AuditHashChain | SHA-256 hash chain detects tampering | In-memory chain can be fully rewritten by adversary with write access (documented: detect-only) |
| **R**, Decision non-repudiation | DecisionReport | policy_version, reasons, source_of_decision recorded | No cryptographic timestamp (RFC 3161); server-clock UTC only |
| **I**, Information leakage via audit | AuditBlock | tool_args_hash hides full action text | observation serialization in _hash_observation includes all fields; if hash is logged, pre-image may leak |
| **D**, Session flooding | Session attack gates | session_action_count > 100 → VERIFY; session_cumulative_risk > 0.80 → VERIFY | Threshold constants are not configurable at runtime; no per-tenant session table |
| **E**, Privilege escalation via phase manipulation | Phase gate | critical phase + critical risk → ESCALATE | Non-critical phase with critical risk only gets VERIFY (not ESCALATE); intentional design |
| **E**, Bypass via unclassified action_type | Unknown action_type handling | None action_type falls through to normal logic (not conservatively blocked) | Documented caveat: unknown action_type is not conservatively escalated; caller must classify |

---

## 2. Trust Boundary Diagram

```
────────────────────────────────────────────────────────────────────
  AGENT PROCESS (untrusted)
  ┌────────────────────────────┐
  │  Agent                     │
  │  Tool call + arguments     │
  └──────────────┬─────────────┘
                 │  PolicyObservation
                 │  (constructed by integration layer)
────────────────┼──────────────────── TRUST BOUNDARY A ───────────
  REMORA RUNTIME (trusted)     │
  ┌──────────────▼─────────────┐
  │  PDP: RemoraDecisionEngine │
  │  decide(obs) → DecisionReport
  │  + PolicyDecisionToken.issue()│
  └──────────────┬─────────────┘
                 │  Signed PolicyDecisionToken
                 │  (HMAC-SHA256, observation_hash binding)
────────────────┼──────────────────── TRUST BOUNDARY B ───────────
  PEP LAYER     │
  ┌──────────────▼─────────────┐
  │  EnforcementGate           │
  │  .check(token)             │
  │  Verifies signature        │
  │  Checks action == 'accept' │
  └──────────────┬─────────────┘
                 │  allowed=True/False
                 │
  ┌──────────────▼─────────────┐
  │  Action execution          │
  │  (only if allowed=True)    │
  └────────────────────────────┘
────────────────────────────────────────────────────────────────────
  AUDIT LAYER
  ┌────────────────────────────┐
  │  AuditHashChain            │
  │  (in-memory, detect-only)  │
  │  DecisionEnvelope          │
  │  + AuditBlock              │
  └────────────────────────────┘

External anchoring (not yet implemented):
  - WORM/object storage immutability policy
  - Transparency Log (Trillian / Sigstore)
  - RFC 3161 trusted timestamp
  - KMS/HSM for signing key (REM-022)
```

**Trust boundary A** (agent → PDP): PolicyObservation fields are caller-controlled. The engine normalises and validates them conservatively but cannot verify `adversarial_detected` itself: it depends on an upstream classifier.

**Trust boundary B** (PDP → PEP): Protected by HMAC-SHA256 signed PolicyDecisionToken. The observation_hash binds each token to a specific call, preventing reuse.

---

## 3. Policy Bypass Analysis

### 3.1 Can any path reach ACCEPT past a hard block?

**Finding: NO identified bypasses to critical hard blocks.**

Traced all ACCEPT-returning paths in `decide()`:

| ACCEPT path | Lines | Hard blocks checked before it |
|-------------|-------|-------------------------------|
| `conformal_phase_thresholds` (Mondrian) | 447–458 | All hard blocks (adv, schema_false, tool_forbidden, coercion, blackmail, counterfactual=False, contradictions>0, argument_tainted, refuse_parametric, distribution_shift, critical+critical, rollback, state_transition, prod_write matrix, evidence_insufficient for high/critical, **critical risk catch-all**), minimax, trap, unknown tier, misspecification, session, fleet, GAP A+C, schema_unverified floor |
| `conformal_trust_threshold` (marginal) | 462–470 | Same as above |
| `temperature_threshold` | 472–480 | Same as above |
| `evidence_supported` | 482–493 | Same as above |
| `ordered_high_trust` | 499–513 | Same as above |

**Critical risk ACCEPT is architecturally blocked**: line 312–314 (`risk_tier == "critical" → VERIFY`) fires for every critical-risk observation that has bypassed the earlier evidence-insufficient gate. This ensures critical risk cannot reach any ACCEPT path regardless of `conformal_phase_thresholds`, `conformal_trust_threshold`, or `temperature_threshold` configuration.

**High risk with evidence CAN reach ACCEPT** via conformal or temperature paths if:
- `evidence_action='answer'` (bypasses evidence_insufficient gate)
- `counterfactual_passed=True` (not False or None, bypasses GAP A)
- `schema_valid` is True or action is read-only (bypasses schema floor)
- Trust/temperature satisfies threshold

This is **intentional design**: high-risk actions are not categorically blocked from ACCEPT; they require evidence + counterfactual verification. Only critical risk is categorically excluded from autonomous ACCEPT.

### 3.2 Hard Block Priority Order Verification

```
Priority 1 (ESCALATE):
  adversarial_detected
  schema_valid=False
  tool_forbidden
  coercion_detected
  blackmail_pattern_detected
  counterfactual_passed=False
  evidence_contradictions>0 with contradiction_cycles>0

Priority 2 (VERIFY or ABSTAIN):
  evidence_contradictions>0 (without cycles: ABSTAIN)
  argument_tainted (VERIFY)
  refuse_parametric_verdict (VERIFY)
  distribution_shift_detected (VERIFY)

Priority 3 (ESCALATE):
  phase='critical' AND risk_tier='critical'
  rollback_available=False AND risk_tier in (high, critical)
  state_transition_uncertain AND risk_tier in (high, critical)
  production_write + critical risk → ESCALATE
  production_write + high risk → VERIFY
  high/critical risk without evidence → VERIFY
  **critical risk catch-all → VERIFY** (ensures critical cannot reach ACCEPT)

Priority 4: minimax gate → ESCALATE
Priority 5: trap gate → ESCALATE or VERIFY
Priority 6: unknown risk tier gate → VERIFY
Priority 7: misspecification gates
Priority 8: session/fleet gates
Priority 9: GAP A+C (counterfactual=None for high/critical evidence path)
Priority 10: schema_unverified floor (mutating + schema_valid=None)
Priority 11+: ACCEPT paths (conformal, temperature, evidence, ordered_high_trust)
```

**The ordering is correct and conservative.** No ACCEPT path can be reached before all hard blocks are evaluated.

### 3.3 Specific Bypass Risk: `from_tool_call` default `target_environment="prod"`

**Medium severity finding.**

`PolicyObservation.from_tool_call()` defaults `target_environment="prod"`. Callers who do not set this explicitly will have all tool calls tagged as production-targeting. This is conservative (errs toward blocking) but may produce unexpected VERIFY/ESCALATE for staging-only tools if the caller does not override.

**Impact:** Over-blocking, not under-blocking. Not a security bypass, but a usability and precision risk.

**Status:** Documented finding; no code change needed as over-blocking is the safer failure mode.

---

## 4. PDP/PEP Separation Assessment (REM-013)

### 4.1 What is implemented

- `remora/enforcement/token.py`: `PolicyDecisionToken` with HMAC-SHA256 signing
- `remora/enforcement/gate.py`: `EnforcementGate` that verifies token before permitting execution
- Observation hash (`_hash_observation`) binds each token to a specific observation
- Strict mode (production): unsigned tokens rejected
- Non-strict mode (development): unsigned tokens allowed with `warnings.warn`

### 4.2 Verified properties

| Property | Verified |
|----------|----------|
| PEP cannot be called without a PDP token | Yes, `gate.enforce()` requires a `PolicyDecisionToken` |
| Forged signatures rejected | Yes, HMAC verify fails; `allowed=False` |
| Changed `action` field invalidates signature | Yes, action is in canonical payload |
| Observation hash mismatch rejected | Yes, `verify(observation_hash=...)` checks binding |
| Non-ACCEPT decisions block execution | Yes, `ACCEPT_ACTIONS = frozenset({"accept"})` |
| Strict mode rejects unsigned tokens | Yes, returns `allowed=False` |
| Non-strict mode warns on unsigned | Yes, `warnings.warn` emitted |

### 4.3 Known gaps (documented in REM-013 and REM-022)

1. **No token expiry / replay window**: A signed ACCEPT token remains valid indefinitely. If captured, it can be replayed for the same observation (same hash). Mitigation requires a nonce store or TTL check.

2. **No KMS/HSM**: `REMORA_PDP_SIGNING_KEY` is a plain environment variable. Compromise of the host yields key compromise. Requires AWS KMS / Azure Key Vault (REM-022).

3. **No RBAC**: Any caller with the signing key can issue tokens for any action. No per-role or per-tenant key isolation.

4. **No process-boundary crossing**: PDP and PEP run in the same Python process. True boundary enforcement requires gRPC/HTTP separation with mutual TLS.

5. **`from_dict` does not verify envelope signature**: `DecisionEnvelope.from_dict()` deserializes without checking `audit.signature`. An adversary who can write to the envelope store can inject unsigned/tampered envelopes.

---

## 5. Fail-Closed vs Fail-Open Analysis

### 5.1 Verified fail-closed behaviors

| Scenario | Behavior | Code location |
|----------|----------|---------------|
| `adversarial_detected=True` | ESCALATE (hard block, no override) | Line 230–232 |
| `schema_valid=False` | ESCALATE | Line 234–236 |
| `schema_valid=None` + mutating action | VERIFY (not ACCEPT) | Line 242–244, 442–443 |
| `risk_tier=None` or unrecognised | Normalised to 'unknown'; VERIFY for mutating/production actions | Lines 72–81, 341–346 |
| `counterfactual_passed=None` + high/critical evidence path | VERIFY | Lines 429–435 |
| `evidence_contradictions=None` + high/critical | Already blocked by evidence_insufficient gate | Lines 308–310 |
| `tool_forbidden=True` | ESCALATE | Lines 248–250 |
| `argument_tainted=True` | VERIFY floor (cannot reach ACCEPT) | Lines 276–278 |
| Missing signing key (EnforcementGate strict) | `allowed=False` | gate.py 79–93 |
| `production_write` with unknown risk tier | ESCALATE via trap gate (0.75+0.15=0.90 score) | trap_classifier.py |

### 5.2 Identified fail-open risks

**Finding F-1 (Low): Unknown action_type is not conservatively blocked**

If `action_type=None` or an unrecognised string, it falls through to normal logic without triggering the unknown-risk-tier VERIFY gate (which only fires for actions explicitly in `_MUTATING_TYPES`). This is documented as intentional in the source comment at line 43:

```python
# Unknown action_type (None / unrecognised string) is NOT in this set — it falls through
# to existing logic rather than being conservatively blocked, to avoid over-blocking tools
# that declare no action_type.
```

However: if `risk_tier` is also unknown AND the action reaches an ACCEPT path (e.g. ordered + high trust), it can ACCEPT with no action classification. This is the weakest point in the fail-closed coverage.

**Test case for F-1**: see `tests/test_policy_engine_audit_v1.py` → `TestUnknownActionTypeAcceptPath`.

**Finding F-2 (Low): Token has no expiry**

A captured valid `PolicyDecisionToken` for a specific observation is permanently replayable for that exact observation hash. Since the token binds to `observation_hash`, it cannot be reused for a different action. The risk window is narrow but present for long-lived ACCEPT tokens in same-session scenarios.

**Finding F-3 (Informational): `AROMER_CONFORMAL_TRUST_THRESHOLD` class constant is unused at runtime**

`RemoraDecisionEngine.AROMER_CONFORMAL_TRUST_THRESHOLD = 0.72` is a class attribute but `decide()` uses `self.conformal_trust_threshold` (the instance attribute set by `__init__`). The class constant is documentation for `AromerOrchestrator` callers, not an active gate. This is not a bug but creates a risk of confusion: a caller might assume setting the class attribute changes engine behavior.

---

## 6. Hash Chain Integrity Assessment

### 6.1 AuditHashChain (`remora/audit/hash_chain.py`)

**Design:** SHA-256 hash-linked list. Each entry covers `{timestamp, question_hash, action, trust_score, phase, metadata}` plus `previous_hash`. Hash chain is stored in-memory.

**Tamper detection:** Single-entry tampering detected by `verify()` (recomputes hash and checks). Chain-break detected by `verify()` (checks `previous_hash` links).

**Limitation (documented):** An adversary with write access can rewrite the entire chain and recompute all hashes. The chain is **tamper-detectable, not tamper-resistant**. The module docstring explicitly states this and lists required external anchoring (WORM, Transparency Log, RFC 3161).

**Verified properties:**
- `verify()` returns False on single-entry tampering ✓
- `entry_hash` covers all semantically relevant fields ✓  
- `previous_hash` chain linkage is enforced ✓
- Genesis entry (no previous) handled correctly ✓

### 6.2 DecisionEnvelope AuditBlock (`remora/governance/envelope.py`)

**`envelope_hash()`** covers: `request_id, domain, action_type, risk_tier, proposed_action, verdict, policy_triggers`. This is sufficient to detect verdict tampering and action reclassification.

**Limitation:** `AuditBlock.hash` and `AuditBlock.signature` are optional fields that must be explicitly populated by the integration layer. `DecisionEnvelope` does not auto-compute or auto-verify them. An envelope produced by `from_dict()` has no signature check.

**Missing:** `AuditBlock.timestamp_utc` uses server clock (documented). RFC 3161 trusted timestamp is roadmap (acknowledged in AuditBlock docstring).

---

## 7. Policy Versioning Controls Assessment

**Current state:** `policy_version = "RemoraDecisionEngine-v3"` is hardcoded in `_build()` at line 953 and in `PolicyTrace` at line 139.

**Assessed controls:**

| Control | Status | Gap |
|---------|--------|-----|
| Version string on every DecisionReport | Present, `POLICY_VERSION_ALWAYS_SET` invariant enforces this | None |
| Version in PolicyTrace | Present | None |
| Version in AuditBlock | Set by caller, not auto-populated | Integration layer must copy it |
| Policy bundle hash (`policy_bundle_hash`) | Field exists in AuditBlock but is None by default | Not computed automatically; requires external tooling |
| Version bump on policy change | Manual, no tooling enforces a bump on git changes to decision_engine.py | Gap: silent version-string drift |
| Previous envelope hash (`previous_hash`) | Field exists; populated externally | Not enforced in engine |

**Finding F-4 (Medium): Policy bundle hash not auto-computed**

`AuditBlock.policy_bundle_hash` is declared as "SHA-256 composite of active policy files" but is always `None` unless the integration layer explicitly sets it. A policy change that is not surfaced in the bundle hash allows policy drift without audit trail change.

**Recommendation:** Add a utility function `compute_policy_bundle_hash()` that hashes `decision_engine.py`, `invariants.py`, `trap_classifier.py`, and `observation.py` deterministically. This would let the integration layer populate `AuditBlock.policy_bundle_hash` automatically.

---

## 8. Specific Test Cases for Unsafe Defaults or Ambiguities

The following test scenarios were identified during audit. Tests are implemented in `tests/test_policy_engine_audit_v1.py`.

| ID | Scenario | Expected result | Finding |
|----|----------|----------------|---------|
| T-01 | `action_type=None, risk_tier=None, trust_score=0.95, phase='ordered'` | ACCEPT (permissive) | F-1: undocumented gap |
| T-02 | `action_type=None, risk_tier=None, trust_score=0.95, phase='ordered'` + conformal phase threshold | ACCEPT | F-1: same gap |
| T-03 | Critical risk + all ACCEPT-path fields set + conformal thresholds | VERIFY (blocked by critical catch-all) | No bypass |
| T-04 | Token with `action` field changed after signing | `allowed=False` | PEP boundary holds |
| T-05 | `AROMER_CONFORMAL_TRUST_THRESHOLD` set as class attribute, instance has `conformal_trust_threshold=None` | No effect on ACCEPT | F-3: class attr confusion |
| T-06 | `envelope_hash()` with tampered verdict field | Different hash | Integrity holds |
| T-07 | Hash chain single-entry tamper | `verify()` returns False | Integrity holds |
| T-08 | `production_write + target=prod + risk_tier=None` | ESCALATE (via trap gate) | Fail-closed |
| T-09 | `argument_tainted=True` + all ACCEPT conditions met | VERIFY (tainted floor holds) | No bypass |
| T-10 | `schema_valid=None + action_type='write' + conformal phase threshold` | VERIFY (schema floor fires before conformal) | No bypass |

---

## 9. Low-Risk Improvements Implemented

### 9.1 `compute_policy_bundle_hash()` utility

**Added to `remora/policy/versioning.py`** (new file). Computes a deterministic SHA-256 composite hash over the policy-critical Python source files. Integration layers can use this to auto-populate `AuditBlock.policy_bundle_hash`.

### 9.2 New test file: `tests/test_policy_engine_audit_v1.py`

Implements tests T-01 through T-10 plus additional edge cases for:
- Unknown action_type ACCEPT path (documenting the gap, not blocking)
- Token no-expiry replay property (verifying observation-hash binding prevents cross-action reuse)
- `AROMER_CONFORMAL_TRUST_THRESHOLD` class attribute non-interference
- Policy bundle hash determinism

---

## 10. Remaining Uncertainty

1. **Oracle upstream**: The engine trusts that `adversarial_detected`, `argument_tainted`, and similar binary flags are set by a trusted upstream classifier. If the classification pipeline is compromised, the engine's hard blocks can be bypassed by setting these flags to False. This is an external trust assumption, not an engine defect.

2. **Token replay window**: No tested scenario confirmed that a replayed token for the same observation causes harm in context. The risk is theoretical without a concrete execution environment.

3. **`conformal_phase_thresholds` with high-risk ACCEPT**: A high-risk action with proper evidence (`evidence_action='answer'`, `counterfactual_passed=True`) CAN reach ACCEPT via the conformal path. This is intentional but may surprise operators who assume high-risk always requires human review. The distinction between `high` and `critical` risk tiers is the architectural boundary.

4. **Envelope signature verification gap**: `DecisionEnvelope.from_dict()` does not verify `AuditBlock.signature`. Any system that round-trips envelopes through untrusted storage must add signature verification before trusting a deserialized envelope.

5. **Policy bundle hash not automated**: Until `compute_policy_bundle_hash()` is wired into the integration layer, `AuditBlock.policy_bundle_hash` remains `None` in all production envelopes, limiting the auditability of policy changes.

---

## Summary Table

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F-1 | Unknown action_type + unknown risk_tier can ACCEPT (documented design gap) | Low | Documented in tests |
| F-2 | PolicyDecisionToken has no expiry/replay TTL | Low | Documented (REM-022 scope) |
| F-3 | `AROMER_CONFORMAL_TRUST_THRESHOLD` class attribute is unused by `decide()` | Informational | Documented in tests |
| F-4 | `AuditBlock.policy_bundle_hash` not auto-computed | Medium | New utility added |
|, | Critical risk cannot ACCEPT through any path | No bypass found | Verified |
|, | Hard block ordering is correct (all hard blocks precede ACCEPT paths) | No bypass found | Verified |
|, | PDP/PEP token binding prevents cross-action reuse | No bypass found | Verified |
|, | Schema unverified floor fires before conformal ACCEPT | No bypass found | Verified |
|, | GAP A (counterfactual=None) fires before conformal ACCEPT | No bypass found | Verified |
