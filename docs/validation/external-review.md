# REMORA: External Review

REMORA's claims are backed by committed artifacts and the math is written out in
full. What it needs now is independent scrutiny. This page is the front door for
reviewers. If you can break a claim, reproduce a different number, or show a
caveat is understated, that is the most valuable contribution you can make.

Negative findings are first-class here. See `NEGATIVE_RESULTS.md`.

**Review the architecture and the claim–artifact binding — not "certify 0% unsafe".**
The headline safety numbers are simulator-scoped and intent-gated; the repo says
so itself. The questions worth your time: are the hard guards actually first, is
every claim bound to a committed artifact, and are the caveats understated?

---

## Reviewer entry: 3 files, 3 artifacts, 3 commands

| Read (in order) | Why |
|---|---|
| [`README.md`](../../README.md) | The claims, with their caveats inline |
| [`docs/02-evidence-and-claims.md`](../02-evidence-and-claims.md) → [`NEGATIVE_RESULTS.md`](../../NEGATIVE_RESULTS.md) | Every claim → artifact; every failure, first-class |
| [`remora/policy/decision_engine.py`](../../remora/policy/decision_engine.py) | The deterministic layer the 0% FAR is attributed to |

| Check the artifact | Backs |
|---|---|
| `results/external_benchmark_agentharm_v1.json` | FAR 0.0% on AgentHarm, N=208 (intent-gating; FBR 100%) |
| `results/toolcall_benchmark_v2_results.json` | 0/70 unsafe templates (simulator; Δ vs baselines n.s.) |
| `results/sap_v3_round_results.json` | Calibrated confidence 87.8% vs majority 85.1% (pre-registered) |

```bash
python -m pip install -e ".[dev]"
python -m remora try          # send a tool call, watch it decide (no API keys)
python -m pytest tests/ -q    # ~3.7k deterministic tests, <1 min
```

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
1. Read the README top section and `docs/02-evidence-and-claims.md`.
2. Skim `NEGATIVE_RESULTS.md`. A project that hides failures is the one to doubt.
3. Send it a tool call yourself: `python -m remora try` (or the eight-scenario
   walkthrough `python -m remora demo`; live control-room:
   `remora.razorsharp.workers.dev/control-room`).
4. Open an issue with one thing you would attack first.

### 2-hour technical review (does it hold up?)
1. `python -m pip install -e ".[dev]"`
2. `make audit` (lint + tests + claim-consistency gate) — or, with no `make`:
   `python -m pytest tests/ -q` plus the `scripts/check_*.py` gates.
3. Pick one headline claim from `docs/02-evidence-and-claims.md` and reproduce it
   from the listed command. Compare to the committed artifact.
4. Read the relevant source (e.g. `remora/policy/decision_engine.py` for the hard
   blocks, `remora/selective/` for the conformal/guardrail logic).
5. File findings as issues. Tag what is wrong, understated, or unclear.

### Research replication path (is the result real?)
1. Read `paper/remora_paper.pdf` and `paper/remora_mathematical_supplement.md`.
2. Regenerate the deterministic benchmarks (no API keys needed) per
   `docs/06-reproducibility.md` and `docs/validation/review_checklist.md`.
3. For live-oracle results, set `GROQ_API_KEY` and re-run; note that oracle model
   versions drift.
4. Report any divergence between the artifact and your run.

## Piloting instead of reviewing?

If you are evaluating REMORA as a shadow-mode pilot platform rather than
reviewing the research: the pre-registered pilot framework — preconditions,
measurement criteria, go/no-go thresholds and stop conditions — is
[pilot_evaluation_protocol_v1.md](pilot_evaluation_protocol_v1.md).

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
