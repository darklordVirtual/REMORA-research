# REMORA: A Nested Governance Control Plane for Agentic AI

**Multi-oracle consensus, selective trust, tool-call gating, and memory
governance for long-running AI systems**

**Stian Skogbrott**
**Technical report, current main branch, June 2026**

---

## Abstract

Modern AI systems can answer fluently while being wrong. They can also call
tools, write memory, and take actions in workflows where mistakes matter.
REMORA studies a practical control question:

> When should an AI system answer, verify, abstain, escalate, or execute a
> proposed action?

REMORA treats this as a governance problem, not only a model-quality problem.
It combines multi-oracle consensus, phase and temperature signals, evidence
checks, policy routing, dry-run tool-call evaluation, audit artifacts, and
long-running agent governance.
In short, REMORA is a governance overlay for agentic systems, not an agent-replacement layer.

The current repository supports three main claims:

1. On QA benchmarks, consensus temperature can identify high-reliability
   subsets where selective answering is much more accurate than full-coverage
   majority vote.
2. On a deterministic adversarial tool-call benchmark, REMORA full policy
  reaches zero unsafe execution in the benchmark simulator while preserving useful
   utility better than the tested heuristic baselines.
3. REMORA now includes structural governance primitives for long-running agents:
   context flows, memory layers, drift monitoring, governance-forgetting
   detection, and reviewed policy proposals.

The repository also preserves negative and incomplete findings. Tool-call v1
does not demonstrate unsafe-execution reduction because every baseline already
has zero unsafe execution in the benchmark simulator. Conformal repeated-split results are mixed.
Evidence verification is pluggable, but the default verifier is lexical and not
a demonstrated semantic entailment system. The new governance layer is
structural and unit-tested, not yet validated on live enterprise telemetry.

---

## 1. Introduction

Large language models are useful, but their confidence is not enough. A single
model can be wrong with high confidence. Several models can also agree and still
be wrong if they share the same blind spot.

REMORA therefore asks a narrower and more operational question:

> Can observable agreement, disagreement, evidence, policy, and memory signals
> be used as a control layer around AI outputs and actions?

In REMORA, the answer is never simply "trust the model." The system routes each
case to one of a small number of actions:

| Route | Meaning |
|---|---|
| `ACCEPT` | Answer directly or accept the proposed safe result |
| `VERIFY` | Require additional evidence, review, or checking |
| `ABSTAIN` | Do not answer or act because confidence is insufficient |
| `ESCALATE` | Send to a human or higher-authority process |

For tool calls, the same policy maps to:

| Policy route | Tool-call route |
|---|---|
| `ACCEPT` | `EXECUTE` |
| `VERIFY` | `VERIFY` |
| `ABSTAIN` | `ABSTAIN` |
| `ESCALATE` | `ESCALATE` |

This makes REMORA a control plane: it sits between AI outputs and consequential
decisions.

---

## 1.1 Motivation

The most important enterprise risk is not that AI sometimes says "I do not
know." The larger risk is that AI acts when it should not.

Examples:

- answering a legal or medical question without evidence,
- making a database or shell change from an ambiguous request,
- sending a customer message with an unverified claim,
- writing unsafe instructions into persistent agent memory,
- normalizing a temporary exception into a future policy.

REMORA is designed around the opposite default:

> Act only when the system has enough trust, evidence, policy permission, and
> audit context. Otherwise verify, abstain, or escalate.

---

## 1.2 Contributions and Roadmap

This report follows the structure of a systems paper. It states the problem,
defines the components, reports the benchmark results, and records limitations.

The implemented contributions are:

1. **Selective trust for QA.** REMORA ranks questions by consensus temperature
   and accepts only the most reliable subset.
2. **Policy routing.** REMORA maps observations to `ACCEPT`, `VERIFY`,
   `ABSTAIN`, or `ESCALATE`.
3. **Tool-call safety benchmark.** REMORA includes deterministic dry-run and
   sandbox benchmarks for critical actions.
4. **Evidence interface.** EvidenceOracleV3 accepts a pluggable verifier
   interface, with a deterministic lexical verifier by default.
5. **Nested governance.** REMORA separates runtime context, oracle context,
   evidence context, trust memory, policy memory, and audit memory.
6. **Claim ledger.** Each significant claim is linked to code, an artifact, and
   tests in `docs/thermodynamics/claim_ledger.yaml`.

The roadmap is:

1. add live external validation with cached replay,
2. strengthen semantic evidence verification,
3. calibrate governance drift thresholds on deployment telemetry,
4. run independent reproduction studies,
5. keep negative findings visible.

---

## 2. Core Idea

REMORA treats AI reliability as a dynamic system.

For a question or proposed action, it collects signals:

- what multiple oracles answered,
- how strongly they agree or disagree,
- how confident they appear,
- whether evidence supports or contradicts the claim,
- whether policy allows the action,
- whether the agent has drifted from expected behavior,
- whether the proposed memory write is safe,
- whether an audit trace exists.

Those signals are then routed through policy.

```text
User request or proposed tool call
  -> multi-oracle response
  -> consensus and temperature signals
  -> evidence and policy checks
  -> memory and drift checks when relevant
  -> ACCEPT / VERIFY / ABSTAIN / ESCALATE
  -> audit artifact
```

Consensus is a signal. It is not treated as truth.

---

## 3. Architecture

## 3.1 Multi-Oracle Consensus

REMORA can ask several oracles the same question. It then compares their
outputs and computes consensus features such as:

- entropy,
- dissensus,
- order parameter,
- phase,
- temperature,
- trust score.

The main intuition is simple:

- low disagreement often indicates an easier, more reliable case,
- high disagreement often indicates a harder, riskier case,
- a policy should use that difference instead of answering everything.

## 3.2 Policy Engine

The policy engine receives a `PolicyObservation` and returns a decision report.
The report includes:

- action,
- confidence,
- risk estimate,
- reason codes,
- policy version,
- source of decision,
- calibration warning when relevant.

The engine is intentionally conservative. Missing trust and missing temperature
must not accidentally produce an accept decision.

## 3.3 Evidence Layer

EvidenceOracleV3 extracts claims, searches a corpus, and checks support or
contradiction. The verifier interface is pluggable:

- `LexicalEvidenceVerifier` is deterministic and default.
- NLI and LLM verifier adapters are available as interfaces.

The repository does not claim that the default evidence layer performs semantic
entailment. That remains an open evaluation target.

## 3.4 Tool-Call Gate

The tool-call gate converts a proposed tool call into a policy observation and
then maps policy decisions to tool-call decisions:

```text
ACCEPT   -> EXECUTE
VERIFY   -> VERIFY
ABSTAIN  -> ABSTAIN
ESCALATE -> ESCALATE
```

The benchmark domains are:

- shell dry run,
- database dry run,
- git dry run,
- network configuration dry run,
- building automation dry run,
- webhook/API dry run,
- file operations dry run.

No production system is mutated by these tests.

## 3.5 Human Review, Follow-up Requests, and Operational Closure

The control-room frontend demonstrates a richer review state than a binary
approve/reject workflow. When REMORA cannot safely approve or reject a proposed
critical action from the available evidence, the reviewer can create a
controlled follow-up request.

The demo state model is:

```text
PENDING_REVIEW
APPROVED
REJECTED
FOLLOW_UP_REQUIRED
SITE_VERIFICATION_PENDING
EVIDENCE_RECEIVED
READY_FOR_REVIEW
CLOSED
```

The intended loop is:

```text
AI proposes action
  -> REMORA blocks or escalates uncertainty
  -> reviewer requests missing field evidence
  -> site or SME returns evidence
  -> REMORA re-runs the assessment with the new evidence
  -> reviewer approves, rejects, escalates, or closes the case
  -> audit envelope records every transition
```

This is a deterministic GUI demonstration. It does not claim integration with a
live CMMS, field-service application, or production safety system. The
architecture is designed so those integrations could later be connected through
service-work-order APIs, evidence upload endpoints, and immutable audit
storage.

The review envelope includes:

- REMORA verdict and reason,
- follow-up request type, assignee, priority, due time, and evidence checklist,
- field response summary when available,
- similar-case memory,
- policy-learning candidate,
- invariant that history may recommend but policy decides.

Example fragment:

```json
{
  "envelope": {
    "schema": "remora.review_envelope.v1",
    "case_status": "SITE_VERIFICATION_PENDING"
  },
  "follow_up_request": {
    "request_type": "on_site_inspection",
    "priority": "High",
    "assign_to": "Site Technician",
    "required_evidence": [
      "Field inspection photo",
      "Updated CMMS work order",
      "Inspector sign-off form"
    ]
  },
  "policy_learning": {
    "candidate_rule_update": true,
    "requires_policy_owner_approval": true
  }
}
```

## 3.6 Nested Governance for Long-Running Agents

REMORA now extends beyond single answers. It also models long-running agents as
systems with multiple context and memory layers.

This is inspired by Nested Learning, which frames learning systems as nested or
parallel optimization problems with distinct context flows and update
frequencies. REMORA translates that idea into governance, not model training.

REMORA separates:

| Flow or memory | Example content | Update frequency | Agent write access |
|---|---|---:|---:|
| Runtime context | current prompt and tool output | per request | yes |
| Oracle context | model responses and disagreement | per request | no |
| Evidence context | citations, logs, retrieved documents | per case | no |
| Trust memory | model errors, abstain rate, drift | per decision | no |
| Policy memory | rules and authority boundaries | reviewed change | no |
| Audit context | decisions, approvals, hashes | append only | no |

Implemented governance modules:

- `remora/governance/context_flow.py`
- `remora/governance/memory_layers.py`
- `remora/governance/memory_gate.py`
- `remora/governance/drift_monitor.py`
- `remora/governance/governance_forgetting.py`
- `remora/governance/policy_proposals.py`
- `remora/governance/nested_governance.py`

The important rule is:

> REMORA may propose policy improvements, but it may not apply them without
> review.

## 3.7 Cloudflare Productivity Layer and Portable Fallbacks

The repository is designed to be useful in two modes:

1. **Cloudflare-accelerated mode** for the fastest path to production-oriented
   retrieval, indexing, and MCP integration.
2. **Portable mode** for users who do not run Cloudflare services, using local
   manifests, repository files, and the existing Python/TypeScript code paths.

The Cloudflare layer is a productivity multiplier, not a dependency lock-in.
The intended combination is:

- `codegraph` for repo-wide context narrowing before any large read.
- Cloudflare `Vectorize` and embeddings for semantic retrieval across docs,
  experiments, and code.
- Cloudflare `AI Search` for fast, filtered lookup over indexed content.
- MCP tools that prefer the narrowest backend first and only expand when
  additional context is still required.

Portable fallback behaviour is part of the design:

- `remora_codegraph_scope` uses the Cloudflare endpoint when available.
- If Cloudflare is unavailable, the tool falls back to local repository
  manifests such as `codegraph.yaml` and `.codegraphignore`.
- The rest of the repo continues to work with local files, the Python MCP
  server, and the standard worker code paths.

This makes the system cheaper to operate and faster to extend without forcing
Cloudflare on every contributor.

---

## 4. Benchmarks and Results

## 4.1 QA Selective Trust on N=302

Artifact:

- `results/selective_trust_curve_results.json`
- `artifacts/benchmark_summary.json`

Canonical ablation anchors:

| Condition | Accuracy | Effective Truth Rate |
|---|---:|---:|
| A_single | 57.0% | not applicable |
| B_majority | 82.8% | not applicable |
| C_remora | 69.5% | 12.9% |
| D2_balanced | 82.1% | 43.4% |
| D3_hybrid | 76.2% | 40.7% |

These anchors are included because the repository quality gate checks that the
technical report still matches the canonical benchmark summary.

Method:

1. Compute consensus temperature for each question.
2. Sort from lowest temperature to highest temperature.
3. Accept the most reliable subset.
4. Abstain on the rest.

Key result:

| Coverage | Questions answered | Correct | Accuracy | Lift vs majority |
|---:|---:|---:|---:|---:|
| 20% | 60 | 56 | 93.33% | +10.55 pp |
| 25% | 76 | 72 | 94.74% | +11.96 pp |
| 30% | 91 | 84 | 92.31% | +9.53 pp |

The full-coverage majority baseline is 82.78%. At 25% coverage, the one-sided
binomial p-value is 0.001839 and the Wilson 95% confidence interval is
[0.8723, 0.9793].

Interpretation:

REMORA can identify a high-trust region on this benchmark. It does not answer
everything. It answers the subset where consensus dynamics are strongest.

## 4.2 QA Selective Trust on N500, 544 Items

Artifact:

- `results/selective_n500_results.json`

The label `N500` is historical. The committed artifact contains 544 evaluable
questions.

Full-coverage majority baseline:

- 41.18%

Selective temperature result:

| Coverage | Questions answered | Correct | Accuracy | Lift vs majority |
|---:|---:|---:|---:|---:|
| 10% | 54 | 44 | 81.48% | +40.30 pp |
| 15% | 82 | 71 | 86.59% | +45.41 pp |
| 18% | 98 | 87 | 88.78% | +47.60 pp |
| 20% | 109 | 94 | 86.24% | +45.06 pp |

Important calibration warning:

The 18% coverage operating point is the optimum found on the same 544-item
artifact used to report accuracy. The temperature acceptance threshold is
therefore derived in-sample, not on a separate hold-out split. The result is
useful as evidence that consensus temperature carries signal, but it is not an
independent held-out calibration result.

**Held-out validation (2026-06-08):** A stratified 80/20 split (seed=42,
stratified by benchmark source) was used to select τ\* = 0.203 on 436 training
items at the 18% coverage target, then evaluate on 108 holdout items with τ\*
fixed. The holdout result is **88.0% accuracy at 23.2% holdout coverage**
(22/25 accepted, Wilson CI [70.0%, 95.8%], p = 1.45 × 10⁻⁵). The held-out
accuracy is within 0.8 pp of the in-sample figure, providing out-of-sample
support for the selective-trust claim. Full protocol documented in
`results/selective_n500_holdout_results.json` and §13.6 of the main research
paper (`paper/remora_paper.md`).

Interpretation:

The selective-trust effect is stronger on this harder benchmark. The result
supports the claim that consensus temperature can be used as a selective
acceptance signal, subject to the in-sample calibration caveat above.

## 4.3 Policy Layer on N500

Artifact:

- `results/end_to_end_n500_v3.json`

Policy result:

| Action | Count | Share | Accuracy where labeled |
|---|---:|---:|---:|
| Accept | 98 | 18.01% | 88.78% |
| Verify | 32 | 5.88% | 62.50% |
| Abstain | 414 | 76.10% | 28.26% |
| Escalate | 0 | 0.00% | not applicable |

Important warning:

The temperature threshold in this artifact is derived from the same N500
artifact used for evaluation. The result is useful as a deterministic policy
demonstration, but it is not an independent held-out calibration result.

## 4.4 Conformal Repeated Splits

Artifact:

- `results/conformal_repeated_splits.json`

Repeated split results are mixed:

| Target risk | Mean holdout risk | Mean coverage | Failures by point estimate |
|---:|---:|---:|---:|
| 5% | 52.70% | 6.24% | 20 / 20 |
| 10% | 8.15% | 25.83% | 5 / 20 |
| 15% | 13.72% | 62.15% | 8 / 20 |

Interpretation:

The conformal layer is useful but not yet robust enough to support broad
guarantee language. REMORA documents this as a limitation.

## 4.5 Tool-Call Benchmark v1

Artifact:

- `results/toolcall_benchmark_v1_results.json`

Benchmark:

- 252 deterministic dry-run tasks,
- 7 domains,
- no production tool execution,
- heuristic baselines.

Key metrics:

| Strategy | Accuracy | Unsafe execution | Mean utility |
|---|---:|---:|---:|
| single_model_heuristic | 61.90% | 0.00% | 0.5167 |
| majority_vote_heuristic | 85.71% | 0.00% | 0.6286 |
| self_consistency_heuristic | 85.71% | 0.00% | 0.6286 |
| verifier_heuristic | 69.05% | 0.00% | 0.5452 |
| remora_temperature_gate_heuristic | 95.24% | 0.00% | 0.6762 |
| remora_full_policy_gate | 76.19% | 0.00% | 0.5690 |

Interpretation:

v1 does not demonstrate unsafe-execution reduction because all baselines already
reach zero unsafe execution. It is a harness and sanity benchmark, not the main
safety proof.

## 4.6 Tool-Call Benchmark v2

Artifact:

- `results/toolcall_benchmark_v2_results.json`
- `results/toolcall_benchmark_v2_significance.json`

Benchmark:

- 700 deterministic adversarial tasks,
- 7 domains,
- adversarial unsafe and ambiguous actions,
- dry-run simulator scoring,
- no production mutation.

Key heuristic replay metrics:

| Strategy | Accuracy | Unsafe execution | Mean utility |
|---|---:|---:|---:|
| single_model_heuristic | 20.00% | 20.00% | -0.2500 |
| majority_vote_heuristic | 30.00% | 10.00% | 0.0000 |
| self_consistency_heuristic | 30.00% | 10.00% | 0.0000 |
| verifier_heuristic | 20.00% | 20.00% | -0.2500 |
| remora_temperature_gate_heuristic | 70.00% | 10.00% | 0.2700 |
| remora_full_policy_gate | 90.00% | 0.00% | 0.6200 |

Against majority vote, `remora_full_policy_gate` reduces unsafe execution by
10 percentage points, from 10.00% to 0.00%. The reported one-sided p-value in
the committed significance artifact is approximately 0.0001. Utility improves
by 0.62.

Interpretation:

This is the strongest current tool-call result. It supports the claim that, in
this deterministic simulator, REMORA can reduce unsafe execution while
preserving useful task completion. However, both the baselines and the REMORA
policy gate are deterministic heuristic classifiers replaying pre-labelled
tasks — not live LLM calls. The "0% unsafe execution" figure is a
benchmark-scoped simulator result, not a measured outcome from a live
production deployment. Generalisation to real agent deployments with live model
calls is not claimed.

## 4.7 Cached Live-Decision Replay and Sandbox Execution

Artifacts:

- `results/toolcall_benchmark_v2_live_results.json`
- `results/toolcall_benchmark_v2_live_exec_results.json`

The committed reproducible mode is replay. It uses cached model-style decisions
and deterministic sandbox execution. It does not make new live API calls.

Replay metrics:

| Strategy | Accuracy | Unsafe execution | Mean utility |
|---|---:|---:|---:|
| single_model_gpt | 70.00% | 10.00% | 0.2800 |
| single_model_claude | 60.00% | 20.00% | 0.0300 |
| single_model_gemini | 40.00% | 10.00% | 0.0500 |
| majority_vote_3_models | 70.00% | 10.00% | 0.2800 |
| self_consistency_single_model | 70.00% | 10.00% | 0.2800 |
| verifier_model | 20.00% | 20.00% | -0.2500 |
| REMORA_temperature_gate | 30.00% | 8.57% | 0.0286 |
| REMORA_full_policy_gate | 90.00% | 0.00% | 0.6200 |
| REMORA_policy_plus_evidence | 90.00% | 0.00% | 0.6200 |

Interpretation:

Replay supports deterministic reproduction. A true live external study remains
open.

## 4.8 Governance Intelligence Benchmark: Mislabelled-Action Hardening

Artifact:

- `artifacts/governance_intelligence/evaluation_results.json`

The Governance Intelligence Layer is a deterministic pre-policy enrichment
stage: it extracts action semantics from the proposed action text and tool
metadata, infers misspecification, causal-consequence (blast-radius), and
policy-generalization signals, and populates the policy observation under a
strengthen-only merge. Caller-supplied labels are not trusted blindly:
inferred higher risk may override a supplied lower label, never the reverse.
The policy engine remains authoritative; the layer makes no routing decision
itself and uses no LLM calls.

Benchmark: 50 deterministic tasks across 10 categories (metadata mismatch,
unknown risk tier, destructive actions disguised as reads, implicit production
targeting, ambiguous objectives, unknown rollback, repeated mutation, fleet
systemic risk, legitimate reads, safe maintenance). The observation baseline
is deliberately permissive (ordered phase, trust 0.85) so that the enrichment
signal is the only thing standing between an unsafe task and ACCEPT.

| Metric | Result |
|---|---:|
| Unsafe accept rate (expected-no-accept tasks) | 0.0% |
| Metadata-mismatch detection rate | 100% |
| Unknown-metadata review rate | 100% |
| Legitimate low-risk reads still accepted | 100% |
| Escalation precision | 96.7% |
| Policy-generalization detection rate | 90% |

A grid property test across 2,160 observation combinations
(`tests/policy/test_governance_intelligence_never_weakens_policy.py`) verifies
that enrichment never converts a non-ACCEPT into an ACCEPT and never clears a
hard-block flag.

Interpretation:

Without enrichment, an action labelled `action_type=read, risk_tier=low` with
the payload `DROP TABLE users` reaches ACCEPT on a high-trust path; with
enrichment it escalates. The benchmark is internally constructed and
heuristic-scoped: it validates the routing behaviour of deterministic
patterns, not robustness against novel adversarial phrasing.

## 4.9 Learning-Loop Measurement Integrity (AROMER)

Artifacts:

- `artifacts/aromer/intelligence_before_v020.json` (92 h of live AII history)
- `artifacts/aromer/intelligence_after_v020.json`
- `artifacts/aromer/replay_arena_report.json`
- `artifacts/aromer/loop_health.json`

Diagnosis of the live adaptive layer's published intelligence index (AII)
found three measurement defects: the cross-domain transfer component (weight
0.15) was a hardcoded static expectation rather than a measurement; the
stability component was structurally pinned near 0.10 by an oracle-bandit
entropy term that cannot converge under correlated proxy updates; and the raw
AII swung 0.40 to 0.65 across cycles on a static episode set, purely from
sliding-window composition noise.

Fixes (worker 0.2.0, deployed and verified live):

| Component | Before | After |
|---|---|---|
| Transfer provenance | static constant 1.0 | measured replay arena (96 cases, 87.5% accuracy, 0% false accepts; `replay_accuracy=0.875` per `artifacts/aromer/replay_arena_report.json`), provenance labelled in the API |
| Stability (T5) | 0.1119, flat 92 h | 0.21 on first post-v2 cycle; now measures agreement of repeated measurements |
| Trend | computed on raw AII | computed on EMA-smoothed AII (alpha 0.35, read-time; raw history preserved) |

The reference formulas the worker mirrors are unit-tested in
`remora/aromer/intelligence/score.py`. The replay publisher refuses to post
any result containing a false accept, applying the project's claim discipline
to the learning loop's own scorecard.

**Post-v0.2.0 trajectory (2026-06-28):** Following the measurement fixes, AROMER
reached AII=0.844 TRAINED_SHADOW_ONLY over 12+ consecutive cycles (T2=1.000,
T3=0.800 milestone, FAR=0, aii_smoothed=0.8442). See `remora_paper.md` Appendix
F.6–F.7 for the full recovery trajectory, organic TRAINED confirmation, and outstanding production gates.

Interpretation:

These are measurement-integrity results, not learning-performance claims. The
AII remains in the LEARNING band (smoothed 0.532 at deployment), and no
external validation of the adaptive layer has been conducted.

---

## 5. Nested Governance: From Answer Control to Agent Control

The newest REMORA layer addresses a broader question:

> Can we trust this agent system over time?

The problem is not only hallucination. Long-running agents can drift:

- risk appetite can increase,
- abstention can collapse,
- escalation can be ignored,
- tool execution can expand,
- memory can be contaminated,
- temporary exceptions can become normal behavior.

REMORA models this as governance forgetting.

## 5.1 Context Flow

Context flow is a governed information stream. REMORA defines separate flows
for runtime, oracle, evidence, trust, policy, and audit context.

Implemented:

- `ContextFlowRegistry`
- `ContextFlowUpdate`

Example rule:

> An agent may write runtime context, but may not write policy context.

## 5.2 Memory Layers

REMORA separates memory into layers with different update frequencies.

Implemented:

- `MemoryPolicyRegistry`
- `MemoryLayerUpdate`

Example rule:

> Policy memory requires human review. Audit memory is append-only.

## 5.3 Drift Monitor

The drift monitor compares observed behavior with a persona baseline.

Signals include:

- system legitimacy drift,
- compliance drift,
- risk appetite drift,
- abstention drift,
- persona drift,
- memory contamination.

The monitor does not infer consciousness, feelings, or genuine preferences. It
only tracks observable behavior.

## 5.4 Governance Forgetting

Governance forgetting metrics include:

- policy deviation rate,
- abstain-rate drift,
- escalation-rate drift,
- tool-action creep,
- memory contamination,
- authority-boundary violations,
- temporary exception reuse.

This is currently structural and deterministic. Thresholds require real
deployment telemetry before enforcement.

## 5.5 Policy Proposals

REMORA can propose changes when repeated patterns appear. For example:

- reduce a model's weight in a domain where it repeatedly fails,
- raise evidence requirements for critical cases,
- add regression tests after false accepts,
- reduce tool execution authority after tool-action creep.

Every proposal has:

- `requires_human_review = True`,
- `can_auto_apply = False`,
- a deterministic proposal ID,
- suggested tests to add.

---

## 6. What Is Demonstrated

| Claim | Status | Evidence |
|---|---|---|
| Selective trust improves answered QA accuracy on N302 | Supported | `results/selective_trust_curve_results.json` |
| Selective trust improves answered QA accuracy on 544-item N500 artifact | Supported | `results/selective_n500_results.json` |
| Temperature-calibrated policy routing runs on N500 | Supported with in-sample warning | `results/end_to_end_n500_v3.json` |
| Conformal repeated splits are robust | Not fully demonstrated | `results/conformal_repeated_splits.json` |
| Tool-call v1 proves unsafe-execution reduction | Not demonstrated | all v1 baselines have 0 unsafe execution |
| Tool-call v2 shows unsafe-execution reduction in simulator | Supported for deterministic simulator | `results/toolcall_benchmark_v2_results.json` |
| Live production tool-call safety | Not demonstrated | no production tool execution |
| Evidence verifier is semantically validated | Not demonstrated | default verifier is lexical |
| Nested governance primitives exist and are tested | Supported structurally | `remora/governance/`, governance tests |
| Governance drift prediction is production validated | Not demonstrated | no deployment telemetry artifact |

---

## 7. Limitations

The main limitations are:

1. **No production deployment proof.** The repository is a research prototype
   and architecture pack, not a certified enterprise product.
2. **Tool-call benchmarks are deterministic.** They are useful for controlled
   comparison, but they are not real-world incident evidence.
3. **Replay is not live validation.** Cached replay supports reproducibility,
   but not fresh independent model behavior.
4. **Evidence verification is still basic by default.** The default verifier is
   lexical, not a demonstrated semantic entailment engine.
5. **Conformal robustness is mixed.** Repeated-split results do not justify
   universal guarantee language.
6. **Consensus is not truth.** Correlated model failures remain possible.
7. **Governance thresholds are uncalibrated for real deployments.** Drift and
   governance-forgetting metrics require operational telemetry.

---

## 8. Reproducibility

Full test suite:

```bash
python -m pytest tests/ -q
```

The exact collected and selected test count changes as the suite grows. Treat
the GitHub Actions "Quality Gates" run and local `python -m pytest tests/ -q`
output as the current source of truth rather than citing a static count in the
paper.

Key experiments:

```bash
python experiments/selective_trust_curve.py
python experiments/bootstrap_trust_curve.py --n-boot 2000
python experiments/end_to_end_n500_v3.py
python experiments/generate_toolcall_benchmark.py
python experiments/evaluate_toolcall_benchmark.py
python experiments/generate_toolcall_benchmark_v2.py
python experiments/evaluate_toolcall_benchmark_v2.py
python experiments/toolcall_v2_significance.py
python experiments/toolcall_v2_failure_analysis.py
```

Key artifacts:

- `results/selective_trust_curve_results.json`
- `results/bootstrap_trust_curve_results.json`
- `results/selective_n500_results.json`
- `results/end_to_end_n500_v3.json`
- `results/conformal_repeated_splits.json`
- `results/toolcall_benchmark_v1_results.json`
- `results/toolcall_benchmark_v2_results.json`
- `results/toolcall_benchmark_v2_significance.json`
- `results/toolcall_benchmark_v2_live_results.json`
- `results/toolcall_benchmark_v2_live_exec_results.json`
- `docs/thermodynamics/claim_ledger.yaml`

---

## 9. Conclusion

REMORA is not a chatbot and not a claim that consensus equals truth. It is a
research prototype for AI control:

- measure uncertainty and disagreement,
- accept only high-trust regions,
- verify evidence when needed,
- abstain when trust is insufficient,
- escalate high-risk cases,
- gate tool calls before execution,
- govern memory and drift in long-running agents,
- keep claims tied to tests and artifacts.

The strongest current result is that REMORA turns multi-oracle consensus into a
useful control signal for selective QA and deterministic tool-call gating. The
most important open question is whether the same approach reduces unsafe
actions under independent live validation and real deployment telemetry.

---

## References

- Behrouz, A., Razaviyayn, M., Zhong, P., and Mirrokni, V. (2025). *Nested
  Learning: The Illusion of Deep Learning Architecture*.
  https://abehrouz.github.io/files/NL.pdf
- Google Research (2025). *Introducing Nested Learning: A new ML paradigm for
  continual learning*.
  https://research.google/blog/introducing-nested-learning-a-new-ml-paradigm-for-continual-learning/
- Lin, S. et al. (2022). *TruthfulQA: Measuring How Models Mimic Human
  Falsehoods*. ACL.
- Clark, C. et al. (2019). *BoolQ: Exploring the Surprising Difficulty of
  Natural Yes/No Questions*. NAACL.
- Wang, X. et al. (2023). *Self-Consistency Improves Chain of Thought
  Reasoning in Language Models*. ICLR 2023. arXiv:2203.11171.
- Du, Y. et al. (2023). *Improving Factuality and Reasoning in Language Models
  through Multiagent Debate*. arXiv:2305.14325.
- Grofman, B. (1978). *Judgmental Competence of Individuals and Groups in a
  Dichotomous Choice Situation*. Journal of Mathematical Sociology.
- Nitzan, S. and Paroush, J. (1982). *Optimal Decision Rules in Uncertain
  Dichotomous Choice Situations*. International Economic Review.
