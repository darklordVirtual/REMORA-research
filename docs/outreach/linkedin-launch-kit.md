# REMORA LinkedIn Launch Kit

Finished, copy-paste LinkedIn material. House style for everything in this file:
English, no hype, no emojis, no em dashes, no exaggerated claims (never "solves AI
safety"). Strong opening line that works before the "see more" cut. One idea per
post. Always close with a clear call to action. Put the GitHub link in the first
comment, not the post body (LinkedIn suppresses reach on posts with outbound
links).

Canonical links for first comments:
- Repo: github.com/darklordVirtual/REMORA
- Live demo: remora.razorsharp.workers.dev/control-room
- Paper (PDF): the R2 link in the repo README

Every number below keeps its caveat. Do not crop the caveats to make a punchier
line. The audience that matters checks.

---

## 1. Founder launch post

Most AI safety work tries to make the model say safer things. I spent the last
months on a different question: what happens in the moment an AI agent is about
to do something.

When an agent can call tools, a wrong answer stops being a wrong sentence. It
becomes a wrong action. A dropped table. A sent payment. A withdrawn route. The
safeguards we built for chat do not transfer to that moment.

REMORA is an open-source layer that sits in front of an agent's tool calls and
decides, before execution, whether to accept the action, verify it, abstain, or
escalate it to a human. Policy can override a confident model. Every decision is
written to an auditable record.

On a 700 task adversarial benchmark, the full policy gate executed 0 percent of
unsafe actions, with a 95 percent confidence interval of 0 to 0.55 percent. It is
research grade, not a certified product, and I publish the negative results next
to the positive ones.

If you work on agents, AI safety, or governance, I would value your eyes on it.
Tell me where it is wrong.

Call to action: star the repo and open an issue with the thing you would attack
first. Link in the comments.

---

## 2. Technical deep-dive post

A vote among language models cannot make an action safe.

If three models confidently agree to do the wrong thing, a majority vote just
rubber stamps it. More votes improve answer accuracy. They do not give you a
mechanism that can say no when the models are confidently wrong.

REMORA puts a set of hard policy blocks in front of the consensus. They run
first. If a block fires, for example a critical risk action in an unstable
regime, or an argument derived from untrusted input, the action is escalated no
matter how strong the agreement was. In testing, the uncertainty signal alone
left 10 percent of unsafe actions getting through. The policy layer is what took
it to zero.

The output of every decision is a DecisionEnvelope: the inputs, the verdict, the
reason codes, and a hash that chains to the previous record. You can replay the
whole chain and see exactly why each action was allowed or stopped.

Call to action: the four outcome model and the envelope schema are in the repo.
Read the code and tell me what you would change. Link in the comments.

---

## 3. Executive AI governance post

If your company is deploying AI agents that take real actions, two requirements
are coming whether you plan for them or not: demonstrable human oversight, and an
audit trail you can defend.

Most agent stacks today have neither. They have a clever model and hope.

REMORA is built around both. Every proposed action is routed to one of four
governed outcomes before it runs. If the policy engine is unreachable, it falls
back to a stricter rule set rather than a silent allow. Every decision is hash
chained, so tampering is detectable. Escalations generate a structured review
task with the evidence required and an owner.

It is research grade and honest about its limits, which is the point. A
governance layer that overstates its guarantees is worse than one that states
them precisely.

Call to action: if you own AI risk, send this to the team standing up agents and
ask them one question. When an agent acts on its own, who signs off, and can you
prove it. Link in the comments.

---

## 4. Research credibility post

My research write up has a section titled Negative Results, and that was on
purpose.

It documents the things that did not work. A difficulty signal I tried that
scored below chance and had to be repurposed. A regime where the system's own
confidence anti correlates with being right. Evidence retrieval that is still a
proxy rather than live. Each one is stated, with its sample size, not buried.

The reason is simple. In governance, a system that publishes its own limits is
more trustworthy than one claiming perfection, and every serious reviewer knows
it. The full derivations are written out so they can be checked line by line.

Call to action: if you work in AI safety, calibration, or selective prediction, I
am looking for external review. Reproduce a number, break a claim, or show a
caveat is understated. Link in the comments.

---

## 5. Demo announcement post

Here is one unsafe AI action getting stopped before it runs.

An agent proposes wiring ninety five thousand euros to a new account and asks to
skip the usual approval. REMORA evaluates it before anything executes. The risk
tier is critical, the action is a production financial write, and there is no
dual control evidence. A policy block fires before the model vote is even tallied.
The verdict is escalate to a human, with the evidence required attached. The wire
never runs. The decision is written to an audit record.

That is the whole idea in one example. Govern what the agent does, before it does
it.

Call to action: run the same scenario yourself in the live Control Room, or in
one command from the repo. Link in the comments.

---

## 6. Guardrails are not enough post

Guardrails watch what an AI says. They do almost nothing about what an AI does.

A content filter can catch a toxic sentence. It has no opinion on whether the
agent should run the database command it just generated. Those are different
problems. One is about language. The other is about an action with consequences
in a real system.

REMORA is the second layer. It governs the action: accept, verify, abstain, or
escalate, decided before execution, with policy able to override a confident
model, and an audit record for every call.

Call to action: if your agent can call tools, you need both layers. The action
layer is open source. Link in the comments.

---

## 7. What happens before an AI agent acts post

We talk a lot about what AI models output. We talk very little about the half
second before an agent acts on that output.

That half second is where the real risk lives. The model has produced a tool
call. Something is about to run. Right now, in most stacks, nothing stands in
that gap except a prompt and optimism.

REMORA stands in that gap. It takes the proposed action, checks it against policy,
evidence, uncertainty, and oracle disagreement, and returns one of four
decisions, before execution. The unsafe action does not run. The decision is
recorded.

Call to action: read how the gap is closed. The architecture and the benchmarks
are in the repo. Link in the comments.

---

## 8. External review invitation post

I am asking for something uncomfortable: please try to break my work.

REMORA is an open-source governance layer for AI agent actions. The claims are
backed by committed artifacts, the math is written out in full, and the negative
results are published. What it has not had yet is enough independent scrutiny.

If you are an AI safety researcher, an agent framework maintainer, or a security
engineer, there is a thirty minute review path and a two hour technical review
path in the repo. Reproduce a number. Challenge a caveat. Find the hole.

Call to action: open an issue with the external review template, or send me a
direct message. Link in the comments.

---

## 9. Short punchy post (under 900 characters)

A vote among AI models cannot stop a confident, wrong action from running.

If three models agree to do the wrong thing, the vote just approves it faster.

What is missing is not a smarter model. It is a layer that asks whether the
conditions for the action are actually met, and can say no regardless of the
vote.

That is REMORA. It governs an agent's tool calls before they run: accept, verify,
abstain, or escalate, with policy that overrides consensus and an audit record
for every decision. Open source, research grade.

Call to action: star the repo if this is a problem you have. Link in the comments.

---

## 10. Long-form LinkedIn article

Title: Before an AI agent acts, something should decide if it should

We spent two years making language models safer to talk to. We are about to hand
those same models the ability to act, and we have barely started on the layer
that decides whether a specific action should run.

This is not a small gap. A hallucinated sentence is embarrassing. An executed
action is not. When an agent can call tools, query databases, move money, or
change infrastructure, the failure mode changes from awkward to irreversible. The
safeguards we built for conversation, alignment training, system prompts, content
classifiers, all operate on language at training or prompt time. None of them
evaluate a specific proposed action, against a specific operational context, at
the moment of execution.

The common answer is to ask several models and take the majority. It helps with
accuracy and does nothing for safety. A vote cannot block a confident, wrong
consensus. Worse, the cases where models agree most strongly are not always the
cases where they are most right. In the hardest cases I measured, the system's
own confidence anti correlated with being correct.

REMORA is my attempt at the missing layer. It sits in front of an agent's tool
calls and produces one of four governed outcomes before anything runs. Accept
means the conditions for autonomous execution are met. Verify means it is
plausible but needs validation. Abstain means the uncertainty is too high to
decide. Escalate means a human reviews it, with the evidence required attached.
Crucially, a set of hard policy blocks runs before any consensus is consulted, so
a confident, wrong majority cannot push an unsafe action through.

It is auditable by construction. Every decision becomes an immutable record,
hash chained to the previous one, so any later modification is detectable. You
can replay the entire chain and see exactly why each action was allowed or
stopped.

I want to be precise about what this is and is not. It is a research grade
reference architecture, not a certified product. On a 700 task adversarial
benchmark the full policy gate executed 0 percent of unsafe actions, with a 95
percent confidence interval of 0 to 0.55 percent. Evidence retrieval is currently
a proxy. The thresholds are not calibrated for any specific production
environment. I publish all of this, including the negative results, because a
governance system that hides its limits is the one you should not trust.

If you are building agents that act, the question is not whether your model is
aligned. It is whether you can decide, defensibly and on the record, which of its
actions are allowed to run. That decision is what this layer is for.

The project is open source. I am looking for people to use it, integrate it, and
above all to review it and tell me where it is wrong.

Call to action: star the repository, run the live demo, and if you have the
expertise, take the external review path and challenge a claim. Links in the
comments.

---

## 10 alternative hooks
1. A vote among AI models cannot make an action safe.
2. Guardrails watch what AI says. Almost nothing governs what AI does.
3. The riskiest moment in agentic AI is the half second before the action runs.
4. My most confident AI predictions were my most wrong ones.
5. We made models safer to talk to. We forgot to govern what they do.
6. An AI agent just tried to wire ninety five thousand euros. Here is what stopped it.
7. Majority vote is not a safety mechanism. It is a faster way to be confidently wrong.
8. If your agent can call tools, a content filter is not enough.
9. In governance, publishing your failures is the trustworthy move.
10. Before an AI agent acts, something should decide if it should.

## 10 post titles
1. Before an AI agent acts, something should decide if it should
2. Why a vote among AI models cannot make an action safe
3. The audit trail your AI agents do not have yet
4. What happens in the half second before an agent acts
5. Guardrails are not enough for agents that act
6. The trust inversion: when confident AI is most wrong
7. Govern what AI does, not just what it says
8. Pre-execution governance for AI agents, explained simply
9. I published my negative results on purpose
10. How to stop an unsafe AI action before it runs

## 10 reply comments the founder can use
1. Good question. The short answer is that policy runs before the model vote, so a confident wrong consensus cannot override it. Happy to point you at the exact code path.
2. Fair challenge. It is research grade, not certified, and I say so everywhere. What specifically would you want to see validated.
3. Yes, the 0 percent is a point estimate. The honest version is the 0 to 0.55 percent confidence interval, which is in the readme.
4. That is exactly the kind of review I am after. Open an issue with the external review template and I will engage on it directly.
5. Agreed that evidence retrieval being a proxy is a real limitation. It is listed in the negative results. Live retrieval is on the roadmap.
6. The four outcomes map to supervisory control levels. Accept is human on the loop, escalate is human in the loop, with verify and abstain in between.
7. You can run the same scenario in the live Control Room in a couple of clicks, or in one command from the repo. Link in the post.
8. Thank you. If you know someone standing up agents in production, that is exactly who I built this for.
9. The audit chain is tamper evident, not tamper proof. Real tamper resistance needs append only storage, which is a deployment dependency. I am careful about that wording.
10. Star helps more than you think for a project like this. And if you have the time, the thirty minute review path is the most useful thing you could do.

## 5 DM outreach templates
See `docs/outreach/external-review-dm-templates.md` for the full set (researcher,
developer, enterprise architect, framework maintainer, security engineer).
