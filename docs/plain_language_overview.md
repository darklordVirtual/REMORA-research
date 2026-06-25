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

## What Is Demonstrated

REMORA has reproducible benchmark evidence for:

- selective QA acceptance on N302 and a 544-item N500 artifact,
- deterministic tool-call safety benchmarking,
- an adversarial tool-call v2 simulator where REMORA full policy reaches zero
  unsafe execution,
- structural governance for long-running agents.

## What Is Not Yet Demonstrated

REMORA is not yet proven as a production safety system.

Open gaps:

- independent live validation,
- real deployment telemetry,
- stronger semantic evidence verification,
- external reproduction,
- calibrated governance-drift thresholds.

## Short Summary

REMORA turns AI reliability into a routing problem:

> accept what is strong, verify what is uncertain, abstain when trust is too
> low, escalate what is too risky, and never let agent memory or tool calls
> drift outside their authority boundaries without review.
