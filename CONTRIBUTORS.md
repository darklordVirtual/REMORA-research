# Contributors

## Author

**Stian** (darklordVirtual)
Contact: support@luftfiber.no

REMORA is the work of a single human author. The following describes the
nature of that contribution to make it auditable and defensible.

---

## What the Author Built

REMORA is a research-grade governance overlay for autonomous AI actions. The
author designed, assembled, and validated the system from the ground up. This
was not a matter of prompting an AI tool and accepting its output, it was a
directed research and engineering project in which the author:

**Originated the research problem.** The question, how do we decide whether
an autonomous agent action is safe to execute, and how do we maintain an
auditable record of that decision: was the author's starting point.

**Designed the governance architecture.** The five-stage cascade pipeline,
the thermodynamic phase model (mapping agent uncertainty to physical
phase-transition analogues), the AROMER closed-loop learning layer, the
DecisionEnvelope audit contract, and the shadow-mode replay engine are the
author's designs. The claim-hygiene protocol that governs what can and cannot
be stated in this paper is the author's protocol.

**Constructed the system from components.** The author selected, integrated,
and validated each component: the multi-oracle consensus engine, the
conformal risk control layer, the prover-verifier deliberation module, the
NLI-based semantic entropy scorer, the causal attribution layer (Bjøru 2026
Paper IV), the Cloudflare Workers deployment stack, the D1 episodic store,
the Thompson-bandit oracle selection, the MetaJudge LLM critic, and the
Bayesian world model. Integration decisions required understanding how the
components interact under failure conditions.

**Ran all experiments.** The author executed and monitored all benchmarks,
all ablation runs, all live AROMER adaptation cycles, and all holdout
evaluations. The AII trajectory (LEARNING → CAPABLE → TRAINED, with full
§9–§13 regression and recovery documentation) is a live operational record of
the author's deployment and monitoring work.

**Preserved all negative results.** The project's claim register includes
`not_supported` and `failed` entries alongside supported ones. The
NEGATIVE_RESULTS.md document preserves every regression, every gap (FA=22.2%
on aradhye holdout, NLI DLL block, T2 window-composition artifact), and every
honest caveat. Retaining these results was the author's explicit decision.

**Verified all claims.** Every number in the paper corresponds to a committed
artifact and an automated regression test. The author reviewed and approved
every claim before inclusion. Citations were verified against original sources.

---

## Role of AI-Assisted Development Tools

Generative AI tools (primarily Claude, Anthropic) were used as development
assistants throughout this project. See `docs/AI_USE.md` for the complete
disclosure.

In summary:

- AI tools drafted code, documentation, and prose.
- The author reviewed, corrected, tested, and approved all output before it
  entered the codebase.
- AI tools did not define the research question, the architecture, the
  experimental protocol, or the claims.
- No AI-generated output was treated as evidence. All evidence is in committed
  artifacts and passing tests.
- AI tools are not listed as authors and cannot be held accountable for
  errors in this work. That accountability rests entirely with the human author.

---

## Acknowledgement of Human Authorship in the Context of AI Safety Research

REMORA is an AI safety project. It governs AI agent actions. That its own
development involved AI assistance is not a contradiction, it is consistent
with the project's thesis: AI tools are useful and should be used, but they
require governance, human oversight, and evidence-backed claims.

The author applied to REMORA's own development the same epistemic standard the
system enforces for agent actions:

- Proposals (from AI or human) require verification before acceptance.
- Uncertainty is recorded, not suppressed.
- Negative results are first-class outputs, not failures to hide.
- Accountability rests with the human decision-maker, not the tool.
