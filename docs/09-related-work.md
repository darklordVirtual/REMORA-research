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
  optional stopping (Howard et al. 2021; Ramdas et al. 2023), a distinct,
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
  `remora/toolcall/ptc/`: stub generator, AST call-graph extractor,
  governed batch executor.

Boundary:

- v1 is explicitly too easy for unsafe-execution differentiation.
- v2 provides deterministic adversarial evidence, not production proof.
- Live validation remains a separate research requirement.
- GPTC is a planning-layer prototype (RF-11, SCOPED); stubs return
  `ProposedCall` data objects only; no real API execution from the
  planning surface. Governance and dispatch are unchanged.

### 4a. Programmatic Tool Calling (PTC) — planning layer

Patel, Sen, Lumer & Subbiah (2026). *The Bitter Lesson of Tool Calling.*
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
  *enumeration accuracy* (correct tool calls actually invoked); models
  can produce correct answers without executing the required tools.

**What REMORA takes from this (RF-11).**

REMORA already owns the governance-and-execution boundary; PTC provides a
complementary composition surface *above* that boundary. The paper itself
makes no governance claim; the following principle is the REMORA authors'
synthesis, not a statement from the source:

> *Code for composition. Policy for authority.*

Concretely:
- `stub_generator.py` takes a `ToolSpec` and generates typed Python planning stubs from
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
`grant_binding_failure_rate`, and `postcondition_match_rate`, planned as
part of the RF-11 ablation benchmark.

**What is not adopted.**

- Direct Python calls into the production API (bypasses REMORA's security model).
- Authors' subprocess execution environment (no REMORA governance gate).
- Any PTC result number as a REMORA claim (not yet run; no artifact exists).

Boundary:

- RF-11 is SCOPED; no performance claim is made. The ablation (JSON vs PTC
  with the same REMORA gate in front of both) is the required next step
  before any number enters `README.md`.

### 4b. Path-dependent runtime governance (2026 comparators)

Three 2026 systems are close enough to REMORA's enforcement surface that
positioning must name them explicitly.

Kaptein, Khan & Podstavnychy (2026). *Runtime Governance for AI Agents:
Policies on Paths.* arXiv:2603.16586. Formalises governance decisions as a
function of agent identity, the partial execution path so far, the proposed
next action and organisational state.

Li, Chen, Wen, Zhang, Liu et al. (2026). *VIGIL: Runtime Enforcement of
Behavioral Specifications in AI Agent Skills.* arXiv:2606.26524. Enforces
behavioural specifications over finite execution traces, including temporal
dependencies and cross-call value flow. (Distinct from the tool-stream
injection paper of the same name tracked in `research_shelf_v1.yaml`.)

Microsoft (2026). *Agent Governance Toolkit.* Open-source runtime security
for agents (announced 2026-04-02): deterministic runtime enforcement, agent
identity, execution rings, policy engines, MCP governance and supply-chain
provenance.

**Positioning.** REMORA's authority binding is per call. The chain runs from
authority provenance through exact-call binding, grant consumption, execution
custody and effect state to evidence and claim governance. Policies on Paths and VIGIL govern *sequences*;
Microsoft AGT is broader in surface. REMORA does not claim trajectory-level
enforcement; the extension from single-call to path-level enforcement is an open direction
(see Open Research Gaps), not an implemented capability.

**Internal runtime-surface implementation (RES-013 / RF-13).** Per-call
binding does not establish that the serving agent process has no additional
callable tools. REMORA's opt-in local reference runtime now observes its own
served list and dispatcher, compares assessment/dispatch identities, checks a
finite authority graph, and records separately recheckable effect evidence.
`python scripts/evaluate_runtime_surface.py --check` reproduces the committed
artifact using a real temporary file write and separate readback. The matrix
binds each module, test and artifact. This is an internal research construct;
no external work in this section is claimed as implemented by it. Deployment
providers still supply authority scopes. No external-runtime completeness,
production containment or independent replication result is claimed.

Quality program Q3.2 to Q3.5 narrowed four of those limits on the same
reference runtime. The lease now carries the digest of the surface observed
at assessment, and the dispatcher compares it at dispatch. In a shadow
measurement the surface did not change in 200 legitimate runs, and every one
of 20 injected changes was caught. A tool's identity can cover its imported
modules and installed dependency versions, not only its own source text. The
credential scope checked against the signed spec can come from an issuer
REMORA queries, not from the tool provider. Surface and effect evidence can
be written to a durable chain and rechecked after a restart. All four are
properties of REMORA's own reference runtime. Measuring them inside an
external agent host is Q3.1, which waits on the choice of host.

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

- `remora/causal/schema.py`: `CausalDecisionModel` over operational concepts,
  bounded to `decision_scope="policy_only"` (Bjøru §3),
- `remora/causal/search.py`: per-concept PS/PN scoring and the minimal
  contrastive concept-intervention search (Paper IV §4.2.2–§4.2.4),
- `remora/causal/attribution.py`: global concept attribution over a log of
  policy decisions (Paper IV §4.2.1, §4.2.3),
- `remora/causal/explanation.py`: the `CausalExplanation` carried on
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

## 11. Task-Bound Execution Authority

REMORA binds an authorization to the exact call it was granted for: tool
name, full arguments, tenant and target, hashed canonically and recomputed
immediately before dispatch. Until RES-012 it did not bind that
authorization to the *task* the call was made under. An approval granted for
task A therefore authorised the identical call under task B. Every binding
REMORA checks still held. Nothing in the chain recorded that the approver
had been answering a different question.

Three independent lines arrived at this within two days of each other, and
the convergence rather than any single one is the argument.

**Yan (2026)** supplies the human evidence. Across 113 non-technical
participants, a reusable user-authored permission policy blocked *fewer*
overreach attempts than either real-time human approval or automated model
review. Users chose "ask" and then approved actions outside the original
task. The finding is uncomfortable for any system that treats a recorded
approval as authority: "the user approved" is measurably not the same as
"the task authorised". REMORA's response is not to distrust approvals but to
scope them, so an approval carries the task it was given under and cannot be
presented outside it.

**Wu et al. (2026)** describe the adjacent failure from the other end.
Trajectory-scoped safety monitors reset each iteration, so an adversary can
hold every individual run under threshold while risk accumulates across the
outer loop. Their LoopHarness keeps non-decaying safety state across that
loop. REMORA does not implement LoopHarness. What it takes from the paper is
structural. That state needs a key, and the key is the same context
identifier this line introduces. The two designs therefore share one module
rather than growing a second task identity beside the first.

**The AGNTCY Identity working group** reached it from the standards side.
Their August 2026 analysis states that Identity plus TBAC grants standing
authority today. Cryptographic binding to `taskId`, action and resource
scope, lifetime and delegation constraints remains open profile work. A
row-by-row crosswalk of that work against implemented REMORA returned `GAP`
on exactly two rows: A2A `taskId` and A2A `contextId`.

### What REMORA takes and what it does not

The binding is deliberately narrow. `context_id` and `task_id` are opaque
strings that REMORA compares and never parses. They fold into the structures
that are already signed. They are not a fifth signed artifact beside intent
authority, proposal, grant and lease: one more thing to verify, revoke and
keep fresh would have cost more than the property is worth.

The constraint that shaped the implementation is that `AuthorizationContext`
hashes into every policy decision token issued since RMR-001, and that hash
is recomputed at redemption. Adding a field naively would have rewritten it
for every context and stopped every existing token verifying. Absent task
fields are therefore omitted from the preimage rather than defaulted to the
empty string. The committed artifact
`artifacts/task_authority/authorization_context_preimage_v1.json` records the
pre-change preimages, so a replicator can check that guarantee without
trusting the test suite.

The same rule now covers the execution lease and the A2A envelope (quality
program Q7.2). Each carries the pair only when bound, so an unbound lease or
envelope signs the bytes it signed before, and
`tests/test_task_bound_lease_and_envelope.py` pins both pre-change key sets.
Checked against another task, either one refuses as `task_mismatch`; one that
was never bound refuses as `task_unbound`. The check runs when the executor
supplies the current task, and a dispatcher built with
`require_task_identity` refuses a call that supplies none. The execution API
takes `context_id` and `task_id` on every call and binds them into the token
and the lease, so a token redeemed under another task is refused before its
grant is spent. A deployment makes the fields mandatory with
`REMORA_REQUIRE_TASK_IDENTITY`; without it, a call that names no task behaves
as before.

`remora/governance/loop_safety.py` keeps the state Wu et al. show must not
decay. It is keyed on `(tenant_id, context_id)`, so a new task inside the
same context sees what earlier iterations accumulated: denials, authority
probes, a switch to another tool straight after a denial, and irreversible
effects. The store is append-only, and only a reset that names a policy
decision starts the count again. An unreadable store raises rather than
reporting an empty history. `POST /v1/execution/assess` reads it before
deciding and records every decision that names a task. A context at a limit
cannot ACCEPT, and only a reviewer's reset naming a policy decision clears
it. The limits are defaults that no study has calibrated.

This is binding, not proof-of-possession. It ties an authorization to a task
and does not prove the presenter holds a key. Nothing here should be read as
closing the AGNTCY profile's PoP requirement, and REMORA claims no PoP at
this revision.

## 12. From Authority to Effect

REMORA's earlier lines bind an authorization to the exact call, and
recompute that binding before dispatch. Quality program WS7 asks what
happens between a correct binding and a correct effect. Each item below
takes one rule from one source, implements it where REMORA already
enforces, and states what it does not take. RES-014 to RES-019 map the code,
tests and artifacts.

**When the gate itself is wrong (RES-019).** Zhang, Kweon and Han (2026)
report that enforcement is bounded by the correctness of its state and of
the matcher that maps requests to steps. REMORA measured its own version of
that in a pre-registered study with seven validator faults
(`NEGATIVE_RESULTS.md` §60). A lenient matcher turned the gate into the
source of unsafe accepts, and failing open converted unavailability into
accepts at roughly its own rate. Stale or incomplete state cost autonomy
instead of safety. No fault let a write through without review.

**Authentic is not complete (RES-014).** An audit chain that verifies says
nothing about whether it holds enough. The evidence export now reports, per
claim, whether the evidence is complete, authentic but incomplete,
inconclusive or tampered. An executed call with no effect observation is
authentic and incomplete for the claim "it happened as intended". No
external source is claimed for this; it builds on RES-013's recheckable
effect evidence.

**The effect the call resolves to (RES-015).** Iyer (2026) resolves a tool
reference against a closed, known set before acting on it. REMORA applies
that at both ends of the lease. The resolved implementation, resource and
effect kind are signed into it, and the executor resolves again. An alias
retargeted, a resource redirected or an implementation remapped after
approval refuses, and a reference the registry does not know is refused
rather than guessed. The committed fixtures
(`artifacts/resolved_effect/fixtures_v1.json`) reproduce all seven cases.

**The premises of a plan (RES-016).** Chen, Wang and Brinton (2026) validate
a plan against the state it depends on, not against all state. A REMORA
lease can now carry the revisions a plan read and name the reads the write
depends on. A moved dependency refuses as `stale_plan`, and a moved
irrelevant read does not. Validating against everything would refuse far
more correct work, and a control that refuses correct work is switched off.

**Evidence outside the agent's process (RES-017).** Qin, Schmotz, Prinzhorn
et al. (2026) report agents deleting their own traces without tripping
guardrails. Every REMORA chain was written by the process that acts. The
reference recorder runs as a separate process with append-only storage and
no delete operation. For the tools a deployment names, the dispatcher
records the intent there before anything is spent, and refuses when the
recorder is down. How separate the process really is depends on the
deployment's OS boundary, which REMORA does not configure.

**Procedure and completion (RES-018).** Singh, Kumar, Agarwal et al. (2026)
match procedural obligations against traces. Xiao and Nuzzo (2026)
supervise tool-call traces with temporal contracts, and Smyth,
Mantilla-Ramos, Tikeng Notsawo et al. (2026) measure agents claiming
completion they did not reach. REMORA takes a small finite-state part: four
obligation shapes, one monitor used both online and in replay, and
completion derived from the trace. A completion claim the trace does not
establish is flagged as an overclaim. General temporal logic, and matching
natural-language procedures, are not implemented.

Every item is strictly narrowing: it adds a refusal before an effect or a
verdict about evidence, and grants nothing. None of the sources' own
measurements is reproduced, and none is claimed.

## 13. Capability Minimization Before Reasoning

REMORA's earlier lines judge an action after an agent has proposed it. WS8,
adopted from an owner-supplied design, reduces what the agent can propose at
all: an agent is shown, and may call, only the tools its task needs. It is
opt-in: a deployment turns it on with a capability policy, and no deployment
is claimed to run one. RES-020 maps the code, tests and artifact. No external
result is claimed for the design itself.

The set an agent works under is derived from trusted state as an
intersection. The requested tools, the principal's tools, the task's, the
tenant's and the environment's are intersected with what the registry holds,
and anything not named is denied. Visibility is not authorization. The same
set is signed into the execution lease and checked again at dispatch, so a
client that ignores the projected tool list gains nothing. An allowed tool is
held to its argument scope, a nested call needs a delegation that is a subset
of its caller's, and a set can be revoked by epoch between issuance and
dispatch. Success is established only when the evidence shows the capability,
the authorization, the execution and a verified effect.

Debenedetti et al. (2025), *Defeating Prompt Injections by Design (CaMeL)*,
is the closest published work. It binds capabilities to data values and
separates a privileged planner from a quarantined model that reads untrusted
content. REMORA does neither. Its capabilities attach to tools, tasks and
arguments, and an argument can be required to equal a fact from trusted
state. That is coarser than CaMeL's data-flow tracking and needs no changes
to how the agent is built.

The pre-registered layer study (`NEGATIVE_RESULTS.md` §62 records its one
missed prediction) shows that each layer stops the class of proposal it was
built for, and that no layer blocks a legitimate one. Its corpus is
author-written. Whether exposing fewer tools changes what a model proposes
in the first place is a question about models, and it needs a live run.

## 14. Test Adequacy for Conformance Corpora

The evidence-sufficiency corpora (`conformance/evidence-sufficiency-v1*`)
are tests of a checker, and a test of a checker needs its own measure of
adequacy. Three external runs with hand-picked faults answered one question: does the
corpus catch these faults. RES-021 answers the other: which faults can it not
catch. The method is that of DeMillo, Lipton and Sayward (1978): seed small
faults into the checker and count the ones no case tells apart. Budd and
Angluin (1982) showed that deciding whether a surviving mutant is equivalent
is undecidable. REMORA therefore keeps a named list of survivors that may only
shrink, never a score, the discipline `docs/assurance/mutation_testing_v1.md`
adopted for the enforcement paths. Just et al. (2014) and Papadakis et al.
(2018) bound what a kill means: mutants stand in for real faults to a measured
degree, and much of that correlation is suite size. Andrews, Briand and
Labiche (2005) support the use REMORA makes of them, as a comparator between
two versions of the same corpus.

Authored cases carry one oracle each. For inputs nobody authored, the corpus
uses metamorphic relations (Chen, Cheung and Yiu, 1998; Segura et al., 2016;
Chen et al., 2018). A relation names a transformation of the input and the
part of the verdict that must not change under it. That answers the oracle
problem described by Barr et al. (2015) without naming the right verdict. The
relations are declared as data in `invariants.json` and executed by the
runner. The same relations are checked on generated inputs with Hypothesis
(Claessen and Hughes, 2000; MacIver et al., 2019), derandomised so a failure
is a counterexample.

What this line does not take. Coverage is not used as the adequacy measure
(Zhu, Hall and May, 1997; Inozemtseva and Holmes, 2014). Subsumption between
mutants (Kurtz et al., 2016) is not computed; the families in the v1.3 spec
are a hand classification. Nothing here is evidence that the checker is
correct, and a corpus written with a survivor list in view shows the repair,
not generalisation. The blind protocol in `docs/design/evidence-
sufficiency-v1.3.md` section 8 is what could show that.

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
