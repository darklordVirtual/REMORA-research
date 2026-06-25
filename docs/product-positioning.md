# REMORA Product Positioning

**Status:** strategy document (2026-06-11). Drives the README top section, the
GitHub description, the social preview, and all outreach copy.

---

## The one decision that matters

REMORA can be described eight different ways. Describing it eight ways is why
nobody remembers what it is. Pick one primary frame, one secondary, and say the
same thing everywhere.

## Positioning angle evaluation

| # | Angle | Clarity | Unique | Market pull | Star potential | Enterprise pull | Research cred | Inflation risk |
|---|---|---|---|---|---|---|---|---|
| 1 | AI governance gate for agentic systems | Med | Med | High | Med | High | High | Med |
| 2 | **Pre-execution tool-call firewall** | **High** | **High** | **High** | **High** | High | Med | Low |
| 3 | Human-in-the-loop decision router | Med | Low | Med | Low | Med | Med | Low |
| 4 | Audit layer for autonomous agents | High | Med | Med | Low | High | Med | Low |
| 5 | Policy engine for LLM actions | High | Low | Med | Med | High | Med | Med |
| 6 | Enterprise AI control plane | Low | Low | Med | Low | High | Low | **High** |
| 7 | Research platform for action governance | Med | Med | Low | Low | Low | **High** | Low |
| 8 | MCP/LangGraph/OpenAI tool-call governance layer | High | Med | **High** | **High** | Med | Med | Low |

**Read:** angle 2 ("pre-execution tool-call firewall") wins on clarity,
uniqueness, and star potential with the lowest inflation risk. Angle 8
(integration framing) is the developer on-ramp. Angle 6 ("control plane") is the
one to avoid early — it sounds like a funded startup REMORA is not, and invites
"where's your SOC 2?" before anyone has read the code.

## Selected positioning

- **Primary:** A pre-execution governance layer (firewall) for AI agent tool
  calls. It decides, before an action runs, whether to ACCEPT, VERIFY, ABSTAIN,
  or ESCALATE — and writes an auditable record of why.
- **Secondary:** A governance layer for tool-calling agents in MCP, LangGraph,
  and OpenAI tool-calling stacks (the integration on-ramp).
- **Research framing (kept, not led with):** a reference architecture and
  empirical baseline for action governance, with published negative results.

## The line to use everywhere

> **Guardrails watch what AI says. REMORA governs what AI does.**

This tagline is approved. It is accurate (output filtering vs. action
governance), differentiating (names the gap), and memorable. Use it as the repo
description, the social preview, and the first line of the launch post.

Backup variants (A/B test, don't dilute):
- "The firewall for AI agent actions. It decides before the action runs."
- "Before an AI agent acts, REMORA decides if it should."

## Copy blocks (copy-paste)

**GitHub repository description (≤350 chars, with topics):**
> Guardrails watch what AI says. REMORA governs what AI does. A pre-execution
> governance layer for AI agent tool calls: ACCEPT / VERIFY / ABSTAIN / ESCALATE,
> with policy, evidence, uncertainty, and an auditable DecisionEnvelope.
> Research-grade, open source.
>
> Topics: `ai-safety` `ai-agents` `llm` `agentic-ai` `ai-governance`
> `tool-calling` `mcp` `langchain` `guardrails` `policy-as-code` `human-in-the-loop`

**Social preview slogan (the og-card already shows the proof numbers):**
> Govern what AI agents *do* — before they do it.

**LinkedIn headline (author profile):**
> Building REMORA — open-source pre-execution governance for AI agents | AI safety, tool-call governance, auditable autonomy

**Hacker News / Reddit title:**
> Show HN: REMORA — a pre-execution governance layer for AI agent tool calls (0% unsafe on a 700-task benchmark, research-grade)

**Enterprise-buyer headline:**
> Prove which autonomous AI actions are allowed to run — on the record.

**Researcher headline:**
> A reference architecture for action governance in LLM agents, with published negative results and reproducible benchmarks.

**Developer headline:**
> Drop a gate in front of your agent's tool calls. Four outcomes, one audit record, MCP/LangGraph/OpenAI adapters.

## What to stop saying
- "Enterprise AI control plane" (until there is a hosted product).
- "Solves AI safety" / "guarantees safety" — never; it governs a decision.
- "Production-certified" — it is research-grade.
- Leading with "thermodynamic" anything to a cold audience. It is a real method;
  it is not a hook. Lead with the action-governance story, let the curious find
  the method.
