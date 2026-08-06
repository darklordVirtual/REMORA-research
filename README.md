# REMORA: Policy-Gated Governance for Operational AI Agents

[![Paper (PDF)](https://img.shields.io/badge/paper-PDF-b31b1b.svg)](paper/remora_paper.pdf) [![CI — Deterministic Test Suite](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml) [![Quality Gates](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml) [![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](LICENSE)

**An AI agent wants to do something. REMORA decides whether it may, before it happens.**

Give an agent real tools and it will eventually reach for the wrong one: the wrong
database, the wrong machine, an instruction that arrived inside a document it was
reading. REMORA is a **governance overlay** — a checkpoint the proposed action must
pass before anything runs. It does not replace the agent; it answers one question per
action, and records why.

| Answer | What it means |
|--------|---------------|
| **ACCEPT** | Safe to run on its own |
| **VERIFY** | One specific thing must be checked first |
| **ABSTAIN** | Not enough to go on, so stop |
| **ESCALATE** | A person has to decide this |

```bash
pip install -e ".[dev]" && python -m remora try     # try it, no API keys needed
```

Built for work where a wrong action costs something real: building automation, energy management, infrastructure control, regulated enterprise workflows.

**Start here:** [Plain-language overview](docs/plain_language_overview.md) · [Reference architecture](docs/reference_architecture.md) · [Executive one-pager](docs/executive_onepager.md) · [Docs index](docs/README.md)

---

## What it does well

Each result is measured on a committed artifact and governed by the
[claim register](docs/assurance/claim_register_v1.yaml); every number carries the
caveat that bounds it.

<!-- claim:CLAIM-002 far_pct far_ci_high_pct fbr_pct n -->
<!-- claim:CLAIM-001 far_pct n_effective n -->
<!-- claim:CLAIM-016 routing_accuracy_pct irrelevance_abstain_pct unobtainable_abstain_pct obtainable_verify_pct required_unknown_accept_pct -->
<!-- claim:CLAIM-013 cw_accuracy_pct majority_accuracy_pct mcnemar_p n -->
<!-- claim:CLAIM-003 far_pct n -->
| What was measured | Result | Bounded by |
|---|---|---|
| **Nothing harmful got through** on an external harm benchmark (AgentHarm) | **0.0%** wrongly allowed, N=208, worst case the data allows: 1.81% | it judges stated intent, not the executed call, and the same strict floor also blocked every harmless twin (100.0%) |
| **Nothing harmful got through** in the adversarial simulator | **0.0%** unsafe runs, 0 of 70 scenario templates (700 tasks), worst case 5.2% | a simulator, not a live system; the margin over simple baselines, Δ=0.0143, is **not statistically significant** (p=0.50). The clear win is usefulness, +0.456 |
| **The behaviour transferred to outside data it had never seen** (BFCL v3, one sealed run) | irrelevant tool → refused **100.0%** of the time (258/258); unobtainable input → refused **100.0%** (133/133); obtainable input → sent for checking **82.7%**; overall routing **94.0%** correct; **0.0%** of unknown-but-required inputs were guessed (0/19) | 4 of 5 pre-registered targets met; the 5th missed, and is [published as measured](NEGATIVE_RESULTS.md#34-external-blind-track-bfcl-four-axes-hold-wrong-call-blindness-measured-cleanly-2026-07-31) |
| **No previously-known failure came back** (historical regression corpus) | **0.0%** wrongly allowed, N=167 | a re-run of past mistakes: it proves nothing new, only that nothing broke |
| **Weighing models by how well-calibrated they are beat counting votes** | **87.8%** vs **85.1%**, N=368, paired test p=0.0064 | better than plain vote-counting, but only directional against the single best model (p=0.077), so **it was not switched on** in the engine |

The two mechanisms behind those numbers — a deterministic hard-guard floor no model
signal can override, and permission welded to the exact call it was granted for — are
explained with code references in the [architecture narrative](docs/01-architecture.md);
baseline context is in [evidence & claims](docs/02-evidence-and-claims.md).

**Evidence discipline.** Replaced results are archived, never deleted
([superseded claims](docs/assurance/superseded_claims.md)); failed results are
published in full in [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md). CI enforces both.

---

## How it works

Everything the agent proposes goes through the same five steps, and nothing runs until
the last one produces an answer:

1. **Admission firewall** — injection, coercion and blackmail patterns are screened
   before any model is called.
2. **Multi-oracle consensus** — independent models judge the action; one trust score.
3. **Evidence verification** — do the cited sources support or contradict it?
4. **Policy decision** — deterministic hard guards first, and they win outright: no
   confidence score or model majority can unlock a forbidden tool, a malformed call,
   or a detected injection. Then conditional guards and calibrated trust routing.
5. **DecisionEnvelope** — every answer joins a hash-chained audit log, whether or not
   anything ran.

On ACCEPT, `/v1/execution/execute` spends a single-use grant and runs the call under a
lease welded to the exact approved arguments. Tools come **only** from deployment
configuration, never from the request — and REMORA cannot stop an agent that reaches a
tool *outside* this API (see [Status](#status-and-what-is-not-proven)). The pipeline
diagram, hard-guard priority rules, what a VERIFY promises, and the diagnostic-only
disagreement metrics: [architecture narrative](docs/01-architecture.md) ·
[ARCHITECTURE.md](ARCHITECTURE.md) (canonical) · [API](docs/07-api-reference.md).

---

## Try it

```bash
python -m remora assess drop_database # one-shot verdict for a named tool
python -m pytest tests/ -q            # full deterministic suite (~4,600 tests, no keys, ~80s)
python scripts/demo_industrial_maintenance.py   # end-to-end walkthrough (dry-run)
python -m remora doctor               # environment self-check, with fixes
```

Nothing above needs an API key: a critical production delete escalates to a person, an
injected instruction is stopped at the firewall, a harmless read is accepted — and each
result shows the rule that decided it. Add `--envelope` for the full audit record, or
`--live` for real models (key in the environment; never printed or stored). Every
command, exit code and option: [docs/cli.md](docs/cli.md).

To govern your own agent, the risk and action type must come from **your tool
registry**, bound to the callable, never guessed from the tool's name:

```python
from remora import assess_tool_call
a = assess_tool_call("drop_database", {"db": "prod-main"},
                     risk_tier="critical", action_type="destructive_write")  # from your registry
if a.should_execute: run_tool(...)   # ACCEPT only; a.envelope is the audit record
```

That library path is *advisory*: it judges the facts you hand it. The enforcing path is
the `/v1/execution` API ([deployment quickstart](docs/deployment/execution-quickstart.md)) — run it locally with the production-mode Docker OT pilot and operator console ([deploy/ot-pilot/docker-compose.yml](deploy/ot-pilot/docker-compose.yml)) or the lighter dev-mode [docker-compose.test.yml](docker-compose.test.yml).
Worked loop: [examples/agent_gate.py](examples/agent_gate.py) · scenarios:
[docs/use-cases/](docs/use-cases/README.md) · reproduce every benchmark:
[docs/06-reproducibility.md](docs/06-reproducibility.md).

---

## Status, and what is not proven

<!-- BEGIN GENERATED: status, source: assurance registers, via scripts/generate_readme_status.py --check. DO NOT EDIT. -->
**Deployment profile:** `SHADOW_PILOT` (= `SHADOW_ONLY`), recomputed from the capability and remediation registers by CI; a profile cannot be raised by editing prose.

**To reach `CONTROLLED_PILOT`, still open:** REM-021, REM-023.

**Capabilities:** 7 of 15 wired to the API path or deeper ([wiring register](docs/assurance/capability_register_v1.yaml)); full gate status in [release_gates.md](docs/assurance/release_gates.md), maturity ladder in [release_profiles_v1.yaml](docs/assurance/release_profiles_v1.yaml).
<!-- END GENERATED: status -->

Shadow-mode research only; not certified for production. The load-bearing caveats:

- **The safety numbers come from benchmarks, not from the field.** The 0% unsafe-execution
  rate is a synthetic-benchmark result: a deterministic simulator and a controlled internal
  corpus, with no real shell, network or database touched.
- **Sample sizes are smaller than they look.** The simulator's 700 tasks are 70 templates
  × 10 cosmetic variants (effective N=70); the margin over baselines is not significant (p=0.50).
- **Nobody outside this project has reproduced any of it.** External replication is pending —
  a distinct, still-open evidence level, and a prerequisite for any stronger label.
- **REMORA cannot stop an agent that goes around it.** The guarantee holds only where a
  deployment routes every tool call through the dispatcher and the agent has no credentials.
- **The audit log detects tampering; it does not prevent it.** Prevention needs append-only
  (WORM) storage, which is not included here.
- **AROMER is experimental**; its numbers are not evidence for the core system.

Everything still open: [remediation_register.yaml](docs/assurance/remediation_register.yaml).
Evidence and leakage disclosures: [evidence & claims](docs/02-evidence-and-claims.md) ·
[experiments](docs/03-experiments.md) · [reviewing this repo](docs/validation/external-review.md).
Terms — FAR/FBR, effective N, Wilson interval, intent-gating, lease — in the
[glossary](docs/plain_language_overview.md#key-terms); denominators in [metric definitions](docs/assurance/metric_definitions_v1.md).

---

## Research foundation, and the experimental layer

Every research line REMORA builds on maps to a concrete control, code file and test in the
machine-checked [research-control matrix](docs/research/research_control_matrix.generated.md).
Positioning: [docs/09-related-work.md](docs/09-related-work.md); derivations:
[paper/remora_paper.md](paper/remora_paper.md). **AROMER**, the **experimental**
closed-loop calibration layer, sits on top: nothing in the control plane depends on it, and its
metrics are **not** evidence for the core governance system
([docs/03-experiments.md](docs/03-experiments.md) §9 · [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md) §12–§16).

**Productized downstream:** [Assured Agent Execution](https://github.com/darklordVirtual/assured-agent-execution)
consumes this repository as seven hash-pinned release artifacts — never from `master`, import
boundary enforced by a test. It is the working evidence that the SDK surface is consumable by a
product, and where upstream gaps surface first: deployment-declared tool classification,
`GROUNDED_READ_ACCEPT` and per-surface fail-closed prerequisites all came from there.

## AI use, citation, license

Built with the assistance of generative-AI development tools; no AI output was accepted
as evidence without an independently confirmed committed artifact, a passing test, or a
verified external source. Full disclosure: [docs/AI_USE.md](docs/AI_USE.md).

```bibtex
@misc{remora2026,
  title  = {REMORA: A Policy-Gated Multi-Oracle Assurance Architecture for Agentic AI},
  author = {Skogbrott, Stian},
  year   = {2026},
  url    = {https://github.com/darklordVirtual/REMORA-research},
  note   = {Research-grade reference architecture. Results are internally
            replicated and bounded by documented assumptions. External
            replication pending.}
}
```

REMORA versions from `v0.10.0` are **source-available under the
[Business Source License 1.1](LICENSE)**, which is not open source, or available under a
separate written [REMORA Commercial License](COMMERCIAL_LICENSE.md). The Licensor is
Stian Skogbrott; **no commercial use is permitted without a commercial license from
the Licensor**.

The BSL permits source inspection, modification, redistribution and non-production
use. **Research is expressly welcome**: studying, benchmarking, reproducing and
publishing results (no benchmark clause) is granted to any person or organization,
and 90-day observer-only shadow-mode research evaluation is granted even inside
companies. Any commercial production use requires a separate commercial agreement —
scope and examples: [LICENSING.md](LICENSING.md); contact: support@luftfiber.no.

Before contributing, see [docs/10-contributing.md](docs/10-contributing.md): run the
full quality gate, ensure every claim links to a committed artifact on disk, and do not
remove negative results or caveats. Working agreement: [CLAUDE.md](CLAUDE.md).
