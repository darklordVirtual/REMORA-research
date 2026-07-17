# REMORA — Executive One-Pager

**One sentence:** REMORA is an executable reference architecture for the
governance layer agent platforms are missing: it decides — per action, with
evidence — whether an AI agent's proposed action is executed autonomously,
reviewed by a human, or stopped.

---

## Problem

Enterprises are moving from AI pilots to agent fleets that touch business
systems and, in industrial settings, safety-relevant infrastructure. Platform
capability is advancing fast; the *control question* is largely unanswered:
who authorizes an individual agent action, on what evidence, under which
delegated authority — and how is that proven afterwards? Per-tool access
control does not scale to this: each step can be individually permitted while
the sequence is not, and "human in the loop" as a blanket rule collapses at
fleet scale.

## Architecture (one layer, four planes)

An assurance control plane between the agent platform and the systems agents
act on — platform-neutral, integrated over open standards (OPA/Rego policy,
OpenTelemetry GenAI telemetry, MCP tool gating, A2A-style delegation
envelopes, RDF audit export):

1. **Decision** — hard safety guards first, then uncertainty-calibrated
   routing to `ACCEPT / VERIFY / ABSTAIN / ESCALATE`. Autonomy is a policy
   output per action, not a property of the agent.
2. **Enforcement** — signed decision tokens bound to the exact tool-call
   arguments; fail-closed on tamper, expiry, or mismatch.
3. **Identity & delegation** — signed envelopes carrying agent identity,
   accountable organisation, and capability chains that can only narrow.
4. **Evidence** — a signed `DecisionEnvelope` per decision, hash-chained,
   replayable, exportable to the operator's knowledge-graph tooling.

Details: [reference_architecture.md](reference_architecture.md).

## Demo (5 minutes, no keys, no network)

```bash
pip install -e ".[dev]" && make test        # full deterministic suite
python scripts/demo_industrial_maintenance.py
```

An RCA-style maintenance agent reads telemetry (**ACCEPT**), proposes a
work-order change (**VERIFY** — the production-write policy matrix requires
human approval), meets contradicting evidence (**ABSTAIN**), and attempts
direct equipment actuation (**ESCALATE** — the signed delegation envelope
fails scope verification; analysis confidence cannot buy actuation
authority). All five decisions come from verified delegation plus the real
decision engine — four canonical outcomes, pinned by tests.

## Evidence discipline

Every quantitative claim in this repository links to a committed result
artifact, negative results are published (`NEGATIVE_RESULTS.md`), and CI
enforces claim-artifact consistency. Key artifact-backed results: zero unsafe
executions on the blinded internal benchmark
(`results/toolcall_blind_v3_results.json`, N=700) and on an independent
external harmful-scenario dataset
(`results/external_benchmark_agentharm_v1.json`, n=208) — both
benchmark-scoped, neither a field-deployment claim.

## Limitations — stated, not buried

Research-grade, `SHADOW_ONLY`. All benchmarks internally run; the
independent-review gate is open and blocks any enforcement mode, tracked in a
public gate register (`docs/assurance/release_gates.md`). The audit chain is
tamper-evident, not tamper-proof. This is an architecture proof intended to
be shadow-run against real agent logs before any enforcement is enabled.

## 90-day pilot shape

**Weeks 0–4:** shadow-replay the operator's real agent action logs → concrete
blocked/reviewed deltas and friction estimate, zero operational impact.
**Weeks 4–8:** encode the operator's autonomy rules as versioned policy;
validate with the conformance harness against the same logs.
**Weeks 8–12:** gated enforcement on one low-consequence action class, with
independent review as the promotion criterion. Every phase produces
replayable artifacts the go/no-go is made against.
