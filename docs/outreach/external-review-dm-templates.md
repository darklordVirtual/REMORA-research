# Outreach Templates: External Review and Integration

Copy-paste templates for inviting review and integration. House style: English,
no hype, no emojis, no em dashes, short, specific, and respectful of the
recipient's time. Always make the ask small and concrete.

Personalize the first line every time. A generic blast is worse than nothing.

---

## Short email (cold, any audience)

Subject: 30 minutes on an open-source governance layer for AI agents

Hi {name},

I built REMORA, an open-source layer that decides, before an AI agent runs a tool
call, whether to accept, verify, abstain, or escalate it. It is research grade and
I publish the negative results.

Given your work on {their area}, I would value a short, critical read. There is a
30 minute review path in the repo. If you find a claim that does not hold, that is
the most useful outcome for me.

Repo: github.com/darklordVirtual/REMORA

No obligation. Even a one line reaction would help.

Thanks,
Stian

---

## Long email (warm, researcher or maintainer)

Subject: Inviting external review of REMORA, a pre-execution governance layer for AI agents

Hi {name},

I have been following {specific work of theirs}. I am reaching out because the
problem I have been working on overlaps with it, and I think you would have a
sharp view on whether I got it right.

REMORA is an open-source governance layer for AI agent actions. It intercepts a
proposed tool call before execution and routes it to one of four outcomes,
accept, verify, abstain, or escalate, using policy, evidence, uncertainty, and
oracle disagreement. Every decision is written to an auditable, hash chained
record.

The claims are backed by committed artifacts and the math is written out in full.
On a 700 task adversarial benchmark the full policy gate executed 0 percent of
unsafe actions, with a confidence interval of 0 to 0.55 percent. I also document a
regime where the system's own confidence anti correlates with correctness, and I
treat it as a negative result rather than hiding it.

What I am missing is independent scrutiny. The repo has a 2 hour technical review
path and a research replication path. If you have time to reproduce one number or
challenge one caveat, I would be grateful, and I will engage on it directly.

Repo: github.com/darklordVirtual/REMORA
Paper and math supplement are linked from the readme.

Thank you for considering it.

Best,
Stian

---

## LinkedIn DM (developer or framework maintainer)

Hi {name}, I built an open-source pre-execution governance layer for AI agent tool
calls. It decides accept, verify, abstain, or escalate before the action runs,
with adapters for MCP, LangGraph, and OpenAI tool use. Given your work on {their
framework}, I would value a critical look, especially at the adapter design. Repo
is in my profile. Even a quick reaction helps. No pressure.

---

## LinkedIn DM (enterprise architect)

Hi {name}, quick one. If your teams are deploying AI agents that take real
actions, REMORA is an open-source layer that gates each action before it runs and
writes an audit trail, mapped to EU AI Act and NIST AI RMF. I am looking for
practitioner feedback on whether the governance model fits how you actually
review autonomous systems. Open to a short call, or just send me a reaction. Repo
in my profile.

---

## Reddit / Hacker News comment response (when someone is skeptical)

That is a fair challenge, and I would rather you push on it than not. To be
precise: the 0 percent unsafe figure is a point estimate with a 0 to 0.55 percent
confidence interval, on a deterministic simulator benchmark, and I attribute the
reduction to the policy hard blocks rather than the uncertainty signal. It is
research grade, not certified. If you reproduce a different number or think a
caveat is understated, open an issue and I will engage on it directly. The
negative results are in the repo, including a case where the system's own
confidence anti correlates with correctness.

---

## Researcher DM (AI safety / calibration)

Hi {name}, I have a result you might find interesting and might want to break. In
the hardest decision regime, the system's trust score anti correlates with
correctness, low trust items at 71 percent correct versus high trust at 27
percent, on a small sample. I treat it as a negative result and route around it
by inverting the selection rule rather than trusting the score. Full derivation is
in the repo. Would value your read on whether the framing holds. No obligation.

---

## Follow-up (one, only if no reply after a week)

Hi {name}, following up once in case this slipped by. Even a one line reaction to
REMORA would be useful, positive or negative. If it is not relevant to your work
right now, no problem at all, and thank you for your time.
