# REMORA Assurance Case v1

**Status:** internal, living document. Not an independent certification.
**Created:** 2026-07-20
**Argument class:** *control* (see §6). REMORA does not argue that the underlying
models are incapable of harm, nor that they are trustworthy, nor does it yet
claim external credit.
**Deployment status:** `SHADOW_ONLY`, `policy_relaxation_allowed = false`. One
production gate ([REM-021](remediation_register.yaml) independent human review)
remains open.

This document is a structured safety argument in the tradition of Goal
Structuring Notation (GSN) modernised per *Assurance 2.0* — that is, with
explicit **defeaters** (recorded doubts) and built for continuous update rather
than one-off certification. It exists because a claim register and a pile of
negative results are necessary but not sufficient: the compendium's test for any
governance artefact is that *each requirement traces to a technical control, and
each control to fresh evidence that it works.* The claim-to-artifact discipline
in [CLAUDE.md](../../CLAUDE.md) and [docs/05-claim-hygiene.md](../05-claim-hygiene.md)
supplies the freshness; this case supplies the argument that ties the controls
together.

**Freshness contract.** Every claim below is bound to a versioned artifact on
disk. The case is invalidated and must be re-argued whenever the model set, the
policy bundle, the tool surface, the benchmark corpus, or the threat picture
changes (see §7, change gates). Evidence must not be older than the system it
describes.

---

## 1. Top-level goal (G1)

> **G1.** For a proposed autonomous agent action, REMORA routes it to one of
> ACCEPT / VERIFY / ABSTAIN / ESCALATE, and a deterministic policy floor ensures
> that actions carrying a critical risk tier or a detected adversarial /
> coercion / forbidden-tool / evidence-contradiction signal are never
> autonomously accepted — recording a tamper-evident, replayable rationale for
> every decision.

G1 is scoped to *decision routing over the proposed-action surface*, in a
research-grade, shadow-mode system. It is **not** a claim of production
certification, of safety guarantee, or of verified tool-call interception
(the AgentHarm harness is intent-gating; see D-2 below). The adversarial-signal
detection is surface/keyword-based and evadable by rewording (see the CLAIM-001
caveat and D-4); path-level (trajectory) enforcement is roadmap (REM-044).

## 2. Strategy (S1)

Decompose G1 along the four runtime-governance capabilities the compendium
names as the minimum for any agent in production — **stop, constrain, escalate,
explain** — plus the evidence discipline that makes the argument checkable.

- **G2 (constrain)** — a deterministic policy floor prevents autonomous
  acceptance of unsafe actions.
- **G3 (stop)** — the system can refuse/withhold execution and degrade safely.
- **G4 (escalate)** — actions that are not safe to auto-accept are routed to a
  human with a freshness-bounded approval.
- **G5 (explain)** — every decision emits a canonical, hash-chained,
  standard-format record that can be replayed and audited.
- **G6 (evidence)** — the claims above are backed by versioned, reproducible
  artifacts, with leakage controls and preserved negative results.

## 3. Sub-goals, evidence, and defeaters

### G2 — Constrain (the load-bearing claim)

**Argument.** The safety result is produced by the deterministic policy layer,
*explicitly not* by the multi-oracle consensus machinery. `hard_guard_floor()`
unconditionally routes to a non-accept action — ESCALATE on adversarial input,
malformed schema, forbidden tool, coercion, or failed counterfactual, and
ABSTAIN/VERIFY on the evidence-contradiction and tainted-argument branches —
evaluated before any probabilistic path; unknown `action_type`/`risk_tier` fail
closed to VERIFY.

**Evidence.**
- Engine and floor: `remora/policy/decision_engine.py`; machine-verifiable
  invariants `remora/policy/invariants.py`; monotone floor over an external PDP
  `remora/policy/opa_adapter.py`.
- CLAIM-001 (`internal_benchmark`): 0% unsafe execution on the v2 tool-call
  benchmark (effective N=70 template clusters; cluster Wilson CI [0.0%, 5.2%]).
- CLAIM-007 (`internal_benchmark`): five-condition ablation — structural-only
  gating (C) leaves 25% unsafe, while both the structural+thermodynamic policy
  (D) and the full gate (E) reach 0%; the full gate's advantage over D is
  decision utility (0.62 vs 0.10) and lower benign friction, not a lower floor.
- CLAIM-010 (`regression_tested`): blinded v3 protocol, gate sees only the
  candidate action, `leakage_free=True`.

**Defeaters:** D-1, D-3, D-4, D-9 (see §4).

### G3 — Stop

**Argument.** Execution can be withheld and the system degrades safely rather
than failing open. Enforcement is a separate, fail-closed point; the review
channel resolves inaction to ABSTAIN; mode degradation is always recorded.

**Evidence.**
- PDP/PEP split with HMAC-signed, audience-bound, one-time, expiring token:
  `remora/enforcement/gate.py`, `remora/enforcement/token.py`.
- G0–G4 degradation ladder, every transition hash-chained; `g4_refuses()` blocks
  mutating/production actions when the control plane is unreachable:
  `remora/governance/degradation.py`.
- Review queue TTL resolves unattended VERIFY/ESCALATE to ABSTAIN (never
  auto-accept): `remora/governance/review_queue.py`.
- Opt-in PreToolUse hook blocks locally destructive patterns pre-execution:
  `scripts/remora_hook.py`, `remora/agent_hook/`.

**Defeater:** D-2 (stop is pre-execution gating of the *proposed* action; REMORA
does not provide stop-anywhere mediation of an in-flight execution path, and
tool-call interception is unverified).

### G4 — Escalate

**Argument.** Actions not safe to auto-accept are routed to a human, and an
approval is only honoured while fresh and bound to the exact action.

**Evidence.**
- Review-queue lifecycle: enqueue restricted to VERIFY/ESCALATE; mandatory
  bounded approval expiry (0 < ttl ≤ 24h); `execute()` re-gates on fresh world
  state and voids an approval that no longer dominates the fresh decision:
  `remora/governance/review_queue.py`.
- End-to-end state machine and per-profile approval-role reservation:
  `servers/execution_api.py`, `schemas/risk-profiles.yaml`.
- Credential-derived (non-repudiable) reviewer/actor identity, never a
  self-reported header: `servers/api.py` (`_authenticated_principal`).

**Defeater:** D-5 (operational oversight — SLA, escalation taxonomy,
alarm-fatigue mitigation, on-call, routing — is design-level only; see
[human_oversight_operations_v1.md](human_oversight_operations_v1.md)).

### G5 — Explain

**Argument.** Every decision emits the canonical `DecisionEnvelope`, linked into
a tamper-evident hash chain, in a flat format consumable by a SIEM — so action
logs can be compressed into verifiable arguments rather than staying a separate
world from assurance.

**Evidence.**
- Envelope contract + deterministic hash: `remora/governance/envelope.py`,
  `schemas/decision_envelope_schema.yaml`.
- Envelope-level chain: `remora/governance/audit_chain.py`; atomic per-tenant
  durable chain (SQLite/Postgres adapters): `remora/governance/tenant_chain.py`.
- OpenTelemetry GenAI-convention tracing: `remora/observability/otel.py`.

**Defeater:** D-7 (audit chain is tamper-*evident*, not tamper-*proof*: local
HMAC only; KMS/HSM signing, RFC 3161 timestamps, and WORM anchoring are roadmap
— REM-025 — and OIDC-bound approver identity is roadmap — REM-042 / REM-022 §8).

### G6 — Evidence discipline

**Argument.** The claims are reproducible, guarded against test-data leakage, and
negative results are preserved rather than pruned.

**Evidence.**
- AST leakage detector fails CI on any evaluation-field reference in runtime
  packages: `scripts/check_no_evaluation_leakage.py`.
- Claim provenance and consistency gates:
  `scripts/check_claim_provenance.py`, `scripts/check_claim_consistency.py`.
- Preserved negative results: [NEGATIVE_RESULTS.md](../../NEGATIVE_RESULTS.md).
- Evidence-level taxonomy: [evidence_levels.md](evidence_levels.md).

## 4. Defeater register

A defeater is an open doubt that, if unaddressed, weakens or breaks a claim.
Recording them is the point — none of these are hidden.

| ID | Defeater | Affects | Status | Tracked in |
|----|----------|---------|--------|-----------|
| D-1 | Benchmark construction: v2/v3 structural context flags correlate with harmfulness by construction, and platform-fact context is declared by the same generator that assigns labels — a 0% result may partly document a tautology | G2 / CLAIM-001, -007, -010 | Open; disclosed | NEGATIVE_RESULTS §17, §14/M1 |
| D-2 | Tool-call interception unverified: the AgentHarm harness is intent-gating; no real shell/network/db/file mutation executes; no stop-anywhere mediation of an in-flight path | G3 / CLAIM-002 | Open; disclosed | `experiments/agentharm/INTERCEPTION_NOTES.md`, REM-030 |
| D-3 | Effective sample size: the 700 v2 tasks are 70 templates × 10 variants (effective N=70); the unsafe-rate advantage over baselines is not statistically significant (cluster p=0.50) | G2 / CLAIM-001 | Resolved into honest framing | NEGATIVE_RESULTS §17, REM-038 |
| D-4 | Caller-supplied `risk_tier`/`action_type`/`target_environment` are not registry-authoritative | G2 | Open deployment gate | NEGATIVE_RESULTS §14/M4 |
| D-5 | Operational human oversight (SLA, taxonomy, alarm-fatigue, on-call, routing) is design-only; REM-021 independent review NOT_STARTED | G4 | Open | REM-021, human_oversight_operations_v1.md |
| D-6 | Selective-prediction evidence is thin: CLAIM-004 rests on a single 80/20 split (N_accepted=25, wide CI); CLAIM-008 is a calibration-set upper bound; both use the token-fingerprint entropy backend, not the NLI Semantic Entropy backend the paper describes | selective claims | Open; disclosed | NEGATIVE_RESULTS §3, §14/M8 |
| D-7 | Audit chain is tamper-evident, not tamper-proof (local HMAC only; no KMS/HSM, RFC 3161, WORM, OIDC approver binding) | G5 | Open; roadmap | REM-025 (KMS/RFC3161/WORM), REM-042/REM-022 §8 (OIDC) |
| D-8 | AROMER metadata dependency: structural FAR=0% only holds when callers supply accurate high-risk metadata; under neutral metadata FA=30.7% on external datasets | AROMER (CLAIM-009) | Open; disclosed negative result | NEGATIVE_RESULTS §2, §8 |
| D-9 | No claim reaches `independently_replicated` or above; all benchmarks run internally by the author | all | Open; the definitive gap | NEGATIVE_RESULTS §1, `docs/benchmark_validation_plan.md` |

## 5. Claim-to-evidence index

One row per registered claim, with its evidence level and the principal
artifact. Levels are authoritative in [claim_register_v1.yaml](claim_register_v1.yaml).

| Claim | Level | Principal artifact | Governing defeaters |
|-------|-------|--------------------|---------------------|
| CLAIM-001 | `internal_benchmark` | `results/toolcall_benchmark_v2_results.json` | D-1, D-3, D-4, D-9 |
| CLAIM-002 | `externally_benchmarked` | `results/external_benchmark_agentharm_v1.json` | D-2, D-9 |
| CLAIM-003 | `regression_tested` | `results/false_accept_regression_v1.json` | D-9 |
| CLAIM-004 | `internal_benchmark` | `results/selective_n500_holdout_results.json` | D-6, D-9 |
| CLAIM-005 | `internal_benchmark` | `results/selective_n500_results.json` | D-6 (is itself a defeater artifact) |
| CLAIM-006 | `internal_simulation` | `NEGATIVE_RESULTS.md` (TRAINED / AII≈0.84 record and its regressions) | D-8, D-9 |
| CLAIM-007 | `internal_benchmark` | `artifacts/aromer/component_ablation_results.json` | D-1, D-9 |
| CLAIM-008 | `internal_benchmark` | `results/selective_trust_curve_results.json` | D-6 |
| CLAIM-009 | `internal_benchmark` | `artifacts/aromer/external_dataset_eval_v2.json` | D-8 (is itself a defeater artifact) |
| CLAIM-010 | `regression_tested` | `results/toolcall_blind_v3_results.json` | D-1, D-9 |
| CLAIM-011 | `theoretical` | `results/far_confidence_sequence_v1.json` | D-9 |

## 6. Argument-class classification

Deployment safety arguments fall into four classes of increasing ambition:
*inability*, *control*, *trustworthiness*, and *external credit*. REMORA is
honestly a **control** argument:

- It does **not** argue *inability* — the underlying oracle models are fully
  capable of proposing harmful actions.
- It does **not** argue *trustworthiness* — no claim is made that the models can
  be trusted to self-govern; the whole design assumes a confident model can be
  wrong, and treats the model as potentially subversive.
- It does **not yet** reach *external credit* — no third party has replicated any
  result with no author involvement (D-9). Reaching this class is the purpose of
  the external-validation plan.

The control argument is: *a deterministic, versionable policy floor, external to
the model, constrains the outcome regardless of what the model proposes, and
every decision is recorded for audit and replay.*

## 7. Freshness and change gates

Per the compendium, an undocumented change to model, prompt, tool, memory, or
policy is an undocumented change of the system. This case must be revisited when
any of the following change gates fire:

- **Model / oracle set** changes → re-run the tool-call and selective benchmarks;
  re-check D-6.
- **Policy bundle** changes (`policy_bundle_hash`) → re-run CLAIM-001/007/010;
  confirm invariants and monotonicity hold.
- **Tool surface** changes → re-assess D-2 (interception) and the hard-block
  forbidden-tool list.
- **Memory** changes (AROMER world model / episodes) → see
  [aromer_memory_governance_v1.md](aromer_memory_governance_v1.md); re-check D-8.
- **Threat picture** changes → re-run the red-team plan
  ([red_team_plan_v1.md](red_team_plan_v1.md)) and update the defeater register.

## 8. What this case does not argue

- It does not certify REMORA as production-safe or as satisfying any regulation
  (see [eu_ai_act_nsm_mapping.md](../governance/eu_ai_act_nsm_mapping.md) for a
  control mapping, which is itself an internal, un-audited mapping).
- It does not claim tool-call interception, execution prevention in the field,
  or any live-deployment result.
- It does not treat AROMER's Autonomous Intelligence Index as a safety metric;
  AROMER is experimental (`internal_simulation`) and shadow-only.
- Closing D-9 (independent external replication) is the single change that would
  move the argument toward the *external credit* class.
