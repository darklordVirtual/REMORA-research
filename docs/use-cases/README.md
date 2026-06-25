# REMORA — Use Cases

> **For non-technical readers.** This section explains where REMORA adds real value,
> using plain language and visual examples from real sectors.

---

## The core idea in one sentence

> REMORA does not just ask an AI and hope for the best.
> It asks multiple AI systems, measures how much they agree,
> checks the answer against authoritative sources,
> and tells you **when the answer is trustworthy** — not just when it sounds confident.

---

## The problem REMORA solves

Every AI system can be confidently wrong.

When an AI says "I'm 94% confident" — that number comes from the model's internal statistics,
not from checking the answer against a real source. A model trained on 2021 data
will be highly confident about things that changed in 2022.

**Standard AI approach:**
```
Question → Single AI → Answer (with confidence number)
                ↑
         No way to verify
         No source cited
         No audit trail
```

**REMORA approach:**
```
Question → Multiple AI oracles → Measure agreement
        → Retrieve from authoritative sources
        → Check for contradictions
        → Only return answer when evidence is strong
        → Include audit trail + source citations
```

---

## Where REMORA adds the most value

![Overview of REMORA use cases across sectors](../../artifacts/use-cases/uc0_overview.png)

REMORA is most valuable when the **cost of a wrong answer is high**:

| Sector | The risk | How REMORA helps |
|--------|----------|-----------------|
| [Healthcare](01-healthcare.md) | Wrong treatment advice | Medical-specific oracles + clinical guideline retrieval |
| [Legal & Compliance](02-legal-compliance.md) | Regulatory misinterpretation → €20M fine | RAG retrieves current statute text + cites source |
| [Financial Services](03-financial.md) | Hallucinated data in due diligence | ETR score gates auto-approve vs human review |
| [Energy & Infrastructure](04-energy.md) | False fault alarms waste engineer visits | Role-oracle swarm diagnoses root cause |
| [Security Research](05-security.md) | 92% of AI alerts are false positives | REMORA FP screen reduces to ~3% false positives |
| [Public Administration — AI Hallucination](06-public-administration-hallucination.md) | Fabricated court decisions enter formal documents | DCE knowledge base lookup flags non-existent citations |
| [Norwegian Law via MCP](07-norwegian-law-mcp.md) | Legal research without authoritative statute access | MCP tools query DCE Norwegian law corpus + multi-oracle consensus |

---

## How to read the use case documents

Each use case document covers:

1. **The scenario** — a specific, realistic situation in that sector
2. **The problem without REMORA** — what goes wrong with a standard AI approach
3. **How REMORA handles it** — step by step, in plain language
4. **The measurable value** — real numbers from experiments or realistic estimates
5. **A visual diagram** — showing the difference clearly

Technical readers can find the underlying code and research in:
- [`paper/whitepaper.md`](../../paper/whitepaper.md) — full academic treatment
- [`remora/`](../../remora/) — the implementation
- [`results/`](../../results/) — all experimental data
- [`docs/mcp-integration.md`](../mcp-integration.md) — MCP server, all 8 tools, and extension model

---

## One thing to know

REMORA is honest about uncertainty.

When the answer is not clear enough — when oracles disagree, when confidence is low,
when no authoritative source was found — REMORA **abstains** rather than guessing.

In a 30-question adversarial test:
- Single AI model: **3 correct, 27 wrong** (10 % accuracy)
- REMORA RAG oracle: **7 correct, 0 wrong, 23 abstentions** (100 % precision)

*Source: `results/rag_adversarial_results.json`*

Abstaining is not a failure. It is the honest, safe answer.
