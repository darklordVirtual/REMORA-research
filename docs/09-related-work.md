# Where does REMORA sit in the literature?

> **Note on `enterprise/*` references:** paths under `enterprise/` name design
> artifacts maintained in the enterprise edition / main implementation repo; they
> are not bundled in this research repo. Descriptive references are retained; the
> files themselves live outside this repository.

This document records the research lines that shaped REMORA and separates
inspiration from implemented claims. It is intentionally conservative: a paper
being relevant does not mean REMORA implements or outperforms it.

## 1. Selective Prediction and Abstention

Relevant ideas:

- selective classification and the reject option,
- risk-coverage curves,
- calibrated abstention under target risk.

How REMORA uses this:

- `remora/selective/guardrail.py`
- `remora/selective/conformal.py`
- N302 and N500 selective-acceptance experiments

Boundary:

- REMORA reports benchmark-scoped selective trust results.
- It does not claim universal out-of-distribution safety guarantees.

## 2. Conformal Risk Control and Anytime-Valid Inference

Relevant ideas:

- split-conformal calibration,
- finite-sample guarantees under exchangeability (Conformal Risk Control,
  Angelopoulos et al. 2022),
- repeated-split robustness checks,
- time-uniform (anytime-valid) confidence sequences that stay valid under
  optional stopping (Howard et al. 2021; Ramdas et al. 2023) — a distinct,
  sequential-monitoring cousin of conformal risk control.

How REMORA uses this:

- conformal thresholding for accept/verify/abstain routing (`remora/selective/crc.py`),
- explicit repeated-split artifacts,
- claim-ledger entries that record failed and mixed robustness results,
- a confidence sequence (`remora/selective/confidence_sequence.py`) for
  continuous false-accept-rate monitoring without inflating the guarantee by
  "peeking" (REM-020 / CLAIM-011).

Boundary:

- REMORA treats conformal results as exchangeability-dependent.
- Repeated-split failures are preserved as negative evidence.
- The confidence-sequence bound is conservative and valid only under its
  stated Beta-binomial mixture assumptions.

## 3. Self-Consistency, Debate, and Cross-Model Verification

Relevant ideas:

- self-consistency sampling,
- verifier models,
- cross-model disagreement as a hallucination or uncertainty signal,
- multi-agent debate and critique-revision.

How REMORA uses this:

- multi-oracle consensus,
- independent verifier gate,
- critique-revision loop,
- majority, self-consistency, verifier, and REMORA tool-call baselines.

Boundary:

- Consensus is not treated as truth.
- REMORA must combine agreement with evidence, policy, risk, and audit.

## 4. Tool-Use Safety and Agent Guardrails

Relevant ideas:

- tool invocation safety,
- dry-run and sandboxed evaluation,
- critical-action routing,
- prompt-injection and unsafe tool-call benchmarks,
- programmatic tool calling and typed Python planning APIs.

How REMORA uses this:

- `remora/toolcall/`
- deterministic tool-call benchmark v1,
- adversarial tool-call benchmark v2,
- dry-run and sandbox execution metrics,
- `EXECUTE / VERIFY / ABSTAIN / ESCALATE` action mapping,
- Governed Programmatic Tool Calling (GPTC, RF-11):
  `remora/toolcall/ptc/` — stub generator, AST call-graph extractor,
  governed batch executor.

Boundary:

- v1 is explicitly too easy for unsafe-execution differentiation.
- v2 provides deterministic adversarial evidence, not production proof.
- Live validation remains a separate research requirement.
- GPTC is a planning-layer prototype (RF-11, SCOPED); stubs return
  `ProposedCall` data objects only — no real API execution from the
  planning surface. Governance and dispatch are unchanged.

### 4a. Programmatic Tool Calling (PTC) — planning layer

Patel, Sen, Lumer & Subbiah (2025). *The Bitter Lesson of Tool Calling.*
arXiv:2608.06370. PricewaterhouseCoopers Commercial Technology and
Innovation Office.

The paper evaluates 14 LLMs on a benchmark of 200 tool-calling tasks spanning
single-call, sequential-chain (up to 12+ steps), and parallel fan-out
scenarios. Key empirical findings (authors' setup, authors' numbers):

- PTC matches or outperforms JSON tool calling on 13/14 models in fan-out
  tasks.
- At chain length ≥ 12, PTC shows an 18.8 percentage-point advantage over
  JSON calling.
- ~50 % reduction in wall-clock latency for chaining on 13/14 models.
- Under 128-tool context, PTC degrades far less than JSON calling
  ("context rot" resistance).
- Authors distinguish *aggregation accuracy* (correct final answer) from
  *enumeration accuracy* (correct tool calls actually invoked) — models
  can produce correct answers without executing the required tools.

**What REMORA takes from this (RF-11).**

REMORA already owns the governance-and-execution boundary; PTC provides a
complementary composition surface *above* that boundary. The key architectural
principle from ChatGPT analysis of this paper:

> *Code for composition. Policy for authority.*

Concretely:
- `ToolSpec → stub_generator.py` generates typed Python planning stubs from
  signed ToolSpec objects. Each stub returns a `ProposedCall` data object;
  it never touches a real API.
- `call_graph.py` extracts the full action DAG from a plan via pure AST
  analysis (never `eval`/`exec`).
- `governed_batch.py` submits each `ProposedCall` individually to REMORA
  governance (ACCEPT/VERIFY/ESCALATE/ABSTAIN), parallelises independent
  ACCEPT nodes, and preserves the full per-call audit envelope.

The PTC execution model from the paper (running model Python in a subprocess
against echo-return stubs) is explicitly *not* adopted: those stubs call no
real APIs and are measuring argument serialisation only. In REMORA, the
sandbox has no network, credentials, or arbitrary filesystem access; Python
is computation; REMORA owns authority.

The enumeration-accuracy finding motivates new GPTC metrics:
`plan_call_recall`, `executed_call_recall`, `unauthorized_call_rate`,
`grant_binding_failure_rate`, and `postcondition_match_rate` — planned as
part of the RF-11 ablation benchmark.

**What is not adopted.**

- Direct Python → production API (bypasses REMORA's security model).
- Authors' subprocess execution environment (no REMORA governance gate).
- Any PTC result number as a REMORA claim (not yet run; no artifact exists).

Boundary:

- RF-11 is SCOPED; no performance claim is made. The ablation (JSON vs PTC
  with the same REMORA gate in front of both) is the required next step
  before any number enters `README.md`.

## 5. Evidence Grounding and Retrieval-Augmented Verification

Relevant ideas:

- RAG for evidence lookup,
- source reliability,
- per-claim support/contradiction analysis,
- semantic entailment and NLI-style verification.

How REMORA uses this:

- `remora/oracles/evidence_v3.py`
- `remora/oracles/evidence_verifier.py`
- lexical default verifier with pluggable verifier interface.

Boundary:

- The default evidence verifier is lexical plus simple contradiction signals.
- Semantic entailment quality is not demonstrated by committed artifacts.

## 6. Statistical Physics and Control Signals

Relevant ideas:

- entropy,
- order parameters,
- susceptibility,
- Lyapunov-style stability,
- phase-like regimes.

How REMORA uses this:

- phase classification into ordered, critical, and disordered regimes,
- consensus temperature,
- selective trust curves,
- abstain/verify/accept routing.

Boundary:

- The physics language is used as an operational analogy and feature family.
- Some theoretical claims remain not demonstrated or explicitly negative in the
  claim ledger.

## 7. Nested Learning, Context Flow, and Continuum Memory

Primary sources:

- Behrouz, Razaviyayn, Zhong, and Mirrokni, "Nested Learning: The Illusion of
  Deep Learning Architecture", PDF: https://abehrouz.github.io/files/NL.pdf.
- Google Research, "Introducing Nested Learning: A new ML paradigm for
  continual learning", November 7, 2025.

Relevant ideas:

- ML systems can be viewed as nested or parallel learning problems,
- each level has its own context flow,
- components update at different frequencies,
- continuum memory generalizes the short-term/long-term memory split,
- self-modifying learning must be governed carefully.

How REMORA uses this:

- `remora/governance/context_flow.py`
- `remora/governance/memory_layers.py`
- `remora/governance/nested_governance.py`
- `remora/governance/governance_forgetting.py`
- `remora/governance/policy_proposals.py`
- `enterprise/nested_governance_layers.yaml`

REMORA translation:

- context flow becomes a governed information stream,
- update frequency becomes a policy boundary,
- continuum memory becomes controlled agent memory layers,
- catastrophic forgetting becomes governance forgetting,
- self-modification becomes reviewed policy proposals.

Boundary:

- REMORA does not implement the Hope architecture.
- REMORA does not train foundation models.
- REMORA does not claim to solve catastrophic forgetting.
- The current contribution is a deterministic governance architecture for
  long-running agents.

## 8. Enterprise AI Governance and Audit

Relevant ideas:

- policy-as-code,
- role and authority boundaries,
- human approval workflows,
- audit ledgers,
- fail-closed deployment,
- continuous evaluation.

How REMORA uses this:

- policy-as-code: `remora/policy/opa_adapter.py` (OPA/Rego delegation with
  monotone hard-guard floor),
- role and authority boundaries: RBAC in `servers/api.py`,
- human approval workflows: `remora/governance/review_queue.py`,
- audit ledgers: `remora/governance/audit_chain.py`,
- rollout reference: `docs/../enterprise/togaf-enterprise-rollout-plan.md`,
  runnable example `examples/enterprise_demo.py`.

The wiring status of each is tracked machine-readably in
[`assurance/capability_register_v1.yaml`](assurance/capability_register_v1.yaml).

Boundary:

- REMORA is not yet a production-certified enterprise product.
- The repository provides a research-grade prototype and architecture pack that
  must be validated in the target organization before enforcement.

## 9. Causal Post-hoc Explainability and Concept Interventions

Primary source:

- Bjøru, A. R. (2026). *Causal Post-hoc Explainable AI* (PhD thesis), NTNU.
  Paper IV: externally-causal, concept-based XAI; Probability of Sufficiency
  and Necessity; contrastive explanation search. Builds on Pearl (2009,
  *Causality*, ch. 9) and Galhotra, Pradhan & Salimi (SIGMOD 2021).

Relevant ideas:

- externally-causal, concept-based explanation over high-level operational
  concepts rather than raw model features,
- Probability of Sufficiency (PS) and Probability of Necessity (PN) as
  per-concept attribution,
- minimal contrastive explanations: the smallest intervention set that flips
  the outcome,
- global explanation by averaging per-instance scores across a dataset.

How REMORA uses this:

- `remora/causal/schema.py` — `CausalDecisionModel` over operational concepts,
  bounded to `decision_scope="policy_only"` (Bjøru §3),
- `remora/causal/search.py` — per-concept PS/PN scoring and the minimal
  contrastive concept-intervention search (Paper IV §4.2.2–§4.2.4),
- `remora/causal/attribution.py` — global concept attribution over a log of
  policy decisions (Paper IV §4.2.1, §4.2.3),
- `remora/causal/explanation.py` — the `CausalExplanation` carried on
  `DecisionEnvelope.causal_explanation`,
- tests: `tests/test_causal.py`, `tests/test_causal_search_attribution.py`
  (PS/PN ∈ {0, 1}, minimality, verdict-change, global mean-PS ordering),
- narrative: [`causal_policy_explanations.md`](evidence/causal_policy_explanations.md).

Boundary:

- REMORA explains **policy causality only**: why its own policy decided as it
  did, and which operational conditions would change that decision.
- It makes no claim about real-world cause and effect and no safety guarantee.
- The counterfactuals are evaluated against the policy model, not the world.

## 10. Spec-Driven Agentic Development and Context Intake

Primary source:

- Nguyen, V. H., & Nguyen, T. (2026). *SDAD: Spec-Driven Agentic Development
  for the AI-Native SDLC*. arXiv:2608.20341v1. Sections 6.1 (context ingestion
  as execution), 7.2 (the four Spec Fidelity dimensions), and 13.4 (the missing
  operational definitions).

Relevant ideas:

- the context consumed during synthesis is part of the execution basis and
  must be reproducible rather than treated as invisible prompt state;
- specification intake should preserve four separate questions:
  completeness, consistency, unambiguity, and verifiability;
- requirements should trace to objective acceptance and verification evidence.

How REMORA uses this:

- `remora/governance/spec_intake.py` creates a signed, content-addressed
  `ContextManifest` over immutable source revisions, exact source-byte hashes,
  model route, prompt template, tool manifest, and the intent/ToolSpec/policy
  authorities present at intake;
- the same module emits a signed, content-addressed `SpecFidelityReceipt` with
  one evidenced verdict per dimension. Its evaluator identity is bound to the
  receipt signature, not accepted as a typed name. It deliberately has no
  scalar score: three easy passes cannot compensate for one failed
  load-bearing dimension;
- positive and negative findings have the same provenance requirement. A
  claimed contradiction or ambiguity without evidence references is refused;
- `schemas/spec_intake_v1.yaml` freezes the artifact contract, and
  `artifacts/spec_intake/sdad_spec_fidelity_v1.json` is a reproducible
  reference fixture, not deployment evidence.

Boundary:

- SDAD presents a conceptual process framework and explicitly leaves Spec
  Fidelity operational definitions and longitudinal baselines open. REMORA's
  checks are a structural operationalisation, not validation of an empirical
  SDAD score.
- The receipt proves neither source truth nor semantic correctness. It records
  which structural checks ran, what evidence they referenced, and which exact
  context they measured.
- This is an implemented library surface, not yet an execution-API gate. Binding
  the manifest to final callable identity and dispatch authority remains open
  under RMR-004.
- REMORA does not adopt Agentic Autonomy Rate as an assurance metric; source
  lines-of-code do not establish correctness, authority, or verified effect.

## Positioning Statement

REMORA is a nested governance control plane for long-running agentic AI:
multi-oracle consensus, calibrated abstention, evidence verification,
tool-call gating, memory governance, drift monitoring, and audit routing in one
reproducible research prototype.

## Open Research Gaps

- independent external benchmark validation,
- live LLM tool-call studies with cached replay,
- semantic evidence verification benchmark,
- deployment telemetry for drift thresholds,
- statistical confidence intervals for governance-forgetting metrics,
- independent reproduction of enterprise integration patterns.

→ [11-benchmark-validation-plan.md](11-benchmark-validation-plan.md) for the
structured validation roadmap.
