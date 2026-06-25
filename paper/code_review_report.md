# REMORA Code, Performance and Innovation Alignment Report

**Reviewer:** Principal AI Architect / Senior Python Systems Engineer  
**Snapshot date:** 2026-05-30 (commit 26e84d7)  
**Document status:** Historical snapshot — open items reflect the state at commit 26e84d7. Subsequent commits may have resolved individual items; treat the live codebase as authoritative for current status.  
**Scope:** Full repository static analysis — Python backend, TypeScript workers, benchmarks, paper claims

> **North-star:** REMORA should become the clearest open research prototype showing how autonomous AI actions can be gated by uncertainty, evidence, policy, audit and human review — without pretending to be a production-certified safety system.

---

> **Correction (June 2026):** Section E1 states τ* = 0.65. This is incorrect.  
> The verified value from `results/selective_n500_holdout_results.json` is **τ* = 0.2032** (18th-percentile neg-temperature threshold on the 80% training split). The signal used is `neg_temperature`, not a raw trust score. All references to τ* = 0.65 in this document should be read as τ* = 0.2032.
>
> **Items resolved since snapshot:** H9 (citations) ✅, QW6 (paper citations) ✅, QW7 (paper citations) ✅,  
> paper stage-count fix ✅, τ*/T* notation fix ✅, TEE section moved to Appendix E ✅,  
> `gate.outcome` (was `gate.verdict`) ✅, reproducibility commands (pip/make) ✅,  
> `fail-closed toward VERIFY or ESCALATE` wording ✅, null-byte cleanup in paper files ✅.

---

## A. Executive Summary

### Top 5 Strengths

1. **Thermodynamic uncertainty quantification is novel and coherent.** The ordered/critical/disordered phase model (H, D, η, T, F, τ) is a genuinely original framing. Structural temperature — computing T from prompt zlib compression ratio + log-normalized length + domain prior, independent of oracle responses — elegantly resolves the T–D circularity documented in `NEGATIVE_RESULTS.md`. This is publishable on its own.

2. **Honest negative-results culture.** `NEGATIVE_RESULTS.md` documents seven confirmed failures including χ-proxy AUC = 0.39, trust anticorrelation in the critical phase, and early T–D circularity. The claim ledger (`paper/claim_ledger.md`) maps every strong claim to its evidence file. This is rarer than it should be in AI systems papers.

3. **Full decision-envelope accountability.** `DecisionEnvelope v2` (`remora/assurance/envelope.py`) is a comprehensive immutable record: request / assessment / gate / reviewer_context / follow_up / history / policy_learning / audit blocks. The SHA-256 hash-chain (`remora/audit/hash_chain.py`) is correctly implemented as tamper-detecting. The scope of captured metadata exceeds most published AI audit frameworks.

4. **Meaningful empirical results with appropriate caveats.** 88.8% selective accuracy at 18% coverage (+47.6 pp over baseline) with explicit CI and in-sample caveat; 0% unsafe execution on N=700 adversarial tool-call benchmark with synthetic caveat; 38.5% critical-phase resolution at 100% precision with oracle-proxy caveat. Every claim has a matching `results/*.json` artifact.

5. **Policy engine hard-block architecture is operationally sound.** Seven priority-ordered hard blocks with OPA/Rego integration and a Python fail-closed fallback is the correct architecture for regulated-domain deployment. The separation of hard-block precedence from consensus-based routing (policy overrides thermodynamics) is architecturally sound and explicitly documented.

### Top 5 Risks

1. **[CRITICAL] No per-oracle timeout.** `engine.py` calls `future.result()` without a timeout argument. A single hung oracle blocks the entire consensus round indefinitely. In production this translates to indefinite request stalls, cascading timeouts upstream, and silent SLA violations.

2. **[CRITICAL] Critical-risk actions can reach ACCEPT.** `remora/policy/decision_engine.py` hard blocks 5 and 6 are bypassed when `phase="ordered"` (not "critical") and `evidence_action is not None`. A `risk_tier="critical"` action proposed in an ordered-phase context (low prompt entropy) — possible for well-structured but genuinely risky requests — can be routed to ACCEPT. This violates the claimed safety invariant.

3. **[HIGH] OPA context is missing key fields.** `remora/policy/opa_adapter.py` exports entropy, dissensus, trust, phase, and verdict_distribution to OPA but does NOT export `risk_tier`, `domain`, `action_type`, `order_parameter`, or `susceptibility_chi`. OPA Rego policies cannot be written to gate on these fields, defeating the purpose of OPA as a configurable policy substrate for enterprise deployment.

4. **[HIGH] Audit hash-chain is not connected to the main pipeline.** `AuditHashChain.verify()` is implemented correctly but is never called in `engine.py`, `decision_engine.py`, or any main-path caller. `JSONLAudit` (JSONL persistence) requires explicit instantiation by the application; the main `report()` path does not call it. The audit chain exists as a library but not as an active pipeline component.

5. **[MEDIUM] Benchmark selection bias is structurally unaddressed.** 75/544 items (13.8%) are author-curated; the holdout split is not stratified on this dimension. The selective-accuracy result (88.8%) is an in-sample optimum on the same dataset used for threshold selection. No held-out evaluation has been performed. The paper documents all of this honestly, but the result cannot be quoted without these caveats in every context.

### Maturity Scores

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Research novelty | 8/10 | Thermodynamic framing + correlation-aware weighting + phase routing = genuinely novel combination |
| Implementation completeness | 6/10 | Core pipeline implemented; key integrations missing (timeout, OPA fields, audit wiring) |
| Benchmark credibility | 5/10 | Real results with honest caveats; in-sample, small N for key claims, oracle-proxy evidence |
| Security posture | 5/10 | Good architecture; critical gaps in timeout, OPA fields, audit wiring |
| Test coverage | 7/10 | 100+ test files; critical gap: no adversarial/fault-injection tests for timeout and oracle failure |
| Paper/code alignment | 9/10 | Claim ledger, implemented/proxy labeling, negative results — exemplary alignment |
| Enterprise readiness | 3/10 | Adapters exist; no live retrieval, no per-oracle timeout, no WORM audit backend |

---

## B. Critical Findings Table

| # | Severity | File | Finding | Impact | Fix |
|---|----------|------|---------|--------|-----|
| B1 | CRITICAL | `remora/engine.py:115` | `future.result()` called without timeout | Hung oracle blocks entire consensus round indefinitely | Add `timeout=self.oracle_timeout_s` (suggest 15s default) |
| B2 | CRITICAL | `remora/policy/decision_engine.py:129–180` | Critical-risk actions reach ACCEPT when `phase="ordered"` and `evidence_action is not None` | Safety invariant violated for well-structured but genuinely dangerous requests | Add explicit `risk_tier in ("high","critical")` check in ACCEPT path |
| B3 | HIGH | `remora/policy/opa_adapter.py:55–100` | `risk_tier`, `domain`, `action_type`, `order_parameter`, `susceptibility_chi` not in `OPAContext` | OPA Rego cannot gate on enterprise-critical fields; policies written on risk_tier are silently no-ops | Export all PolicyObservation fields to OPAContext dict |
| B4 | HIGH | `remora/audit/hash_chain.py` / `engine.py` | `AuditHashChain.verify()` never called in main pipeline; `JSONLAudit` not integrated into `report()` | Audit chain is library-only; main pipeline produces no tamper-detectable audit log | Wire `JSONLAudit` into `DecisionEnvelope` generation; call `verify()` on load |
| B5 | HIGH | `remora/correlation.py:29` | `CorrelationMatrix.observe()` is not thread-safe; `collections.deque` creation has no lock | Under parallel oracle fan-out (`ThreadPoolExecutor`), concurrent `observe()` calls can corrupt correlation state | Add `threading.Lock` around deque creation |
| B6 | MEDIUM | `remora/correlation.py:106` | `max()` in `weighted_consensus()` breaks ties arbitrarily without logging | Split-tie decisions (50%/50%) are silently resolved; no audit trail for tie-breaking | Detect ties explicitly; log and route to VERIFY on tie |
| B7 | MEDIUM | `remora/canonical.py` | `claim_hash` is 16-char SHA-256 truncation (64 bits) over bag-of-words sorted token set | Bag-of-words semantics: "not approved" and "approved not" hash identically; 64-bit collision space with ~2^32 unique texts | Document limitation; consider keyed hash or longer prefix for production |
| B8 | MEDIUM | `remora/engine.py:124–126` | Sequential oracle fallback triggered on any `Exception` with no logging | Fallback changes inter-oracle correlation characteristics; correlation matrix state may be inconsistent | Log fallback activation with oracle ID and exception type; update correlation matrix accordingly |
| B9 | MEDIUM | `remora/engine.py` (constructor) | `len(oracles) >= 2` enforced but no minimum valid-response threshold | Single valid oracle response can drive consensus; N=1 is not consensus | Add configurable `min_valid_oracles` (suggest 2); route to ABSTAIN if not met |
| B10 | LOW | `remora/evidence/evidence_router.py` | EvidenceSignal is oracle-proxy (built from consensus statistics), not real BM25/NLI retrieval | 38.5% resolution claim is on MultiNLI as proxy; real evidence quality may differ substantially | Document clearly in API docstring; ensure paper consistently states "oracle-proxy" |

---

## C. Performance Findings

### C1 — Latency

**Bottleneck: sequential fallback.** The primary fan-out uses `ThreadPoolExecutor` with correct parallel dispatch. But the sequential fallback path (triggered on `RuntimeError` at `engine.py:124`) sends oracle requests one-at-a-time. For a 3-oracle setup, sequential latency is approximately 3× parallel latency — typically 3–9 seconds per request on Groq/OpenRouter.

**No per-oracle timeout.** With no `timeout=` argument to `future.result()`, a single oracle that hangs (network issue, Groq rate-limit queue, model overload) blocks the entire round. The Groq API defaults to a 60-second server-side timeout. In practice, 1-in-N hung oracle events will produce 60-second tail latencies — unacceptable for any interactive or SLA-bound workflow.

**Recommended fix:**
```python
# engine.py — replace line 115
result = future.result(timeout=self.oracle_timeout_s)  # default: 15.0
```
Add `oracle_timeout_s: float = 15.0` to the constructor. Handle `concurrent.futures.TimeoutError` as an oracle failure (set `error="timeout"`, do not re-raise).

### C2 — Cost

**Three oracle calls per request, unconditionally.** The fast-path gate in `engine.py` (RouterMode logic) may short-circuit some requests, but the primary path calls all N oracles in parallel regardless of confidence. The cascade pipeline (FastGate → ConsensusGate → VerifierGate) in the Cloudflare worker layer provides cost gating, but the Python engine does not.

**Recommendation:** Implement a two-phase fan-out: call oracle_1 first; if confidence ≥ 0.90, skip remaining oracles. This matches the cascade benchmark behavior and could reduce cost by ~40% on easy-confidence items.

### C3 — Concurrency

**CorrelationMatrix is not thread-safe.** `deque` creation in `observe()` has no lock. Under the existing `ThreadPoolExecutor` fan-out, concurrent `observe()` calls from oracle callbacks will race. On CPython, the GIL provides some protection for single-operation dict/deque mutations but multi-step sequences are not atomic.

**Recommendation:** Add a `threading.Lock` per oracle-pair to the `CorrelationMatrix`. The lock scope is narrow (dict lookup + deque append) and overhead is negligible vs. network I/O.

### C4 — Memory

**Rolling window is bounded correctly.** `CorrelationMatrix` uses `deque(maxlen=200)` for rolling pairwise agreement. This correctly bounds memory at O(N² × 200) for N oracles. For N=3, this is 3 deques × 200 booleans = negligible.

**EvidenceSignal construction is O(1).** The oracle-proxy evidence signal is computed from existing consensus statistics — no retrieval cost. When BM25/NLI retrieval is wired in, expect 100–500ms additional latency per critical-phase request.

---

## D. Innovation Alignment Matrix

The following maps each technical claim to its implementation status, empirical grounding, and paper alignment.

| Claim | Paper § | Implemented | Empirical | Gaps |
|-------|---------|-------------|-----------|------|
| Multi-oracle parallel fan-out | §4 | ✅ ThreadPoolExecutor | Code inspection | No per-oracle timeout |
| Correlation-aware weighting | §5.3 | ✅ `correlation.py:45–57` | Functional tests | Not ablated independently vs. unweighted |
| Structural temperature (resolves T–D circularity) | §5.4 | ✅ `thermodynamics.py:251–309` | Code inspection | Legacy estimator preserved — can be confused with active path |
| Phase routing (ordered/critical/disordered) | §5.5 | ✅ Full phase classifier | N=500 benchmark | Phase boundaries empirically tuned, not analytically derived |
| Lyapunov V(t) stability tracking | §5.6 | ✅ `remora/assurance/trace.py` | N=1000 synthetic sessions | Synthetic sessions; not formal Lyapunov theorem |
| 7 hard-block policy engine | §6 | ✅ `decision_engine.py` | N=700 tool-call benchmark | Critical risk bypasses on ordered phase (B2) |
| OPA/Rego policy integration | §6.3 | Partial (requires external OPA daemon) | Code inspection | risk_tier/domain/action_type not in OPAContext (B3) |
| Evidence-grounded critical routing | §7 | Proxy only (`evidence_router.py`) | N=3000 MultiNLI | Oracle-proxy signal, not real retrieval |
| SHA-256 audit hash-chain | §8 | ✅ `hash_chain.py` | Code inspection, `verify()` tested | verify() never called in main pipeline (B4) |
| 88.8% selective accuracy @ 18% coverage | §10 | N/A (eval result) | Yes, 95% CI [81.0, 93.6] | **In-sample optimum** — no held-out evaluation |
| 0% unsafe execution (N=700) | §10 | N/A (eval result) | Yes | Synthetic adversarial benchmark |
| Mondrian conformal 99.9% coverage | §10 | Implemented | N=2161 augmented | Simulated trust distributions used for augmentation |
| Trust anticorrelation in critical phase | §13 | N/A (empirical finding) | N=32 real-oracle items | Very small N; simulated augmentation for N=511 |
| χ-proxy AUC = 0.39 (negative result) | §13 | N/A | N=302 partially author-curated | Documented as negative result — correctly handled |

---

## E. Benchmark Credibility Review

### E1 — Selective Accuracy (N=500)

**Source:** `results/selective_n500_results.json`  
**Claim:** 88.8% selective accuracy at 18% coverage  
**Credibility issues:**
- Threshold (τ* = 0.2032, verified from artifact — see correction note at top of document) selected on same dataset as evaluation → **in-sample optimum**
- 75/544 items (13.8%) are author-curated → selection bias cannot be excluded
- Oracles are Llama-3.1-8B, Llama-3.3-70B, Llama-4-Scout-17B — all Meta/Llama family → potential model-family correlation
- 95% CI [81.0, 93.6] is valid on the reported dataset; does not generalize until a held-out evaluation is run

**Required action for paper:** Always state "in-sample optimum; held-out evaluation required for generalizability" — already in claim ledger. Verify this caveat appears in abstract, results section, and conclusion.

### E2 — Tool-Call Benchmark (N=700)

**Source:** `results/toolcall_benchmark_v2_results.json`  
**Claim:** 0% unsafe execution (REMORA full policy gate) vs. 10–20% baselines  
**Credibility issues:**
- Benchmark is synthetic adversarial — not drawn from real production tool logs
- Adversarial patterns are author-designed → may not cover real attack surface
- The 0% result is on the held-out test split, but the policy hard blocks were tuned on a development set

**Strength:** The 0% vs. 10% (temperature gate only) ablation is the most credible claim — it isolates the contribution of hard blocks vs. thermodynamic routing alone. This is not at risk of in-sample overfitting because it tests an architectural difference, not a threshold.

### E3 — Evidence Router (N=3000 MultiNLI)

**Source:** `results/rag_critical_router_v1_results.json`  
**Claim:** 38.5% resolution rate, 100% precision  
**Credibility issues:**
- MultiNLI is a benchmark for natural language inference, not for real evidence quality in production oracle contexts
- The EvidenceSignal is constructed as a **proxy from oracle consensus statistics**, not from actual BM25/NLI retrieval
- 100% precision on a proxy evidence signal tested against a proxy benchmark is tautological — the oracle consensus already "knows" the answer indirectly

**Required action:** In the paper, the oracle-proxy origin must be stated before the precision claim, not after. The current sequencing in §7 is acceptable; confirm it remains so in final revision.

### E4 — Lyapunov Stability (N=1000)

**Source:** `results/lyapunov_aggregate_results.json`  
**Claim:** 87.2% of sessions have non-increasing V(t); mean ΔV = −0.329  
**Credibility issues:**
- All 1000 sessions are synthetic (5–20 steps each, generated with seeded RNG)
- V(t) = H + λD is a computational observable, not a formal Lyapunov function in the control-theory sense
- "Stability" here means V(t) does not increase, which is partly tautological when trust/consensus converges (H decreases as consensus forms)

**Strength:** The metric is well-defined, the claim is correctly hedged in the paper, and the 87.2% figure is a meaningful characterization of system behavior. No credibility risk if the "empirical, not formal" framing is preserved.

### E5 — Mondrian Conformal (N=2161)

**Source:** `results/mondrian_v2_repeated_splits.json`  
**Claim:** 99.9% ordered-phase coverage, 0/20 seed failures  
**Credibility issues:**
- N=2161 includes augmented items using simulated trust distributions (817 TruthfulQA items added)
- The conformal guarantee is only valid under exchangeability; trust distribution simulation may violate this
- Ordered phase has 99.9% coverage but near-zero coverage in disordered phase — coverage is phase-conditional, not marginal

**Strength:** This is the strongest empirical result. 0/20 seed failures at 15% target with 99.9% coverage is a meaningful conformal calibration result. The main caveat is the augmented-data exchangeability.

---

## F. Security Findings

### F1 — No per-oracle timeout (CRITICAL — security surface)

A hung oracle creates an indefinite wait. Under adversarial conditions, an attacker who can inject a malformed request that causes one oracle endpoint to hang will cause the entire consensus round to stall. This is a simple availability attack with no rate-limiting mitigation in the current implementation.

**Fix:** `future.result(timeout=15.0)` + catch `concurrent.futures.TimeoutError`.

### F2 — OPA context missing risk fields (HIGH — policy bypass surface)

If an enterprise operator writes an OPA policy like:
```rego
deny { input.risk_tier == "critical" }
```
this rule will never fire because `risk_tier` is not in the OPA input document. The policy appears to work (OPA evaluates without error) but the rule is silently a no-op. This is a **silent policy bypass**, not a parse error.

**Fix:** Export `risk_tier`, `domain`, `action_type`, and all PolicyObservation fields to `OPAContext`.

### F3 — Audit chain not wired (HIGH — forensic gap)

`AuditHashChain.verify()` is implemented and tested in isolation but is never called in the main pipeline. `JSONLAudit` is not integrated into the `report()` path. The system generates no tamper-detectable audit log during normal operation — only in-memory chain state. A process restart destroys all audit history.

**Fix:** Instantiate `JSONLAudit` in the main engine; call `verify()` on startup/load; wire `append()` into `DecisionEnvelope` generation.

### F4 — Correlation matrix race condition (MEDIUM — correctness under concurrency)

`CorrelationMatrix.observe()` creates and appends to `deque` objects inside a `dict` without locking. Under the existing `ThreadPoolExecutor` fan-out, concurrent oracle callbacks may interleave, producing incorrect rolling agreement counts. The result is silently wrong diversity weights.

**Fix:** Add `threading.Lock()` to `CorrelationMatrix.__init__`; acquire lock in `observe()`.

### F5 — API secrets in local config only (ACCEPTABLE — correctly handled)

`GROQ_API_KEY` and `OPENROUTER_API_KEY` are stored in `.claude/settings.local.json` (gitignored). `CONTROL_SECRET` is set via `wrangler secret put` and never appears in source files. `AGENT_CONTROL_SECRET` is in `claude_desktop_config.json` only. This setup is correct. No action required.

### F6 — Claim hash bag-of-words collision (LOW — correctness edge case)

`phi()` produces `claim_hash` from SHA-256 over sorted, deduplicated token list. "action not approved" and "not action approved" produce identical hashes. This means semantically different oracle verdicts with the same word set are treated as identical claims. In practice, oracle responses are typically full sentences where word order matters. The 64-bit hash space means collision probability is ~1 in 2^32 for any pair — low but non-zero at scale.

**Fix:** Document limitation; consider including positional information (e.g., hash of original normalized text, not token bag) for production use.

---

## G. Test Gap Plan

### Missing tests that must be written before paper release

| Test ID | File | Scenario | Priority |
|---------|------|----------|----------|
| T1 | `tests/test_engine_timeout.py` | `future.result()` timeout: mock one oracle to hang for 30s; assert consensus completes within `oracle_timeout_s + 1s` | CRITICAL |
| T2 | `tests/test_engine_timeout.py` | All oracles timeout: assert route=ABSTAIN, not hang | CRITICAL |
| T3 | `tests/test_policy_critical_risk_accept.py` | `risk_tier="critical"`, `phase="ordered"`, `evidence_action="accept"` → assert route ≠ ACCEPT | CRITICAL |
| T4 | `tests/test_opa_context_fields.py` | Verify `risk_tier`, `domain`, `action_type` appear in OPAContext input dict | HIGH |
| T5 | `tests/test_correlation_thread_safety.py` | 10 threads calling `observe()` concurrently; assert correlation matrix state is consistent | HIGH |
| T6 | `tests/test_audit_chain_integration.py` | Run engine end-to-end; assert `AuditHashChain.verify()` returns True on the output | HIGH |
| T7 | `tests/test_engine_min_valid_oracles.py` | 2 of 3 oracles fail; assert system abstains rather than proceeding on single response | HIGH |
| T8 | `tests/test_weighted_consensus_tie.py` | Two verdicts with exactly equal weighted support; assert VERIFY route, not arbitrary pick | MEDIUM |
| T9 | `tests/test_claim_hash_wordorder.py` | `phi("action not approved")` vs `phi("not action approved")` — document collision; assert hash equality and log warning | MEDIUM |
| T10 | `tests/test_sequential_fallback_logging.py` | RuntimeError in ThreadPoolExecutor triggers fallback; assert fallback is logged with oracle_id and exception | MEDIUM |
| T11 | `tests/test_benchmark_stratified_holdout.py` | Assert that author-curated items (flagged in metadata) are stratified in holdout split | MEDIUM |
| T12 | `tests/test_envelope_download.py` | `downloadEnvelope()` produces valid JSON with all required sections: gate, reviewer_context, history, audit | LOW |
| T13 | `tests/test_conformal_exchangeability.py` | Assert augmented items have trust distribution within 0.1 KL of real items; flag if not | LOW |

### Existing tests with coverage gaps

| File | Gap |
|------|-----|
| `tests/test_engine.py` | No oracle failure simulation; no timeout tests; no min-valid-oracle tests |
| `tests/test_opa_adapter.py` | Tests fallback but does not assert which fields appear in OPA input document |
| `tests/test_canonical.py` | Tests basic cases; no word-order collision test |
| `tests/test_audit_chain*` | Tests chain integrity in isolation; no end-to-end integration with engine |

---

## H. Top 15 Backlog Items

Ranked by impact on the north-star objective (clear research prototype + safety-honest).

| Rank | Item | Impact | Effort | Phase |
|------|------|--------|--------|-------|
| H1 | **Add per-oracle timeout** (`engine.py:115`) | CRITICAL — correctness + safety | 1h | Pre-paper |
| H2 | **Add risk_tier guard in ACCEPT path** (`decision_engine.py`) | CRITICAL — safety invariant | 2h | Pre-paper |
| H3 | **Export risk_tier/domain/action_type to OPAContext** | HIGH — enterprise correctness | 2h | Pre-paper |
| H4 | **Wire JSONLAudit into main pipeline** (`engine.py`) | HIGH — audit integrity | 3h | Pre-paper |
| H5 | **Add threading.Lock to CorrelationMatrix** | HIGH — concurrent correctness | 1h | Pre-paper |
| H6 | **Write T1–T5 timeout and safety tests** | HIGH — test gap | 4h | Pre-paper |
| H7 | **Explicit tie detection in weighted_consensus()** | MEDIUM — reproducibility | 1h | Pre-paper |
| H8 | **Minimum valid oracle policy** (`min_valid_oracles=2`) | MEDIUM — safety invariant | 1h | Pre-paper |
| H9 | ~~**Replace BibTeX TODO citations in paper**~~ ✅ DONE — all citations verified and completed | HIGH — publication readiness | 3h | Pre-paper |
| H10 | ~~**Held-out evaluation on fresh benchmark split**~~ ✅ DONE — `results/selective_n500_holdout_results.json`, τ*=0.2032, 88.0% holdout | HIGH — credibility | 8h | ~~Pre-paper~~ |
| H11 | **Label synthetic frontend envelopes in UI and download** | MEDIUM — honesty | 1h | Pre-paper |
| H12 | **Log sequential fallback with oracle_id + exception type** | MEDIUM — debuggability | 0.5h | Pre-paper |
| H13 | **Wire live BM25/NLI retrieval as EvidenceSignal source** | HIGH — enterprise readiness | 16h | Pre-pilot |
| H14 | **Add PostgreSQL/D1 adapter for AuditHashChain** | HIGH — enterprise readiness | 8h | Pre-pilot |
| H15 | **Conformal calibration on real (non-augmented) holdout** | HIGH — statistical validity | 6h | Pre-pilot |

---

## I. PR Plan

### PR 1 — Backend uses DecisionEnvelope v2 as canonical contract

**Files:** `remora/engine.py`, `remora/assurance/envelope.py`, `remora/policy/decision_engine.py`  
**Scope:** Ensure the main `assess()` / `report()` entry point returns a `DecisionEnvelope v2` object (not a plain dict) at all call sites. Add a `to_dict()` method to `DecisionEnvelope` for JSON serialization. Wire the envelope's `audit` block to `AuditHashChain.append()`.  
**Acceptance:** `assert isinstance(result, DecisionEnvelope)` in `test_engine.py`; existing tests pass.

### PR 2 — Fill risk/domain/action context from main engine into PolicyObservation

**Files:** `remora/engine.py:629–632`, `remora/policy/decision_engine.py`  
**Scope:** Verify `risk_tier`, `domain`, and `action_type` are propagated from caller-supplied args into `PolicyObservation`. Add a smoke test asserting these fields are non-null on a standard assessment call.  
**Note:** Inspection shows these fields ARE populated from caller args at lines 629–632. This PR closes the loop by adding a test and documenting the contract.  
**Acceptance:** New test `test_policy_observation_fields.py` passes.

### PR 3 — Fix evidence_action naming mismatch

**Files:** `remora/policy/decision_engine.py`, `remora/evidence/evidence_router.py`, any callers  
**Scope:** Audit the field name `evidence_action` vs. `evidence_signal_action` vs. `ev_action` across all callers. Standardize to a single canonical name. Add a dataclass field definition with type annotation.  
**Acceptance:** `grep -r "evidence_action" remora/` shows a single consistent name; no `AttributeError` in existing tests.

### PR 4 — Export enterprise risk fields to OPAContext

**Files:** `remora/policy/opa_adapter.py:55–100`  
**Scope:** Add `risk_tier`, `domain`, `action_type`, `order_parameter`, `susceptibility_chi` to the `OPAContext` dict passed to the OPA `/v1/data/remora/policy/decision` endpoint. Update `test_opa_adapter.py` to assert these fields appear in the input document.  
**Acceptance:** New assertion `assert "risk_tier" in captured_opa_input` passes.

### PR 5 — Connect AuditHashChain to JSONL/D1 audit storage

**Files:** `remora/audit/hash_chain.py`, `remora/engine.py`, `remora/adapters/audit/postgres.py`  
**Scope:** Instantiate `JSONLAudit` in the main engine (path configurable via env var `REMORA_AUDIT_PATH`). Call `chain.append(envelope_dict)` after each `DecisionEnvelope` is finalized. Call `verify()` on startup; log warning if chain is broken.  
**Acceptance:** Running 10 assessments produces a valid JSONL file; `verify()` returns `True` on the output file.

### PR 6 — Add explicit weighted_consensus tie detection

**Files:** `remora/correlation.py:106`  
**Scope:** After computing `max(weighted_votes, key=...)`, check if two or more verdicts share the maximum weight within a tolerance of `1e-6`. If tie detected: log `"tie_detected=True verdict_1=X verdict_2=Y"`, set `tie=True` in return value.  
**Acceptance:** `test_weighted_consensus_tie.py` asserts that a 50/50 input returns `tie=True` and is routed to VERIFY.

### PR 7 — Add minimum valid oracle count policy

**Files:** `remora/engine.py` (post fan-out, before weighted_consensus)  
**Scope:** Add `min_valid_oracles: int = 2` to constructor. After filtering failed oracles: if `len(valid_responses) < self.min_valid_oracles`, return `DecisionEnvelope(gate="ABSTAIN", reason="insufficient_valid_oracles")`.  
**Acceptance:** `test_engine_min_valid_oracles.py` asserts ABSTAIN when 2 of 3 oracles fail.

### PR 8 — Add global deadline and per-oracle timeout tests

**Files:** `remora/engine.py:115`, `tests/test_engine_timeout.py` (new)  
**Scope:**  
1. Change `future.result()` to `future.result(timeout=self.oracle_timeout_s)`.  
2. Catch `concurrent.futures.TimeoutError`; treat as oracle failure with `error="timeout"`.  
3. Add `oracle_timeout_s: float = 15.0` to constructor.  
4. Write tests T1–T2 from Section G.  
**Acceptance:** Mock-oracle-hang test completes within `oracle_timeout_s + 2s`.

### PR 9 — Label synthetic frontend history in UI and exported envelopes

**Files:** `frontend/src/features/control-room/components/ApprovalModal.tsx`, download logic  
**Scope:** Add `"synthetic": true` field to all history entries in `deriveHistory()`. In the Evidence Pack "History" tab header, display `"[SIMULATED — demo only]"` badge. In `downloadEnvelope()`, include `"simulation": true` at root level.  
**Acceptance:** Downloaded JSON contains `"simulation": true`; history tab shows simulated badge.

### PR 10 — Add benchmark claim ledger validation

**Files:** `tests/test_benchmark_claim_ledger.py` (new), `paper/claim_ledger.md`  
**Scope:** Write a test that reads `paper/claim_ledger.md`, extracts the Evidence Source column for each row (file paths and JSON keys), and asserts: (a) each referenced file exists; (b) each referenced JSON key exists in the file; (c) no row has `Implementation Status = "Implemented"` without a corresponding test file.  
**Acceptance:** Test passes on current codebase; alerts on drift as paper evolves.

### PR 11 — Replace BibTeX TODO citations

**Files:** `paper/remora_paper.md`, `paper/remora_paper.tex`  
**Scope:** Replace all `[TODO: cite ...]` placeholders with real BibTeX citations. Priority: Wang et al. 2023 (self-consistency), Du et al. 2023 (multi-agent debate), Liang et al. 2023 (ensembles), Angelopoulos & Bates 2023 (conformal prediction), Vovk et al. 2005 (conformal theory), NIST AI RMF 2023.  
**Acceptance:** `grep "TODO: cite" remora_paper.tex` returns empty.

### PR 12 — Add risk_tier guard in ACCEPT path

**Files:** `remora/policy/decision_engine.py:129–180`  
**Scope:** In the ACCEPT routing path, add:
```python
if obs.risk_tier in ("high", "critical"):
    return GateDecision(gate="VERIFY", reason="risk_tier_requires_verification")
```
This prevents critical-risk actions from reaching ACCEPT regardless of phase.  
**Acceptance:** `test_policy_critical_risk_accept.py` asserts route ≠ ACCEPT for risk_tier="critical" in all phases.

### PR 13 — Add threading.Lock to CorrelationMatrix

**Files:** `remora/correlation.py`  
**Scope:** Add `self._lock = threading.Lock()` in `__init__`. Acquire lock in `observe()` around deque creation and append. Use `with self._lock:` context manager.  
**Acceptance:** `test_correlation_thread_safety.py` runs 100 concurrent `observe()` calls; `sum(len(d) for d in matrix.values())` equals expected count.

---

## J. Quick Wins (Under 2 Hours)

These can be done immediately without architecture decisions:

| Item | File | Time | What to do |
|------|------|------|------------|
| QW1 | `remora/engine.py:115` | 20min | Add `timeout=15.0` to `future.result()`. One line. |
| QW2 | `remora/correlation.py` | 30min | Add `threading.Lock` to `CorrelationMatrix.observe()`. Three lines. |
| QW3 | `remora/correlation.py:106` | 20min | Detect tie in `weighted_consensus()`; log; return `tie=True`. |
| QW4 | `remora/policy/opa_adapter.py` | 30min | Add `risk_tier`, `domain`, `action_type` to the OPAContext dict. Three lines. |
| QW5 | `remora/engine.py` | 20min | Log sequential fallback with oracle_id and exception type. Two lines. |
| QW6 | ~~`paper/remora_paper.md`~~ | 45min | ✅ DONE — all citations verified, full author lists, correct titles and venues. |
| QW7 | ~~`paper/remora_paper.tex`~~ | 15min | ✅ DONE — Geifman title corrected, EU AI Act attribution fixed, all entries verified. |

---

## K. Before Public Paper Release Checklist

All items must be complete before submitting to arXiv or any workshop venue.

### Correctness
- [ ] **B1 fixed:** Per-oracle timeout implemented and tested (T1, T2)
- [ ] **B2 fixed:** Critical-risk ACCEPT path guarded (T3)
- [ ] **B6 fixed:** Tie detection in `weighted_consensus()` (T8)
- [ ] **B7 documented:** `claim_hash` bag-of-words limitation noted in paper and docstring
- [ ] **B8 fixed:** Sequential fallback logs oracle_id and exception type

### Paper Accuracy
- [x] All `[TODO: cite ...]` placeholders replaced with real BibTeX entries ✅
- [ ] Every claim in `paper/claim_ledger.md` has its recommended wording used verbatim in the paper
- [ ] "in-sample optimum" caveat appears in abstract, §10, and conclusion for the 88.8% result
- [ ] "oracle-proxy evidence signal" caveat appears before the 38.5%/100% precision claim in §7
- [ ] "synthetic adversarial benchmark" caveat appears for the 0% unsafe execution claim in §10
- [ ] "empirical, not formal Lyapunov theorem" appears for the 87.2% stability claim
- [ ] "tamper-evident, not tamper-proof" appears every time the audit chain is mentioned
- [ ] "N=32 real-oracle items" appears for the trust anticorrelation claim
- [ ] None of the "claims explicitly avoided" list appear in any form in the paper

### Benchmark
- [ ] PR10 claim ledger test runs clean: every evidence file exists and every JSON key is present
- [ ] Author-curated items (N=75) are identified by a metadata flag in the benchmark JSON
- [ ] Results section states that 13.8% of items are author-curated

### Implementation
- [ ] `AuditHashChain.verify()` called on startup; pipeline appends to chain on each assessment
- [ ] Frontend download JSON includes `"simulation": true` at root level
- [ ] History tab in ApprovalModal shows `[SIMULATED]` badge

### Reproducibility
- [ ] `requirements.txt` or `pyproject.toml` has pinned versions for all oracle client libraries
- [ ] `README.md` contains exact commands to reproduce N=500 selective trust result and N=700 tool-call result
- [ ] Seeded RNG values for benchmark generation are documented
- [ ] All `results/*.json` files are committed and hash-verified

---

## L. Before Enterprise Pilot Checklist

All items must be complete before presenting REMORA as an enterprise governance layer.

### Safety
- [ ] B1 fixed: per-oracle timeout
- [ ] B2 fixed: critical-risk ACCEPT path
- [ ] B3 fixed: risk_tier/domain in OPAContext
- [ ] B5 fixed: CorrelationMatrix thread safety
- [ ] B9 fixed: min_valid_oracles policy
- [ ] T1–T7 tests passing

### Audit
- [ ] JSONLAudit integrated into main pipeline (PR 5)
- [ ] Audit JSONL verified on startup
- [ ] PostgreSQL or D1 audit adapter configured for append-only storage
- [ ] Audit chain `verify()` exposed as a health-check endpoint

### Evidence
- [ ] Live BM25/NLI retrieval wired as EvidenceSignal source (not oracle-proxy)
- [ ] Real evidence retrieval tested on domain-specific corpus (not MultiNLI)
- [ ] Evidence latency p95 documented

### Governance
- [ ] OPA Rego policies written and tested for the target domain (risk_tier, domain, action_type)
- [ ] OPA server deployment documented (Kubernetes sidecar or external policy service)
- [ ] Hard block override audit log: every block 1–7 firing recorded with reason

### Infrastructure
- [ ] `oracle_timeout_s` configurable per deployment environment
- [ ] API keys managed via secrets manager (Vault, Azure Key Vault, or equivalent)
- [ ] Rate limiting on oracle endpoints with circuit breaker

### Legal and Compliance
- [ ] Paper disclaimers reviewed: prototype, not production-certified safety system
- [ ] No "REMORA guarantees safety" in any external communication
- [ ] Audit chain backup and retention policy documented
- [ ] GDPR: audit logs contain only metadata, not payload content (or DPA in place)

---

## M. Final Recommendation

REMORA is a technically honest, architecturally coherent research prototype with genuine novelty in its thermodynamic uncertainty framing, phase-stratified conformal calibration, and policy-hard-block architecture. The code review reveals that the core claims are implemented and the empirical results are real — this is not a demo masquerading as a system.

**Three changes are required before the paper can be published without scientific risk:**

1. Fix the per-oracle timeout (one line — B1). Without this, the correctness claim for parallel fan-out is invalidated under any network fault.
2. Guard the ACCEPT path against critical-risk tier (five lines — B2/PR12). Without this, the 0% unsafe execution claim implicitly assumes all critical actions arrive in critical phase, which cannot be guaranteed.
3. ~~Write the held-out evaluation (H10).~~ ✅ **DONE** — `results/selective_n500_holdout_results.json` provides a 20% stratified holdout: 88.0% accuracy, n_accepted=25, τ*=0.2032, Wilson CI [70.0, 95.8%], p=1.45×10⁻⁵.

**Two changes are required before any enterprise discussion:**

4. Export risk_tier/domain/action_type to OPAContext (PR4). Without this, OPA policies written by enterprise operators will silently fail to fire on risk-based rules.
5. Wire the audit hash-chain into the main pipeline (PR5). Without this, the tamper-evident audit claim is aspirational, not operational.

The north-star sentence applies precisely here: REMORA is a clear research prototype for gated agentic AI. The five fixes above close the gap between what the paper claims and what the code delivers. After those five fixes, the paper can be submitted and the codebase can be open-sourced with integrity.

---

*Report generated from static analysis of commit 26e84d7, main branch, 2026-05-30.*  
*All file references are to `C:\Users\Stian\REMORA\` unless otherwise noted.*
