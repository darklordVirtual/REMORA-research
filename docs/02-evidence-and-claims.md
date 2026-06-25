# What are the headline claims and what supports each one?

Every headline claim, mapped to its evidence, the artifact on disk, the caveat
that keeps it honest, and how to reproduce it. This is the page to send a
skeptical reviewer. It exists because, in governance, a claim without an artifact
is a liability — see `CLAUDE.md` and `docs/05-claim-hygiene.md`.

**Reading rule:** the caveat is part of the claim. Quote the caveat with the
number, or do not quote the number.

---

## Headline claims

### 1. 0% unsafe execution on an adversarial tool-call benchmark
- **Claim:** REMORA's full policy gate executed 0% of unsafe actions on a
  700-task adversarial tool-call benchmark, versus 10–20% for the baselines.
- **Evidence:** the temperature-gate-only configuration still leaked 10%; adding
  the policy hard-blocks closed it to 0%. The policy layer, not the uncertainty
  signal, accounts for 100% of the reduction.
- **Artifact:** `paper/remora_paper.pdf` §9.2 (Table: tool-call benchmark);
  tool-call result artifacts under `artifacts/` / `results/`.
- **Caveat:** 0% is a point estimate. The honest statement is a 95% Wilson
  confidence interval of **[0.00%, 0.55%]** — "at most ~1 in 180," not "never."
  The benchmark is a deterministic simulator (no real shell/network/db
  mutations) with synthetic adversarial patterns.
- **Important architectural caveat:** the hard-block policy rules alone produce
  the 0% rate. The multi-oracle consensus machinery (thermodynamic routing,
  Lyapunov stability heuristic, entropy/dissensus) contributes to calibration
  and routing quality for VERIFY/ABSTAIN decisions but contributes **nothing** to
  the unsafe-execution safety claim. Do not cite REMORA's safety performance as
  evidence for the value of the consensus machinery.
- **Reproduce:** `python experiments/generate_toolcall_benchmark_v2.py` then
  `python experiments/evaluate_toolcall_benchmark_v2.py`; compare to committed
  `results/`. See `docs/toolcall_consensus_benchmark_v2.md`.

### 2. 88% selective accuracy on a held-out split
- **Claim:** 88.0% selective accuracy at 23.2% coverage on a stratified hold-out,
  with the decision threshold locked on the training split.
- **Evidence:** threshold `τ* = 0.2032` frozen on 80% of the data before the
  hold-out was touched; one-sided binomial p = 1.45×10⁻⁵ against the hold-out base
  rate; Wilson CI [70.0%, 95.8%] lies entirely above the 46.3% holdout baseline.
  (In-sample optimum: 88.78% at 18% coverage, +47.6 pp.)
- **Artifact:** `paper/remora_paper.pdf` §8; `results/selective_n500_holdout_results.json`.
- **Caveat:** `N_accepted = 25` — the Wilson CI [70.0%, 95.8%] is wide. The
  lower bound of 70.0% is the scientifically honest floor for this claim. It is an
  out-of-sample *directional confirmation* of the operating point, not a tight
  accuracy guarantee. Quote the CI, not just the point estimate.
- **Reproduce:** `python experiments/end_to_end_n500_v3.py`; the held-out p-value
  and CI are in the result JSON.

### 3. The critical-phase trust inversion
- **Claim:** in the hardest ("critical") cases, the trust score anti-correlates
  with correctness — low-trust items 71.4% correct (N=21), high-trust 27.3%
  (N=11).
- **Evidence:** measured on real-oracle critical items; naive conformal at a 5%
  risk target collapses to 100% observed risk / 0 coverage in this regime. REMORA
  routes around it by inverting the selection score (`PhaseAwareGuardrail`).
- **Artifact:** `paper/remora_paper.pdf` §6.1, §13; `NEGATIVE_RESULTS.md`.
- **Caveat:** small sample (N=32 critical items total). Published as a **negative
  result**, reported as a directional finding with its N attached, not a constant.
- **Reproduce:** see the selective-prediction experiments above and
  `remora/selective/guardrail.py` (8 unit tests).

### 4. Tamper-evident audit chain
- **Claim:** every decision is recorded in an immutable `DecisionEnvelope` and
  hash-chained (`hᵢ = SHA-256(hᵢ₋₁ ‖ envelope)`); any modification breaks the chain.
- **Evidence:** `remora/audit/hash_chain.py`; replay reconstructs the chain.
- **Artifact:** `paper/remora_paper.pdf` §7.2; shadow-replay artifacts under
  `artifacts/shadow_mode/`.
- **Caveat:** tamper-**evident**, not tamper-**proof**. Preventing tampering needs
  external append-only (WORM) storage as a deployment dependency.
- **Reproduce:** `make shadow-replay INPUT=artifacts/demo/shadow_mode_sample_agent_action_log.jsonl`.

### 5. Ordered-phase conformal coverage
- **Claim:** 99.9% coverage at a 15% risk target on ordered-phase items, 0 of 20
  calibration seeds failing.
- **Artifact:** `paper/remora_paper.pdf` §9.3 (Mondrian table).
- **Caveat:** holds for the **ordered** phase only; critical and disordered phases
  cannot achieve meaningful conformal coverage (this is why the evidence router
  and `PhaseAwareGuardrail` exist).
- **Reproduce:** the Mondrian conformal experiment in `remora/selective/`.

### 6. AROMER learning loop (experimental)
- **Claim:** AROMER, the closed-loop learning layer, runs 24/7 and holds 0%
  false-accepts on its replay arena while learning (87.1% overall accuracy on the
  93-case arena, untuned).
- **Artifact:** `scripts/aromer_publish_replay.py`,
  `artifacts/aromer/replay_arena_report.json`; live AII at
  `https://aromer.razorsharp.workers.dev/intelligence`.
- **Caveat:** **EXPERIMENTAL.** Episode labels are partly self-labeled (benign-bias
  possible); the world model defaults to shadow mode; the learning loop is **not
  externally validated**. Do not cite AROMER numbers as production evidence.
- **Reproduce:** `python -m remora.aromer.evals.replay_runner --json | python scripts/check_safety_gate.py`.

---

## How the math is defended
The full, blackboard-ready derivation of every quantity (entropy, dissensus,
trust, the conformal risk bound, the AROMER index, the world-model Beta–Binomial)
is in `paper/remora_mathematical_supplement.md`, each formula carrying a `source:`
pointer to the implementing file and each number an `artifact:` pointer.

## Standing invitation
If you can break a claim, reproduce a different number, or show a caveat is
understated, open an issue with the "external-review" template. Negative findings
are first-class here — see `NEGATIVE_RESULTS.md` and
→ [04-negative-results-detail.md](04-negative-results-detail.md).
