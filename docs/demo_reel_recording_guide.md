# REMORA Demo Reel — Recording & Publishing Guide

The reel is `examples/remora_demo_reel.html` — a self-contained, auto-playing
motion sequence (no dependencies, works offline). It plays a ~45-second story and
loops:

1. **Hook** — an AI agent decides to wire €95,000, skip approval (terminal).
2. **Stakes** — "a wrong sentence is embarrassing; a wrong action is irreversible."
3. **Intercept** — REMORA evaluates it: consensus → critical phase → policy hard
   block → **ESCALATE → human**, hash-chained.
4. **Four outcomes** — ACCEPT / VERIFY / ABSTAIN / ESCALATE; "policy overrides
   consensus, always."
5. **Proof** — 0% unsafe [0,0.55%] · 88% held-out (p=1.45×10⁻⁵) · 99.9% conformal
   · SHA-256 audit.
6. **CTA** — `github.com/darklordVirtual/REMORA`.

Every on-screen number is artifact-backed with its caveat intact — it will not
embarrass you in front of a technical audience.

---

## Fastest path to an MP4 (≈10 minutes)

### 1. Open the reel full-screen
```
# from the repo root
cd examples
python -m http.server 8731
# then open in Chrome:
http://127.0.0.1:8731/remora_demo_reel.html
```
Press **F** for fullscreen (or the browser's own fullscreen). The reel auto-plays
and loops. Press **R** to restart from the hook, **Space** to pause.

> Use Chrome at 100% zoom. The stage is a centered square that scales to the
> window — for a square video, make the window roughly square; for 16:9, widen it
> (the square stage stays centered on a black field, which looks intentional).

### 2. Record it
**Windows:** Press `Win+G` (Xbox Game Bar) → record, **or** use OBS Studio (free).
**macOS:** `Cmd+Shift+5` → record selected portion, **or** OBS.
**Best quality:** OBS Studio → add a "Window Capture" of the Chrome tab → record
at **1080×1080** (square) or **1920×1080**, 30 fps, MP4.

Record **one clean loop** (~45 s). Start the capture, press **R** in the browser
to reset to the hook, let it run once to the CTA, stop.

### 3. Trim & export
- Trim to start exactly on the hook and end on the CTA (hold the CTA ~2–3 s).
- Export **MP4, H.264, 30 fps**.
- LinkedIn limits: up to 10 min / 5 GB — you are nowhere near; keep it ~45 s.

---

## Format choices (pick per goal)

| Aspect | Pixels | Best for |
|---|---|---|
| **1:1 square** | 1080×1080 | LinkedIn feed default — recommended, most mobile real estate |
| **4:5 portrait** | 1080×1350 | Even more feed height on mobile |
| **16:9** | 1920×1080 | Embedding on the site / YouTube / decks |

The reel's square stage centers cleanly inside any of these. For 1:1, size the
Chrome window square before recording.

---

## Export still frames (thumbnail / OpenGraph card / carousel)

The reel supports a **still-frame mode** — append `?scene=N` (N = 0–5) to freeze
on one fully-revealed scene, then screenshot at any resolution:

```
http://127.0.0.1:8731/remora_demo_reel.html?scene=4   # the proof numbers
http://127.0.0.1:8731/remora_demo_reel.html?scene=3   # the four outcomes
http://127.0.0.1:8731/remora_demo_reel.html?scene=2   # ESCALATE climax
```

- **Best thumbnail / OG card:** `?scene=4` (proof) or `?scene=2` (ESCALATE). These
  double as the `og:image` recommended in `docs/frontend_ux_governance_review.md`
  (P2-1) — export at 1200×630.
- **LinkedIn carousel (PDF):** export scenes 0→5 as stills, drop into a 6-page PDF
  — a strong no-video alternative that also performs well on LinkedIn.

To get a crisp 1200×630, set the browser window to ~1260×690 and screenshot the
stage, or use Chrome DevTools device toolbar at a custom size.

---

## The first 3 seconds (this decides everything)

On LinkedIn, video autoplays **muted** while people scroll. You win or lose in the
first frames. The reel's hook is built for this — an agent about to wire €95k with
"skip approval." Reinforce it:

- **Add a burned-in caption** on the first 3 seconds: e.g. *"An AI agent just tried
  to wire €95,000. Watch what stopped it."* (Most people watch muted — captions are
  not optional.)
- Keep the **danger frame** (red command) on screen long enough to read while
  scrolling — the current ~4.5 s is tuned for that.
- The reel has **no audio** by design (so it's safe muted). If you add music, use a
  low, tense bed — never speech you'd need sound to follow.

> Optional: add SRT/burned captions throughout with a tool like CapCut or the
> built-in editors. The on-screen text is already large, but a caption track widens
> reach and accessibility.

---

## Publishing on LinkedIn (mechanics that matter)

1. **Native upload the video** — do not post a YouTube link. LinkedIn suppresses
   off-platform video; native autoplays in feed.
2. **Hook in the first line of the post**, before the "…see more" cut. Pair the
   reel with **Post 1 or Post 2** from `docs/linkedin_promotion_posts.md`
   (the "0% unsafe" hook or the trust-inversion story).
3. **Put the GitHub link in the FIRST COMMENT, not the post body** — links in the
   body cut reach. Pin that comment.
4. Post when your audience is active (typically Tue–Thu, mornings CET for a
   European technical crowd).
5. **Reply to every comment in the first hour** — early engagement drives the
   algorithm. End the post with a question (the drafts already do).
6. Add a **custom thumbnail** (export `?scene=2` or `?scene=4`) so the pre-play
   frame is the dramatic one, not a random middle frame.

### Suggested pairing
- **Video + Post 1** ("0% unsafe… here's the catch I have to tell you about") →
  the reel *shows* the catch (the ESCALATE), the post tells it honestly.
- First comment: `Live demo: https://remora.razorsharp.workers.dev · Code + paper:
  https://github.com/darklordVirtual/REMORA — it's research-grade and I publish the
  negative results. Tell me where it's wrong.`

---

## Tuning the reel (optional)

All in `examples/remora_demo_reel.html`:
- **Scene durations:** the `TL` array (ms per scene) near the bottom of the script.
- **The agent command:** the `CMD` constant (keep it visceral and plausible).
- **Proof numbers:** the `PROOF` array in the markup — *only* edit these to match a
  committed artifact, and keep the caveat line (CLAUDE.md).
- **Colors/fonts:** the `:root` CSS variables (brand serif + mono, signal blue, the
  four state colors).

## Honesty guardrail (don't undo this)
The reel keeps the caveats on every number (`Wilson CI [0, 0.55%]`, `held-out`,
`p = 1.45×10⁻⁵`). Do not crop them out to make a punchier frame — the technical
audience you want will check, and the honest version is the credible one.
