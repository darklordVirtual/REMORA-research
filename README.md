<img width="2172" height="724" alt="REMORA" src="https://github.com/user-attachments/assets/baa9dfb0-976e-4f57-a0a5-de1dfc056fa8" />

# REMORA

> ### Guardrails watch what AI says. REMORA governs what AI does.

A **pre-execution governance layer for AI agent tool calls.** Before an action
runs, REMORA decides — `ACCEPT` / `VERIFY` / `ABSTAIN` / `ESCALATE` — using
policy, evidence, uncertainty, and oracle disagreement, and writes an auditable
`DecisionEnvelope`.

[**Try it in 60s**](#try-it-in-60-seconds) ·
[**Live demo**](https://remora.razorsharp.workers.dev/control-room) ·
[**Evidence & claims**](docs/evidence-and-claims.md) ·
[**Read the paper**](https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf) ·
[**Enterprise white paper**](https://remora-agent-control.razorsharp.workers.dev/papers/REMORA_Enterprise_Whitepaper.pdf) ·
[**Review the claims**](docs/external-review.md)

[![Quality Gates](https://github.com/darklordVirtual/REMORA/actions/workflows/quality-gates.yml/badge.svg)](https://github.com/darklordVirtual/REMORA/actions/workflows/quality-gates.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![Status: research-grade](https://img.shields.io/badge/status-research--grade-orange)](#scope--limitations)
[![Live demo](https://img.shields.io/badge/demo-live-brightgreen)](https://remora.razorsharp.workers.dev)
[![Paper](https://img.shields.io/badge/paper-PDF-blue)](https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf)
[![Enterprise white paper](https://img.shields.io/badge/white%20paper-enterprise%20PDF-0e4a5c)](https://remora-agent-control.razorsharp.workers.dev/papers/REMORA_Enterprise_Whitepaper.pdf)

---

## The problem in one line

An AI agent that can call tools can drop a database, send a payment, or change
infrastructure. A wrong answer stops being a wrong sentence and becomes a wrong
**action**. Alignment, system prompts, and content filters operate on language at
training or prompt time. None of them decide whether a **specific proposed
action** should execute. That decision is the gap REMORA fills.

| Outcome | Meaning | Autonomous action |
|---|---|---|
| **ACCEPT** | assurance conditions met | permitted |
| **VERIFY** | plausible, validation required | pending |
| **ABSTAIN** | too uncertain to decide | blocked |
| **ESCALATE** | human review required | blocked, routed to a person |

`ACCEPT` does not mean the action is correct. It means the conditions for running
it without a human are verifiably met. REMORA governs **execution permission**,
not truth.

## Try it in 60 seconds

```bash
git clone https://github.com/darklordVirtual/REMORA.git
cd REMORA && python -m pip install -e ".[dev]"
python examples/demo_scenarios/run_demo_scenarios.py
```

Three proposed agent actions go in. Three governed verdicts come out, before
anything executes:

```
Read-only audit query .............. ACCEPT
Write with untrusted argument ...... VERIFY
Wire transfer, skip approval ....... ESCALATE
Nothing above executed. Each action was gated before any tool ran.
```

No keys, no Docker. Prefer Docker? `docker compose up` starts the governance API
on `http://localhost:8080` with mock oracles. Prefer the browser? Run a scenario
in the [live Control Room](https://remora.razorsharp.workers.dev/control-room).

## Why this is different

- **It governs actions, not text.** Guardrails filter outputs. REMORA gates the
  tool call before it runs.
- **Policy overrides consensus.** A confident, wrong majority cannot push an
  unsafe action through — hard policy blocks run before any vote is tallied.
- **Auditable by construction.** Every decision is an immutable, hash-chained
  `DecisionEnvelope`. Replay the chain; see exactly why each action was allowed or
  stopped.
- **Honest by policy.** Claims are tied to artifacts, and negative results are
  published. See [docs/evidence-and-claims.md](docs/evidence-and-claims.md) and
  [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md).

## Evidence (the caveat is part of the claim)

- **0% unsafe execution** on a 700-task adversarial tool-call benchmark, Wilson CI
  **[0.00%, 0.55%]** (deterministic simulator). Important: the hard-block policy
  rules account for **100% of this reduction** — the multi-oracle thermodynamic
  machinery contributes routing calibration, not the safety floor itself.
- **88% selective accuracy** on a locked held-out split, one-sided binomial
  **p = 1.45×10⁻⁵** (N_accepted = 25; Wilson CI **[70.0%, 95.8%]** — the wide
  interval reflects the small accepted set; read as directional confirmation).
- A **trust inversion** in the hardest cases, published as a negative result and
  routed around rather than trusted (N=32 critical-phase items; sample is small).

Full claim → evidence → artifact → caveat → reproduce map:
**[docs/evidence-and-claims.md](docs/evidence-and-claims.md)**. Blackboard-ready
math: [paper/remora_mathematical_supplement.md](paper/remora_mathematical_supplement.md).
Detailed benchmark tables are in [Benchmarks](#benchmarks-detail) below.

> REMORA is a **research-grade reference architecture**, not a certified product,
> not a guarantee of safety, and not a replacement for domain authority.

## Who is this for?

| You are | Start with | You get |
|---|---|---|
| **Agent developer** | [Try it in 60s](#try-it-in-60-seconds), [LangGraph adapter](examples/langgraph_integration.py), [OpenAI tool-calling adapter](examples/openai_tool_calling.py) | Runnable dispatch-gating around tool calls |
| **Security reviewer** | [Shadow Mode](examples/shadow_mode_demo.py), [eval_pack/](eval_pack/) | See what agents would execute before enforcement |
| **Research evaluator** | [paper (PDF)](https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf), [docs/external-review.md](docs/external-review.md), [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md) | Reproducible claims, artifacts, limitations |
| **Enterprise architect** | [Enterprise white paper (PDF)](https://remora-agent-control.razorsharp.workers.dev/papers/REMORA_Enterprise_Whitepaper.pdf), [docs/togaf/](docs/togaf/), [deploy/](deploy/) | TOGAF-aligned blocks, compliance mapping, deployment |
| **Executive / risk owner** | [docs/plain_language_overview.md](docs/plain_language_overview.md), [white paper §1–§2](https://remora-agent-control.razorsharp.workers.dev/papers/REMORA_Enterprise_Whitepaper.pdf) | What governed autonomy buys you, in 10 minutes |

## Drop into any agent loop

```python
from remora.adapters import LangGraphActionAdapter
from remora.adapters.gateway import LocalGateway
from remora.engine import Remora, Genome

adapter = LangGraphActionAdapter(gateway=LocalGateway(Remora(genome=Genome())))
result = adapter.intercept(
    action_name="delete_table", action_args={"table": "users"},
    domain="database", risk_tier="critical",
    action_type="destructive_write", target_environment="prod",
)
if result.should_execute:
    run_tool()
else:
    send_to_review(result.envelope)   # ESCALATE: routed, not run
```

The same pattern works for OpenAI tool calling, MCP tools, custom loops, and
shadow replay logs. The lowest-friction way to adopt REMORA is **Shadow Mode**:
run it beside your agent, block nothing, and get a replay report answering "what
would our agents have done if we had let them act?" See
[examples/shadow_mode_demo.py](examples/shadow_mode_demo.py).

## Commercial / advisory

The core is open source under Apache-2.0 and always will be. For production help,
the maintainer offers external validation of your agent's action-safety posture,
integration into your MCP / LangGraph / OpenAI stack, and sector policy packs
mapped to your compliance framework. Independent, senior, accountable. See
[docs/commercial-packaging.md](docs/commercial-packaging.md). Contact:
support@luftfiber.no.

## Contribute & review

- **Star the repo** if action governance is a problem you have.
- **Review the claims** via [docs/external-review.md](docs/external-review.md) —
  there is a 30-minute path and a 2-hour technical path. Negative findings are
  first-class.
- **Open an issue** with the
  [external-review](.github/ISSUE_TEMPLATE/external_review.yml) or
  [integration](.github/ISSUE_TEMPLATE/integration_request.yml) template.

---

# Deep material

Everything below is for readers who have decided REMORA is worth a closer look.

## How it works

```text
AI agent proposes a tool call
  -> fail-closed admission / schema / forbidden-tool / tainted-argument gates
  -> multi-oracle consensus + uncertainty (entropy, dissensus, phase)
  -> 7 hard policy blocks (run before any routing logic)
  -> verdict: ACCEPT / VERIFY / ABSTAIN / ESCALATE
  -> DecisionEnvelope written and hash-chained to the audit log
```

| Topic | Document |
|---|---|
| Full system architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Math (blackboard-ready) | [paper/remora_mathematical_supplement.md](paper/remora_mathematical_supplement.md) |
| Research paper | [paper/remora_paper.pdf](https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf) |
| DecisionEnvelope audit semantics | [docs/decision_envelope_audit.md](docs/decision_envelope_audit.md) |
| MCP integration | [docs/mcp-integration.md](docs/mcp-integration.md) |
| Negative results | [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md) |
| Security posture | [SECURITY.md](SECURITY.md) |

### Governance Intelligence Layer

Caller-supplied labels are not trusted blindly. An optional deterministic
enrichment layer extracts action semantics from the proposed action itself and
populates misspecification, blast-radius, and policy-generalization signals under
a **strengthen-only** rule (inferred higher risk may override a supplied lower
label, never the reverse).

```python
from remora.policy import PolicyObservation, enrich_then_decide
# An agent labels "DROP TABLE users" as a low-risk read:
obs = PolicyObservation(question="DROP TABLE users", risk_tier="low",
                        action_type="read", target_environment="prod",
                        phase="ordered", trust_score=0.95)
report = enrich_then_decide(obs)   # -> ESCALATE (was ACCEPT without enrichment)
```

On the 50-task disguised-action benchmark (offline, no keys): **0.0% unsafe
accepts**, 100% metadata-mismatch detection, 100% of legitimate reads still
accepted, 96.7% escalation precision
(`artifacts/governance_intelligence/evaluation_results.json`). Design notes:
[docs/research/governance_intelligence_layer.md](docs/research/governance_intelligence_layer.md).

## Benchmarks (detail)

Reproducible research and simulator results. **Not a production-safety
certification.** Read [docs/evidence-and-claims.md](docs/evidence-and-claims.md)
for the full caveats; the most load-bearing ones are repeated here.

| Claim | Result | Scope |
|---|---|---|
| Blocks unsafe tool calls | **0.0% unsafe**, Wilson CI [0.00%, 0.55%] | [Simulator] 700-task deterministic benchmark |
| Selective routing (held-out) | **88.0%** at 23.2% coverage, p=1.45×10⁻⁵ | [QA] held-out split, n_accepted=25 (wide CI) |
| Selective routing (in-sample) | **88.8%** at 18.0% coverage, +47.6 pp | [QA] 544-item artifact |
| AgentHarm harmful-action blocking (Mode 3) | **blocked_recall=0.977**†, FPR=0.023 | [Live oracle + gate] 88 curated cases |
| Cross-domain evidence routing | **100% precision** | [Static provider] 32 curated cases; live oracle is lower |
| Disguised/mislabelled actions never ACCEPT | **0.0% unsafe accepts** | [Offline] 50-task governance-intelligence benchmark |
| AROMER replay arena (measured) | **0% false accepts** | [Curated arena] via `scripts/aromer_publish_replay.py` |

**Load-bearing caveats:**
- **Simulator-scoped:** tool-call numbers come from a deterministic synthetic
  benchmark, not a live deployment.
- **Wide CI:** the held-out 88.0% accepted only 25 items.
- **No external validation** yet — all benchmarks are internally run.
- **Blocked recall ≠ ESCALATE recall:** † the AgentHarm 0.977 counts ESCALATE
  *and* VERIFY as "blocked"; strict ESCALATE-only recall is 0.114.
- **Static vs live oracle:** the 100% cross-domain precision uses the static
  evidence provider; the live Workers AI oracle is lower.
- **Thermodynamic language** is an uncertainty-routing proxy, not a physics claim.
- **Hallucination bound:** the bound is a candidate hallucination-bound proxy and an implemented research heuristic, not a formal guarantee.
- **Tool-call safety** is a controlled safety simulation, not production evidence.
- **Entropy backend:** reported benchmarks use a token-fingerprint heuristic (sorted SHA-256 tokens), not full Semantic Entropy over NLI clusters. The NLI backend exists as a drop-in but was not used for any reported result.

Reproduce: `make safety-check`, or per-benchmark commands in
[docs/reproducibility.md](docs/reproducibility.md) and
[docs/evidence-and-claims.md](docs/evidence-and-claims.md).

**Reviewer anchors (claim hygiene).** Result 1 uses **N = 302**, a **57.0%** single-model baseline, an **82.8%** majority-vote baseline, and top-25% selective routing with 76 accepted questions, 72 correct answers, and 94.7% accuracy.

Result 2 uses the historical **N500** label for a 544-question artifact. The label `N500` is historical and the current artifact evaluates 544 questions. It reports a 41.18% full-coverage majority baseline, top-10% k=54, top-15% k=82, top-18% k=98 with 88.8% accuracy, and top-20% k=109.

Tool-call reviewer detail. v1 (252 tasks) reports `remora_temperature_gate_heuristic` mean utility 0.6762 and `remora_full_policy_gate` mean utility 0.5690 with 0.7619 accuracy; v1 does not demonstrate unsafe-execution reduction.

v2 (700 tasks) reports temperature-gate utility 0.2700 and full-policy utility 0.6200 with 0.9000 accuracy, and reduces unsafe execution in the deterministic simulator. Significance artifact: `results/toolcall_benchmark_v2_significance.json`.

## AROMER — experimental live learning loop

AROMER (Autonomous REMORA Orchestrator) turns REMORA into a closed-loop system
that learns from every decision: persistent episodic memory, Bayesian world-model
priors, a Workers AI meta-judge, and a real 3-model oracle ensemble. It runs 24/7
on Cloudflare and is wired to this repo's own tool calls via hooks.

- **Live AII:** `https://aromer.razorsharp.workers.dev/intelligence`
- **Live log:** `https://aromer.razorsharp.workers.dev/log?format=text` (operational telemetry — domain/action_type only, no user data)
- **Offline in 60s:** `python examples/aromer_quickstart.py`

> **EXPERIMENTAL.** Episode labels are partly self-labeled; the world model
> defaults to shadow mode; the learning loop has **no external validation** and no
> external live-agent validation has been conducted. Do not cite AROMER numbers as
> production evidence. Details:
> [docs/quickstart_aromer.md](docs/quickstart_aromer.md).

## Scope & limitations

| Limit | Detail |
|---|---|
| Simulator-scoped safety | Controlled benchmarks do not prove field deployment safety |
| Small accepted holdout set | 88.0% is a point estimate; CI is wide |
| Live-agent validation pending | External replication and real tool-call studies are still needed |
| Evidence quality matters | Bad retrieval can cause bad governance decisions |
| Not a universal AI safety solution | REMORA governs actions; it does not make models truthful |

Full negative results: [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md).

## Implementation status

| Area | Status |
|---|---|
| Policy decision engine + 7 hard blocks | Implemented |
| DecisionEnvelope + SHA-256 audit chain | Implemented |
| Shadow replay | Implemented |
| LangGraph / OpenAI / MCP adapters | Implemented |
| Governance Intelligence Layer (opt-in) | Implemented |
| AROMER learning loop | Implemented (experimental) |
| Live-agent external validation | Pending |
| Production certification | Not claimed |

## Downloads & further reading

- **Research paper (PDF):** [direct download](https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf) · [in-repo source](paper/remora_paper.tex)
- **Enterprise white paper (PDF, TOGAF-aligned):** [direct download](https://remora-agent-control.razorsharp.workers.dev/papers/REMORA_Enterprise_Whitepaper.pdf)
- **Research notes / articles:** [remora.razorsharp.workers.dev/articles](https://remora.razorsharp.workers.dev/articles)
- [docs/plain_language_overview.md](docs/plain_language_overview.md) — non-technical overview
- [docs/policy_cookbook/](docs/policy_cookbook/) — practical policy examples
- [docs/togaf/](docs/togaf/) — enterprise architecture package

## Licensing

Open-source REMORA code is authored by Stian Skogbrott for Luftfiber AS under
Apache-2.0. AROMER branding, hosted/managed service rights, enterprise support,
compliance/audit packages, and private policy packs are reserved for separate
commercial agreements. GO-STAR, law search, DCE, and custom integrations are
proprietary unless explicitly released under a separate open-source license. See
[LICENSE](LICENSE), [NOTICE](NOTICE), [TRADEMARKS.md](TRADEMARKS.md), and
[enterprise/ENTERPRISE_LICENSE.md](enterprise/ENTERPRISE_LICENSE.md).

---

Built by [@darklordVirtual](https://github.com/darklordVirtual). Authored by Stian
Skogbrott for Luftfiber AS. Apache-2.0 licensed.
