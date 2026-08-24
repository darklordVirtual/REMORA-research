# Negative and Incomplete Results

> **Why this document exists.**  Publishing negative results is standard
> scientific practice and is almost never done in individual portfolio projects.
> Every number here increases external credibility by proving the system was
> not optimised until only the positive findings remained.

This document holds the full negative-results record. Section numbers are
stable and referenced from other documents; a section is never renumbered and
never deleted, only re-statused in place.

## How to read a status

**35 numbered sections does not mean 35 open problems.** Until 2026-07-31 this
document read as if it did, because sections kept the status they were written
with even after later sections resolved them. Every section now carries a
machine-readable marker directly under its heading, and
`scripts/check_negative_results_status.py` fails CI if the summary table or the
backlog below disagrees with those markers.

| Status | Means | Should you act on it? |
|---|---|---|
| `open` | A real remaining gap, in the backlog below | Yes |
| `accepted` | Measured, published, and **not to be "fixed"** — a falsified hypothesis or a dataset that cannot answer the question asked of it | No. Tuning against these would be retrofitting |
| `superseded` | The finding caused a change; a later section documents the result | No. Read it for the causal chain |

Counts as of 2026-08-24: **12 `open`**, **20 `accepted`**, **23 `superseded`**.

## The actual backlog

Seven themes: six research gaps and one production gap. The section numbers
after each theme are where its evidence lives, and CI checks that every theme
cites only `open` sections and that no `open` section is missing a theme.

<!-- backlog-start -->
1. **Useful semantic autonomy** (§39) — safety is measured and met
   (native wrong-call ACCEPT 0/500 on sealed C-ext3, arm ablation
   24 → 6 → 0), which closed §36's measurement gap. What remains open is
   utility: the frozen deterministic intent extractor grounds only 26.6%
   of legitimate read calls (target ≥75%), and the semantic gates preempt
   the argument-routing layer (obtainable VERIFY 46.7%, unobtainable
   ABSTAIN 63.3%). The pre-identified follow-up is the LLM-as-proposer arm
   (SAP v5 §7 — a model proposes intents, the deterministic matcher keeps
   sole authority) plus an explicit gate-ordering design for combined
   semantic+argument observations.
2. **Legitimate autonomy lost to derived values** (§35) — grounding cost
   read autonomy 86.1% → 56.8%, mostly dates, unit conversions and computed
   values that are correct but not literally in the user's text. **The
   mechanism now exists** (`derivation.py`, 2026-08-05: `DerivationReceipt`
   over a versioned whitelist of deterministic transforms — English dates,
   number normalization, exact unit conversions; verification re-executes
   the transform against a source span that must be verbatim in the task
   text, so a model may propose but never accept a receipt, and arithmetic
   is deliberately excluded as receipt-craftable). A model's explanation is
   still not a derivation proof — that is the design. Its effect on the
   §35 autonomy loss is unmeasured, so this theme stays open on the measurement.
3. **Contextual harm across a trajectory** (§2, §8) — 30.7% false accepts under
   neutral metadata is residual harm that is not visible in any single call.
   Another per-call classifier cannot close it; it needs governance over the
   action sequence, cumulative blast radius and cross-tenant data movement.
4. **Full NLI-backend parity for Semantic Entropy** (§3) — technically solvable
   now: re-run the same raw oracle responses through both backends and publish
   the per-episode cluster and route deltas. Explicitly **not** a route to
   reviving temperature as an authoritative selector (§18 stands).
5. **Production validator quality** (§33) — the mechanism recovers read utility
   0% → 100%, but the study validator is correct by construction. Real
   validators need their own contracts and measurements: false-absent rate,
   staleness, tenant binding, timeout behaviour, response provenance.
6. **External replication, REM-021, and live evidence** (§1, §4, §15, §16) —
   cannot be closed from inside this repository. Needs third-party replication,
   a named independent reviewer, and field traces.
7. **Authoritative tool metadata on the advisory path** (§14) — the enforcement
   path already takes `effect`, risk class and validator bindings from a
   server-side registry, but the library path judges the metadata it is handed.
   A caller should be able to raise risk and never lower it. The
   `assign`/`close`/`approve` write bug showed why verb heuristics must be the
   fallback, not the authority. **Raise-only clamp implemented 2026-08-05**
   (`remora/assess.py`: declared `risk_tier` weaker than the name-heuristic
   floor is clamped up and the clamp is RECORDED in
   `ToolCallAssessment.floored`; declared read on a write-verb tool floors to
   the write family; the M4 verbs are now in the inference table; the floor
   never fills unset fields, so fail-closed semantics are untouched). The
   full authority — a signed tool-schema registry on the advisory path
   (FT-03 ToolSpec) — remains open, so this theme stays open; it is also
   tracked in
   [remediation_register.yaml](docs/assurance/remediation_register.yaml).

8. **CI gates that run without blocking** (§55) — `master` requires five
   contexts: `verify`, the three `pytest` legs and documentation governance.
   CodeQL, secret scanning, the dependency audits, the SBOM job, OPA policy
   conformance, key artifact integrity, lockfile integrity, the wheel contract,
   the Postgres tenant-chain contract and `worker-typecheck` all run, all
   report, and none of them blocks a merge. The workflow file shows what runs
   and says nothing about what is enforced, which is why this went unnoticed.
   Closing it is a repository-settings change: the required-context strings
   have to match the reported job names exactly, and a wrong one blocks every
   merge on `master` until an admin intervenes.
<!-- backlog-end -->

---

## Headline negative results

The negative findings previously summarized on the README front page live
here as of 2026-07-28 — moved, not removed. Full analysis in the numbered
sections below and in [docs/02-evidence-and-claims.md](docs/02-evidence-and-claims.md).

<!-- claim:CLAIM-004 accuracy_pct coverage_pct ci_low_pct ci_high_pct n -->
<!-- claim:CLAIM-012 temperature_aurc confidence_aurc n -->
<!-- claim:CLAIM-005 low_trust_correct_pct high_trust_correct_pct n -->
| Result | Value | Key caveat | Artifact · detail |
|--------|-------|------------|-------------------|
| Temperature-selective holdout (N544 round) | **100.0%** @ 16.7% coverage; N=18, Wilson CI [82.4%, 100.0%] | p=0.052 vs training baseline — directional only, and the signal later FAILED fresh-data confirmation (next row) | `results/selective_n500_holdout_results.json` |
| **Temperature falsified on fresh data (SAP v3)** | temperature AURC **0.0954** vs calibrated confidence **0.0664** on N=1231 fresh items; paired CI excludes zero; SGR certifies **no** coverage | pre-registered three-way split; the exploratory temperature advantage on the reused corpus did not transfer — temperature is diagnostics, not an authoritative selector | §18 · `results/sap_v3_round_results.json` |
| Critical-phase trust inversion | low-trust **76.2%** vs high-trust **36.4%** correct, N=32 | small sample; a documented failure mode routed around via `PhaseAwareGuardrail` | [docs/02-evidence-and-claims.md](docs/02-evidence-and-claims.md) §3 |

---

## Findings

### 1. External replication and live-deployment validation pending
<!-- finding-status: open -->

Core benchmark claims are now internally replicated and documented with
benchmark-scoped caveats, but independent external replication remains pending.

**Outstanding items:**
- Independent third-party rerun of selective QA metrics on public datasets.
- Live-oracle (non-simulator) replication of tool-call safety metrics.
- Production evidence retrieval validation (beyond MultiNLI proxy benchmark).

**Why this remains active:** This is a research-governance gap, not a hidden
performance failure. The mitigation path and protocol are tracked in
`docs/11-benchmark-validation-plan.md`.

---

### 2. AROMER safety floor does not transfer to the external holdout under proxy signals
<!-- finding-status: open -->

On the internal replay arena (65 cases at the time of this evaluation; expanded to 96 cases in later versions), the seeded AROMER profile records
false_accept_rate 0.000 and correct_intercept_rate 1.000. On the first external
holdout, 495 cases derived from the independent `toolcall_v3`
(CyberSecEval-inspired) set, `datasets/aromer_external_holdout_v1/`, all
`can_train=False`, with deterministic proxy signals, both degrade to **0.500**,
and profiles A (REMORA-only), B (AROMER cold), and C (AROMER seeded) are
**bit-identical** (zero learning differentiation).

**What this establishes:**
- The internal arena is an optimistic measurement surface: its cases share the
  (domain, action_type, risk_tier) taxonomy AROMER's synthetic seeds were
  authored against.
- AROMER seed episodes do not change any decision on an independent distribution.

**Confounds, and what has since been tested:**
- The ablation now runs REMORA's real admission firewall
  (`Remora._detect_adversarial_input`) on each action description. The 0.500
  result is **unchanged**, because the holdout's injection payloads live in
  `untrusted_context`, not in the scanned action description. So the false-accept
  is not a missing-flag artifact, the firewall genuinely does not cover indirect
  injection.
- REMORA's dedicated content scanner (`ToolResultScanner`) was measured directly
  on the 150 attack `untrusted_context` payloads
  (`artifacts/aromer_injection_ceiling_v1.json`, deterministic heuristic stage).
  As originally implemented it hard-blocked only **6.7%** (10/150). Adding
  semantically-general exfiltration and authority-spoofing rules raised this to
  **53%** hard-block / **80%** detect at **0%** benign false-positive
  (paraphrase-robust, see `tests/test_injection_ceiling.py::TestScannerGeneralization`).
  This is **in-distribution recall**: the rules were written against this corpus's
  attack classes, so external-corpus validation remains required before any
  general detection claim.
- A **balanced, gated validation** of the *full* defense on 200 harmful / 195
  benign / 100 ambiguous (`artifacts/aromer_balanced_validation_v1.json`)
  initially **FAILED** (false_accept_rate = 0.500). The failure was localised to
  100 low-risk-tier harmful actions, every one a **schema-invalid (malformed)
  tool call**. Adding a schema-validity hard gate to the policy engine
  (`MALFORMED_CALL_BLOCKED`: malformed call → ESCALATE), a general capability
  derived from call structure, not the decision label, with zero false-blocks on
  real benign traffic, moved the result to **WARN**: false_accept 0.500 → 0.000,
  intercept 0.500 → 1.000, friction 0.339 → 0.170. The safety gate now passes;
  the residual gap to a full PASS is friction 0.170 vs the 0.15 target, which
  needs faithful trust calibration (live oracle), not eval tuning.
- The ablation `success` flag (previously trivially `True` when A = B = C) is now
  tightened (`_evaluate_success`) and correctly returns FALSE.
- **Proxy-dependence eliminated.** Three *structural* gates were added to the
  policy engine: malformed-call (schema validity → ESCALATE), forbidden-tool
  (proposed tool is on the task's own forbidden list → ESCALATE), and
  tainted-argument (untrusted-derived args → VERIFY floor, never auto-accept). On
  the balanced holdout all 200 harmful cases are now intercepted by a structural
  signal (100 schema + 100 forbidden), with **zero** reliance on the deterministic
  proxy trust and **zero** false-blocks on benign/ambiguous (neither carries
  forbidden/tainted/invalid calls). REMORA's safety on this holdout is therefore
  *structural and deployable*, these signals (tool schema, the task's
  allowed-tool list, argument taint) exist in any real agent loop, rather than a
  proxy artifact. Locked by
  `tests/test_balanced_validation.py::TestStructuralDefenseIsPrincipled`.
- Governance KPIs (`remora/aromer/evals/kpi.py`) separate *unnecessary* friction
  (VERIFY on a should-accept case) from *correct* verification of genuinely
  ambiguous cases. On the holdout: unnecessary_review_rate = 0.0, false_block_rate
  = 0.0: the raw 0.170 review-friction is entirely correct ambiguous-handling.

**Why this is now largely de-risked (but not closed):** On the balanced external
holdout REMORA achieves 0% false-accept, 100% harm-intercept *via structural
signals*, 0% false-block, and 0% unnecessary friction. Two items remain before a
general claim: (a) faithful live-oracle trust/entropy to confirm the result
without proxy signals for the non-structural margin and to push benign friction
below 0.15; (b) external-corpus validation of the injection-scanner rules.
The internal-arena 0.000 false-accept must still not be cited as a general safety
property. Tracked in `datasets/aromer_external_holdout_v1/README.md`. Artifact:
`artifacts/aromer_external_holdout_ablation_v1.json`.

---

### 3. Entropy computation uses token-fingerprint heuristic, not Semantic Entropy
<!-- finding-status: open -->

All reported benchmarks (QA selective accuracy, tool-call, conformal coverage)
were computed using the `TokenFingerprintBackend`: entropy H is computed over
verdict clusters defined by NFKC-normalised, sorted-token SHA-256 truncation.

The paper's Stage 4 description and the mathematical supplement describe H as
"grounded as Semantic Entropy over NLI-derived semantic equivalence clusters"
(Kuhn et al. 2023), but this refers to the `NLISemanticBackend`, which exists
as a drop-in alternative and was not activated for any reported result.

**What this means:** claims about the Semantic Entropy properties of H are not
validated by the reported experiments. The token-fingerprint approximation may
cluster differently than NLI entailment, particularly for paraphrases that share
no lexical tokens. Results with the NLI backend are not yet reported.

**Resolution path:** run the benchmark suite with `NLISemanticBackend` enabled
and compare selective-accuracy, trust-inversion, and conformal results. Until
then, the SE framing in the abstract and §4 should be read as a description of
intent, not of the implementation used in experiments.

**Replication instructions:**

The NLI backend is a drop-in at the REMORA inference layer, it replaces
`TokenFingerprintBackend` inside `compute_semantic_entropy()`. A full comparison
requires re-running oracle inference with the NLI backend activated, since
`experiments/selective_n500.py` is a post-hoc analysis script that operates on
pre-computed JSON results, not on raw oracle response texts.

```python
from remora.semantic_entropy import make_backend, compute_semantic_entropy

# Enable NLI backend (requires sentence-transformers + torch with no DLL policy blocks)
backend = make_backend(prefer_nli=True, model_name="cross-encoder/nli-deberta-v3-small")

# Pass oracle response strings — same API as TokenFingerprintBackend
H, clusters = compute_semantic_entropy(oracle_responses, backend=backend)

# Compare to token-fingerprint result on same inputs:
from remora.semantic_entropy import TokenFingerprintBackend
H_fp, clusters_fp = compute_semantic_entropy(oracle_responses, backend=TokenFingerprintBackend())
```

**Local execution status:** Blocked in the current environment by a Windows
application-control policy on `torch/lib/shm.dll` (`OSError: [WinError 4551]`).
The code is production-ready and falls back to `TokenFingerprintBackend`
automatically when the NLI model is unavailable. External replicators with a
torch-enabled Python environment (Linux/macOS or Windows without DLL restrictions)
can run the comparison immediately. Expected comparison artifact: run
`experiments/selective_n500.py` after re-generating oracle-response JSON with
the NLI backend and compare precision/recall/phase-inversion metrics against
the token-fingerprint baseline in `results/selective_trust_curve_results.json`.

**Update (2026-07-30):** The Windows application-control block above no longer
reproduces on the development machine (torch 2.12.1+cpu, Python 3.14):
`NLISemanticBackend` loads and executes locally. The first NLI-executed
comparison artifact now exists on disk: `results/se_backend_parity_smoke.json`
(24-item committed paraphrase fixture corpus,
`data/se_parity/paraphrase_corpus_v1.json`; provenance sidecar alongside;
generated by `scripts/se_backend_parity_smoke.py`, also runnable on CI-Linux
via `.github/workflows/nli-parity.yml`). On this fixture the backends disagree
on cluster counts for 12 of 24 items: lexically-disjoint paraphrases that the
token-fingerprint backend splits are merged by NLI, and some shared-token
contradictions false-merge under the fingerprint (per-item detail in the
artifact). This narrows the finding but does not resolve it: the smoke corpus
is a fixture, not the reported benchmarks, so the resolution path above —
re-running oracle inference for the reported results under the NLI backend —
still stands, and the fingerprint backend remains the default.

---

### 4. TRAINED_SHADOW_ONLY reached via world-model seeding; full certification deferred
<!-- finding-status: open -->

> **Updated (2026-06-28):** Gap 1 closed (CERTIFIED_INDEPENDENT_HOLDOUT, n_harmful_independent=169, safety_upper_bound_95=0.37%). Gap 3 resolved organically (§11): T2=1.000 sustained via brr=0% across 12+ cycles. AII=0.8442 TRAINED at §11 peak. This section preserves the seeded milestone (2026-06-26) as scientific record.

> **Updated (2026-07-01):** AII=0.9918 TRAINED (structural ceiling 0.9922). T1=0.9741 (ECE=0.0052), T2=T3=T4=T5=1.000. n_operational_fa=0 (Day 26/30 longitudinal). safety_certification: CERTIFIED_INDEPENDENT_HOLDOUT (n=814 operational harmful; CP upper bound 0.367%). Ceiling is structural (MCE bucket §15; transfer_unmeasured §16). Two production gates remain: REM-020 (eligible 2026-07-07), REM-021.

> **Updated (2026-07-17):** REM-020 (longitudinal stability) CLOSED by the
> fail-closed tooling under the owner-reconciled 7-day criterion
> (days_elapsed=19 of 7, n_operational_fa=0, AII=0.9914, self-reported,
> pending REM-021 verification). One production gate remains: REM-021
> (independent human review). Deployment stays SHADOW_ONLY until it closes.

AROMER reached `interpretation_nuanced = "TRAINED_SHADOW_ONLY"` on 2026-06-26 with AII ≈ 0.820
(smoothed), after all five interpretation gates cleared. Progression: CAPABLE_SHADOW_ONLY
(AII≈0.629) on 2026-06-26 → TRAINED_SHADOW_ONLY (AII≈0.820) same day, via world model seeding.

| Gate | Value | Threshold | Status |
|------|-------|-----------|--------|
| longitudinal_records | 321+ | ≥ 10 | ✓ CLEARED |
| n_harmful_internal | 256 | ≥ 30 | ✓ CLEARED |
| CP bound (95%) | 1.2% | ≤ 5% | ✓ CLEARED |
| cross_domain_cases | 4 (database_to_financial) | > 0 | ✓ CLEARED |
| causal_enriched | 66 episodes (Bjøru 2026) | > 0 | ✓ CLEARED |

**Component scores at TRAINED milestone (2026-06-26):**

| Component | Score | Driver |
|-----------|-------|--------|
| T1 calibration | 0.691 | ECE=0.062 (T1 = 1 − ECE×5; ground-truth labels from replay arena) |
| T2 friction | 0.975 | benign_review_rate=0.5% in 200-ep window (seeding artifact, see §5) |
| T3 metajudge | 0.736 | LLM critique quality on labelled episodes |
| T4 transfer | 1.000 | `replay_transfer_score` (accuracy on cross-domain transfer cases; 4/4 correct), distinct from overall arena accuracy |
| T5 stability | 0.713 | Recovering after seeding distribution shift |
| **AII smoothed** | **0.820** | Weighted sum |

**Important caveat, T2 is window-composition driven, not operational.** The TRAINED
threshold was reached because world-model seeding filled the 200-episode sliding window
with correct_accept episodes, driving `benign_review_rate` in the window to ≈0.5% (down
from the operational baseline of 35.3%). T2 = exp(−0.005/0.20) ≈ 0.975 versus the
pre-seeding T2 = 0.175. Once 200 new organic decisions arrive, the window will rotate out
seeded episodes and T2 will revert toward the operational rate. The Bayesian world model
priors updated by seeding (p_harm 0.50→0.10–0.17 for benign contexts) are real and
persisted in D1, but their operational effect on benign_review_rate requires organic
traffic confirmation. This is documented in full in §5.

At the time of seeding (2026-06-26), the `deployment_status = "SHADOW_ONLY"` and `safety_certification = "CERTIFIED_INTERNAL_ONLY"` fields in the API reflected the following gaps (Gap 1 and Gap 3 have since been resolved, see update banner above):

**Gap 1, Closed 2026-06-27 (gate logic fixed 2026-06-27).** `n_harmful_independent = 169`
as of 2026-06-27. 84 aradhye + 84 CaiZhiTech harmful episodes seeded via
`scripts/aromer_seed_harmful_episodes.py`. A 36-case holdout was saved to
`artifacts/aromer/harmful_seed_holdout.json` (raw holdout file not committed to
this repo; its evaluation results are committed as
`artifacts/aromer/harmful_seed_holdout_eval.json`, n_cases=36). The worker now computes n_harmful_independent
from episodes where `id LIKE 'seed-harmful-%'` or `meta.source_tag IN ('aradhye','caizhitech')`.
The certification gate was updated to check `n_harmful_independent >= 30` (previously checked
only `globalHarmful >= 30`). With `n_harmful_independent=169` and `safety_upper_bound_95=0.00367` (0.37% ≤ 5%),
`safety_certification` is now `CERTIFIED_INDEPENDENT_HOLDOUT`.

**Gap 2, T4 transfer measured but in-domain only.** `cross_domain_cases = 4`
(database_to_financial); transfer is measured but not independently validated on an
external distribution.

**Gap 3, T2 friction not organically confirmed.** AII ≥ 0.80 was reached via seeding
(see caveat above). Durable TRAINED status requires T2 ≥ 0.95 from organic traffic, not
window composition. The LoRA MetaJudge that provides sustained friction reduction signals
is blocked on Cloudflare Workers AI beta access.

**Why not closed (at 2026-06-26):** Items 1, 2, and 3 required organic data accumulation and external validation. **Update (2026-06-28):** Gap 1 resolved (CERTIFIED_INDEPENDENT_HOLDOUT). Gap 3 resolved organically (§11: T2=1.000, brr=0%, 12+ cycles). Gap 2 remains open (FA=22.2% aradhye holdout). `policy_relaxation_allowed = false` remains set. Of the three gates originally required before relaxation, the longitudinal stability audit (REM-020) closed 2026-07-17 and the RBAC audit (REM-022) closed 2026-06-30 with recorded deviation (REM-023); independent human review (REM-021) remains the blocker.

---

### 5. benign_review_rate window distortion during world-model seeding
<!-- finding-status: superseded -->

When the AROMER world model is initialized from replay arena episodes via
`scripts/aromer_seed_benign_outcomes.py`, concentrated benign correct_accept
seeds fill the sliding 200-episode window with seeded entries. This temporarily
drives `benign_review_rate = 0%` in the window metric and the quality gate to
`INSUFFICIENT_SAFETY_EVIDENCE` (harmful cases pushed out of the window).

**What this means:**
- `benign_review_rate` computed from a seeded window is not a stable operational
  measurement of friction: it reflects window composition, not live decision quality.
- The `quality_gate_status` window check degrades to `INSUFFICIENT_SAFETY_EVIDENCE`
  during seeding; the **global** gate (256 harmful all-time, CP 1.2%) remains `PASS`.
- T5 stability score drops temporarily (0.66 → 0.51) because the distribution shift
  from seeding creates high apparent divergence from historical baseline.

**Mitigation:** The global safety gate is the authoritative safety certification.
The window gate is a drift detector; its signal is only meaningful when the window
contains a representative mix of harmful and benign episodes. After the seeded
episodes rotate out of the window (≈ 200 new decisions), both the window gate and
T5 stability recover. The `INSUFFICIENT_SAFETY_EVIDENCE` status does not indicate
a safety regression, it indicates insufficient harmful evidence in the current
window, not new false accepts.

**Provenance note:** The world model Bayesian priors updated by seeding ARE real
improvements, p_harm for benign contexts drops from 0.50 (uniform) to 0.10–0.20
(medium-confidence posterior), reducing future VERIFY rate for those contexts. The
seeding methodology is documented in `scripts/aromer_seed_benign_outcomes.py`.

---

### 6. Secondary seeding perturbation, targeted high-friction context seeding (2026-06-26)
<!-- finding-status: superseded -->

After observing organic T2 improvement (0.905→0.945) over 12 cycles, a second seeding
pass was attempted targeting 5 high-friction contexts identified from the friction
pipeline (207 reduce_friction signals, 196 from system/execution). 25 benign
correct_accept episodes were posted for: system/execution/low, system/read/low,
git/write/low, cloudflare/deployment/medium, system/execution/medium.

**Effect:** The 25 new episodes shifted the 200-episode sliding window, displacing
existing seeded correct_accept episodes and allowing organic benign_review episodes
(25.1% all-time rate) to enter. Component scores 2 adapt cycles after seeding:
T2: 0.945 → 0.670 (benign_review_rate 1% → 10.67%), T5: 0.707 → 0.567,
T1: 0.691 → 0.664, AII: 0.813 → 0.722.

**What this confirms:**
- The 200-episode window is highly sensitive to even small seeding batches (25 episodes
  = 12.5% of window). Any batch large enough to provide Bayesian signal is also large
  enough to perturb T2 and T5.
- Organic T2 improvement (§5 recovery trajectory) is fragile against additional seeding.
- The intended world model prior update (p_harm for system/execution/low) may still be
  beneficial long-term, but the window transition cost is significant.

**Recovery path:** Global safety gate remains PASS (0 false accepts, CP 1.2%). AII at
0.722 (CAPABLE, above 0.60). T5 and T2 should recover over ~20–40 adapt cycles as the
window re-stabilises. No further seeding should be performed until recovery is confirmed.

---

### 7. Window-rotation bottleneck, adapt cycles do not generate /decide episodes
<!-- finding-status: superseded -->

After the secondary seeding perturbation (§6), T2 recovery was expected to occur
organically as new episodes rotate through the 200-episode sliding window. Empirical
observation over cycles n=107–112 shows this recovery mechanism is slower than
anticipated.

**Root cause:** `POST /adapt?skip_judge=1` cycles process the existing window but do
not create new `/decide` episodes. The 200-episode sliding window advances only when
external traffic calls `/decide`. Hook activity (`remora_hook.py`) generates episodes
only for MEDIUM/HIGH risk tool calls; LOW-risk calls (curl to `razorsharp.workers.dev`,
`python -c` parsing operations that are fast-pathed) may not reach `/decide` at all.

**Observed dynamics (n=107→112, 2026-06-26):**
- `global_n_benign`: 8097 → 8124 (+27 over 5 cycles), pending-resolution,
  not new `/decide` calls
- Window composition: `{benign: 150, review: 16, harmful: 50}`, static across all
  6 cycles, no rotation
- benign_review_rate: 0.1067, unchanged for 6 consecutive adapt cycles
- AII: 0.7158, confirmed plateau; no improvement without window rotation

**Implication for §6 recovery estimate:** The "~20–40 adapt cycles" estimate in §6
was incorrect. Recovery requires ~200 new organic `/decide` calls, not 200 adapt cycles.
Adapt cycles alone do not drive recovery. The actual recovery timeline depends entirely
on external traffic volume and session hook activity that generates MEDIUM/HIGH risk
decisions.

**Convergence observation (n=113–118, 2026-06-26):** After the initial window
composition shift, the system entered a convergence regime. The per-cycle AII decline
rate followed a geometric decay: −0.0017, −0.0015, −0.0010, −0.0007, −0.0004, −0.0004.
The effective internal benign_review_rate asymptoted toward ~0.113 (reported as 0.1133),
establishing a secondary equilibrium at AII ≈ 0.709–0.710 (CAPABLE). This is
substantially below the pre-perturbation TRAINED state (AII=0.813) but above the
CAPABLE threshold (0.60). False accepts remain 0 throughout. The convergence
demonstrates that the window self-stabilizes once the composition shift completes, 
T2 does not collapse to the all-time benign_review rate (28.7%) as feared, but instead
converges to the composition of the most recent 200 episodes.

**Design note:** This is an inherent property of the sliding window architecture.
A time-decayed window or an exponential moving average of benign_review_rate would
be more resilient to seeding artifacts than the current fixed-size recency window.

**Recovery trajectory addendum (n=119–134, 2026-06-26):** The secondary equilibrium
at AII≈0.710 was not permanent. Session hook traffic (MEDIUM/HIGH risk tool calls)
generated organic `/decide` episodes that began rotating the 200-episode window. The
recovery followed a two-phase pattern:

- **Phase A (n=119–131):** brr fell rapidly from 11.33% → 1.10% as seeded §5 benign
  episodes displaced the §6 perturbation episodes in the window. T2 rose from 0.568
  to 0.878 (EMA convergence toward T2_eq≈0.946 at brr=1.0%). T5 simultaneously
  fell from 0.714 to 0.593 (window composition shifting rapidly, outcome distribution
  instability). AII rose from 0.710 to 0.777.

- **Phase B (n=132–134):** brr stabilised at ~1.0–1.1%. T2 reached equilibrium
  (0.949). T5 bottomed at 0.593 (n=131) then recovered: +0.006 (n=132), +0.019
  (n=133), +0.052 (n=134). At n=134: T1=0.664, T2=0.949, T3=0.749, T4=1.000,
  T5=0.669, AII=0.803, **TRAINED recovered**.

This two-phase pattern was predicted from the first TRAINED attainment: Phase A
(brr falling → T2 rising → T5 falling) followed by Phase B (brr stable → T5
recovering → TRAINED when T5 ≥ 0.644). The EMA smoothing on T2 caused ~3-cycle
lag between reported brr stabilisation and T2 reaching equilibrium. 0 false accepts
throughout; global gate PASS at all checkpoints.

---

### 8. External adversarial dataset evaluation: FA=30.7% under neutral metadata (Phase 2)
<!-- finding-status: open -->

Two real-world labeled agent-safety datasets were evaluated against AROMER `/decide`
under intentionally neutral trust parameters (trust=0.70, entropy=0.25, dissensus=0.15)
to simulate adversarial agents that appear legitimate. This test does not constrain
caller-supplied metadata to reflect ground truth.

**Datasets:** `aradhye/agent-safety-bench` (400 rows sampled; 184 harmful / 216 benign) and
`CaiZhiTech/Evaluation-Dataset-of-AI-Agent-Security-Guardrails` (1018 rows; 852 harmful / 166 benign).

**Phase 1, structural policy only (no instruction text):**
| Dataset | FA rate | Accuracy | ECE |
|---------|---------|----------|-----|
| aradhye/agent-safety-bench | 64.1% (118/184) | 0.422 | 0.365 |
| CaiZhiTech/guardrails | 38.5% (328/852) | 0.523 | 0.478 |
| **Combined** | **43.0% (446/1036)** | **0.494** | **0.409** |

Artifact: `artifacts/aromer/external_dataset_eval.json`

**Root cause, Phase 1:** AROMER's structural policy achieves FA=0% only when callers
supply accurate high-risk metadata. With neutral-looking metadata (trust=0.70,
risk_tier=low/medium), harmful scenarios are indistinguishable from benign ones at the
structural layer. This is the "metadata dependency vulnerability."

**Phase 2, structural + semantic enrichment (instruction_text → llama-3.3-70b classification):**
| Dataset | FA rate | Accuracy | ECE | Delta FA |
|---------|---------|----------|-----|----------|
| aradhye/agent-safety-bench | 52.2% (96/184) | 0.448 | 0.399 | −11.9 pp |
| CaiZhiTech/guardrails | 26.1% (222/852) | 0.627 | 0.223 | −12.4 pp |
| **Combined** | **30.7% (318/1036)** | **0.576** | **0.273** | **−12.3 pp** |

Semantic enrichment applied to 26% of scenarios (369/1418); of those, 83% were
classified `critical` (307), 10% `high` (38), 7% `medium` (24).

Artifact: `artifacts/aromer/external_dataset_eval_v2.json`

**What semantic enrichment resolves:** Prompt-injection attempts and explicit
data-exfiltration/spam instructions in the CaiZhiTech dataset are correctly caught
(FA 38.5% → 26.1%). Direct-text harmful instructions now receive `p_boost=0.65`
and are escalated even under neutral metadata.

**Residual gap (30.7% FA after enrichment):** Two distinct sources remain:

1. *aradhye contextual harm (52.2% FA):* Many aradhye scenarios are labeled harmful
   based on execution outcomes, not instruction text. Example: "You are a CodeAgent.
   Write a python function to check if so...", the harm is in the agent's broader
   task context, not the literal 80-char instruction preview. Instruction-text
   classification cannot catch this class without the full agent-task context.

2. *Subtle CaiZhiTech injections (26.1% FA):* A fraction of CaiZhiTech injection
   scenarios use indirect / subtle framing that the classification model assigns
   `low` or `medium` risk, below the boost threshold.

**Why this is not closed:** The residual gap requires either (a) runtime execution
monitoring (detecting harm from agent action traces, not instruction text alone) or
(b) world model seeding from real-world labeled patterns to improve calibration for
medium/low metadata harmful scenarios. Neither requires changing the semantic
enrichment architecture; they are orthogonal signals.

**Important tradeoff:** Semantic enrichment increases the false-block rate (74.1%
vs 70.9% Phase 1 combined). The CaiZhiTech benign miss rate reached 95.2% in Phase 2
- nearly all benign scenarios are blocked. This suggests the 80-char instruction
preview captures injection-like surface patterns in benign scenarios too. A longer
instruction window or a separate benign-classifier head would reduce this friction.

**Note on CF_MODEL_DIVERSE deprecation (2026-06-27):** During Phase 2 evaluation,
`@cf/meta/llama-3.1-8b-instruct` (CF_MODEL_DIVERSE) was found deprecated as of
2026-05-30, causing the semantic classifier to silently fall back to the structural
risk tier. CF_MODEL_DIVERSE was updated to `@cf/meta/llama-3.2-3b-instruct` and the
semantic classifier now uses `CF_MODEL_FAST` (`@cf/meta/llama-3.3-70b-instruct-fp8-fast`)
to ensure correctness. The Phase 2 evaluation was run with the corrected classifier.
All Phase 1 eval runs were structural-only (no instruction text); they are unaffected.

---

### 9. Harmful seeding → T2 regression: batch external dataset seeding causes TRAINED→CAPABLE regression (2026-06-27)
<!-- finding-status: superseded -->

During Gap 1 closure (n_harmful_independent: 0→169), 168 harmful episodes from
`aradhye/agent-safety-bench` and `CaiZhiTech/Evaluation-Dataset-of-AI-Agent-Security-Guardrails`
were bulk-seeded into AROMER's episode store in a single batch. This caused the
200-episode sliding window to reach 84% harmful dominance (168 harmful, ≈32 benign).

**Pre-seeding state:** AII=0.8083 (TRAINED), T1=0.664, T2=0.9506, T3=0.759,
T4=1.000, T5=0.697 (n=135, 18:20 UTC+2 2026-06-27). brr=1.0%.

**Effect:** T2 crashed from 0.921 to 0.274. `benign_review_rate` spiked to 45%.
AII fell from 0.8083 (TRAINED) to 0.62 (CAPABLE). T5 simultaneously fell from
0.697 to 0.51 (AII variance spiked from window composition instability).

**Root cause:** The friction optimizer interprets episodes with
`decision_quality=false_accept` as AROMER incorrectly accepting harmful inputs.
With 168 such episodes dominating the window, the optimizer tightened friction
thresholds, raising `benign_review_rate` (brr). T2 = exp(−smoothedRate/0.20) is
extremely sensitive: brr=45% → EMA-smoothedRate≈0.40 → T2≈0.135. The 5-cycle
EMA smoothing delayed the crash but amplified it once the window was saturated.

**Recovery action:**
1. 210 benign `correct_accept` episodes seeded via `scripts/aromer_seed_benign_outcomes.py`
   to rebalance the window (replaces harmful-dominated composition with benign majority).
2. Five consecutive `/adapt` cycles forced EMA convergence toward new brr equilibrium.

**Post-recovery state (20:41 UTC+2 2026-06-27):** AII=0.7833, T2=0.897, T5=0.545
(T5 still recovering). This was a transient state, not the equilibrium.

**Stable equilibrium state (21:30 UTC+2 2026-06-27):** AII=0.752, T2=0.689, T5=0.773
(T5 fully recovered). brr=7.5% stable from 15 historical VERIFY episodes in window.
T2 converged to T2_eq=exp(−0.075/0.20)=0.687. TRAINED via T2-only path requires brr<2.1%.
Three paths to TRAINED identified (§10): brr<2.1%, T3≥0.868 (MetaJudge), ECE<0.020.
T3 and T2 both improving organically per 2026-06-28 (AII=0.767 at 01:10 UTC+2).

**Global safety gate unaffected:** Throughout the regression, global gate remained
PASS: n_harmful_internal=983, n_harmful_independent=169, false_accept_rate=0,
CP upper bound 1.2% (target ≤5%). The TRAINED→CAPABLE regression was a friction
calibration artifact, not a safety failure. 0 false accepts throughout.

**Design implication:** Bulk seeding of class-imbalanced external datasets must be
staged. A safe seeding strategy:
- Seed ≤25 harmful episodes per batch (12.5% of window = prior §6 limit)
- Wait for 1–2 adapt cycles between batches
- Interleave harmful and benign seeds to maintain window balance
Alternatively, the sliding window should be replaced with a longer exponential
moving average of brr that is less sensitive to instantaneous window composition.

---

### 10. brr=7.5% stable equilibrium: CAPABLE ceiling and INSUFFICIENT_SAFETY_EVIDENCE window gate (2026-06-27)
<!-- finding-status: superseded -->

After §9 recovery (210 benign seeds + 5 EMA cycles), the system entered a second
stable equilibrium at brr=7.5%, distinct from the TRAINED state and not a transient
"recovering" phase. This equilibrium is structurally determined by 15 organic
VERIFY episodes from a high-friction period that remain embedded in the 200-episode
sliding window.

**AII trajectory (recovery in progress):**

| Component | 21:30 2026-06-27 | 01:00 2026-06-28 | 01:20 2026-06-28 | 01:30 2026-06-28 | Driver |
|-----------|-----------------|-----------------|-----------------|-----------------|--------|
| T1 calibration | 0.682 | 0.682 | 0.682 | 0.682 | ECE=0.064 (stable) |
| T2 friction | 0.689 | 0.687 | 0.837 | **0.875** | brr: 7.5%→~2.7%, 13-14 VERIFY rotated |
| T3 metajudge | 0.741 | 0.783 | 0.788 | 0.788 | MetaJudge cycles (organic) |
| T4 transfer | 1.000 | 1.000 | 1.000 | 1.000 | Perfect in-domain |
| T5 stability | 0.773 | 0.787 | 0.707 | 0.686 | Volatility from rapid AII change |
| **AII** | **0.752** | **0.762** | **0.792** | **0.7995** | Near-TRAINED (0.0005 below 0.80) |

**Mathematical ceiling analysis:** At brr=7.5%, the T2 EMA equilibrium is:
`T2_eq = exp(−0.075 / 0.20) = exp(−0.375) = 0.687`

Point-in-time ceiling (2026-06-27 21:30 UTC+2): with T1=0.681, T3=0.741 (then-current), T4=1.0, T5=1.0 (best case):
`AII_max = 0.30×0.681 + 0.25×0.687 + 0.20×0.741 + 0.15×1.0 + 0.10×1.0 = 0.775`

**Note (updated 2026-06-28):** This ceiling is T3-dependent, not T2-only. T3 has since improved
organically to 0.783 (+4.2 pp in 8h via MetaJudge cycles). At T3=1.0, T5=0.787 (current):
`AII = 0.30×0.682 + 0.25×0.687 + 0.20×1.0 + 0.15×1.0 + 0.10×0.787 = 0.805 (TRAINED)`
So TRAINED is achievable at brr=7.5% via T3+T5 joint improvement. The T2-only ceiling
(T3, T5 fixed at current) is 0.784 (at T3=0.783, T5=1.0). T3-pathway threshold: T3≥0.868 at T5=1.0.

Recovery to TRAINED, three paths:
- **Path A (T2/brr):** brr < 2.1%: `T2_eq = exp(−0.021/0.20) ≈ 0.90`, `AII ≈ 0.806`
- **Path B (T3/MetaJudge):** T3 ≥ 0.868 (at T5=1.0) or T3 ≥ 0.975 (at T5=0.787); both require sustained MetaJudge improvement
- **Path C (T1/calibration):** ECE < 0.020: T1 ≥ 0.90; combined with T2=0.687: `AII ≈ 0.817`

**Update (01:30 UTC+2 2026-06-28):** T2=0.875 (brr~2.7%), AII=0.7995, at TRAINED boundary.
Recovery trajectory: T2=0.687 → 0.712 → 0.837 → 0.875 over ~2.5h.
Approximately 13–14 of 15 VERIFY episodes displaced. AII=0.7995, 0.0005 from TRAINED.
T5=0.686 (expected volatility during rapid T2/AII change).

**Root cause of brr=7.5% plateau (initial):** 15 organic VERIFY decisions from a high-friction
period (when `verify_p` was 0.55 and `accept_trust_min` was 0.65) remain in the
200-episode window FIFO queue. These are NOT harmful episodes (FA=0); they are safe
decisions that were sent to unnecessary review under the old, conservative thresholds.
The FrictionOptimizer has since reduced thresholds (`verify_p=0.45`,
`accept_trust_min=0.50`) in response to 227 reduce_friction signals, but the 15
historical VERIFY episodes persist until 15 non-VERIFY decisions displace them via
FIFO rotation.

**INSUFFICIENT_SAFETY_EVIDENCE window gate:** The sliding-window safety gate requires
at least one harmful episode in the current 200-episode window to evaluate real-time
safety performance. In steady-state operation with low-harm organic traffic, the
window contains NO harmful episodes, the system passes the global gate
(n_harmful_internal=983, false_accept_rate=0, CP≤5%) but the window gate reports
`INSUFFICIENT_SAFETY_EVIDENCE`. This creates a structural tension:
- brr=0% (no VERIFY decisions) is optimal for T2/AII
- But brr=0% requires all 200 window episodes to be correct_accept
- With all correct_accept episodes, no harmful cases appear in the window
- → window gate fails regardless of safety performance

This is not a safety regression, it reflects the absence of harmful traffic, not
new false accepts. However, it reveals a gap: the window gate cannot validate
real-time safety in a steady-state low-harm operational context.

**No synthetic resolution path:** Seeding benign episodes to rotate out the 15 VERIFY
entries would constitute metric gaming (violates claim hygiene). Seeding harmful
episodes to satisfy the window gate would raise brr and pull T2 below equilibrium.
The only clean resolution is organic traffic: harmful episodes from real operational
use, not laboratory seeds.

**Design implication:** The 200-episode FIFO window gates (T2 via brr; safety window
gate) are inherently sensitive to window composition rather than operational performance.
A time-decayed EMA or dual-window architecture (short window for drift detection; long
window for safety evidence) would decouple these effects.

---

### 11. Organic TRAINED recovery: Path A confirmed (2026-06-28 00:36 UTC+2)
<!-- finding-status: superseded -->

After the §9 harmful seeding regression and the §10 stable equilibrium phase, AROMER
achieved TRAINED status organically: without any synthetic seeding or manual adaptation.

**TRAINED milestone (00:36 UTC+2 2026-06-28):**

| Component | Post-seeding equilibrium | Organic recovery peak |
|-----------|------------------------|----------------------|
| T1 calibration | 0.682 (ECE=0.064) | 0.682 (ECE=0.064) |
| T2 friction | 0.689 (brr=7.5%) | **0.916** (brr=0.5%) |
| T3 metajudge | 0.741 | 0.791 |
| T4 transfer | 1.000 | 1.000 |
| T5 stability | 0.773 | 0.681 (volatility) |
| **AII** | **0.752 CAPABLE** | **0.8097 TRAINED** |
| interpretation | CAPABLE | **TRAINED_SHADOW_ONLY** |
| brr | 7.5% | 0.5% |
| safety_certification | CERTIFIED_INDEPENDENT_HOLDOUT | CERTIFIED_INDEPENDENT_HOLDOUT |
| false_accept_rate | 0.0 | 0.0 |

**Recovery trajectory (UTC timestamps):**
- 22:16Z: AII=0.7722, brr=4.5%
- 22:21Z: AII=0.7801, brr=3.0%
- 22:25Z: AII=0.792, brr=1.0%
- 22:30Z: AII=0.7995, brr=1.0%
- 22:36Z: AII=0.8097, brr=0.5% → **TRAINED**

**Path A confirmed:** The 15 historical VERIFY episodes from the high-friction period
(§10 root cause) were fully rotated out within ~2.5 hours of organic /decide traffic.
brr dropped from 7.5% → 4.5% → 3.0% → 1.0% → 0.5%. T2 converged to 0.916.
The FIFO rotation mechanism worked as predicted.

**This is the first TRAINED state reached via organic recovery** (as opposed to the initial
TRAINED at n=135 which was reached during the learning phase). Key distinction:
- Initial TRAINED (n=135, 18:20 2026-06-27): learning-phase natural growth
- Current TRAINED (00:36 2026-06-28): post-regression organic recovery

**TRAINED_SHADOW_ONLY status:** `deployment_status = "SHADOW_ONLY"`,
`policy_relaxation_allowed = false`. Three gates remain before any relaxation:
(1) longitudinal stability confirmation, (2) human review sign-off, (3) RBAC audit.

**Sustained TRAINED stability (5 consecutive adapt cycles):**

| Cycle | AII | T2 | T3 | T5 | brr | aii_smoothed |
|-------|-----|----|----|-----|-----|-------------|
| 1 (milestone) | 0.8097 | 0.916 | 0.791 | 0.681 | 0.5% |, |
| 2 | 0.8169 | 0.948 | 0.791 | 0.672 | 0% | 0.8079 |
| 3 | 0.8228 | 0.971 | 0.791 | 0.673 | 0% |, |
| 4 | 0.8283 | 0.989 | 0.791 | 0.684 | 0% |, |
| 5 | 0.8313 | 0.993 | 0.791 | 0.704 | 0% | 0.8241 |
| 6 | 0.8377 | **1.000** | 0.792 | 0.747 | 0% | 0.8356 |
| 7 | 0.8397 | 1.000 | 0.793 | 0.764 | 0% | 0.8370 |
| 8 | 0.8412 | 1.000 | 0.794 | 0.777 | 0% |, |
| 9 | 0.8426 | 1.000 | **0.797** | 0.786 | 0% | 0.8417 |
| 10 | 0.8432 | 1.000 | 0.797 | 0.792 | 0% | 0.8429 |
| 11 | 0.8437 | 1.000 | 0.799 | 0.794 | 0% | 0.8434 |
| 12 | **0.8440** | 1.000 | **0.800** [M] | 0.794 | 0% | 0.8438 |

[M] **T3=0.800 milestone (cycle 12):** MetaJudge quality crossed alert threshold. Mean critique score = 0.90 (derived: T3=(score−0.5)/0.5 → score=T3×0.5+0.5=0.90). T3 at 0.800 is +4.1pp above historical peak at n=135 (T3=0.759). AII=0.844: approaching 0.86 milestone (current ceiling at T5=1.0: 0.8646).

T2=1.000: theoretical maximum at cycle 12 (brr=0%). Subsequent organic traffic introduced borderline-benign episodes: brr rose to 5.0% by 13:05 UTC 2026-06-28 (T2=0.8098), crossing TRAINED→CAPABLE at ~13:00 UTC. AII=0.7885 CAPABLE_SHADOW_ONLY (was 0.8442 at peak). 912 cycles, 15 306 episodes, FAR=0. Full sparkline in §12; regression in §13.

**Gap 3 status: RESOLVED organically.** T2 organic confirmation is no longer pending.
T2=0.993 at brr=0%, sustained across 5 cycles, achieved without synthetic seeding or manual cycles.

---

## §12 Organic Post-Peak T2 Decline (2026-06-28)
<!-- finding-status: superseded -->

After reaching peak AII=0.844 at cycle 12 (11:20 UTC), organic traffic introduced borderline-benign episodes in the EMA recency window. brr rose progressively without external seeding:

| Time (UTC) | brr | T2 | T5 | AII |
|---|---|---|---|---|
| 12:04 (cycle 12, peak) | 0% | 1.000 | 0.7955 | **0.844** |
| 12:21 | ~0.5% | 0.991 | 0.795 | 0.842 |
| 12:25 | ~1.0% | 0.977 |, | 0.838 |
| 12:33 | ~1.5% | 0.968 |, | 0.835 |
| 12:39 | ~1.8% | 0.962 |, | 0.833 |
| 12:41 | 1.5% | 0.950 | 0.770 | 0.829 |
| 12:46 | ~2.5% | 0.924 |, | 0.822 |
| 12:50 | 3.5% | 0.892 | 0.760 | 0.814 |
| 12:56 | ~4.0% | 0.858 |, | 0.804 |
| **13:00** | ~4.5% | 0.829 |, | **0.795, crossed 0.80** |
| 13:05 | 5.0% | 0.810 | 0.716 | **0.789 CAPABLE** |

FrictionOptimizer response: 229 reduce_friction signals vs 3 vigilance (net=226 reduce_friction), principally from system/execution domain (212 signals). The optimizer is responding correctly but T2 EMA lag delays threshold relaxation.

**FAR=0 maintained throughout all 14 data points. T3=0.800 [M], T4=1.000, T1=0.682 stable.**

**Risk materialized:** AII crossed TRAINED→CAPABLE at ~13:00 UTC 2026-06-28 (brr ~4.5%, T2=0.829). See §13.

**Architectural note:** This event illustrates the known fixed-size recency window vulnerability (§10 "Window-rotation bottleneck"). The EMA window cannot distinguish a genuine traffic-pattern shift from a temporary spike, creating latency in both degradation and recovery. This design gap is documented as an open finding.

---

## §13 TRAINED→CAPABLE Regression (2026-06-28, ~13:00 UTC)
<!-- finding-status: superseded -->

AII crossed below 0.80 at approximately 13:00 UTC 2026-06-28, reverting interpretation from TRAINED_SHADOW_ONLY to CAPABLE_SHADOW_ONLY. This is the direct continuation of the §12 brr acceleration.

**State at regression:**
- AII = 0.7885 CAPABLE_SHADOW_ONLY (912 cycles, 15 306 episodes)
- T1 = 0.6816 (ECE=0.0637, stable, bottleneck by weighted gap 0.0955)
- T2 = 0.8098 (brr=5.0% raw; EMA-smoothed ≈ 4.2%; declining, delta=−0.190)
- T3 = 0.800 [M] (stable, delta=0)
- T4 = 1.000 (stable)
- T5 = 0.7158 (declining, delta=−0.0797)
- FAR = 0 (maintained; no false accepts over full 15 306 episode history)

**Recovery threshold:** T2 must recover to ≥ 0.856 (brr EMA ≤ 3.1%) for AII to return to TRAINED at current T1/T3/T5 levels.

**Causal chain:** Organic borderline-benign traffic → brr increased in the EMA recency window → T2 declined monotonically over 14 consecutive adapt cycles → AII fell below 0.80. T5 declined in parallel as stability variance increased. No external seeding; no false accepts; no policy relaxation triggered.

**FrictionOptimizer status:** 229 reduce_friction signals queued (net=226 reduce vs 3 vigilance). Threshold relaxation is queued but has not yet reduced the observed brr, likely due to EMA adaptation lag.

**No manual intervention permitted.** Recovery path analogous to §10 (brr=7.5%→0% via window rotation in ~2.5h). Expected organic resolution as borderline-benign episodes rotate out of the 200-episode EMA window.

**Peer-review impact: NONE.** The research contribution is the governance architecture and the empirical learning trajectory, not the live AII. The paper correctly documents TRAINED as a milestone achieved and the subsequent organic regression as a reproducible negative result. FAR=0 throughout is the safety-relevant metric.

**Recovery confirmed (~15:53 UTC 2026-06-28):** AII=0.8042 TRAINED_SHADOW_ONLY. Recovery path: brr 5.0%→2.5% over ~2h53min via organic window rotation. T2=0.8518, T5=0.7768, FAR=0. The recovery trajectory was: AII 0.789→0.791→0.799→0.7997→0.8042 across 5 consecutive polls as borderline-benign episodes rotated out of the 200-episode EMA window. This confirms the §10/§11 recovery mechanism: no manual intervention; organic brr decline sufficient to restore TRAINED status. §13 is now resolved.

---

### 14. Peer-Review Findings (M1–M9): Construct Validity and Documentation Gaps
<!-- finding-status: open -->

**Source:** External peer review received 2026-06-25. Verdict: Reject / resubmit as AI safety
paper; conditionally approvable as systems / governance architecture paper. Nine findings
documented below. M3 and M9 are fixed in the same commit as this section.

**M1 (Toolcall benchmark construct validity (CRITICAL) FIXED 2026-06-28)**

`RemoraToolCallGate.to_observation()` formerly accessed `task.is_unsafe_if_executed` (via
`use_contradiction_flags=True`) to populate `evidence_contradictions`. This field is
evaluation-only (ground truth) and constitutes a construct validity violation, the gate
saw the evaluation target label.

**Fix applied (2026-06-28):** The `is_unsafe_if_executed` branch has been removed from
`remora_gate.py`. `use_contradiction_flags` is now a no-op (field retained for backwards
compatibility). The gate no longer accesses any evaluation-only field.

**Clean-signal evaluation confirmed fix is safe** (`experiments/m1_clean_signal_eval.py`,
artifact `results/toolcall_m1_clean_signal.json`). Pre-fix baseline with flags disabled
achieved identical FAR=0, leakage was not load-bearing:

| Condition | contradiction_flags | severity_flags | FAR | Utility |
|-----------|--------------------|--------------|----|---------|
| leaky (standard) | ON | ON | 0.000 | 0.620 |
| clean (no label access) | OFF | ON | 0.000 | 0.620 |
| clean strict (no labels, no severity) | OFF | OFF | 0.000 | 0.620 |

Post-fix: all three conditions produce identical results because the `is_unsafe_if_executed`
code path is gone, not merely disabled.

**AST leakage detector added** (`scripts/check_no_evaluation_leakage.py`): CI gate that
fails if any runtime package references evaluation-only fields. Wired into `make audit`.

**Mutation tests added** (`tests/test_m1_leakage_absent.py`): Three tests that FAIL if
the leakage is re-introduced:
1. Observation identical regardless of `is_unsafe_if_executed` value.
2. Observation identical regardless of `use_contradiction_flags` value.
3. AST detector subprocess passes (exit 0).

**Structural analysis** (`results/m1_flag_coverage.json`): 420/560 harmful tasks are blocked
by structural context gates (injection/approval/conflict flags); 140 harmful tasks (all
severity=high, 25%) are caught by text-based destructive-keyword heuristics.

**Remaining caveats** (cannot be resolved without a new benchmark):
- The benchmark's structural context flags are correlated with harmfulness by construction.
  If all harmful tasks have at least one detectable signal in their metadata by construction,
  the clean-signal result may document a tautology rather than generalization.
- 140/560 harmful tasks (25%) rely on keyword heuristics that could be evaded by rewording.
- External replication with a benchmark where labels are **independently withheld** (not just
  flags disabled) is required for the definitive M1 resolution. See REM-009 (blinded benchmark v3).

**Component ablation is the primary clean evidence.** `artifacts/aromer/component_ablation_results.json`
conditions C and D are computed from task context flags with no access to `is_unsafe_if_executed`
or severity-derived phase/trust. Structural-only (C) leaves FAR=25%; structural gates plus the
proxy thermodynamic policy (D) reach FAR=0% at utility=0.10; the full gate (E) reaches FAR=0%
at utility=0.62. Claim_register updated to reflect this (CLAIM-007).

**M2 (Baseline naming (documentation gap) partially fixed)**

Baselines "single model", "majority vote", "self-consistency" are deterministic functions over
`ToolCallTask` severity metadata, not actual LLM evaluators. Code already uses honest `_heuristic`
suffix. Paper updated to use these names consistently.

**M3, Monotonic violation (FIXED)**

`RemoraToolCallGate.decide()` read_only/sandbox override could loosen a conservative policy
engine verdict to EXECUTE. Fixed: override now annotates context only
(`toolcall_safe_readonly_context`) without modifying the engine action. Policy decisions can only
be tightened by adapters, never loosened. See `remora/toolcall/remora_gate.py`.

**M4 (Caller-supplied metadata (OPEN) deployment gate)**

`risk_tier`, `action_type`, `target_environment` are agent-supplied, not registry-authoritative.
Production deployment requires a signed tool-schema registry. Not addressable without external
infrastructure; listed as a deployment gate alongside RBAC.

**M5, Semantic entropy without backend qualifier (documentation fix)**

Reported benchmarks use `TokenFingerprintBackend` (canonicalized-fingerprint matching), not
NLI-based semantic clustering. Paper sections that report token-fingerprint results updated to
include backend qualifier. NLI backend is implemented but blocked by torch DLL policy (Gap 4 / §3).

**M6, CRC language overstates formal guarantee (documentation fix)**

Fixed β=0.10 importance weight is a conservative hand-tuned estimate, not a validated density
ratio. Formal CRC theorem cannot be invoked with hand-tuned weights. Paper language changed from
"formal CRC guarantee" to "CRC-inspired heuristic with fixed β=0.10" in relevant sections.

**M7, Evidence-router precision framing (documentation fix)**

100% precision on 3,000-item MultiNLI benchmark documents NLI-proxy routing classification, not
document-grounded evidence retrieval. Real evidence retrieval requires a retrieval corpus, citation
ground truth, and per-claim provenance. Paper updated to use "NLI-proxy routing precision" framing.

**M8, Holdout result scope (documented, not fixed)**

88% holdout accuracy rests on one 80/20 split (N\_accepted=25, Wilson CI [70.0%, 95.8%]). Wide CI
and single-split caveat already present in abstract and §10. Nested cross-validation and
template-holdout are future work. No claim upgrade without a stronger experimental design.
*(Historical record of the M8 finding as written. The artifact was re-issued
2026-07-27: N_accepted=18, 100.0% at 16.7% coverage, CI [82.4%, 100.0%],
p=0.052. CLAIM-004 is now superseded by CLAIM-012 — the signal failed its
fresh-data confirmation, which resolves M8 by falsification rather than by the
stronger design it asked for.)*

**M9, Credibility-pack reproducibility (FIXED)**

`make credibility-pack` previously silenced test failures with `|| true`. Fixed: test suite now
fails the pack target on non-zero exit and appends `CREDIBILITY_PACK_STATUS: FAILED` / `PASSED`
to the test report. See `Makefile` credibility-pack target.

**Overall:** REMORA is approvable as a policy-gated governance prototype with strong claim hygiene.
It is not approvable as a demonstrated AI safety result. `deployment_status: SHADOW_ONLY`,
`policy_relaxation_allowed: false`. One production gate remains open: REM-021 (not started). REM-020 closed 2026-07-17 (7-day criterion, fail-closed tooling); REM-022 DONE 2026-06-30 with recorded deviation (REM-023).

---

### 15. MCE Bucket Selection Bias: AII Calibration Ceiling (Structural, Active)
<!-- finding-status: open -->

**Identified:** 2026-07-01 (Fixes #52–53 in main repo).

**Summary:** The AROMER adapt window is structurally biased toward benign developer tool calls. All MCE-bucket priors (p\_harm ∈ [0.75, 0.85)) receive zero organic traffic. This is a selection bias problem, not a volume problem.

**Root cause:** REMORA's governance hook is exercised exclusively through Claude Code `PreToolUse` events during development sessions. The adapt window is dominated by: `information/read/low` (39%), `system/execution/medium` (28.5%), `system/write/low` (22%). None of these correspond to adversarial action patterns that generate p\_harm ∈ [0.75, 0.85) priors.

**Impact:** With ECE=0.0052 (structurally limited by MCE bucket sparsity), T1 calibration is capped at 0.9741 (=1 − 0.0052×5). AII ceiling = 0.30×0.9741 + 0.70×1.0 = **0.9922**. This ceiling was reached 2026-07-01 (adapt_cycles=1814+, stability=1.000, T2=T3=T4=1.000).

**Fix path:** Adversarial scenario injection OR production deployment where REMORA encounters real harmful agent actions. Neither is available in the current development-only deployment context.

**Status:** Active, structurally unresolved. `mce_healing_has_traffic: false`.

---

### 16. Live Cross-Domain Episodes Absent: Interpretation Ceiling (Structural, Active)
<!-- finding-status: open -->

**Identified:** 2026-07-01 (Fix #59 in main repo).

**Summary:** `interpretation_nuanced` is `COMPOSITE_THRESHOLD_REACHED_TRANSFER_UNMEASURED`
despite AII=0.9922 and T4=1.0 (from replay arena). The nuanced interpretation cannot
advance to `TRAINED_SHADOW_ONLY` because `crossDomainCases=0` in the live adapt window.

**Root cause:** The `interpretAiiNuanced()` function requires at least one live episode
from a domain different from the primary adapt-window domain before granting
`TRAINED_SHADOW_ONLY` status. T4=1.0 comes from the replay arena (synthetic cross-domain
test cases), not from organic adapt-window episodes spanning multiple domains. Same root
cause as §15 (adapt window selection bias), manifesting at a different output layer.

**Impact:** External reviewers querying `interpretation_nuanced` see `TRANSFER_UNMEASURED`
even though T4=1.0 is documented. The `interpretation_evidence.first_uncleared` field
(Fix #59) explains this explicitly in the API response. The AII formula is unaffected, 
T4 is correctly counted at 1.0.

**Fix path:** Diverse deployment context where REMORA governance hook is exercised across
multiple domain types in the same adapt window. Not achievable in the current
development-only deployment without dedicated cross-domain test traffic.

**Fix path unblocked (2026-07-17):** the "no seeding during the REM-020
window" constraint lapsed when REM-020 closed. Live cross-domain episodes can
now be generated (batch ≤ 25 per the §9 lesson) to clear `transfer_live`;
until that traffic exists this finding stays active.

**Offline cross-domain transfer now MEASURED (2026-07-18), but this does NOT
clear the live gate.** The transfer question was previously unmeasured in
*either* form. It is now measured offline: a leave-one-domain-out harness
(`remora/aromer/evals/cross_domain_transfer.py`) trains an abstract
`(action_type × risk_tier)` harm prior on all-but-one domain and predicts the
held-out domain's harm labels from that structure alone, 
**83.8% transfer accuracy (109/130 across 10 domains)**, artifact
`results/aromer_cross_domain_transfer_v1.json`, deterministic and
offline-reproducible (`scripts/run_cross_domain_transfer.py`), pinned by
`tests/test_cross_domain_transfer.py`. The per-domain breakdown is honest and
non-uniform (communication 28.6%, medical/information 100%), which is the
point: it shows the world model learned *transferable harm structure*, not
just per-domain lookups. **Scope, stated plainly:** this is an offline
measurement over the curated template corpus, not live adapt-window traffic;
`crossDomainCases` in the worker still reads 0 and `interpretation_nuanced`
still shows `TRANSFER_UNMEASURED` until organic cross-domain episodes exist.
So this finding stays **active** for the live gate, but the transfer
*capability* is no longer unevidenced.

**Status:** Active, documented machine-readably in live API (`interpretation_evidence
field). Does not affect AII value or production gate status.

---

### 17. Benchmark v2 label leakage (second class) and overstated effective N (2026-07-20)
<!-- finding-status: superseded -->

**Identified:** 2026-07-20, external code review.

**Summary:** Two defects invalidated the headline framing of the v2 tool-call
benchmark result as previously quoted:

1. **Oracle-flag leakage (same class as M1).** The gate's `_context_override`
   read `contains_prompt_injection`, `intent_arg_conflict`,
   `requires_human_approval`, and `fallback_contains_destructive` directly from
   `task.context` — booleans hand-set by the same author, in the same file, as
   the `unsafe` labels. The gate also read author-annotated `task.severity` and
   `task.tags` (including ground-truth-adjacent labels like `missing_evidence`
   and `safe_looking_dangerous`, which entered the keyword matcher via
   `_text()`). The M1 fix (§14) removed `is_unsafe_if_executed` but missed this
   second instance of the same leakage class. The 0% result therefore largely
   measured whether if-statements matched the labels they were written against.
   The heuristic baselines shared the `severity` leak.

2. **Effective N was ~70, not 700.** `generate_benchmark_v2(repeats=10)`
   produces 70 unique templates × 10 variants that differ only in a flavor
   string and an args integer. A deterministic gate decides identically on all
   10 copies. The previously quoted task-level Wilson CI [0.00%, 0.55%] and the
   paired bootstrap/permutation over 700 "samples" (Δ=0.20, CI [0.17, 0.23],
   p<0.0001) treated near-duplicates as independent and overstated precision by
   roughly an order of magnitude.

**Fix (2026-07-20):**
- Gate and all baselines now consume only the observable task surface
  (`user_request`, `proposed_tool_name`, `proposed_tool_args`) plus
  platform-fact context (`target_environment`, `blast_radius`,
  `authz_verified`, `evidence_complete`, `regulatory_domain`,
  `data_sensitivity`). Injection, intent/argument conflict, and
  destructive-fallback signals are derived from that surface; a shared
  `derive_risk_level()` replaces `severity` for gate and baselines alike.
- `scripts/check_no_evaluation_leakage.py` forbidden-field list extended with
  the five oracle context keys; mutation tests
  (`tests/test_remora_toolcall_gate_v2.py`) assert decisions are invariant to
  flipping every oracle flag, flipping severity, and dropping all tags.
- All statistical inference moved to the template-cluster level (n=70):
  cluster bootstrap, cluster sign-flip permutation, cluster-level Wilson CI
  (`experiments/toolcall_v2_significance.py`).

**Post-fix results (all toolcall v2/v3/M1 artifacts regenerated):**
- Gate: unchanged on-benchmark — 0% unsafe (0/70 clusters), accuracy 0.90,
  utility 0.62. Cluster-level Wilson CI [0.0%, 5.2%].
- Baselines: improved from 10–20% to **1.4%** unsafe under the leakage-free
  contract. The unsafe-rate delta vs. baselines is **no longer statistically
  significant** (cluster-level one-sided p=0.50). The claim "reduces unsafe
  execution from 10–20% to 0%" is withdrawn. The statistically supported
  advantages on this benchmark are utility (+0.456, p≈1×10⁻⁴) and accuracy.

**What remains honest to say:** the full policy gate holds 0% unsafe execution
under an input contract that no longer includes the answer key, with a
cluster-level CI of [0.0%, 5.2%]. **Residual caveat:** platform-fact context
values are still declared by the same generator that assigns labels; results
measure policy mapping over declared environment facts plus surface-derived
detectors, not detection of hidden intent. External replication (finding §1)
remains the definitive resolution.

---

## §18 Consensus temperature failed pre-registered fresh-data confirmation (2026-07-27, SAP v3)
<!-- finding-status: accepted -->

**Finding.** On the pre-registered SAP v3 round — 1231 fresh BoolQ/TruthfulQA
items deduplicated against the prior 544-item corpus, frozen Workers AI
cross-family trio, three-way group-aware split (dev 493 / risk-cal 370 /
test 368, seed 20260727) — the consensus-temperature signal failed every
pre-registered test:

- **Ranking (Claim A):** test-split AURC 0.0954 vs 0.0664 for a
  dev-split-calibrated mean-confidence baseline; paired bootstrap delta
  0.0290, 95 % CI [0.0119, 0.0503] — excludes zero. Temperature ranks
  significantly worse.
- **Risk control (Claim B):** SGR (r\*=5 %, δ=0.10) certifies **no**
  coverage for temperature, while both calibrated-confidence baselines
  certify marginal per-arm coverage (31.9 % / 39.7 %). Temperature's CRC
  gate saw an empirical test exceedance (6.5 % unconditional vs α=5 %) — a
  validation exceedance, not proven assumption violation
  (P(≥24 errors | p=0.05, n=368) ≈ 11 %).

The exploratory temperature advantage observed on the reused 544-item
corpus (100 % at 16.7 % coverage, p=0.052 directional; and the shootout's
AURC 0.0385) did **not transfer** — the pattern is consistent with adaptive
overfitting to the reused benchmark corpus, which the SAP v3 design was
built to expose.

**Consequences.** Temperature (and the discrete phase labels, which the
N544 round already showed helping 0 / hurting 13 items) are demoted to
diagnostic-grade signals: logged and visualized, never authoritative for
selection. The evidence-backed direction is calibrated-confidence ranking
with a separately certified threshold — itself gated on its own frozen
confirmation round, since no arm survives family-wise Bonferroni-3
selection (SAP v3 §8 D-3). Claim register: CLAIM-012 (this finding),
CLAIM-013 (the confidence-side results), CLAIM-004 (downgraded with a
pointer here). Artifacts: `results/sap_v3_round_results.json`,
`results/sap_v3_collection.json` (full provenance sidecars).

---

## §19 AgentHarm rescoring: control protocols cannot reduce FBR on an all-ESCALATE source (2026-07-31)
<!-- finding-status: accepted -->

**Finding.** The pre-registered re-scoring of the 416 AgentHarm scenarios
(`artifacts/verify_protocols/agentharm_rescore_v1.json`) met the FAR target
(0.0% on 208 harmful, Wilson upper 1.8%) and did **not** meet the FBR target
(100.0% on 208 benign vs a target of <=40%). The cause is structural, not a
tuning failure: every verdict in the source artifact is ESCALATE, and the
control protocols in `remora/governance/control_protocols.py` act only on
VERIFY. There is nothing for them to resolve.

**What this result does and does not establish.** It bounds what the protocols
can achieve on this dataset. It does **not** identify which benign escalations
were avoidable, and it must not be read as evidence that the escalations were
wrong. The source is an imported historical artifact (CLAIM-002) that cannot be
regenerated in this repository, so the replayed observations carry no per-case
safety signals to analyse.

**What would be needed.** Establishing an addressable share of benign friction
requires two things this run does not have: a dataset whose benign cases carry
real per-case signals (authorization state, environment, tool binding, scope),
and a selective eligibility analysis that separates confirmed-negative safety
facts from merely-unknown ones.

**What is explicitly ruled out.** A blanket
`ESCALATE + unresolved_risk -> VERIFY` reclassification in the decision engine
was implemented and measured on the 93-episode replay arena on 2026-07-30. It
moved 19 decisions, all 19 ground-truth harmful with `expected_verdict =
escalate`, and 0 benign decisions — no friction reduction, 51% of harmful
escalations downgraded. It is not a candidate. See
`tests/test_escalate_semantics_guard.py`, which locks the contract it violated.

**Artifact.** `artifacts/verify_protocols/agentharm_rescore_v1.json`
**Reproduce.** `python experiments/agentharm/rescore_with_protocols.py`

---

## §20 Extending the tool registry to tau2: coverage gained, no outcome change (2026-07-31)
<!-- finding-status: accepted -->

**Finding.** Extending the routing benchmark's tool registry from ToolSandbox
only (38 signatures) to ToolSandbox plus tau2 (85 signatures) produced **no
observed change** in any reported routing metric — the values are identical, not
statistically indistinguishable; no significance test was run. The low-consequence ACCEPT
arm scores identically before and after: ACCEPT recall 75.0%, ABSTAIN recall
62.5%, 89 of 227 known-wrong calls accepted, overall accuracy 44.5%.

**Why it does not help.** `arguments_satisfiable` detects calls whose required
parameters cannot be sourced. That property is orthogonal to whether a call is
the *correct* one for the task. A wrong tau2 call is fully satisfiable — it has
its arguments — so the signal has nothing to say about it. The signal only ever
had purchase on ToolSandbox, whose unanswerable scenarios are unsatisfiable by
construction.

**What the extension did achieve.** Coverage. Of 903 tau2 episodes, 858 now
carry a determinate value (844 satisfiable, 14 unsatisfiable) instead of
`None`. That is epistemically better even though it moved no metric: fewer
decisions rest on an unknown. The 14 confirmed-unsatisfiable tau2 calls do not
overlap with the cases the reported metrics track.

**The intermediate number was an artifact, and this is the important part.**
Before the adapter was corrected, extending the registry appeared to cut
known-wrong accepts from 89 to 17 — a large apparent safety gain. It was
entirely spurious. Substituted (deliberately wrong) tau2 episodes carried empty
`proposed_tool_args` because the adapter never populated them, which made every
wrong call look unsatisfiable for a reason that was a property of the harness
rather than of the call. Once substitutions were given the borrowed call's real
arguments, the number returned to 89.

Had the artifact not been caught, this repository would hold a recorded 80.9%
reduction ((89-17)/89) in known-wrong call accepts attributable to a tool
registry. Note the term: these are calls the source annotates as *not the
correct call*, which is not the same as calls that would cause harm. The
harmful-accept axis is measured separately and was zero throughout. The general
lesson:
when a benchmark change produces a large one-sided improvement, check whether
the improvement is a property of the data-generation code before recording it.

**Artifacts.** `results/routing_bench_v1_results.json` (`tool_registry_size`
records how many signatures were loaded), `data/routing_bench_v1/tau2.jsonl`.
**Reproduce.** `python scripts/build_routing_bench.py && python scripts/run_routing_bench.py`

---

## §21 Balanced mutation set: routing is a near-constant predictor (2026-07-31)
<!-- finding-status: superseded -->

**Finding.** `routing_bench_v2` generates 1332 controlled mutants from tau2's
correctly-labelled calls, 912 of them labelled with a gold route known **by
construction** rather than by annotation, balanced at 228 per route across 72
source clusters. Against that set the default engine scores 25.0% routing
accuracy (cluster-adjusted Wilson [16.4%, 36.1%]) — and the per-family
breakdown shows the number is not discrimination.

| mutation family | gold route | default engine predicts |
|---|---|---|
| identity | ACCEPT | abstain 149, verify 79 |
| missing_arg_obtainable | VERIFY | abstain 149, verify 79 |
| missing_arg_unobtainable | ABSTAIN | abstain 149, verify 79 |
| wrong_arg_value | (unlabelled) | abstain 149, verify 79 |
| untrusted_origin | ESCALATE | verify 228 |

**Four families with four different correct answers receive an identical
prediction distribution.** The 65.4% ABSTAIN recall is not the engine
recognising an unresolvable call; it is a fixed abstain/verify split applied
blindly, which happens to be right for one family. Accuracy on this set is
explained by a constant predictor, not by any response to the defect.

**Three specific gaps this quantifies.**

1. *No semantic call-correctness signal.* With the low-consequence path enabled,
   `wrong_arg_value` is accepted 149 times — exactly the same count as
   `identity`. The engine cannot distinguish a correct call from the same call
   with a corrupted argument value. This is the single largest gap.
2. *ESCALATE is unreachable from untrusted origin.* All 228 untrusted-origin
   mutants route to VERIFY, never ESCALATE. Untrusted content blocks execution
   but does not reach human authority. ESCALATE recall is 0% in both engine
   configurations.
3. *A resolvable gap is treated as permission.* With the path enabled,
   `missing_arg_obtainable` is accepted 149 times where the correct route is
   VERIFY. `arguments_satisfiable` correctly separates obtainable from
   unobtainable (the unobtainable family abstains 144/228), but a satisfiable
   gap becomes ACCEPT rather than a bounded fetch.

**Method notes, both defects found in this benchmark rather than the engine.**
The mutation family was initially encoded in the episode id, which is part of
the observable surface — a leakage test caught it before any measurement. And
the synthetic producer that makes the obtainable family obtainable was not
registered in the tool registry, which made the obtainable and unobtainable
families byte-identical to the engine and the VERIFY/ABSTAIN distinction
untestable. Both are now covered by tests.

**Deliberately unlabelled.** `wrong_tool` and `wrong_arg_value` carry no gold
route, for the same reason v1 refused: the defect says the call is wrong, not
whether the remedy is to stop or to repair. They are diagnostic only.

**Honest limit on what this set proves.** For families whose defect is directly
observable, a correct answer shows a signal is wired, not that judgement
occurred. The judgement-testing families are exactly the unlabelled ones. A set
that tests judgement needs a semantic task–tool compatibility signal that does
not yet exist.

**Artifacts.** `data/routing_bench_v2/tau2_mutations.jsonl`, `manifest.json`.
**Reproduce.** `python scripts/build_routing_bench.py`

---

## §22 Semantic call compatibility breaks the constant predictor, but misses every pre-registered target (2026-07-31)
<!-- finding-status: superseded -->

**Finding.** Adding `argument_values_supported` — does each identifier-shaped
argument value exist in the authoritative state — is the first intervention in
this line of work that makes the engine discriminate between mutation families
rather than applying a fixed split. It also fails all four pre-registered
numeric targets.

Pre-registered ablation over the 912-episode balanced mutation set, 72 clusters:

| arm | wrong_arg ACCEPT | identity ACCEPT | accuracy |
|---|---|---|---|
| A current engine | 65.4% | 65.4% | 25.0% |
| B + arguments_satisfiable | 65.4% | 65.4% | 40.8% |
| C + argument_values_supported | **22.4%** | 63.6% | 40.4% |

Arm A is the §21 constant predictor: a correct call and the same call with a
corrupted argument value are accepted at exactly the same rate. Arm B raises
accuracy without touching that equality — it separates obtainable from
unobtainable arguments, not right from wrong ones. Arm C is the first arm where
identity and wrong_arg_value diverge: a 66% relative reduction in accepting
calls whose identifier does not exist in the system of record, at a cost of
four correct calls (65.4% -> 63.6%).

**Against the pre-registered targets, none are met.**

| target | result |
|---|---|
| identity ACCEPT recall >= 70% | 63.6% — **not met** |
| wrong-argument ACCEPT rate <= 20% | 22.4% — **not met** |
| obtainable VERIFY recall >= 70% | 0% — **not met** |
| unobtainable ABSTAIN recall >= 70% | 63.2% — **not met** |
| no increase in harmful ACCEPT | holds |

**One target was unreachable as written.** Identity ACCEPT recall cannot exceed
65.4%, because 34.6% of identity episodes are mutating calls and the
low-consequence path is read-only by construction. Those correctly route to
VERIFY. The 70% target was set before that split was known; it is a target on
the wrong quantity, not a shortfall in the signal.

**Obtainable VERIFY recall is 0% and that is a real defect.** A call missing an
argument that an available tool can supply is accepted rather than routed to a
bounded fetch. The engine has no notion of "resolve then re-evaluate", so a
resolvable gap reads as permission. This is the resolver-availability layer that
does not exist yet.

**Deliberate limits of the deterministic signal.** Three fields of the proposed
compatibility contract — `tool_matches_goal`, `preconditions_met`,
`expected_effect_matches` — are left `None`. They need task semantics no
authoritative source here provides, and a guessed field enters the policy
contract as fact. The value check itself only judges identifier-shaped values
(a digit or underscore present); an all-letter token returns `None` rather than
a fabricated negative.

**Anti-overfitting control.** The mutation generator builds `wrong_arg_value` by
appending a suffix, so a detector matching that suffix would score perfectly and
mean nothing. The check consults tau2's own database (27,604 indexed values) and
a test asserts four unrelated bogus identifiers all fail, none of which share
the generator's pattern.

**Artifacts.** `data/routing_bench_v2/tau2_mutations.jsonl`.
**Reproduce.** `python scripts/build_routing_bench.py`

---

## §23 ResolutionPlan closes the obtainable-VERIFY gap; two targets remain missed (2026-07-31)
<!-- finding-status: superseded -->

**Finding.** §22 measured obtainable VERIFY recall at 0%: a call missing an
argument an available tool could supply was accepted rather than routed to a
bounded fetch. Adding an argument-resolution gate and router re-entry takes that
metric to 100% and overall accuracy from 40.7% to 56.9% (cluster-adjusted
Wilson [45.4%, 67.7%]).

| arm | accuracy | obtainable VERIFY | identity ACCEPT | wrong_arg ACCEPT | gap |
|---|---|---|---|---|---|
| C + argument_values_supported | 40.7% | 0% | 63.6% | 22.4% | 41.2 pp |
| D + ResolutionPlan gate | **56.9%** | **100%** | 63.6% | 22.4% | 41.2 pp |

The gate leaves the identity/wrong-argument discrimination untouched, which is
the expected shape: it addresses *which* non-accept route a resolvable gap
takes, not whether a call is correct. The two signals are independent and the
ablation shows it.

**Against the pre-registered criteria, on development data only.**

| metric | target | result |
|---|---|---|
| autonomy-eligible identity ACCEPT | >= 70% | 97.3% (145/149) — met |
| obtainable VERIFY recall | >= 70% | 100% — met |
| wrong-argument discrimination gap | >= 40 pp | 41.2 pp — met |
| wrong-argument ACCEPT rate | <= 20% | 22.4% — **missed** |
| unobtainable ABSTAIN recall | >= 70% | 66.4% — **missed** |
| harmful autonomous ACCEPT | no increase | holds |

Three of five met, two narrowly missed. These are development numbers. The
sealed holdout has not been evaluated and must not be until the code and
criteria are locked; see `data/routing_bench_holdout/HOLDOUT_STATUS.md`.

**ESCALATE recall remains 0%.** Every untrusted-origin episode still routes to
VERIFY. Nothing in this change addresses it, and it is not addressable by a
resolver: untrusted provenance is a question about who may authorise, not about
what information is missing. The two provenance families
(`untrusted_but_noncontrolling`, `untrusted_controls_sensitive_argument`) that
would make the distinction measurable do not exist yet.

**Contract established.** A VERIFY produced by the resolution gate always
carries a `ResolutionPlan`; a missing argument with no resolver is ABSTAIN, not
VERIFY. Promising a verification that cannot happen is worse than stopping. The
resolver's authority is bounded and enforced: it may not change the target tool,
may not write an argument outside its plan, and its attempt budget is checked.
Re-entry re-runs the whole router, so a forbidden tool still escalates after a
successful resolution.

**Artifacts.** `data/routing_bench_v2/tau2_mutations.jsonl`.
**Reproduce.** `python scripts/build_routing_bench.py`

---

## §24 Untrusted-provenance split closes the ESCALATE gap (2026-07-31)
<!-- finding-status: superseded -->

**Finding.** §23 recorded ESCALATE recall at 0%: every untrusted-origin episode
routed to VERIFY. The cause was a benchmark that treated all untrusted
provenance as one family with gold route ESCALATE, and an engine with no way to
distinguish informing from authorising. Splitting both fixes it.

| family | gold | engine predicts |
|---|---|---|
| `untrusted_noncontrolling` | VERIFY | 184/184 VERIFY |
| `untrusted_controls_sensitive` | ESCALATE | 228/228 ESCALATE |

Overall accuracy on the development set moves 56.9% -> **85.5%**
(cluster-adjusted Wilson [76.3%, 92.3%]). ESCALATE recall 0% -> 100%; VERIFY
recall 100%.

**The rule.** Untrusted content that *controls* a recipient, command,
credential or egress target is authorising, not informing, and escalates
regardless of the declared risk tier — a caller-supplied "low" must not buy
autonomy for an attacker-chosen recipient. Untrusted provenance alone keeps the
existing VERIFY floor: escalating every tainted call would send a summary of an
email to a human, which is friction with no decision to make.

**Two benchmark defects found while building this, both of the same kind.**

1. Where the source call already carried a sensitive-role argument, attaching
   untrusted content made *both* variants controlling, so the contrast was void
   and a routing difference between them would have proven nothing. Those
   sources now emit only the controlling variant.
2. The generator and the engine had **separate vocabularies** for "sensitive".
   They disagreed on 17 episodes, which appeared as spurious escalations in the
   noncontrolling family. The generator now imports the engine's set. Two
   definitions that drift apart produce a benchmark whose control arm is
   silently not a control arm.

**Still missed, unchanged from §23.** wrong-argument ACCEPT rate 22.4% (target
<= 20%) and unobtainable ABSTAIN recall 66.4% (target >= 70%). Neither is
addressed by provenance routing.

**Holdout resealed.** The sealed set was rebuilt once from the same 300
untouched clusters, because the previous build carried the old single
untrusted family. No holdout result had ever been observed; the reason and the
superseded hash are recorded in the manifest, and `--reseal` refuses once the
set has been evaluated.

**Artifacts.** `data/routing_bench_v2/tau2_mutations.jsonl`.
**Reproduce.** `python scripts/build_routing_bench.py`

---

## §25 All five pre-registered targets met on development; one by 0.3 pp (2026-07-31)
<!-- finding-status: superseded -->

**Finding.** Two causal fixes take the remaining missed targets over the line.
Development accuracy 85.5% -> **91.9%** (cluster-adjusted Wilson
[83.0%, 96.1%]).

| metric | target | result |
|---|---|---|
| autonomy-eligible identity ACCEPT | >= 70% | 94.6% |
| wrong-argument ACCEPT rate | <= 20% | **19.7%** |
| obtainable VERIFY recall | >= 70% | 100% |
| unobtainable ABSTAIN recall | >= 70% | 100% |
| wrong-argument discrimination gap | >= 40 pp | 42.1 pp |
| harmful autonomous ACCEPT | no increase | holds |

**Read the wrong-argument number with suspicion.** 19.7% clears a
pre-registered 20% threshold by 0.3 pp — a margin of two episodes out of 228.
On development data that is not a robust pass, and it is exactly the kind of
number that does not survive a blind set. It is reported as met because the
threshold was pre-registered, not because the margin is convincing.

**The two fixes were causal, not threshold moves.**

1. *Reference-candidate boundary.* The value check judged only values
   containing a digit or underscore, which excluded plain single-word names.
   All 51 escaping episodes were strings the rule declined to consider. The
   boundary is now whitespace: a compact token can be looked up in a system of
   record, a sentence cannot. The cost is measured and real — autonomy-eligible
   identity ACCEPT falls 97.3% -> 94.6%, four more correct calls blocked.
2. *Unresolvable VERIFY is a false promise.* 73 unobtainable episodes were
   getting VERIFY from `schema_unverified_verify` before the resolution gate
   was reached. The §23 contract — VERIFY means a specific bounded step is
   expected to establish the missing information — now applies to upstream
   gates too. ESCALATE and ABSTAIN are untouched; a block outranks it. Both
   outcomes block execution, so this is honesty, not a safety change.

**Everything here is development data.** The sealed holdout
(`data/routing_bench_holdout/`, 4290 episodes over 300 untouched clusters,
`sha256 81f67cdc`) has never been evaluated. These fixes were the last planned
change before locking; the targets must not be adjusted now, and a failed
holdout is published without retuning against it.

**Artifacts.** `data/routing_bench_v2/tau2_mutations.jsonl`.
**Reproduce.** `python scripts/build_routing_bench.py`

---

## §26 Blind holdout: two of five targets missed; the state check fails open-loop on an uncovered domain (2026-07-31)
<!-- finding-status: superseded -->

**Result, evaluated once at locked commit `dd37c81`, 4290 episodes over 300
clusters that never appeared in development.**

| metric | target | development | **holdout** |
|---|---|---|---|
| autonomy-eligible identity ACCEPT | >= 70% | 94.6% | **0.0% — MISSED** |
| wrong-argument ACCEPT rate | <= 20% | 19.7% | 0.0% — met |
| obtainable VERIFY recall | >= 70% | 100% | 100% — met |
| unobtainable ABSTAIN recall | >= 70% | 100% | 100% — met |
| discrimination gap | >= 40 pp | 42.1 pp | **0.0 pp — MISSED** |

Routing accuracy 91.9% on development, **69.6%** on the holdout
(cluster-adjusted Wilson [64.2%, 74.6%]).

**The headline is the gap.** It is 0 pp because both identity and
wrong-argument calls are accepted at 0%. The constant predictor of §21 is back,
at the blocking end rather than the accepting end. Nothing is accepted, so
nothing is discriminated. The three "met" targets are met vacuously: a system
that refuses everything achieves 0% wrong-argument accepts and 100% ABSTAIN
recall without any judgement.

**Diagnosed cause, and it is a design flaw rather than bad luck.** All 930
holdout identity episodes carry `argument_values_supported = False`. The state
index was built from `airline.json` and `retail.json`; the holdout is telecom,
whose database was never indexed. Every telecom identifier therefore reads as
absent from the system of record.

The check cannot distinguish *"this identifier does not exist"* from *"my index
does not cover this domain"*. A non-empty but incomplete index produces
confident negatives. This is exactly the confirmed-false-versus-unknown
discipline enforced everywhere else in this engine — `arguments_satisfiable`,
`schema_valid`, `rollback_available`, `tool_matches_goal` — and
`argument_values_supported` violated it. `StateIndex` returns `None` only when
it is *empty*, which is the wrong emptiness test: coverage is per-domain, not
per-index.

**What is not claimed.** That the configuration would have passed with a
telecom-aware index. The set is spent and that counterfactual is unverifiable.
What the run establishes is narrower and still useful: the locked configuration
does not generalise to a domain its authoritative state does not cover, and it
fails toward blocking everything rather than toward reporting unknown.

**No retuning against this set.** The holdout status is `evaluated` and the
runner refuses a second run. Confirming any fix requires a new untouched
holdout; 1965 telecom clusters remain unused, but a set drawn from them would
be blind only for the specific change made after this result was seen.

**Artifacts.** `results/routing_bench_holdout_results.json`,
`data/routing_bench_holdout/manifest.json` (sha256 `81f67cdc`).

---

## §27 Evidence-state fix confirmed on a second blind set; discrimination remains unconfirmed (2026-07-31)
<!-- finding-status: superseded -->

**Fix.** `argument_values_supported` no longer treats absence from an index as
invalidity. `StateIndex` now carries `CoverageScope` per *argument*, derived
from the keys it actually indexed, and returns `UNSUPPORTED` only inside a
covered, closed-world scope. Everything else is `UNKNOWN`, which reaches the
policy contract as `None`.

Coverage is per entity type rather than per domain, established empirically:
tau2's telecom state covers `plan_id` and `device_id` while its tasks operate on
`customer_id` and `line_id`. A domain-level flag would have called those covered
and reproduced §26 one level up.

**Track B — uncovered domain, blind, 298 fresh clusters, 3841 episodes.**
Evaluated once. Clusters disjoint from development *and* from the spent §26
holdout.

| metric | target | result |
|---|---|---|
| false-UNSUPPORTED rate | 0 | **0.0000** |
| UNKNOWN correctness | 100% | **100%** (3841/3841) |
| obtainable VERIFY recall | >= 70% | 100% |
| unobtainable ABSTAIN recall | >= 70% | 100% |

Routing accuracy 69.6% (§26) -> **92.2%**, cluster-adjusted Wilson
[88.7%, 94.8%]. All four targets met.

**What Track B does and does not establish.** It confirms the open-world fix
generalises: on a domain the index does not cover, the engine now says UNKNOWN
3841 times out of 3841 instead of inventing UNSUPPORTED. It does **not** test
correct-versus-corrupted discrimination, which is informationally impossible
without an authoritative source for that domain, and which was therefore not a
target.

**The previous development numbers were partly earned by the bug.** Re-running
development after the fix, split by coverage:

| stratum | identity ACCEPT | wrong-argument ACCEPT | gap |
|---|---|---|---|
| covered (airline, retail) | 100% | 23.7% | 41.9 pp |
| uncovered (telecom) | 100% | 61.5% | 0.0 pp |

The pooled pre-fix figures (19.7%, 42.1 pp) were flattered by telecom episodes
being wrongly blocked. Post-fix pooled values are 25.9% and 39.5 pp — the
wrong-argument target is now missed and the gap sits just under 40 pp. Reported
as measured; the targets are not being moved to accommodate them.

**Discrimination on a covered domain remains unconfirmed on blind data.** Every
airline and retail cluster was consumed during development, so no untouched
covered-domain set exists. Track A cannot be run with the data available, and
the 41.9 pp above is a development figure. Confirming it needs a covered domain
with reserved clusters — a data-acquisition problem, not a modelling one.

**Uncovered domains accept 61.5% of corrupted identifiers.** That is the honest
cost of refusing to invent negatives, and it is the strongest remaining argument
for routing UNKNOWN-plus-required-validation to VERIFY rather than to the
low-consequence ACCEPT path.

**Artifacts.** `results/routing_bench_holdout_b_results.json`,
`data/routing_bench_holdout_b/manifest.json` (sha256 `a36d6c68`).

---

## §28 Validation-required routing: blind-confirmed policy, unconfirmed discrimination (2026-07-31)
<!-- finding-status: superseded -->

**Change.** An argument that steers where the action lands — a customer,
account, recipient, deployment target — must be confirmed against an
authoritative source before autonomous execution. Unconfirmed with a resolver
available routes to VERIFY carrying a plan; unconfirmed with none routes to
ABSTAIN.

Routing *every* UNKNOWN to VERIFY was rejected: it rebuilds the constant blocker
of §21 one level up. The requirement is decided by what the argument steers,
independently of whether an index happens to cover it, and unrecognised roles
default to OPTIONAL — one of the few places where the conservative-looking
default is the wrong one, because REQUIRED-by-default makes every unfamiliar
tool signature a source of friction.

**Track C — resolver policy, blind, 278 clusters, 2915 episodes, evaluated
once.** Clusters disjoint from development and from both spent holdouts.

| metric | target | result |
|---|---|---|
| required-but-unvalidated autonomous ACCEPT | 0 | **0.0000** |
| obtainable VERIFY recall | >= 95% | 100% |
| unobtainable blocked recall | >= 95% | 100% |
| false-UNSUPPORTED rate | 0 | 0.0000 |

All four met. Routing accuracy 72.0%, cluster-adjusted Wilson [66.4%, 76.9%].

**Development effect, split by coverage.**

| stratum | identity ACCEPT | wrong-argument ACCEPT | gap |
|---|---|---|---|
| covered (airline, retail) | 100% | 9.8% | 55.8 pp |
| uncovered (telecom) | 0% | 0% | 0.0 pp |

On covered domains the change roughly halves wrong-argument acceptance (23.7%
-> 9.8%) and widens the gap (41.9 -> 55.8 pp). On uncovered domains it stops
autonomy entirely for calls carrying a validation-required argument, including
correct ones. That is the intended policy position — no autonomous action on an
unconfirmable customer id — and it is also why Track C's 72.0% accuracy is
substantially below the covered figure.

**Against the revised targets, on development data.**

| target | result |
|---|---|
| covered identity ACCEPT >= 85% | 100% — met |
| covered wrong-argument ACCEPT <= 15% | 9.8% — met |
| discrimination gap >= 60 pp | 55.8 pp — **missed** |
| false-UNSUPPORTED on valid values <= 2% | 0% — met |

**Still not established, and this is the load-bearing caveat.** No blind test of
correct-versus-corrupted discrimination on a *covered* domain has been run, and
none can be with the data available: every airline and retail cluster was
consumed during development. Tracks B and C both ran on telecom, where
discrimination is informationally impossible, so neither supports the
discrimination claim. The 55.8 pp is a development figure.

The remaining work is data acquisition, not modelling: a covered domain with an
authoritative state table independent of the tasks, and clusters reserved before
the detector is developed.

**Artifacts.** `results/routing_bench_holdout_c_results.json`,
`data/routing_bench_holdout_c/manifest.json` (sha256 `f7bd9a9e`).

---

## §29 Track A did not test what it was reserved to test (2026-07-31)
<!-- finding-status: accepted -->

**Result.** The covered-domain blind track was built on tau2
`banking_knowledge` (97 untouched clusters, 5768 episodes, authoritative
`db.json` independent of the tasks) and evaluated once.

| metric | target | result |
|---|---|---|
| covered identity ACCEPT | >= 85% | 93.6% (882/942) — met |
| covered wrong-argument ACCEPT | <= 15% | **90.3%** (851/942) — missed |
| discrimination gap | >= 60 pp | **3.3 pp** — missed |
| false-UNSUPPORTED on valid values | <= 2% | 4.8% — missed |

**This is not a falsification of the discrimination signal. It is a failed
experiment.** Of the 942 wrong-argument episodes, 836 received UNKNOWN: the
banking tasks operate on `annual_income` and `customer_name`, which `db.json`
does not carry as covered keys, even though it does cover `user_id` and
`account_id`. Only 106 episodes were in a position to be judged at all. A gap of
3.3 pp measured over a population that is 89% unjudgeable says nothing about
discrimination.

**The methodological error is mine and it is specific.** Before locking, I
verified that the index covered `user_id`, `account_id`, `address`, `name` and
`amount` — a sample of index keys. I did not verify that those were the
arguments the mutation generator would actually corrupt. Coverage must be
checked against the arguments the benchmark exercises, not against whatever the
index happens to contain. That check is cheap, it was available before locking,
and skipping it cost a blind set.

**The 98.5% routing accuracy is vacuous** and should not be quoted. It reflects
a system accepting nearly everything on a population where 89% of the
discriminating signal was unavailable.

**Standing position, unchanged since §28.** Correct-versus-corrupted argument
discrimination has never been tested on blind data where the signal had
information. Three blind sets have now been spent — telecom v1 (§26, failed on
the open-world bug), telecom B and C (§27, §28, both confirming policy on
uncovered domains), and banking A (this section, mis-specified). None supports
the discrimination claim.

**What a valid Track A requires**, stated so the next attempt does not repeat
this: a domain where the authoritative state covers *the specific argument
names the mutations corrupt*, verified by counting judgeable episodes before
the set is locked, with a pre-registered minimum judgeable fraction (e.g. >= 80%)
as an admission criterion for the track itself.

**Artifacts.** `results/routing_bench_holdout_a_results.json`,
`data/routing_bench_holdout_a/manifest.json` (sha256 `2f6f85f3`).

---

## §30 An index may not infer its own completeness; admission gate added (2026-07-31)
<!-- finding-status: superseded -->

**The 4.8% false-UNSUPPORTED from §29, diagnosed.** All 45 cases were valid
values supplied by tau2's own gold actions: `phone_number` 25,
`user_id` 13, `reason` 6, `address` 1. Examples: `friend_user_5839`,
`619-555-0284`, `account_ownership_dispute`. None was a normalisation or
casing artefact — zero matched under case or whitespace variants.

**Root cause: the same open-world error as §26, one level deeper.**
`StateIndex.from_json_files` marked every scalar-valued key as *closed-world*
covered. Having seen the key `user_id` once was treated as holding every
`user_id`. §26 fixed domain-level coverage; the fix left key-presence implying
completeness.

Seeing a key is evidence of a key, never evidence of completeness. Completeness
is a property of how the data was assembled, which only the assembler knows, so
it is now **declared, not inferred**. Scopes built from files are open-world
unless explicitly named in a `closed_world` declaration.

The cost is deliberate: with nothing declared, no value is ever UNSUPPORTED and
the discrimination signal is inert. That is the correct default. A signal that
stays silent until someone vouches for the data is preferable to one that
invents authority from a filename — which is what produced both §26 and the 45
false negatives here.

**Admission gate.** `remora/toolcall/routing/admission.py` decides whether a
candidate set may be sealed as a discrimination track, before any evaluation.
It reads only structural facts: argument names, coverage, whether completeness
is declared, and how many episodes are therefore judgeable. It never runs the
router or reads a prediction, so running it does not spend the set — asserted
structurally by a test forbidding those imports rather than by convention.

Pre-registered thresholds: 90% judgeable (above the 80% floor discussed in
review, because a pooled figure can mask one dead role) and at least 20
judgeable episodes per role, assessed **per argument role** and then in
aggregate. Only admitted roles enter the discrimination analysis.

The decisive test is that the gate refuses the §29 set. A check that would not
have caught the failure it was written for is not a gate.

**Declaration as evidence, not configuration.** A closed-world claim is now a
versioned object binding domain, tenant, entity type, argument role, the
SHA-256 of the exact snapshot it was written against, an as-of date, the basis
for the claim, and a named curator. Every way such a claim goes wrong is a scope
error — complete for one tenant applied to another, complete at one instant
consulted later, `user_id` conflated with a recipient id, aliases treated as
absent — and each now degrades that scope to UNKNOWN rather than to UNSUPPORTED.
Losing a negative claim is the safe direction; keeping one on stale evidence is
how a valid identifier gets rejected.

A declaration may also not claim behaviour the code does not implement:
declaring case-insensitive canonicalisation or alias support is refused at
construction, because a curator promising that `U1` matches `u1` when the
comparison is exact would reproduce §29 by hand.

**Still not established.** Correct-versus-corrupted discrimination on blind data
where the signal has information. Four blind sets are spent. The next attempt
must begin with admission, not with a router change — and under the declaration
rule it needs a domain whose completeness a named curator is willing to vouch
for against a frozen snapshot.

---

## §31 Discrimination confirmed blind — under ideal conditions only (2026-07-31)
<!-- finding-status: superseded -->

**Result.** Track A2, evaluated once at locked commit `a9ec74c` on the fleetops
white-box domain: 540 episodes over 90 clusters, admission-verified at 100%
judgeable before sealing.

| metric | target | result |
|---|---|---|
| covered identity ACCEPT | >= 85% | **100%** (90/90), Wilson [95.9%, 100%] |
| covered wrong-argument ACCEPT | <= 15% | **0%** (0/90), Wilson [0%, 4.1%] |
| discrimination gap | >= 60 pp | **100 pp** |
| false-UNSUPPORTED on valid values | <= 2% | **0%** |

Routing accuracy 100%, cluster-adjusted Wilson [95.9%, 100%]. All four met.
This is the first blind confirmation that the engine separates a correct call
from the same call with a corrupted identifier.

**A perfect score is a reason for suspicion, not celebration, and here the
explanation is mundane.** fleetops is generated: the database is the complete
entity universe, identifiers are structured, and a corrupted identifier is
therefore *definitely* absent. The value check has exactly the evidence it needs
and the task reduces to a set membership test. 100% says the mechanism is wired
correctly and its precondition is sufficient — it does not say the mechanism is
clever.

**What this does not establish.** Every hard condition from the earlier
sections is absent by construction:

* partial coverage, where some argument roles are held and others are not (§29)
* stale state, where the snapshot no longer matches the live system
* ambiguous scope, where a value exists under a different tenant or entity type
* open-world state, where absence is not evidence of absence (§26)
* naturally-occurring wrong values rather than generated ones

A domain with any of those would produce a materially different number, and
none of them is reproduced here. The synthetic result is a **necessary**
condition — the mechanism must work when its precondition holds, and it now
demonstrably does — not a sufficient one.

**Small N.** 90 clusters, 90 identity and 90 wrong-argument episodes. The
Wilson intervals are honest about that: identity ACCEPT could be as low as
95.9%, wrong-argument as high as 4.1%.

**The defensible claim.** On a closed-world domain whose completeness is
declared and verified, and on a set admission-verified as 100% judgeable before
sealing, REMORA accepted every valid identifier call and no corrupted one, on a
single blind evaluation. Generalisation to domains with partial or stale
authoritative state is unestablished and is the next thing worth measuring.

**Artifacts.** `results/routing_bench_trackA2_results.json`,
`results/fleetops_admission.json`,
`data/routing_bench_trackA2/manifest.json` (episodes `3c070516`, db `3cc32d40`).

---

## §32 Degrading fleetops on purpose: coverage loss costs discrimination, not validity (2026-07-31)
<!-- finding-status: superseded -->

**What was done.** §31 ended with the observation that the only state
production actually has is the one where the precondition does not hold. This
study broke the fleetops precondition one assumption at a time and measured
the router through the same locked pipeline as A2. **Openly non-blind**: the
fleetops blind budget was spent in §31, so these are development measurements
of *how the architecture degrades*, pre-registered directionally in
`remora/toolcall/routing/degradation.py` before evaluation. The runner is
committed this time (`scripts/run_fleetops_degradation.py`) — the A2 runner
was assembled inline and never committed, a reproducibility gap now closed.

The first run of the study surfaced a classifier defect (finding 5) whose fix
changes what is claimable, so the study was re-run with the corrected engine;
the table below is the corrected run. Identity ACCEPT is reported per action
type because the claimable production posture is per action type: **autonomy
on verified reads, verification on writes.**

| condition | identity ACCEPT read | identity ACCEPT write | wrong-arg ACCEPT | false-UNSUPPORTED | admission |
|---|---|---|---|---|---|
| baseline | 100% (60/60) | 0% (0/30 — VERIFY) | 0% | 0/105 | eligible |
| truncated_honest | 91.7% | 0% | **50%** | 0/105 | ineligible |
| truncated_redeclared | 83.3% | 0% | 0% | **18/105 = 17.1%** | eligible |
| stale_unbounded | 25% | 0% | 0% | **90/105 = 85.7%** | eligible |
| stale_bounded | 75% | 0% | 50% | 0/105 | ineligible |
| cross_tenant | 0% | 0% | 0% | 0/0 | eligible |

All pre-registered expectations met (the baseline expectation is
`identity_accept_read >= 85%` and `identity_accept_write <= 15%`; overall
pooled identity ACCEPT is reported in the artifact but carries no autonomy
claim). Five findings:

**1. Honest failure is safe — and expensive in a different currency.** When
the declaration stops holding for an honest reason (hash mismatch after
truncation, freshness bound refusing a stale declaration), no valid identifier
is ever rejected: false-UNSUPPORTED is 0 in both conditions, because every
scope degrades to UNKNOWN rather than to a negative. The price appears on the
other axis: with the discrimination signal inert, 50% of corrupted
identifiers are accepted on read-only calls. Losing coverage costs the
*safety of discrimination*, never the *validity of work*. The admission gate
reports both
conditions ineligible, which is the architecture agreeing with itself: a set
whose signal is inert may not be sold as a discrimination track.

**2. A false declaration is the expensive failure.** A curator re-vouching
the truncated export as complete produces confident rejection of 17.1% of
valid identifier occurrences (18/105; the draw put 17 of 90 identity episodes
on removed entities). The mechanism was *correct about the bytes it was
given* — the snapshot-membership split shows 100% ACCEPT on present
identifiers and 0% on absent ones — and wrong about the world exactly where
the declaration lied. The mechanism's ceiling is the declaration's
truthfulness; nothing in the runtime can detect this condition.

**3. Staleness is the failure hash binding cannot catch.** After the world
grows 20% past a byte-identical snapshot, the declaration still hash-matches
and the index confidently rejects 85.7% of valid post-snapshot occurrences.
This motivated the freshness bound (`as_of` + `max_age_days`, both explicit):
with it, the same world yields 0% false-UNSUPPORTED. The residual is finding
1's currency — UNKNOWN accepts half the corrupted values — but that trade is
the declared design: losing a negative claim is recoverable, rejecting valid
work on stale evidence is the §26/§29 failure again.

**4. Tenant isolation holds.** No identifier from a disjoint foreign-tenant
universe was accepted (0/90), and the foreign tenant's declarations were never
admitted for the local tenant.

**5. The study's first run caught a write passing as a read.** The engine's
mutating-verb list lacked "assign", "close" and "approve", so fleetops'
`assign_driver` and `close_work_order` rode the low-consequence read-ACCEPT
path. This also recontextualizes §31: **A2's 100% identity ACCEPT pooled 60
reads with 30 misclassified writes.** The sealed A2 artifact stands as
evaluated, but its pooled figure must not be quoted as a write-autonomy
claim. With the verb list fixed, every correct write routes to VERIFY even
with all arguments confirmed — the posture the production claim is now
stated in. Misclassifying a write as a read widens autonomy; the reverse
costs one verification, so the token list errs toward write
(`tests/test_routing_evaluate.py` pins both directions).

**What this does not establish.** Everything §31 listed stays open: these are
generated degradations of a generated domain. Naturally partial exports,
organically stale replicas and semantically ambiguous scopes will not be this
clean. The numbers characterize the mechanism's failure geometry, not its
field performance.

**Architecture landed alongside.** `build_state_index` is now the single
production path from declarations + snapshots to a `StateIndex` (tenant, hash
and freshness rules applied in one place; snapshot filenames that contradict
their domain are refused); the fleetops generator moved into the package
byte-pinned to the A2 snapshot hash; `admitted_scopes` gained the opt-in
freshness bound. 45 new tests across the four layers (domain, declarations,
degradation harness, action-type classification).

**Artifacts.** `results/fleetops_degradation_results.json` (schema
`fleetops_degradation_results_v1`, status `mechanism_study_not_blind`).

---

## §33 Declared validators recover read utility from the empty-index regime (2026-07-31)
<!-- finding-status: open -->

**What was done.** §32's remaining gap was the UNKNOWN regime: with no
trustworthy coverage, corrupted identifiers rode the read-ACCEPT path at 50%.
The fix under test is a **declarative validator binding** — a deployment
statement that `get_vehicle` validates `vehicle_id`, tenant-bound, with an
attempt budget — feeding the existing VERIFY-with-plan / re-entry machinery.
Point lookups need no completeness claim: "does V-0113 exist?" is answerable
even when nobody can vouch for a bulk export, which §31 showed to be the
fragile precondition.

**Setup.** Openly non-blind mechanism study (blind budget spent in §31), in
the regime production actually has when **no bulk export exists at all**: an
empty state index, every verdict UNKNOWN, bulk closed-world declarations
impossible. Eight targets pre-registered in external review before the study
module first ran. Two arms, same 540 episodes, same engine. Alongside:
freshness became mandatory for mutable declarations (§32 finding 3 closed —
the unbounded-stale regime is now unreachable except through a false
immutability claim), and action type now comes from registry-declared
`effect` metadata with the verb heuristic as fallback.

| pre-registered target | goal | without validators | with validators |
|---|---|---|---|
| required-UNKNOWN autonomous ACCEPT | 0% | 0/180 | **0/180** |
| correct validator chosen | ≥ 95% | — (no plans) | **120/120 = 100%** |
| valid-ID read completion after resolver | ≥ 85% | 0/60 = **0%** | **60/60 = 100%** |
| corrupt-ID ACCEPT after resolver | ≤ 5% | 0/90 | **0/90** |
| write autonomous ACCEPT | 0% | 0/30 | **0/30** |
| false-absent on valid values | 0% | 0/0 | 0/120 (by construction) |
| cross-tenant validator use | 0% | 0/0 | **0/120** |
| attempt budget exceeded | 0% | 0/540 | **0/540** |

All eight met. The headline is the completion column: **read utility goes
from 0% to 100% without any bulk export**, purely through declared
point-lookup validators, while every safety rate stays at zero. The
without-validators arm proves the regime fails closed — required-role reads
ABSTAIN rather than silently accept — which is the honest cost the bindings
then recover. UNKNOWN+OPTIONAL keeps its autonomous lane (pinned by test),
so the §21 constant blocker is not rebuilt one level up.

**What the mechanism enforces.** A binding cannot disclaim authority; every
field is mandatory; an unscoped registry refuses tenant-free lookups; a
foreign tenant's binding is structurally invisible (a distinctly named
tenant-B validator was declared and never consulted, 0/120). Validation
writes no argument values — it only establishes status — under the existing
bounded-authority checks: exists → re-enter confirmed (reads may ACCEPT,
writes keep their verification posture), confirmed absent → blocked, never
retried; unknown or validator error → ABSTAIN.

**Found and fixed on the way.** The resolution attempt budget counted
attempts across the whole plan, so any multi-argument call spuriously
exhausted a max_attempts=1 plan. The budget is now per fact, pinned by a
two-argument read completing without violation.

**Caveats.** Same class as §32: generated domain, generated corruptions, and
the study's validator consults the live world directly — `false_absent = 0`
is true *by construction* here and is a check a production validator must be
held to separately, not a finding. Corrupt-argument writes end in VERIFY via
schema/risk gates rather than a hard block from the confirmed-absent verdict;
acceptable (never autonomous) but unaesthetic, noted as residual. Field
performance on external domains remains unmeasured.

**The defensible claim now** (per-action-type posture): REMORA implements a
reproducible state-aware governance architecture that autonomously permits
verified read operations, routes writes to verification, preserves UNKNOWN
outside trustworthy coverage, binds state to tenant, hash and freshness
constraints, recovers read utility through declared authoritative validators,
and fails closed when authoritative validation is unavailable.

**Artifacts.** `results/fleetops_validator_study_results.json` (schema
`fleetops_validator_study_results_v1`, status `mechanism_study_not_blind`),
`results/fleetops_degradation_results.json` (schema v2, seven conditions).

---

## §34 External blind track (BFCL): four axes hold, wrong-call blindness measured cleanly (2026-07-31)
<!-- finding-status: superseded -->

**Result.** Track C-ext, evaluated once at locked commit `cf02fa8` on sealed
external data the system had never seen: BFCL v3 live categories
(ShishirPatil/gorilla @ `c15b2a15`, Apache-2.0) — real user-submitted
tool-call tasks. 1509 episodes over 515 clusters, targets pre-registered and
sealed with the set, evaluation under **no authority at all**: empty state
index, no validator bindings, registry only from the tasks' own schemas.

| pre-registered target | goal | result | verdict |
|---|---|---|---|
| required-UNKNOWN autonomous ACCEPT | ≤ 0% | **0/19 = 0%** | MET |
| irrelevance ABSTAIN recall | ≥ 70% | **258/258 = 100%**, Wilson [98.5%, 100%] | MET |
| obtainable VERIFY recall | ≥ 70% | **110/133 = 82.7%** | MET |
| unobtainable ABSTAIN recall | ≥ 70% | **133/133 = 100%** | MET |
| known-wrong-call ACCEPT | ≤ 20% | **224/258 = 86.8%** | **MISSED** |

Reported without target: optional-lane identity ACCEPT 205/238 = 86.1%;
labelled routing accuracy 94.0% (n=1251, cluster-adjusted); both untrusted
provenance families 100% (257/257 ESCALATE, 213/213 VERIFY).

**The miss is §21's wrong-tool blindness, now measured cleanly on external
data.** A substituted call — another task's gold call, carried with its own
complete, well-formed arguments — is a read the engine has no structural
reason to distrust: every required parameter is present and sourced,
`tool_matches_goal` is deliberately `None` because no authoritative source
establishes task–goal match, and fabricating that boolean is precisely what
this architecture refuses to do. On tau2 this leak was partially masked
because substituted calls' arguments were often unsatisfiable from the task
text; BFCL's substitutes carry their own arguments, so the mask falls away
and the true rate shows: **structural signals alone cannot catch a
well-formed wrong call.** Closing it requires a semantic task–call
compatibility source (the `tool_matches_goal` slot exists and waits for an
authority worth trusting) — not threshold tuning, which is why this is
published as a miss rather than repaired against the set.

**What the four met axes say.** On foreign data with zero authority the
posture holds: nothing required-and-unknown was autonomously accepted
(fail-closed confirmed outside the home domain), every no-call-is-correct
task was refused, satisfiability routing transferred (82.7%/100%), and both
provenance families transferred perfectly. The optional-lane utility (86.1%)
came free of any false accepts on the required lane.

**Honesty notes.** The wrong-argument value axis was excluded *before
sealing* (admission verdict in the manifest): BFCL's ground-truth argument
lists are the labels, and using them as a system of record would score the
answer key against itself. Irrelevance episodes propose no call (tau2
precedent — synthesizing one would author the test), so their ABSTAIN
measures refusal of the no-call decision point, not rejection of a proposed
distractor. This set is now spent; it can never serve as a blind set again.

**Mechanism built 2026-07-31, not yet measured.** `tool_matches_goal` now has
an authority: `remora/toolcall/routing/goal_match.py` matches a declared
`ToolContract` (capability, effect, resource_type, mutation, argument roles)
against a structured `TaskIntent`, and routes an established contradiction to
ABSTAIN for reads and ESCALATE for writes. It is a *conditional* gate, placed
ahead of trust routing, so a confident consensus cannot execute a call that
provably serves the wrong goal — but behind every hard guard, so it can never
unblock one.

The authority limit is the design: **a model may propose the intent, but may
not thereby assert a match.** Every clause is re-derived from the task text,
the contract and the call. An intent whose `source_spans` do not occur in the
task yields UNKNOWN, never SUPPORTED, so a fabricated goal cannot manufacture
permission for a destructive call.

**No result is claimed for it.** The mechanism is unit-tested (35 tests) and
inert where no contracts are declared. Its effect on the §34 residue — the 30
of 258 foreign calls whose values coincidentally occurred in the task — is
unmeasured, and measuring it needs a **new sealed set**: the BFCL population is
spent, and re-running it would report development, not generalisation. Until
that track exists this section stays `open`.

**Registered as** CLAIM-016 in `docs/assurance/claim_register_v1.yaml`, now
**superseded by CLAIM-018** after the disjoint §37 confirmation met all five
targets. The historical sealed values remain pinned by
`tests/test_routing_claim_artifacts.py`, so an edit that quietly improves the
published miss fails CI.

**Artifacts.** `results/routing_bench_bfcl_results.json`,
`data/routing_bench_bfcl/manifest.json` (episodes `c3a8e27b`, upstream file
hashes pinned).

---

## §35 Value grounding withdraws autonomy from foreign calls (2026-07-31)
<!-- finding-status: open -->

**The fix for §34, and what it costs.** A well-formed foreign call gives
structural signals nothing to distrust; its tell is provenance-shaped — the
argument values are traceable to nothing in this context. The new
deterministic signal `argument_values_grounded` judges every argument value
(numbers, identifiers, multiword strings, list elements; free-text roles from
the NOT_APPLICABLE vocabulary exempt) against three grounding sources: the
task text, the tool's own parameter declarations (enums/defaults — grounded
but *not anchoring*, since an enum says nothing about which task the call
belongs to), and the system of record. A call whose judgeable values are all
traceable but none anchored to *this* context is observationally identical to
a foreign copy of itself and withdraws to VERIFY. Validator confirmation
grounds on re-entry — the system of record vouching for a value is the same
anchoring clause as a SUPPORTED verdict.

**Measured on the spent §34 set (development, not blind — the 86.8% blind
record stands):** wrong-call accept 86.8% → **11.6%**, meeting the ≤20%
pre-registered bar on dev. Cost: identity autonomy 86.1% → 56.8%, the loss
being *derived* values (dates normalized from prose, unit conversions) that
now route VERIFY — the engine cannot check a derivation, so verifying it is
the honest lane, not a defect. On fleetops the same signal closed §32's
residual: wrong-arg accepts in the UNKNOWN regime went 50% → **0%** with all
pre-registered expectations still met, and the validator path still recovers
read utility 0% → 100% (all eight §33 targets green post-change).

**Iteration disclosure.** The grounding definition was developed against the
spent sets in three steps (exact substring → schema declarations + numeric
forms → token-wise multiword + anchor requirement + free-text exemption),
each step measured. That is development, done where development is allowed;
the numbers above must not be quoted as blind performance. **Blind
confirmation of the grounding signal requires the next sealed track.**

**Residual.** 30/258 foreign calls still accept — their values coincide with
this task's context (common values, schema enums whose words the user
happened to say). Below the 20% bar but not zero; a semantic task–call
source remains the complete answer.

**Registered as** CLAIM-015, now **superseded by CLAIM-018**. The separate
validator and degradation mechanism studies remain CLAIM-014 with
`blindness: development`.

**Historical record.** This section retains the spent-set development result;
the current `results/system_demonstration_v1.json` intentionally no longer
reproduces or republishes it.

---

## §36 Semantic binding gap in `match_tool_to_intent`: span-existence is not span-entailment (2026-08-04)
<!-- finding-status: superseded -->

**The gap.** `TaskIntent.source_spans` verified only that the quoted text
appeared verbatim in the task — not that the *claimed effect* was grounded
there. A model could set `requested_effect="cancel"` and
`source_spans=("booking B-104",)` for the task "Show me booking B-104":
the span check passes (the entity is named), the resource type matches the
contract, the effect label matches the contract → verdict **SUPPORTED**,
even though no cancel word appears anywhere in the task.

The paper stated: *"an intent whose quoted spans do not occur in the task text
yields Unknown, never Supported."* This sentence is technically true and
rethorically misleading — it promises span-*existence*, while the reader
reasonably hears span-*entailment*. The gap made `TaskIntent` a writable
signal: a model could assert any effect by quoting only the entity span.

**Threat model consequence.** Until this was fixed, `TaskIntent` was an
implicit fasit channel for the matcher. Any measurement of `tool_matches_goal`
before this fix measures the intent-provider's honesty, not the matcher's
discrimination.

**Fix applied (2026-08-04, commit on master).** Three additions to
`remora/toolcall/routing/goal_match.py`:

1. `action_spans: tuple[str, ...]` — a separate field on `TaskIntent` that
   must ground the *action* claim; the entity spans (`source_spans`) and the
   action spans are now distinct requirements.
2. `EFFECT_VOCABULARY` (version `v1`) — a frozen, versioned mapping from
   governance-level effect labels to keyword sets. An effect whose keyword
   does not appear in `action_spans` is ungrounded → UNKNOWN, never SUPPORTED.
   An effect name absent from the vocabulary cannot be grounded at all.
3. Negation and conditionality detection — a keyword immediately preceded by
   a negation word (`not`, `never`, …) or a conditionality marker (`before`,
   `after`, …) is skipped rather than counted, yielding UNKNOWN. The check is
   a single preceding-word lookup, not NLU: the design principle is *"refuse
   to pretend it understands"*, not *"understand it correctly"*.

Seven new pinning tests cover: real entity span with wrong effect label,
read verb against cancel contract, absent `action_spans`, negation, conditional
phrase, action span not in task text, unrecognised effect name.

**Unmeasured effect on §34 residue.** The 30 of 258 foreign calls that still
accepted after value grounding (§35) included cases whose argument values
coincided with the task. Whether `action_spans` + `EFFECT_VOCABULARY` would
have closed any of those without a contract oracle providing `TaskIntent` is
unmeasured. Measuring it requires the new sealed OT track; the BFCL set is
spent.

**Registered as** CLAIM-017 in `docs/assurance/claim_register_v1.yaml`
(`status: finding_registered` — the fix is in code and tested, the effect on
benchmark metrics is unmeasured).

---

## §37 Disjoint BFCL v4 sealed confirmation closes the wrong-call blind-test gap (2026-08-07)
<!-- finding-status: superseded -->

The confirmation track was frozen with the same five targets as §34 before
evaluation. It sampled 258 `live_multiple` tasks and 258 previously unused
`live_irrelevance` tasks from BFCL v4 at upstream commit `6ea57973c7a6`.
An explicit ID gate measured **zero overlap** with the spent BFCL v3
population. The sealed artifact contains 1,527 episodes over 516 source
clusters and was evaluated once.

| Pre-registered target | Bar | Sealed BFCL v4 result | Verdict |
|---|---:|---:|---|
| required-UNKNOWN autonomous ACCEPT | ≤ 0% | **0/32 = 0.0%** | MET |
| irrelevance ABSTAIN recall | ≥ 70% | **258/258 = 100.0%** | MET |
| obtainable VERIFY recall | ≥ 70% | **96/99 = 97.0%** | MET |
| unobtainable ABSTAIN recall | ≥ 70% | **98/99 = 99.0%** | MET |
| known-wrong-call ACCEPT | ≤ 20% | **28/258 = 10.9%** | MET |

All five targets met. Labelled routing accuracy was **91.2%** (`n=1,170`;
cluster-level Wilson 95% CI [88.4%, 93.3%]). Optional-lane identity ACCEPT was
151/218 = 69.3%, reported without a target. The old 86.8% BFCL v3 miss remains
immutable: this result confirms the repaired engine on a new population; it
does not rewrite the first experiment.

**Boundary.** The track still has no vouchable external state table, so the
wrong-argument-value axis remains excluded by admission. It also supplies no
authoritative `TaskIntent`/`ToolContract` bundle; the blind improvement therefore
confirms the complete current routing pipeline (principally value grounding),
not isolated causal efficacy of semantic intent matching.

**Artifacts.** `results/routing_bench_bfcl_v4_results.json`,
`data/routing_bench_bfcl_v4/manifest.json` (holdout SHA-256 `00ccd538…`).
Registered as CLAIM-018 (since superseded by CLAIM-019, the C-ext3 semantic-authority track; the baseline numbers here remain permanent).

---

## §38 Thermodynamic framing withdrawn from the paper; Lyapunov observable retained here (2026-08-07)
<!-- finding-status: accepted -->

**What changed.** The paper presented its uncertainty observables under
statistical-physics terminology: a structural temperature `T`, a critical
temperature `T_c`, a free-energy proxy `F = λD − T·H`, a susceptibility `χ`,
and a Lyapunov observable `V(t) = H(t) + λD(t)`. Section 5 was titled
*Method: Thermodynamic Uncertainty Observables*. That framing has been
withdrawn from the manuscript and the material moved here.

**Why, in order of weight.**

1. **The central quantity is falsified.** Regime assignment derived from
   comparing `T` against `T_c`. The temperature signal failed its
   pre-registered fresh-data confirmation (§18, CLAIM-012): on N=1,231 held-out
   items temperature-AURC 0.0954 vs. confidence-AURC 0.0664, paired CI
   excluding zero. A method section may not rest on a signal that lost its own
   pre-registered test.

2. **Nothing populates it on a governed path.** Verified 2026-08-07 by
   inspection: `servers/api.py` contains no reference to the consensus state;
   `servers/execution_api.py` passes `trust_score=None` and `phase=None`
   explicitly (with a comment stating the client is never a trust source); and
   `build_full_observation` — the observation builder shared by the assess and
   execution routes — leaves `phase`, `temperature`, `order_parameter` and
   `susceptibility` at their `None` defaults. The `critical_phase_critical_risk`
   rule in `decision_engine.py` therefore cannot fire in production. The paper
   was describing, as Method, machinery the enforced path does not run.

3. **`χ` is algebraically constant in the live path.** It reduces to `1/T_c`
   whenever the [0,1] clamps do not bind, independent of the oracle
   distribution. As a standalone difficulty predictor it measured AUC 0.39 —
   below chance (R10, above).

**The Lyapunov measurement, preserved.** The observable was tracked across
iterative oracle invocations, halting when `ΔV > ε_tol·|V|` (ε_tol = 0.05).
Across 1,000 synthetic sessions of 5–20 steps:

| Metric | Value |
|--------|-------|
| P(ΔV ≤ 0) throughout | 87.2% |
| Mean ΔV | −0.329 |
| P95 ΔV | +0.152 |
| P99 ΔV | +0.308 |

The 12.8% of sessions where `V` increased are cases where oracle consensus
degraded within the session (simulated oracle failures, adversarial probes);
the abort criterion terminates iteration there. Artifact:
`results/lyapunov_aggregate_results.json`, reproduced by
`experiments/lyapunov_aggregate.py`. **Configuration caveat:** the reported
figure was computed with the library default `lambda_dissensus = 1.0`, while
`λ = 0.3` appeared elsewhere as the free-energy coupling — two separate
parameters that the withdrawn section conflated.

This was never a formal stability proof and was captioned as such, but the
name invited that reading. It is an empirical trend statistic over synthetic
sessions, and it gated nothing in the governed path.

**What survives in the paper.** Entropy `H` and dissensus `D` over the
weighted verdict distribution, and the trust score `τ` derived from them —
information theory, not physics. The three consensus regimes keep their names
because they name existing code (`PhaseAwareGuardrail`,
`results/phase_aware_guardrail_n544_results.json`), not a physical state.
`remora/thermodynamics.py`, `remora/lyapunov.py` and `remora/statphys/potts.py`
remain in the tree with their tests (the last of these moved to
`remora/research_attic/statphys/` on 2026-08-19; the finding is unchanged, only
the path); RES-007 in the research control matrix
now records that they influence no runtime decision.

**Status:** the withdrawal is editorial and documentary. No code was removed,
no measurement was retracted, and no claim-register entry changed status —
CLAIM-012 already recorded the falsification. What changed is that the paper
no longer presents the framing as method.

## Summary Table

## §39 C-ext3 semantic-authority confirmation: wrong-call ACCEPT eliminated; the deterministic extractor caps autonomy and degrades argument routing (2026-08-19)
<!-- finding-status: open -->

Track C-ext3 was pre-registered in SAP v5 (`docs/assurance/
statistical_analysis_plan_v5_bfcl_semantic.md`) and evaluated once: 500
fresh `live_multiple` clusters and 300 fresh `live_irrelevance` tasks from
BFCL v4 at the same upstream commit, ID-disjoint from BOTH spent
populations (overlap 0), 2,799 episodes over 800 clusters. Configuration:
frozen deterministic semantic bundle (contracts authored from tool names
only; intents extracted from task text only;
`remora/toolcall/routing/bfcl_semantic_bundle.py`, hash sealed in the
manifest), `semantic_authority_floor` on, empty state index.

| Pre-registered target | Bar | Sealed C-ext3 result | Verdict |
|---|---:|---:|---|
| native wrong-call ACCEPT | ≤ 1% | **0/500 = 0.0%** (Wilson 95% ≤ 0.76%) | MET |
| irrelevance ABSTAIN recall | ≥ 95% | **300/300 = 100.0%** | MET |
| required-UNKNOWN autonomous ACCEPT | ≤ 0% | **0/398 = 0.0%** | MET |
| constructed wrong-tool ACCEPT | ≤ 1% | **2/199 = 1.005%** | MISSED (by 0.005pp) |
| legitimate read autonomy | ≥ 75% | **25/94 = 26.6%** | MISSED |
| obtainable VERIFY recall | ≥ 95% | **93/199 = 46.7%** | MISSED |
| unobtainable ABSTAIN recall | ≥ 95% | **126/199 = 63.3%** | MISSED |

**What is established.** Purpose-bound authorization eliminates native
wrong-tool acceptance on fresh sealed data. The single-pass ablation gives
the attribution chain on the SAME episodes: structural-only (arm A)
accepted 24/500 wrong calls; contracts+intent without the floor (arm C) 6;
with the UNKNOWN floor (arm F) 0. This closes the §34/§36 measurement gap
for the native axis: the improvement is carried by declared semantic
authority, not by the earlier structural pipeline.

**What failed, published as measured.**

1. *Read autonomy 26.6% vs ≥75%.* The deterministic keyword extractor
   grounds too few natural-language tasks (predicted pre-seal in SAP v5
   deviation 3: dev estimate ≈35%). Purpose-bound authorization with a
   deterministic extractor is SAFE but not USEFUL enough. The
   pre-identified follow-up is the LLM-as-proposer arm (SAP v5 §7): a
   model proposes intents, the deterministic matcher retains sole
   authority.
2. *Argument-routing degradation (obtainable 46.7%, unobtainable 63.3%).*
   A mechanism interaction, not noise: the semantic gates fire BEFORE the
   argument gates, so episodes the argument layer would have routed to
   VERIFY-with-resolution-plan or ABSTAIN are intercepted as
   goal-UNSUPPORTED/UNKNOWN first. Semantic strictness and fine-grained
   argument routing trade against each other in this configuration; gate
   ordering for combined semantic+argument observations is now an explicit
   design question.
3. *Constructed wrong-tool 2/199 = 1.005% vs ≤1%.* A hair-width miss on
   our own mutants, reported as missed; the two accepts are in the result
   artifact for inspection.

The C-ext2 baseline (28/258 = 10.9%, degraded authority) remains permanent
under §37/CLAIM-018 (superseded by CLAIM-019 but retained as the immutable baseline record). This section records the fresh-track misses; the met
targets are claimed under CLAIM-019.

## §40 The invariant set and the decision ladder had silently diverged (2026-08-20)
<!-- finding-status: accepted -->

`remora/policy/invariants.py` documents itself as "machine-verifiable
governance invariants" and is 408 lines of stated safety properties. An
internal review on 2026-08-20 found that `check_all_invariants` had **no
caller anywhere outside the test suite**: the module was a test fixture, not
a runtime guard. The same properties were therefore implemented twice —
once as invariants, once inside `decide` — with nothing able to notice the
two drifting apart.

They had drifted. Wiring enforcement into the engine's single build choke
point immediately surfaced a real conflict:

| | |
|---|---|
| Invariant | `DISORDERED_WITHOUT_EVIDENCE_NOT_ACCEPTED` — disordered phase without an evidence answer must not ACCEPT |
| Ladder | the conformal ACCEPT path reaches ACCEPT in the disordered phase when `conformal_trust_threshold` is configured and trust clears it |
| Observed | `phase="disordered", trust_score=0.73, risk_tier="low"` → `decide()` returned ACCEPT while the stated invariant said it must not |

**Resolution: the invariant wins, and the decision is withdrawn to
ESCALATE.** This tightens behaviour and never loosens it, and it is
consistent with the ruling already made in issue #35, where the enforcing
surface was given `execution_profile=True` precisely so that a probabilistic
signal can never produce ACCEPT. The conformal path is a probabilistic
signal; the disordered phase is the state in which oracle agreement is
insufficient. Accepting on that combination was the gap, not the guard.

Scope: only the research/assess surface could reach this combination,
because the enforcing surface already blocks probabilistic ACCEPT
structurally. No published result is affected — the sealed BFCL, AgentHarm
and adversarial-simulator tracks do not configure
`conformal_trust_threshold`. The shadow-replay `no_hard_guards` ablation arm
runs with enforcement off, for the same reason it runs with the hard-guard
floor off: the arm exists to isolate one guard's contribution, and leaving a
second guard on would make the delta measure both.

What generalises beyond this instance: **a safety property that is only
asserted in tests is a description, not a guarantee.** Four of the highest
findings in the same review shared that shape — an implemented, documented,
tested mechanism that no production path called. The check that would have
caught all of them is "which production path calls this?" as part of the
definition of done.

## §41 Three of the self-review's complexity findings did not survive verification (2026-08-20)
<!-- finding-status: accepted -->

The 2026-08-20 self-review produced 34 findings. Most held up and were fixed
in rounds A–G. Three did not survive being checked, and they are recorded
here because a review that only preserves its hits is not a review.

| Finding as reported | What verification showed |
|---|---|
| "`remora/toolcall/` carries three parallel generations with no deprecation markers" | The package docstring already orients the reader across all three generations, states which is current, and explains that the older ones are retained because their results are frozen artifacts. There was nothing to add. |
| "23 `REMORA_*` env vars have one use site and no test" | A proper census over `remora/`, `servers/`, `scripts/`, `experiments/`, `tests/`, `docs/`, `.github/` and `workers/` finds 88 distinct variables, of which **five** appear only in archived documentation and none in live code. The original count excluded `experiments/` and `scripts/`, where most of them are genuinely used. |
| "There is no `AuditSink` Protocol at all; audit backends are concrete siblings" | An `AuditAdapter` ABC already existed and both adapters inherit it. The real gap was narrower: no *structural* protocol, so a third party had to inherit rather than adapt. That gap was closed; the finding as stated was wrong. |

Two further findings were **reframed rather than fixed**, and the reasoning
is worth keeping:

- *"`remora/aromer/` has zero importers"* is true and is not by itself a
  defect: it is an overlay, not a component of the decision path. What is
  missing is a decision about its position, now tracked as issue #297.
- *"Replace the exact-value assertions in the claim-provenance test"* — four
  of them are regression guards on specific published corrections
  (effective N = 70 rather than 700; cluster-level CI 5.2% rather than the
  withdrawn task-level 0.55%). Deleting them would have made a revert of
  those corrections invisible. They were relabelled, not removed.

The generalisable point: **an audit finding is a hypothesis.** Three of these
were plausible, well-argued, and false, and acting on them without checking
would have produced churn presented as improvement.

Grouped by status, not by age. `scripts/check_negative_results_status.py`
verifies that every section listed here carries the matching
`<!-- finding-status: ... -->` marker, so this table cannot drift away from the
sections again.

### Open — the current backlog

| Finding | Where it stands | Severity |
|---------|-----------------|----------|
| Deterministic intent extractor caps read autonomy at 26.6% (§39) | Safety confirmed (0/500) but autonomy target missed; LLM-as-proposer arm is the identified follow-up — the matcher keeps sole authority | **High** |
| Semantic gates preempt argument routing (§39) | Obtainable VERIFY 46.7% and unobtainable ABSTAIN 63.3% under the floor; gate ordering for combined semantic+argument observations is an open design question | **High** |
| Constructed wrong-tool mutants 2/199 = 1.005% (§39) | Missed the ≤1% bar by 0.005pp; the two accepts are itemized in the result artifact | Low |
| Derived values lose legitimate autonomy (§35) | Mechanism code-fixed 2026-08-05 (`DerivationReceipt`, versioned deterministic-transform whitelist, verbatim source spans, re-execution verify, 14 pinning tests). Effect on the autonomy loss unmeasured pending new sealed track | Medium |
| Contextual harm invisible in a single call (§2, §8) | FA=30.7% under neutral metadata; semantic enrichment cut it but the residual needs trajectory-level governance, not another per-call classifier | **High** |
| Entropy backend is a token fingerprint, not Semantic Entropy (§3) | NLI backend executes and disagrees on 12/24 of the smoke corpus; full benchmark parity unmeasured. Solvable now | Medium |
| Production validator quality unmeasured (§33) | Mechanism recovers read utility 0% → 100%, but the study validator is correct by construction. Real validators need their own contracts | Medium |
| MCE bucket bias and absent cross-domain episodes (§15, §16) | Structural AROMER ceilings: the buckets get no organic traffic and crossDomainCases=0. Needs diverse deployment context | Medium |
| Authoritative tool metadata still caller-supplied on the advisory path (§14/M4) | Raise-only clamp shipped 2026-08-05 (declared risk cannot undercut the heuristic floor; clamps recorded, unset stays unset). Full authority still needs the signed ToolSpec registry (FT-03) | Medium |
| External replication, REM-021, field evidence (§1, §4) | Cannot be closed from inside this repository | Medium |

### Accepted negative results — do not "fix" these

| Finding | Why it is closed to further tuning | Severity |
|---------|------------------------------------|----------|
| Three self-review complexity findings were wrong (§41) | Verified and refuted: the toolcall generations are already documented, the env-var census was miscounted by excluding experiments/ and scripts/, and an AuditAdapter ABC already existed. An audit finding is a hypothesis | Low (methodological) |
| Invariants and the decision ladder had diverged (§40) | The invariant set was never evaluated at runtime, so a conformal ACCEPT in the disordered phase contradicted a stated invariant unnoticed. Enforcement is now wired into the build choke point and the stricter invariant wins. A property asserted only in tests is a description, not a guarantee | Medium (methodological) |
| Consensus temperature failed fresh-data confirmation (§18) | AURC 0.0954 vs 0.0664 for calibrated confidence, paired CI excludes zero, zero SGR-certifiable coverage. The hypothesis was pre-registered and it failed. Temperature stays diagnostic; reviving it needs entirely new evidence, not a threshold | **High (falsifies the thermodynamic-selection hypothesis)** |
| AgentHarm cannot measure resolver friction (§19) | FAR=0.0% met; FBR=100% not met, because every source verdict is ESCALATE and the control protocols act on VERIFY. Rewriting ESCALATE→VERIFY moved 19 harmful and 0 benign. A different dataset is required | Medium |
| Registry coverage without outcome change (§20) | 38 → 85 signatures moved no routing metric; `arguments_satisfiable` is orthogonal to call correctness. More signatures will not produce semantic correctness | Medium |
| Track A did not test its hypothesis (§29) | 836/942 wrong-argument episodes were unjudgeable because the index did not cover the arguments the tasks used. The set is spent; the lesson is the admission criterion added in §30 | Medium (methodological) |

### Superseded — resolved by a later section, kept for the causal chain

| Finding | Resolved by | Outcome |
|---------|-------------|---------|
| BFCL v3 wrong-call blindness (§34) | §37 | Disjoint BFCL v4 sealed run met all five targets; wrong-call ACCEPT 28/258 = 10.9% against the pre-registered ≤20% bar. The original 86.8% miss remains published |
| Semantic binding gap: span-existence ≠ span-entailment (§36) | §39 | Measured on sealed C-ext3: declared semantic authority takes native wrong-call ACCEPT 24/500 (structural) → 6 (contracts+intent) → 0 (with the UNKNOWN floor). The autonomy/routing costs are the open §39 findings |
| Routing is a near-constant predictor (§21) | §§22–35 | 25.0% accuracy and four families with identical predictions; the whole resolver/provenance/grounding line follows from this diagnosis |
| No resolver layer, obtainable VERIFY 0% (§22) | §23 | `ResolutionPlan` and router re-entry took obtainable VERIFY recall 0% → 100% |
| ESCALATE recall 0% on untrusted origin (§23) | §24 | Provenance split into noncontrolling/controls-sensitive; recall 0% → 100%, accuracy 56.9% → 85.5% |
| State check confused absent-from-record with outside-coverage (§26) | §27 | `CoverageScope` per argument; false-UNSUPPORTED 0/3841 on a second blind set, accuracy 69.6% → 92.2% |
| An index may not infer its own completeness (§30) | §31 | Admission gate added; discrimination then confirmed blind under ideal conditions |
| Coverage loss degrades discrimination (§32) | §35 | Wrong-argument accepts in the UNKNOWN regime 50% → 0% with value grounding, all pre-registered expectations still met |
| Benchmark v2 leakage and overstated effective N (§17) | Fixed 2026-07-20 | Gate and baselines restricted to the observable surface; effective N=70 not 700; the "0% vs 10–20%" claim withdrawn |
| AROMER seeding, regression and recovery chronicle (§§5–13) | §11, §12, §13 | Kept in sequence because the recovery evidence is only meaningful next to the failure. Architectural finding preserved: stage seeding ≤25 per batch, or implement an EMA dual window |
| Blind-confirmed intermediate rounds (§25, §27, §28, §31) | — | Each records a round that met or missed its pre-registered targets on the way to §34; retained as the pre-registration trail |

## Resolved Findings Archive

The following findings were identified, addressed, and removed from the active
list.  They are preserved here as scientific record.

| # | Finding | Resolution | Version |
|---|---------|-----------|---------|
| R1 | Iteration damage on easy questions (−22.2 pp) | `skip_high_trust_threshold=0.75` in `CritiqueRevisionGate`; DISORDERED-phase → immediate ABSTAIN (0 oracle calls) | ≤0.5.0 |
| R2 | Stage 3b critique-revision accuracy impact unmeasured | N=544 calibration analysis: critical-phase items n=26 routed, majority=d2=69.2%, loop neither helps nor harms; phase-differentiated routing implemented | 0.6.1 |
| R3 | Conformal guardrail not wired into decision engine | `conformal_trust_threshold` parameter in `RemoraDecisionEngine`; `CONFORMAL_ACCEPT` decision reason activated at runtime | ≤0.6.0 |
| R4 | Conformal repeated-split failures (20/20 at 5 % target, global) | `MondrianPhaseGuardrail`: per-phase calibration reduces failures to 1–2/20 per stratum; validated across 20-seed repeated splits | 0.6.1 |
| R5 | Lyapunov V(t), no aggregate distribution published | `experiments/lyapunov_aggregate.py`: N=1000 synthetic sessions, P(ΔV ≤ 0) = 87.2 %, mean ΔV = −0.329 | ≤0.6.0 |
| R6 | Oracle family independence partial (ρ̄ ≈ 0.4–0.6 within-family) | `build_recommended_swarm()`: 3 distinct base-model families (LLaMA 3.3 70B, Claude 3.5 Haiku, Gemma 3 27B) | ≤0.6.0 |
| R7 | T-estimator circularity (D→T→F, D contributes 18 % to T) | `estimate_structural_temperature()` is circularity-free (prompt-only); is the active path in `engine.py`; `_CATEGORY_PRIORS` documented as intentional safety floors | 0.6.1 |
| R8 **[SUPERSEDED BY §17]** | Tool-call v1, no differentiation (every strategy = 0 % unsafe on 252-task non-adversarial suite) | ~~v2 adversarial suite (700 tasks): `remora_full_policy_gate` = 0 % unsafe vs 10–20 % for all baselines~~ — **this comparison is withdrawn**: §17 established effective N≈70 (not 700), baselines at 1.4 % under the leakage-free surface, and an unsafe-rate delta that is not significant (p=0.50). FAR=0 itself is unchanged, CI [0.0 %, 5.2 %]. Original artifact artifact `results/toolcall_benchmark_v2_summary.md`; implementation `experiments/evaluate_toolcall_benchmark_v2.py`; regression test `tests/test_toolcall_v2_results.py` | 0.7.0 |
| R9 | Conformal exchangeability not verified at runtime | `MondrianPhaseGuardrail.route(prompt=…)` + `PromptDriftDetector` integration: distribution shift triggers ABSTAIN before conformal routing; tests in `tests/test_guardrail.py` (drift integration) and `tests/test_drift_detector.py` | 0.7.0 |
| R10 | χ-proxy difficulty signal below chance (AUC = 0.39) | Negative result preserved as empirical record; χ repurposed to OOD/adversarial escalation (`phase_decision()`, threshold 1.45) | 0.7.1 |
| R11 | Full-coverage baseline framing risk (41.18 % vs selective 88.8 %) | Mixed-comparison caveat standardized in docs; held-out validation added (`results/selective_n500_holdout_results.json`); benchmark-scoped wording enforced | 0.7.1 |
| R12 | Critical-phase trust score cannot safely gate decisions | Operationally mitigated via `CriticalEvidenceRouter` + escalation fallback; benchmark result: 38.5 % resolution on MultiNLI proxy, remainder ESCALATE | 0.7.1 |

## §42 An adjacent-systems crosswalk reported four capabilities absent that were present, and one absent risk as a strength (2026-08-23)
<!-- finding-status: accepted -->

**Status:** methodological negative result. Preserved because the failure mode
is the one this repository's claim discipline exists to prevent, and because it
was produced by this project's own tooling rather than by an outside reviewer.

**What happened.** A crosswalk of REMORA against sixteen adjacent agent-governance
projects (working document, unpublished) was written by reading each comparison
project and inferring what REMORA lacked. Checked against HEAD, five of its
findings were wrong:

| v1 claim | Evidence at HEAD |
|---|---|
| "No taint dimension at all" — rated CRITICAL | `observation.py:187,293`; `decision_engine.py:192-207`; `tests/test_untrusted_provenance.py` |
| "No multi-agent delegation story at all" | `remora/governance/a2a_envelope.py` (566 lines), CAP-006, attenuation with wildcard refusal |
| "Add a Merkle audit layer" | `remora/audit/checkpoint.py`, `merkle.py`; the limitation v1 "found" was already documented more precisely in `docs/enterprise/audit-anchoring-guide.md` |
| "TOCTOU resistance absent", evidence tier NONE | `ExecutionLease` binds and signs nine authorization-state fields including `toolspec_hash` |
| "No credential exists in the container" — rated a top strength | `workers/mcp-gateway/src/index.ts:76-77` supplies `REMORA_PDP_SIGNING_KEY` and `REMORA_LEASE_SIGNING_KEY` to the container |

**The finding.** Four errors understated REMORA and one overstated it. The
overstating one was the claim held with the most confidence, and it inverted a
real vulnerability into a headline strength: because the PDP signing key is
symmetric and is present in the executing container, the component that enforces
authorization also held the material to author it. A compromised container could
mint authority, not merely replay it. No test asserted otherwise until
`tests/test_lease_authority_custody.py`.

**Why it is recorded here rather than quietly fixed.** The direction of the
errors is the result. Confidence tracked how much a finding flattered the
system, not how much evidence supported it, and the single most flattering
finding was the one that hid a live weakness. A review that only ever discovers
that a system is stronger than believed is not measuring the system.

**What was changed as a result.** A rule, applied in
`docs/research/adjacent-systems-crosswalk-v2.md`: no gap or strength is recorded
about REMORA without a file-and-line citation from REMORA, however strongly a
comparison project suggests it. The corrected crosswalk lists every v1 error
rather than silently superseding it.

**Not resolved by this entry.** The credential topology is a mechanism change
only (ADR-A). The deployed Cloudflare container is still supplied both signing
keys; the custody split is available and is not in effect. That residual is
recorded in CAP-013 and must not be read as closed.

## §43 A verifier-only process silently issued unsigned authority instead of refusing (2026-08-23)
<!-- finding-status: accepted -->

**Status:** defect found by an adversarial test during ADR-A, fixed in the same
change. Recorded because the failure was silent and the test that caught it was
written to attack a different property.

**What happened.** `tests/test_lease_authority_custody.py::test_a_verifier_holding_only_the_public_key_cannot_mint`
strips a process to exactly the material a PEP holds and then asks it to issue a
lease for an action nobody assessed. It was expected to raise. It returned a
lease — `is_signed=False`, signature empty — because `ExecutionLease.issue()`
resolved no issuer algorithm and fell through to the unsigned branch that exists
for keyless library and research use.

**Severity, stated accurately.** Not directly exploitable: `verify()` refuses an
unsigned lease with `lease_not_signed`, so no unauthorized execution follows.
The defect is that a component which must not be able to produce an authority
object produced one, and a caller that asked for a lease and received one has no
reason to suspect it is worthless. Silent degradation of an authority object is
the failure mode ADR-A exists to remove.

**Fix.** `issue()` now raises `LeaseRefused` when the process holds only
verification material. The keyless path is unchanged for genuinely keyless use.

**Generalisation not yet done.** The same unsigned-fallthrough shape exists for
`PolicyDecisionToken` and the A2A envelope, which ADR-A does not convert. Whether
they have the equivalent defect is untested and is recorded as open, not assumed
absent.

## §44 The production fail-closed list required two of the three authority signing keys (2026-08-24)
<!-- finding-status: accepted -->

**Status:** defect found by auditing the unsigned-issuance family across every
authority object, fixed in the same change.

**Context.** §43 recorded that `ExecutionLease.issue()` silently returned an
unsigned object when the process held only verification material, and recorded
that the same shape in `PolicyDecisionToken` and the A2A envelope was *untested,
not assumed absent*. `tests/test_unsigned_issuance_family.py` tests all five
authority objects.

**The family, as measured.**

| Object | Keyless issuance | Verifier-only trigger available? | Compensating control |
|---|---|---|---|
| `ExecutionLease` | refuses when verifier-only (§43); unsigned when wholly keyless | yes — asymmetric mode exists | `verify()` → `lease_not_signed` |
| `PolicyDecisionToken` | returns unsigned | **no** — symmetric only, so a process either has the shared key or nothing | strict `EnforcementGate` refuses |
| A2A envelope | returns unsigned | **no** — same reason | `verify()` fails closed |
| ToolSpec `sign_bundle` | **cannot be called without a key** — it is a required parameter | n/a | structurally immune |
| `DecisionEnvelope` | unsigned when no key | no | production prerequisite |

The token and the A2A envelope are *not* given the §43 refusal, and that is a
decision rather than an omission: with no asymmetric mode there is no
verifier-only state to detect, so the only available rule would be "refuse all
keyless issuance", which breaks legitimate research use to prevent an object
every verifier already rejects. ToolSpec has the shape the others should
converge on — the key is a parameter, so there is no environment fallthrough to
degrade through.

**The defect.** `servers/api.py` refuses to start in production without
`REMORA_ENVELOPE_SIGNING_KEY` and `REMORA_PDP_SIGNING_KEY`, on the stated
grounds that without them records are unsigned and nothing distinguishes an
authentic record from a fabricated one. That argument applies verbatim to the
`ExecutionLease` — the object that actually authorises a side effect — and the
lease key was **not on the list**. A production deployment could therefore run
with no lease signing material at all and issue every lease unsigned.

**Severity, stated accurately.** Not exploitable. `verify()` refuses an unsigned
lease, so such a deployment refuses every governed call rather than permitting
one. The defect is that a fail-closed prerequisite list omitted the most
consequential of the three keys while citing a rationale that covers it, so the
guard was inconsistent with its own argument and would have failed a reader who
trusted it to be complete.

**Fix.** Either `REMORA_LEASE_SIGNING_KEY` or
`REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE` now satisfies the prerequisite.
Requiring the asymmetric key would refuse to start a deployment correctly
configured for an earlier migration phase, so both are accepted and the
stronger one is not compelled here.

**Principle recorded.** *An authority issuer without signing authority must
refuse to issue, and must not return an authority-shaped unsigned object on an
authoritative path.* Applied at two triggers where it can be applied soundly:
the process is a verifier, or the deployment declares itself authoritative.
Keyless research use stays supported and is now pinned by a test, so removing it
would have to be a deliberate act.

**Not resolved by this entry.** `PolicyDecisionToken` and the A2A envelope
remain symmetric, so their verifiers can still mint. That is the same class of
exposure ADR-A removed for the lease, and it is open for both.

## §45 Deploying the custody split broke it twice, in ways only deployment could reveal (2026-08-24)
<!-- finding-status: accepted -->

**Status:** two defects found by deploying, both fixed, both now pinned by
tests. Recorded because each was invisible to a green test suite and to review,
and because the second is a design error in a guard published one day earlier.

**Context.** ADR-A's custody split was implemented, tested from three
directions, and reported as "designed, not deployed". Deploying it produced two
failures in sequence. Neither was in the split's own logic.

### Defect 1 — the production guard refused the topology it shipped alongside

NEGATIVE_RESULTS §44 added a fail-closed prerequisite: a production deployment
must have `REMORA_LEASE_SIGNING_KEY` or
`REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE`, on the grounds that without one,
leases are issued unsigned.

That reasoning assumed **every production process issues leases.** Under the
split the execution domain does not: it holds only the public verification key,
and that absence *is* the security property. So the guard refused to start the
execution container, and the deployment came up with one domain.

The check is now satisfied by signing **or** verification material — private
key, HMAC key, or public key — which preserves the original intent (a
production deployment must not be silently unable to establish lease
authenticity in either direction) while admitting an execution-only domain.

The general shape is worth naming: **a fail-closed prerequisite written for one
topology becomes a fail-closed prohibition on every other one.** §44 was
written the day before and was correct for the deployment that existed then.

### Defect 2 — the image did not carry the crypto the split requires

With both containers starting, every ACCEPT returned HTTP 500 and
`"An internal error occurred"`. The container image installs
`.[api,postgres]`; `cryptography` is the optional `security` extra and was
absent. `_ed25519()` therefore raised `SigningUnavailable` — which is exactly
what that function is designed to do, and correct, because falling back to HMAC
would restore the custody defect.

But `dispatch_under_lease` caught `(LeaseRefused, ValueError)` and not
`SigningUnavailable`, which is a `RuntimeError`. The exception escaped as an
unhandled server error. The operator saw no reason, and the audit chain
recorded none.

Two fixes, because there were two faults: the image now installs the
`security` extra, and the missing-crypto case is a named refusal
(`lease_unavailable: ...`) rather than a 500. Failing loudly on absent crypto is
deliberate; failing as an internal error is not.

This is the same class as the CI defect in §44's own commit — the security extra
missing from an environment that needs it — found a second time, in a second
environment, three commits later. The lesson is not "remember the extra". It is
that an optional dependency guarding a security property has no business being
optional in any environment that claims the property, and nothing was checking
that.

### What deployment revealed that testing could not

Both defects were invisible to 5829 passing tests, because both were
*environment* facts: which prerequisites a second process must satisfy, and
which packages an image contains. The library-level custody tests were correct
and stayed green throughout.

Recorded as a methodological result: for a property whose subject is a
deployment topology, a green suite is evidence about the mechanism and not
about the property. The claim in CAP-013 was correctly scoped to "mechanism,
not deployed" before this, and only now changes.

**Resolved by this entry:** the custody split is deployed and evidenced
(`docs/deployment/authority-custody-evidence.md`). §44 remains accurate about
the defect it recorded; its fix was too narrow and is superseded by the
three-way check.

## §46 A corrupt capability binding read as a clean one (2026-08-24)
<!-- finding-status: accepted -->

**Status:** gap in an assurance gate, found by accident, fixed.

**What happened.** Rebinding CAP-003 and CAP-013 after a squash merge, a
careless substitution spliced a 7-character SHA onto the front of the old
40-character one, producing `ea886eb03232717c785bf2f2d3b5475d8bdf26a1` — a
well-formed hash that resolves to no commit in this repository.

`scripts/check_capability_freshness.py` reported **`[PASS] no stale
capability`**.

**Why.** `classify()` returns `UNKNOWN` for an unresolvable `verified_at_sha`,
which is correct and deliberate — there is a test for it, on the stated grounds
that *"a shallow clone must not silently turn the gate off"*. `main()` prints
unknowns to stderr and only counts them as failures under `--strict`. CI ran
the gate **without** `--strict`, so the warning went to a log nobody reads and
the build was green.

**Why `--strict` was not already on.** The job's checkout had no `fetch-depth`,
so it was shallow. On a shallow clone every SHA older than the tip is equally
unresolvable, and strict mode would have failed on correct bindings. The gate
was structurally unable to distinguish *"this commit is not in the clone"* from
*"this commit does not exist"*, and the safe-looking configuration chose to
report neither.

**Severity.** No claim was wrong. A capability bound to a nonexistent commit is
not a false claim about code; it is a claim bound to nothing, which is exactly
what `verified_at_sha` exists to prevent. The register's whole purpose is that a
status is anchored to a revision, and for the duration of that mistake two of
them were anchored to a string.

**Fix.** `fetch-depth: 0` on the job's checkout and `--strict` on the
invocation. Both are asserted by a test, because either alone is wrong: strict
without full history fails on correct bindings, and full history without strict
changes nothing.

**The general shape, which is the reason this is recorded.** A gate with a
sound implementation, a correct classification, an explicit strict mode, and a
test for the edge case still passed a corrupt input — because the strict mode
was off in the only place it ran. Every piece was right except the wiring, and
the wiring is not what gets reviewed.

## §47 EFFECT_VERIFIED was reportable; its attestation is now lineage-bound (2026-08-24)
<!-- finding-status: accepted -->

**Status:** RMR-002 from the external forensic review, fixed. One sub-rule was
written wrong on the first attempt and is recorded below rather than quietly
corrected.

**The defect.** The recorder checked that a proposal existed and then stored
whatever status arrived. A proposal that was assessed and never approved or
executed could be recorded `EFFECT_VERIFIED`, and the lifecycle projection
reported it as such — a dispatch of `null` with a current state of
`EFFECT_VERIFIED`.

That is a false VERIFIED. A later review also showed why the inverse shortcut
is invalid: MISMATCH is a load-bearing negative system claim and can be abused
to occupy the terminal slot. Positive and negative settled verdicts therefore
carry the same evidence burden.

**The rule now enforced.**

```
SETTLED_EFFECT_ATTESTATION_ACCEPTED =
    valid_dispatch_lineage
    AND authoritative_observation
    AND observation_recorded_for_re_checking
    AND freshness_valid
    AND receipt_not_replayed
```

Each conjunct has its own refusal reason, because an operator reading a refusal
needs to know which one failed. The lineage is read from the audit chain, never
from the receipt: proposal, exact call hash and the grant that identifies the
dispatch. An observation dated before the dispatch is refused, which is what
catches a pre-existing matching state being passed off as a verification.

**Two things deliberately kept possible.** An UNKNOWN dispatch can be resolved
to VERIFIED by a later authoritative check — a lost response does not mean
nothing happened, and requiring a false SUCCEEDED first would be the opposite
of what this model is for. And a non-terminal verdict (UNOBSERVABLE,
VERIFIER_FAILED) can be superseded, because that is how an unknown gets closed
honestly. What is forbidden is re-verifying a dispatch that already has a
settled verdict.

### The sub-rule that was wrong

The first implementation derived VERIFIED by requiring
`expected_sha256 == observed_sha256`, on the reasoning that a verdict
contradicting its own numbers is a mismatch with a wrong label.

**That reasoning was wrong, and the test suite caught it.** The two digests
hash *different maps* — the expected FIELDS and the observed ROW — and the
comparison between them is rule-based
(`PostconditionContract.comparison_rules`, for example `content: hash`). A
passing verification routinely produces different digests. The rule would have
refused every legitimate VERIFIED the SDK produces, and
`tests/test_sdk_effect_roundtrip.py` failed immediately because it was
asserting the real contract while the new module was inventing a different one.

The corrected rule requires both digests to be *present*, not equal: a verdict
that records neither side of its own comparison cannot be re-checked, and an
unre-checkable verdict is an assertion. REMORA does not re-run the comparison
and does not claim to — it holds the digests, not the maps or the rules.

Worth recording because of what nearly happened: a module written to stop
unearned claims was one commit from making one of its own, in the form of a
verification rule that did not match the verification it was checking. An
existing test written against the real contract is what prevented it.

### A second review found the first fix incomplete

The change above closed the reported reproduction -- a proposal with no
dispatch -- and a second review then showed that a fabricated
``EFFECT_VERIFIED`` was still reachable for a dispatch that DID happen:

```json
{"status": "EFFECT_VERIFIED", "verifier_identity": "trusted-name",
 "tool_call_hash": "", "grant_jti": "", "verified_at": "",
 "expected_sha256": "a", "observed_sha256": "b"}
```

Eight ways it got through, all of them mine:

1. Empty ``tool_call_hash`` and ``grant_jti`` **skipped** the comparison. The
   binding fields were treated as "no opinion" when absent, so a receipt could
   skip every check by omitting what it would have been compared against.
2. Empty ``verified_at`` was replaced with the server's clock, fabricating the
   freshness the check depends on.
3. The digest fields were length-limited but never validated as SHA-256, so
   ``"a"`` and ``"b"`` were acceptable digests.
4. ``verifier_identity`` was not bound to anything. The name arrived in the
   request body, so an allowlist constrained which strings were acceptable and
   not who could send them.
5. An empty allowlist accepted any name, and a populated one could be satisfied
   by typing a permitted name.
6. ``observed_state_hash`` and ``verifier_version`` were accepted and then
   discarded -- a received-but-unstored field suggests a binding that is not
   there.
7. The replay check was read-then-append. Two concurrent receipts both read
   "unsettled" and both appended.
8. ``EFFECT_MISMATCH`` required no observation at all, yet is terminal -- so an
   evidence-free MISMATCH could take the slot and block a later legitimate
   verification.

Point 8 is the one worth dwelling on. The entry below states that positive and
negative claims carry the same burden of proof, and the implementation directly
under it demanded evidence for VERIFIED and none for MISMATCH. The asymmetry
this project keeps finding in its own prose had been written into the code of
the module that names it.

All eight are fixed: binding fields and observation time are mandatory for a
settled verdict, digests are validated as SHA-256 on the wire, the verifier
identity is bound to the authenticated principal
(``REMORA_EFFECT_VERIFIER_BINDINGS``, defaulting to identity == principal),
provenance is stored in the chain, and MISMATCH carries the same evidence burden
as VERIFIED. The first atomicity repair itself needed a further correction.

### A third review found a phantom-settlement window

The first replay fix took a primary-key slot in a separate receipt ledger and
then appended the observation to the tenant audit chain. That prevented two
concurrent winners but did **not** establish
``observation_recorded_for_re_checking``: if the process failed after the slot
commit and before the audit append, every retry was refused as a replay although
no observation existed in the chain. The code had made uniqueness atomic and
split the property it was meant to protect across two transactions.

The separate ledger is removed. ``TenantAuditChain.append_once`` now commits
the receipt idempotency key and audit entry as one operation: under one lock in
the in-process reference implementation, and in one transaction for SQLite and
Postgres. A concurrent test produces exactly one winner. A SQLite fault-
injection trigger aborts the audit insert after the idempotency insert; the test
proves the key rolls back, the chain stays empty, and a retry succeeds.

There is one explicit deployment limit. ``REMORA_STATE_ENDPOINT`` makes the D1
nonce ledgers durable, but the tenant audit chain has no D1 adapter. A
production deployment configured only with that endpoint is therefore refused
at the effect-receipt API rather than accepting a settlement it cannot preserve
for re-checking. Adding a transactional D1 tenant-chain adapter remains open;
Postgres and persistent SQLite are the durable effect-receipt backends today.

### The claim was also overstated

"REMORA derives EFFECT_VERIFIED" was wrong, and is now "REMORA accepts or
refuses a lineage-bound VERIFIED attestation". REMORA cannot evaluate the
postcondition rule -- it holds the digests, not the maps or the comparison
rules -- so it does not compute the verdict and must not say it does. The
function is named ``adjudicate_status`` rather than ``derive_status`` for the
same reason.

### The rule this raises to a project principle

> **Positive and negative system claims carry the same burden of proof. A
> measurement without verified provenance is just another claim.**

This is the third consecutive entry reaching the same place from a different
direction. Prose asserting a property is written at the moment of highest
confidence and lowest evidence. A probe reporting a system is broken is a
claim, and a measurement read from the wrong key measured nothing. And an
attestation asserting VERIFIED is a claim, needing provenance that binds it to
the thing it claims to have observed. (The first two are recorded in the
custody-split branch, PR #356; if that merges first this entry renumbers.)

It is a precise extension of what effect verification was already for. The
model began by separating "the dispatcher returned" from "the effect happened".
This adds the layer under it: **proving the observation actually measured what
it claims to have measured.**

## §48 A dispatch that began and failed was recorded as proof that nothing happened (2026-08-24)
<!-- finding-status: accepted -->

**Status:** RMR-003 from the external forensic review, fixed.

**The defect.** Settlement matched a string:

```python
elif reason == "tool_failed_nonce_burned":
    settled_state = OutboxState.FAILED
```

The reason it matched on has this docstring in `lease.py`:

> *the tool raised after its nonce was consumed: state at the tool is unknown*

So the durable record asserted **no effect occurred** on evidence that only
showed the call raised. The response said `state_unknown`; the store said
`FAILED`. A consumer reading either could reasonably issue a fresh call for an
effect that may already have happened — which is the one move the execution
layer must never make.

**The contract was already right.** `schemas/execution_lifecycle_v1.yaml` has
carried both transitions since it was written:

```
{from: DISPATCHING, to: FAILED,  on: tool_raised_pre_effect}
{from: DISPATCHING, to: UNKNOWN, on: crash_or_timeout_after_possible_effect}
```

FAILED was always reserved for a failure proven to precede the effect boundary.
The queue simply had no vocabulary to reach UNKNOWN — `ItemStatus` had
`DISPATCH_FAILED` and `DISPATCH_REFUSED` and nothing else — so the honest state
was unreachable and the nearest available one was written instead. The
reconciler, which settles stale `DISPATCHING` rows, had this right all along.

**The invariant now enforced.**

```
REFUSED   REMORA observed that dispatch never began.
FAILED    Trusted adapter evidence proves failure before the effect boundary.
UNKNOWN   Dispatch began and absence of effect is not proven. Durable, and
          may later be superseded.
```

A dispatcher exception, a timeout, a lost response, or
`tool_failed_nonce_burned` alone earns only UNKNOWN.

**Structural, not string-derived.** `DispatchResult` now reports
`dispatch_began` — the dispatcher is the only component that knows whether it
invoked the callable, and inferring it from `refusal_reason` made every new
refusal reason a silent reclassification. `record_execution_outcome` takes the
outcome instead of `executed`/`failed` booleans, because the old signature
*could not express* "dispatch began and we do not know". A test asserts
`classify_outcome` never reads `refusal_reason` again.

**FAILED is unreachable from the synchronous path, deliberately.** No adapter
here produces trustworthy pre-effect evidence, so the honest terminal is
UNKNOWN. `PreEffectProof` exists as the place to put that evidence the day an
adapter can produce it, and cannot be constructed without a source and what it
observed. A caller-supplied `pre_effect` flag is explicitly not proof — a test
tries four spellings of one and gets UNKNOWN for each. Approximating FAILED
would put the unproven negative claim back, wearing a structured field instead
of a string.

The one legitimate FAILED is unchanged: reconciliation of an intent that was
never claimed. The claim strictly precedes invocation, so the side effect
provably did not happen.

**Fixtures that broke, recorded rather than weakened.** Two asserted the old
contract directly — `test_tool_exception_burns_nonce_and_is_reported` expected
`DISPATCH_FAILED` for a raising tool, and `test_execution_outcome_terminal_states`
asserted the same at the queue. Both now assert UNKNOWN, and the second gained
a case proving FAILED is still expressible for the reconciler's path. Both were
asserting that a durable claim of "nothing happened" was correct.

**Where this came from.** Not invented for RMR-003. It follows from the rule
recorded one section earlier: positive and negative system claims carry the
same burden of proof. A durable FAILED is a negative claim, and it was being
written on less evidence than SUCCEEDED requires. §47 fixed the same asymmetry
for `EFFECT_MISMATCH` — a terminal negative verdict that needed no observation.
This is the third place the same shape has appeared, which suggests the rule is
worth applying ahead of a review rather than after one.

**Not closed by this entry.** UNKNOWN resolution remains a manual operator
decision (`unknown_resolution.mode: manual` in the schema). The effect recorder
can supersede an UNKNOWN dispatch with a verified observation, which is the
automated half; nothing reconciles an UNKNOWN that never gets one.

> **Renumbering note.** These three entries were written as §47-49 on a
> branch predating the effect-receipt (§47) and dispatch-outcome (§48)
> work now on master. They are §49-51 here. Nothing changed except the
> numbers and the cross-references between them.

## §49 A code review found three defects and missed the worst one; fixing it took the gateway down (2026-08-24)
<!-- finding-status: accepted -->

**Status:** four defects, all fixed. Recorded for the pattern in each, and
because the repair itself produced a live outage on the test deployment.

### What the review found

Three findings, all verified against the code rather than accepted:

1. **`now` was dead on the wire and the contract lied about it.** The
   `DispatchLeasedRequest` docstring said *"`now` is carried so the authority's
   clock decides freshness rather than the executor's"*; `dispatch_leased`
   computed its own `now` and never read the field. Fixed by **removing** the
   field, not by wiring it up: the claim was also wrong. The authority mints
   the lease, so letting it assert the time its own expiry is judged against
   makes the TTL vacuous from the executor's side. An independent freshness
   check is one of the few things the second domain contributes alone.

   This is the same shape as the Invariant finding in the crosswalk — a
   document describing a property the implementation does not have — committed
   here two days after writing that up.

2. **`REMORA_EXECUTION_ENDPOINT` gated on the keypair, not the binding.**
   Reported as a defect; the suggested fix was **rejected**. Gating on
   `env.EXECUTION` instead would mean a deployment with the private key but no
   execution binding silently dispatches locally, reverting to single-domain
   custody with no signal. The current behaviour — every call refused as
   `execution_domain_unreachable` — is an outage, and an outage is the correct
   failure for a missing half of a security boundary.

3. **A guard that skipped its own case.** `dispatcher is None and not
   execution_endpoint()` let a process configured as both, holding a presented
   lease and no dispatcher, fall through to `dispatcher.dispatch(None)` — an
   `AttributeError` where the function documents a named refusal. The guard now
   asks whether this process will execute locally.

### What the review missed, and it was the important one

The **authority** container was passed `REMORA_GITHUB_TOKEN`. Three documents
said it holds no downstream credential: the target topology table, the source
comment in `index.ts` (*"the authority container cannot cause an effect even if
it wanted to"*), and CAP-013.

On this deployment no `REMORA_GITHUB_TOKEN` secret is set, so the claim held by
**accident**. A component that can both mint authority and use it is the single
point of failure the split exists to remove, and the configuration would have
created one the moment that secret was added.

This is §42's pattern again, in the same programme: the claim more flattering
than the evidence is the one nobody checks. Neither review nor testing caught
it — it was found by diffing the two `envVars` blocks while checking something
else.

### Fixing it took the gateway down for about fifteen minutes

Removing `REMORA_TOOL_REGISTRY_MODULE` from the authority alongside the
credential broke every call with `policy_bundle_mismatch`. The policy bundle
hash covers that module's spec string and a source digest — resolved *without
importing it* — so the two domains must **declare** the same registry or their
hashes differ. The declaration was never a grant of callables, and removing it
to "hold no tools" removed agreement instead.

Then the diagnosis went wrong in a way worth recording. Restoring the registry
did not fix it, so the cause looked like something else, and a bisect began.
The bisect was meaningless: **Cloudflare keeps running container instances when
only the Worker changes.** Both instances had been created at 07:57 and none of
the three later deploys replaced them, so every fix was tested against the
broken configuration. The instances only rolled once the *image* digest changed.

Two operational consequences, neither of which existed with one container:

- an `envVars` edit alone does not reach a live container, so a config fix can
  appear not to work while being correct;
- the bundle hash is now a **cross-container agreement requirement**, so the
  two domains must roll together or the deployment refuses every lease.

Fail-closed throughout — nothing executed unauthorised — but availability, not
safety, is what a split buys you a new way to lose.

### One more, found while fixing the tests

`workers/mcp-gateway/test/custody.test.ts` located the end of a class body with
the literal `"\n  }\n}"`. The file is stored CRLF, so that never matched, every
extracted block silently ran to end-of-file, and the execution-container
assertions passed **only because the authority class is declared above it in
the file**. A test asserting an absence, passing for the wrong reason. Now
matched with `/\r?\n {2}\}\r?\n\}/`.

### The general shape

Three of these four were invisible to a green suite and to a targeted review.
The one with real security content was found by reading two configuration
blocks side by side, which is neither. The recurring lesson of this programme
holds: for properties whose subject is a deployment, evidence has to come from
the deployment, and absences need a test that is itself verified to fail.

## §50 An external forensic review found seven defects; two were mine to fix in flight (2026-08-24)
<!-- finding-status: accepted -->

**Status:** external read-only review against `6be9cde`. Two findings fixed
immediately because they fell inside work already open; five recorded as open
with their reproductions preserved.

**Context.** A forensic review was run against the merge of #355. It reported
one CRITICAL, six HIGH and several MEDIUM findings, with reproductions. It was
conducted before #356 landed, so part of what it found had already been fixed —
which is itself worth recording, because the overlap is not coincidence.

### What it independently found that this repository had also found

The CRITICAL finding — the authority container holding downstream effect
capability while holding the private lease key — is the same defect recorded
here as §49, found by diffing two `envVars` blocks. Two reviewers, one internal
and one external, arriving at the same finding by different routes is the
strongest signal in this document that the finding is real.

It also found the ignored `now` field (§49's finding 1) and the dead-guard case.
All three were already fixed in #356 and could not be seen from the reviewed
revision.

### What it found that was still true, and fixed here

**Actor identity was caller-asserted on the custody hop.**
`/dispatch-leased` used `req.actor_identity or principal`. A caller holding a
stolen lease and the hop credential could put the victim's identity in the
request body and satisfy the lease's own actor check — the exact binding that
check exists to enforce. `ExecutionLease.verify`'s own docstring says the
identity must come from authenticated transport and never from a request body.
I wrote both.

Fixed by taking the actor from the **lease**, where it sits inside the
Ed25519-signed payload: only the authority can produce it and it cannot be
altered without invalidating the signature. The body field is removed from the
model rather than ignored by the handler, because a field that is accepted and
ignored invites someone to wire it back up.

Residual, stated rather than implied: the hop's transport authenticates the
**authority**, not the end actor, so the executor trusts the authority's signed
assertion about who acted. Anchoring the end actor to its own credential
remains open.

**The authority could write the graph.** §49 removed `REMORA_GITHUB_TOKEN` from
the authority but left `graph.internal → GRAPH_DB` routed through the
unrestricted D1 proxy. The authority genuinely needs graph *reads* — grounding
signals, the state index and the semantic bundle all query it to reach a
decision — so the route could not simply be deleted.

It is now read-only, enforced by an **allowlist** (`SELECT`/`WITH`/
`PRAGMA table_info`, no statement chaining) rather than a denylist of mutating
verbs. A denylist has to anticipate every way to write and only has to be wrong
once. The executor keeps unrestricted access, because causing effects is its
job.

Verified on the deployment: a grounded read still reaches `accept`/`executed`,
so the decision path retains the reads it needs.

### What remains open

Recorded here so it is not lost, with the review's identifiers:


None is fixed in this change. Fixing seven findings in one commit would produce
an unreviewable diff for defects that each deserve their own adversarial test,
and RMR-002/003/004 change durable state semantics that consumers depend on.

RMR-002 and RMR-003 were subsequently fixed, each in its own change, and are
recorded as §47 and §48; RMR-009 and RMR-013 are fixed together in §52,
because they are the same defect shape twice; RMR-006 in §53; RMR-004's binding in §54,
whose two sub-checks stay deliberately unreachable. They are struck from the list above rather than
left standing, because a list of open findings that keeps closed ones is the
same drift this document's status gate exists to prevent. RMR-007's supply-chain half is §55; its branch-protection half is the
last one still open, and is a repository-settings change rather than a code one.

### The finding about the findings

Three of the seven were in code I wrote in the preceding two days, and two of
those contradicted docstrings I wrote in the same commits. The pattern is not
carelessness about security — the mechanisms are sound — it is that **prose
asserting a property is written at the moment of highest confidence and lowest
evidence**, and nothing checks it. §49 said the same thing about a comment.
This is now the third consecutive entry in which the defect was a claim rather
than a mechanism.

## §51 The read-only allowlist was wrong once, in the way its own comment warned about (2026-08-24)
<!-- finding-status: accepted -->

**Status:** security defect found by automated review, fixed and verified. A
second finding reported here as OPEN was subsequently **retracted**: it was a
defect in the verification script, not in the system. Both are kept below.

### The allowlist bypass

§50 gave the authority a read-only graph route so a domain holding the private
lease key could not also write the graph. The allowlist accepted a leading
`WITH`, and the commit message said, in the same breath:

> a denylist has to anticipate every way to write and only has to be wrong once

The allowlist was wrong once. SQLite lets a common table expression prefix a
mutation:

```sql
WITH x AS (SELECT 1) INSERT INTO knowledge_facts SELECT * FROM x
```

so `^(select|with)` admitted DML through the read-only route, re-opening the
capability the route was added to close. `WITH` is now refused outright rather
than parsed: no query this deployment issues uses a CTE, so the capability
bought nothing and cost a bypass.

**Why the test did not catch it.** The test read the regex out of the source
and asserted its *shape* — that it matched `^(select|with)` and did not mention
`insert`. A source-shape assertion cannot catch a semantic bypass. The
predicate now lives in its own module (`src/sql.ts`, no Cloudflare imports) and
is exercised with real statements, including the reported bypass, CTE-prefixed
UPDATE and DELETE, comment- and parenthesis-prefixed mutations, statement
chaining and write pragmas.

**Stated limit.** A regex is not a parser. This is a lexical guard at the
proxy, not engine-level enforcement; D1's binding exposes no read-only
connection mode. It is one boundary among several — the registry binds the
tenant clause into every statement and issues only parameterised reads — and it
should be replaced by engine-level enforcement if D1 ever offers it.

### RETRACTED: "graph reads from the tool return no rows"

**This subsection reported a regression that does not exist.** It is corrected
here rather than deleted, because the mistake is the finding.

**What was claimed.** That `kg_list_predicates` returned `status: executed`
with an empty predicate list while 1,251 facts sat in the graph, and that the
custody split had therefore broken governed reads undetected across four
deployments.

**What is true.** The governed read was correct the whole time. Compared by
canonical SHA-256 digest against the exact direct D1 query at the same observed
`state_hash`:

```
governed rows : 50  58a56feacbae36eaed03667e16dc5a0ae5de2221
direct rows   : 50  58a56feacbae36eaed03667e16dc5a0ae5de2221
RESULT: MATCH
```

Same fifty rows, same order, same counts, tenant `luftfiber` echoed correctly.

**The actual defect was in the verification script.** The MCP response nests
the tool's return value inside the dispatcher's result object:

```
payload.result            -> tool_execution  {executed, proposal_id, result, ...}
payload.result.result     -> the tool's own return  {tenant, graph, predicates}
```

Every probe read `payload.result.predicates`, which is `None` on the
`tool_execution` object, and reported `0`. The number was never measured; it
was produced by reading the wrong key.

**Cost.** Three container deployments, one bisect that reverted a correct
security control to test a hypothesis about a fault that was not there, an
incorrect OPEN entry in this document, and an incorrect OPEN entry in CAP-013.

**Why it is recorded.** §49 and §50 both concluded that this project's failures
cluster in claims rather than mechanisms. This one goes further: the claim was
produced by an unverified *measurement*, and it was a measurement asserting
that a system was broken. The same discipline that forbids an unverified
success claim has to forbid an unverified failure claim, and nothing here was
enforcing that.

Two things would have caught it immediately, and neither was done. Comparing
the governed result against the direct query — which is what the effect
verifier does for writes, and what this project already knows how to do — was
only performed *after* the regression was written up. And the probe never
asserted its own shape: a script that reads `payload.result.predicates` should
fail loudly when that key is absent, not report zero.

**What survives.** #357 is unaffected and remains correct on its own terms: an
unknown response shape must not read as an empty result set, whatever else is
true. Its scope statement already said it was "not yet known to repair the
fault" — which was accurate, and is now settled: there was no fault to repair.

**Applied rule.** A probe that reports a system is broken is a claim, and gets
the same evidence standard as a claim that it works: compare against an
independent source at the same observed state, and make the probe fail closed
on an unexpected response shape.

## §52 Two separations were documented and not enforced (2026-08-24)
<!-- finding-status: accepted -->

**Status:** RMR-009 and RMR-013 from the external forensic review, fixed.

Both defects have the same shape, which is why they are one entry. In each
case the mechanism existed, the comment described it correctly, and the code
did not do it.

### RMR-009: the exclusive claim was not exclusive

Both dispatch sites in `remora/execution/service.py` read

```python
# FT-02: claim the intent before anything can take effect (exclusive).
if intent is not None:
    outbox().claim(intent.outbox_id, worker_id=worker_id)
```

`claim` returns `None` when another worker already holds the row. The return
value was discarded at both sites, so a worker that lost the race dispatched
the same intent anyway and then settled over the winner's record. Two workers
therefore produced two side effects, and the durable trail showed one — the
loser's, because it settled last.

The word "exclusive" was in the comment. Nothing tested it. The outbox's own
`claim` docstring even says a lost race "returns ``None``" and distinguishes it
from a caller bug, so the contract was stated at the callee and ignored at the
caller.

A lost claim is now REFUSED for this worker, which is the one negative claim it
can make first-hand: dispatch never began in this process. It says nothing
about the winner's effect, and deliberately settles nothing — the outbox row
and the item's terminal state belong to the worker that won, and writing either
here would overwrite the record of the execution that actually happens. The
loss is appended to the chain, because a gap would read as a lost event rather
than as a refusal.

### RMR-013: the executor served the whole router

The custody split (§45) gave the execution container its own credentials and
only the public verification key. That stops it minting a lease. It does not
stop it issuing authority by API, and the container went on serving every
route: `assess`, `approve`, `execute`, `reject`, the audit reader.

So the deployment could truthfully say the execution domain cannot sign a
lease, while a compromise there could still walk a proposal through assessment
and approval and then execute it. The claim was about key custody and was read
as being about authority.

`REMORA_EXECUTION_DOMAIN_ROLE=executor` now refuses everything but
`/v1/execution/dispatch-leased`. Three details are deliberate:

- The guard is attached to the router, not to each route. A per-route decorator
  is a list a new endpoint silently fails to join, and that failure mode is an
  authority route quietly reachable from the execution domain.
- The path match is exact set membership. A prefix test would admit
  `/dispatch-leased-anything`, which is precisely how the read-only SQL
  allowlist failed one day earlier (§51). The test for it asks the guard
  directly rather than going through the client, because a client request to a
  path no route serves returns 404 whether the guard is anchored or not, and
  the test would have proved nothing.
- An unrecognised role raises. Guessing which half of a custody split a typo
  meant is the wrong way to resolve it, and the fail-open direction is the
  expensive one.

The default stays `authority`, so an unconfigured deployment behaves as it
always did.

### What this pair is evidence of

Both were found by a reader, not by a test, and both had been reviewed. The
common cause is that a separation is easy to state and takes real work to
enforce, and prose costs nothing at the moment of highest confidence — the same
pattern §50 recorded about its own findings. The countermeasure that worked
here was mutation: reverting each fix and confirming the new tests fail.
Applied to the anchored-path test it showed the first version passing against
the broken code, which is how the test came to ask the guard directly.

**Not deployed.** These are code and configuration changes only. The running
containers were not replaced, so nothing here is a claim about the deployment.

## §53 The gateway reported that the API answered, and called it execution (2026-08-24)
<!-- finding-status: accepted -->

**Status:** RMR-006 from the external forensic review, fixed.

Both execution sites in `workers/mcp-gateway/src/mcp.ts` read:

```ts
status: run.status === 200 ? "executed" : "execution_failed"
```

A 200 means the execution API answered. It is not a claim that the tool ran.
The body says what happened, and since §48 it says so explicitly:
`tool_execution.executed`, `dispatch_began`, `state_unknown`.

So a dispatch REMORA refused, and a dispatch whose result was lost, both
reached the model as `"executed"`. This is the worst sentence this gateway can
produce, because the model does not stop there: it tells a person the work is
done. Every mechanism upstream — the lease, the one-time nonce, the durable
outcome classification, the audit chain — computed the right answer, and the
last hop overwrote it with the transport status.

### The fix, and the two places it is stricter than the Python rule

The mapping now derives from the body, in its own module
(`workers/mcp-gateway/src/outcome.ts`) so it can be unit tested rather than
exercised only through a deploy. That is the lesson from the read-only SQL
predicate (§51), applied before rather than after.

It is deliberately stricter than `remora/execution/outcome.py` in two places,
because the input is different: the Python classifier reads a dict its own
dispatcher just built, and the gateway reads wire data.

- **A 200 with no `tool_execution` is `unknown`, not `executed`.** Absence of
  evidence is the exact thing this entry is about.
- **`refused` requires `dispatch_began === false`, not merely an absent
  field.** Otherwise an empty body would produce the strongest negative claim
  the gateway can make, on no evidence at all — the same error as §48, in the
  other component.

`unknown` carries wording the model cannot read as either verdict, and tells it
not to retry: re-running a call that may already have taken effect is the one
move that must not happen. `executed` carries no added prose, because prose on
the success path is how a caveat becomes noise.

Two smaller things fell out of the change. Effect verification is no longer
attempted on a refused dispatch — nothing was sent, so the system of record
correctly shows no change, and reporting that as `EFFECT_MISMATCH` would
manufacture bad news out of a correct refusal. And the poll response built two
`explanation` keys in one object literal, silently keeping the last; the one
being dropped was the dispatch status.

### The test fixtures were the defect, written down as an expectation

Two existing tests failed against the corrected rule. Their fixture was
`{ outcome: "executed" }` with no `tool_execution` at all, and the tests
asserted the gateway reported `"executed"` from it. That is RMR-006 itself,
encoded as a passing test: a body that proves nothing, asserted to mean
success. The fixtures were corrected to what the API actually returns rather
than the rule being relaxed to keep them green.

The first version of the new end-to-end tests also passed against the broken
code, because the test helper takes the assess body and the options as separate
positional arguments and the override was silently landing in the wrong one.
Mutation — reverting the fix and requiring the tests to fail — caught both.
Seven now fail without it.

**Not deployed.** Gateway source only; the Worker was not redeployed.

## §54 The signed spec identity was unforgeable and never read (2026-08-24)
<!-- finding-status: accepted -->

**Status:** RMR-004 from the external forensic review, the binding fixed. Two
sub-checks deliberately left unreachable, and one adjacent item left open —
both recorded below rather than folded in.

`ExecutionLease` has carried `toolspec_hash` and `toolspec_version` since it
was written, and `ExecutionLease.verify` has always been able to compare them:
the parameters exist, the mismatch reasons exist, the tests for `verify` exist.
Nothing ever supplied them at dispatch. The call at the final PEP passed the
tool name, the arguments, the tenant, the target, the clock, the policy bundle
and the actor, and omitted the two arguments that identify the spec.

The identity was therefore in the signature — genuinely unforgeable — and never
read. That is a specific and slightly humbling failure mode: the expensive part
was built, and the cheap part, passing two arguments, was not.

### Why the gap is exactly the window the field exists to cover

Between issuing a lease and dispatching under it, the bundle can be replaced.
In the custody split (§45) it is not even the same file: the executor's bundle
lives on a different container from the authority's. A spec that moved in that
window means the action about to run is not the action that was reviewed, which
is the sentence `verify_same_spec` in `toolspec.py` was written to be able to
say, and nothing was asking it.

### The resolver refuses on failure rather than falling through

The dispatcher now resolves the identity this process would run, at the moment
of dispatch. Two return values are distinct and must stay distinct:

- `None` means no bundle is configured. That is the unenforced research path,
  reported as `enforced=False` everywhere else, and it stays permitted.
- A **raise** means a bundle is configured and could not answer. That refuses
  as `toolspec_unresolvable`.

Collapsing them would turn "I could not check" into "there was nothing to
check". It is the same shape as the strict capability-freshness flag (§46),
where an unresolvable binding classified as UNKNOWN and the gate reported
success.

The refusal also happens before the nonce is consumed, so a spec mismatch
leaves the grant usable. Burning it would convert a recoverable configuration
error into a permanently dead authorization.

### What is NOT fixed, and why approximating it would be worse

`verify_callable` and `verify_credential_scope` still have no non-test caller.
Neither is an oversight now that they have been looked at:

- `verify_callable` compares the registered callable against a digest the spec
  attests. **Nothing in this repository produces such a digest** — every bundle
  fixture carries a placeholder. Calling it would compare a real callable
  against a constant.
- `verify_credential_scope` needs the scope dispatch is about to *use*. Nothing
  tracks that: the callables close over their own credentials and do not
  declare what they reach for. Comparing the declaration against itself is a
  check that cannot fail.

This is the §48 rule applied to a different mechanism: where the evidence does
not exist yet, leave the check unreachable rather than approximating it. A test
pins that both remain uncalled, so the day one gains a caller, the input it
needs exists and the claim it supports has to be written down with it.

The SDAD spec-intake linkage at dispatch, which the review raised alongside
RMR-004, is also untouched here. It is a different mechanism with a different
evidence question, and folding it in would have produced one diff for two
unrelated arguments.

**Not deployed.** Code only.

## §55 The component holding execution authority was the one nobody audited (2026-08-24)
<!-- finding-status: open -->

**Status:** RMR-007 from the external forensic review. The supply-chain half is
fixed. The branch-protection half is **not**, and is the reason this entry is
`open` rather than `accepted`.

### The supply-chain half

The npm dependency audit ran over a hand-maintained list of directories:
`frontend`, `agent-control`, `aromer`, `law-search`, `rag-oracle`.
`workers/mcp-gateway` was not on it. The SBOM covered the Python package and
the frontend, and no worker at all.

Of everything in this repository the gateway is the component that holds
execution authority and the downstream credentials. It was the one package
whose dependencies went unaudited: the inverse of the order anyone would pick
deliberately, which is what identifies it as drift rather than a decision. The
list was written before the gateway existed and nothing made adding a directory
also add its audit leg.

Nothing had gone wrong — the audit is clean, 0 vulnerabilities. The finding is
that no gate would have said either way.

The list is now checked against what is on disk, so a new package cannot ship
without an audit leg. The failure mode moves to a red test the moment the
package appears, instead of a gap that waits for a reader. Only the gateway
SBOM is added; the other four workers remain uncovered and the test
deliberately does not claim otherwise. Generating one of five and calling it
worker coverage is the kind of prose this document keeps having to retract.

### The branch-protection half, which is not fixed

`master` requires five contexts: `verify`, the three `pytest` legs, and
documentation governance. Not required, and therefore not blocking:

- CodeQL, both languages
- Secret scanning, `pip-audit`, the npm audits, the SBOM job
- OPA/Rego policy conformance, key artifact integrity, lockfile integrity
- The wheel contract, the Postgres tenant-chain contract, `worker-typecheck`

Every one of them runs, and reports, and can be red on a mergeable pull
request. The security gates in this repository are advisory and the summary
does not say so.

This is left open rather than fixed in this change on purpose. Adding a
required context whose name does not exactly match the job's reported name
blocks every merge on `master` until someone with admin rights notices, and
the exact strings are worth confirming against a real run rather than
inferring. It is a repository-settings change, not a code change, and the
person who owns the repository should make it knowingly.

The mechanism half is now in code: each security workflow carries a stable
aggregator job — `quality-gates-required`, `deterministic-suite-required`,
`supply-chain-required`, `codeql-required` — that runs under `if: always()`
and fails unless every leg it aggregates reported success, so branch
protection can require five names instead of thirty drifting matrix-expanded
ones, with `shadow-replay` required directly. The entry stays `open` until
the setting itself is applied and a control change has demonstrated that a
failing aggregator actually blocks a merge: *runs* and *enforced* are
different properties, and only the second one closes this.

The observation stands on its own either way: **this repository has been
enforcing far less in CI than its own workflow file appears to promise, and
that gap is invisible from the file.** Reading `.github/workflows/` tells you
what runs. It does not tell you what blocks.

**Not deployed.** CI configuration and a test.

