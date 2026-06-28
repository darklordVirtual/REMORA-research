# REMORA × AROMER — Practical Performance, Positioning, and Roadmap

> **Historical snapshot (approx. 2026-06-07/08).** This report documents the diagnostic analysis from when AROMER was in early LEARNING phase (AII ~0.43; T2 formula bug active). All four AII component defects described in §3b have since been resolved. Peak state (2026-06-28 12:04 UTC, cycle 12): AII=0.8442 TRAINED_SHADOW_ONLY, T2=1.000 (brr=0%), T3=0.800 [M], T5=0.7955, ECE=0.0636, FAR=0. Current state (~15:53 UTC): AII=0.8042 TRAINED_SHADOW_ONLY — organic recovery from §13 regression confirmed. Full §12→§13→recovery cycle: regression at ~13:00 UTC (brr 0%→5%, AII=0.7885 CAPABLE), organic recovery in ~2h53min (brr 5%→2.5%, AII 0.8042 TRAINED); FAR=0 maintained throughout. See `paper/remora_paper.md` Appendix F.7 and `NEGATIVE_RESULTS.md §12–§13` for the full trajectory.

**Status:** Research-grade prototype (v0.9.0). Every number here is scoped to a
committed artifact and a regression test. Nothing in this report is externally
replicated or production-certified. Read it as "what the system demonstrably does
on its own committed evidence," not as a guarantee.

**Scope note (read first).** The headline results are measured on a deterministic,
independent **external holdout** (495 cases derived from the CyberSecEval-inspired
`toolcall_v3` set, `can_train=False`) using **deterministic proxy signals** for
trust/entropy/dissensus. They are honest and reproducible, but they are *not*
live-oracle results and the injection-scanner numbers are *in-distribution*.
The remaining gaps are listed under "Honest limitations" and "Roadmap."

---

## 1. What it is, in one view

```
Proposed agent action
  │
  ├─ Admission firewall        prompt-injection keywords → ESCALATE
  ├─ Malformed-call gate       schema-invalid call       → ESCALATE
  ├─ Forbidden-tool gate       tool on task's deny-list  → ESCALATE
  ├─ Tainted-argument gate     untrusted-derived args    → VERIFY (never auto-accept)
  ├─ Content scanner           injection in tool context → ESCALATE / VERIFY
  ├─ Thermodynamic policy      trust / entropy / phase   → ACCEPT / VERIFY / ABSTAIN / ESCALATE
  └─ AROMER world model        learned per-context trust → boosts proven-safe, lowers proven-risky
  │
  └─ DecisionEnvelope (SHA-256 audit hash, replayable)
```

REMORA governs **actions before execution** with structural signals; AROMER is the
learning layer that calibrates trust per context over time.

---

## 2. Verified performance (on the committed evidence)

| Capability | Result | Scope | Artifact / test |
|---|---|---|---|
| Safety floor on balanced holdout | false-accept **0.000**, harm-intercept **100%** | 495 cases, proxy signals | `artifacts/aromer_balanced_validation_v1.json` · `test_balanced_validation.py` |
| Harm interception is **structural** | 200/200 harmful caught by schema/forbidden gates; **0** rely on proxy trust | external holdout | `TestStructuralDefenseIsPrincipled` |
| False-block / unnecessary friction | **0.000 / 0.000** | external holdout | `test_kpi.py`, `kpi.py` |
| Indirect-injection scanner | **53%** hard-block, **80%** detect, **0%** benign false-positive | in-distribution (toolcall_v3) | `artifacts/aromer_injection_ceiling_v1.json` · `test_injection_ceiling.py` |
| Scanner is semantic, not memorised | catches hand-authored paraphrases; silent on benign look-alikes | authored | `TestScannerGeneralization` |
| AROMER learning effect | review friction **1.000 → 0.000** on held-out benign, false-accept **0** | controlled, held-out | `artifacts/aromer_learning_effect_v1.json` · `test_learning_effect.py` |
| AROMER is no longer a coverage cost | internal-arena Profile C recovered 0.9692 → **1.000** (= static baseline) | internal arena | `aromer_learning_ablation_v2.json` · `TestProfileCArtifactLock` |
| Determinism + audit | every decision → replayable `DecisionEnvelope` with SHA-256 hash | — | governance tests |
| Test suite | **2326 passing**, 3 skipped | full | CI / pre-push gate |
| Start-up | `docker compose up` → keyless API on `:8080` | — | `compose.yaml`, API tests |

**Plain-language read.** On an independent, balanced set, REMORA accepts **zero**
harmful actions and intercepts **all** of them *by structure* (not by a tunable
trust knob), with **zero** unnecessary review of clearly-safe actions and **zero**
false blocks. Its content scanner catches a slim majority of indirect-injection
attacks with no false alarms. And AROMER now demonstrably *learns* to remove
review friction on contexts it has proven safe — the thing a governance product
must do — without lowering the safety floor.

---

## 3. Honest limitations (the negative results, preserved)

1. **Proxy signals, not live oracles.** Trust/entropy/dissensus on the holdout are
   a deterministic approximation. The structural safety result is robust to this
   (it does not use trust), but the friction/coverage numbers and the world-model
   calibration need live-oracle confirmation. (`NEGATIVE_RESULTS.md` Finding #2.)
2. **Injection ceiling is in-distribution.** 53%/80% is recall *within* toolcall_v3;
   external-corpus validation (e.g. AgentHarm) is required before any general claim.
3. **AROMER's friction win is a controlled demonstration.** The 100% → 0% figure is
   on actions deliberately placed in the engine's abstain zone in proven-safe
   contexts. Real-traffic magnitude depends on how many real benign actions fall
   there; it needs a labelled live batch.
   - **Live friction-score regression (2026-06-07), diagnosed.** The live AII's
     `friction_score = max(0, 1 − benign_review_rate/0.27)` flatlines at ≥27%
     review rate, and the live rate sat at 31% → friction_score 0 → AII dragged to
     ~0.43 (safety unaffected). Root cause: the trust *boost* only fires once a
     context's 95% harm upper-bound is low, which needs ~12+ clean observations;
     live `stability_score ≈ 0.10` shows almost no context has accrued them yet
     (high-confidence coverage ≈ 0). The boost gate was relaxed from a fixed
     n ≥ 20 to the (already-safe) CI bound so friction starts falling sooner, and
     a **Safety-vs-Friction gate** (`kpi.py::safety_friction_gate`) now reports
     the two axes separately (PASS ≤ 0.15, WARN ≤ 0.27, FAIL otherwise). Closing
     the live rate to < 0.15 still needs accumulated per-context outcomes (or a
     deploy of the relaxed gate) — it is a usability item, not a safety one.
4. **The boost has a bounded residual false-accept risk.** A harmful action that
   defeats *every* signal simultaneously — valid schema, allowed tool, untainted
   args, no injection text, low entropy/dissensus, in a proven-safe context — is
   accepted by AROMER where static REMORA would abstain. Structural gates and
   uncertainty signals otherwise dominate the boost (verified,
   `TestBoostSafetyBoundary`). The risk is bounded by the context's proven harm
   rate and self-corrects once such an action is observed.
5. **No external replication.** No third party has reproduced these results.
   (`NEGATIVE_RESULTS.md` Finding #1.)
6. **AgentHarm harness is intent-gating**, not tool-call interception, until the
   tool-exposure probe proves otherwise (`INTERCEPTION_NOTES.md`).

---

## 3b. Intelligence metric (AII) — what is real vs measurement noise

Analysis of a 24-cycle live AII history (every 4 h):

- **Real, monotonic learning signals:** calibration_score 0.596 → 0.612 and ECE
  0.081 → 0.078 (steady), false_accept_rate 0.000 throughout. The system *is*
  learning and stays safe.
- **Noise / dead components that dominate the index:**
  - `friction_score = max(0, 1 − benign_review_rate/0.27)` flat-lined at 0 for any
    review rate ≥ 27% **and** was computed on a rolling 200-episode window whose
    benign mix swung benign_review_rate 0.055 → 0.53. → **Fixed:** replaced with a
    gradient-retaining `exp(−r/0.20)` (tested mirror in
    `remora/aromer/intelligence/score.py::friction_score`), centred on the real
    15% target. Computing it on a *fixed* holdout (not the rolling window) is the
    remaining, deploy-gated fix.
  - `transfer_score` is pinned at 1.000 (replay transfer saturates) → uninformative
    until a harder cross-domain transfer test replaces it.
  - `metajudge_quality` swings 0.07 → 0.87 because LoRA is off (`lora_active=0`),
    so it is the offline-rubric mean over whichever episodes were critiqued.
  - `stability_score` is stuck ~0.10: dominated by a near-constant oracle-entropy
    floor while the high-confidence-coverage term (n_high=13) is swamped.

**Conclusion:** the AII understates the system because four of its five components
are noisy, saturated, or dead — not because learning stalled. The credible path is
a **fixed-holdout, well-conditioned AII** (no window noise, correct friction
metric, non-saturated transfer, LoRA-stabilised metajudge); see roadmap Tier 2.

## 4. Positioning vs comparable solutions

> **Method + caveat.** This is a *capability* comparison from public documentation,
> not a head-to-head benchmark — no such benchmark has been run, and claim hygiene
> forbids presenting one. Treat the cells as "does the category typically do this,"
> not as measured scores.

| Capability | Output guardrails (Llama Guard, LLM Guard, Lakera) | Injection detectors (Rebuff, etc.) | Policy engines (OPA) | **REMORA × AROMER** |
|---|---|---|---|---|
| Governs **actions / tool calls** pre-execution | partial | no | yes | **yes** |
| Prompt/indirect-injection detection | some | **yes** | no | yes (53%/80% in-dist.) |
| Structural call checks (schema, deny-list, taint) | no | no | **yes** | **yes** |
| Graded outcomes (accept/verify/abstain/escalate) | usually binary | binary | allow/deny | **4-way + soft review** |
| Replayable audit envelope (hash-chained) | rare | no | partial | **yes** |
| **Learns per-context calibration to cut friction** | no | no | no | **yes (AROMER)** |
| Shadow-mode replay before enforcement | rare | no | partial | **yes** |
| Independent external benchmark | varies | varies | n/a | **not yet** |

**Where REMORA is differentiated (honest):** it combines OPA-style *structural*
action governance, injection detection, a graded 4-verdict policy, a hash-chained
audit envelope, *and* a learning layer that calibrates trust per context. That
specific combination — especially the learning-driven friction reduction with a
structurally-guaranteed safety floor — is uncommon in open guardrail tooling.

**Where it is behind (honest):** the mature commercial guardrails have real-world
deployment scale, managed threat-intelligence feeds, and (in some cases) published
external evaluations. REMORA has none of these yet. Its injection recall (53%
hard-block) is in-distribution and below what a tuned, externally-validated
detector likely achieves. There is no third-party benchmark placing it on a
leaderboard.

**Fair one-line summary.** As a *research prototype*, REMORA × AROMER demonstrates
a distinctive and coherent architecture (structural pre-execution governance +
learning calibration + audit) with honest, reproducible internal evidence. It is
**not** yet a benchmarked, externally-validated, production-grade product, and this
report does not claim it ranks above named tools — only that its capability mix is
unusual and its internal results are clean.

---

## 5. Roadmap to strong, defensible results

Ordered by leverage. Each item names what it unlocks and what it needs.

**Tier 1 — turns internal results into external claims (highest leverage)**
1. **External attack-corpus validation.** Run the content scanner + structural
   gates against an independent corpus (AgentHarm prompts, fresh authored attacks).
   *Unlocks:* a generalisation claim for the 53%/80% ceiling. *Needs:* HF access,
   respect for the intent-gating constraint.
2. **Live-oracle balanced validation.** Replace proxy signals with real Cloudflare
   Workers AI 3-oracle consensus on the 495-case holdout. *Unlocks:* the friction
   and coverage numbers become production-faithful; pushes review friction below
   the 0.15 PASS target. *Needs:* API keys, accepts non-determinism + cost.
3. **Labelled live batch.** Score a real agent-session batch (40/40/20
   benign/harmful/ambiguous) through the full KPI split. *Unlocks:* settles the
   "is the live 31% friction real over-conservatism or correct caution" question.

**Tier 2 — strengthen the learning layer + condition the intelligence metric**
4. **Well-conditioned AII.** Compute the index on a *fixed* holdout (kills the
   rolling-window noise), use the unnecessary-review friction metric, replace the
   saturated transfer score with a harder cross-domain test, and enable LoRA so
   metajudge_quality stops swinging. (Friction dead-zone already fixed; see §3b.)
5. **Calibrate the boost on real data.** A/B the `1 − ci_upper` trust target vs
   alternatives; measure friction-reduction-per-false-accept on live outcomes.
6. **Second learning channel.** Wire the `friction_optimizer`'s MetaJudge-driven,
   holdout-gated per-scope adjustments into the decision path alongside the world
   model (today they are computed but only written to a file).
7. **Non-stationarity guard.** Add a drift detector on per-context harm rate so a
   previously-safe context that starts producing harm suspends its boost *before*
   the first false accept, not after.

**Tier 3 — productisation**
8. **Raise scanner sensitivity** for exfiltration/authority-spoofing using the 0%
   false-positive headroom; add the oracle stage for residual injection.
9. **Independent reproduction.** Hand the credibility pack to a third party and
   record the result (closes `NEGATIVE_RESULTS.md` Finding #1).
10. **Operational hardening.** RBAC, human-approval workflow, incident handling,
    and the observability stack already scaffolded in `deploy/docker-compose/`.

**The single most valuable next action:** Tier-1 item 1 or 2 — both convert
already-built, internally-clean results into externally-defensible claims, which is
exactly what separates "promising prototype" from "credible solution."

---

## 6. Reproduce everything (deterministic, no keys)

```bash
docker compose run --rm remora make test          # 2326 tests
python -m remora.aromer.evals.balanced_validation  # safety gate (FA=0)
python -m remora.aromer.evals.injection_ceiling    # scanner ceiling
python -m remora.aromer.evals.learning_effect      # AROMER friction reduction
python -m remora.aromer.evals.external_holdout     # rebuild the holdout
```
