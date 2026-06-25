# REMORA — External Review

REMORA's claims are backed by committed artifacts and the math is written out in
full. What it needs now is independent scrutiny. This page is the front door for
reviewers. If you can break a claim, reproduce a different number, or show a
caveat is understated, that is the most valuable contribution you can make.

Negative findings are first-class here. See `NEGATIVE_RESULTS.md`.

---

## Who we are looking for
- AI safety and alignment researchers (selective prediction, calibration,
  uncertainty, agent safety).
- LLM agent framework maintainers (MCP, LangGraph, LangChain, OpenAI tool use,
  AutoGen, CrewAI).
- Security engineers (tool-call abuse, prompt injection, supply chain).
- Governance, risk, and compliance practitioners.
- Enterprise architects deploying agents.
- Open-source maintainers in adjacent spaces.

## Three review paths

### 30-minute review (is this credible?)
1. Read the README top section and `docs/evidence-and-claims.md`.
2. Skim `NEGATIVE_RESULTS.md`. A project that hides failures is the one to doubt.
3. Run the live demo: `remora.razorsharp.workers.dev/control-room`, or the local
   60-second demo: `python examples/demo_scenarios/run_demo_scenarios.py`.
4. Open an issue with one thing you would attack first.

### 2-hour technical review (does it hold up?)
1. `python -m pip install -e ".[dev]"`
2. `make audit` (lint + tests + claim-consistency gate).
3. Pick one headline claim from `docs/evidence-and-claims.md` and reproduce it
   from the listed command. Compare to the committed artifact.
4. Read the relevant source (e.g. `remora/policy/decision_engine.py` for the hard
   blocks, `remora/selective/` for the conformal/guardrail logic).
5. File findings as issues. Tag what is wrong, understated, or unclear.

### Research replication path (is the result real?)
1. Read `paper/remora_paper.pdf` and `paper/remora_mathematical_supplement.md`.
2. Regenerate the deterministic benchmarks (no API keys needed) per
   `docs/reproducibility.md` and `docs/review_checklist.md`.
3. For live-oracle results, set `GROQ_API_KEY` and re-run; note that oracle model
   versions drift.
4. Report any divergence between the artifact and your run.

## What we will do with your review
- Engage on the issue directly and publicly.
- Fix or document anything you surface; understated caveats get corrected.
- Credit reviewers (with permission) in the acknowledgements.

## How to start
- Open an issue using the **External review** template.
- Or contact the maintainer: support@luftfiber.no.
- For integration questions, use the **Integration request** template.

## What this is not
REMORA is a research-grade reference architecture, not a certified product, not a
guarantee of safety, and not a replacement for domain authority. It governs a
decision: whether a proposed action is allowed to run, on the record. Hold the
review to that scope, and push hard inside it.
