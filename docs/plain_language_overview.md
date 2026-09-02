# REMORA in Plain Language

## What REMORA Is

REMORA is a control layer for AI systems.

It asks a simple question before an AI answer or action is trusted:

> Is this reliable enough to accept, or should it be verified, refused, or
> escalated?

REMORA is not a chatbot. It is a way to decide when AI should answer, when it
should check evidence, when it should avoid acting, and when a person should be
involved.

## Why It Exists

AI models can sound confident while being wrong. In low-risk settings that may
be acceptable. In legal, medical, industrial, infrastructure, security, or
customer-facing workflows, a wrong confident answer can cause real harm.

REMORA is built around a safer default:

- answer when trust is high,
- verify when uncertainty is manageable,
- abstain when trust is too low,
- escalate when risk or authority requires a human,
- execute tool calls only when policy allows it.

## How It Works

REMORA compares several signals:

- do multiple AI oracles agree?
- are they confident for the same reason?
- is there supporting evidence?
- does policy allow this action?
- is this a safe tool call?
- is the agent drifting over time?
- is persistent memory being written safely?

The result is one route:

| Route | Meaning |
|---|---|
| `ACCEPT` | Trust the result |
| `VERIFY` | Check more evidence or ask another reviewer |
| `ABSTAIN` | Do not answer or act |
| `ESCALATE` | Send to human review |

## Asking What It Would Take

A blocked action raises an obvious question: what would have to be different?
The `whatif` command answers it by trying every combination of favourable
signals against the real policy. For a critical production write the answer
is that no amount of model confidence reaches ACCEPT. The only paths that do
require the deployment to declare the tool low risk and read-only, which is
to say a different tool. Each change in a path is labelled with who can make
it: the deployment, the agent's own proposal, or a model. The answer is an
analysis of the policy, never a grant.

## What Is Demonstrated

REMORA has reproducible benchmark evidence for:

- selective question-answering: knowing which subset of decisions can be
  trusted (measured on committed 302-item and 544-item benchmark artifacts),
- deterministic tool-call safety benchmarking,
- an adversarial tool-call simulator where the full policy reaches zero
  unsafe execution (simulator-scoped; see the caveats in
  [02-evidence-and-claims.md](02-evidence-and-claims.md)),
- structural governance for long-running agents.

## What Is Not Yet Demonstrated

REMORA is not yet proven as a production safety system.

Open gaps:

- independent live validation,
- real deployment telemetry,
- stronger semantic evidence verification,
- external reproduction,
- calibrated governance-drift thresholds.

## Key terms

The vocabulary used across the front page and the evidence documents, in plain
language. Canonical metric definitions with exact denominators:
[metric definitions](assurance/metric_definitions_v1.md).

| Term | Meaning |
|------|---------|
| **False accept rate (FAR)** | How often something harmful was wrongly allowed. The safety headline; 0% is the goal. |
| **False block rate (FBR)** | How often something harmless was blocked. 100% means safety was bought by blocking everything, useful work included. |
| **N / effective N** | Sample size. Effective N counts only genuinely independent items: 700 tasks built from 70 templates give effective N=70, and every statistic here uses the 70. |
| **Wilson 95% interval** | The range of true rates the data is compatible with. The upper end is the worst case the evidence cannot rule out. |
| **Blind / sealed / spent** | A blind set is scored exactly once, against targets fixed beforehand. Afterwards it is *spent*: running it again measures development, not generalisation, and this repo labels which is which. |
| **Coverage** | The share of decisions the system is willing to answer at all. Accuracy is then measured only on that share. |
| **Calibrated confidence** | Model confidence rescaled on held-out data so that "0.9" really does mean about 90% right. |
| **Multi-oracle consensus** | Several independent models judging the same action, merged into one trust score. |
| **Intent-gating vs interception** | Intent-gating judges what the agent *says* it will do. Interception would capture the call itself. The AgentHarm result is intent-gating. |
| **Shadow mode** | Decisions are computed and logged but not enforced. REMORA's current profile. |
| **Lease / dispatcher (PEP)** | The dispatcher is the only component that actually runs a tool, and only under a single-use lease tied to tenant, tool, exact arguments and policy version. |
| **Superseded claim** | A result a later round replaced. It is archived, never deleted, and may not be cited on the front page. |
| **AROMER** | The experimental learning layer that sits on top. Nothing in the core depends on it. |

## Short Summary

REMORA turns AI reliability into a routing problem:

> accept what is strong, verify what is uncertain, abstain when trust is too
> low, escalate what is too risky, and never let agent memory or tool calls
> drift outside their authority boundaries without review.
