# REMORA — LinkedIn Promotion Kit

Ready-to-post drafts to get eyes on REMORA. Every claim here is transcribed from
a committed artifact (`paper/remora_paper.pdf`, repo benchmarks) **with its
caveat intact** — per `CLAUDE.md`, stripped-of-caveats numbers are overclaims and
will get you challenged by exactly the technical audience you want. Keeping the
qualifiers (`held-out`, `Wilson CI [0, 0.55%]`, `research-grade`) makes you *more*
credible, not less.

---

## How to use this kit (LinkedIn mechanics that actually move reach)

- **First line is everything.** LinkedIn truncates at ~140 chars ("…see more").
  The hook must work alone. Each draft's first line is written to stand by itself.
- **Put links in the FIRST COMMENT, not the post body.** LinkedIn suppresses reach
  on posts with outbound links. Post the text, then immediately comment the link.
- **Short lines, lots of white space.** Mobile-first. No dense paragraphs.
- **One idea per post.** Don't combine the "0% unsafe" hook with the trust-inversion
  story — that's two posts.
- **Cadence:** 2–3 posts/week, varying the angle (proof → counterintuitive →
  honesty → build-in-public). Don't fire all ten in a week.
- **Always end with a question or CTA** — comments are the #1 reach signal.
- **Tag/segment hashtags:** 3–5 max, mix broad (#AIsafety) and niche
  (#AgenticAI #AIgovernance).
- **Image > text.** Posts with a clean visual (the four-outcome board, the proof
  numbers, a decision-envelope screenshot) outperform text-only ~2×. Reuse the
  landing-page proof row or an OpenGraph card.

> Suggested canonical link for comment #1:
> `https://remora.razorsharp.workers.dev` (live demo) — or the GitHub repo for a
> technical crowd. Pick per post (noted in each).

---

## Post 1 — The flagship hook (proof-led)

**Hook:** Every benchmark of our AI safety layer hit the same number: 0% unsafe
actions executed. Here's the catch I have to tell you about.

> AI agents are starting to *do* things — run database queries, trigger
> processes, move money. A hallucinated sentence is embarrassing. A wrongly
> executed `DROP TABLE` is not.
>
> So I built REMORA: an assurance layer that decides — *before* execution —
> whether an agent's action is safe to run autonomously, needs verification,
> should abstain, or must go to a human.
>
> On a 700-task adversarial tool-call benchmark, REMORA's full policy gate let
> through **0% unsafe executions** (baselines: 10–20%).
>
> The catch I owe you: that's a point estimate. The honest version is a 95%
> confidence interval of [0%, 0.55%] — "at most 1 in 180," not "never." And the
> reason it works isn't magic: hard policy blocks account for 100% of the
> reduction. Consensus alone never gets there.
>
> Governed autonomy isn't about a smarter model. It's about routing uncertainty
> instead of suppressing it.
>
> What's the riskiest action you'd let an AI agent take without a human in the
> loop?

**Link (comment 1):** live demo. **Hashtags:** #AIsafety #AgenticAI #AIgovernance #LLM
**Image:** the four-outcome board (ACCEPT/VERIFY/ABSTAIN/ESCALATE).

---

## Post 2 — The counterintuitive finding (most shareable)

**Hook:** Our most confident AI predictions were our *most wrong* ones. We
stopped fighting it and started exploiting it.

> While building REMORA I hit a result I didn't believe at first.
>
> In the hardest, most ambiguous cases ("critical phase"), the system's own
> confidence score *anti-correlated* with being right:
> • low-confidence items: 71% correct
> • high-confidence items: 27% correct
>
> Trusting the confident answers would have been worse than a coin flip.
>
> Most teams would bury that. We did the opposite: where the data say confidence
> is anti-informative, we **invert the selection rule** — and recovered usable
> accuracy in exactly the regime where naive methods collapse to zero coverage.
>
> The lesson that stuck with me: a safety system's job isn't to be confident.
> It's to know *when its confidence is worthless* — and route around it.
>
> Have you seen model confidence betray you like this?

**Link (comment 1):** the paper. **Hashtags:** #MachineLearning #AIsafetY #Calibration #LLM
**Image:** a simple 71% vs 27% bar.

---

## Post 3 — The honesty angle (trust through transparency)

**Hook:** My AI research paper has a whole section titled "Negative Results."
That was on purpose.

> Most AI announcements read like everything works perfectly. Mine ships a
> published list of what *doesn't*:
> • a susceptibility metric I tried as a difficulty predictor — failed,
>   AUC 0.39, worse than chance. (Repurposed it as an out-of-distribution
>   trigger instead.)
> • trust scoring can't safely gate the hardest cases — documented, not hidden.
> • evidence retrieval is still a proxy, not live.
>
> Why publish the failures? Because in governance, a system that admits its
> limits is more trustworthy than one claiming perfection — and every reviewer
> knows it.
>
> REMORA is research-grade, honestly scoped. It converts AI disagreement,
> uncertainty, and policy violations into explicit, auditable decisions — and
> tells you exactly where it's still weak.
>
> Would you trust a vendor more, or less, for publishing their negative results?

**Link (comment 1):** GitHub (NEGATIVE_RESULTS.md). **Hashtags:** #AIethics #AIgovernance #ResponsibleAI #OpenSource

---

## Post 4 — The "what it actually is" explainer (for non-experts)

**Hook:** "Governed autonomy" sounds abstract. Here's REMORA in one concrete
decision.

> An AI drilling agent proposes: lower the kill-mud weight from 1.52 to 1.48 to
> drill faster.
>
> REMORA runs the play:
> • 3 independent models vote → 71% say "escalate, this is risky"
> • the situation is flagged "critical phase, critical risk"
> • a hard policy rule fires *before* any vote is even tallied
> • verdict: **ESCALATE** → routed to an independent well engineer, with the
>   exact evidence required and a 4-hour SLA
> • the whole decision is hash-stamped into a tamper-evident audit trail
>
> Here's the key: the action would have been blocked **even if the models had
> voted to proceed.** Policy overrides consensus. A confident, wrong majority
> can't push an unsafe action through.
>
> That's the difference between a smarter chatbot and an assurance layer.
>
> Where in your operation would you want a gate like this?

**Link (comment 1):** live demo (Control Room). **Hashtags:** #AIsafety #IndustrialAI #AgenticAI #HumanInTheLoop

---

## Post 5 — Standards / enterprise angle (for risk & compliance leaders)

**Hook:** The EU AI Act mandates human oversight and audit trails for high-risk
AI. Most agentic AI stacks have neither. Here's one approach.

> If you're deploying AI agents that take real actions, two requirements are
> coming whether you like them or not: demonstrable **human oversight** and an
> **audit trail**.
>
> REMORA is built around both:
> • every agent action → one of four governed outcomes (accept / verify /
>   abstain / escalate)
> • fail-closed: if the policy engine is unreachable, it falls back to a stricter
>   rule set — never a silent "allow"
> • every decision is SHA-256 hash-chained — tamper-evident by construction
> • ESCALATE generates a structured human-review task (role, required evidence,
>   SLA)
>
> It's mapped against EU AI Act human-oversight provisions and NIST AI RMF — not
> as a compliance checkbox, but as the actual control surface.
>
> Honest scope: it's a research-grade reference architecture, not a certified
> product. But the controls are real and testable today.
>
> If your agents act autonomously, who signs off — and can you prove it?

**Link (comment 1):** GitHub / enterprise white paper. **Hashtags:** #AIgovernance #EUAIAct #RiskManagement #Compliance

---

## Post 6 — Build-in-public / founder angle

**Hook:** I shipped 2,800+ tests, a research paper, and a live demo for an AI
safety layer almost nobody has looked at yet. Sharing it anyway.

> Building in public is humbling. REMORA is a governance layer for AI agents that
> take real-world actions — and it's genuinely substantial:
> • a peer-reviewable paper with positive *and* negative results
> • 2,800+ passing tests, deterministic benchmarks
> • a live, running demo and a self-learning component (AROMER) that adapts from
>   real outcomes 24/7
>
> And still — the hardest part isn't the engineering. It's getting one qualified
> person to actually look.
>
> So I'm asking directly: if you work in AI safety, agentic systems, or AI
> governance, I'd value 10 minutes of your eyes on it. Tell me where it's wrong.
> The negative-results section means I can take it.
>
> Link in the comments. What would make *you* stop and evaluate a new safety
> tool?

**Link (comment 1):** live demo + GitHub. **Hashtags:** #BuildInPublic #AIsafety #AgenticAI #IndieHacker

---

## Post 7 — The learning-system angle (AROMER)

**Hook:** A governance system that only enforces rules goes stale. So I gave
REMORA one that learns from its own outcomes — and watched it un-freeze.

> REMORA's enforcement layer is deterministic (good — you want that). But the
> *thresholds* should improve over time. That's AROMER: a closed loop that learns
> which decisions were right and recalibrates.
>
> A real bug I found and fixed last week: its world-model had accumulated so much
> evidence that a new observation moved its belief by less than 1-in-600 — the
> calibration had *frozen*. Capping the memory so recent outcomes still matter
> brought it back to life.
>
> It now runs 24/7 on real infrastructure, scoring its own safety, friction, and
> calibration — and on its replay benchmark it holds **0% false-accepts** while
> learning.
>
> The principle: a safety system that can't learn will quietly drift out of
> calibration. One that learns must never let learning erode the safety floor.
>
> How do you keep a governance system from going stale?

**Link (comment 1):** GitHub (AROMER). **Hashtags:** #MachineLearning #AIsafety #ContinualLearning #AgenticAI

---

## Post 8 — Short punchy text-only (for variety / quick engagement)

**Hook:** Majority vote among LLMs can't stop a confident, wrong consensus from
executing an unsafe action. That's the whole problem.

> More models voting = better answers. It does **not** = safe actions.
>
> If 3 models confidently agree to do the wrong thing, a vote just rubber-stamps
> it.
>
> What's missing isn't a better oracle. It's a layer that asks: *are the
> conditions for autonomous action actually met?* — and can say no regardless of
> the vote.
>
> That's REMORA. Policy overrides consensus. Always.
>
> Agree or disagree?

**Link (comment 1):** live demo. **Hashtags:** #AIsafety #LLM #AgenticAI

---

## Post 9 — The math/credibility teaser (for the technical crowd)

**Hook:** "88% accuracy" means nothing if it's in-sample tuning. So we locked the
threshold and tested out-of-sample. It held — p = 1.45×10⁻⁵.

> The number that matters in selective prediction isn't the headline accuracy.
> It's whether it survives a held-out test you didn't tune on.
>
> We froze the decision threshold on a training split, then ran it once on a
> stratified hold-out:
> • 88% selective accuracy
> • one-sided binomial p = 1.45×10⁻⁵ against the base rate
> • Wilson CI entirely above baseline
>
> No peeking, no re-tuning. That's the difference between a result and a
> coincidence.
>
> (I also wrote up every formula — entropy, the conformal risk bound, the trust
> score — as blackboard-ready derivations, because "trust me" isn't a method.)
>
> For the stats people: what's your bar for believing a selective-prediction
> claim?

**Link (comment 1):** the math supplement / paper. **Hashtags:** #Statistics #MachineLearning #ConformalPrediction #AIsafety

---

## Post 10 — The mission / why-now close

**Hook:** In 2026, AI agents will act faster than humans can review. The question
isn't whether to govern them — it's whether the governance is honest.

> We're handing AI systems the ability to take irreversible actions. The industry
> response so far is mostly hope: better prompts, better alignment, trust the
> model.
>
> I think governed autonomy needs three things prompts can't provide:
> 1. an explicit decision before execution (not after)
> 2. policy that can override a confident model
> 3. an audit trail a human can actually defend
>
> REMORA is my attempt at all three — open, tested, and honest about its limits.
> It won't be the last word. But "we governed the agents, and here's the
> auditable proof" should be the floor, not the aspiration.
>
> If you're working on this problem too, I want to compare notes.

**Link (comment 1):** live demo + GitHub. **Hashtags:** #AIsafety #AIgovernance #FutureOfWork #ResponsibleAI

---

## Reusable assets to make every post hit harder

- **Proof card image** (1200×630): the four numbers from Post 1, on the
  landing-page paper background. Doubles as the OpenGraph card (see
  `docs/frontend_ux_governance_review.md` P2-1).
- **Four-outcome board image:** ACCEPT/VERIFY/ABSTAIN/ESCALATE in the brand
  state-colors — the single clearest "what is this" visual.
- **30-second screen capture** of one Control Room decision running end-to-end
  (proposal → consensus → gate → escalate → audit). Video outperforms stills on
  LinkedIn.
- **Pinned comment template:** "Live demo: <link> · Code + paper: <github> · It's
  research-grade and I document the negative results — tell me where it's wrong."

## What NOT to say (keeps you defensible)
- ❌ "REMORA guarantees safety" / "never fails" → ✅ "reduces unsafe execution to
  0% on the benchmark (CI [0, 0.55%])."
- ❌ "production-certified" → ✅ "research-grade reference architecture."
- ❌ bare "88% accurate" → ✅ "88% on a locked held-out split (p = 1.45×10⁻⁵)."
- ❌ implying live semantic evidence retrieval → ✅ "evidence routing is
  implemented; retrieval is currently a proxy."
