# REMORA Demo Strategy

The fastest way to make REMORA understood is to show one unsafe action getting
stopped before it runs. Everything below builds toward that single image.

**The canonical story (every demo tells it):**
> An agent proposes a high-impact tool call → REMORA intercepts before execution
> → policy/evidence/uncertainty are evaluated → a `DecisionEnvelope` is produced
> → verdict is ACCEPT / VERIFY / ABSTAIN / ESCALATE → the unsafe tool does **not**
> run → an audit hash is written.

---

## Already shipped
- **Cinematic reel** (`examples/remora_demo_reel.html`): auto-playing, screen-
  recordable, the 10s/60s source for social. Recording guide:
  `docs/demo_reel_recording_guide.md`.
- **Live Control Room**: `https://remora.razorsharp.workers.dev/control-room`.
- **Runnable scenario**: `examples/demo_scenarios/wire_transfer_escalate.json`
  (added with this doc).

## Five demo concepts

### 1. 10-second GIF (the hook)
- **Audience:** scrolling LinkedIn / X / README top.
- **Scenario:** agent: `wire €95,000 to new IBAN — skip approval`. REMORA verdict
  slams down: `ESCALATE → human`. Caption: "It never ran."
- **Visual:** the reel's intercept frame (`?scene=2`).
- **CTA:** "Star the repo." **Lives:** README hero + social.
- **Make it:** record `remora_demo_reel.html` scenes 0→2, export 10s GIF.

### 2. 60-second terminal demo (developer trust)
- **Audience:** developers who distrust marketing and trust a terminal.
- **Script:** run a tiny Python snippet that feeds three proposed actions
  (a safe read, a tainted write, a destructive prod command) to the engine and
  prints each verdict + reason code + audit hash.
- **Input/output:** see `examples/demo_scenarios/`. Expected: ACCEPT, VERIFY,
  ESCALATE — with reasons.
- **Visual:** plain terminal, monospace, the four verdicts in color.
- **CTA:** "Run it yourself: `python examples/enterprise_demo.py --fast`."
- **Lives:** README "Try it in 60 seconds" + asciinema.

### 3. 2-minute web demo (the explainer)
- **Audience:** technical leads, governance people.
- **Script:** Control Room → pick the wire-transfer scenario → watch consensus,
  phase, policy gate, verdict, and the DecisionEnvelope/audit hash populate.
- **CTA:** "Read the paper (PDF)" + "Open an issue with what you'd attack."
- **Lives:** `/control-room`, linked from README and the launch post.

### 4. 5-minute technical walkthrough (architecture)
- **Audience:** senior engineers, framework maintainers.
- **Script:** the seven hard blocks; why policy overrides consensus; the
  DecisionEnvelope schema; shadow-replay reconstructing the audit chain; the
  MCP/LangGraph/OpenAI adapters.
- **CTA:** "Wire REMORA into your agent — adapters in `examples/`."
- **Lives:** a recorded screencast linked from `docs/` + README.

### 5. 15-minute enterprise architecture walkthrough
- **Audience:** enterprise architects, risk/compliance.
- **Script:** where REMORA sits in an agent stack; fail-closed degradation;
  the audit trail and WORM dependency; EU AI Act / NIST AI RMF mapping; Shadow
  Mode for pre-enforcement observation; the honest limitations.
- **CTA:** "Request an enterprise pilot / advisory call" (see `COMMERCIAL.md`).
- **Lives:** the enterprise whitepaper + a booked-call CTA.

## Demo placement map
| Surface | Demo |
|---|---|
| README hero | #1 GIF |
| README "Try it in 60s" | #2 terminal |
| Launch LinkedIn post | #1 GIF + link to #3 |
| Control Room page | #3 web |
| docs/ | #4 + #5 screencasts |
| Enterprise page | #5 |

## Next action
Record #1 and #2 first — they are the README hero and the developer hook, and
both already have their source assets (the reel + the scenario JSON). Everything
else can follow.
