# REMORA Speaking Guide

**Purpose:** A practical speaking guide for explaining REMORA accurately to non-technical audiences, technical leaders, researchers, customers, and interviewers.

**Status:** Training material. It does not create new product claims. When a number is used, the caveat is part of the sentence.

**Primary sources:** `ARCHITECTURE.md`, `docs/02-evidence-and-claims.md`, `docs/claim_hygiene.md`, `NEGATIVE_RESULTS.md`, `docs/assurance/release_gates.md`, and `paper/remora_paper.md`.

---

## 1. The rule that keeps every explanation honest

Use this order whenever you explain REMORA:

1. **Problem:** What can go wrong when an AI agent is allowed to act?
2. **Mechanism:** Which layer handles that problem?
3. **Evidence:** What has actually been tested, measured, or proven?
4. **Boundary:** What does that result not prove?

The one sentence to learn first:

> I separate mechanism, empirical result, and guarantee. Code existing in a repository is not the same as validation, and a good benchmark result is not a general deployment guarantee.

This is the most important habit in the project. It prevents both overclaiming and unnecessary technical jargon.

---

## 2. REMORA in one sentence

### Norwegian

> REMORA is a pre-execution governance layer for AI agents. Before an agent performs a consequential action, REMORA decides whether it may proceed autonomously, needs validation, must abstain, or requires a human.

### English

> REMORA is a pre-execution governance layer for AI agents. Before an agent performs a consequential action, REMORA decides whether it may proceed autonomously, needs validation, must abstain, or requires a human.

### Do not say

- "REMORA decides what is true."
- "REMORA guarantees the action is correct."
- "REMORA makes AI safe."

### Say instead

> REMORA governs execution permission. An ACCEPT means the specified assurance conditions for unattended execution have been met. It does not mean the action is universally correct or risk-free.

---

## 3. The decision vocabulary you must know

| Verdict | Plain language | What happens |
|---|---|---|
| **ACCEPT** | The documented conditions for unattended execution are met. | The action may proceed. |
| **VERIFY** | The action may be reasonable, but more validation is required. | It is held pending validation. |
| **ABSTAIN** | The system lacks enough reliable basis to decide. | Autonomous execution is blocked. |
| **ESCALATE** | The risk or policy violation requires a person. | Autonomous execution is blocked and routed to human review. |

The key explanation:

> REMORA does not reduce all uncertainty to yes or no. It has an explicit middle ground. When evidence is incomplete, it can hold the action rather than guessing.

---

## 4. The core mental model

```text
Agent proposes an action
        |
        v
1. Hard policy checks
        |
        +---- policy breach -> ESCALATE / ABSTAIN
        |
        v
2. Multi-oracle uncertainty assessment
        |
        v
3. Evidence support or contradiction checks
        |
        v
4. Selective routing based on trust, phase, and calibration
        |
        v
ACCEPT / VERIFY / ABSTAIN / ESCALATE
        |
        v
5. DecisionEnvelope and tamper-evident audit chain
```

The most important architectural rule:

> Stage 1 runs first. A confident model majority cannot override a deterministic hard block.

---

# Part I: Speak at different levels

## 5. Fifteen-second explanation

### Norwegian

> REMORA is a safety and governance gate in front of AI agents. Before an agent changes something in the real world, like infrastructure, building controls, payments, or external APIs, REMORA checks policy, uncertainty, and evidence. If the basis is weak, it blocks, pauses, or sends the decision to a human.

### English

> REMORA is a safety and governance gate in front of AI agents. Before an agent changes something in the real world, such as infrastructure, building controls, payments, or external APIs, REMORA checks policy, uncertainty, and evidence. If the basis is weak, it blocks, pauses, or sends the decision to a human.

## 6. Thirty-second explanation for a recruiter or non-technical leader

### Norwegian

> Jeg bygger REMORA fordi AI-agenter snart ikke bare vil svare på spørsmål. De vil foreslå og utføre handlinger. Problemet er at en språkmodell kan høres trygg ut uten at den har godt nok grunnlag. REMORA ligger mellom agenten og handlingen. Først bruker den faste sikkerhetsregler som ikke kan overstyres. Deretter bruker den usikkerhet, evidens og kontrollert routing for å avgjøre om handlingen kan gå videre, må verifiseres, må stoppes, eller må til et menneske. Målet er ikke at AI skal virke mer selvsikker. Målet er at den skal få mindre autonomi når grunnlaget er svakt.

## 7. Sixty-second explanation for a CTO or security leader

### Norwegian

> REMORA er et pre-execution governance overlay for agentiske AI-handlinger. Den tar inn en foreslått tool call med kontekst, risiko og målmiljø, og returnerer ACCEPT, VERIFY, ABSTAIN eller ESCALATE. Den første og viktigste delen er en deterministisk policy-motor. Den blokkerer blant annet forbudte verktøy, malformed calls, coercion, tainted arguments og risikable produksjonshandlinger før modeller får påvirke utfallet. Etter policy-laget brukes flere orakler, uenighetssignaler, evidenssjekk og selective routing for å skille mellom ting som kan kjøre, ting som trenger mer verifikasjon, og ting systemet ikke bør avgjøre selv. Alle beslutninger pakkes i en DecisionEnvelope og logges i en hash-kjede. Det gjør beslutningen sporbar og manipulasjon synlig, men ikke automatisk umulig uten ekstern append-only lagring.

## 8. Two-minute explanation for an engineering interview

### Norwegian

> REMORA er et forsøk på å gjøre agentisk AI styrbar før den handler. Jeg kommer fra drift, nettverk og OT, så utgangspunktet mitt er at en AI-anbefaling ikke er nok når den kan endre en VLAN-policy, et SD-anlegg, en HVAC-setpoint, en betalingsflyt eller en produksjonskonfigurasjon. Du trenger en kontrollflate mellom agentens intensjon og selve utførelsen.
>
> Arkitekturen starter med et deterministisk policy-lag. Det er sikkerhetsgulvet. Dersom input er adversarial, verktøykallet er ugyldig, et verktøy er forbudt, argumenter er tainted, eller handlingen er for risikabel i produksjon, kan ikke senere sannsynlighetsmodeller overstyre det. Dette er viktig fordi vi har sett i benchmarkene at usikkerhetssignaler alene ikke ga sikkerhet. Den fullstendige policy-gaten ga 0 prosent unsafe execution på en 700-task deterministisk simulator, men det er hard-block-reglene som forklarer reduksjonen. Derfor sier jeg ikke at consensus eller entropy har skapt sikkerhetsresultatet.
>
> Etter policy-laget brukes multi-oracle consensus, entropy, dissensus, evidence verification og conformal selective routing for å gjøre noe annet: å styre usikre saker mot VERIFY eller ABSTAIN. På toppen logges hver beslutning som en DecisionEnvelope i en hash-kjede. REMORA er fortsatt research-grade og shadow-only i de mest krevende delene. Derfor er jeg nøye på å skille simulatorresultat, intent-gating, replay-evaluering og en faktisk produksjonsgaranti.

## 9. Five-minute explanation for a technical audience

Use this structure. Do not memorize every sentence. Memorize the order.

### 1. Why the problem matters

> The important transition is from text generation to action execution. A hallucinated answer is inconvenient. A hallucinated action can change a production system, expose data, send money, or alter physical operations.

### 2. What REMORA is and is not

> REMORA does not replace the agent and it does not function as a general truth engine. It evaluates a proposed action before execution and decides whether autonomous execution is permitted.

### 3. The deterministic safety floor

> The policy engine is ordered and fail-conservative. Hard-block invariants execute before probabilistic routing. This creates a simple and inspectable rule: if a policy violation is observed, model confidence cannot reverse it.

### 4. The uncertainty and routing layer

> Multi-oracle agreement is not treated as proof. It is treated as a signal. Entropy, dissensus, phase, evidence status, and calibrated trust determine whether a non-blocked action is suitable for ACCEPT, needs VERIFY, or should be ABSTAIN.

### 5. Evidence and auditability

> The evidence layer checks support and contradiction where sources are available. The result is wrapped in a DecisionEnvelope with decision reasons, policy version, risk state, and audit fields. The hash chain is tamper-evident. It becomes tamper-resistant in practice only when backed by external append-only storage and operational controls.

### 6. What evidence exists

> The full policy gate produced 0 percent unsafe execution on a 700-task deterministic adversarial simulator, with Wilson 95 percent interval [0.00%, 0.55%]. The policy layer causes that result. A held-out selective result showed 88 percent accuracy at 23.2 percent coverage, but only 25 actions were accepted, so the interval is wide [70.0%, 95.8%]. The critical phase produced a negative result, where trust was inverted on a small N=32 subset. REMORA routes around that instead of hiding it.

### 7. The honest close

> The project is strongest as an assurance-oriented research architecture. The remaining work is independent review, stronger external validation, genuine tool-call interception in external harnesses, and operational deployment evidence.

---

# Part II: Explain the architecture without getting lost

## 10. Stage 1: Hard policy invariants

### Simple explanation

> These are the non-negotiable rules. If an action breaks one, the system does not ask a model to vote on whether that is acceptable.

### Technical explanation

> `RemoraDecisionEngine` normalizes context and evaluates a priority-ordered ladder. Examples include adversarial input, malformed calls, forbidden tools, coercion, blackmail patterns, failed counterfactual checks, contradictory evidence, tainted arguments, and environment-sensitive production writes. The engine returns a structured decision report and an explanation trace.

### Why it matters

> It moves the strongest safety claim away from opaque model judgment and into deterministic, inspectable code.

### Boundary

> A policy proof is conditional on the observation. If upstream detection misses a dangerous condition, the policy engine cannot block on a signal it never receives.

### Good phrase

> The system is not claiming that policy detects every threat. It claims that when a hard invariant is present in the observation, the policy ladder will not autonomously ACCEPT the action.

## 11. Stage 2: Multi-oracle consensus

### Simple explanation

> REMORA asks more than one model or oracle, then treats agreement and disagreement as information about uncertainty.

### Technical explanation

> The consensus layer collects multiple oracle responses and derives trust, entropy, dissensus, and phase. Correlation-aware weighting is intended to reduce artificial confidence from echo-chamber agreement.

### Boundary

> Three related models are not equivalent to three independent experts. Shared model family, training data, prompt structure, or tool environment can create correlated errors.

### Good phrase

> Consensus is a routing signal, not a truth guarantee.

## 12. Entropy, dissensus, and phase

### Simple explanation

> When responses are aligned, the situation may be more orderly. When they spread out or conflict, the system becomes more conservative.

### Technical explanation

> Entropy summarizes response dispersion. Dissensus represents conflict or disagreement. REMORA derives an operational phase such as ordered, critical, or disordered and uses that phase in selective routing.

### Boundary

> The thermodynamic language is an uncertainty-routing metaphor. It is not a claim that the system obeys physical thermodynamics or discovers physical energy laws.

### Good phrase

> The phase labels are a compact operational language for disagreement structure, not physics.

## 13. Evidence verification

### Simple explanation

> Models should not only state that something is supported. REMORA tries to check whether available evidence actually supports or contradicts the proposed action or claim.

### Technical explanation

> The current evidence relation detection is lexical and heuristic, based on overlap and negation patterns, with a future semantic/NLI upgrade possible.

### Boundary

> Current lexical evidence checking is not equivalent to human-level fact verification or a fully validated natural-language inference system.

## 14. Selective prediction and conformal routing

### Simple explanation

> The system is allowed to say: “I do not have enough basis to approve this.” That is selective prediction.

### Technical explanation

> Conformal and phase-aware thresholds are used to control when the system accepts, verifies, or abstains. The current coverage claims are phase-scoped. Ordered-phase results must not be generalized to critical or disordered situations.

### Boundary

> Conformal methods provide guarantees only under their stated assumptions. They do not prove every accepted action is correct, and they can degrade under distribution shift.

### Good phrase

> Coverage is a statistical property over a defined stream of cases, not a promise that each individual decision is right.

## 15. Credal envelope and worst-case risk

### Simple explanation

> REMORA does not always reduce uncertainty to one number. It uses a plausible risk interval and asks what the worst credible outcome could be.

### Technical explanation

> The current `CredalEnvelope` builds an interval around a harm estimate using trust, entropy, dissensus, phase, action irreversibility, and risk-tier severity. A minimax-style worst-case loss gate can escalate when the upper risk bound crosses a threshold.

### Boundary

> The interval is currently a calibrated heuristic. It is not yet a formally constructed credal set with a statistical coverage guarantee, and it is not a complete Gamma-maximin action-selection framework.

### Good phrase

> It is a conservative worst-case risk gate over a heuristic uncertainty envelope, not a finished theory of imprecise probability.

## 16. DecisionEnvelope and audit chain

### Simple explanation

> Each decision gets a receipt: what action was proposed, why the system decided as it did, and the decision state around it.

### Technical explanation

> Each `DecisionEnvelope` contains action, decision, reasons, policy version, and audit information. Hash chaining uses the previous hash and current envelope. Editing a prior record breaks the chain.

### Boundary

> Hash chains are tamper-evident. They are not tamper-proof by themselves. Tamper resistance needs external append-only storage, access controls, and operational key management.

---

# Part III: The evidence you may quote

## 17. Evidence card: simulator safety result

### Safe wording

> On a 700-task adversarial tool-call benchmark implemented as a deterministic simulator, the full policy gate had 0 percent observed unsafe execution. The Wilson 95 percent interval was [0.00%, 0.55%]. The hard-block policy rules accounted for the reduction. This does not prove field-deployment safety because the benchmark did not execute real shell, network, or database mutations.

### Do not say

- "REMORA has zero risk."
- "REMORA prevents unsafe actions in production."
- "The consensus layer achieved zero unsafe execution."

## 18. Evidence card: selective accuracy

### Safe wording

> On a held-out split, REMORA reported 88.0 percent selective accuracy at 23.2 percent coverage, with the threshold locked before the hold-out was used. Only 25 cases were accepted, so the Wilson interval is wide: [70.0%, 95.8%]. It is directional out-of-sample evidence, not a tight general accuracy estimate.

### What the result means

> When the system chose to act only on a limited subset, it was more accurate than the base rate on that subset.

### What it does not mean

> It does not mean REMORA is 88 percent accurate on all actions.

## 19. Evidence card: critical-phase trust inversion

### Safe wording

> In the small critical-phase subset, trust anti-correlated with correctness: lower-trust cases were more often correct than higher-trust cases. The sample was N=32, so this is a negative directional finding, not a universal law. The system responds by changing its routing logic rather than treating trust as universally valid.

### Why this is valuable

> A system that publishes where its signal fails is more credible than a system that reports only aggregate wins.

## 20. Evidence card: auditability

### Safe wording

> REMORA records decisions in a hash-chained audit trail. That makes later modification detectable. It does not independently prevent deletion or rewriting of records without external append-only storage.

## 21. Evidence card: AgentHarm

### Safe wording today

> The current AgentHarm harness should be described as intent-gating unless a verified PreToolUse interception path and required artifacts exist. It evaluates the proposed action surface, not every executed tool call.

### Do not say

- "REMORA has been fully validated on AgentHarm."
- "REMORA intercepts every AgentHarm tool call."
- "REMORA achieved zero unsafe execution in AgentHarm."

## 22. Evidence card: AROMER

### Safe wording

> AROMER is REMORA's experimental, shadow-only learning overlay. Its replay metrics are useful for internal monitoring, but its labels are partly self-labeled and it has not been externally validated. It is not production evidence.

---

# Part IV: Audience-specific explanations

## 23. For a customer in building automation or energy management

> Imagine an AI assistant that proposes changing ventilation schedules, lighting zones, setpoints, or energy loads. The question is not whether the AI can produce a plausible answer. The question is whether it should be allowed to make the change unattended. REMORA sits in front of that action. It checks fixed safety rules, whether the context and evidence are sufficient, whether the decision is uncertain, and whether a human must approve it. It also creates an audit record showing why the change was allowed, paused, or escalated.

## 24. For a CTO

> The product value is a control plane for agent actions. Instead of embedding scattered prompt rules inside every workflow, you expose a common decision contract: action plus context goes in, a typed decision report and signed governance envelope come out. Deterministic policy enforces non-negotiables; probabilistic signals govern autonomy level; audit artifacts make the decision reviewable.

## 25. For a security leader

> REMORA treats agent autonomy as an authorization problem under uncertainty. A model can propose an action, but it does not own execution permission. The policy layer can fail closed, require schema validation, reject forbidden tools, force review for risky environments, and bind a decision token to a specific observation. The key limitation is that the enforcement boundary must be placed where actual tools are dispatched.

## 26. For a researcher or professor

> The central contribution is not a claim that multi-oracle consensus makes agents safe. The central artifact is an assurance-oriented architecture that separates deterministic policy safety from probabilistic selective routing. The repo attempts to make every headline claim traceable to artifacts, reports a critical negative result, and scopes simulator results explicitly. The open questions are external replication, true interception, calibration under drift, and stronger formal verification of the deterministic layer.

## 27. For an employer or recruiter

> The project demonstrates how I work with complex systems. I start from operational risk, make the architecture explicit, build testable controls, document limitations, and avoid claiming that a model is reliable just because it can generate a convincing explanation. My practical background in infrastructure and OT is useful here because I think about what happens when software touches real systems, not only about model output quality.

## 28. Explaining your non-university background without apologizing

> I do not come from a traditional university research track. I come from real infrastructure, telecom, networks, building systems, and operational responsibility. That gave me a practical question first: what control is needed before an AI can change something real? I have then approached the research side seriously by making claims artifact-backed, documenting limitations, publishing negative findings, and inviting external review. I do not present that as a substitute for peer review. I present it as disciplined engineering that is ready for independent scrutiny.

Avoid saying:

> I am self-taught, so I may not know the theory.

Say:

> I have a non-traditional route into the field, so I compensate by being explicit about sources, assumptions, test artifacts, and external review requirements.

---

# Part V: Theory cards

## 29. Policy invariants

**Simple:** Rules that must never be bypassed.

**Technical:** Predicates over `PolicyObservation` that imply a non-ACCEPT decision.

**One-line formula:**

```text
InvariantViolation(observation) -> decision != ACCEPT
```

**Boundary:** Only as reliable as the input signals and the specified invariant set.

## 30. Bernoulli rate

**Simple:** A rate for something that either happened or did not happen.

**Technical:** For false accept events, each relevant trial is 1 if an unsafe action was accepted and 0 otherwise.

```text
FAR = false_accepts / harmful_opportunities
```

**Boundary:** Observing zero events does not prove the true rate is exactly zero.

## 31. Wilson confidence interval

**Simple:** A range that communicates uncertainty around an observed proportion.

**Technical:** A binomial proportion interval with better finite-sample behavior than the simple normal approximation near zero or one.

**Boundary:** It is usually fixed-sample inference. If a rate is monitored continuously and acted upon at a data-dependent time, use an anytime-valid method such as a confidence sequence.

## 32. Confidence sequence

**Simple:** A confidence interval you can inspect repeatedly over time without invalidating the statistical guarantee.

**Technical:** A time-uniform interval sequence designed so that the parameter remains covered across all monitoring times with controlled probability.

**Why REMORA needs it:** Useful for any continuously monitored safety rate such as false accepts, false blocks, or oracle failures.

## 33. Entropy and dissensus

**Simple:** Measures of how much the oracle responses spread apart or conflict.

**Technical:** Entropy summarizes dispersion across response clusters. Dissensus captures conflict structure. REMORA uses both as routing observables.

**Boundary:** Neither is truth itself.

## 34. Conformal prediction

**Simple:** A way to control how often a system should refrain from making high-confidence decisions under stated assumptions.

**Technical:** Calibration-based procedures that offer coverage or risk-control properties under exchangeability or other stated conditions.

**Boundary:** Drift and adversarial data can break naïve assumptions.

## 35. Credal envelope

**Simple:** A range of plausible risk values instead of one overly confident number.

**Technical:** Current REMORA code uses an interval around harm risk and a worst-case loss gate.

**Boundary:** The current interval is heuristic. It should not be described as a complete imprecise-probability model.

## 36. Lyapunov language

**Simple:** A way to reason about whether a system tends toward stability or instability over time.

**Technical:** REMORA uses Lyapunov-inspired tracking as an empirical operational signal.

**Boundary:** Existing use is not a formal global stability proof for the full agent system.

## 37. Barrier certificates and formal policy proof

**Simple:** A way to prove that certain unsafe states cannot be reached if the assumptions hold.

**Technical:** For current REMORA policy logic, the clearest near-term target is machine-checked non-reachability of ACCEPT under hard-invariant violations, rather than broad dynamic-control claims.

**Boundary:** A proof over policy observations is not a proof about all possible real-world states.

## 38. Neyman-Pearson framing

**Simple:** First set a strict safety-error budget, then minimize unnecessary friction.

**Technical:** Optimize benign friction subject to a bound on unsafe autonomous acceptance.

```text
minimize FBR subject to FAR <= alpha
```

**Boundary:** A system that blocks everything can achieve FAR=0. It is a safety floor, not proof of useful deployment behavior.

## 39. Oracle independence and Condorcet

**Simple:** A majority becomes more useful only when the voters make meaningfully different mistakes.

**Technical:** Condorcet-style gains depend heavily on competence above chance and sufficient independence. Correlated models can fail together.

**Boundary:** More model calls are not automatically more evidence.

---

# Part VI: Questions you will get

## 40. "Is this just a rule engine?"

> The deterministic safety floor is intentionally rule-based because some constraints should be inspectable and non-negotiable. REMORA is more than a rule engine because it also handles uncertainty, evidence, multi-oracle disagreement, selective abstention, and auditability. But I do not pretend that probabilistic layers should replace hard policy when the risk is operationally high.

## 41. "Why not just use a human in the loop for everything?"

> Human review is essential for high-risk or uncertain actions, but it does not scale to every low-risk action. REMORA is about deciding where autonomous execution is acceptable, where validation is required, and where a human must take over. It manages autonomy rather than eliminating humans.

## 42. "Why not trust the best model?"

> A single strong model can still be confidently wrong, can change behavior after an API update, and can share blind spots with its training distribution. REMORA treats model output as one input to governance, not as the final authority.

## 43. "Does consensus make the answer correct?"

> No. Consensus can reduce some types of uncertainty, but correlated systems can agree on the same mistake. In REMORA, consensus is used for routing quality, not as the primary safety guarantee.

## 44. "Does 0 percent unsafe execution mean it is safe?"

> No. It means zero unsafe executions were observed on a particular simulator benchmark. The 95 percent Wilson interval was [0.00%, 0.55%], and the result does not prove safety in real deployment. It is evidence about the benchmark and policy configuration, not a universal guarantee.

## 45. "Why is the false-block rate high in some external tests?"

> The conservative corner solution is easy: block everything and unsafe acceptance goes to zero. That is useful as a floor, but it is not a finished product objective. The next objective is to reduce benign friction while keeping unsafe acceptance below a hard bound.

## 46. "What is the biggest current limitation?"

> The main limitations are external replication, full live tool interception at the enforcement boundary, performance under distribution shift, and independent human review. The project documents these gaps rather than treating them as solved.

## 47. "What makes this research rather than just software?"

> Software becomes research-oriented when it is used to test explicit hypotheses, compare alternatives, report uncertainty, preserve artifacts, publish negative results, and state the boundary of the conclusion. REMORA is strongest where it does that. It still needs more independent validation to become established research.

## 48. "What do you personally bring to this?"

> I bring a systems and operational-risk perspective. I have worked with real infrastructure and control environments where wrong automation has a cost. That shaped the design principle: agents can propose actions, but they should not automatically own execution permission.

---

# Part VII: Red flags and repairs

## 49. Never use these phrases

| Do not say | Why it fails | Better phrase |
|---|---|---|
| "REMORA makes AI safe." | Absolute, unprovable. | "REMORA adds a governed decision layer before execution." |
| "Consensus guarantees correctness." | False under correlation and shared blind spots. | "Consensus is one uncertainty signal." |
| "The entropy proves the answer is wrong." | Entropy is not truth. | "High entropy is a reason to reduce autonomous confidence." |
| "The audit chain is immutable." | Only tamper-evident without external storage. | "The audit chain makes modification detectable." |
| "We validated AgentHarm." | Too broad without full interception artifacts. | "The current harness supports scoped intent-gating claims." |
| "AROMER is autonomous intelligence." | Easily overread. | "AROMER is an experimental shadow-mode learning overlay." |
| "We use thermodynamics in AI." | Sounds like metaphor inflation. | "We use thermodynamic-style observables as an uncertainty-routing metaphor." |
| "The credal layer is full imprecise probability theory." | Current implementation is heuristic. | "The credal layer uses a conservative interval-style risk heuristic." |

---

# Part VIII: Practical drill plan

## 50. Daily ten-minute practice

### Minute 1 to 2: One sentence

Say the one-sentence definition without looking.

### Minute 3 to 4: The four verdicts

Explain ACCEPT, VERIFY, ABSTAIN, and ESCALATE to a non-technical person.

### Minute 5 to 6: The safety floor

Explain why Stage 1 is separate from consensus.

### Minute 7 to 8: One evidence card

Choose one: simulator safety, held-out selective accuracy, critical-phase inversion, auditability, AgentHarm, or AROMER.

### Minute 9 to 10: One limitation

End every practice answer with one honest boundary.

## 51. Weekly thirty-minute practice

1. Record a two-minute explanation in Norwegian.
2. Record the same explanation in English.
3. Answer five hostile questions from Part VI without reading.
4. Review any answer where you overclaimed, used vague words, or lost the architecture order.
5. Rewrite only the one sentence that failed.

## 52. Test yourself with these prompts

- Explain REMORA to a property manager in 30 seconds.
- Explain why policy comes before consensus to a security architect.
- Explain the 0 percent simulator result without overselling it.
- Explain why a high false-block rate can be a deliberate early safety posture but not an end state.
- Explain what a confidence sequence would improve in REM-020.
- Explain why a hash chain is tamper-evident and not tamper-proof.
- Explain why a negative result can make a project stronger.
- Explain your non-university path without sounding defensive.

---

# Part IX: Interview close

## 53. A strong closing statement

### Norwegian

> Det jeg prøver å bygge med REMORA er ikke en modell som later som den vet alt. Jeg prøver å bygge et system som er tydelig på når autonomi er forsvarlig, når mer validering trengs, og når et menneske må overta. Det viktigste for meg er at påstandene kan spores til kode, tester og artefakter, og at systemet også dokumenterer når signalene feiler.

### English

> What I am building with REMORA is not a model that pretends to know everything. I am building a system that is explicit about when autonomy is justified, when more validation is needed, and when a human must take over. The important part is that claims can be traced to code, tests, and artifacts, and that the system also documents where its signals fail.

---

# Part X: Source map for deeper study

| Topic | First file to study | Then study |
|---|---|---|
| Core architecture | `ARCHITECTURE.md` | `docs/01-architecture.md` |
| What may be claimed | `docs/02-evidence-and-claims.md` | `docs/claim_hygiene.md` |
| Decision logic | `remora/policy/decision_engine.py` | `remora/policy/invariants.py` and tests |
| Auditability | `remora/governance/envelope.py` | `remora/audit/hash_chain.py` |
| Selective routing | `remora/selective/guardrail.py` | `conformal.py`, `crc.py` |
| Uncertainty metrics | `remora/semantic_entropy.py` | `remora/thermodynamics/` |
| Credal worst-case gate | `remora/credal.py` | decision engine integration |
| Negative results | `NEGATIVE_RESULTS.md` | `docs/04-negative-results-detail.md` |
| Release maturity | `docs/assurance/release_gates.md` | `remediation_register.yaml` |
| Theory roadmap | `docs/THEORETICAL_FOUNDATIONS_FEATURE_PROPOSALS.md` | acceptance artifacts when implemented |

---

## Final reminder

Your goal is not to sound like a paper.

Your goal is to make another person understand three things:

1. What REMORA controls.
2. Why the control exists.
3. Exactly how far the evidence currently goes.

When you can explain that simply first, then go technical only when asked, you will sound more credible than someone who leads with jargon.
