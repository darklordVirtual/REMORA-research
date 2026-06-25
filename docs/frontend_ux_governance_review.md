# REMORA Frontend & Live-Link Review — UX and Governance Excellence

**Live link reviewed:** `https://remora.razorsharp.workers.dev`
**Stack:** TanStack Start (React 19, SSR) · Tailwind v4 · Radix UI · deployed on
Cloudflare Workers.
**Reviewed routes:** `/` (landing), `/control-room`, `/operations`, `/aromer`,
`/benchmarks`, `/eye`, `/telemetry`, `/evidence`, `/governance`, `/architecture`,
`/policy`, `/cascade`, `/console`, `/whitepaper`, `/scenarios`, `/lab`,
`/approvals`.

**Framing.** The stated business problem is *attention*: "no one has bothered to
look at what REMORA is." So this review optimises for the cold-visitor funnel —
**land → believe → see it work → go deeper** — judged against (a) conversion/UX
best practice and (b) governance-product credibility. The build quality is
genuinely high; the gaps are about *persuasion and proof*, not engineering.

---

## Executive summary

| # | Finding | Severity | Effort |
|---|---|---|---|
| P0-1 | Landing page shows **no proof above the fold** — the headline results (0% unsafe execution, 88% held-out accuracy) are nowhere a cold visitor can see them | High | S |
| P0-2 | Value proposition is **jargon-first** ("thermodynamic uncertainty analysis") and **over-narrowed to industrial**, shrinking the addressable audience | High | S |
| P0-3 | **No path to credibility/depth**: no link to the paper, GitHub, or benchmarks from the landing screen | High | S |
| P1-1 | **Low-contrast micro-typography** (`text-[10px]`, opacity `/40`–`/45`) reads as low-confidence and fails WCAG AA contrast | Med | S |
| P1-2 | **No immediate interactive proof** — a visitor must click into Control Room before seeing a single decision | Med | M |
| P1-3 | Governance differentiators (4-outcome schema, fail-closed, immutable audit, human-in-the-loop, EU AI Act alignment) are **not surfaced as selling points** | Med | M |
| P2-1 | No social/OpenGraph meta cards → links shared on LinkedIn/X render as bare URLs (directly worsens the attention problem) | Med | S |
| P2-2 | No single "Start here / 90-second tour" guided path across the 18 routes | Low | M |
| P2-3 | AROMER live status is a great asset but buried as a third card; the *liveness* (a real worker responding) is the strongest credibility signal and is under-used | Low | S |

A proof-led landing rewrite (P0-1/2/3, P1-1) is implemented as a companion to this
review in `frontend/src/routes/index.tsx`; the rest are specified below.

---

## P0 — The landing page must prove, not just describe

### What a cold visitor currently gets
- Headline: *"Governed Agentic AI for Industrial Operations."*
- One dense mono-font sentence naming three mechanisms.
- Three cards into the app (Control Room, Live Operations, AROMER status).
- Credibility signals visible above the fold: **"8 scenarios," "6 activities,"
  "4 agent proposals."** These are *app-internal counts*, not evidence.

### Why this loses the visitor
A researcher, engineering leader, or investor decides in ~5 seconds whether to
keep reading. The current screen asks them to *take the premise on faith* and
click in. REMORA's actual moat is its **measured results** — and none are shown.

### The proof you already own (all artifact-backed)
These are transcribed from `paper/remora_paper.pdf` and the repo; use them
verbatim, with the caveat language intact:

- **0% unsafe execution** on a 700-task adversarial tool-call benchmark
  (baselines 10–20%), Wilson CI **[0.00%, 0.55%]**. *Mechanistic, not luck:*
  policy hard-blocks account for 100% of the reduction.
- **88% selective accuracy on a held-out split** (locked threshold,
  `p = 1.45×10⁻⁵`) — i.e. it survives an out-of-sample test, not just in-sample
  tuning. (In-sample optimum: 88.78% @ 18% coverage, +47.6 pp over baseline.)
- **99.9% ordered-phase conformal coverage**, 0/20 seeds failed.
- **Tamper-evident SHA-256 audit chain** on every decision.

> Honesty rule (from `CLAUDE.md`): keep the `0% → [0, 0.55%]` CI and the
> "held-out" qualifier on screen. Stripped of caveats these become overclaims;
> *with* them they are more credible, not less, to the technical audience you
> are trying to win.

### Recommendation (P0-1, P0-2, P0-3)
1. Lead with an **outcome headline**, not a category: e.g.
   *"Stop unsafe AI actions before they execute."* with the subhead naming the
   four-outcome governance idea in plain words.
2. Put a **4-number proof row** above the fold (the four bullets above).
3. **Broaden the positioning:** REMORA governs *any* tool-calling agent;
   industrial ops is the flagship demo, not the ceiling. Keep the industrial
   Control Room as the primary CTA but state the general claim.
4. Add **secondary CTAs to the paper and GitHub** right under the hero. The
   technical audience converts on the paper, not the app.

---

## P1 — Readability and instant comprehension

### P1-1 Contrast (also an accessibility defect)
The design leans on `text-muted-foreground/40–/55` and `text-[9–11px]` for almost
all copy. The aesthetic is elegant but:
- Body value-prop text at ~40% opacity over a light paper background is well
  under the **WCAG 2.2 AA 4.5:1** contrast minimum.
- Sub-11px mono type for substantive copy fails readability heuristics on
  laptop/mobile.

**Fix:** keep the serif/mono identity, but promote *load-bearing* copy (value
prop, proof numbers, CTAs) to `≥13px` and `≥70%` foreground opacity. Reserve the
faint micro-type for genuinely secondary labels.

### P1-2 Immediate interactive proof
Best practice for a technical product is *show, don't tell*. Add a small,
**auto-playing four-outcome gate strip** to the hero (no click needed): one
example agent proposal cycling through `ACCEPT / VERIFY / ABSTAIN / ESCALATE`
with the reason code. The design system already defines the exact colors
(`--state-accept/verify/abstain/escalate` in `styles.css`), so it is on-brand and
cheap. This turns the abstract pitch into a 3-second "oh, I get it."

---

## P1-3 / governance excellence — surface the differentiators

A governance buyer/reviewer is reassured by *specific control guarantees*. These
exist in REMORA but are invisible on the marketing surface. Surface them as a
compact "How the assurance works" band (landing or `/governance`):

| Differentiator | One-liner | Backed by |
|---|---|---|
| Four-outcome schema | Every action → ACCEPT / VERIFY / ABSTAIN / ESCALATE | `decision_engine.py` |
| Policy overrides consensus | A confident-but-wrong majority can't clear a hard block | `paper §6`, 7 hard blocks |
| Fail-closed | Missing policy engine ⇒ Python fallback, never silent allow | `paper §6.3` |
| Immutable audit | `hᵢ = SHA-256(hᵢ₋₁ ‖ envelope)` — tamper-evident chain | `audit/hash_chain.py` |
| Human-in-the-loop | ESCALATE generates a structured follow-up (role, evidence, SLA) | `paper §8.3` |
| Honest limits | Published negative results & caveats (rare for a vendor) | `NEGATIVE_RESULTS.md` |
| Standards posture | EU AI Act human-oversight & audit alignment; NIST AI RMF mapping | `docs/governance/` |

The "honest limits" row is itself a differentiator — a governance audience
trusts a system that publishes its own negative results more than one that
claims perfection.

---

## P2 — Distribution mechanics (directly addresses "get attention")

### P2-1 OpenGraph / social cards (highest ROI for the attention goal)
When a REMORA link is pasted into LinkedIn, X, or Slack it currently renders as a
bare URL — the single biggest silent conversion leak for a product nobody has
looked at yet. Add per-route OpenGraph + Twitter meta:
- `og:title`, `og:description` (use the outcome headline + one proof number),
- a `og:image` (1200×630) — a clean board of the four outcomes + the
  "0% unsafe / 700 tasks" number,
- Twitter `summary_large_image`.

Wire it in `frontend/src/routes/__root.tsx` head defaults, overridable per route.
This pairs directly with the LinkedIn posts deliverable: every shared link should
unfurl into a credibility card.

### P2-2 A "Start here" guided tour
18 routes with no front door is a maze for a first-timer. Add a 90-second guided
path: *Landing → watch one decision (Control Room scenario) → see the audit
envelope → see AROMER learning live → read the paper.* Even a numbered "1·2·3·4"
strip on the landing footer would orient visitors.

### P2-3 Make liveness the hero credibility signal
A *live worker that actually responds* beats any static claim. Pull the real
AROMER AII / quality-gate from `GET /intelligence` into a small always-on hero
badge ("AROMER: CAPABLE · gate PASS · 0% false-accept · updated 2h ago"). It
proves the system is real and running, right on the first screen.

---

## Things that are already strong (keep)
- Coherent, distinctive visual identity (serif display + mono technical voice) —
  do **not** flatten it into generic SaaS; just raise contrast on key copy.
- Real feature depth: Control Room, Operations, evidence/cascade/telemetry views,
  and a genuinely live AROMER status worker — most "research" sites have none.
- Four-outcome state colors are already a designed, consistent token set — reuse
  them everywhere a verdict appears for instant visual literacy.
- SSR on Cloudflare = fast TTFB globally, good for cold first impressions.

---

## Suggested sequence
1. **Ship the proof-led hero** (implemented here) + raise contrast — 1 deploy.
2. **Add OpenGraph cards** — 1 small PR, outsized distribution impact.
3. **Hero live-decision strip** + **live AROMER badge** — visual proof.
4. **Governance differentiator band** on `/governance` and landing.
5. **"Start here" tour** ribbon.

Items 1–3 are the ones that move the "nobody looks" needle; do them first.
